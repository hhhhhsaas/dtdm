"""
Bảo mật: băm mật khẩu, JWT, RBAC.

Vì sao Argon2id chứ không phải MD5/SHA1?
  MD5/SHA1: thiết kế để NHANH → brute force dễ dàng với GPU hiện đại
  bcrypt: chậm cố ý, nhưng giới hạn 72 byte đầu vào
  Argon2id: chậm + chống tấn công kênh bên (side-channel) + không giới hạn độ dài
             → lựa chọn tốt nhất hiện nay (OWASP khuyến nghị)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Băm mật khẩu
# ---------------------------------------------------------------------------
_hasher = PasswordHasher(
    time_cost=3,         # số vòng lặp
    memory_cost=65536,   # 64 MB bộ nhớ
    parallelism=4,       # số luồng
    hash_len=32,
    salt_len=16,
)


def hash_password(plain: str) -> str:
    """Băm mật khẩu. Argon2id tự sinh salt ngẫu nhiên mỗi lần."""
    if len(plain) < 8:
        raise ValueError("Mật khẩu phải có ít nhất 8 ký tự")
    if len(plain) > 256:
        raise ValueError("Mật khẩu quá dài (tối đa 256 ký tự)")
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Kiểm tra mật khẩu. Luôn trả False thay vì ném exception."""
    try:
        _hasher.verify(hashed, plain)
        return True
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Phát hiện mật khẩu đã lưu bằng tham số cũ → cần băm lại."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def hash_token(token: str) -> str:
    """
    Băm refresh token trước khi lưu vào DB.

    ⭐ Nếu DB bị lấy (SQL injection, sao lưu rò rỉ), attacker có token ĐÃ BĂM
    nên không dùng được để đăng nhập. So sánh hợp lệ bằng so sánh thời gian cố định.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    """So sánh chống rò rỉ thời gian (timing attack)."""
    return secrets.compare_digest(a, b)


# ---------------------------------------------------------------------------
#  Vai trò
# ---------------------------------------------------------------------------
class Role(str, Enum):
    ADMIN = "ADMIN"        # chủ nhà — toàn quyền
    MANAGER = "MANAGER"    # quản lý trọ — vận hành hằng ngày
    TENANT = "TENANT"      # người thuê — chỉ dữ liệu của mình
    SYSTEM = "SYSTEM"      # job nền, không đăng nhập

    @property
    def level(self) -> int:
        return {"TENANT": 1, "MANAGER": 2, "ADMIN": 3, "SYSTEM": 4}[self.value]


# ---------------------------------------------------------------------------
#  Token
# ---------------------------------------------------------------------------
class TokenPayload(BaseModel):
    sub: uuid.UUID                      # user id
    username: str
    role: Role
    property_id: uuid.UUID | None = None   # ⭐ ràng buộc multi-tenant
    exp: datetime
    iat: datetime
    iss: str = "qlpt-auth-service"
    jti: str = Field(default_factory=lambda: str(uuid.uuid4()))


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def _create_jwt(payload: dict, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    body = {
        **payload,
        "iat": now,
        "exp": now + ttl,
        "iss": settings.jwt_issuer,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        body,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(
    user_id: uuid.UUID | str,
    username: str,
    role: Role,
    property_id: uuid.UUID | str | None = None,
) -> str:
    """
    Access token sống NGẮN (15 phút).

    Vì sao ngắn? Mục đích: giảm thời gian mà một token bị lộ vẫn dùng được.
    Đánh đổi: phải refresh thường xuyên → nhưng đó là chấp nhận được
    so với việc token sống 7 ngày.
    """
    return _create_jwt(
        {
            "sub": str(user_id),
            "username": username,
            "role": role.value if isinstance(role, Role) else role,
            "property_id": str(property_id) if property_id else None,
            "typ": "access",
        },
        timedelta(minutes=settings.access_token_ttl_minutes),
    )


def create_refresh_token(user_id: uuid.UUID | str) -> str:
    """Refresh token sống DÀI (7 ngày) — chỉ dùng để lấy access token mới."""
    token = secrets.token_urlsafe(48)   # 48 byte entropy = 384 bit, rất mạnh
    return f"{user_id}.{token}"


def create_internal_token(caller: str | None = None) -> str:
    """
    ⭐ Token nội bộ (role=SYSTEM) cho các lời gọi service-to-service.

    Vì sao cần: các endpoint `/internal/v1/...` đều bắt buộc
    `require_roles(Role.SYSTEM)`. Nếu không có cơ chế này thì chúng chỉ có
    thể truy cập bằng tay qua `curl` — tức là trong hệ thống đang chạy,
    KHÔNG service nào gọi được service nào, và mọi luồng nghiệp vụ cần
    đọc chéo dữ liệu đều chết. Đó là hệ quả của việc tách 8 database.

    ⭐ `sub` PHẢI là UUID hợp lệ vì `decode_token` ép
       `uuid.UUID(payload["sub"])`. Ta dùng `uuid5` (UUID TẤT ĐỊNH từ tên)
       thay vì `uuid4` nên cùng một service luôn mang cùng một `sub` — khi
       đọc log truy vết thấy `sub` là biết ngay ai gọi, không cần tra bảng.
    """
    name = caller or settings.service_name
    return create_access_token(
        user_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"qlpt-service.{name}"),
        username=f"system:{name}",
        role=Role.SYSTEM,
    )


def decode_token(token: str, expected_type: str = "access") -> TokenPayload:
    """
    Giải mã & kiểm tra JWT.

    Kiểm tra: chữ ký đúng, chưa hết hạn, đúng issuer, đúng loại token.
    Bắt buộc verify_exp=True — không bao giờ tắt kiểm tra hạn.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token không hợp lệ hoặc đã hết hạn",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub", "iat"], "verify_exp": True},
        )
    except jwt.ExpiredSignatureError as exc:
        logger.info("JWT đã hết hạn")
        # `from exc` giữ chuỗi nhân quả trong log, còn HTTPException trả về
        # cho client vẫn là câu "Thông tin xác thực không hợp lệ" chung chung —
        # phân biệt "hết hạn" với "sai chữ ký" giúp kẻ tấn công dò cấu trúc.
        raise credentials_error from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT không hợp lệ: %s", type(exc).__name__)
        raise credentials_error from exc

    # Chặn nhầm: dùng refresh token gọi API thường
    if payload.get("typ") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Cần token loại '{expected_type}'",
        )

    return TokenPayload(
        sub=uuid.UUID(payload["sub"]),
        username=payload.get("username", ""),
        role=Role(payload["role"]),
        property_id=uuid.UUID(payload["property_id"]) if payload.get("property_id") else None,
        exp=payload["exp"],
        iat=payload["iat"],
        iss=payload.get("iss", settings.jwt_issuer),
        jti=payload.get("jti", ""),
    )


# ---------------------------------------------------------------------------
#  Dependency: lấy user hiện tại
# ---------------------------------------------------------------------------
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


class CurrentUser(BaseModel):
    """Thông tin người dùng đã xác thực, gắn vào request."""

    id: uuid.UUID
    username: str
    role: Role
    property_id: uuid.UUID | None

    @property
    def level(self) -> int:
        return self.role.level

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def can_manage(self) -> bool:
        """Có quyền vận hành (admin hoặc manager)?"""
        return self.role.level >= Role.MANAGER.level

    def assert_property_access(self, property_id: uuid.UUID | str | None) -> None:
        """
        ⭐ Kiểm tra RÀNG BUỘC MULTI-TENANT.

        ADMIN không bị giới hạn (quản trị nhiều cơ sở).
        MANAGER chỉ được truy cập đúng cơ sở được gán.
        Đây là hàng rào BẢO MẬT quan trọng nhất trong hệ thống nhiều chủ nhà —
        nếu thiếu, MANAGER của nhà trọ A có thể xem dữ liệu nhà trọ B.
        """
        if self.is_admin or self.role is Role.SYSTEM:
            return
        if property_id is None:
            return
        if self.property_id is None or str(self.property_id) != str(property_id):
            logger.warning(
                "Chặn truy cập chéo cơ sở: user=%s role=%s cố đọc property=%s",
                self.username, self.role.value, property_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền truy cập dữ liệu của cơ sở này",
            )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> CurrentUser:
    """
    Lấy user từ Bearer token.

    Ngoài xác thực, còn kiểm tra DENYLIST trong Redis — cho phép thu hồi
    access token ngay lập tức khi tài khoản bị khóa (không chờ hết 15 phút).
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu token xác thực",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials, expected_type="access")

    # --- Kiểm tra denylist (token đã thu hồi) ---
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            if await redis.exists(f"revoked:jti:{payload.jti}"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token đã bị thu hồi",
                )
        except HTTPException:
            raise
        except Exception as exc:  # Redis lỗi → KHÔNG chặn người dùng
            logger.warning("Không kiểm tra được denylist Redis: %s", exc)

    return CurrentUser(
        id=payload.sub,
        username=payload.username,
        role=payload.role,
        property_id=payload.property_id,
    )


# ---------------------------------------------------------------------------
#  Dependency: phân quyền theo vai trò
# ---------------------------------------------------------------------------
def require_roles(*allowed: Role) -> Callable:
    """
    Tạo dependency kiểm tra vai trò.

    Dùng:  @router.post("/", dependencies=[Depends(require_roles(Role.ADMIN))])

    Lỗi thường gặp: đặt dependency ở router mà quên khai báo trên từng endpoint.
    Cách an toàn hơn: gắn vào router, KHÔNG dùng to_app dependency chung.
    """
    allowed_set = set(allowed)

    async def _checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed_set:
            logger.warning(
                "Từ chối truy cập: user=%s role=%s cần=%s",
                user.username, user.role.value, [r.value for r in allowed_set],
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Chỉ {', '.join(r.value for r in allowed)} được phép thực hiện "
                    f"thao tác này. Vai trò của bạn: {user.role.value}"
                ),
            )
        return user

    return _checker


# 依赖 shorthand — dùng cho type annotation
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


# ---------------------------------------------------------------------------
#  Rate limiting dựa trên Redis
# ---------------------------------------------------------------------------
async def rate_limit(
    request: Request,
    user: CurrentUserDep,
    limit: int = 100,
    window: int = 60,
) -> None:
    """
    Giới hạn số request theo user (sliding window đơn giản qua Redis INCR + EXPIRE).

    Nếu Redis không khả dụng → cho qua. Lý do: rate limit là biện pháp bảo vệ,
    KHÔNG được biến thành điểm yếu (single point of failure).
    """
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return

    key = f"ratelimit:{user.id}:{request.url.path}"
    try:
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        count, _ = await pipe.execute()

        if count > limit:
            ttl = await redis.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Vượt quá giới hạn {limit} request/{window}s. Thử lại sau {ttl}s",
                headers={"Retry-After": str(ttl)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Rate limit check lỗi (cho qua): %s", exc)


# Nhập ở cuối để tránh circular import
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402
