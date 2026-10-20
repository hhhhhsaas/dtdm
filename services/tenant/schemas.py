"""Schema Pydantic của tenant-service — hồ sơ người thuê."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# CCCD Việt Nam: 12 chữ số (căn cước) hoặc 9 chữ số (CMND cũ).
# Dùng `\d` thay vì `[0-9]` để tránh khớp ký tự Unicode (ví dụ chữ số
# Ả Rập "٣") — regex Unicode `\d` mặc định khớp chữ số ASCII trong Python
# với `re.ASCII` không bật, nên dùng `[0-9]` rõ ràng hơn.
ID_CARD_PATTERN = re.compile(r"^(?:[0-9]{9}|[0-9]{12})$")
PHONE_PATTERN = re.compile(r"^(?:0|\+84)[0-9]{8,10}$")

IdCard = Annotated[str, Field(pattern=ID_CARD_PATTERN)]
Phone = Annotated[str, Field(pattern=PHONE_PATTERN)]


# ===========================================================================
#  TENANT
# ===========================================================================
class TenantCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "property_id": "6b1f...-...",
            "full_name": "Nguyễn Văn A",
            "phone": "0901234567",
            "id_card_number": "001203012345",
            "date_of_birth": "1998-03-15",
            "gender": "M",
            "email": "nguyenvana@example.com",
            "occupation": "Kỹ sư phần mềm",
            "emergency_contact_name": "Nguyễn Thị B",
            "emergency_contact_phone": "0912345678",
        }
    })

    property_id: uuid.UUID
    full_name: str = Field(min_length=2, max_length=100)
    phone: Phone
    id_card_number: IdCard | None = Field(
        default=None,
        description="CCCD 12 số (hoặc CMND 9 số). Được mã hóa AES-256-GCM khi lưu.",
    )
    date_of_birth: date | None = None
    gender: Literal["M", "F", "OTHER"] | None = None
    email: EmailStr | None = None
    address: str | None = None
    occupation: str | None = Field(default=None, max_length=100)
    emergency_contact_name: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = None
    zalo_oa_id: str | None = Field(default=None, max_length=50)
    note: str | None = None

    @field_validator("full_name", "emergency_contact_name")
    @classmethod
    def _clean_name(cls, v: str | None) -> str | None:
        # Gộp khoảng trắng: "Nguyễn   Văn  A" → "Nguyễn Văn A".
        # Không làm thế này thì tìm kiếm theo tên sẽ ra 2 kết quả.
        return " ".join(v.split()) if v else v

    @field_validator("date_of_birth")
    @classmethod
    def _check_age(cls, v: date | None) -> date | None:
        if v is None:
            return None
        today = date.today()
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if age < 16:
            raise ValueError("Người thuê phải đủ 16 tuổi (Nghị định 100/2019)")
        if age > 100:
            raise ValueError("Ngày sinh không hợp lý")
        return v


class TenantUpdate(BaseModel):
    """Cập nhật hồ sơ. Mọi thay đổi đều được ghi vào `tenant_history`."""

    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    phone: Phone | None = None
    email: EmailStr | None = None
    address: str | None = None
    occupation: str | None = Field(default=None, max_length=100)
    emergency_contact_name: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = None
    zalo_oa_id: str | None = Field(default=None, max_length=50)
    note: str | None = None
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    risk_note: str | None = None
    is_active: bool | None = None


class TenantIdCardUpdate(BaseModel):
    """
    Cập nhật CCCD — TÁCH RIÊNG khỏi `TenantUpdate`.

    ⭐ Lý do: đổi CCCD là hành động nhạy cảm, cần:
       - xác thực lại (đổi CCCD có thể để lách quy định hạn chế)
       - ghi audit log riêng
       - chặn trùng với người khác
    Gom vào endpoint chung thì rất dễ bị bỏ sót các bước này.
    """

    id_card_number: IdCard
    reason: str = Field(min_length=3, max_length=255,
                        description="Lý do đổi CCCD (bắt buộc, ghi vào nhật ký)")


class TenantResponse(BaseModel):
    """
    ⭐ THÔNG TIN NGƯỜI THUÊ — KHÔNG BAO GIỜ chứa CCCD đầy đủ.

    Chỉ có `id_card_masked` (4 số cuối). Muốn xem đầy đủ phải gọi
    `GET /tenants/{id}/id-card`, endpoint kiểm tra quyền và ghi audit log.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    full_name: str
    date_of_birth: date | None
    gender: str | None
    phone: str
    email: str | None
    address: str | None
    occupation: str | None
    id_card_masked: str | None = None
    id_card_last4: str | None = None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    zalo_oa_id: str | None
    is_active: bool
    risk_level: str
    risk_note: str | None
    current_room_id: uuid.UUID | None
    current_contract_id: uuid.UUID | None
    created_at: datetime
    note: str | None = None


class TenantSensitiveResponse(BaseModel):
    """Trả về CCCD ĐẦY ĐỦ — chỉ dùng cho endpoint đã kiểm tra quyền."""

    tenant_id: uuid.UUID
    full_name: str
    id_card_number: str
    id_card_front: str | None = None
    id_card_back: str | None = None
    note: str = "Truy cập dữ liệu nhạy cảm — đã ghi nhật ký"


class TenantSummary(BaseModel):
    """Tóm tắt dùng trong dropdown chọn người thuê (bỏ qua thông tin phụ)."""

    id: uuid.UUID
    full_name: str
    phone: str
    current_room_id: uuid.UUID | None = None


# ===========================================================================
#  BẠN CÙNG PHÒNG
# ===========================================================================
class RoommateCreate(BaseModel):
    room_id: uuid.UUID
    full_name: str = Field(min_length=2, max_length=100)
    phone: Phone
    tenant_id: uuid.UUID | None = Field(
        default=None, description="Nếu người này đã có hồ sơ trong hệ thống",
    )
    is_primary: bool = Field(
        default=False, description="True = người đứng tên chính (chủ hợp đồng)",
    )


class RoommateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    room_id: uuid.UUID
    tenant_id: uuid.UUID | None
    full_name: str
    phone: str
    is_primary: bool
    created_at: datetime


# ===========================================================================
#  LỊCH SỬ
# ===========================================================================
class HistoryCreate(BaseModel):
    """Bổ sung ghi chú vào lịch sử (append-only, không sửa được)."""

    event_type: Literal[
        "NOTE_ADDED", "PROFILE_UPDATED", "RISK_CHANGED", "MOVED_OUT", "OTHER"
    ] = "NOTE_ADDED"
    note: str = Field(min_length=1, max_length=1000)
    event_data: dict | None = None


class HistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: uuid.UUID
    property_id: uuid.UUID | None
    room_id: uuid.UUID | None
    event_type: str
    event_data: dict | None
    actor_id: uuid.UUID | None
    note: str | None
    created_at: datetime


# ===========================================================================
#  THỐNG KÊ
# ===========================================================================
class TenantStats(BaseModel):
    """Chỉ số về người thuê — report-service dùng để dựng dashboard."""

    property_id: uuid.UUID | None
    total: int
    active: int
    inactive: int
    by_risk: dict[str, int] = Field(default_factory=dict)
    avg_tenure_months: float = Field(
        default=0.0, description="Thời gian ở trung bình (tháng)",
    )
    without_id_card: int = Field(
        default=0, description="Số hồ sơ chưa cung cấp CCCD",
    )
    as_of: datetime


class TransferRequest(BaseModel):
    """
    Chuyển người thuê sang cơ sở khác (VD: hết hợp đồng, sang nhà trọ mới).

    ⭐ Vì sao có endpoint này mà không xoá hồ sơ cũ?
       Lịch sử thuê của 1 người là dữ liệu đáng giá: chủ nhà dùng nó để
       biết ai đã ở và ra vì lý do gì. Xoá hồ sơ mỗi lần chuyển nhà thì
       sau 2 năm không còn gì để tham khảo.
    """

    new_property_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=255)


__all__ = [
    "HistoryCreate",
    "HistoryResponse",
    "IdCard",
    "Phone",
    "RoommateCreate",
    "RoommateResponse",
    "TenantCreate",
    "TenantIdCardUpdate",
    "TenantResponse",
    "TenantSensitiveResponse",
    "TenantStats",
    "TenantSummary",
    "TenantUpdate",
    "TransferRequest",
]
