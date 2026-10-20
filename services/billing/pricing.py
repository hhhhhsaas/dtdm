"""
billing-service — Công thức tính tiền.   Cổng 8005  |  db_billing

===============================================================================
⚠️  FILE NÀY LÀ "LUẬT" CỦA HỆ THỐNG. SỬA Ở ĐÂY = ĐỔI TIỀN THẬT CỦA KHÁCH.
===============================================================================

Vì sao tách riêng, không viết thẳng vào `main.py`?
  - Công thức là thứ CẦN ĐỊNH NGHĨA KỸ và CẦN TEST ĐỘC LẬP. Đặt riêng, ta
    test được "100 kWh tiêu bao nhiêu tiền" mà không cần dựng cả service,
    không cần database, không cần HTTP.
  - Nó là tài liệu thực thi: đọc file này là hiểu hệ thống tính tiền ra sao.
    Nhóm có thể đối chiếu với hợp đồng thuê mà không cần đọc code khác.

===============================================================================
BA NGUYÊN TẮC KHÔNG ĐƯỢC PHÁM VỠ
===============================================================================
  1. KHÔNG BAO GIỜ dùng `float`. 0.1 + 0.2 != 0.3 trong IEEE-754. Với hóa
     đơn 2.350.000đ, sai số 1e-9 đi qua 4 phép nhân rồi làm tròn có thể lệch
     tới vài nghìn đồng → người thuê khiếu nại, mình không biết sai ở đâu.
     Mọi phép tính tiền ở đây dùng `Decimal` và `ROUND_HALF_UP`.

  2. BIỂU GIÁ BẬC THANG là LŨY TIẾN, không phải bậc đơn. 220 kWh KHÔNG
     phải 220 × giá(bậc 4). Sai lầm này phổ biến nhất khi làm bài toán
     điện nước, và mỗi hộ dân bị tính thiệt.

  3. TIỀN CỌC KHÔNG BAO GIỜ ÂM (R3). Trừ cọc phải có `min(remaining, total)`.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

#: VND là số nguyuan — mọi kết quả trả về đều làm tròn về đồng
MONEY = Decimal("1")
ZERO = Decimal("0")


def money(value: Decimal | int | float | str) -> Decimal:
    """
    Ép mọi thứ về `Decimal` rồi làm tròn về đồng.

    CỐ Ý chuyển `float` thành `Decimal` qua `str`, KHÔNG qua `Decimal(float)`.
    Vì `Decimal(0.1)` = 0.1000000000000000055511151231257827…, còn
    `Decimal(str(0.1))` = 0.1. Chỉ một ký tự `str` nhưng sai số 5e-18 —
    và sai số ấy nhân lên 200 hóa đơn thành tiền thật.
    """
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
#  Biểu giá bậc thang
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Tier:
    """
    Một bậc giá: từ 0 đến `up_to` đơn vị, giá `price_per_unit` mỗi đơn vị.

    ⭐ `up_to_kwh = None` nghĩa là bậc cuối, không giới hạn. Dùng `None` thay vì
       `Decimal("Infinity")` vì `Decimal("Infinity")` nhân với số bất thường
       có thể ném `decimal.InvalidOperation` — rủi ro runtime không đáng có.
    """

    up_to: Decimal | None          # trần của bậc (None = bậc cuối)
    price_per_unit: Decimal

    def __repr__(self) -> str:
        top = "∞" if self.up_to is None else str(self.up_to)
        return f"≤{top} × {self.price_per_unit}"


def graduated_charge(usage: Decimal, tiers: list[Tier]) -> Decimal:
    """
    Tính tiền theo biểu giá bậc thang LŨY TIẾN.

    Ví dụ: dùng 220 kWh, các bậc 0–50:1800, 51–100:2500, 101–200:3100,
    >200:3500 (VND/kWh):

        50  × 1.800 =  90.000
        50  × 2.500 = 125.000
        100 × 3.100 = 310.000
        20  × 3.500 =  70.000
        ────────────────────────
        tổng          595.000đ

    ⚠️  KHÔNG được viết `usage × giá_của_bậc_cuối_có_chứa_usage` — đó là
        "bậc đơn", tính sai và người thuê bị thu đắp hơn hàng trăm nghìn mỗi
        tháng. Đây là lỗi phổ biến nhất khi lập trình bài toán điện nước.

    Args:
        usage: lượng tiêu thụ (kWh hoặc m³), không âm
        tiers: các bậc, KHÔNG cần sắp xếp trước (hàm tự sắp)

    Returns:
        Tổng tiền, đã làm tròn về đồng.
    """
    if usage < 0:
        raise ValueError("Lượng tiêu thụ không thể âm")

    if not tiers:
        return ZERO

    # `None` (bậc không giới hạn) luôn phải đứng cuối, kể cả khi người nhập
    # liệu xếp sai. Sắp xếp lại ở đây thay vì tin tưởng input.
    ordered = sorted(tiers, key=lambda t: (t.up_to is None, t.up_to or ZERO))

    total = ZERO
    remaining = usage
    previous_top = ZERO

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

        total += in_tier * tier.price_per_unit
        remaining -= in_tier
        if tier.up_to is not None:
            previous_top = tier.up_to

    return money(total)


#: Biểu giá điện dân dụng Việt Nam (đơn giá bậc thang, VND/kWh)
DEFAULT_ELECTRIC_TIERS: list[Tier] = [
    Tier(Decimal("50"), Decimal("1800")),
    Tier(Decimal("100"), Decimal("2500")),
    Tier(Decimal("200"), Decimal("3100")),
    Tier(None, Decimal("3500")),
]

#: Biểu giá nước sinh hoạt (VND/m³) — không bậc thang, đơn giá đơn
DEFAULT_WATER_TIERS: list[Tier] = [Tier(None, Decimal("15000"))]


# ---------------------------------------------------------------------------
#  Tiền phòng
# ---------------------------------------------------------------------------
def days_in_month(period: date) -> int:
    """Số ngày thực tế trong tháng (28/29/30/31) — dùng `calendar`, không đoán mò."""
    return calendar.monthrange(period.year, period.month)[1]


def billable_days(start_date: date, end_date: date, period: date) -> int:
    """
    Số ngày trong `period` mà hợp đồng còn hiệu lực.

    Cần thiết vì ở Việt Nam phổ biến cả 2 trường hợp:
      - dọn phòng ngày 15 → tháng đó chỉ tính 15 ngày tiền phòng
      - nhận phòng ngày 20 → chỉ tính 11 ngày

    Nếu cứ nhân `monthly_price` với 1 tháng đầy đủ, chủ trọ thu thiệt oan;
    người thuê phản đối thì mất uy tín.
    """
    if period.year != start_date.year or period.month != start_date.month:
        return 0

    month_start = period.replace(day=1)
    month_end = period.replace(day=days_in_month(period))

    # Khoảng giao của hợp đồng với tháng
    lo = max(start_date, month_start)
    hi = min(end_date, month_end)
    if hi < lo:
        return 0
    return (hi - lo).days + 1


def prorated_rent(monthly_price: Decimal, start_date: date, end_date: date,
                  period: date) -> tuple[Decimal, int]:
    """
    Tiền phòng theo ngày thực tế.

        rent = monthly_price × (số ngày thuê / số ngày trong tháng)

    ⭐ Vì sao chia theo "ngày trong tháng" chứ không dùng `relativedelta`?
        Vì tháng có 28/29/30/31 ngày. Dùng hàm số cố định 30 sẽ tính sai tháng 2
        (28 ngày → dư tiền) và tháng 7 (31 ngày → thiếu tiền). Chênh lệch
        2.500.000 × 3/31 ≈ 240.000đ mỗi tháng — đủ để sinh khiếu nại.
    """
    billable = billable_days(start_date, end_date, period)
    if billable <= 0:
        return ZERO, 0
    total_days = days_in_month(period)
    rent = money(Decimal(monthly_price) * Decimal(billable) / Decimal(total_days))
    return rent, billable


# ---------------------------------------------------------------------------
#  Phí trễ hạn
# ---------------------------------------------------------------------------
#: Hệ số phạt mỗi ngày trễ (5% tiền phòng)
LATE_FEE_RATE = Decimal("0.05")
#: Trần phí trễ hạn — không thể phạt vô hạn, nếu không hợp đồng dễ bị vô hiệu
LATE_FEE_MAX_DAYS = 30


def late_fee(monthly_price: Decimal, days_overdue: int) -> Decimal:
    """
    Phí trễ hạn = 5% × tiền phòng × số ngày trễ, tối đa 30 ngày.

    ⭐ Trần 30 ngày là điều khoản bảo vệ chủ trọ: nếu khách trễ 6 tháng thì
       phạt cũng chỉ bằng 1,5 tháng tiền phòng. Không có trần, hóa đơn có
       thể lớn hơn cả tiền cọc và dễ khiếu nại.
    """
    if days_overdue <= 0:
        return ZERO
    capped = min(days_overdue, LATE_FEE_MAX_DAYS)
    return money(Decimal(monthly_price) * LATE_FEE_RATE * Decimal(capped))


# ---------------------------------------------------------------------------
#  Tổng hợp hóa đơn
# ---------------------------------------------------------------------------
@dataclass
class InvoiceTotals:
    """
    Kết quả tính tiền cho 1 hợp đồng trong 1 kỳ.

    Dùng `dataclass` thay vì dict: khi có 7 khoản tiền, gõ nhầm tên biến sẽ
    được Python bắt ngay lúc chạy. Với dict, `tota_amount` sẽ tạo ra một
    khoá mới = 0 đồng và hóa đơn ra sai mà không báo lỗi.
    """

    rent: Decimal = ZERO
    electric: Decimal = ZERO
    water: Decimal = ZERO
    services: Decimal = ZERO
    late_fee: Decimal = ZERO
    discount: Decimal = ZERO
    deposit_deducted: Decimal = ZERO

    @property
    def subtotal(self) -> Decimal:
        """Tổng chi phí TRƯỚC khi trừ cọc."""
        return money(
            self.rent + self.electric + self.water + self.services + self.late_fee
            - self.discount
        )

    @property
    def total(self) -> Decimal:
        """Tổng phải trả. KHÔNG BAO GIỜ âM (R3)."""
        return money(max(ZERO, self.subtotal - self.deposit_deducted))

    def as_dict(self) -> dict[str, Decimal]:
        return {
            "rent_amount": money(self.rent),
            "electric_amount": money(self.electric),
            "water_amount": money(self.water),
            "service_amount": money(self.services),
            "late_fee_amount": money(self.late_fee),
            "discount_amount": money(self.discount),
            "deposit_deducted": money(self.deposit_deducted),
            "total_amount": self.total,
        }


def apply_deposit(
    totals: InvoiceTotals,
    deposit_remaining: Decimal,
) -> tuple[InvoiceTotals, Decimal]:
    """
    Trừ tiền cọc vào hóa đơn — nơi DUY NHẤT được phép làm việc này.

    ⭐ R3 — 3 lớp bảo vệ:
        1. `min(deposit_remaining, subtotal)` — không trừ quá số cọc còn lại
        2. `max(0, ...)`                 — hóa đơn không bao giờ âm
        3. CHECK constraint ở DB của contract-service (`deposit_deducted <=
           deposit_amount`) — chặn cả khi có ai UPDATE tay bằng psql

    Trả về `(totals_mới, số_tiền_đã_trừ)` — số tiền đã trừ được gửi lại
    contract-service để cập nhật `deposit_deducted`, nên phải đúng tuyệt đối.
    """
    remaining = max(ZERO, Decimal(deposit_remaining))
    used = min(remaining, totals.subtotal)
    if used < 0:
        used = ZERO
    totals.deposit_deducted = money(used)
    return totals, totals.deposit_deducted


def next_due_date(period: date) -> date:
    """
    Hạn thanh toán: ngày 3 của tháng kế tiếp.

    Cho phép trả muộn tới đầu tháng sau (phổ biến ở Việt Nam) nhưng vẫn gây
    áp lực: quá ngày 3 mới tính phí trễ hạn.
    """
    if period.month == 12:
        return date(period.year + 1, 1, 3)
    return date(period.year, period.month + 1, 3)


__all__ = [
    "DEFAULT_ELECTRIC_TIERS",
    "DEFAULT_WATER_TIERS",
    "LATE_FEE_MAX_DAYS",
    "LATE_FEE_RATE",
    "MONEY",
    "ZERO",
    "InvoiceTotals",
    "Tier",
    "apply_deposit",
    "billable_days",
    "days_in_month",
    "graduated_charge",
    "late_fee",
    "money",
    "next_due_date",
    "prorated_rent",
]
