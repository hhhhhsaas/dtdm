"""
================================================================================
tenant-service — Hồ sơ người thuê.        Cổng 8003  |  db_tenant
================================================================================

Ba điểm đáng chú ý:
  1. CCCD ĐƯỢC MÃ HÓA + CHE KHI TRẢ VỀ — xem `common/crypto.py`.
  2. MỌI THAY ĐỔI HỒ SƠ ĐỀU GHI VÀO `tenant_history` (append-only) — bằng
     chứng khi có tranh chấp, không phải log kỹ thuật.
  3. KHÔNG GIỮ "ai đang thuê ở đâu" làm nguồn chuẩn — thứ đó thuộc
     contract-service. Ở đây chỉ giữ bản sao cập nhật qua event.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common import (
    BusinessRuleError,
    ConflictError,
    CurrentUser,
    MessageResponse,
    NotFoundError,
    PageParams,
    Role,
    apply_sort,
    create_service_app,
    get_db,
    get_event_bus,
    paginate,
    record_business_event,
    require_roles,
)
from common.config import settings
from common.crypto import blind_index
from common.database import session_scope
from common.events import DomainEvent, IdempotentConsumer
from common.telemetry import set_business_gauge
from models import Roommate, Tenant, TenantHistory
from schemas import (
    HistoryCreate,
    HistoryResponse,
    RoommateCreate,
    RoommateResponse,
    TenantCreate,
    TenantIdCardUpdate,
    TenantResponse,
    TenantSensitiveResponse,
    TenantStats,
    TenantSummary,
    TenantUpdate,
    TransferRequest,
)

logger = logging.getLogger(__name__)

# R1 — tối đa 3 người/phòng: 1 chủ hợp đồng + 2 bạn cùng phòng
MAX_OCCUPANTS_PER_ROOM = 3


# ===========================================================================
#  APP
# ===========================================================================
async def _setup_consumer(app_instance) -> None:
    consumer = IdempotentConsumer(
        handler=_handle_event, consumer_name="tenant-service:contract-events",
    )
    app_instance.state.ctx.consumers.append(consumer)
    try:
        await get_event_bus().subscribe(
            "qlpt.tenant.events", consumer.handle,
            ["contract.activated", "contract.terminated", "contract.expired"],
        )
    except Exception as exc:
        logger.warning("Không đăng ký consumer được: %s", exc)


app = create_service_app(
    name="tenant-service",
    description=(
        "**Hồ sơ người thuê**\n\n"
        "- Thông tin cá nhân, CCCD (mã hóa AES-256-GCM), liên hệ khẩn cấp\n"
        "- Bạn cùng phòng (tối đa 3 người/phòng)\n"
        "- Lịch sử thuê — append-only, dùng làm bằng chứng\n"
        "- Đánh giá rủi ro khách thuê\n\n"
        "### Quyền riêng tư\n"
        "- CCCD **không bao giờ** nằm trong response thông thường\n"
        "- Endpoint `/id-card` yêu cầu quyền quản lý và ghi audit log\n"
        "- Mọi lần đọc CCCD đều được ghi lại"
    ),
    version="1.0.0",
    lifespan_extra=_setup_consumer,
)


# ===========================================================================
#  HELPER
# ===========================================================================
def _to_response(tenant: Tenant) -> dict:
    """Chuyển model → dict, đảm bảo KHÔNG lọt CCCD đầy đủ ra ngoài."""
    return {
        "id": tenant.id,
        "property_id": tenant.property_id,
        "full_name": tenant.full_name,
        "date_of_birth": tenant.date_of_birth,
        "gender": tenant.gender,
        "phone": tenant.phone,
        "email": tenant.email,
        "address": tenant.address,
        "occupation": tenant.occupation,
        "id_card_masked": tenant.id_card_masked,
        "id_card_last4": tenant.id_card_last4,
        "emergency_contact_name": tenant.emergency_contact_name,
        "emergency_contact_phone": tenant.emergency_contact_phone,
        "zalo_oa_id": tenant.zalo_oa_id,
        "is_active": tenant.is_active,
        "risk_level": tenant.risk_level,
        "risk_note": tenant.risk_note,
        "current_room_id": tenant.current_room_id,
        "current_contract_id": tenant.current_contract_id,
        "created_at": tenant.created_at,
        "note": tenant.note,
    }


async def _get_tenant_or_404(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not tenant:
        raise NotFoundError(f"Không tìm thấy người thuê {tenant_id}")
    return tenant


async def _add_history(
    session: AsyncSession,
    tenant: Tenant,
    event_type: str,
    actor: CurrentUser | None = None,
    note: str | None = None,
    event_data: dict | None = None,
) -> None:
    """Ghi 1 dòng lịch sử. Append-only — không có đường sửa/xoá."""
    session.add(TenantHistory(
        tenant_id=tenant.id,
        property_id=tenant.property_id,
        room_id=tenant.current_room_id,
        event_type=event_type,
        event_data=event_data,
        actor_id=actor.id if actor else None,
        note=note,
    ))


async def _resolve_property_id(user: CurrentUser, requested: uuid.UUID | None) -> uuid.UUID | None:
    if user.is_admin:
        return requested
    if user.property_id is None:
        raise BusinessRuleError("Tài khoản chưa được gán vào cơ sở nào")
    if requested is not None and str(requested) != str(user.property_id):
        user.assert_property_access(requested)
    return user.property_id


# ===========================================================================
#  ROUTER: TENANT
# ===========================================================================
tenant_router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@tenant_router.get("", summary="Danh sách người thuê")
async def list_tenants(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    property_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    risk_level: str | None = None,
    search: str | None = Query(None, description="Tìm theo tên, số điện thoại hoặc email"),
    sort: str = "full_name_asc",
) -> dict:
    effective = await _resolve_property_id(user, property_id)

    stmt = select(Tenant).where(Tenant.deleted_at.is_(None))
    if effective:
        stmt = stmt.where(Tenant.property_id == effective)
    if room_id:
        stmt = stmt.where(Tenant.current_room_id == room_id)
    if is_active is not None:
        stmt = stmt.where(Tenant.is_active.is_(is_active))
    if risk_level:
        stmt = stmt.where(Tenant.risk_level == risk_level)
    if search:
        like = f"%{search}%"
        # Tìm theo tên / điện thoại / email.
        # ⭐ KHÔNG tìm theo CCCD ở đây: CCCD đã mã hóa nên không thể so khớp
        #   bằng `ilike`. Muốn tra trùng CCCD dùng endpoint chuyên biệt,
        #   vốn so khớp qua blind index.
        stmt = stmt.where(
            Tenant.full_name.ilike(like)
            | Tenant.phone.ilike(like)
            | Tenant.email.ilike(like)
        )

    stmt = apply_sort(
        stmt, Tenant, sort,
        allowed={"name": "full_name", "created": "created_at", "risk": "risk_level"},
        default="full_name",
    )

    items, meta = await paginate(session, stmt, params)
    return {
        "items": [TenantResponse(**_to_response(t)) for t in items],
        "meta": meta.model_dump(),
    }


@tenant_router.get("/summary", response_model=list[TenantSummary],
                    summary="Danh sách rút gọn (cho dropdown)")
async def list_tenant_summaries(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[TenantSummary]:
    """Endpoint nhẹ cho ô chọn trong form tạo hợp đồng — không phân trang,
    không trả thông tin phụ, chỉ những gì form cần."""
    effective = await _resolve_property_id(user, property_id)
    stmt = select(Tenant).where(
        Tenant.deleted_at.is_(None), Tenant.is_active.is_(True)
    )
    if effective:
        stmt = stmt.where(Tenant.property_id == effective)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            Tenant.full_name.ilike(like) | Tenant.phone.ilike(like)
        )
    rows = (await session.execute(
        stmt.order_by(Tenant.full_name).limit(limit)
    )).scalars().all()
    return [
        TenantSummary(id=t.id, full_name=t.full_name, phone=t.phone,
                      current_room_id=t.current_room_id)
        for t in rows
    ]


@tenant_router.get("/stats", response_model=TenantStats, summary="📊 Thống kê người thuê")
async def tenant_stats(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> TenantStats:
    effective = await _resolve_property_id(user, property_id)

    base = select(Tenant).where(Tenant.deleted_at.is_(None))
    if effective:
        base = base.where(Tenant.property_id == effective)
    condition = base.subquery()

    rows = (await session.execute(
        select(
            Tenant.risk_level,
            Tenant.is_active,
            func.count(Tenant.id),
            func.count(Tenant.id_card_bidx),
        )
        .where(Tenant.id.in_(select(condition.c.id)))
        .group_by(Tenant.risk_level, Tenant.is_active)
    )).all()

    by_risk: dict[str, int] = {}
    total = active = 0
    with_id_card = 0
    for risk, is_act, count, has_id in rows:
        by_risk[risk] = by_risk.get(risk, 0) + count
        total += count
        active += count if is_act else 0
        with_id_card += has_id

    # Thời gian ở trung bình: dùng tuổi hồ sơ làm xấp xỉ (người vào ở
    # gần đây có created_at mới hơn). Chính xác hơn là tính từ hợp đồng,
    # nhưng hợp đồng nằm ở service khác — chấp nhận xấp xỉ ở đây.
    oldest = (await session.execute(
        select(func.min(Tenant.created_at)).where(Tenant.id.in_(select(condition.c.id)))
    )).scalar()
    avg_months = 0.0
    if oldest:
        days = (datetime.now(UTC) - oldest).days
        avg_months = round(days / 30.4, 1)

    stats = TenantStats(
        property_id=effective,
        total=total,
        active=active,
        inactive=total - active,
        by_risk=by_risk,
        avg_tenure_months=avg_months,
        without_id_card=total - with_id_card,
        as_of=datetime.now(UTC),
    )
    set_business_gauge(settings.service_name, "active_tenants", active)
    return stats


@tenant_router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED,
                    summary="Tạo hồ sơ người thuê")
async def create_tenant(
    payload: TenantCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantResponse:
    await _resolve_property_id(user, payload.property_id)
    data = payload.model_dump()
    id_card = data.pop("id_card_number", None)

    tenant = Tenant(**data)
    # ⭐ Dùng setter để sinh đồng thời ciphertext + blind index + 4 số cuối
    tenant.set_id_card(id_card)
    session.add(tenant)

    try:
        await session.flush()
    except IntegrityError as exc:
        if "uq_tenant_id_card" in str(exc.orig):
            raise ConflictError(
                "CCCD này đã được đăng ký cho người thuê khác trong hệ thống. "
                "Một CCCD chỉ được dùng cho 1 hồ sơ."
            ) from exc
        if "ix_tenant_phone" in str(exc.orig):
            raise ConflictError(f"Số điện thoại {payload.phone} đã tồn tại") from exc
        raise

    await _add_history(session, tenant, "CREATED", user, note="Tạo hồ sơ người thuê")

    await get_event_bus().publish(session, DomainEvent(
        event_type="tenant.created",
        data={
            "tenant_id": str(tenant.id), "property_id": str(tenant.property_id),
            "full_name": tenant.full_name, "phone": tenant.phone,
            "has_id_card": bool(id_card),
            "entity_type": "tenant", "entity_id": str(tenant.id),
        },
    ))
    record_business_event(settings.service_name, "tenant.created")
    logger.info("👤 Tạo hồ sơ %s (%s) bởi %s", tenant.full_name, tenant.id, user.username)
    return TenantResponse(**_to_response(tenant))


@tenant_router.get("/{tenant_id}", response_model=TenantResponse, summary="Chi tiết hồ sơ")
async def get_tenant(
    tenant_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantResponse:
    tenant = await _get_tenant_or_404(session, tenant_id)
    user.assert_property_access(tenant.property_id)
    return TenantResponse(**_to_response(tenant))


@tenant_router.patch("/{tenant_id}", response_model=TenantResponse, summary="Cập nhật hồ sơ")
async def update_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantResponse:
    tenant = await _get_tenant_or_404(session, tenant_id)
    user.assert_property_access(tenant.property_id)

    before = _to_response(tenant)
    changes = payload.model_dump(exclude_unset=True)

    # Đổi mức rủi ro là quyết định kinh doanh → chỉ ADMIN, và phải có lý do
    if "risk_level" in changes and changes["risk_level"] != tenant.risk_level:
        if not user.is_admin:
            raise BusinessRuleError("Chỉ quản trị viên mới đánh giá lại mức rủi ro")
        if not changes.get("risk_note"):
            raise BusinessRuleError("Phải nêu lý do khi đánh giá lại mức rủi ro")

    for field, value in changes.items():
        setattr(tenant, field, value)
    await session.flush()

    await _add_history(
        session, tenant, "PROFILE_UPDATED", user,
        note="Cập nhật: " + ", ".join(changes.keys()),
        event_data={"changed": list(changes.keys())},
    )
    if "risk_level" in changes:
        await _add_history(
            session, tenant, "RISK_CHANGED", user,
            note=f"{before['risk_level']} → {tenant.risk_level}",
            event_data={"from": before["risk_level"], "to": tenant.risk_level},
        )

    return TenantResponse(**_to_response(tenant))


@tenant_router.put("/{tenant_id}/id-card", response_model=TenantSensitiveResponse,
                   summary="🔐 Cập nhật CCCD (yêu cầu quyền cao)")
async def update_id_card(
    request: Request,
    tenant_id: uuid.UUID,
    payload: TenantIdCardUpdate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantSensitiveResponse:
    """
    Endpoint nhạy cảm — 3 lớp kiểm soát:
      1. Chỉ ADMIN/MANAGER (không có TENANT)
      2. Phải nêu lý do (ghi vào lịch sử append-only)
      3. Chặn trùng với hồ sơ khác qua blind index
    """
    tenant = await _get_tenant_or_404(session, tenant_id)
    user.assert_property_access(tenant.property_id)

    bidx = blind_index(payload.id_card_number)
    duplicate = (await session.execute(
        select(Tenant).where(
            Tenant.id_card_bidx == bidx, Tenant.id != tenant_id,
        )
    )).scalar_one_or_none()
    if duplicate:
        raise ConflictError(
            f"CCCD này đã thuộc về hồ sơ của {duplicate.full_name} "
            f"(mã hồ sơ {duplicate.id})."
        )

    old_last4 = tenant.id_card_last4
    tenant.set_id_card(payload.id_card_number)
    await session.flush()

    await _add_history(
        session, tenant, "ID_CARD_UPDATED", user,
        note=payload.reason,
        # ⭐ Chỉ ghi 4 số cuối vào nhật ký, KHÔNG ghi CCCD đầy đủ.
        # Nhật ký là dữ liệu ít nhạy cảm hơn nhưng vẫn nằm trong DB.
        event_data={"old_last4": old_last4, "new_last4": tenant.id_card_last4},
    )

    logger.info("🔐 %s cập nhật CCCD cho hồ sơ %s — lý do: %s",
                user.username, tenant_id, payload.reason)

    return TenantSensitiveResponse(
        tenant_id=tenant.id,
        full_name=tenant.full_name,
        id_card_number=tenant.id_card_decrypted or "",
    )


@tenant_router.get("/{tenant_id}/id-card", response_model=TenantSensitiveResponse,
                   summary="🔐 Xem CCCD đầy đủ (ghi audit log)")
async def read_id_card(
    tenant_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantSensitiveResponse:
    """
    ⚠️  ENDPOINT NÀY GHI NHẬT KÝ MỖI LẦN ĐƯỢC GỌI.

    Nguyên tắc bảo mật dữ liệu cá nhân: truy cập dữ liệu nhạy cảm phải
    để lại dấu vết. Nếu không ai biết ai đã xem CCCD của ai thì cũng không
    ai có thể phát hiện việc lạm dụng.

    Lưu ý triển khai thật: nên thêm `access_log` ở tầng nginx
    (`log_format` đã có `$request_uri`) làm lớp ghi thứ hai, và giới hạn
    endpoint này cho ADMIN khi nghiên cứu pháp lý.
    """
    tenant = await _get_tenant_or_404(session, tenant_id)
    user.assert_property_access(tenant.property_id)

    if not tenant.id_card_enc:
        raise NotFoundError("Hồ sơ này chưa có CCCD")

    await _add_history(
        session, tenant, "ID_CARD_VIEWED", user,
        note=f"Truy cập bởi {user.username} ({user.role.value})",
    )
    logger.warning("👁️  %s (%s) đã xem CCCD của hồ sơ %s",
                   user.username, user.role.value, tenant_id)

    return TenantSensitiveResponse(
        tenant_id=tenant.id,
        full_name=tenant.full_name,
        id_card_number=tenant.id_card_decrypted or "",
        id_card_front=tenant.id_card_front,
        id_card_back=tenant.id_card_back,
    )


@tenant_router.get("/{tenant_id}/history", response_model=list[HistoryResponse],
                   summary="Lịch sử hồ sơ")
async def get_history(
    tenant_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
) -> list[HistoryResponse]:
    tenant = await _get_tenant_or_404(session, tenant_id)
    user.assert_property_access(tenant.property_id)

    rows = (await session.execute(
        select(TenantHistory)
        .where(TenantHistory.tenant_id == tenant_id)
        .order_by(TenantHistory.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return [HistoryResponse.model_validate(h) for h in rows]


@tenant_router.post("/{tenant_id}/history", response_model=HistoryResponse,
                    status_code=status.HTTP_201_CREATED, summary="Thêm ghi chú")
async def add_history_note(
    tenant_id: uuid.UUID,
    payload: HistoryCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HistoryResponse:
    tenant = await _get_tenant_or_404(session, tenant_id)
    user.assert_property_access(tenant.property_id)

    history = TenantHistory(
        tenant_id=tenant.id,
        property_id=tenant.property_id,
        room_id=tenant.current_room_id,
        event_type=payload.event_type,
        event_data=payload.event_data,
        actor_id=user.id,
        note=payload.note,
    )
    session.add(history)
    await session.flush()
    return HistoryResponse.model_validate(history)


@tenant_router.post("/{tenant_id}/transfer", response_model=TenantResponse,
                    summary="Chuyển người thuê sang cơ sở khác")
async def transfer_tenant(
    tenant_id: uuid.UUID,
    payload: TransferRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TenantResponse:
    """
    Chuyển cơ sở — GIỮ NGUYÊN hồ sơ và lịch sử.

    ⭐ Cũ sở được ghi vào `previous_property_ids` để sau này tra cứu
    "người này từng ở nhà trọ nào" — đây chính là dữ liệu chủ nhà cần
    để biết ai đã từng ở và rời đi, giúp đánh giá rủi ro chính xác hơn.
    """
    tenant = await _get_tenant_or_404(session, tenant_id)

    if payload.new_property_id == tenant.property_id:
        raise BusinessRuleError("Người thuê đã ở cơ sở này")

    if tenant.current_contract_id:
        raise BusinessRuleError(
            "Người thuê đang có hợp đồng hiệu lực. "
            "Phải kết thúc hợp đồng trước khi chuyển cơ sở."
        )

    old_property = tenant.property_id
    history = list(tenant.previous_property_ids or [])
    if str(old_property) not in history:
        history.append(str(old_property))

    tenant.previous_property_ids = history
    tenant.property_id = payload.new_property_id
    tenant.current_room_id = None
    await session.flush()

    await _add_history(
        session, tenant, "MOVED_OUT", user,
        note=payload.reason,
        event_data={"from_property": str(old_property),
                    "to_property": str(payload.new_property_id)},
    )
    logger.info("🚚 Chuyển hồ sơ %s: %s → %s",
                tenant.full_name, old_property, payload.new_property_id)
    return TenantResponse(**_to_response(tenant))


@tenant_router.delete("/{tenant_id}", response_model=MessageResponse,
                      summary="Ẩn hồ sơ (soft delete)")
async def delete_tenant(
    tenant_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """
    ⭐ SOFT DELETE, và CHỈ khi không còn hợp đồng.

    Hồ sơ bị ẩn vẫn giữ nguyên CCCD đã mã hóa và toàn bộ lịch sử — vì
    hợp đồng cũ và hóa đơn cũ vẫn tham chiếu tới. Xoá hẳn sẽ để lại
    hóa đơn không biết thuộc về ai, mất khả năng đối chiếu kế toán.
    """
    tenant = await _get_tenant_or_404(session, tenant_id)
    if tenant.current_contract_id:
        raise BusinessRuleError(
            "Không thể ẩn hồ sơ khi người thuê đang có hợp đồng hiệu lực"
        )

    tenant.deleted_at = datetime.now(UTC)
    tenant.is_active = False
    await _add_history(session, tenant, "DELETED", user, note="Ẩn hồ sơ")
    logger.info("🗑  Ẩn hồ sơ %s (%s) bởi %s", tenant.full_name, tenant_id, user.username)
    return MessageResponse(message=f"Đã ẩn hồ sơ của {tenant.full_name}")


# ===========================================================================
#  ROUTER: BẠN CÙNG PHÒNG
# ===========================================================================
roommate_router = APIRouter(prefix="/api/v1/roommates", tags=["roommates"])


@roommate_router.get("", response_model=list[RoommateResponse],
                      summary="Danh sách bạn cùng phòng")
async def list_roommates(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    room_id: uuid.UUID | None = None,
    property_id: uuid.UUID | None = None,
) -> list[RoommateResponse]:
    effective = await _resolve_property_id(user, property_id)
    stmt = select(Roommate).where(Roommate.deleted_at.is_(None))
    if room_id:
        stmt = stmt.where(Roommate.room_id == room_id)
    if effective:
        stmt = stmt.where(Roommate.property_id == effective)
    rows = (await session.execute(
        stmt.order_by(Roommate.is_primary.desc(), Roommate.full_name)
    )).scalars().all()
    return [RoommateResponse.model_validate(r) for r in rows]


@roommate_router.post("", response_model=RoommateResponse,
                      status_code=status.HTTP_201_CREATED, summary="Thêm bạn cùng phòng")
async def add_roommate(
    payload: RoommateCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoommateResponse:
    """
    ⭐ R1 — kiểm tra tối đa 3 người/phòng TRƯỚC khi insert.

    Vì sao kiểm ở service chứ không chỉ dựa vào DB?
      - `roommates` và `contracts` nằm ở 2 DB khác nhau → DB không thể
        thêm FK ràng buộc chéo.
      - Cần trả lỗi 422 với thông báo tiếng Việt rõ ràng ("phòng đã đủ 3 người"),
        thay vì lỗi constraint kỹ thuật.
      - Còn race condition thật sự (2 request cùng lúc) thì xử lý ở
        contract-service bằng partial unique index trên `contract_roommates`.
    """
    from common.clients import get_http_client

    room_info = await get_http_client("room").get(f"/internal/v1/rooms/{payload.room_id}")
    property_id = uuid.UUID(room_info["property_id"])
    user.assert_property_access(property_id)

    existing = (await session.execute(
        select(func.count(Roommate.id)).where(
            Roommate.room_id == payload.room_id, Roommate.deleted_at.is_(None)
        )
    )).scalar() or 0

    if existing >= MAX_OCCUPANTS_PER_ROOM:
        raise BusinessRuleError(
            f"Phòng {room_info['room_number']} đã có {existing} người. "
            f"Quy định tối đa {MAX_OCCUPANTS_PER_ROOM} người/phòng "
            f"(1 chủ hợp đồng + 2 bạn cùng phòng)."
        )

    if payload.tenant_id:
        exists = (await session.execute(
            select(Roommate).where(
                Roommate.tenant_id == payload.tenant_id,
                Roommate.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if exists:
            raise ConflictError("Người này đã là bạn cùng phòng ở một phòng khác")

    roommate = Roommate(
        property_id=property_id,
        room_id=payload.room_id,
        tenant_id=payload.tenant_id,
        full_name=payload.full_name,
        phone=payload.phone,
        is_primary=payload.is_primary,
    )
    session.add(roommate)
    await session.flush()
    return RoommateResponse.model_validate(roommate)


@roommate_router.delete("/{roommate_id}", response_model=MessageResponse,
                        summary="Xoá bạn cùng phòng")
async def remove_roommate(
    roommate_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    r = (await session.execute(
        select(Roommate).where(Roommate.id == roommate_id)
    )).scalar_one_or_none()
    if not r:
        raise NotFoundError("Không tìm thấy bạn cùng phòng")
    user.assert_property_access(r.property_id)

    r.deleted_at = datetime.now(UTC)
    return MessageResponse(message=f"Đã xoá {r.full_name} khỏi danh sách bạn cùng phòng")


# ===========================================================================
#  INTERNAL API
# ===========================================================================
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


@internal_router.get("/tenants/{tenant_id}", summary="[Nội bộ] Lấy hồ sơ")
async def internal_get_tenant(
    tenant_id: uuid.UUID,
    _: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    contract-service & billing-service gọi endpoint này.

    ⭐ Cố tình KHÔNG kiểm tra `assert_property_access`:
       token SYSTEM (service-to-service) không mang `property_id` của người
       dùng, nên hàm đó sẽ ném 403 oan. Thay vào đó service gọi là service,
       đã được tin cậy ở tầng mạng nội bộ (Docker network không có đường ra
       Internet). Ranh giới tin cậy được vẽ ở tầng hạ tầng, không phải
       bằng cách kiểm tra quyền hụt hiệu.
    """
    tenant = await _get_tenant_or_404(session, tenant_id)
    return {
        "id": str(tenant.id),
        "property_id": str(tenant.property_id),
        "full_name": tenant.full_name,
        "phone": tenant.phone,
        "email": tenant.email,
        "current_room_id": str(tenant.current_room_id) if tenant.current_room_id else None,
        "is_active": tenant.is_active,
        "risk_level": tenant.risk_level,
    }


# ===========================================================================
#  CONSUMER
# ===========================================================================
async def _handle_event(event: DomainEvent) -> None:
    handler = {
        "contract.activated": _on_contract_activated,
        "contract.terminated": _on_contract_closed,
        "contract.expired": _on_contract_closed,
    }.get(event.event_type)
    if handler is None:
        return
    async with session_scope() as session:
        await handler(session, event)


async def _on_contract_activated(session: AsyncSession, event: DomainEvent) -> None:
    """
    Hợp đồng có hiệu lực → cập nhật bản sao "đang ở phòng nào".

    ⭐ Đây là DỮ LIỆU SAI LỆCH CÓ CHỦ ĐÍCH (eventual consistency).
       Nếu event bị mất, `current_room_id` sẽ không đúng. Đây là đánh
       đổi được chấp nhận vì:
         - Trước khi thao tác quan trọng (tạo hợp đồng, tính tiền),
           luôn tra lại contract-service (nguồn chuẩn).
         - Nhưng với MỤC ĐÍCH TRÌNH BÀY (xem danh sách, tìm kiếm) thì bản
           sao tiện hơn nhiều và chấp nhận sai số vài giây.
       Nếu đổi yêu cầu "dữ liệu phải luôn tuyệt đối đúng" thì phải dùng
       truy vấn đồng bộ sang contract-service — đánh đổi bằng p95.
    """
    tenant_id = event.data.get("tenant_id")
    if not tenant_id:
        return

    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == uuid.UUID(tenant_id))
    )).scalar_one_or_none()
    if not tenant:
        logger.warning("contract.activated: không tìm thấy người thuê %s", tenant_id)
        return

    tenant.current_room_id = uuid.UUID(event.data["room_id"])
    tenant.current_contract_id = uuid.UUID(event.data["contract_id"])
    tenant.is_active = True
    await session.flush()

    await _add_history(
        session, tenant, "MOVED_IN",
        note=f"Vào ở phòng {event.data.get('room_number', '')}",
        event_data={
            "room_id": event.data["room_id"],
            "contract_id": event.data["contract_id"],
            "end_date": event.data.get("end_date"),
        },
    )
    logger.info("🏠 %s vào ở phòng %s", tenant.full_name, event.data.get("room_number"))


async def _on_contract_closed(session: AsyncSession, event: DomainEvent) -> None:
    """Hợp đồng kết thúc → bỏ liên kết phòng, ghi lịch sử rời đi."""
    tenant_id = event.data.get("tenant_id")
    if not tenant_id:
        return

    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == uuid.UUID(tenant_id))
    )).scalar_one_or_none()
    if not tenant:
        return

    tenant.current_room_id = None
    tenant.current_contract_id = None
    await session.flush()

    await _add_history(
        session, tenant, "MOVED_OUT",
        note=f"Rời phòng: {event.data.get('reason') or event.event_type}",
        event_data={
            "room_id": event.data.get("room_id"),
            "reason": event.data.get("reason"),
            "event_type": event.event_type,
        },
    )
    logger.info("🚪 %s rời phòng %s", tenant.full_name, event.data.get("room_number"))


# ===========================================================================
#  ĐĂNG KÝ ROUTER
# ===========================================================================
app.include_router(tenant_router)
app.include_router(roommate_router)
app.include_router(internal_router)
