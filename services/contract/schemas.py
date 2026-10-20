"""Schema Pydantic của contract-service — hợp đồng thuê, cọc, bạn cùng phòng."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# VND — số nguyên, chặn số âm.
MONEY = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=0)]
# R1 — 1 chủ hợp đồng + tối đa 2 bạn cùng phòng
MAX_ROOMMATES = 2
PHONE_PATTERN = re.compile(r"^(0|\+84)\d{9,10}$")


class PhoneStr(str):
    """Validator dùng chung cho SĐT Việt Nam."""


def _validate_phone(v: str) -> str:
    v = v.strip().replace(" ", "").replace("-", "")
    if not PHONE_PATTERN.match(v):
        raise ValueError("Số điện thoại không hợp lệ (cần dạng 09xxxxxxxx)")
    return v


# ===========================================================================
#  ROOMMATE
# ===========================================================================
class RoommateCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"full_name": "Trần Minh B", "phone": "0912345678",
                    "is_guarantor": False}
    })

    full_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=9, max_length=15)
    id_card_number: str | None = Field(default=None, max_length=20)
    tenant_id: uuid.UUID | None = None
    is_guarantor: bool = False

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        return _validate_phone(v)

    @field_validator("full_name")
    @classmethod
    def _squash(cls, v: str) -> str:
        return " ".join(v.split())


class RoommateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    full_name: str
    phone: str
    id_card_number: str | None
    is_guarantor: bool
    created_at: datetime


class RoommateSet(BaseModel):
    """PUT = thay toàn bộ danh sách bạn cùng phòng."""

    roommates: list[RoommateCreate] = Field(
        max_length=MAX_ROOMMATES,
        description=f"Tối đa {MAX_ROOMMATES} bạn cùng phòng (R1: tổng cộng 3 người/phòng)",
    )

    @field_validator("roommates")
    @classmethod
    def _one_guarantor(cls, v: list[RoommateCreate]) -> list[RoommateCreate]:
        guarantors = [r for r in v if r.is_guarantor]
        if len(guarantors) > 1:
            raise ValueError("Chỉ được có 1 người bảo lãnh")
        names = [r.full_name.lower() for r in v]
        if len(set(names)) != len(names):
            raise ValueError("Trong danh sách có 2 người trùng tên")
        return v


# ===========================================================================
#  CONTRACT
# ===========================================================================
class ContractCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "property_id": "6b1f...-...", "room_id": "0c4e...-...",
            "primary_tenant_id": "9a2c...-...", "primary_tenant_name": "Nguyễn Văn A",
            "primary_tenant_phone": "0901234567", "primary_tenant_email": "a@gmail.com",
            "start_date": "2026-10-01", "end_date": "2027-09-30",
            "monthly_price": "2500000", "deposit_amount": "5000000",
            "payment_cycle": "MONTHLY", "roommates": [],
        }
    })

    property_id: uuid.UUID
    room_id: uuid.UUID
    primary_tenant_id: uuid.UUID
    primary_tenant_name: str = Field(min_length=2, max_length=100)
    primary_tenant_phone: str = Field(min_length=9, max_length=15)
    primary_tenant_email: str | None = Field(default=None, max_length=150)

    start_date: date
    end_date: date
    monthly_price: MONEY
    deposit_amount: MONEY = Decimal("0")
    payment_cycle: Literal["MONTHLY", "QUARTERLY", "YEARLY"] = "MONTHLY"
    terms: dict | None = None
    room_id_confirmed: bool = Field(
        default=False,
        description="Xác nhận phòng đã được kiểm tra trống (client gửi kèm để tránh xung đột)",
    )

    @field_validator("primary_tenant_phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        return _validate_phone(v)

    @field_validator("start_date")
    @classmethod
    def _past_start(cls, v: date) -> date:
        if (v - date.today()).days < -365:
            raise ValueError("Ngày bắt đầu không hợp lý (quá 1 năm trong quá khứ)")
        return v

    @model_validator(mode="after")
    def _check_dates(self) -> ContractCreate:
        if self.end_date <= self.start_date:
            raise ValueError("Ngày kết thúc phải sau ngày bắt đầu")
        months = (self.end_date.year - self.start_date.year) * 12 + \
                 (self.end_date.month - self.start_date.month)
        if months > 60:
            raise ValueError("Hợp đồng không được dài quá 5 năm")
        return self


class ContractUpdate(BaseModel):
    """
    Sửa hợp đồng. CHỈ khi còn ở DRAFT / PENDING_SIGN.

    ⭐ Không sửa được sau khi ACTIVE: hợp đồng đã ký, mọi thay đổi phải qua
       phụ lục hoặc chấm dứt + ký lại. Nếu cho sửa, ai đó đổi giá tháng 2
       của hợp đồng đang chạy → hóa đơn tháng 1 và tháng 2 lệch nhau mà
       không ai hiểu vì sao.
    """

    primary_tenant_name: str | None = Field(default=None, min_length=2, max_length=100)
    primary_tenant_phone: str | None = Field(default=None, min_length=9, max_length=15)
    primary_tenant_email: str | None = Field(default=None, max_length=150)
    start_date: date | None = None
    end_date: date | None = None
    monthly_price: MONEY | None = None
    deposit_amount: MONEY | None = None
    payment_cycle: Literal["MONTHLY", "QUARTERLY", "YEARLY"] | None = None
    terms: dict | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> ContractUpdate:
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("Ngày kết thúc phải sau ngày bắt đầu")
        return self


class DepositCreate(BaseModel):
    """Ghi nhận đã thu tiền cọc."""

    model_config = ConfigDict(json_schema_extra={
        "example": {"amount": "5000000", "method": "BANK_TRANSFER",
                    "receipt_no": "MB-20261001-001"}
    })

    amount: MONEY
    method: Literal["CASH", "BANK_TRANSFER", "MOMO", "VNPAY"] = "CASH"
    receipt_no: str | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=500)


class ActivateRequest(BaseModel):
    """
    Kích hoạt hợp đồng.

    `confirm_deposit` bắt buộc = True: người quản lý phải xác nhận đã thu đủ
    cọc. Bắt buộc bấm 2 lần có chủ đích — một trong những chỗ dễ thất lạc tiền
    nhất trong nghiệp vụ nhà trọ.
    """

    confirm_deposit: bool = Field(
        default=False, description="Xác nhận đã thu đủ tiền cọc ngoài tiền mặt"
    )
    effective_date: date | None = Field(
        default=None, description="Ngày hiệu lực (mặc định = start_date)"
    )


class TerminateRequest(BaseModel):
    """
    Chấm dứt hợp đồng sớm.

    `reason` là BẮT BUỘC: không có lý do thì khi tranh chấp không biết ai sai.
    """

    reason: str = Field(min_length=10, max_length=1000)
    effective_date: date | None = None
    refund_deposit: bool = Field(
        default=False, description="Hoàn lại tiền cọc (ghi nhận trả cọc)"
    )
    penalty_amount: MONEY = Decimal("0")


class RenewRequest(BaseModel):
    """Gia hạn — tạo hợp đồng MỚI, không sửa hợp đồng cũ."""

    new_start_date: date
    new_end_date: date
    new_monthly_price: MONEY | None = Field(
        default=None, description="Để trống = giữ nguyên giá cũ"
    )
    new_deposit_amount: MONEY | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> RenewRequest:
        if self.new_end_date <= self.new_start_date:
            raise ValueError("Ngày kết thúc phải sau ngày bắt đầu")
        return self


class ContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_no: str
    property_id: uuid.UUID
    room_id: uuid.UUID
    primary_tenant_id: uuid.UUID
    primary_tenant_name: str
    primary_tenant_phone: str
    primary_tenant_email: str | None
    start_date: date
    end_date: date
    monthly_price: Decimal
    deposit_amount: Decimal
    deposit_paid_at: datetime | None
    deposit_deducted: Decimal
    remaining_deposit: Decimal = Decimal("0")
    payment_cycle: str
    status: str
    terminated_reason: str | None
    terms: dict | None
    created_at: datetime
    activated_at: datetime | None

    room_number: str | None = Field(default=None, description="Lấy từ room-service")
    roommates: list[RoommateResponse] = Field(default_factory=list)
    days_remaining: int | None = None
    total_paid_deposit: Decimal = Decimal("0")


class ContractListItem(BaseModel):
    """Phiên bản rút gọn cho danh sách — không kèm roommates."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_no: str
    property_id: uuid.UUID
    room_id: uuid.UUID
    room_number: str | None = None
    primary_tenant_id: uuid.UUID
    primary_tenant_name: str
    primary_tenant_phone: str
    start_date: date
    end_date: date
    monthly_price: Decimal
    deposit_amount: Decimal
    status: str
    days_remaining: int | None = None


class ContractStats(BaseModel):
    total: int
    by_status: dict[str, int] = Field(default_factory=dict)
    active: int
    expiring_30d: int
    monthly_revenue: Decimal = Decimal("0")
    deposits_held: Decimal = Decimal("0")


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_id: uuid.UUID
    amount: Decimal
    method: str
    receipt_no: str | None
    paid_at: datetime


__all__ = [
    "MAX_ROOMMATES",
    "MONEY",
    "ActivateRequest",
    "ContractCreate",
    "ContractListItem",
    "ContractResponse",
    "ContractStats",
    "ContractUpdate",
    "DepositCreate",
    "PaymentResponse",
    "RenewRequest",
    "RoommateCreate",
    "RoommateResponse",
    "RoommateSet",
    "TerminateRequest",
]
