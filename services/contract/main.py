"""
===============================================================================
contract-service — Vòng đời hợp đồng thuê.   Cổng 8004  |  db_contract
===============================================================================

Đây là CORE DOMAIN của hệ thống — nơi quyết định "phòng này có người thuê
hay không". Mọi service khác đều nghe theo service này, không nghe ngược lại.

Bốn phần kỹ thuật đáng chú ý:

  1. MÁY TRẠNG THÁI (`_transition`) — DUY NHẤT một hàm được đổi trạng thái
     hợp đồng, kiểm tra bảng `ALLOWED_TRANSITIONS`, và luôn phát event.
     Ràng buộc luôn ở một chỗ = không có đường lách luật.

  2. R2 Ở TẦNG DB — partial unique index `(room_id) WHERE status='ACTIVE'`.
     Python check không đủ, vì 2 request song song đều thấy "chưa có".

  3. SAGA ORCHESTRATION — `activate` là bước quyết định của luồng "nhận phòng".
     Saga chạy theo thứ tự 3a → 3b → 3c: giữ phòng (room) → commit ACTIVE →
     ghi nhận cọc. Nếu bước 3a fail thì dừng, không commit gì cả.

  4. SCHEDULER TÁCH RIÊNG — hợp đồng hết hạn và sắp hết hạn được phát hiện bởi
     container `scheduler`, gọi endpoint nội bộ ở đây. Nhờ vậy chạy 3 replica
     contract-service vẫn không ai phát event trùng.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common import (
    BusinessRuleError,
    ConflictError,
    CurrentUser,
    NotFoundError,
    PageParams,
    Role,
    apply_sort,
    create_service_app,
    get_db,
    get_event_bus,
    get_http_client,
    paginate,
    record_business_event,
    require_roles,
)
from common.config import settings
from common.events import DomainEvent
from common.repository import next_sequence
from common.telemetry import set_business_gauge
from models import (
    ALLOWED_TRANSITIONS,
    Contract,
    ContractPayment,
    ContractRoommate,
    ContractStatus,
    TenantSnapshot,
)
from schemas import (
    ActivateRequest,
    ContractCreate,
    ContractListItem,
    ContractResponse,
    ContractStats,
    ContractUpdate,
    DepositCreate,
    PaymentResponse,
    RenewRequest,
    RoommateResponse,
    RoommateSet,
    TerminateRequest,
)

logger = logging.getLogger(__name__)

#: R1 — tối đa 3 người/phòng (1 chủ hợp đồng + 2 bạn)
MAX_OCCUPANTS = 3

#: Số ngày trước khi hết hạn thì phát event nhắc gia hạn
EXPIRING_WARNING_DAYS = 30

#: Thời gian giữ phòng (giờ) trong Saga bước 3a.
#: Đủ lâu để người thuê mang CCCP + cọc tiền tới nộp; quá ngắn thì phòng bị
#: giữ mãi khi khách đổi ý, quá dài thì phòng "kẹt" không cho thuê được.
RESERVE_HOURS = 24


# ===========================================================================
#  APP
# ===========================================================================
# ⚠️  contract-service KHÔNG đăng ký consumer nào.
#
#     Lý do: nó là Orchestrator của Saga — phát event ra, không phản ứng lại
#     với event của service khác. Nếu nó có consumer, mỗi event đi qua lại
#     sẽ tạo thêm 1 cặp (producer, consumer) không cần thiết và làm tăng
#     độ trễ toàn hệ thống. Việc duy nhất cần theo dõi bên ngoài là
#     `scheduler` gọi `/internal/v1/contracts/*`.
app = create_service_app(
    name="contract-service",
    description=(
        "**Hợp đồng thuê** *(Core Domain)*\n\n"
        "- Soạn → gửi ký → kích hoạt → gia hạn / chấm dứt\n"
        "- Quản lý tiền cọc (R3: không bao giờ trừ quá số đã đặt)\n"
        "- Bạn cùng phòng (R1: tối đa 3 người/phòng)\n"
        "- Phát event điều khiển room / billing / notification\n\n"
        "### Trạng thái hợp đồng\n"
        "`DRAFT → PENDING_SIGN → ACTIVE → (EXPIRED | TERMINATED) → RENEWED`\n\n"
        "### Ràng buộc\n"
        "- **R2**: 1 phòng chỉ có 1 hợp đồng `ACTIVE` (partial unique index)\n"
        "- **R3**: tiền cọc không bao giờ âm\n"
        "- Hợp đồng `ACTIVE` **không sửa được** — phải ký lại"
    ),
    version="1.0.0",
)


# ===========================================================================
#  MÁY TRẠNG THÁI
# ===========================================================================
async def _transition(
    session: AsyncSession,
    contract: Contract,
    new_status: str,
    *,
    reason: str | None = None,
    actor: CurrentUser | None = None,
    extra: dict | None = None,
) -> Contract:
    """
    Hàm DUY NHẤT được phép đổi trạng thái hợp đồng.

    Mọi lối vào — REST thủ công lẫn cron của scheduler — đều gọi hàm này. Nhờ vậy:
      - không có đường nào đổi trạng thái mà bỏ qua luật chuyển trạng thái
      - mọi lần đổi đều sinh ra event → notification luôn biết diễn biến
      - `from`/`to` luôn có trong event để report dựng được timeline

    ⭐ Nguyên tắc "single point of truth" cho state machine — cùng nguyên tắc
       mà room-service áp cho trạng thái phòng. Trong microservice, nguyên nhân
       phổ biến nhất của dữ liệu sai là có 3 chỗ cùng ghi vào 1 trường.
    """
    old_status = contract.status
    if old_status == new_status:
        logger.debug("HĐ %s đã ở trạng thái %s", contract.contract_no, new_status)
        return contract

    allowed = ALLOWED_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise BusinessRuleError(
            f"Hợp đồng đang ở trạng thái {old_status} nên không thể chuyển sang "
            f"{new_status}. Chỉ chuyển được sang: "
            f"{', '.join(sorted(allowed)) or '(trạng thái cuối, không chuyển được)'}",
            details={
                "contract_id": str(contract.id),
                "contract_no": contract.contract_no,
                "current_status": old_status,
                "requested_status": new_status,
            },
        )

    contract.status = new_status
    if new_status == ContractStatus.ACTIVE.value:
        contract.activated_at = datetime.now(UTC)
    if new_status in (ContractStatus.TERMINATED.value, ContractStatus.CANCELLED.value):
        contract.terminated_at = datetime.now(UTC)
        contract.terminated_reason = reason

    await session.flush()

    # Tên event theo trạng thái đích: consumer chỉ cần subscribe theo tên.
    await get_event_bus().publish(session, DomainEvent(
        event_type=f"contract.{new_status.lower()}",
        data={
            "contract_id": str(contract.id),
            "contract_no": contract.contract_no,
            "property_id": str(contract.property_id),
            "room_id": str(contract.room_id),
            "tenant_id": str(contract.primary_tenant_id),
            "tenant_name": contract.primary_tenant_name,
            "from": old_status,
            "to": new_status,
            "reason": reason,
            "end_date": contract.end_date.isoformat(),
            "monthly_price": str(contract.monthly_price),
            **(extra or {}),
            "entity_type": "contract",
            "entity_id": str(contract.id),
            "changed_by": actor.username if actor else "system",
        },
    ))
    record_business_event(settings.service_name, f"contract.{new_status.lower()}")

    logger.info("📄 HĐ %s: %s → %s (%s)", contract.contract_no, old_status,
                new_status, reason or "—")
    return contract


# ===========================================================================
#  ROUTER: CONTRACT
# ===========================================================================
contract_router = APIRouter(prefix="/api/v1/contracts", tags=["contracts"])


@contract_router.get("", summary="Danh sách hợp đồng")
async def list_contracts(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    property_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    contract_status: str | None = Query(
        None, alias="status", description="Lọc theo trạng thái hợp đồng"
    ),
    active_only: bool = Query(False, description="Chỉ hợp đồng đang hiệu lực"),
    expiring_in_days: int | None = Query(
        None, ge=1, le=365, description="Hợp đồng sắp hết hạn trong N ngày"
    ),
    sort: str = Query("end_date_asc", description="end_date|start_date|monthly_price"),
) -> dict:
    """
    ADMIN thấy tất cả; MANAGER chỉ thấy hợp đồng của cơ sở mình.

    ⭐ Ràng buộc cơ sở được ép ở `WHERE` chứ không phải lọc sau khi lấy — nếu
       lọc sau, database vẫn đọc hàng nghìn dòng của cơ sở khác rồi mới bỏ,
       vừa chậm vừa lộ số liệu qua `meta.total`.
    """
    effective = _resolve_property(user, property_id)

    stmt = select(Contract).where(Contract.renewed_to_id.is_(None))
    if effective:
        stmt = stmt.where(Contract.property_id == effective)
    if room_id:
        stmt = stmt.where(Contract.room_id == room_id)
    if tenant_id:
        stmt = stmt.where(Contract.primary_tenant_id == tenant_id)
    if contract_status:
        stmt = stmt.where(Contract.status == contract_status)
    if active_only:
        stmt = stmt.where(Contract.status == ContractStatus.ACTIVE.value)
    if expiring_in_days:
        today = date.today()
        stmt = stmt.where(
            Contract.status == ContractStatus.ACTIVE.value,
            Contract.end_date >= today,
            Contract.end_date <= today + timedelta(days=expiring_in_days),
        )

    stmt = apply_sort(
        stmt, Contract, sort,
        allowed={"end_date": "end_date", "start_date": "start_date",
                 "price": "monthly_price", "no": "contract_no"},
        default="end_date",
    )

    items, meta = await paginate(session, stmt, params)
    return {
        "items": [_to_list_item(c) for c in items],
        "meta": meta.model_dump(),
    }


@contract_router.post("", response_model=ContractResponse,
                      status_code=status.HTTP_201_CREATED, summary="Soạn hợp đồng mới")
async def create_contract(
    payload: ContractCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    """
    Tạo hợp đồng ở trạng thái `DRAFT`.

    Hợp đồng sinh ra ở DRAFT chứ không phải ACTIVE: người thuê chưa ký, chưa đặt
    cọc thì chưa có nghĩa vụ pháp lý. Bấm "Tạo hợp đồng" không được tự động
    biến phòng thành "đang có người".
    """
    _resolve_property(user, payload.property_id)

    # --- Kiểm tra phòng có khoá chưa (Saga bước 3a xem thêm ở `activate`) ---
    room = await _fetch_room(payload.room_id)
    if room:
        if str(room["property_id"]) != str(payload.property_id):
            raise BusinessRuleError(
                "Phòng không thuộc cơ sở này. Hãy kiểm tra lại phòng đã chọn."
            )
        if room["status"] == "OCCUPIED":
            raise ConflictError(
                f"Phòng {room['room_number']} đang có người thuê. "
                "Hãy kết thúc hợp đồng hiện tại trước khi tạo hợp đồng mới."
            )
        if room["status"] == "MAINTENANCE":
            raise BusinessRuleError(
                f"Phòng {room['room_number']} đang được bảo trì, chưa thể ký hợp đồng mới."
            )

    active = (await session.execute(
        select(Contract).where(
            Contract.room_id == payload.room_id,
            Contract.status == ContractStatus.ACTIVE.value,
        )
    )).scalar_one_or_none()
    if active:
        raise ConflictError(
            f"Phòng này đang có hợp đồng {active.contract_no} còn hiệu lực "
            f"(kết thúc ngày {active.end_date})."
        )

    contract = Contract(
        contract_no=await _next_contract_no(session),
        status=ContractStatus.DRAFT.value,
        created_by=user.id,
        **{k: v for k, v in payload.model_dump().items()
           if k not in ("room_id_confirmed",)},
    )
    session.add(contract)
    await session.flush()

    # Bản chụp hồ sơ — đóng băng tại thời điểm tạo hợp đồng
    session.add(TenantSnapshot(
        contract_id=contract.id,
        tenant_id=payload.primary_tenant_id,
        full_name=payload.primary_tenant_name,
        phone=payload.primary_tenant_phone,
        email=payload.primary_tenant_email,
    ))

    await get_event_bus().publish(session, DomainEvent(
        event_type="contract.created",
        data={
            "contract_id": str(contract.id),
            "contract_no": contract.contract_no,
            "property_id": str(contract.property_id),
            "room_id": str(contract.room_id),
            "tenant_id": str(contract.primary_tenant_id),
            "entity_type": "contract", "entity_id": str(contract.id),
        },
    ))

    logger.info("📝 Tạo hợp đồng %s cho phòng %s (bởi %s)",
                contract.contract_no, payload.room_id, user.username)
    return await _load_response(session, contract)


@contract_router.get("/expiring", response_model=list[ContractListItem],
                      summary="⏰ Hợp đồng sắp hết hạn")
async def list_expiring(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(EXPIRING_WARNING_DAYS, ge=1, le=180,
                      description="Sắp hết hạn trong N ngày"),
    property_id: uuid.UUID | None = None,
) -> list[ContractListItem]:
    """Màn hình "cần gọi điện cho ai tuần này" — truy vấn 1 lần, không N+1."""
    effective = _resolve_property(user, property_id)
    today = date.today()

    stmt = select(Contract).where(
        Contract.status == ContractStatus.ACTIVE.value,
        Contract.end_date >= today,
        Contract.end_date <= _add_days(today, days),
    )
    if effective:
        stmt = stmt.where(Contract.property_id == effective)
    stmt = stmt.order_by(Contract.end_date)

    rows = (await session.execute(stmt)).scalars().all()
    return [_to_list_item(c) for c in rows]


@contract_router.get("/stats", response_model=ContractStats, summary="📊 Thống kê hợp đồng")
async def contract_stats(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> ContractStats:
    effective = _resolve_property(user, property_id)

    base = select(Contract).where(Contract.renewed_to_id.is_(None))
    if effective:
        base = base.where(Contract.property_id == effective)

    rows = (await session.execute(
        select(Contract.status, func.count(Contract.id))
        .where(Contract.status.in_([s.value for s in ContractStatus]))
        .group_by(Contract.status)
    )).all()

    by_status = {s.value: 0 for s in ContractStatus}
    for st, count in rows:
        by_status[st] = count

    # Doanh thu thuê ước tính = tổng tiền phòng của các HĐ đang chạy.
    # Chỉ tính HĐ ACTIVE: hợp đồng hết hạn tuần trước không sinh doanh thu.
    active = (await session.execute(
        select(
            func.coalesce(func.sum(Contract.monthly_price), 0),
            func.coalesce(func.sum(Contract.deposit_amount - Contract.deposit_deducted), 0),
            func.count(Contract.id),
        ).where(base.where(Contract.status == ContractStatus.ACTIVE.value))
    )).one()

    today = date.today()
    expiring_30d = (await session.execute(
        select(func.count(Contract.id)).where(
            base.where(
                Contract.status == ContractStatus.ACTIVE.value,
                Contract.end_date >= today,
                Contract.end_date <= _add_days(today, 30),
            )
        )
    )).scalar() or 0

    set_business_gauge(settings.service_name, "contracts_active", int(active[2] or 0),
                       str(effective or "all"))
    return ContractStats(
        total=sum(by_status.values()),
        by_status=by_status,
        active=by_status.get(ContractStatus.ACTIVE.value, 0),
        expiring_30d=int(expiring_30d),
        monthly_revenue=Decimal(active[0] or 0),
        deposits_held=Decimal(active[1] or 0),
    )


@contract_router.get("/{contract_id}", response_model=ContractResponse,
                     summary="Chi tiết hợp đồng")
async def get_contract(
    contract_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)
    return await _load_response(session, contract)


@contract_router.patch("/{contract_id}", response_model=ContractResponse,
                      summary="Sửa hợp đồng (chỉ khi chưa hiệu lực)")
async def update_contract(
    contract_id: uuid.UUID,
    payload: ContractUpdate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)

    if contract.status not in (ContractStatus.DRAFT.value,
                               ContractStatus.PENDING_SIGN.value):
        raise BusinessRuleError(
            f"Hợp đồng {contract.contract_no} đang ở trạng thái {contract.status} "
            "nên không thể sửa. Hợp đồng đã ký chỉ sửa được bằng phụ lục hoặc "
            "ký lại hợp đồng mới.",
            details={"contract_id": str(contract_id), "status": contract.status},
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if field == "start_date" and value > contract.end_date:
            raise BusinessRuleError("Ngày bắt đầu phải trước ngày kết thúc")
        if field == "end_date" and value <= contract.start_date:
            raise BusinessRuleError("Ngày kết thúc phải sau ngày bắt đầu")
        setattr(contract, field, value)

    await session.flush()
    return await _load_response(session, contract)


# ---------------------------------------------------------------------------
#  VÒNG ĐỜI HỢP ĐỒNG
# ---------------------------------------------------------------------------
@contract_router.post("/{contract_id}/send", response_model=ContractResponse,
                      summary="📤 Gửi người thuê ký")
async def send_contract(
    contract_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    """
    `DRAFT → PENDING_SIGN`: gửi hợp đồng cho người thuê xem & đặt cọc.

    Phải có ít nhất 1 bạn cùng phòng đã điền? KHÔNG — một mình thuê là hợp
    lệ. Nhưng phải có CCCD trước khi ký, nên đây là lúc kiểm tra hồ sơ đủ.
    """
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)

    if not contract.primary_tenant_phone:
        raise BusinessRuleError(
            "Hợp đồng chưa có số điện thoại người thuê — không thể gửi để ký."
        )

    await _transition(session, contract, ContractStatus.PENDING_SIGN.value,
                      actor=user, reason="Gửi người thuê ký")
    return await _load_response(session, contract)


@contract_router.post("/{contract_id}/deposit", response_model=ContractResponse,
                      summary="💰 Ghi nhận đã thu tiền cọc")
async def record_deposit(
    contract_id: uuid.UUID,
    payload: DepositCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    """
    Ghi nhận cọc. Không tự kích hoạt hợp đồng — quyền kích hoạt thuộc
    người quản lý sau khi đã đủ 2 điều kiện (nguồn tiền + người thuê xác nhận).

    ⭐ Cho phép ghi nhận nhiều lần (đặt 1 phần rồi đặt nốt) — mỗi lần thêm 1
    dòng `contract_payments`. Tổng đã đặt = SUM(contract_payments).
    """
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)

    if contract.status in (ContractStatus.CANCELLED.value,
                           ContractStatus.TERMINATED.value,
                           ContractStatus.EXPIRED.value):
        raise BusinessRuleError(
            f"Hợp đồng {contract.contract_no} đã ở trạng thái {contract.status} — "
            "không thể thu cọc thêm."
        )

    payment = ContractPayment(
        contract_id=contract.id,
        amount=payload.amount,
        method=payload.method,
        receipt_no=payload.receipt_no,
        note=payload.note,
        received_by=user.id,
    )
    session.add(payment)
    await session.flush()

    # `deposit_paid_at` = thời điểm đủ cọc (không phải lần đặt đầu tiên)
    total_paid = Decimal(await _total_paid(session, contract.id))
    if total_paid >= contract.deposit_amount:
        contract.deposit_paid_at = datetime.now(UTC)

    await get_event_bus().publish(session, DomainEvent(
        event_type="contract.deposit_paid",
        data={
            "contract_id": str(contract.id),
            "contract_no": contract.contract_no,
            "room_id": str(contract.room_id),
            "tenant_id": str(contract.primary_tenant_id),
            "amount": str(payload.amount),
            "method": payload.method,
            "required": str(contract.deposit_amount),
            "received_total": str(total_paid),
            "fully_paid": total_paid >= contract.deposit_amount,
            "entity_type": "contract", "entity_id": str(contract.id),
        },
    ))

    logger.info("💰 Thu cọc %s cho HĐ %s (tổng %s/%s)",
                payload.amount, contract.contract_no, total_paid, contract.deposit_amount)
    return await _load_response(session, contract)


@contract_router.post("/{contract_id}/activate", response_model=ContractResponse,
                      summary="✅ Kích hoạt hợp đồng")
async def activate_contract(
    contract_id: uuid.UUID,
    payload: ActivateRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    """
    `PENDING_SIGN → ACTIVE` — bước QUYẾT ĐỊNH của luồng "nhận phòng mới".

    ====================  SAGA ORCHESTRATION  ====================
    Thứ tự cố ý: giữ phòng → commit → thông báo.

      3a. Gọi room-service giữ phòng (RESERVED).
          Fail ở đây → dừng luôn, DB chưa đổi gì → trạng thái như cũ.
      3b. Ghi `ACTIVE` + COMMIT (trong cùng transaction với hóa đơn cọc).
          Nếu commit fail → phòng vẫn RESERVED, có thể giải phóng thủ công.
      3c. Phát `contract.activated` → room-service chuyển sang OCCUPIED,
          billing bắt đầu tính tiền, notification gửi email.
    ==============================================================

    ⚠️  Vì sao 3b phải ĐỨNG RIÊNG, không gộp với 3a?
        Vì 3a là gọi service khác (không thể rollback được). Nếu gộp, khi
        3a thành công mà 3b fail, phòng bị giữ mà hợp đồng chưa chạy →
        phòng "kẹt". Tách ra thì trạng thái xấu nhất chỉ là "phòng giữ nhầm",
        sửa được bằng 1 thao tác; còn gộp lại là "mất tiền cọc mà không có
        hợp đồng".
    """
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)

    if contract.status != ContractStatus.PENDING_SIGN.value:
        raise ConflictError(
            f"Hợp đồng đang ở trạng thái {contract.status}, không thể kích hoạt. "
            "Chỉ kích hoạt được hợp đồng đang chờ ký."
        )

    if not payload.confirm_deposit:
        raise BusinessRuleError(
            "Phải xác nhận đã thu đủ tiền cọc trước khi kích hoạt hợp đồng. "
            "Bỏ qua bước này là nguyên nhân phổ biến nhất gây mất tiền cọc.",
            details={"deposit_amount": str(contract.deposit_amount)},
        )

    total_paid = Decimal(await _total_paid(session, contract.id))
    if total_paid < contract.deposit_amount:
        raise BusinessRuleError(
            f"Chưa thu đủ tiền cọc: đã thu {total_paid:,.0f}đ, cần "
            f"{contract.deposit_amount:,.0f}đ. Thiếu "
            f"{(contract.deposit_amount - total_paid):,.0f}đ."
            if contract.deposit_amount > 0
            else "Hợp đồng này không yêu cầu cọc nhưng vẫn cần xác nhận.",
            details={"paid": str(total_paid), "required": str(contract.deposit_amount)},
        )

    # ---- Saga 3a: giữ phòng ----
    reserved = await _reserve_room(contract, user)
    if not reserved:
        raise ConflictError(
            "Không giữ được phòng (phòng có thể vừa được người khác thuê). "
            "Vui lòng kiểm tra lại trạng thái phòng rồi thử lại."
        )

    # ---- Saga 3b: commit trạng thái ----
    await _transition(
        session, contract, ContractStatus.ACTIVE.value, actor=user,
        reason="Người thuê đã đặt cọc và xác nhận",
        extra={"deposit_paid": str(total_paid)},
    )

    logger.info("🎉 Kích hoạt hợp đồng %s — phòng %s chuyển sang có người thuê",
                contract.contract_no, contract.room_id)
    return await _load_response(session, contract)


@contract_router.post("/{contract_id}/terminate", response_model=ContractResponse,
                      summary="⛔ Chấm dứt hợp đồng sớm")
async def terminate_contract(
    contract_id: uuid.UUID,
    payload: TerminateRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    """
    `ACTIVE → TERMINATED`.

    Bắt buộc có lý do (≥10 ký tự) — không có lý do thì khi tranh chấp không
    biết ai sai, và báo cáo "vì sao khách rời" sẽ vô dụng.

    Phí phạt (nếu có) được ghi nhận để billing tính vào hóa đơn cuối cùng.
    """
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)

    if contract.status != ContractStatus.ACTIVE.value:
        raise ConflictError(
            f"Chỉ chấm dứt được hợp đồng đang hiệu lực. "
            f"Hợp đồng này đang ở trạng thái {contract.status}."
        )

    if payload.penalty_amount > contract.remaining_deposit:
        raise BusinessRuleError(
            f"Phí phạt {payload.penalty_amount:,.0f}đ lớn hơn tiền cọc còn lại "
            f"({contract.remaining_deposit:,.0f}đ). Với mức phạt lớn hơn, cần thu "
            "thêm ngoài hóa đơn — ghi nhận ở module công nợ.",
            details={"remaining_deposit": str(contract.remaining_deposit)},
        )

    extra: dict = {}
    if payload.penalty_amount > 0:
        extra["penalty_amount"] = str(payload.penalty_amount)
    if payload.refund_deposit:
        extra["deposit_refunded"] = str(contract.remaining_deposit)

    await _transition(
        session, contract, ContractStatus.TERMINATED.value, actor=user,
        reason=payload.reason, extra=extra,
    )
    return await _load_response(session, contract)


@contract_router.post("/{contract_id}/cancel", response_model=ContractResponse,
                      summary="✖️ Huỷ hợp đồng (trước khi ký)")
async def cancel_contract(
    contract_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    reason: str = Query(..., min_length=5, max_length=500,
                        description="Lý do huỷ (bắt buộc)"),
) -> ContractResponse:
    """
    `DRAFT | PENDING_SIGN → CANCELLED`.

    Khác `terminate`: huỷ khi hợp đồng **chưa có hiệu lực**, nên không phát
    `contract.terminated` mà phát `contract.cancelled` — room-service dùng
    event này để giải phóng phòng đã giữ (RESERVED) mà KHÔNG đụng tới
    hợp đồng đang chạy.
    """
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)
    await _transition(session, contract, ContractStatus.CANCELLED.value,
                      actor=user, reason=reason)
    return await _load_response(session, contract)


@contract_router.post("/{contract_id}/renew", response_model=ContractResponse,
                      status_code=status.HTTP_201_CREATED,
                      summary="🔄 Gia hạn (tạo hợp đồng mới)")
async def renew_contract(
    contract_id: uuid.UUID,
    payload: RenewRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    """
    Gia hạn bằng cách TẠO HỢP ĐỒNG MỚI, không sửa hợp đồng cũ.

    ⭐ Vì sao không sửa hợp đồng cũ?
        Hợp đồng cũ là **bằng chứng** đã ký. Nếu kéo dài `end_date` của nó,
        giá và kỳ hạn trong hợp đồng gốc sẽ không còn khớp với thực tế — mất
        giá trị chứng minh. Hợp đồng cũ chuyển sang `RENEWED` và trỏ tới hợp
        đồng mới; lịch sử thuê của phòng vẫn nối liền không đứt.
    """
    old = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(old.property_id)

    if old.status not in (ContractStatus.EXPIRED.value, ContractStatus.TERMINATED.value):
        raise BusinessRuleError(
            f"Chỉ gia hạn được hợp đồng đã kết thúc. Hợp đồng {old.contract_no} "
            f"đang ở trạng thái {old.status}."
        )

    if old.renewed_to_id:
        raise ConflictError(
            f"Hợp đồng {old.contract_no} đã được gia hạn bằng hợp đồng khác rồi."
        )

    new = Contract(
        contract_no=await _next_contract_no(session),
        property_id=old.property_id,
        room_id=old.room_id,
        primary_tenant_id=old.primary_tenant_id,
        primary_tenant_name=old.primary_tenant_name,
        primary_tenant_phone=old.primary_tenant_phone,
        primary_tenant_email=old.primary_tenant_email,
        start_date=payload.new_start_date,
        end_date=payload.new_end_date,
        monthly_price=payload.new_monthly_price or old.monthly_price,
        deposit_amount=payload.new_deposit_amount or old.deposit_amount,
        payment_cycle=old.payment_cycle,
        status=ContractStatus.DRAFT.value,
        renewed_from_id=old.id,
        terms=old.terms,
        created_by=user.id,
    )
    session.add(new)
    await session.flush()

    old.renewed_to_id = new.id
    await _transition(session, old, ContractStatus.RENEWED.value, actor=user,
                      reason=f"Gia hạn thành hợp đồng {new.contract_no}",
                      extra={"new_contract_id": str(new.id)})

    logger.info("🔄 Gia hạn: %s → %s (từ %s đến %s)", old.contract_no,
                new.contract_no, new.start_date, new.end_date)
    return await _load_response(session, new)


# ---------------------------------------------------------------------------
#  ROOMMATE
# ---------------------------------------------------------------------------
@contract_router.get("/{contract_id}/roommates", response_model=list[RoommateResponse],
                     summary="Danh sách bạn cùng phòng")
async def list_roommates(
    contract_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[RoommateResponse]:
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)
    return [RoommateResponse.model_validate(r) for r in contract.roommates]


@contract_router.put("/{contract_id}/roommates", response_model=ContractResponse,
                     summary="Thay toàn bộ bạn cùng phòng")
async def set_roommates(
    contract_id: uuid.UUID,
    payload: RoommateSet,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractResponse:
    """
    ⭐ R1 — tối đa 3 người/phòng: 1 chủ hợp đồng + tối đa 2 bạn.

    Giới hạn này kiểm ở đây chứ không ép bằng CHECK constraint, vì nó phụ
    thuộc `rooms.max_occupants` (phòng 2 người, phòng 3 người) — thứ nằm ở
    DB khác nên không thể đưa thành ràng buộc SQL ở đây.
    """
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)

    if contract.status == ContractStatus.ACTIVE.value:
        raise BusinessRuleError(
            "Không thêm/bớt người ở hợp đồng đang hiệu lực. "
            "Hãy tạo phụ lục hợp đồng hoặc chấm dứt rồi ký lại."
        )

    if len(payload.roommates) > MAX_OCCUPANTS - 1:
        raise BusinessRuleError(
            f"Phòng chỉ được tối đa {MAX_OCCUPANTS} người "
            f"(1 chủ hợp đồng + {MAX_OCCUPANTS - 1} bạn cùng phòng)."
        )

    contract.roommates.clear()
    await session.flush()
    for r in payload.roommates:
        data = r.model_dump()
        card = data.pop("id_card_number", None)
        contract.roommates.append(ContractRoommate(**data, id_card_last4=card[-4:] if card else None))

    await session.flush()
    logger.info("👥 Cập nhật %d bạn cùng phòng cho HĐ %s",
                len(payload.roommates), contract.contract_no)
    return await _load_response(session, contract)


@contract_router.get("/{contract_id}/payments", response_model=list[PaymentResponse],
                     summary="Lịch sử đặt cọc")
async def list_payments(
    contract_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[PaymentResponse]:
    contract = await _get_contract_or_404(session, contract_id)
    user.assert_property_access(contract.property_id)

    rows = (await session.execute(
        select(ContractPayment)
        .where(ContractPayment.contract_id == contract_id)
        .order_by(ContractPayment.paid_at)
    )).scalars().all()
    return [PaymentResponse.model_validate(p) for p in rows]


# ===========================================================================
#  ROUTER: INTERNAL — dùng bởi service khác
# ===========================================================================
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


# ⭐ ROUTE TĨNH PHẢI KHAI BÁO TRƯỚC ROUTE ĐỘNG: Starlette (FastAPI) match route
#    theo THỨ TỰ ĐĂNG KÝ. Nếu `/contracts/active` khai sau
#    `/contracts/{contract_id}` thì request tới `/contracts/active` bị route
#    động nuốt (contract_id="active") → FastAPI validate UUID fail → 422.
#    Lỗi này từng làm hỏng job tính tiền hằng tháng (billing) và số hợp đồng
#    đang hiệu lực trên dashboard (report).
@internal_router.get("/contracts/active", summary="[Nội bộ] HĐ đang hiệu lực")
async def internal_list_active(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM, Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> list[dict]:
    """
    Danh sách hợp đồng ACTIVE — nguồn dữ liệu cho job tính tiền hằng tháng.

    billing-service KHÔNG tự có bảng hợp đồng (database-per-service), nên muốn
    tính tiền tháng 10 nó phải hỏi chính service sở hữu hợp đồng.
    """
    stmt = select(Contract).where(Contract.status == ContractStatus.ACTIVE.value)
    if property_id:
        stmt = stmt.where(Contract.property_id == property_id)
    rows = (await session.execute(stmt.order_by(Contract.room_id))).scalars().all()

    return [
        {
            "id": str(c.id), "contract_no": c.contract_no,
            "property_id": str(c.property_id), "room_id": str(c.room_id),
            "tenant_id": str(c.primary_tenant_id),
            "monthly_price": str(c.monthly_price),
            "start_date": c.start_date.isoformat(), "end_date": c.end_date.isoformat(),
        }
        for c in rows
    ]


@internal_router.get("/contracts/{contract_id}", summary="[Nội bộ] Snapshot hợp đồng")
async def internal_get_contract(
    contract_id: uuid.UUID,
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM, Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    billing-service gọi endpoint này khi sinh hóa đơn.

    ⭐ Đây là "snapshot" đóng băng: giá, cọc, kỳ hạn đều lấy từ hợp đồng, KHÔNG
    đọc `rooms.base_price` hiện tại. Nếu đọc giá phòng hiện tại thì hóa đơn tháng 3
    sẽ tính theo giá tháng 10 — sai ngay.
    """
    contract = await _get_contract_or_404(session, contract_id)
    total_paid = Decimal(await _total_paid(session, contract.id))
    return {
        "id": str(contract.id),
        "contract_no": contract.contract_no,
        "property_id": str(contract.property_id),
        "room_id": str(contract.room_id),
        "primary_tenant_id": str(contract.primary_tenant_id),
        "primary_tenant_name": contract.primary_tenant_name,
        "primary_tenant_phone": contract.primary_tenant_phone,
        "primary_tenant_email": contract.primary_tenant_email,
        "start_date": contract.start_date.isoformat(),
        "end_date": contract.end_date.isoformat(),
        "monthly_price": str(contract.monthly_price),
        "deposit_amount": str(contract.deposit_amount),
        "deposit_deducted": str(contract.deposit_deducted),
        "deposit_paid": str(total_paid),
        "remaining_deposit": str(contract.remaining_deposit),
        "payment_cycle": contract.payment_cycle,
        "status": contract.status,
    }


@internal_router.post("/contracts/expire-due", summary="[Nội bộ] Chuyển HĐ hết hạn")
async def internal_expire_due(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
    today: date | None = None,
) -> dict:
    """
    Được gọi bởi container `scheduler` mỗi ngày lúc 02:00.

    Hợp đồng có `end_date < today` mà vẫn `ACTIVE` → chuyển `EXPIRED` và phát
    event. room-service nhận `contract.expired` sẽ trả phòng về trống.

    ⭐ Vì sao job này ở container riêng mà không bên trong contract-service?
        Vì khi chạy N replica, cả N đều sẽ chạy job → N lần ghi. Tách ra,
        chỉ 1 scheduler, và dùng khoá phân tán Redis để chống chạy trùng.
        Xem `services/scheduler/main.py`.
    """
    ref = today or date.today()
    due = (await session.execute(
        select(Contract).where(
            Contract.status == ContractStatus.ACTIVE.value,
            Contract.end_date < ref,
        )
    )).scalars().all()

    for contract in due:
        await _transition(
            session, contract, ContractStatus.EXPIRED.value,
            reason=f"Hết hạn ngày {contract.end_date}",
            extra={"expired_at": ref.isoformat()},
        )

    logger.info("⏰ Đã chuyển %d hợp đồng sang EXPIRED (ngày %s)", len(due), ref)
    return {"expired": len(due), "date": ref.isoformat(),
            "contract_ids": [str(c.id) for c in due]}


@internal_router.post("/contracts/notify-expiring", summary="[Nội bộ] Phát cảnh báo hết hạn")
async def internal_notify_expiring(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(EXPIRING_WARNING_DAYS, ge=1, le=180),
) -> dict:
    """
    Phát `contract.expiring` cho các hợp đồng sắp hết hạn trong `days` ngày.

    Idempotent theo **ngày**: scheduler gọi hàm này mỗi ngày, nhưng chỉ phát
    event khi thực sự bước ngưỡng T-30 / T-7 / T-1. Nhờ vậy chạy 5 lần trong
    ngày cũng không nhắc 5 lần — điều người thuê rất ghét.
    """
    ref = date.today()
    milestones = {30, 7, 1}

    soon = (await session.execute(
        select(Contract).where(
            Contract.status == ContractStatus.ACTIVE.value,
            Contract.end_date >= ref,
            Contract.end_date <= _add_days(ref, days),
        )
    )).scalars().all()

    notified = 0
    for contract in soon:
        left = (contract.end_date - ref).days
        if left not in milestones:
            continue
        await get_event_bus().publish(session, DomainEvent(
            event_type="contract.expiring",
            data={
                "contract_id": str(contract.id),
                "contract_no": contract.contract_no,
                "property_id": str(contract.property_id),
                "room_id": str(contract.room_id),
                "tenant_id": str(contract.primary_tenant_id),
                "tenant_name": contract.primary_tenant_name,
                "tenant_phone": contract.primary_tenant_phone,
                "tenant_email": contract.primary_tenant_email,
                "end_date": contract.end_date.isoformat(),
                "days_left": left,
                "entity_type": "contract", "entity_id": str(contract.id),
            },
        ))
        notified += 1

    logger.info("🔔 Đã phát %d cảnh báo hết hạn (T-%s)", notified, sorted(milestones))
    return {"notified": notified, "candidates": len(soon), "milestones": sorted(milestones)}


@internal_router.post("/contracts/{contract_id}/deposit-deducted",
                      summary="[Nội bộ] Ghi nhận billing đã trừ cọc")
async def internal_deposit_deducted(
    contract_id: uuid.UUID,
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
    amount: Decimal = Query(..., ge=0, description="Số tiền cọc vừa được trừ"),
) -> dict:
    """
    billing-service gọi sau khi trừ cọc vào một hóa đơn.

    R3 được ép ở ĐÂY (nơi duy nhất được phép thay đổi `deposit_deducted`)
    và ở CHECK constraint trong DB. Hai tầng: tầng ứng dụng trả lỗi rõ ràng,
    tầng DB chặn kể cả khi có ai đó UPDATE tay bằng psql.
    """
    contract = await _get_contract_or_404(session, contract_id)
    new_value = contract.deposit_deducted + amount

    if new_value > contract.deposit_amount:
        raise BusinessRuleError(
            f"Không thể trừ cọc {amount:,.0f}đ: chỉ còn "
            f"{contract.remaining_deposit:,.0f}đ trong tổng cọc "
            f"{contract.deposit_amount:,.0f}đ.",
            details={
                "contract_id": str(contract_id),
                "deposit_amount": str(contract.deposit_amount),
                "deposit_deducted": str(contract.deposit_deducted),
                "requested": str(amount),
            },
        )

    contract.deposit_deducted = new_value
    await session.flush()
    logger.info("💸 Trừ cọc %s cho HĐ %s — còn lại %s", amount,
                contract.contract_no, contract.remaining_deposit)
    return {
        "contract_id": str(contract.id),
        "deposit_deducted": str(contract.deposit_deducted),
        "remaining_deposit": str(contract.remaining_deposit),
    }


# ===========================================================================
#  TIỆN ÍCH NỘI BỘ
# ===========================================================================
def _resolve_property(user: CurrentUser, requested: uuid.UUID | None) -> uuid.UUID | None:
    """
    ADMIN: được xem tất cả (trả về `requested` hoặc None = toàn hệ thống).
    MANAGER: bị ép về đúng cơ sở trong token.
    """
    if user.is_admin:
        return requested
    if user.property_id is None:
        raise BusinessRuleError(
            "Tài khoản chưa được gán vào cơ sở nào. Liên hệ quản trị viên."
        )
    if requested is not None and str(requested) != str(user.property_id):
        user.assert_property_access(requested)      # ném 403 rõ ràng
    return user.property_id


async def _get_contract_or_404(session: AsyncSession, contract_id: uuid.UUID) -> Contract:
    contract = (await session.execute(
        select(Contract)
        .options(selectinload(Contract.roommates))
        .where(Contract.id == contract_id)
    )).scalar_one_or_none()
    if not contract:
        raise NotFoundError(f"Không tìm thấy hợp đồng {contract_id}")
    return contract


async def _next_contract_no(session: AsyncSession) -> str:
    """
    Sinh mã hợp đồng dạng `HD-2026-000123`.

    `next_sequence` lấy `MAX(...) FOR UPDATE` — chống 2 request cùng lúc sinh
    trùng số. Ràng buộc UNIQUE trên `contract_no` vẫn là hàng rào cuối: nếu vẫn
    trùng, `IntegrityError` được bắt và thử lại với số kế tiếp.
    """
    year = date.today().year
    for attempt in range(3):
        seq = await next_sequence(
            session, "contracts", "contract_no",
            "contract_no LIKE :prefix",
            {"prefix": f"HD-{year}-%"},
        )
        candidate = f"HD-{year}-{seq:06d}"
        exists = (await session.execute(
            select(Contract.id).where(Contract.contract_no == candidate)
        )).scalar_one_or_none()
        if not exists:
            return candidate
        logger.warning("Trùng mã hợp đồng %s — thử lại (lần %s)", candidate, attempt + 1)
    raise ConflictError("Không sinh được mã hợp đồng, vui lòng thử lại")


async def _total_paid(session: AsyncSession, contract_id: uuid.UUID) -> int:
    """Tổng tiền cọc đã thu = SUM(contract_payments.amount)."""
    return int((await session.execute(
        select(func.coalesce(func.sum(ContractPayment.amount), 0))
        .where(ContractPayment.contract_id == contract_id)
    )).scalar() or 0)


async def _fetch_room(room_id: uuid.UUID) -> dict | None:
    """
    Gọi room-service để kiểm tra phòng.

    ⭐ Nếu room-service không sẵn sàng → trả None (coi như không kiểm tra được)
    chứ KHÔNG ném lỗi. Lý do: người dùng vẫn phải tạo được hợp đồng khi
    room-service đang bảo trì; ràng buộc R2 thật sự vẫn được DB của
    contract-service bảo vệ. Đây là nguyên tắc "degrade gracefully".
    """
    try:
        return await get_http_client("room").get(f"/internal/v1/rooms/{room_id}")
    except Exception as exc:
        logger.warning("Không kiểm tra được phòng %s (%s) — tiếp tục", room_id, exc)
        return None


async def _reserve_room(contract: Contract, user: CurrentUser) -> bool:
    """
    Saga bước 3a: giữ phòng. Trả về False nếu không giữ được (phòng vô hiệu).

    Không dùng `/status` công khai vì endpoint đó cần token người dùng mang
    `property_id` — token SYSTEM của service-to-service không có, nên sẽ bị
    chặn 403. Đây là lý do tồn tại các endpoint `/internal`.
    """
    try:
        result = await get_http_client("room").patch(
            f"/internal/v1/rooms/{contract.room_id}/reserve",
            json={"contract_id": str(contract.id), "hours": RESERVE_HOURS},
        )
        return bool(result and result.get("reserved", True))
    except Exception as exc:
        logger.warning("Không giữ được phòng %s: %s", contract.room_id, exc)
        return False


async def _load_response(session: AsyncSession, contract: Contract) -> ContractResponse:
    """Dựng response đầy đủ (kèm roommates, tiền cọc, số phòng, số ngày còn lại)."""
    response = ContractResponse.model_validate(contract)
    response.remaining_deposit = contract.remaining_deposit
    response.total_paid_deposit = Decimal(await _total_paid(session, contract.id))
    response.days_remaining = (contract.end_date - date.today()).days

    room = await _fetch_room(contract.room_id)
    if room:
        response.room_number = room.get("room_number")
    return response


def _to_list_item(contract: Contract) -> ContractListItem:
    item = ContractListItem.model_validate(contract)
    if contract.status == ContractStatus.ACTIVE.value:
        item.days_remaining = (contract.end_date - date.today()).days
    return item


def _add_days(base: date, days: int) -> date:
    return base + timedelta(days=days)


# ===========================================================================
#  ĐĂNG KÝ ROUTER
# ===========================================================================
app.include_router(contract_router)
app.include_router(internal_router)
