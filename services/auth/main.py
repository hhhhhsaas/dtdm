"""
=============================================================================
auth-service — Identity & Access Management        Cổng 8001  |  db_auth
=============================================================================

Nhiệm vụ: đăng nhập, phát hành/thu hồi token, quản lý tài khoản, phân quyền.

Đặc điểm kiến trúc đáng chú ý:
  1. KHÔNG lưu mật khẩu gốc — chỉ lưu Argon2id hash
  2. Refresh token lưu dạng hash SHA-256 → DB bị lấy cũng không dùng được
  3. Chống brute-force: khóa tài khoản sau 5 lần sai trong 15 phút
  4. Ghi LoginAttempt cho MỌI lần thử → phát hiện & điều tra được
  5. AuditLog cho mọi thao tác quản trị (R6)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitExceeded,
    UnauthorizedError,
    create_access_token,
    create_refresh_token,
    create_service_app,
    get_current_user,
    get_db,
    get_event_bus,
    hash_password,
    hash_token,
    require_roles,
    verify_password,
)
from common.events import DomainEvent, IdempotentConsumer
from common.security import CurrentUser, Role
from common.telemetry import (
    get_request_id,
)
from models import AuditLog, LoginAttempt, RefreshToken, User
from schemas import (
    LoginRequest,
    MessageResponse,
    PasswordChange,
    RefreshRequest,
    RoleAssignment,
    TokenResponse,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)

logger = logging.getLogger(__name__)

# ===========================================================================
#  CẤU HÌNH BẢO MẬT
# ===========================================================================
MAX_FAILED_LOGINS = 5           # số lần sai trước khi khóa
LOCK_DURATION_MINUTES = 15      # thời gian khóa
MAX_SESSIONS_PER_USER = 5      # số phiên đồng thời tối đa
LOGIN_WINDOW_MINUTES = 15      # cửa sổ thống kê lần sai

# ===========================================================================
#  CONSUMER — định nghĩa TRƯỚC khi tạo app
# ===========================================================================
# create_service_app() nhận `lifespan_extra` và sẽ gọi hàm này trong
# vòng đời ứng dụng. Vì vậy phải định nghĩa handler TRƯỚC khi gọi factory —
# ngược lại sẽ NameError lúc import module.
async def _on_user_registered(event: DomainEvent) -> None:
    """
    Nhận event user.registered.

    Hiện chỉ ghi log — chỗ gửi email chào mừng thuộc notification-service
    (auth KHÔNG biết SMTP, biết template, biết lịch gửi). Giữ lại consumer
    này vì auth cần một hàng đợi riêng cho các event về danh tính: khi sau này
    thêm "gửi mã đặt lại mật khẩu" thì chỉ thêm handler, không đổi hạ tầng.
    """
    logger.info("👋 Nhận user.registered: %s (%s)",
                event.data.get("username"), event.event_id)


async def _setup_consumer(app_instance) -> None:
    """Đăng ký consumer sau khi service đã khởi động (event bus sẵn sàng)."""
    consumer = IdempotentConsumer(
        handler=_on_user_registered,
        consumer_name="auth-service:user-registered",
    )
    app_instance.state.ctx.consumers.append(consumer)
    try:
        await get_event_bus().subscribe(
            "qlpt.user.events", consumer.handle, ["user.registered"]
        )
    except Exception as exc:
        logger.warning("Không đăng ký consumer được: %s", exc)


app = create_service_app(
    name="auth-service",
    description=(
        "**Xác thực & phân quyền**\n\n"
        "- Đăng nhập / đăng xuất / làm mới token\n"
        "- Quản lý tài khoản (ADMIN)\n"
        "- Phân quyền RBAC 3 vai trò: ADMIN / MANAGER / TENANT\n\n"
        "### Bảo mật\n"
        "- Mật khẩu lưu dạng Argon2id\n"
        "- Refresh token lưu dạng hash SHA-256\n"
        "- Khóa tài khoản sau 5 lần đăng nhập sai\n"
        "- Audit log mọi thao tác quản trị"
    ),
    version="1.0.0",
    lifespan_extra=_setup_consumer,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])
users_router = APIRouter(prefix="/api/v1/users", tags=["users"])


# ===========================================================================
#  HELPER
# ===========================================================================
def _client_ip(request: Request) -> str:
    """
    Lấy IP thật của client.

    ⭐ nginx PHẢI truyền X-Forwarded-For. Nếu không có, ta dùng X-Real-IP,
    rồi mới fallback về IP của chính nginx (không chính xác nhưng còn hơn).
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.headers.get("X-Real-IP", request.client.host if request.client else "unknown")


#: Refresh token của trình duyệt nằm trong cookie HttpOnly — JavaScript không
#: đọc được, nên lỗ XSS không lấy được phiên dài hạn. Chỉ gửi kèm các request
#: tới /api/v1/auth (Path), không gửi cross-site (SameSite=Strict).
REFRESH_COOKIE = "qlpt_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _wants_cookie(request: Request) -> bool:
    """
    Web đánh dấu bằng header riêng. Script/CLI (smoke test, Makefile) không gửi
    header này nên vẫn nhận refresh token trong body như cũ.

    ⭐ Header tùy biến cũng là chốt chống CSRF: form từ site khác không đặt
       được header, nên không thể dùng cookie để gọi /auth/refresh hộ.
    """
    return request.headers.get("X-Token-Transport") == "cookie"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE, token, max_age=app_settings_refresh_days() * 86400,
        path=REFRESH_COOKIE_PATH, secure=True, httponly=True, samesite="strict",
    )


def _refresh_from(request: Request, payload: RefreshRequest | None) -> str | None:
    if payload and payload.refresh_token:
        return payload.refresh_token
    return request.cookies.get(REFRESH_COOKIE) if _wants_cookie(request) else None


async def _record_attempt(
    session: AsyncSession, request: Request, username: str,
    user_id: uuid.UUID | None, success: bool, reason: str | None = None,
) -> None:
    session.add(LoginAttempt(
        user_id=user_id, username_attempted=username[:50],
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("User-Agent") or "")[:255],
        success=success, failure_reason=reason,
    ))


async def _count_recent_failures(session: AsyncSession, username: str) -> int:
    since = datetime.now(UTC) - timedelta(minutes=LOGIN_WINDOW_MINUTES)
    result = await session.execute(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.username_attempted == username,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since,
        )
    )
    return result.scalar() or 0


async def _audit(
    session: AsyncSession, request: Request,
    actor: CurrentUser | None, action: str,
    resource_type: str, resource_id: str | None = None,
    before: dict | None = None, after: dict | None = None,
) -> None:
    session.add(AuditLog(
        actor_id=actor.id if actor else None,
        actor_username=actor.username if actor else None,
        actor_role=actor.role.value if actor else None,
        action=action, resource_type=resource_type, resource_id=resource_id,
        before=before, after=after,
        ip_address=_client_ip(request),
        request_id=get_request_id(),
    ))


async def _revoke_old_sessions(session: AsyncSession, user: uuid.UUID) -> None:
    """
    Giới hạn số phiên đồng thời.

    ⭐ Tính năng quan trọng: nếu không giới hạn, kẻ tấn công có thể đăng nhập
    bằng mật khẩu bị lộ và mở hàng trăm phiên. Giới hạn buộc attacker chỉ
    giữ được vài phiên → dễ phát hiện.
    """
    active = (await session.execute(
        select(RefreshToken)
        .where(RefreshToken.user_id == user, RefreshToken.revoked_at.is_(None))
        .order_by(RefreshToken.created_at.desc())
    )).scalars().all()

    if len(active) >= MAX_SESSIONS_PER_USER:
        now = datetime.now(UTC)
        for old in active[: len(active) - MAX_SESSIONS_PER_USER + 1]:
            old.revoked_at = now
        logger.info("Đã thu hồi %d phiên cũ của user %s",
                    len(active) - MAX_SESSIONS_PER_USER + 1, user)


# ===========================================================================
#  AUTH
# ===========================================================================
@router.post("/auth/login", response_model=TokenResponse,
             summary="Đăng nhập", tags=["auth"])
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """
    Đăng nhập bằng username hoặc email.

    **Lưu ý bảo mật:** thông báo lỗi cố ý KHÔNG phân biệt "sai mật khẩu"
    với "không tồn tại tài khoản" — nếu phân biệt, attacker có thể dò
    xem username nào tồn tại.
    """
    identifier = payload.username.strip()

    user = (await session.execute(
        select(User).where(
            (User.username == identifier) | (User.email == identifier.lower())
        )
    )).scalar_one_or_none()

    # --- Kiểm tra khóa ---
    if user and user.is_locked and user.locked_until:
        if user.locked_until > datetime.now(UTC):
            remaining = int((user.locked_until - datetime.now(UTC)).total_seconds() // 60) + 1
            await _record_attempt(session, request, identifier, user.id, False, "ACCOUNT_LOCKED")
            await session.commit()
            raise RateLimitExceeded(
                f"Tài khoản đang bị khóa. Thử lại sau {remaining} phút."
            )
        # Đã hết thời gian khóa → mở khóa
        user.is_locked = False
        user.failed_login_count = 0
        logger.info("🔓 Tự động mở khóa tài khoản %s", user.username)

    # --- Sai thông tin ---
    if not user or not verify_password(payload.password, user.password_hash):
        reason = "INVALID_PASSWORD" if user else "USER_NOT_FOUND"
        await _record_attempt(session, request, identifier, user.id if user else None,
                              False, reason)
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.is_locked = True
                user.locked_until = (datetime.now(UTC)
                                     + timedelta(minutes=LOCK_DURATION_MINUTES))
                logger.warning(
                    "🔒 KHÓA tài khoản %s sau %s lần đăng nhập sai",
                    user.username, user.failed_login_count,
                )
        # ⭐ COMMIT TRƯỚC KHI RAISE: get_db rollback mọi thứ khi có exception.
        #    Không commit thì failed_login_count/is_locked/LoginAttempt bị huỷ
        #    → khoá tài khoản không bao giờ có hiệu lực, dò mật khẩu vô hạn.
        await session.commit()
        # Thông báo chung chung — không tiết lộ tài khoản có tồn tại không
        raise UnauthorizedError("Sai tên đăng nhập hoặc mật khẩu")

    # --- Tài khoản bị vô hiệu hóa ---
    if not user.is_active:
        await _record_attempt(session, request, identifier, user.id, False, "INACTIVE")
        await session.commit()
        raise PermissionDeniedError(
            "Tài khoản đã bị vô hiệu hóa. Liên hệ quản trị viên."
        )

    # --- Thành công ---
    user.failed_login_count = 0
    user.last_login_at = datetime.now(UTC)
    await _record_attempt(session, request, identifier, user.id, True)
    await _revoke_old_sessions(session, user.id)

    access_token = create_access_token(
        user.id, user.username, Role(user.role), user.property_id
    )
    refresh_raw = create_refresh_token(user.id)

    session.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_raw),
        expires_at=datetime.now(UTC)
        + timedelta(days=app_settings_refresh_days()),
        user_agent=(request.headers.get("User-Agent") or "")[:255],
        ip_address=_client_ip(request),
    ))

    # Phát event → notification-service chào mừng người dùng mới / cảnh báo đăng nhập
    try:
        await get_event_bus().publish(session, DomainEvent(
            event_type="user.logged_in",
            data={
                "user_id": str(user.id), "username": user.username,
                "role": user.role, "ip": _client_ip(request),
            },
        ))
    except Exception as exc:
        logger.warning("Không phát được event user.logged_in: %s", exc)

    logger.info("✅ %s đăng nhập thành công (IP %s)", user.username, _client_ip(request))
    if _wants_cookie(request):
        _set_refresh_cookie(response, refresh_raw)
    return TokenResponse(
        access_token=access_token,
        refresh_token="" if _wants_cookie(request) else refresh_raw,
        expires_in=app_settings_access_seconds(),
        user=UserResponse.model_validate(user),
    )


def app_settings_refresh_days() -> int:
    from common.config import settings
    return settings.refresh_token_ttl_days


def app_settings_access_seconds() -> int:
    from common.config import settings
    return settings.access_token_ttl_minutes * 60


@router.post("/auth/refresh", response_model=TokenResponse,
             summary="Làm mới access token")
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    payload: RefreshRequest | None = None,
) -> TokenResponse:
    """
    Đổi refresh token lấy access token mới.

    Bảo mật: **token cũ bị thu hồi ngay** sau khi dùng. Nếu không thu hồi,
    refresh token bị đánh cắp vẫn dùng được vô hạn lần.
    """
    raw = _refresh_from(request, payload)
    if not raw or "." not in raw:
        raise UnauthorizedError("Định dạng refresh token không hợp lệ")

    user_id_str, _ = raw.split(".", 1)
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as exc:
        # `from None`: người dùng KHÔNG cần biết refresh token sai ở đâu —
        # thông báo chi tiết chỉ giúp kẻ tấn công đoán. Giữ chuỗi lỗi gốc
        # trong log nội bộ là đủ.
        raise UnauthorizedError("Refresh token không hợp lệ") from exc

    stored = (await session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.token_hash == hash_token(raw),
        )
    )).scalar_one_or_none()

    if not stored or not stored.is_valid:
        raise UnauthorizedError("Refresh token không hợp lệ hoặc đã hết hạn")

    user = await session.get(User, user_id)
    if not user or not user.is_active or user.is_locked:
        raise UnauthorizedError("Tài khoản không còn hợp lệ")

    # Thu hồi token cũ (rotation)
    stored.revoked_at = datetime.now(UTC)

    access_token = create_access_token(user.id, user.username, Role(user.role), user.property_id)
    new_refresh = create_refresh_token(user.id)
    session.add(RefreshToken(
        user_id=user.id, token_hash=hash_token(new_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=app_settings_refresh_days()),
        user_agent=(request.headers.get("User-Agent") or "")[:255],
        ip_address=_client_ip(request),
    ))

    if _wants_cookie(request):
        _set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=access_token,
        refresh_token="" if _wants_cookie(request) else new_refresh,
        expires_in=app_settings_access_seconds(),
        user=UserResponse.model_validate(user),
    )


@router.post("/auth/logout", response_model=MessageResponse,
             summary="Đăng xuất")
async def logout(
    request: Request,
    response: Response,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    payload: RefreshRequest | None = None,
) -> MessageResponse:
    """Thu hồi refresh token. Access token sẽ tự hết hạn sau ≤15 phút."""
    raw = _refresh_from(request, payload)
    stored = (await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
    )).scalar_one_or_none() if raw else None

    if stored and stored.user_id == user.id:
        stored.revoked_at = datetime.now(UTC)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH,
                           secure=True, httponly=True, samesite="strict")

    # Đưa JTI của access token vào denylist Redis → vô hiệu hóa NGAY LẬP TỨC
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        from common.security import decode_token
        try:
            payload_jwt = decode_token(
                request.headers.get("Authorization", "").replace("Bearer ", "", 1)
            )
            await redis.setex(
                f"revoked:jti:{payload_jwt.jti}", 3600, "1"
            )
        except Exception:
            pass  # access token sẽ tự hết hạn, không nghiêm trọng

    return MessageResponse(message="Đã đăng xuất thành công")


@router.get("/auth/me", response_model=UserResponse, summary="Thông tin người dùng hiện tại")
async def me(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    # ⭐ KHÔNG dựng UserResponse từ claims trong token: token chỉ mang
    #   id/username/role/property_id, thiếu email/full_name/is_active… →
    #   ResponseValidationError (500). Phải đọc bản ghi đầy đủ từ DB.
    db_user = await session.get(User, user.id)
    if not db_user:
        raise NotFoundError("Không tìm thấy người dùng")
    return UserResponse.model_validate(db_user)


@router.post("/auth/change-password", response_model=MessageResponse,
             summary="Đổi mật khẩu")
async def change_password(
    payload: PasswordChange,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    db_user = await session.get(User, user.id)
    if not db_user:
        raise NotFoundError("Không tìm thấy người dùng")

    if not verify_password(payload.old_password, db_user.password_hash):
        raise BusinessRuleError("Mật khẩu cũ không đúng")

    db_user.password_hash = hash_password(payload.new_password)
    db_user.password_changed_at = datetime.now(UTC)

    # ⭐ Thu hồi TẤT CẢ phiên sau khi đổi mật khẩu.
    # Nếu mật khẩu bị lộ, việc đổi mật khẩu phải cắt đứt ngay mọi phiên
    # của kẻ tấn công — nếu không, chúng vẫn truy cập được.
    now = datetime.now(UTC)
    active = (await session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
        )
    )).scalars().all()
    for t in active:
        t.revoked_at = now

    await _audit(session, request, user, "CHANGE_PASSWORD", "user", str(user.id))
    logger.info("🔑 %s đổi mật khẩu, thu hồi %d phiên", user.username, len(active))
    return MessageResponse(
        message=f"Đổi mật khẩu thành công. {len(active)} phiên cũ đã bị thu hồi."
    )


# ===========================================================================
#  QUẢN LÝ NGƯỜI DÙNG (ADMIN)
# ===========================================================================
@users_router.get("", response_model=UserListResponse, summary="Danh sách người dùng")
async def list_users(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str | None = None,
    search: str | None = None,
) -> UserListResponse:
    """Chỉ ADMIN được xem toàn bộ danh sách."""
    stmt = select(User).where(User.deleted_at.is_(None))
    if role:
        stmt = stmt.where(User.role == role)
    if search:
        like = f"%{search}%"
        stmt = stmt.where((User.username.ilike(like)) | (User.full_name.ilike(like))
                          | (User.email.ilike(like)))

    total = (await session.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0

    rows = (await session.execute(
        stmt.order_by(User.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in rows],
        total=total, page=page, page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


@users_router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
                   summary="Tạo tài khoản")
async def create_user(
    payload: UserCreate,
    request: Request,
    admin: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    exists = (await session.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    )).scalar_one_or_none()
    if exists:
        raise ConflictError("Tên đăng nhập hoặc email đã được sử dụng")

    # Ràng buộc: MANAGER bắt buộc phải có property_id
    if payload.role == "MANAGER" and not payload.property_id:
        raise BusinessRuleError("Quản lý phải được gán vào một cơ sở nhà trọ")

    user = User(
        username=payload.username, email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name, phone=payload.phone,
        role=payload.role, property_id=payload.property_id,
    )
    session.add(user)
    await session.flush()

    await _audit(session, request, admin, "CREATE_USER", "user",
                 str(user.id), after={"username": user.username, "role": user.role})
    await get_event_bus().publish(session, DomainEvent(
        event_type="user.registered",
        data={
            "user_id": str(user.id), "username": user.username,
            "email": user.email, "full_name": user.full_name, "role": user.role,
        },
    ))

    logger.info("➕ ADMIN tạo tài khoản %s (%s)", user.username, user.role)
    return UserResponse.model_validate(user)


@users_router.get("/{user_id}", response_model=UserResponse, summary="Chi tiết người dùng")
async def get_user(
    user_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """
    Quyền đọc:
      - ADMIN: tất cả
      - MANAGER: tài khoản trong cơ sở mình
      - TENANT: chỉ chính mình
    """
    if user.role is Role.TENANT and user.id != user_id:
        raise PermissionDeniedError("Bạn chỉ có thể xem thông tin của chính mình")
    if user.role is Role.MANAGER:
        target = await session.get(User, user_id)
        if target and target.property_id and str(target.property_id) != str(user.property_id):
            raise PermissionDeniedError("Không có quyền xem người dùng của cơ sở khác")

    db_user = await session.get(User, user_id)
    if not db_user or db_user.deleted_at:
        raise NotFoundError("Không tìm thấy người dùng")
    return UserResponse.model_validate(db_user)


@users_router.patch("/{user_id}", response_model=UserResponse, summary="Cập nhật người dùng")
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    request: Request,
    admin: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    db_user = await session.get(User, user_id)
    if not db_user or db_user.deleted_at:
        raise NotFoundError("Không tìm thấy người dùng")

    before = db_user.to_dict(exclude={"password_hash"})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(db_user, field, value)
    await session.flush()

    await _audit(session, request, admin, "UPDATE_USER", "user", str(user_id),
                 before=before, after=db_user.to_dict(exclude={"password_hash"}))
    return UserResponse.model_validate(db_user)


@users_router.put("/{user_id}/role", response_model=UserResponse, summary="Gán vai trò")
async def assign_role(
    user_id: uuid.UUID,
    payload: RoleAssignment,
    request: Request,
    admin: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    db_user = await session.get(User, user_id)
    if not db_user:
        raise NotFoundError("Không tìm thấy người dùng")

    if payload.role == "MANAGER" and not payload.property_id:
        raise BusinessRuleError("Quản lý phải được gán vào một cơ sở nhà trọ")
    if db_user.id == admin.id:
        raise BusinessRuleError("Không thể tự thay đổi vai trò của chính mình")

    before = {"role": db_user.role, "property_id": str(db_user.property_id)}
    db_user.role = payload.role
    db_user.property_id = payload.property_id
    await session.flush()

    await _audit(session, request, admin, "ASSIGN_ROLE", "user", str(user_id),
                 before=before, after={"role": db_user.role,
                                       "property_id": str(db_user.property_id)})
    logger.info("🔄 ADMIN đổi vai trò %s: %s → %s", db_user.username, before["role"], payload.role)
    return UserResponse.model_validate(db_user)


@users_router.delete("/{user_id}", response_model=MessageResponse,
                     summary="Vô hiệu hóa tài khoản (soft delete)")
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    admin: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """
    ⭐ SOFT DELETE (R7) — không xóa hẳn.

    Vì sao: hóa đơn/hợp đồng tham chiếu tới user. Xóa hẳn sẽ phá vỡ
    lịch sử tài chính — vấn đề nghiêm trọng về kế toán.
    """
    db_user = await session.get(User, user_id)
    if not db_user:
        raise NotFoundError("Không tìm thấy người dùng")
    if db_user.id == admin.id:
        raise BusinessRuleError("Không thể tự vô hiệu hóa tài khoản của chính mình")

    db_user.is_active = False
    now = datetime.now(UTC)
    for t in (await session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id,
                                   RefreshToken.revoked_at.is_(None))
    )).scalars().all():
        t.revoked_at = now

    await _audit(session, request, admin, "DEACTIVATE_USER", "user", str(user_id))
    logger.info("🚫 ADMIN vô hiệu hóa tài khoản %s", db_user.username)
    return MessageResponse(
        message=f"Đã vô hiệu hóa tài khoản {db_user.username} và thu hồi mọi phiên đăng nhập"
    )


# ===========================================================================
#  ĐĂNG KÝ ROUTER
# ===========================================================================
app.include_router(router)
app.include_router(users_router)
