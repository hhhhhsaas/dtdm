"""Schema Pydantic của room-service — hợp đồng API cho danh mục phòng."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Tiền: Decimal với regex để chặn số âm và quá nhiều chữ số thập phân.
# Field(gt=0) trong Pydantic vẫn cho phép "1.5e3" (ký hiệu khoa học) — thứ
# mà người dùng gõ tay không bao giờ có ý định. Regex chặn cứng hơn.
MONEY = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=0)]
ROOM_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9\-/]{1,20}$")


# ===========================================================================
#  PROPERTY
# ===========================================================================
class PropertyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    address: str = Field(min_length=5)
    owner_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=15)
    tax_code: str | None = Field(default=None, max_length=20)
    description: str | None = None

    @field_validator("name", "owner_name")
    @classmethod
    def _squash(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v else v


class PropertyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    address: str | None = None
    owner_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=15)
    tax_code: str | None = Field(default=None, max_length=20)
    description: str | None = None
    is_active: bool | None = None


class PropertyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    owner_name: str | None
    phone: str | None
    tax_code: str | None
    total_rooms: int
    description: str | None
    is_active: bool
    created_at: datetime


# ===========================================================================
#  BUILDING
# ===========================================================================
class BuildingCreate(BaseModel):
    property_id: uuid.UUID
    name: str = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=255)


class BuildingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    name: str
    note: str | None
    # Số phòng — chỉ có sau khi đã truy vấn bổ sung (không lưu cột riêng,
    # vì sẽ phải cập nhật mỗi lần thêm/xoá phòng → dễ lệch)
    room_count: int = 0


# ===========================================================================
#  AMENITY
# ===========================================================================
class AmenityCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)
    default_monthly_fee: MONEY = Decimal("0")
    description: str | None = None


class AmenityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    icon: str | None
    default_monthly_fee: Decimal
    description: str | None
    is_active: bool


class RoomAmenitySet(BaseModel):
    """Gán tiện ích cho phòng (PUT = thay toàn bộ)."""

    amenity_ids: list[uuid.UUID] = Field(max_length=50)


# ===========================================================================
#  ROOM
# ===========================================================================
class RoomCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "property_id": "6b1f...-...", "building_id": "0c4e...-...",
            "room_number": "101", "floor": 1, "area_m2": "22.50",
            "base_price": "2500000", "max_occupants": 3,
            "amenity_ids": [],
        }
    })

    property_id: uuid.UUID
    building_id: uuid.UUID
    room_number: str = Field(min_length=1, max_length=20)
    floor: int = Field(default=1, ge=-5, le=100)
    area_m2: Decimal | None = Field(default=None, ge=1, le=1000, decimal_places=2)
    base_price: MONEY
    max_occupants: int = Field(default=1, ge=1, le=10)
    note: str | None = None
    photos: list[str] = Field(default_factory=list, max_length=10)
    amenity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    @field_validator("room_number")
    @classmethod
    def _valid_number(cls, v: str) -> str:
        v = v.strip().upper()
        if not ROOM_NUMBER_PATTERN.match(v):
            raise ValueError(
                "Số phòng chỉ được chứa chữ, số, dấu gạch ngang và dấu gạch chéo "
                "(ví dụ: 101, 201A, B-12)"
            )
        return v


class RoomUpdate(BaseModel):
    """Cập nhật phòng. KHÔNG cho sửa `status` — endpoint riêng có kiểm soát."""

    room_number: str | None = Field(default=None, min_length=1, max_length=20)
    floor: int | None = Field(default=None, ge=-5, le=100)
    area_m2: Decimal | None = Field(default=None, ge=1, le=1000, decimal_places=2)
    base_price: MONEY | None = None
    max_occupants: int | None = Field(default=None, ge=1, le=10)
    note: str | None = None
    photos: list[str] | None = Field(default=None, max_length=10)
    is_active: bool | None = None


class RoomStatusChange(BaseModel):
    """
    Đổi trạng thái phòng thủ công.

    ⚠️  Không cho đổi sang `OCCUPIED` từ đây — trạng thái đó chỉ hợp lệ khi
        có hợp đồng ACTIVE. Nếu cho phép, sẽ tồn tại phòng "đang có người thuê"
        nhưng không có hợp đồng → billing không tính tiền, doanh thu thất lạc
        mà không ai biết. Endpoint này chỉ dành cho MAINTENANCE / RESERVED.
    """

    model_config = ConfigDict(json_schema_extra={
        "example": {"status": "MAINTENANCE", "reason": "Hết vệ sinh, cần sơn tường"}
    })

    status: Literal["AVAILABLE", "MAINTENANCE", "RESERVED"]
    reason: str | None = Field(default=None, max_length=255)


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    building_id: uuid.UUID
    room_number: str
    floor: int
    area_m2: Decimal | None
    base_price: Decimal
    max_occupants: int
    status: str
    current_contract_id: uuid.UUID | None
    note: str | None
    photos: list | None
    created_at: datetime

    # Trường bổ sung do service gắn vào (không có trong bảng)
    building_name: str | None = None
    amenities: list[AmenityResponse] = Field(default_factory=list)


class RoomAvailableItem(RoomResponse):
    """
    Phòng trống kèm GIÁ ƯỚC TÍNH đã gồm điện nước.

    ⭐ `estimated_total` lấy từ cache Redis do billing-service đẩy vào
       (qua event `price_tiers.updated`), KHÔNG gọi đồng bộ sang billing.
       Lý do: trang tìm phòng là trang được gọi NHIỀU nhất và phải nhanh;
       gọi chuỗi 3 service (room → billing → price lookup) sẽ phá vỡ SLA
       p95 < 300ms. Ước tính sai một chút cũng chấp nhận được — người thuê
       xem giá thật khi nhận hóa đơn.
    """

    estimated_electric: Decimal = Decimal("0")
    estimated_water: Decimal = Decimal("0")
    estimated_services: Decimal = Decimal("0")
    estimated_total: Decimal = Decimal("0")
    price_is_estimate: bool = True


class RoomStats(BaseModel):
    """
    Thống kê công suất. Đây là metric nghiệp vụ quan trọng nhất của chủ nhà
    ("nhà trọ của tôi còn bao nhiêu phòng trống?") nên được cache sẵn.
    """

    property_id: uuid.UUID | None
    total: int
    available: int
    occupied: int
    maintenance: int
    reserved: int
    occupancy_rate: float = Field(description="Tỷ lệ lấp đầy 0–100 (%)")
    total_monthly_revenue: Decimal = Field(default=Decimal("0"),
                                          description="Tiền phòng/tháng nếu kín phòng")
    average_price: Decimal = Decimal("0")
    by_floor: dict[str, int] = Field(default_factory=dict)
    as_of: datetime


# ===========================================================================
#  TRÌNH DUYỆT
# ===========================================================================
class RoomSearchRequest(BaseModel):
    """Tìm phòng theo tiêu chí — POST vì có nhiều tham số lọc phức tạp."""

    property_id: uuid.UUID | None = None
    building_id: uuid.UUID | None = None
    min_price: MONEY | None = None
    max_price: MONEY | None = None
    min_area: Decimal | None = Field(default=None, ge=0)
    min_max_occupants: int | None = Field(default=None, ge=1, le=10)
    amenities: list[str] = Field(default_factory=list, max_length=20)
    available_from: date | None = None
    search: str | None = Field(default=None, max_length=100)
    sort: Literal["price_asc", "price_desc", "area_asc", "area_desc"] = "price_asc"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


__all__ = [
    "MONEY",
    "AmenityCreate",
    "AmenityResponse",
    "BuildingCreate",
    "BuildingResponse",
    "PropertyCreate",
    "PropertyResponse",
    "PropertyUpdate",
    "RoomAmenitySet",
    "RoomAvailableItem",
    "RoomCreate",
    "RoomResponse",
    "RoomSearchRequest",
    "RoomStats",
    "RoomStatusChange",
    "RoomUpdate",
]
