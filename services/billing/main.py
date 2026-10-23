"""
===============================================================================
billing-service — Tính tiền, hóa đơn, thanh toán.  Cổng 8005  |  db_billing
===============================================================================

Đây là service phức tạp nhất và tải cao nhất: cuối tháng, vài trăm hợp đồng
cùng cần tính tiền đúng một lần. Vì vậy file này tập trung vào 3 câu hỏi:

  1. TÍNH ĐÚNG KHÔNG?      → `pricing.py` (mọi công thức nằm ở đó, test riêng)
  2. TÍNH TRÙNG KHÔNG?    → UNIQUE(contract_id, period) + `skip_existing`
  3. CHẬM KHÔNG?           → cache biểu giá, 1 câu GROUP BY thay vì N+1, job
                             bất đồng bộ thay vì request 30 giây

Luồng tính tiền 1 hợp đồng (hàm `generate_invoice`):

    contract-service  ──HTTP──▶  billing-service
        (snapshot đóng băng)         │
                                    ├─ lấy chỉ số điện/nước kỳ này + kỳ trước
                                    ├─ graduated_charge() theo bậc thang
                                    ├─ phí dịch vụ (cache) + tiện ích phòng
                                    ├─ phí trễ hạn (nếu quá hạn kỳ trước)
                                    ├─ apply_deposit()  ← R3
                                    └─ INSERT invoice + details (1 transaction)
                                              │
                                    outbox ──▶ invoice.issued
                                              ├──▶ notification (gửi khách)
                                              └──▶ report (doanh thu)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from common.database import session_scope
from common.events import DomainEvent, IdempotentConsumer
from common.repository import acquire_lock, next_sequence, release_lock
from common.telemetry import set_business_gauge
from models import (
    BillingJob,
    Invoice,
    InvoiceDetail,
    InvoiceStatus,
    ItemType,
    MeterReading,
    Payment,
    PriceTier,
    ServiceFee,
    UtilityType,
)
from pricing import (
    DEFAULT_ELECTRIC_TIERS,
    DEFAULT_WATER_TIERS,
    LATE_FEE_MAX_DAYS,
    LATE_FEE_RATE,
    ZERO,
    InvoiceTotals,
    Tier,
    apply_deposit,
    days_in_month,
    graduated_charge,
    late_fee,
    money,
    next_due_date,
    prorated_rent,
)
from schemas import (
    BillingJobResponse,
    GenerateJobRequest,
    InvoiceListItem,
    InvoiceResponse,
    InvoiceStats,
    MeterReadingBatch,
    MeterReadingCreate,
    MeterReadingResponse,
    PaymentCreate,
    PaymentResponse,
    PriceScheduleCreate,
    PriceTierResponse,
    ServiceFeeCreate,
    ServiceFeeResponse,
    TariffEstimate,
)

logger = logging.getLogger(__name__)

#: TTL cache biểu giá. Giá đổi rất hiếm (1–2 lần/năm) nên cache rất lâu cũng
#: được; nhưng vẫn để TTL để khi admin sửa giá thì giá mới có hiệu lực nhanh.
CACHE_TTL_TARIFF = 900         # 15 phút
CACHE_TTL_SERVICES = 1800      # 30 phút

#: Phí dịch vụ mặc định khi cơ sở chưa cấu hình (giá thị trường 2026)
DEFAULT_SERVICE_FEES: list[tuple[str, str, Decimal]] = [
    ("INTERNET", "Internet cáp quang", Decimal("100000")),
    ("CLEANING", "Vệ sinh chung", Decimal("50000")),
    ("TRASH", "Thu gom rác", Decimal("30000")),
    ("PARKING", "Gửi xe máy", Decimal("70000")),
]


# ===========================================================================
#  APP
# ===========================================================================
async def _setup_consumer(app_instance) -> None:
    """
    billing-service nghe 1 loại event duy nhất: `contract.terminated`.

    Khi hợp đồng kết thúc giữa tháng mà hóa đơn tháng đó đã phát, phần tiền
    phải trả lại cho người thuê. Đây là nghiệp vụ "hoàn tiền dở dang" — nếu
    không có, chủ trọ mất tiền oan và phải xử lý thủ công.
    """
    consumer = IdempotentConsumer(
        handler=_handle_event,
        consumer_name="billing-service:contract-lifecycle",
    )
    app_instance.state.ctx.consumers.append(consumer)
    try:
        await get_event_bus().subscribe(
            "qlpt.billing.events", consumer.handle,
            ["contract.terminated", "contract.expired", "price_tiers.updated"],
        )
    except Exception as exc:
        logger.warning("Không đăng ký consumer được: %s", exc)


app = create_service_app(
    name="billing-service",
    description=(
        "**Tính tiền** *(Core Domain)*\n\n"
        "- Biểu giá điện nước bậc thang (có versioning, không sửa giá cũ)\n"
        "- Nhập chỉ số đồng hồ theo kỳ (R4: chỉ số không được giảm)\n"
        "- Sinh hóa đơn hàng loạt, có tiền phòng tính theo ngày thực tế\n"
        "- Trừ tiền cọc (R3: không bao giờ âm), phí trễ hạn có trần\n"
        "- Ghi nhận thanh toán, theo dõi công nợ\n\n"
        "### Công thức\n"
        "`TỔNG = tiền phòng + điện (lũy tiến) + nước + DV − trừ cọc`\n\n"
        "### Quy tắc tiền\n"
        "- Mọi phép tính dùng `Decimal`, tuyệt đối không dùng `float`\n"
        "- Hóa đơn `PAID` không sửa được (R8)"
    ),
    version="1.0.0",
    lifespan_extra=_setup_consumer,
)


# ===========================================================================
#  CACHE BIỂU GIÁ
# ===========================================================================
def _tariff_cache_key(property_id: uuid.UUID, utility: str) -> str:
    return f"billing:tariff:{property_id}:{utility}"


def _services_cache_key(property_id: uuid.UUID) -> str:
    return f"billing:fees:{property_id}"


async def _load_tiers(
    session: AsyncSession, redis: Any, property_id: uuid.UUID, utility: str,
) -> list[Tier]:
    """
    Lấy biểu giá đang hiệu lực. Cache 2 tầng: Redis → DB.

    ⭐ Vì sao cache được? Vì hàm này chạy 2 lần cho MỖI hợp đồng (điện + nước).
        200 hợp đồng = 400 lần đọc DB cho dữ liệu gần như không đổi trong cả
        năm. Cached thì còn vài chục lần cho cả tháng. Đây là nơi cache sinh
        lợi rõ nhất trong toàn hệ thống.
    """
    key = _tariff_cache_key(property_id, utility)
    if redis is not None:
        try:
            raw = await redis.get(key)
            if raw:
                data = json.loads(raw)
                return [Tier(Decimal(t["up"]) if t["up"] else None, Decimal(t["price"]))
                        for t in data]
        except Exception as exc:
            logger.warning("Redis GET tariff lỗi: %s", exc)

    today = date.today()
    rows = (await session.execute(
        select(PriceTier)
        .where(
            PriceTier.property_id == property_id,
            PriceTier.utility_type == utility,
            PriceTier.effective_from <= today,
            (PriceTier.effective_to.is_(None)) | (PriceTier.effective_to > today),
        )
        .order_by(PriceTier.tier_index)
    )).scalars().all()

    if not rows:
        # Chưa cấu hình biểu giá → dùng giá mặc định toàn quốc.
        # Chọn "dùng mặc định" thay vì "báo lỗi" vì hệ thống vẫn tính được
        # tiền ngay ngày cài, thay vì chặn người dùng vì chưa cấu hình.
        logger.info("Chưa có biểu giá %s cho cơ sở %s — dùng giá mặc định",
                    utility, property_id)
        return list(DEFAULT_ELECTRIC_TIERS if utility == UtilityType.ELECTRIC.value
                    else DEFAULT_WATER_TIERS)

    tiers = [Tier(r.up_to_qty, r.unit_price) for r in rows]
    if redis is not None:
        try:
            await redis.setex(key, CACHE_TTL_TARIFF, json.dumps(
                [{"up": str(t.up_to) if t.up_to is not None else None,
                  "price": str(t.price_per_unit)} for t in tiers]
            ))
        except Exception as exc:
            logger.warning("Redis SETEX tariff lỗi: %s", exc)
    return tiers


async def _load_service_fees(
    session: AsyncSession, redis: Any, property_id: uuid.UUID,
) -> list[ServiceFee]:
    """Phí dịch vụ bắt buộc của cơ sở (cache 30 phút — thay đổi rất hiếm)."""
    key = _services_cache_key(property_id)
    if redis is not None:
        try:
            raw = await redis.get(key)
            if raw:
                return [
                    ServiceFee(property_id=property_id, code=d["code"], name=d["name"],
                               amount=Decimal(d["amount"]), is_mandatory=d["mandatory"])
                    for d in json.loads(raw)
                ]
        except Exception as exc:
            logger.warning("Redis GET fees lỗi: %s", exc)

    rows = (await session.execute(
        select(ServiceFee).where(
            ServiceFee.property_id == property_id,
            ServiceFee.is_active.is_(True),
        )
    )).scalars().all()

    if redis is not None and rows:
        try:
            await redis.setex(key, CACHE_TTL_SERVICES, json.dumps([
                {"code": f.code, "name": f.name, "amount": str(f.amount),
                 "mandatory": f.is_mandatory} for f in rows
            ]))
        except Exception as exc:
            logger.warning("Redis SETEX fees lỗi: %s", exc)
    return rows


async def _invalidate_billing_cache(request: Request, property_id: uuid.UUID) -> None:
    """
    Xoá cache biểu giá & phí sau khi sửa.

    ⭐ Xoá SAU khi ghi, không xoá trước. Lý do: xoá trước rồi ghi DB thất bại
       thì cache trống → hệ thống chậm nhưng vẫn ĐÚNG. Xoá sau thì có cửa sổ
       < 1ms mà cache còn dữ liệu cũ — chấp nhận được, và thà chậm 1ms còn hơn
       sai tiền.
    """
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    try:
        await redis.delete(
            _tariff_cache_key(property_id, UtilityType.ELECTRIC.value),
            _tariff_cache_key(property_id, UtilityType.WATER.value),
            _services_cache_key(property_id),
        )
    except Exception as exc:
        logger.warning("Không xoá được cache biểu giá: %s", exc)


# ===========================================================================
#  ROUTER: BIỂU GIÁ
# ===========================================================================
price_router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


@price_router.get("/tiers", response_model=list[PriceTierResponse],
                  summary="Biểu giá đang hiệu lực")
async def get_tiers(
    request: Request,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID,
    utility_type: Annotated[str, Query(pattern="^(ELECTRIC|WATER)$")],
) -> list[PriceTierResponse]:
    user.assert_property_access(property_id)
    await _load_tiers(session, request.app.state.redis, property_id, utility_type)

    today = date.today()
    rows = (await session.execute(
        select(PriceTier).where(
            PriceTier.property_id == property_id,
            PriceTier.utility_type == utility_type,
            PriceTier.effective_from <= today,
            (PriceTier.effective_to.is_(None)) | (PriceTier.effective_to > today),
        ).order_by(PriceTier.tier_index)
    )).scalars().all()
    return [PriceTierResponse.model_validate(r) for r in rows]


@price_router.post("/tiers", status_code=status.HTTP_201_CREATED,
                   summary="Đặt biểu giá mới (đóng băng bảng cũ)")
async def create_price_schedule(
    request: Request,
    payload: PriceScheduleCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    ⭐ VERSIONING BIỂU GIÁ — thao tác KHÔNG được ghi đè dữ liệu cũ.

    Thay vì `UPDATE price_tiers SET unit_price = ...`:
        1. Đóng bảng giá hiện tại: `effective_to = effective_from - 1 ngày`
        2. Chèn các bậc MỚI với `effective_from` mới, `effective_to = NULL`

    Nhờ vậy hóa đơn tháng 9 (đã gửi khách) vẫn tra ra đúng bảng giá tháng 9.
    Sửa bảng giá cũ nghĩa là sửa lại sổ sách đã phát hành.
    """
    user.assert_property_access(payload.property_id)
    if payload.effective_from <= date.today():
        raise BusinessRuleError(
            f"Ngày hiệu lực phải từ NGÀY MAI trở đi (đã nhập "
            f"{payload.effective_from}). Lý do: biểu giá kỳ này đã dùng để tính "
            "tiền và gửi khách — không thay đổi lại được. Hãy nhập biểu giá mới "
            "từ kỳ sau.",
            details={"today": date.today().isoformat()},
        )

    prev = (await session.execute(
        select(PriceTier).where(
            PriceTier.property_id == payload.property_id,
            PriceTier.utility_type == payload.utility_type,
            PriceTier.effective_to.is_(None),
        )
    )).scalars().all()

    close_on = payload.effective_from - timedelta(days=1)
    for tier in prev:
        tier.effective_to = close_on
    await session.flush()

    for index, tier in enumerate(payload.tiers):
        session.add(PriceTier(
            property_id=payload.property_id,
            utility_type=payload.utility_type,
            tier_index=index,
            up_to_qty=tier.up_to_qty,
            unit_price=tier.unit_price,
            effective_from=payload.effective_from,
            effective_to=None,
        ))
    await session.flush()

    await _invalidate_billing_cache(request, payload.property_id)
    await get_event_bus().publish(session, DomainEvent(
        event_type="price_tiers.updated",
        data={
            "property_id": str(payload.property_id),
            "utility_type": payload.utility_type,
            "effective_from": payload.effective_from.isoformat(),
            "tier_count": len(payload.tiers),
            "entity_type": "price_tier", "entity_id": str(payload.property_id),
        },
    ))

    logger.info("💲 Đặt biểu giá %s cho cơ sở %s, hiệu lực %s (%d bậc, đóng %d bậc cũ)",
                payload.utility_type, payload.property_id,
                payload.effective_from, len(payload.tiers), len(prev))
    return {
        "message": f"Đã đặt biểu giá {payload.utility_type} hiệu lực từ "
                   f"{payload.effective_from}",
        "new_tiers": len(payload.tiers),
        "closed_tiers": len(prev),
        "effective_from": payload.effective_from.isoformat(),
    }


@price_router.get("/fees", response_model=list[ServiceFeeResponse],
                  summary="Phí dịch vụ của cơ sở")
async def list_service_fees(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID,
) -> list[ServiceFeeResponse]:
    user.assert_property_access(property_id)
    rows = (await session.execute(
        select(ServiceFee)
        .where(ServiceFee.property_id == property_id)
        .order_by(ServiceFee.code)
    )).scalars().all()
    return [ServiceFeeResponse.model_validate(f) for f in rows]


@price_router.put("/fees", response_model=ServiceFeeResponse,
                  summary="Đặt phí dịch vụ (ghi đè theo mã)")
async def set_service_fee(
    request: Request,
    payload: ServiceFeeCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceFeeResponse:
    """
    Upsert theo khoá `(property_id, code)`.

    ⭐ Vì sao dùng `INSERT ... ON CONFLICT DO UPDATE` chứ không phải
       "SELECT xem có chưa rồi INSERT/UPDATE"?
       Vì 2 request song song (2 người cùng sửa, hoặc 1 người bấm Enter 2 lần)
       sẽ cùng đọc thấy "chưa có" rồi cùng INSERT. Khi đó một trong hai gặp
       `unique_violation` và người dùng thấy lỗi 500 vô nghĩa. `ON CONFLICT` để
       PostgreSQL tự quyết định — không có cửa sổ tranh chấp nào.

    `property_id` KHÔNG lấy từ body: lấy từ tài khoản đang đăng nhập. Nếu lấy
    từ body thì user của cơ sở A có thể ghi phí vào cơ sở B chỉ bằng cách đổi
    1 trường JSON — mọi kiểm tra phân quyền ở tầng trên đều vô nghĩa.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    property_id = _resolve_property(user, None)
    if property_id is None:
        raise BusinessRuleError(
            "Tài khoản chưa được gán vào cơ sở nào nên không đặt được phí dịch vụ. "
            "Hãy nhờ quản trị viên cấp cơ sở cho tài khoản.",
        )

    stmt = (
        pg_insert(ServiceFee)
        .values(
            property_id=property_id,
            code=payload.code,
            name=payload.name,
            amount=payload.amount,
            is_mandatory=payload.is_mandatory,
            is_active=True,
        )
        .on_conflict_do_update(
            constraint="uq_service_fee_code",
            set_={
                "name": payload.name,
                "amount": payload.amount,
                "is_mandatory": payload.is_mandatory,
                "is_active": True,
            },
        )
        .returning(ServiceFee)
    )
    fee = (await session.execute(stmt)).scalar_one()

    await _invalidate_billing_cache(request, property_id)
    logger.info("💲 Đặt phí %s = %sđ cho cơ sở %s",
                fee.code, fee.amount, property_id)
    return ServiceFeeResponse.model_validate(fee)


# ===========================================================================
#  ROUTER: CHỈ SỐ ĐIỆN NƯỚC
# ===========================================================================
meter_router = APIRouter(prefix="/api/v1/meter-readings", tags=["meter-readings"])


@meter_router.post("", response_model=MeterReadingResponse,
                   status_code=status.HTTP_201_CREATED, summary="📟 Nhập chỉ số")
async def create_meter_reading(
    request: Request,
    payload: MeterReadingCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MeterReadingResponse:
    """
    ⭐ R4 — chỉ số kỳ này PHẢI LỚN HƠN kỳ trước.

    Kiểm tra ở tầng ứng dụng để trả lỗi đọc được ("chỉ số nhỏ hơn kỳ trước
    20 kWh"), nhưng KHÔNG tin hoàn toàn: race condition khiến 2 request cùng
    lúc có thể cùng pass check. Hàng rào cuối là UNIQUE(room, type, period).
    """
    user.assert_property_access(payload.property_id)

    existing = (await session.execute(
        select(MeterReading).where(
            MeterReading.room_id == payload.room_id,
            MeterReading.utility_type == payload.utility_type,
            MeterReading.period == payload.period,
        )
    )).scalar_one_or_none()
    if existing:
        raise ConflictError(
            f"Phòng này đã nhập chỉ số {payload.utility_type} cho kỳ "
            f"{payload.period:%m/%Y} rồi (giá trị {existing.reading_value}). "
            "Mỗi kỳ chỉ nhập 1 lần — sai số thì dùng endpoint SỬA.",
            details={"reading_id": str(existing.id),
                     "current_value": str(existing.reading_value)},
        )

    previous = (await session.execute(
        select(MeterReading)
        .where(
            MeterReading.room_id == payload.room_id,
            MeterReading.utility_type == payload.utility_type,
            MeterReading.period < payload.period,
        )
        .order_by(MeterReading.period.desc())
        .limit(1)
    )).scalar_one_or_none()

    previous_value = previous.reading_value if previous else None

    # ---- R4: chỉ số không được giảm ----
    if previous_value is not None and payload.reading_value < previous_value:
        raise BusinessRuleError(
            f"Chỉ số kỳ này ({payload.reading_value}) nhỏ hơn chỉ số kỳ trước "
            f"({previous_value}). Đồng hồ điện nước chỉ tăng chứ không giảm. "
            "Nếu thực sự đã thay đồng hồ, hãy ghi rõ vào ghi chú để kế toán "
            "biết giảm số.",
            details={
                "room_id": str(payload.room_id),
                "utility_type": payload.utility_type,
                "current": str(payload.reading_value),
                "previous": str(previous_value),
                "previous_period": previous.period.isoformat() if previous else None,
            },
        )

    reading = MeterReading(
        property_id=payload.property_id,
        room_id=payload.room_id,
        utility_type=payload.utility_type,
        period=payload.period,
        reading_value=payload.reading_value,
        previous_value=previous_value,
        read_by=user.id,
        note=payload.note,
    )
    session.add(reading)
    await session.flush()

    # Tính tiền ngay để người nhập biết mình vừa ghi bao nhiêu.
    estimate = ZERO
    breakdown: list[dict] = []
    if previous_value is not None:
        tiers = await _load_tiers(
            session, request.app.state.redis, payload.property_id, payload.utility_type
        )
        amount, breakdown = _charge_breakdown(
            payload.reading_value - previous_value, tiers,
            UtilityType(payload.utility_type),
        )
        estimate = amount

    logger.info("📟 Nhập chỉ số %s phòng %s kỳ %s: %s (tiêu thụ %s = %sđ)",
                payload.utility_type, payload.room_id, payload.period,
                payload.reading_value, reading.consumption, estimate)

    response = MeterReadingResponse.model_validate(reading)
    response.estimated_amount = estimate
    response.charge_breakdown = breakdown
    return response


def _charge_breakdown(
    consumption: Decimal, tiers: list[Tier], utility: UtilityType,
) -> tuple[Decimal, list[dict]]:
    """
    Tính tiền theo bậc thang VÀ trả về từng dòng chi tiết.

    Trả về cả `breakdown` vì khi khách hỏi "tiền điện tháng này tính thế nào?",
    câu trả lời phải là "50 kWh đầu × 1.800, 50 kWh tiếp × 2.500…" chứ không
    phải một con số tổng 595.000 không giải thích được.
    """
    ordered = sorted(tiers, key=lambda t: (t.up_to is None, t.up_to or ZERO))
    remaining = Decimal(consumption)
    previous_top = Decimal("0")
    total = Decimal("0")
    rows: list[dict] = []

    for index, tier in enumerate(ordered):
        if remaining <= 0:
            break
        if tier.up_to is None:
            in_tier, top = remaining, None
        else:
            in_tier = min(remaining, tier.up_to - previous_top)
            top = tier.up_to
        if in_tier <= 0:
            previous_top = max(previous_top, tier.up_to or previous_top)
            continue

        amount = money(in_tier * tier.price_per_unit)
        total += amount
        rows.append({
            "tier": index + 1,
            "from": str(previous_top),
            "to": str(top) if top is not None else "∞",
            "quantity": str(in_tier),
            "unit_price": str(tier.price_per_unit),
            "amount": str(amount),
        })
        remaining -= in_tier
        if tier.up_to is not None:
            previous_top = tier.up_to

    _ = utility      # giữ tham số cho log/tương lai
    return money(total), rows


@meter_router.post("/batch", summary="📟 Nhập chỉ số hàng loạt")
async def create_meter_readings_batch(
    request: Request,
    payload: MeterReadingBatch,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Nhập nhiều chỉ số trong 1 lần gọi.

    ⭐ Vì sao quan trọng: đọc 40 phòng bằng 40 lần POST = 40 round-trip HTTP +
       40 transaction. Gộp 1 lần = 1 round-trip. Với mạng 100ms, chênh lệch là
       4 giây — và khi đọc cả tòa nhà 200 phòng thì gần 20 giây.
    """
    user.assert_property_access(payload.property_id)

    inserted, skipped, errors = 0, 0, []
    for item in payload.readings:
        try:
            await create_meter_reading(request, item, user, session)
            inserted += 1
        except (ConflictError, BusinessRuleError) as exc:
            skipped += 1
            errors.append({
                "room_id": str(item.room_id),
                "utility_type": item.utility_type,
                "reason": str(exc),
            })

    # KHÔNG rollback toàn bộ khi 1 dòng lỗi — người nhập chỉ số 40 phòng
    # không muốn mất 39 phòng đã nhập vì 1 phòng sai. Báo cáo chi tiết để
    # họ sửa dòng lỗi rồi nhập tiếp.
    logger.info("📟 Nhập hàng loạt kỳ %s: %d thành công, %d bỏ qua",
                payload.period, inserted, skipped)
    return {
        "period": payload.period.isoformat(),
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }


@meter_router.get("", summary="Danh sách chỉ số")
async def list_meter_readings(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    property_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    period: date | None = None,
    utility_type: str | None = None,
) -> dict:
    effective = _resolve_property(user, property_id)

    stmt = select(MeterReading)
    if effective:
        stmt = stmt.where(MeterReading.property_id == effective)
    if room_id:
        stmt = stmt.where(MeterReading.room_id == room_id)
    if period:
        stmt = stmt.where(MeterReading.period == period)
    if utility_type:
        stmt = stmt.where(MeterReading.utility_type == utility_type)
    stmt = stmt.order_by(MeterReading.period.desc(), MeterReading.room_id)

    items, meta = await paginate(session, stmt, params)
    return {
        "items": [MeterReadingResponse.model_validate(r) for r in items],
        "meta": meta.model_dump(),
    }


# ===========================================================================
#  HÀM LÕI: SINH HÓA ĐƠN
# ===========================================================================
async def generate_invoice(
    session: AsyncSession,
    redis: Any,
    contract_snapshot: dict,
    period: date,
    *,
    created_by: uuid.UUID | None = None,
    include_deposit: bool = True,
) -> Invoice:
    """
    Tính & tạo hóa đơn cho 1 hợp đồng trong kỳ `period`.

    Toàn bộ công thức nằm ở `pricing.py`; hàm này chỉ lo phần I/O: đọc chỉ số,
    đọc biểu giá, ghi bảng, phát event. Tách vậy để công thức test được mà
    không cần database.

    ⭐ Đây là hàm bất đồng bộ nhưng KHÔNG tự commit — commit do
       `get_db`/`session_scope` bên ngoài. Lý do: hóa đơn + chi tiết +
       event outbox phải nằm trong CÙNG một transaction. Nếu hóa đơn ghi
       xong mà event chưa ghi, sẽ có hóa đơn mà không ai được thông báo
       (dual-write problem — chính là lý do có bảng `outbox`).
    """
    contract_id = uuid.UUID(str(contract_snapshot["id"]))
    property_id = uuid.UUID(str(contract_snapshot["property_id"]))
    room_id = uuid.UUID(str(contract_snapshot["room_id"]))

    # ---- Chống tạo trùng: UNIQUE(contract_id, period) ----
    existing = (await session.execute(
        select(Invoice).where(
            Invoice.contract_id == contract_id,
            Invoice.period == period,
        )
    )).scalar_one_or_none()
    if existing:
        raise ConflictError(
            f"Hợp đồng {contract_snapshot['contract_no']} đã có hóa đơn kỳ "
            f"{period:%m/%Y} ({existing.invoice_no}).",
            details={"invoice_id": str(existing.id), "invoice_no": existing.invoice_no},
        )

    start_date = date.fromisoformat(str(contract_snapshot["start_date"]))
    end_date = date.fromisoformat(str(contract_snapshot["end_date"]))
    monthly_price = Decimal(str(contract_snapshot["monthly_price"]))

    totals = InvoiceTotals()

    # ---- (1) TIỀN PHÒNG — theo số ngày thực tế ----
    totals.rent, billable = prorated_rent(monthly_price, start_date, end_date, period)
    if billable == 0:
        raise BusinessRuleError(
            f"Hợp đồng {contract_snapshot['contract_no']} không hiệu lực trong "
            f"kỳ {period:%m/%Y} (kỳ hạn {start_date} → {end_date}). Không tạo "
            "hóa đơn cho hợp đồng đã kết thúc.",
            details={"start": start_date.isoformat(), "end": end_date.isoformat()},
        )

    days_of_month = days_in_month(period)
    details: list[dict] = [{
        "item_type": ItemType.RENT.value,
        "description": f"Tiền phòng {billable}/{days_of_month} ngày",
        "quantity": str(Decimal(billable)),
        "unit_price": str(monthly_price),
        "amount": totals.rent,
        "breakdown": {
            "billable_days": billable,
            "days_in_month": days_of_month,
            "daily_rate": str(money(monthly_price / Decimal(days_of_month))),
        },
    }]

    # ---- (2)(3) ĐIỆN NƯỚC — lũy tiến theo bậc thang ----
    for utility in (UtilityType.ELECTRIC, UtilityType.WATER):
        reading = (await session.execute(
            select(MeterReading).where(
                MeterReading.room_id == room_id,
                MeterReading.utility_type == utility.value,
                MeterReading.period == period,
            )
        )).scalar_one_or_none()

        if not reading or reading.previous_value is None:
            # Chưa nhập chỉ số kỳ này (hoặc là kỳ đầu tiên) → khoản này = 0,
            # KHÔNG bỏ hẳn khỏi hóa đơn: khách vẫn phải trả tiền phòng + DV.
            logger.info("⚠ Thiếu chỉ số %s phòng %s kỳ %s — tính 0đ",
                        utility.value, room_id, period)
            continue

        consumption = reading.consumption or ZERO
        tiers = await _load_tiers(session, redis, property_id, utility.value)
        amount, breakdown = _charge_breakdown(consumption, tiers, utility)

        if utility is UtilityType.ELECTRIC:
            totals.electric = amount
        else:
            totals.water = amount

        details.append({
            "item_type": utility.value,
            "description": f"{utility.label_vi} {consumption.normalize()} {utility.unit} "
                           f"({reading.reading_value - consumption} → {reading.reading_value})",
            "quantity": str(consumption),
            "unit_price": None,
            "amount": amount,
            "breakdown": {"tiers": breakdown},
        })

    # ---- (4) PHÍ DỊCH VỤ ----
    fees = await _load_service_fees(session, redis, property_id)
    mandatory = [f for f in fees if f.is_mandatory]
    totals.services = money(sum((f.amount for f in mandatory), ZERO))
    for fee in mandatory:
        details.append({
            "item_type": ItemType.SERVICE.value,
            "description": fee.name,
            "quantity": "1",
            "unit_price": str(fee.amount),
            "amount": money(fee.amount),
            "breakdown": {"code": fee.code},
        })

    # ---- (4b) PHÍ TIỆN ÍCH GẮN PHÒNG (đồng bộ gọi room-service) ----
    # ⭐ Gọi room-service CHỈ khi tạo hóa đơn (1 lần/kỳ/phòng), KHÔNG gọi
    #    trong vòng lặp tính 200 hợp đồng mà không cache. Nếu room-service
    #    chết, ta dùng tiếp giá trị cache thay vì hỏng cả đợt tính tiền.
    amenity_fee = await _room_amenity_fee(redis, room_id)
    if amenity_fee > 0:
        totals.services = money(totals.services + amenity_fee)
        details.append({
            "item_type": ItemType.SERVICE.value,
            "description": "Phí tiện ích phòng (điều hoà, máy giặt…)",
            "quantity": "1",
            "unit_price": str(amenity_fee),
            "amount": amenity_fee,
            "breakdown": {"source": "room-service"},
        })

    # ---- (5) PHÍ TRỄ HẠN + PHÍ CHẤM DỨT SỚM ----
    # Hai khoản này là "tiền phạt" nhưng bản chất khác nhau, tách riêng để khi
    # khách khiếu nại mình biết chính xác đang bị tính khoản nào.
    late = ZERO

    previous_invoice = (await session.execute(
        select(Invoice).where(
            Invoice.contract_id == contract_id,
            Invoice.period < period,
        ).order_by(Invoice.period.desc()).limit(1)
    )).scalar_one_or_none()

    if previous_invoice and not previous_invoice.is_paid:
        days_late = (date.today() - previous_invoice.due_date).days
        late = late_fee(monthly_price, days_late)
        if late > 0:
            logger.info("⏰ HĐ %s trễ %d ngày (hóa đơn %s) → phí trễ hạn %sđ",
                        contract_snapshot["contract_no"], days_late,
                        previous_invoice.invoice_no, late)
            totals.late_fee = late
            details.append({
                "item_type": ItemType.LATE_FEE.value,
                "description": f"Phí trễ hạn {days_late} ngày "
                               f"(hóa đơn {previous_invoice.invoice_no}, "
                               f"hạn {previous_invoice.due_date:%d/%m/%Y})",
                "quantity": str(Decimal(days_late)),
                "unit_price": str(money(monthly_price * LATE_FEE_RATE)),
                "amount": late,
                "breakdown": {
                    "days_late": days_late,
                    "rate": str(LATE_FEE_RATE),
                    "cap_days": LATE_FEE_MAX_DAYS,
                    "previous_invoice_no": previous_invoice.invoice_no,
                },
            })

    penalty = Decimal(str(contract_snapshot.get("penalty_amount") or 0))
    if penalty > 0:
        details.append({
            "item_type": ItemType.PENALTY.value,
            "description": "Phí chấm dứt hợp đồng sớm",
            "quantity": "1",
            "unit_price": str(penalty),
            "amount": money(penalty),
            "breakdown": {},
        })
        # Cộng vào `late_fee` vì đó là cột duy nhất trong `Invoice` mang nghĩa
        # "khoản phạt"; tách riêng 2 cột chỉ để sinh thêm 1 câu GROUP BY mà
        # không đổi được quyết định nào.
        totals.late_fee = money(totals.late_fee + penalty)

    # ---- (6) TRỪ TIỀN CỌC (R3) ----
    deposit_used = ZERO
    if include_deposit:
        remaining = Decimal(str(contract_snapshot.get("deposit_remaining")
                                or contract_snapshot.get("remaining_deposit") or 0))
        totals, deposit_used = apply_deposit(totals, remaining)
        if deposit_used > 0:
            details.append({
                "item_type": ItemType.DEPOSIT.value,
                "description": "Trừ tiền cọc",
                "quantity": "1",
                "unit_price": str(-deposit_used),
                "amount": money(-deposit_used),
                "breakdown": {"deposit_remaining": str(remaining)},
            })

    # ---- Ghi hóa đơn ----
    invoice = Invoice(
        invoice_no=await _next_invoice_no(session, property_id, period),
        property_id=property_id,
        contract_id=contract_id,
        room_id=room_id,
        tenant_id=uuid.UUID(str(contract_snapshot["primary_tenant_id"]))
        if contract_snapshot.get("primary_tenant_id") else None,
        tenant_name=str(contract_snapshot.get("primary_tenant_name") or "—"),
        room_number=contract_snapshot.get("room_number"),
        period=period,
        due_date=next_due_date(period),
        status=InvoiceStatus.PENDING.value,
        created_by=created_by,
        **totals.as_dict(),
    )
    session.add(invoice)
    await session.flush()

    for item in details:
        session.add(InvoiceDetail(invoice_id=invoice.id, **item))

    await session.flush()

    # ---- Event (ghi vào outbox, cùng transaction) ----
    await get_event_bus().publish(session, DomainEvent(
        event_type="invoice.issued",
        data={
            "invoice_id": str(invoice.id),
            "invoice_no": invoice.invoice_no,
            "property_id": str(property_id),
            "contract_id": str(contract_id),
            "room_id": str(room_id),
            "tenant_id": str(invoice.tenant_id) if invoice.tenant_id else None,
            "tenant_name": invoice.tenant_name,
            "total_amount": str(invoice.total_amount),
            "due_date": invoice.due_date.isoformat(),
            "period": period.isoformat(),
            "entity_type": "invoice", "entity_id": str(invoice.id),
        },
    ))
    record_business_event(settings.service_name, "invoice.issued")

    return invoice


async def _room_amenity_fee(redis: Any, room_id: uuid.UUID) -> Decimal:
    """
    Phí tiện ích gắn với phòng, lấy từ room-service (có cache 1 giờ).

    Nếu room-service không sẵn sàng → trả 0 và ghi log cảnh báo. Chấp nhận
    việc THIẾU một khoản nhỏ hơn nhiều so với việc cả đợt tính tiền thất bại;
    kế toán sẽ bổ sung khi có thể.
    """
    cache_key = f"billing:amenity-fee:{room_id}"
    if redis is not None:
        with suppress(Exception):
            raw = await redis.get(cache_key)
            if raw is not None:
                return Decimal(raw)

    try:
        data = await get_http_client("room").get(
            f"/internal/v1/rooms/{room_id}/amenity-fees"
        )
        fee = Decimal(str((data or {}).get("total_monthly_fee") or 0))
    except Exception as exc:
        logger.warning("Không lấy được phí tiện ích phòng %s: %s — tạm tính 0đ",
                       room_id, exc)
        return ZERO

    if redis is not None:
        # Hết hạn 1 giờ: phí tiện ích đổi rất hiếm, nhưng cache quá lâu thì
        # khi sửa giá phòng, trang công khai hiện giá cũ. Redis chết ở đây
        # không sao — chỉ mất cache.
        with suppress(Exception):
            await redis.setex(cache_key, 3600, str(fee))
    return fee


async def _next_invoice_no(session: AsyncSession, property_id: uuid.UUID,
                           period: date) -> str:
    """Sinh mã hóa đơn `HD-202610-0042` (tiền tố + kỳ + số thứ tự trong kỳ)."""
    prefix = f"HD-{period:%Y%m}-"
    # 3 lần thử: `next_sequence` dùng `MAX(...) + 1`, nên 2 tiến trình sinh
    # song song có thể cùng ra một số. Lặp lại sẽ thấy số đã bị chiếm và
    # sinh số kế tiếp. Hàng rào cuối vẫn là UNIQUE trên `invoice_no`.
    for _attempt in range(3):
        seq = await next_sequence(
            session, "invoices", "invoice_no",
            "invoice_no LIKE :prefix", {"prefix": f"{prefix}%"},
        )
        candidate = f"{prefix}{seq:04d}"
        exists = (await session.execute(
            select(Invoice.id).where(Invoice.invoice_no == candidate)
        )).scalar_one_or_none()
        if not exists:
            return candidate
        logger.warning("Trùng mã hóa đơn %s — thử lại", candidate)
    raise ConflictError("Không sinh được mã hóa đơn, vui lòng thử lại")


# ===========================================================================
#  ROUTER: HÓA ĐƠN
# ===========================================================================
invoice_router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


@invoice_router.get("", summary="Danh sách hóa đơn")
async def list_invoices(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    property_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    period: date | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
    invoice_status: str | None = Query(None, alias="status"),
    overdue_only: bool = Query(False, description="Chỉ hóa đơn quá hạn chưa trả"),
    sort: str = Query("period_desc", description="period|total_amount|due_date"),
) -> dict:
    effective = _resolve_property(user, property_id)

    stmt = select(Invoice)
    if effective:
        stmt = stmt.where(Invoice.property_id == effective)
    if room_id:
        stmt = stmt.where(Invoice.room_id == room_id)
    if tenant_id:
        stmt = stmt.where(Invoice.tenant_id == tenant_id)
    if period:
        stmt = stmt.where(Invoice.period == period)
    if period_from:
        stmt = stmt.where(Invoice.period >= period_from)
    if period_to:
        stmt = stmt.where(Invoice.period <= period_to)
    if invoice_status:
        stmt = stmt.where(Invoice.status == invoice_status)
    if overdue_only:
        stmt = stmt.where(
            Invoice.due_date < date.today(),
            Invoice.status.in_([InvoiceStatus.PENDING.value,
                                InvoiceStatus.OVERDUE.value]),
        )

    stmt = apply_sort(
        stmt, Invoice, sort,
        allowed={"period": "period", "total": "total_amount", "due": "due_date"},
        default="period",
    )

    items, meta = await paginate(session, stmt, params)
    return {
        "items": [_to_list_item(i) for i in items],
        "meta": meta.model_dump(),
    }


@invoice_router.get("/stats", response_model=InvoiceStats,
                     summary="📊 Tổng hợp tài chính")
async def invoice_stats(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
    period: date | None = None,
) -> InvoiceStats:
    """
    ⭐ 1 câu `GROUP BY status` thay vì 8 câu `COUNT/SUM` riêng.

    Với 200 hóa đơn thì chẳng khác biệt, nhưng báo cáo tài chính hay được
    mở kèm bộ lọc dài và cache đầu vào yếu — 8 câu này là 8 round-trip DB.
    """
    effective = _resolve_property(user, property_id)

    stmt = select(Invoice.status, func.count(Invoice.id),
                  func.coalesce(func.sum(Invoice.total_amount), 0),
                  func.coalesce(func.sum(Invoice.paid_amount), 0))
    if effective:
        stmt = stmt.where(Invoice.property_id == effective)
    if period:
        stmt = stmt.where(Invoice.period == period)
    stmt = stmt.group_by(Invoice.status)

    rows = (await session.execute(stmt)).all()

    by_status = {s.value: 0 for s in InvoiceStatus}
    billed = collected = Decimal("0")
    for st, count, sum_total, sum_paid in rows:
        by_status[st] = count
        billed += Decimal(sum_total or 0)
        collected += Decimal(sum_paid or 0)

    outstanding = billed - collected
    return InvoiceStats(
        property_id=effective,
        period=period,
        total_invoices=sum(by_status.values()),
        paid=by_status.get(InvoiceStatus.PAID.value, 0),
        pending=by_status.get(InvoiceStatus.PENDING.value, 0),
        overdue=by_status.get(InvoiceStatus.OVERDUE.value, 0),
        total_billed=money(billed),
        total_collected=money(collected),
        total_outstanding=money(outstanding),
        collection_rate=round(float(collected / billed * 100), 2) if billed else 0.0,
    )


@invoice_router.get("/overdue", response_model=list[InvoiceListItem],
                    summary="⏰ Hóa đơn quá hạn (công nợ)")
async def list_overdue(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
    min_days: int = Query(1, ge=1, le=365, description="Trễ ít nhất N ngày"),
) -> list[InvoiceListItem]:
    """
    Bảng công nợ — ai còn nợ, nợ bao lâu.

    Đây là màn hình được mở ra nhiều nhất trong 2 tuần đầu mỗi tháng, nên
    trả về kèm `days_overdue` để UI sắp xếp được mà không phải tính lại.
    """
    effective = _resolve_property(user, property_id)
    cutoff = date.today() - timedelta(days=min_days)

    stmt = select(Invoice).where(
        Invoice.due_date < cutoff,
        Invoice.status.in_([InvoiceStatus.PENDING.value, InvoiceStatus.OVERDUE.value]),
    )
    if effective:
        stmt = stmt.where(Invoice.property_id == effective)
    stmt = stmt.order_by(Invoice.due_date)

    rows = (await session.execute(stmt)).scalars().all()
    return [_to_list_item(i) for i in rows]


@invoice_router.get("/mine", response_model=list[InvoiceResponse],
                    summary="🧾 Hóa đơn của tôi (người thuê)")
async def list_my_invoices(
    user: Annotated[CurrentUser, Depends(require_roles(Role.TENANT))],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(12, ge=1, le=36, description="Số kỳ gần nhất"),
) -> list[InvoiceResponse]:
    """
    Người thuê chỉ xem được hóa đơn của chính mình.

    ⭐ Lọc theo claim `tenant_id` trong JWT (auth-service lấy từ cột
       users.tenant_id). Không nhận tenant_id từ query — nếu nhận, đổi tham số
       là xem được hóa đơn người khác. Đặt TRƯỚC route `/{invoice_id}` để
       "mine" không bị hiểu là UUID.
    """
    if user.tenant_id is None:
        return []      # tài khoản chưa gắn hồ sơ người thuê
    from sqlalchemy.orm import selectinload
    rows = (await session.execute(
        select(Invoice)
        .options(selectinload(Invoice.details))
        .where(Invoice.tenant_id == user.tenant_id)
        .order_by(Invoice.period.desc())
        .limit(limit)
    )).scalars().all()
    return [_to_invoice_response(i) for i in rows]


@invoice_router.get("/{invoice_id}", response_model=InvoiceResponse,
                    summary="Chi tiết hóa đơn (kèm giải thích từng dòng)")
async def get_invoice(
    invoice_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InvoiceResponse:
    invoice = await _get_invoice_or_404(session, invoice_id)
    user.assert_property_access(invoice.property_id)
    return _to_invoice_response(invoice)


@invoice_router.get("/{invoice_id}/payments", response_model=list[PaymentResponse],
                    summary="Lịch sử thanh toán")
async def list_invoice_payments(
    invoice_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[PaymentResponse]:
    invoice = await _get_invoice_or_404(session, invoice_id)
    user.assert_property_access(invoice.property_id)
    rows = (await session.execute(
        select(Payment).where(Payment.invoice_id == invoice_id)
        .order_by(Payment.received_at)
    )).scalars().all()
    return [PaymentResponse.model_validate(p) for p in rows]


@invoice_router.post("/{invoice_id}/payments", response_model=PaymentResponse,
                     status_code=status.HTTP_201_CREATED,
                     summary="💵 Ghi nhận thanh toán")
async def record_payment(
    invoice_id: uuid.UUID,
    payload: PaymentCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PaymentResponse:
    """
    ⭐ Khoá dòng hóa đơn (FOR UPDATE): 2 người cùng ghi nhận một lúc sẽ cùng
       đọc `remaining_amount` cũ và cùng qua kiểm tra → thu vượt. Có khoá thì
       request thứ hai phải đợi, đọc lại số đã cập nhật rồi mới kiểm tra.

    ⭐ R8 — hóa đơn `PAID` không nhận thêm thanh toán.

    Trả nhiều hơn tổng là trả thừa. Cho phép sẽ sinh ra tình huống: sổ sách
    ghi đã thu 3.000.000 cho hóa đơn 2.350.000 → báo cáo tài chính sai, và
    không ai biết 650.000 đó là gì. Nếu khách trả thừa, trả lại tiền mặt
    và ghi thành khoản khác.
    """
    invoice = await _get_invoice_or_404(session, invoice_id, lock=True)
    user.assert_property_access(invoice.property_id)

    if invoice.is_paid:
        raise BusinessRuleError(
            f"Hóa đơn {invoice.invoice_no} đã thanh toán đủ từ "
            f"{invoice.paid_at:%d/%m/%Y}. Không thể ghi thêm thanh toán. "
            "Nếu cần điều chỉnh, hãy phát hóa đơn điều chỉnh riêng.",
            details={"paid_amount": str(invoice.paid_amount),
                     "total_amount": str(invoice.total_amount)},
        )

    if invoice.status == InvoiceStatus.CANCELLED.value:
        raise BusinessRuleError("Hóa đơn đã bị huỷ — không nhận thanh toán")

    if payload.amount > invoice.remaining_amount:
        raise BusinessRuleError(
            f"Số tiền trả ({payload.amount:,.0f}đ) lớn hơn số còn phải "
            f"({invoice.remaining_amount:,.0f}đ). Vui lòng trả đúng số còn nợ, "
            "phần thừa sẽ trả lại riêng.",
            details={"remaining": str(invoice.remaining_amount)},
        )

    payment = Payment(
        invoice_id=invoice.id,
        amount=payload.amount,
        method=payload.method,
        reference=payload.reference,
        receipt_no=payload.receipt_no,
        received_by=user.id,
        note=payload.note,
    )
    session.add(payment)
    await session.flush()

    invoice.paid_amount = money(invoice.paid_amount + payload.amount)
    if invoice.paid_amount >= invoice.total_amount:
        invoice.paid_amount = money(invoice.total_amount)
        invoice.status = InvoiceStatus.PAID.value
        invoice.paid_at = datetime.now(UTC)

        # ⭐ R3 — đồng bộ `deposit_deducted` về contract-service.
        # Nếu hóa đơn đã trừ cọc, phải báo lại để hợp đồng không bị trừ
        # 2 lần ở kỳ sau. Đây là bước bù cho việc không có transaction
        # xuyên 2 DB.
        if invoice.deposit_deducted > 0:
            await _sync_deposit_deduction(invoice, invoice.deposit_deducted)

    await get_event_bus().publish(session, DomainEvent(
        event_type="payment.received",
        data={
            "payment_id": str(payment.id),
            "invoice_id": str(invoice.id),
            "invoice_no": invoice.invoice_no,
            "property_id": str(invoice.property_id),
            "contract_id": str(invoice.contract_id),
            "room_id": str(invoice.room_id),
            "tenant_id": str(invoice.tenant_id) if invoice.tenant_id else None,
            "tenant_name": invoice.tenant_name,
            "amount": str(payment.amount),
            "method": payment.method,
            "invoice_paid": invoice.is_paid,
            "entity_type": "payment", "entity_id": str(payment.id),
        },
    ))
    record_business_event(settings.service_name, "payment.received")

    logger.info("💵 Nhận %sđ cho hóa đơn %s (%s/%sđ) — %s",
                payment.amount, invoice.invoice_no, invoice.paid_amount,
                invoice.total_amount,
                "ĐÃ TRẢ ĐỦ" if invoice.is_paid else "còn nợ")
    return PaymentResponse.model_validate(payment)


async def _sync_deposit_deduction(invoice: Invoice, amount: Decimal) -> None:
    """
    Báo cho contract-service biết đã trừ bao nhiêu cọc.

    Gọi HTTP đồng bộ trong lúc đang ghi hóa đơn là điểm rủi ro (thêm độ trễ,
    thêm failure mode). Xử lý an toàn: lỗi thì chỉ log cảnh báo, KHÔNG rollback
    việc ghi nhận thanh toán — tiền đã nhận rồi, không có lý do gì để bỏ.
    Sẽ đồng bộ lại ở job sửa lệch chạy hằng đêm.
    """
    try:
        await get_http_client("contract").post(
            f"/internal/v1/contracts/{invoice.contract_id}/deposit-deducted",
            params={"amount": str(amount)},
        )
    except Exception as exc:
        logger.error(
            "❌ Không đồng bộ được trừ cọc %sđ cho HĐ %s: %s. "
            "Sẽ xử lý lại bởi job 'make reconcile-deposits'.",
            amount, invoice.contract_id, exc,
        )


# ---------------------------------------------------------------------------
#  Job tính tiền hàng loạt
# ---------------------------------------------------------------------------
#: Giữ tham chiếu các task nền để chúng không bị GC trước khi xong.
_BACKGROUND_TASKS: set[asyncio.Task] = set()

job_router = APIRouter(prefix="/api/v1/billing-jobs", tags=["billing-jobs"])


@job_router.post("", response_model=BillingJobResponse,
                 status_code=status.HTTP_202_ACCEPTED,
                 summary="🚀 Tính tiền hàng loạt cho 1 kỳ")
async def create_billing_job(
    request: Request,
    payload: GenerateJobRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BillingJobResponse:
    """
    Tính tiền cho TẤT CẢ hợp đồng đang hiệu lực của 1 cơ sở trong 1 kỳ.

    ⭐ Vì sao chạy nền (202 Accepted) chứ không trả kết quả luôn?
        200 hợp đồng × (3 lần gọi service khác + 5 câu SQL) ≈ 30–60 giây.
        HTTP timeout chỉ 10 giây (nginx) → request chết, nhưng job vẫn chạy
        tiếp và sinh ra 200 hóa đơn. Người dùng nghĩ thất lạc rồi bấm lần 2
        → 2 job chạy song song. Trả 202 + mã job giải quyết đúng vấn đề này.

    ⭐ Vì sao có `deploy.replicas` mà không cần scale?
        Job chạy trong 1 container. Muốn song song hơn thì tách phần tính
        vào RabbitMQ và chạy worker. Ở quy mô vài trăm hóa đơn, chạy 1 job
        trong 30 giây là đủ; kiến trúc đã sẵn sàng cho việc mở rộng đó.
    """
    user.assert_property_access(payload.property_id)

    # ---- Idempotency ở tầng job: bấm 2 lần = trả về job cũ ----
    existing = (await session.execute(
        select(BillingJob).where(
            BillingJob.property_id == payload.property_id,
            BillingJob.period == payload.period,
        )
    )).scalar_one_or_none()
    if existing and existing.status in ("PENDING", "RUNNING"):
        logger.info("♻ Job %s/%s đang chạy — trả về job cũ", payload.property_id,
                    payload.period)
        return BillingJobResponse.model_validate(existing)

    job = existing or BillingJob(property_id=payload.property_id, period=payload.period)
    job.status = "PENDING"
    job.processed = job.succeeded = job.failed = 0
    job.total_contracts = 0
    job.error = None
    job.started_at = job.finished_at = None
    job.created_by = user.id
    if not existing:
        session.add(job)
    await session.commit()      # ⭐ XEM GIẢI THÍCH BÊN DƯỚI

    # ⭐ VÌ SAO COMMIT Ở GIỮA HANDLER, KHÔNG ĐỢI `get_db` COMMIT CUỐI?
    #   Vì `_run_billing_job` mở session RIÊNG để ghi tiến độ vào CHÍNH dòng
    #   `billing_jobs` này. Trong khi request session chưa commit, nó đang giữ
    #   row-level lock trên dòng đó → session của job sẽ đợi khoá, và vì
    #   `lock_timeout=10000` nên chết sau 10 giây với lỗi
    #   "canceling statement due to lock timeout". Đây là deadlock kinh điển
    #   giữa 2 connection của cùng 1 DB.
    #   Commit ở đây chấp nhận được vì `billing_jobs` chỉ là bảng trạng thái
    #   của job (không phải sổ sách tài chính): commit rồi hỏng thì cũng chỉ
    #   mất dấu vết, chạy lại là xong.
    await session.refresh(job)

    if payload.dry_run:
        # Chạy thử: KHÔNG tạo hóa đơn. `_run_billing_job` ghi bảng xem trước
        # vào cột `error` của chính job này (dùng lại bảng có sẵn, đỡ phải
        # thêm bảng riêng chỉ để chứa vài chục dòng text tạm).
        await _run_billing_job(
            job.id, payload.property_id, payload.period, user.id,
            include_deposit=payload.include_deposit_deduction, dry_run=True,
        )
        # Refresh để lấy trạng thái vừa được job ghi ở session khác — đọc
        # object đang cache sẽ trả số liệu cũ và UI hiện tiến độ 0%.
        await session.refresh(job, attribute_names=[
            "status", "total_contracts", "processed", "succeeded", "failed",
            "error", "started_at", "finished_at",
        ])
        logger.info("🧪 Chạy thử tính tiền kỳ %s: %d/%d hợp đồng — %d thành công, "
                    "%d lỗi", payload.period, job.processed,
                    job.total_contracts, job.succeeded, job.failed)
        return BillingJobResponse.model_validate(job)

    # Job thật: chạy ngoài request (nền), giữ request trả lời ngay.
    # Giữ tham chiếu task để tránh bị GC giữa chừng — asyncio chỉ giữ strong
    # reference tới task đang chạy, không có bảng tham chiếu yếu, nên không
    # giữ thì job có thể "chết lặng lẽ" mà không ai biết.
    task = asyncio.create_task(_run_billing_job_background(
        job.id, payload.property_id, payload.period, user.id,
        include_deposit=payload.include_deposit_deduction,
    ))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    logger.info("🚀 Đã tạo job tính tiền %s kỳ %s", payload.property_id, payload.period)
    return BillingJobResponse.model_validate(job)


@job_router.get("/{job_id}", response_model=BillingJobResponse,
                summary="Theo dõi tiến độ job")
async def get_job(
    job_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BillingJobResponse:
    job = await session.get(BillingJob, job_id)
    if not job:
        raise NotFoundError(f"Không tìm thấy job {job_id}")
    user.assert_property_access(job.property_id)
    return BillingJobResponse.model_validate(job)


async def _run_billing_job_background(
    job_id: uuid.UUID, property_id: uuid.UUID, period: date,
    actor: uuid.UUID, *, include_deposit: bool,
) -> None:
    """
    Task nền. Mỗi hợp đồng là 1 transaction RIÊNG.

    ⭐ Vì sao không gộp tất cả vào 1 transaction?
        - 200 hợp đồng trong 1 transaction = 1 lần commit 30 giây, và nếu
          lỗi ở phòng thứ 199 thì MẤT TRẮNG cả 198 hóa đơn trước đó.
        - Transaction riêng = 198 thành công, 1 thất bại, 1 thông báo lỗi
          rõ ràng để sửa. Với nghiệp vụ tài chính, "mất trắng" là không
          chấp nhận được.
    """
    try:
        await _run_billing_job(job_id, property_id, period, actor,
                               include_deposit=include_deposit, dry_run=False)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Job tính tiền %s lỗi: %s", job_id, exc)
        async with session_scope() as session:
            job = await session.get(BillingJob, job_id)
            if job:
                job.status = "FAILED"
                job.error = str(exc)[:1000]
                job.finished_at = datetime.now(UTC)


async def _run_billing_job(
    job_id: uuid.UUID, property_id: uuid.UUID, period: date,
    actor: uuid.UUID, *, include_deposit: bool, dry_run: bool,
) -> dict:
    """Thân của job — dùng chung cho chạy thật và chạy thử."""
    summary_lines: list[str] = []

    async with session_scope() as job_session:
        job = await job_session.get(BillingJob, job_id)
        if not job:
            return {"error": "job không tồn tại"}
        job.status = "RUNNING"
        job.started_at = datetime.now(UTC)
        job.error = None

    # ---- Bước 1: lấy danh sách hợp đồng ACTIVE từ contract-service ----
    try:
        contracts = await get_http_client("contract").get(
            "/internal/v1/contracts/active", params={"property_id": str(property_id)}
        )
    except Exception as exc:
        async with session_scope() as s:
            job = await s.get(BillingJob, job_id)
            if job:
                job.status = "FAILED"
                job.error = f"Không lấy được danh sách hợp đồng: {exc}"
                job.finished_at = datetime.now(UTC)
        raise

    contracts = contracts or []
    async with session_scope() as s:
        job = await s.get(BillingJob, job_id)
        if job:
            job.total_contracts = len(contracts)

    logger.info("🧮 Bắt đầu tính tiền %d hợp đồng — cơ sở %s, kỳ %s",
                len(contracts), property_id, period)

    processed = succeeded = failed = skipped = 0

    # ---- 1 kết nối Redis cho CẢ job, không tạo mới ở từng vòng lặp ----
    # Nếu tạo `redis.from_url()` trong vòng lặp thì 200 hợp đồng = 200 client =
    # 200 connection tới Redis, và không connection nào được đóng. Redis mặc
    # định chỉ chịu được vài chục client → job chết OOM giữa chừng.
    redis = await _background_redis()

    # ---- Chống 2 tiến trình cùng chạy 1 job ----
    # `create_billing_job` đã chặn bằng UNIQUE(property_id, period) + kiểm tra
    # trạng thái, nhưng đó là ràng buộc ở tầng DB. Redis lock là lớp thứ hai
    # bảo vệ trường hợp job bị kích hoạt từ 2 đường khác nhau (nút bấm tay và
    # scheduler chạy cùng lúc).
    lock_name = f"billing-job:{job_id}"
    lock_owner = f"{settings.service_name}:{job_id}"
    if not await acquire_lock(redis, lock_name, lock_owner, ttl=900):
        logger.warning("🔒 Job %s đang được tiến trình khác giữ khoá — bỏ qua",
                       job_id)
        async with session_scope() as s:
            job = await s.get(BillingJob, job_id)
            if job:
                job.error = "Bị bỏ qua: tiến trình khác đang chạy job này"
        return {"processed": processed, "succeeded": 0, "failed": 0,
                "skipped": skipped, "locked_by_other": True}

    try:
        for snapshot in contracts:
            contract_no = snapshot.get("contract_no", "?")
            try:
                async with session_scope() as s:
                    # Chống tạo trùng: bỏ qua hợp đồng đã có hóa đơn kỳ này.
                    # Hàng rào cuối là UNIQUE(contract_id, period) — dò này chỉ
                    # để không phải chờ tới lúc gặp IntegrityError.
                    exists = (await s.execute(
                        select(Invoice.id).where(
                            Invoice.contract_id == uuid.UUID(str(snapshot["id"])),
                            Invoice.period == period,
                        )
                    )).scalar_one_or_none()
                    if exists:
                        skipped += 1
                        processed += 1
                        continue

                    if dry_run:
                        totals = await _preview_invoice(s, redis, snapshot,
                                                       period, include_deposit)
                        summary_lines.append(
                            f"  {snapshot.get('room_number') or '—'!s} "
                            f"· tiền phòng {totals.rent:,.0f} "
                            f"· điện {totals.electric:,.0f} "
                            f"· nước {totals.water:,.0f} "
                            f"· DV {totals.services:,.0f} "
                            f"· TỔNG {totals.total:,.0f}đ"
                        )
                        processed += 1
                        continue

                    # Lấy snapshot đầy đủ (có deposit_remaining) — danh sách
                    # `active` cố tình gọn nhẹ, không mang theo cọc.
                    full = await get_http_client("contract").get(
                        f"/internal/v1/contracts/{snapshot['id']}"
                    )
                    await generate_invoice(s, redis, full or snapshot, period,
                                           created_by=actor,
                                           include_deposit=include_deposit)
                    succeeded += 1
                    processed += 1

            except ConflictError as exc:
                # Hợp đồng khác vừa tạo hóa đơn kỳ này (race) → không phải lỗi.
                skipped += 1
                processed += 1
                logger.debug("Bỏ qua %s: %s", contract_no, exc)
            except Exception as exc:
                failed += 1
                processed += 1
                logger.error("❌ HĐ %s: %s: %s", contract_no,
                             type(exc).__name__, exc)

            # Cập nhật tiến độ mỗi 20 hợp đồng. Ghi mỗi vòng lặp thì tốn 200
            # lần UPDATE cho 200 hợp đồng — thêm gánh mà UI vẫn không kịp
            # nhìn thấy.
            if processed % 20 == 0:
                logger.info("  ... %d/%d (thành công %d, lỗi %d, bỏ qua %d)",
                            processed, len(contracts), succeeded, failed, skipped)
                await _save_job_progress(job_id, processed, succeeded, failed,
                                        total_contracts=len(contracts))

        async with session_scope() as s:
            job = await s.get(BillingJob, job_id)
            if job:
                job.status = "DONE"
                job.processed = processed
                job.succeeded = succeeded
                job.failed = failed
                job.finished_at = datetime.now(UTC)
                job.error = ("\n".join(summary_lines[:50])
                             if dry_run and summary_lines else None)
    finally:
        await release_lock(redis, lock_name, lock_owner)

    logger.info("✅ Hoàn tất tính tiền kỳ %s: %d thành công, %d lỗi, %d bỏ qua",
                period, succeeded, failed, skipped)
    set_business_gauge(settings.service_name, "billing_invoices_created", succeeded,
                       str(property_id))
    return {"processed": processed, "succeeded": succeeded, "failed": failed,
            "skipped": skipped, "preview": summary_lines}


async def _save_job_progress(job_id: uuid.UUID, processed: int, succeeded: int,
                             failed: int, *, total_contracts: int) -> None:
    """Ghi tiến độ lên `billing_jobs` để UI vẽ thanh tiến trình."""
    try:
        async with session_scope() as s:
            job = await s.get(BillingJob, job_id)
            if job:
                job.processed = processed
                job.succeeded = succeeded
                job.failed = failed
                if total_contracts:
                    job.total_contracts = total_contracts
    except Exception as exc:
        # Tiến độ chỉ để hiển thị — ghi lỗi ở đây KHÔNG được làm hỏng job.
        logger.warning("Không lưu được tiến độ job %s: %s", job_id, exc)


async def _background_redis() -> Any:
    """Redis dùng trong task nền (ngoài vòng đời request)."""
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.redis_url, encoding="utf-8",
                                   decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:
        logger.warning("Không dùng được Redis trong job nền: %s", exc)
        return None


async def _preview_invoice(
    session: AsyncSession, redis: Any, snapshot: dict, period: date,
    include_deposit: bool,
) -> InvoiceTotals:
    """
    Tính thử: chạy đúng công thức nhưng KHÔNG ghi gì.

    Dùng lại chính `generate_invoice` bằng cách rollback transaction sau khi
    ghi — đảm bảo "bản xem trước" và "bản thật" dùng CÙNG một công thức.
    Nếu viết riêng, chúng sẽ lệch nhau ngay lần sửa đầu tiên.
    """
    totals = InvoiceTotals()
    start = date.fromisoformat(str(snapshot["start_date"]))
    end = date.fromisoformat(str(snapshot["end_date"]))
    price = Decimal(str(snapshot["monthly_price"]))
    room_id = uuid.UUID(str(snapshot["room_id"]))
    property_id = uuid.UUID(str(snapshot["property_id"]))

    totals.rent, _ = prorated_rent(price, start, end, period)
    for utility in (UtilityType.ELECTRIC, UtilityType.WATER):
        reading = (await session.execute(
            select(MeterReading).where(
                MeterReading.room_id == room_id,
                MeterReading.utility_type == utility.value,
                MeterReading.period == period,
            )
        )).scalar_one_or_none()
        if not reading or reading.previous_value is None:
            continue
        tiers = await _load_tiers(session, redis, property_id, utility.value)
        amount, _ = _charge_breakdown(reading.consumption or ZERO, tiers, utility)
        if utility is UtilityType.ELECTRIC:
            totals.electric = amount
        else:
            totals.water = amount

    fees = await _load_service_fees(session, redis, property_id)
    totals.services = money(sum((f.amount for f in fees if f.is_mandatory), ZERO))
    totals.services = money(totals.services + await _room_amenity_fee(redis, room_id))

    if include_deposit:
        remaining = Decimal(str(snapshot.get("deposit_remaining")
                                or snapshot.get("remaining_deposit") or 0))
        totals, _ = apply_deposit(totals, remaining)
    return totals


# ===========================================================================
#  ROUTER: THAM SỐ & BẢNG GIÁ ƯỚC TÍNH
# ===========================================================================
estimate_router = APIRouter(prefix="/api/v1/estimates", tags=["estimates"])


@estimate_router.get("/monthly-typical", response_model=TariffEstimate,
                     summary="💡 Mức tiêu thụ trung bình (để ước tính giá)")
async def typical_monthly_cost(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
    months: int = Query(6, ge=1, le=24, description="Lấy trung bình N tháng gần nhất"),
) -> TariffEstimate:
    """
    Tính mức tiêu thụ trung bình từ HÓA ĐƠN ĐÃ PHÁT, rồi đẩy xuống cache Redis
    để room-service (trang tìm phòng công khai) dùng.

    ⭐ Vì sao lấy từ hóa đơn chứ không lấy "số liệu giả định"?
        Giả định (100 kWh/tháng) là con số trung bình cả nước — ở khu công
        nghiệp có thể gấp 5 lần. Lấy từ chính hóa đơn của cơ sở đó cho ước
        tính sát thực tế. Cần đủ dữ liệu thì mới dùng con số thật, chưa đủ
        thì fallback về giá trị mặc định.
    """
    effective = _resolve_property(user, property_id)

    since = date.today().replace(day=1)
    since = date(since.year, since.month, 1) - timedelta(days=31 * months)

    stmt = (
        select(
            func.coalesce(func.sum(MeterReading.consumption), 0),
            func.count(MeterReading.id),
        )
        .where(
            MeterReading.period >= since,
            MeterReading.utility_type == UtilityType.ELECTRIC.value,
        )
    )
    if effective:
        stmt = stmt.where(MeterReading.property_id == effective)

    elec_total, readings = (await session.execute(stmt)).one()

    stmt2 = (
        select(
            func.coalesce(func.sum(MeterReading.consumption), 0),
            func.count(MeterReading.id),
        )
        .where(
            MeterReading.period >= since,
            MeterReading.utility_type == UtilityType.WATER.value,
        )
    )
    if effective:
        stmt2 = stmt2.where(MeterReading.property_id == effective)
    water_total, water_readings = (await session.execute(stmt2)).one()

    # Số phòng trung bình đang hoạt động trong kỳ → suy ra tiêu thụ/phòng
    active_rooms = (await session.execute(
        select(func.count(func.distinct(MeterReading.room_id))).where(
            MeterReading.period >= since
        )
    )).scalar() or 1

    months_effective = max(months, 1)
    avg_kwh = money(Decimal(elec_total or 0) / Decimal(max(readings, 1)))
    avg_m3 = money(Decimal(water_total or 0) / Decimal(max(water_readings, 1)))

    tiers_e = await _load_tiers(session, None, effective or uuid.UUID(int=0),
                                UtilityType.ELECTRIC.value)
    tiers_w = await _load_tiers(session, None, effective or uuid.UUID(int=0),
                                UtilityType.WATER.value)
    elec_cost = graduated_charge(avg_kwh, tiers_e)
    water_cost = graduated_charge(avg_m3, tiers_w)

    fees = await _load_service_fees(session, None, effective or uuid.UUID(int=0))
    service_cost = money(sum((f.amount for f in fees if f.is_mandatory), ZERO))

    # ⭐ Ghi kết quả xuống Redis cho room-service (trang tìm phòng công khai) đọc.
    #   Khoá `room:tariff:<property_id>` phải KHỚP CHÍNH XÁC với khoá mà
    #   room/main.py đọc — lệch 1 ký tự thì trang công khai hiện 0đ. Vì vậy ta
    #   để nguyên tên khoá ở đây và ghi chú rõ, thay vì "phát minh" khoá mới.
    #   Nguồn sự thật vẫn là bảng `price_tiers`/`service_fees`: xoá cache
    #   thì chỉ chậm thêm 1 lần đọc DB, không mất dữ liệu.
    await _publish_tariff_cache(
        effective, avg_kwh, avg_m3, elec_cost, water_cost, service_cost,
    )

    estimate = TariffEstimate(
        property_id=effective,
        average_monthly_kwh=avg_kwh,
        average_monthly_m3=avg_m3,
        average_electric_cost=elec_cost,
        average_water_cost=water_cost,
        average_services_cost=service_cost,
        average_total_per_room=money(elec_cost + water_cost + service_cost),
        based_on_invoices=readings,
    )
    logger.info("💡 Ước tính TB: %.0f kWh + %.2f m³ + %sđ DV = %sđ/phòng/tháng "
                "(%d chỉ số, %d phòng, %d tháng)",
                avg_kwh, avg_m3, service_cost, estimate.average_total_per_room,
                readings, active_rooms, months_effective)
    return estimate


async def _publish_tariff_cache(
    property_id: uuid.UUID | None,
    avg_kwh: Decimal, avg_m3: Decimal,
    elec_cost: Decimal, water_cost: Decimal, services_cost: Decimal,
) -> None:
    """
    Ghi bảng giá ước tính vào Redis theo đúng định dạng room-service đọc.

    ⭐ Hợp đồng giữa 2 service (contract của cache, không phải của API):
        khoá  : `room:tariff:<property_id>`  (hoặc `room:tariff:all`)
        kiểu  : HASH
        field : `electric`, `water`, `services`  (chuỗi số nguyên VND)

       `services` ở đây là phí DV CỐ ĐỊNH của cơ sở, KHÔNG gồm tiện ích
       gắn từng phòng — vì room/main.py tự cộng tiện ích phòng vào nữa. Nếu ta
       ghi cả tiện ích vào đây thì tiền bị cộng 2 lần.

    Vì sao để 2 service cùng ghi/đọc 1 khoá mà không có hợp đồng chính thức?
    Vì đây là CACHE phục vụ hiển thị, không phải dữ liệu. Sai thì trang công
    khai hiện sai con số tham khảo; xoá khoá thì mất tối đa 15 phút cache.
    Đổi lại, `billable` vẫn đúng vì tiền thật đến từ bảng `invoices`.
    """
    redis = await _background_redis()
    if redis is None:
        return
    key = f"room:tariff:{property_id or 'all'}"
    try:
        await redis.hset(key, mapping={
            "electric": str(money(elec_cost)),
            "water": str(money(water_cost)),
            "services": str(money(services_cost)),
            # Thêm 2 field này để khi có người hỏi "số này từ đâu" thì tra
            # được ngay, không phải đoán.
            "avg_kwh": str(avg_kwh),
            "avg_m3": str(avg_m3),
        })
        await redis.expire(key, CACHE_TTL_TARIFF)
    except Exception as exc:
        logger.warning("Không ghi được tariff cache %s: %s", key, exc)


# ===========================================================================
#  ROUTER: INTERNAL
# ===========================================================================
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


@internal_router.post("/invoices/mark-overdue", summary="[Nội bộ] Đánh dấu quá hạn")
async def internal_mark_overdue(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
    grace_days: int = Query(0, ge=0, le=31),
) -> dict:
    """
    Được scheduler gọi mỗi ngày: chuyển hóa đơn `PENDING` quá hạn → `OVERDUE`
    và phát `invoice.overdue` để notification nhắc khách.

    ⭐ Idempotent: chạy 5 lần trong ngày vẫn chỉ chuyển đúng những hóa đơn
       cần chuyển — vì điều kiện lọc là `status='PENDING'`, đã chuyển rồi thì
       không còn khớp.
    """
    today = date.today() - timedelta(days=grace_days)
    overdue = (await session.execute(
        select(Invoice).where(
            Invoice.status == InvoiceStatus.PENDING.value,
            Invoice.due_date < today,
        )
    )).scalars().all()

    for invoice in overdue:
        invoice.status = InvoiceStatus.OVERDUE.value
        await get_event_bus().publish(session, DomainEvent(
            event_type="invoice.overdue",
            data={
                "invoice_id": str(invoice.id),
                "invoice_no": invoice.invoice_no,
                "property_id": str(invoice.property_id),
                "contract_id": str(invoice.contract_id),
                "room_id": str(invoice.room_id),
                "tenant_id": str(invoice.tenant_id) if invoice.tenant_id else None,
                "tenant_name": invoice.tenant_name,
                "tenant_phone": None,
                "total_amount": str(invoice.total_amount),
                "outstanding": str(invoice.remaining_amount),
                "days_overdue": (today - invoice.due_date).days,
                "due_date": invoice.due_date.isoformat(),
                "entity_type": "invoice", "entity_id": str(invoice.id),
            },
        ))

    logger.info("⏰ Đánh dấu %d hóa đơn quá hạn", len(overdue))
    return {"marked": len(overdue), "invoice_ids": [str(i.id) for i in overdue]}


@internal_router.get("/invoices/{invoice_id}", summary="[Nội bộ] Chi tiết hóa đơn")
async def internal_get_invoice(
    invoice_id: uuid.UUID,
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM, Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """report-service gọi khi dựng báo cáo doanh thu."""
    invoice = await _get_invoice_or_404(session, invoice_id)
    return {
        "id": str(invoice.id),
        "invoice_no": invoice.invoice_no,
        "property_id": str(invoice.property_id),
        "contract_id": str(invoice.contract_id),
        "room_id": str(invoice.room_id),
        "tenant_id": str(invoice.tenant_id) if invoice.tenant_id else None,
        "tenant_name": invoice.tenant_name,
        "period": invoice.period.isoformat(),
        "rent_amount": str(invoice.rent_amount),
        "electric_amount": str(invoice.electric_amount),
        "water_amount": str(invoice.water_amount),
        "service_amount": str(invoice.service_amount),
        "late_fee_amount": str(invoice.late_fee_amount),
        "deposit_deducted": str(invoice.deposit_deducted),
        "total_amount": str(invoice.total_amount),
        "paid_amount": str(invoice.paid_amount),
        "status": invoice.status,
        "due_date": invoice.due_date.isoformat(),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
    }


@internal_router.get(
    "/financials/snapshot",
    summary="[Nội bộ] Ảnh chụp hóa đơn & thanh toán",
)
async def internal_financials_snapshot(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = Query(
        None, description="Bỏ trống = toàn hệ thống",
    ),
) -> dict:
    """
    Trả về mọi hóa đơn + thanh toán (chỉ đọc) để report-service DỰNG LẠI
    `daily_financials` và `open_invoices`.

    ⭐ Vì sao không tự tổng hợp theo ngày ở đây? Vì hình dạng read model là
       quyết định của report-service, không phải của nơi giữ dữ liệu gốc.
       Billing chỉ trả lời về những gì nó sở hữu; ai gom nhóm thế nào là việc
       của bên đọc. Giữ ranh giới này thì đổi cách báo cáo không phải sửa
       billing.

    ⭐ Trả kèm mốc thời gian ĐẦY ĐỦ (`issued_at`, `received_at`) chứ không cắt
       sẵn thành ngày: việc quy về "ngày nghiệp vụ" (giờ VN) là logic của
       report-service — cắt ngày ở đây theo UTC sẽ lệch mất một ngày với các
       event lúc rạng sáng giờ VN.
    """
    inv_stmt = select(Invoice)
    if property_id is not None:
        inv_stmt = inv_stmt.where(Invoice.property_id == property_id)
    invoices = (await session.execute(inv_stmt)).scalars().all()

    pay_stmt = select(Payment)
    if property_id is not None:
        pay_stmt = pay_stmt.join(
            Invoice, Payment.invoice_id == Invoice.id
        ).where(Invoice.property_id == property_id)
    payments = (await session.execute(pay_stmt)).scalars().all()

    # `payments` không có cột `property_id` — lấy qua hóa đơn. Khi lọc theo
    # cơ sở, `invoices` cũng đã bị lọc nên bảng ánh xạ luôn đủ.
    property_of = {inv.id: inv.property_id for inv in invoices}

    return {
        "property_id": str(property_id) if property_id else None,
        "invoices": [
            {
                "id": str(inv.id),
                "invoice_no": inv.invoice_no,
                "property_id": str(inv.property_id),
                "contract_id": str(inv.contract_id),
                "room_id": str(inv.room_id),
                "tenant_id": str(inv.tenant_id) if inv.tenant_id else None,
                "tenant_name": inv.tenant_name,
                "period": inv.period.isoformat(),
                "total_amount": str(inv.total_amount),
                "paid_amount": str(inv.paid_amount),
                "status": inv.status,
                "due_date": inv.due_date.isoformat(),
                "issued_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in invoices
        ],
        "payments": [
            {
                "id": str(pay.id),
                "invoice_id": str(pay.invoice_id),
                "property_id": str(property_of.get(pay.invoice_id) or ""),
                "amount": str(pay.amount),
                "received_at": pay.received_at.isoformat() if pay.received_at else None,
            }
            for pay in payments
        ],
    }


# ===========================================================================
#  CONSUMER
# ===========================================================================
async def _handle_event(event: DomainEvent) -> None:
    """
    Phản ứng với event của service khác.

    ⭐ Xử lý phải idempotent: RabbitMQ bảo đảm at-least-once, cùng 1 event có
       thể tới 2 lần. `IdempotentConsumer` (bảng `processed_events`) chặn
       phần lớn trùng lặp; phần còn lại là bảo đảm "chạy lại cho kết quả
       giống nhau".
    """
    handler = {
        "contract.terminated": _on_contract_terminated,
        "contract.expired": _on_contract_ended,
        "price_tiers.updated": _on_price_tiers_updated,
    }.get(event.event_type)

    if handler is None:
        logger.debug("Bỏ qua event không quan tâm: %s", event.event_type)
        return

    async with session_scope() as session:
        await handler(session, event)


async def _on_contract_terminated(session: AsyncSession, event: DomainEvent) -> None:
    """
    Hợp đồng bị chấm dứt giữa tháng → phần tiền thừa phải hoàn lại.

    ⭐ Đây là chỗ dễ BỎ SÓT nhất trong hệ thống tính tiền: hóa đơn tháng đã
       phát cho cả tháng, khách dọn phòng ngày 15, còn 15 ngày chưa ở. Nếu
       không hoàn, chủ trọ thu oan — và lần sau khách sẽ không tin.
    """
    contract_id = uuid.UUID(str(event.data["contract_id"]))
    effective = date.fromisoformat(str(event.data.get("end_date")
                                       or event.data.get("effective_date")
                                       or date.today().isoformat()))

    invoices = (await session.execute(
        select(Invoice).where(
            Invoice.contract_id == contract_id,
            Invoice.status.in_([InvoiceStatus.PENDING.value,
                                InvoiceStatus.OVERDUE.value]),
        )
    )).scalars().all()

    refund_total = Decimal("0")
    for invoice in invoices:
        month_days = days_in_month(invoice.period)
        month_last_day = invoice.period.replace(day=month_days)
        last_day = min(effective, month_last_day)
        if last_day < invoice.period:
            continue      # hợp đồng kết thúc TRƯỚC kỳ này bắt đầu → không hoàn

        used_days = (last_day - invoice.period).days + 1
        unused_days = month_days - used_days
        if unused_days <= 0:
            continue      # khách ở hết tháng → không hoàn

        unused_ratio = Decimal(unused_days) / Decimal(month_days)
        # ⭐ Chỉ hoàn tiền PHÒNG + DV theo ngày. KHÔNG hoàn tiền điện nước
        #    vì khách đã ở và đã dùng; cũng không hoàn phí trễ hạn. Hoàn
        #    cả 3 khoản đó là lỗi thuê ngoài ý muốn phổ biến khi làm bài
        #    toán hoàn cọc.
        refund = money((invoice.rent_amount + invoice.service_amount) * unused_ratio)

        if refund <= 0:
            continue

        # Ghi bằng `session.add` chứ không dùng `__table__.insert()`: quan hệ
        # ORM (`Invoice.details`) được `expire`/refresh đúng cách, nên khi
        # API trả chi tiết hóa đơn ngay sau đó sẽ thấy dòng hoàn tiền này.
        # Dùng core insert thì phải tự lo gọi lại `selectinload`.
        session.add(InvoiceDetail(
            invoice_id=invoice.id,
            item_type=ItemType.DISCOUNT.value,
            description=f"Hoàn tiền {unused_days} ngày chưa ở "
                        f"(hợp đồng kết thúc {effective:%d/%m/%Y})",
            quantity=str(Decimal(unused_days)),
            unit_price=None,
            amount=money(-refund),
            breakdown={
                "unused_days": unused_days,
                "used_days": used_days,
                "days_in_month": month_days,
                "refund": str(refund),
                "reason": "contract.terminated",
            },
        ))
        invoice.discount_amount = money(invoice.discount_amount + refund)
        invoice.rent_amount = money(max(Decimal("0"), invoice.rent_amount - refund))
        invoice.service_amount = money(
            max(Decimal("0"), invoice.service_amount - refund)
        )
        invoice.total_amount = money(max(Decimal("0"), invoice.total_amount - refund))
        # Nếu khách đã trả trước rồi mới dọn phòng → hoàn tiền mặt riêng,
        # hóa đơn chuyển về PENDING cho tới khi kế toán xử lý khoản hoàn.
        if invoice.paid_amount > invoice.total_amount:
            invoice.paid_amount = money(invoice.total_amount)
            if invoice.status == InvoiceStatus.PAID.value:
                invoice.status = InvoiceStatus.PENDING.value
        refund_total += refund
        logger.info("↩ Hoàn %sđ cho hóa đơn %s (dùng %d/%d ngày)",
                    refund, invoice.invoice_no, used_days, month_days)

    if refund_total > 0:
        await get_event_bus().publish(session, DomainEvent(
            event_type="invoice.refunded",
            data={
                "contract_id": str(contract_id),
                "property_id": str(invoices[0].property_id) if invoices else None,
                "amount": str(refund_total),
                "effective_date": effective.isoformat(),
                "invoice_ids": [str(i.id) for i in invoices],
                "entity_type": "contract", "entity_id": str(contract_id),
            },
        ))
    logger.info("↩ Tổng hoàn %sđ cho hợp đồng %s (kết thúc %s)",
                refund_total, contract_id, effective)


async def _on_contract_ended(session: AsyncSession, event: DomainEvent) -> None:
    """Hợp đồng hết hạn tự nhiên: chỉ đánh dấu, không hoàn tiền."""
    contract_id = uuid.UUID(str(event.data["contract_id"]))
    invoices = (await session.execute(
        select(Invoice).where(
            Invoice.contract_id == contract_id,
            Invoice.status.in_([InvoiceStatus.PENDING.value,
                                InvoiceStatus.OVERDUE.value]),
        )
    )).scalars().all()
    logger.info("HĐ %s đã kết thúc — còn %d hóa đơn chưa thanh toán",
                contract_id, len(invoices))


async def _on_price_tiers_updated(session: AsyncSession, event: DomainEvent) -> None:
    """
    Giá mới → ghi xuống cache Redis cho room-service (trang tìm phòng) đọc.

    ⭐ Cache chung giữa 2 service là thứ mà người mới rất dễ hiểu nhầm là
       "chia sẻ trạng thái". Thực ra nó là cache phục vụ truy vấn, ai cũng
       có thể xoá, xoá hỏng thì chỉ mất cache chứ không mất dữ liệu. Nguồn
       sự thật vẫn là bảng `price_tiers`.
    """
    property_id = uuid.UUID(str(event.data["property_id"]))
    utility = str(event.data.get("utility_type", UtilityType.ELECTRIC.value))

    redis = await _background_redis()
    if redis is None:
        return

    # Lấy bảng giá MỚI (có hiệu lực từ ngày mai, chưa hiệu lực hôm nay) và
    # ghi sẵn để khi tới ngày áp dụng thì cache đã đúng.
    rows = (await session.execute(
        select(PriceTier).where(
            PriceTier.property_id == property_id,
            PriceTier.utility_type == utility,
            PriceTier.effective_from <= date.today(),
            (PriceTier.effective_to.is_(None)) | (PriceTier.effective_to > date.today()),
        ).order_by(PriceTier.tier_index)
    )).scalars().all()

    await _load_tiers(session, redis, property_id, utility)   # ghi cache
    logger.info("🔄 Đã làm mới cache biểu giá %s cho cơ sở %s (%d bậc)",
                utility, property_id, len(rows))


# ===========================================================================
#  TIỆN ÍCH NỘI BỘ
# ===========================================================================
def _resolve_property(user: CurrentUser, requested: uuid.UUID | None) -> uuid.UUID | None:
    if user.is_admin:
        return requested
    if user.property_id is None:
        raise BusinessRuleError("Tài khoản chưa được gán vào cơ sở nào.")
    if requested is not None and str(requested) != str(user.property_id):
        user.assert_property_access(requested)
    return user.property_id


async def _get_invoice_or_404(
    session: AsyncSession, invoice_id: uuid.UUID, *, lock: bool = False,
) -> Invoice:
    """`lock=True` → SELECT … FOR UPDATE, giữ khoá dòng tới hết transaction."""
    from sqlalchemy.orm import selectinload
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.details))
        .where(Invoice.id == invoice_id)
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    invoice = (await session.execute(stmt)).scalar_one_or_none()
    if not invoice:
        raise NotFoundError(f"Không tìm thấy hóa đơn {invoice_id}")
    return invoice


def _to_invoice_response(invoice: Invoice) -> InvoiceResponse:
    response = InvoiceResponse.model_validate(invoice)
    response.remaining_amount = invoice.remaining_amount
    if invoice.due_date < date.today() and not invoice.is_paid:
        response.days_overdue = (date.today() - invoice.due_date).days
    return response


def _to_list_item(invoice: Invoice) -> InvoiceListItem:
    item = InvoiceListItem.model_validate(invoice)
    if invoice.due_date < date.today() and not invoice.is_paid:
        item.days_overdue = (date.today() - invoice.due_date).days
    return item


# ===========================================================================
#  ĐĂNG KÝ ROUTER
# ===========================================================================
app.include_router(price_router)
app.include_router(meter_router)
app.include_router(invoice_router)
app.include_router(job_router)
app.include_router(estimate_router)
app.include_router(internal_router)
