"""
seed_billing — Biểu giá, chỉ số, hóa đơn & thanh toán (db_billing).

    docker compose exec -T billing python -m scripts.seed_billing

Tạo (cho cơ sở «Nhà trọ Minh Khai»):
  - PriceTier    : biểu giá điện 4 bậc lũy tiến + nước 1 bậc (giá đọc từ env,
                   default theo .env.example — đổi env là đổi được giá mẫu)
  - ServiceFee   : INTERNET / CLEANING / TRASH (bắt buộc) + PARKING (tuỳ chọn)
  - MeterReading : 3 kỳ × 9 phòng đang thuê × 2 loại (điện, nước) = 54 dòng.
                   Cột `consumption` do PostgreSQL tự tính (Computed) — script
                   không thể ghi sai bởi tầng ứng dụng.
  - Invoice      : 3 kỳ × 9 hợp đồng ACTIVE = 27 hóa đơn. Trạng thái:
                       kỳ 1 (cũ nhất): 9 PAID
                       kỳ 2 (giữa)   : 7 PAID + 2 OVERDUE  (hợp đồng #3, #7)
                       kỳ 3 (mới nhất): 1 PAID (trả sớm) + 8 PENDING
                   Hợp đồng #3/#7 phải chịu PHÍ TRỄ HẠN ở kỳ 3 (hóa đơn kỳ 2
                   chưa trả) — đúng luật trong `billing/pricing.late_fee`.
                   Hợp đồng #4 trừ cọc 500.000đ ở kỳ 1 (khớp DEPOSIT_USED của
                   seed_contract — R3), hợp đồng #7 được giảm 200.000đ.
  - InvoiceDetail : dòng chi tiết cho MỌI hóa đơn (để in: RENT/ELECTRIC/WATER/
                    SERVICE/DEPOSIT/DISCOUNT/LATE_FEE)
  - Payment      : cho 17 hóa đơn PAID (9 + 7 + 1)

⭐ ĐIỂM MẤU CHỐT CẦN NÓI TRONG BÁO CÁO — seed bỏ qua EVENT BUS:
   Ghi thẳng bảng `invoices` KHÔNG phát `invoice.created` → read model của
   report-service KHÔNG tự đầy. Sau khi seed phải đối chiếu lại:
       POST /internal/v1/reports/reconcile
   (chính là job `report-reconcile` mà scheduler chạy mỗi 6 giờ).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from billing.pricing import (
    LATE_FEE_MAX_DAYS,
    LATE_FEE_RATE,
    ZERO,
    Tier,
    graduated_charge,
    late_fee,
    money,
    next_due_date,
)
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Invoice,
    InvoiceDetail,
    ItemType,
    MeterReading,
    Payment,
    PriceTier,
    ServiceFee,
)
from scripts._seed_common import (
    ADMIN_ID,
    CONTRACT_IDS,
    CONTRACT_LAYOUT,
    DEPOSIT_USED,
    INVOICE_DISCOUNTS,
    MANAGER_ID,
    PROPERTY_ID,
    ROOM_PRICES,
    TENANT_IDS,
    TENANT_NAMES,
    TODAY,
    env_money,
    last_full_months,
    uid,
    upsert,
)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")

#: Những hợp đồng "quên trả" hóa đơn kỳ giữa → bị đánh dấu OVERDUE + phạt ở kỳ sau
OVERDUE_CONTRACTS = {3, 7}
#: Hợp đồng trả sớm hóa đơn kỳ mới nhất (gương mẫu)
EARLY_PAYER_CONTRACT = 8

METHODS = ("CASH", "BANK_TRANSFER", "MOMO")


def _tier_rows(usage: Decimal, tiers: list[Tier]) -> tuple[Decimal, list[dict]]:
    """
    (Số tiền, danh sách bậc đã dùng) — bản sao thuật toán của
    `graduated_charge` để có dữ liệu IN hóa đơn. ⚠️ SỐ TIỀN LẤY TỪ
    `graduated_charge`; hàm này CHỈ để dựng `breakdown` hiển thị.
    """
    ordered = sorted(tiers, key=lambda t: (t.up_to is None, t.up_to or ZERO))
    rows: list[dict] = []
    remaining, previous_top = usage, ZERO
    for tier in ordered:
        if remaining <= 0:
            break
        if tier.up_to is None:
            in_tier = remaining
        else:
            in_tier = min(remaining, tier.up_to - previous_top)
            if in_tier <= 0:
                previous_top = max(previous_top, tier.up_to)
                continue
        rows.append({
            "up_to": "∞" if tier.up_to is None else str(tier.up_to),
            "unit_price": str(tier.price_per_unit),
            "qty": str(in_tier),
            "amount": str(money(in_tier * tier.price_per_unit)),
        })
        remaining -= in_tier
        if tier.up_to is not None:
            previous_top = tier.up_to
    return graduated_charge(usage, tiers), rows


async def seed(session: AsyncSession) -> dict:
    # ---------------------------------------------------------------- (1)
    #  BIỂU GIÁ — phiên bản đang hiệu lực: mở từ 6 tháng trước, chưa đóng
    # ----------------------------------------------------------------
    effective_from = last_full_months(6)[0]
    tier1 = env_money("DEFAULT_ELECTRIC_TIER1_PRICE", "1800")
    water_price = env_money("DEFAULT_WATER_PRICE", "15000")

    electric_tiers: list[Tier] = [
        Tier(Decimal("50"), tier1),
        Tier(Decimal("100"), Decimal("2500")),
        Tier(Decimal("200"), Decimal("3100")),
        Tier(None, Decimal("3500")),
    ]
    water_tiers: list[Tier] = [Tier(None, water_price)]

    for index, (up_to, price) in enumerate(
        [(t.up_to, t.price_per_unit) for t in electric_tiers], start=1
    ):
        await upsert(
            session, PriceTier, "id",
            {"id": uid("pricetier", "ELECTRIC", str(index)),
             "property_id": PROPERTY_ID,
             "utility_type": "ELECTRIC",
             "tier_index": index,
             "up_to_qty": up_to,                    # None = bậc cuối
             "unit_price": price,
             "effective_from": effective_from,
             "effective_to": None},
            unique_by=("property_id", "utility_type", "tier_index", "effective_from"),
        )
    await upsert(
        session, PriceTier, "id",
        {"id": uid("pricetier", "WATER", "1"),
         "property_id": PROPERTY_ID,
         "utility_type": "WATER",
         "tier_index": 1,
         "up_to_qty": None,
         "unit_price": water_price,
         "effective_from": effective_from,
         "effective_to": None},
        unique_by=("property_id", "utility_type", "tier_index", "effective_from"),
    )

    # ---------------------------------------------------------------- (2)
    #  PHÍ DỊCH VỤ CỐ ĐỊNH — bảng giá mặc định của cơ sở (.env.example)
    # ----------------------------------------------------------------
    service_fees = (
        ("INTERNET", "Internet cáp quang",
         env_money("DEFAULT_INTERNET_FEE", "100000"), True),
        ("CLEANING", "Vệ sinh chung",
         env_money("DEFAULT_CLEANING_FEE", "50000"), True),
        ("TRASH", "Phí thu gom rác",
         env_money("DEFAULT_TRASH_FEE", "20000"), True),
        ("PARKING", "Gửi xe máy", Decimal("100000"), False),
    )
    for code, name, amount, mandatory in service_fees:
        await upsert(
            session, ServiceFee, "id",
            {"id": uid("servicefee", code),
             "property_id": PROPERTY_ID,
             "code": code, "name": name, "amount": amount,
             "is_mandatory": mandatory, "is_active": True},
            unique_by=("property_id", "code"),
        )

    # ---------------------------------------------------------------- (3)
    #  CHỈ SỐ ĐIỆN NƯỚC — 3 kỳ × 9 phòng đang thuê. `consumption` tự tính.
    # ----------------------------------------------------------------
    periods = last_full_months(3)                 # kỳ 0 = cũ nhất
    readings: dict[tuple[str, str, date], tuple[Decimal, Decimal]] = {}
    active = [(c, t, r, d) for c, t, r, s, d in CONTRACT_LAYOUT if s == "ACTIVE"]

    meter_rows = 0
    for cx, _tx, room_no, _days_left in active:
        prev = {"ELECTRIC": Decimal(str(800 + cx * 50)),
                "WATER": Decimal(str(60 + cx * 9))}
        for pidx, period in enumerate(periods):
            usages = {
                "ELECTRIC": Decimal(str(55 + (cx * 9 % 75) + pidx * 4)),
                "WATER": Decimal(str(4 + (cx * 5 % 9) + pidx)),
            }
            for kind, usage in usages.items():
                previous = prev[kind]
                value = previous + usage
                readings[(room_no, kind, period)] = (value, usage)
                await upsert(
                    session, MeterReading, "id",
                    {"id": uid("meter", room_no, kind, period.isoformat()),
                     "property_id": PROPERTY_ID,
                     "room_id": uid("room", room_no),
                     "utility_type": kind,
                     "period": period,
                     "reading_value": value,
                     "previous_value": previous,
                     "read_by": MANAGER_ID,
                     "read_at": datetime.combine(
                         period + timedelta(days=4), time(9, 30), tzinfo=TZ)},
                    unique_by=("room_id", "utility_type", "period"),
                )
                prev[kind] = value
                meter_rows += 1

    # ---------------------------------------------------------------- (4)
    #  HÓA ĐƠN — 3 kỳ × 9 hợp đồng ACTIVE
    # ----------------------------------------------------------------
    invoices = details = payments = 0
    due_p1 = next_due_date(periods[1])            # do kỳ 2 (để tính phạt trễ hạn)
    days_late_p1 = (TODAY - due_p1).days

    for cx, tx, room_no, _days_left in active:
        contract_id = CONTRACT_IDS[cx - 1]
        room_id = uid("room", room_no)
        tenant_id = TENANT_IDS[tx - 1]
        full_name, _phone, _email = TENANT_NAMES[tx - 1]
        monthly = money(ROOM_PRICES[room_no])

        for pidx, period in enumerate(periods):
            # ---- từng khoản tiền ------------------------------------------
            elec_value, elec_usage = readings[(room_no, "ELECTRIC", period)]
            water_value, water_usage = readings[(room_no, "WATER", period)]
            elec_amount, elec_rows = _tier_rows(elec_usage, electric_tiers)
            water_amount, water_rows = _tier_rows(water_usage, water_tiers)
            services_total = sum((f[2] for f in service_fees if f[3]), ZERO)

            late = ZERO
            if pidx == 2 and cx in OVERDUE_CONTRACTS and days_late_p1 > 0:
                late = late_fee(monthly, days_late_p1)

            discount = money(INVOICE_DISCOUNTS.get(cx, "0")) if pidx == 0 else ZERO

            # ---- trừ cọc (R3: không trừ quá số cọc còn lại / không âm) ----
            deposit_used = ZERO
            if pidx == 0 and cx in DEPOSIT_USED:
                remaining = monthly                     # cọc = 1 tháng, chưa dùng
                deposit_used = min(money(DEPOSIT_USED[cx]), remaining)
            remaining_total = (monthly + elec_amount + water_amount + services_total
                               + late - discount)
            deposit_used = min(deposit_used, max(ZERO, remaining_total))

            total = money(remaining_total - deposit_used)

            # ---- trạng thái & thanh toán -----------------------------------
            if pidx == 0 or (pidx == 1 and cx not in OVERDUE_CONTRACTS) \
                    or (pidx == 2 and cx == EARLY_PAYER_CONTRACT):
                status = "PAID"
                paid_amount = total
                if pidx == 2:                           # trả sớm
                    paid_at = datetime.combine(period + timedelta(days=1),
                                               time(8, 0), tzinfo=TZ)
                else:
                    paid_at = datetime.combine(next_due_date(period)
                                               + timedelta(days=1),
                                               time(9, 0), tzinfo=TZ)
            elif pidx == 1 and cx in OVERDUE_CONTRACTS:
                status, paid_amount, paid_at = "OVERDUE", ZERO, None
            else:
                status, paid_amount, paid_at = "PENDING", ZERO, None

            invoice_id = uid("invoice", period.isoformat(), room_no)
            await upsert(session, Invoice, "id", {
                "id": invoice_id,
                "invoice_no": f"HD-{period:%Y%m}-{cx:04d}",
                "property_id": PROPERTY_ID,
                "contract_id": contract_id,
                "room_id": room_id,
                "tenant_id": tenant_id,
                "tenant_name": full_name,
                "room_number": room_no,
                "period": period,
                "rent_amount": monthly,
                "electric_amount": elec_amount,
                "water_amount": water_amount,
                "service_amount": services_total,
                "late_fee_amount": late,
                "discount_amount": discount,
                "deposit_deducted": deposit_used,
                "total_amount": total,
                "paid_amount": paid_amount,
                "status": status,
                "due_date": next_due_date(period),
                "paid_at": paid_at,
                "is_final": True,
                "created_by": ADMIN_ID,
            })
            invoices += 1

            # ---- dòng chi tiết để in ---------------------------------------
            # Mỗi dòng mang `key` riêng để sinh UUID tất định không trùng
            # (điện/nước có thể có nhiều bậc, SERVICE có 3 dòng…).
            detail_rows: list[tuple[str, str, str, str | None, Decimal, Decimal, dict]] = [
                ("RENT", ItemType.RENT.value, f"Tiền phòng tháng {period:%m/%Y}",
                 "1", monthly, money(monthly), {}),
                ("ELEC", ItemType.ELECTRIC.value,
                 f"Điện {elec_usage} kWh ({elec_value - elec_usage} → {elec_value})",
                 str(elec_usage), None, elec_amount, {"tiers": elec_rows}),
                ("WATER", ItemType.WATER.value,
                 f"Nước {water_usage} m³ ({water_value - water_usage} → {water_value})",
                 str(water_usage), None, water_amount, {"tiers": water_rows}),
            ]
            for code, name, amount, mandatory in service_fees:
                if not mandatory:
                    continue
                detail_rows.append(
                    (f"SERVICE-{code}", ItemType.SERVICE.value, name,
                     "1", amount, money(amount), {"code": code}),
                )
            if late > 0:
                detail_rows.append(
                    ("LATE", ItemType.LATE_FEE.value,
                     f"Phí trễ hạn {days_late_p1} ngày "
                     f"(hóa đơn kỳ {periods[1]:%m/%Y} chưa thanh toán)",
                     str(Decimal(days_late_p1)), money(monthly * LATE_FEE_RATE),
                     late, {"days_late": days_late_p1, "rate": str(LATE_FEE_RATE),
                            "cap_days": LATE_FEE_MAX_DAYS}),
                )
            if discount > 0:
                detail_rows.append(
                    ("DISCOUNT", ItemType.DISCOUNT.value, "Khuyến mãi nhập trọ",
                     "1", money(-discount), money(-discount), {}),
                )
            if deposit_used > 0:
                detail_rows.append(
                    ("DEPOSIT", ItemType.DEPOSIT.value, "Trừ tiền cọc",
                     "1", money(-deposit_used), money(-deposit_used),
                     {"deposit_remaining": str(monthly)}),
                )

            for key, item_type, description, qty, unit_price, amount, breakdown in detail_rows:
                await upsert(session, InvoiceDetail, "id", {
                    "id": uid("invdetail", period.isoformat(), room_no, key),
                    "invoice_id": invoice_id,
                    "item_type": item_type,
                    "description": description,
                    "quantity": Decimal(qty) if qty is not None else None,
                    "unit_price": money(unit_price) if unit_price is not None else None,
                    "amount": amount,
                    "breakdown": breakdown,
                })
                details += 1

            # ---- thanh toán (chỉ hóa đơn PAID) -----------------------------
            if status == "PAID":
                await upsert(session, Payment, "id", {
                    "id": uid("payment", period.isoformat(), room_no),
                    "invoice_id": invoice_id,
                    "amount": total,
                    "method": METHODS[(cx + pidx) % 3],
                    "reference": None,
                    "receipt_no": f"PT-{period:%Y%m}-{cx:02d}",
                    "received_by": MANAGER_ID if (cx + pidx) % 2 == 0 else ADMIN_ID,
                    "received_at": paid_at,
                    "note": None,
                })
                payments += 1

    await session.flush()
    print(
        "\n⚠️  Seed ghi THẲNG vào bảng, KHÔNG phát event bus → read model của\n"
        "   report-service chưa đầy. Hãy chạy đối chiếu (scheduler làm mỗi 6h):\n"
        "     curl -X POST http://report:8008/internal/v1/reports/reconcile\n"
    )
    return {
        "bac_gia": 5,
        "phi_dich_vu": len(list(service_fees)),
        "chi_so": meter_rows,
        "hoa_don": invoices,
        "dong_chi_tiet": details,
        "da_thu": payments,
        "qua_han": 2,
    }


def main() -> int:
    from scripts._seed_common import run_seed

    return asyncio.run(run_seed("billing-service", seed))


if __name__ == "__main__":
    sys.exit(main())
