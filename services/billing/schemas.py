"""Schema Pydantic của billing-service — biểu giá, chỉ số, hóa đơn, thanh toán."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MONEY = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=0)]
QTY = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


# ===========================================================================
#  BIỂU GIÁ
# ===========================================================================
class PriceTierInput(BaseModel):
    """Một bậc giá khi tạo/cập nhật biểu giá."""

    up_to_qty: QTY | None = Field(
        default=None, description="Trần của bậc. NULL = bậc cuối, không giới hạn"
    )
    unit_price: MONEY

    @field_validator("up_to_qty")
    @classmethod
    def _positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("Trần bậc phải lớn hơn 0 (số kWh/m³ dương)")
        return v


class PriceScheduleCreate(BaseModel):
    """
    Tạo bộ biểu giá mới, có hiệu lực từ một ngày.

    ⭐ Gửi lại TOÀN BỘ các bậc, không phải "bậc cần sửa". Lý do: nếu cho
       cập nhật lẻ từng bậc, sẽ có trạng thái "bảng giá nửa cũ nửa mới" —
       hóa đơn tính ra số liệu không ai giải thích được.
    """

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "utility_type": "ELECTRIC",
            "effective_from": "2026-10-01",
            "tiers": [
                {"up_to_qty": "50", "unit_price": "1800"},
                {"up_to_qty": "100", "unit_price": "2500"},
                {"up_to_qty": "200", "unit_price": "3100"},
                {"up_to_qty": None, "unit_price": "3500"},
            ],
        }
    })

    utility_type: Literal["ELECTRIC", "WATER"]
    effective_from: date
    tiers: list[PriceTierInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _tiers_increasing(self) -> PriceScheduleCreate:
        # Bậc cuối (up_to_qty = None) phải đứng cuối, và các trần phải tăng dần.
        # Nếu không, `graduated_charge` sẽ tính ra số tiền vô nghĩa mà không
        # báo lỗi — kiểu lỗi "chạy được nhưng sai".
        tops = [t.up_to_qty for t in self.tiers]
        if None in tops[:-1]:
            raise ValueError("Chỉ bậc CUỐI CÙNG được để trần bằng null (không giới hạn)")
        finite = [t for t in tops if t is not None]
        if finite != sorted(finite):
            raise ValueError("Các bậc phải sắp theo trần tăng dần")
        if len(set(finite)) != len(finite):
            raise ValueError("Có 2 bậc cùng trần — không hợp lệ")
        return self


class PriceTierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    utility_type: str
    tier_index: int
    up_to_qty: Decimal | None
    unit_price: Decimal
    effective_from: date
    effective_to: date | None


class ServiceFeeCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"code": "INTERNET", "name": "Internet cáp quang", "amount": "100000"}
    })

    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=100)
    amount: MONEY
    is_mandatory: bool = True


class ServiceFeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    code: str
    name: str
    amount: Decimal
    is_mandatory: bool
    is_active: bool


# ===========================================================================
#  CHỈ SỐ ĐIỆN NƯỚC
# ===========================================================================
class MeterReadingCreate(BaseModel):
    """
    Nhập chỉ số đồng hồ.

    ⭐ R4 — nghiệp vụ chỉ nhận `reading_value` (chỉ số hiện tại), KHÔNG nhập
       `consumption`. Vì bảo đảm "chỉ số không giảm" chỉ kiểm được khi so với
       kỳ trước — mà kỳ trước là dữ liệu trong DB, không phải dữ liệu client
       gửi lên. Cho client gửi cả hai sẽ mở đường cho việc lách luật.
    """

    model_config = ConfigDict(json_schema_extra={
        "example": {"room_id": "0c4e...-...", "utility_type": "ELECTRIC",
                    "period": "2026-10-01", "reading_value": "1284.50",
                    "note": "Đọc ngày 01/10"}
    })

    property_id: uuid.UUID
    room_id: uuid.UUID
    utility_type: Literal["ELECTRIC", "WATER"]
    period: date = Field(description="Kỳ dạng YYYY-MM-01 (ngày 1 của tháng)")
    reading_value: QTY
    note: str | None = Field(default=None, max_length=500)

    @field_validator("period")
    @classmethod
    def _first_of_month(cls, v: date) -> date:
        if v.day != 1:
            raise ValueError(
                "Kỳ phải là ngày 1 của tháng (YYYY-MM-01). "
                f"Bạn gửi ngày {v.day}. Lý do: kỳ tính tiền LUÔN theo tháng, "
                "cho phép nhập kỳ lệch 1 ngày chỉ tạo ra 2 kỳ khác nhau."
            )
        return v


class MeterReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    room_id: uuid.UUID
    utility_type: str
    period: date
    reading_value: Decimal
    previous_value: Decimal | None
    consumption: Decimal | None
    read_at: datetime
    note: str | None

    # Tính tiền tức thời để người nhập biết mình vừa ghi bao nhiêu tiền
    estimated_amount: Decimal | None = None
    charge_breakdown: list[dict] | None = None


class MeterReadingBatch(BaseModel):
    """Nhập nhiều phòng cùng lúc (chụp 20 chỉ số trong 10 phút rồi gõ lại)."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "property_id": "6b1f...-...",
            "period": "2026-10-01",
            "readings": [
                {"room_id": "...", "utility_type": "ELECTRIC",
                 "reading_value": "1284.50"},
            ],
        }
    })

    property_id: uuid.UUID
    period: date
    readings: list[MeterReadingCreate] = Field(min_length=1, max_length=500)

    @field_validator("period")
    @classmethod
    def _first_of_month(cls, v: date) -> date:
        if v.day != 1:
            raise ValueError("Kỳ phải là ngày 1 của tháng (YYYY-MM-01)")
        return v


# ===========================================================================
#  HÓA ĐƠN
# ===========================================================================
class InvoiceDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_type: str
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    property_id: uuid.UUID
    contract_id: uuid.UUID
    room_id: uuid.UUID
    room_number: str | None
    tenant_id: uuid.UUID | None
    tenant_name: str
    period: date
    rent_amount: Decimal
    electric_amount: Decimal
    water_amount: Decimal
    service_amount: Decimal
    late_fee_amount: Decimal
    discount_amount: Decimal
    deposit_deducted: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    remaining_amount: Decimal = Decimal("0")
    status: str
    due_date: date
    paid_at: datetime | None
    created_at: datetime
    days_overdue: int | None = None
    details: list[InvoiceDetailResponse] = Field(default_factory=list)


class InvoiceListItem(BaseModel):
    """Danh sách — không kèm chi tiết để response nhẹ."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    property_id: uuid.UUID
    room_id: uuid.UUID
    room_number: str | None
    tenant_id: uuid.UUID | None
    tenant_name: str
    period: date
    total_amount: Decimal
    paid_amount: Decimal
    status: str
    due_date: date
    days_overdue: int | None = None


class PaymentCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"amount": "2350000", "method": "BANK_TRANSFER",
                    "reference": "FT20261015-00123"}
    })

    amount: MONEY
    method: Literal["CASH", "BANK_TRANSFER", "MOMO", "VNPAY", "CARD"]
    reference: str | None = Field(default=None, max_length=100)
    receipt_no: str | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("amount")
    @classmethod
    def _not_zero(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Số tiền thanh toán phải lớn hơn 0")
        return v


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    amount: Decimal
    method: str
    reference: str | None
    receipt_no: str | None
    received_by: uuid.UUID
    received_at: datetime
    note: str | None


class GenerateJobRequest(BaseModel):
    """
    Yêu cầu tính tiền hàng loạt cho 1 kỳ.

    `skip_existing=True` (mặc định) nghĩa là đã có hóa đơn thì bỏ qua — đây
    là chốt chặn quan trọng nhất khi bấm nút 2 lần. Người dùng thường bấm vội,
    hoặc bấm lại vì thấy mạng chậm mà không biết đã chạy xong chưa.
    """

    model_config = ConfigDict(json_schema_extra={
        "example": {"property_id": "6b1f...-...", "period": "2026-10-01"}
    })

    property_id: uuid.UUID
    period: date
    skip_existing: bool = True
    include_deposit_deduction: bool = True
    dry_run: bool = Field(
        default=False,
        description="Chỉ tính thử, không ghi hóa đơn — dùng để xem trước trước khi phát",
    )

    @field_validator("period")
    @classmethod
    def _first_of_month(cls, v: date) -> date:
        if v.day != 1:
            raise ValueError("Kỳ tính tiền phải là ngày 1 của tháng (YYYY-MM-01)")
        return v


class BillingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    period: date
    status: str
    total_contracts: int
    processed: int
    succeeded: int
    failed: int
    progress: float = 0.0
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class InvoiceStats(BaseModel):
    """Tổng hợp nhanh cho dashboard tài chính."""

    property_id: uuid.UUID | None = None
    period: date | None = None
    total_invoices: int = 0
    paid: int = 0
    pending: int = 0
    overdue: int = 0
    total_billed: Decimal = Decimal("0")
    total_collected: Decimal = Decimal("0")
    total_outstanding: Decimal = Decimal("0")
    collection_rate: float = Field(
        default=0.0, description="Tỷ lệ thu hồi tiền (%)"
    )


class TariffEstimate(BaseModel):
    """
    Mức tiêu thụ trung bình dùng để ƯỚC TÍNH giá phòng trên trang công khai.

    ⭐ Chỉ phục vụ hiển thị. Không bao giờ dùng để thu tiền — người thuê xem
       giá thật khi nhận hóa đơn. Nếu dùng để thu tiền thì mọi sai lệch ước
       tính đều thành khiếu nại.
    """

    property_id: uuid.UUID | None = None
    average_monthly_kwh: Decimal = Decimal("100")
    average_monthly_m3: Decimal = Decimal("4")
    average_electric_cost: Decimal = Decimal("190000")
    average_water_cost: Decimal = Decimal("60000")
    average_services_cost: Decimal = Decimal("0")
    average_total_per_room: Decimal = Decimal("0")
    based_on_invoices: int = 0
    is_estimate: bool = True


__all__ = [
    "MONEY",
    "QTY",
    "BillingJobResponse",
    "GenerateJobRequest",
    "InvoiceDetailResponse",
    "InvoiceListItem",
    "InvoiceResponse",
    "InvoiceStats",
    "MeterReadingBatch",
    "MeterReadingCreate",
    "MeterReadingResponse",
    "PaymentCreate",
    "PaymentResponse",
    "PriceScheduleCreate",
    "PriceTierInput",
    "PriceTierResponse",
    "ServiceFeeCreate",
    "ServiceFeeResponse",
    "TariffEstimate",
]
