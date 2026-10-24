"""Schema Pydantic của maintenance-service — phiếu sự cố & lịch bảo trì."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CategoryName = Literal[
    "PLUMBING", "ELECTRIC", "APPLIANCE", "FURNITURE",
    "STRUCTURE", "PEST", "GAS", "OTHER",
]
PriorityName = Literal["LOW", "NORMAL", "HIGH", "URGENT"]
StatusName = Literal["OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED", "CLOSED", "CANCELLED"]
ScopeName = Literal["BUILDING", "ROOM", "EQUIPMENT"]
FrequencyName = Literal["WEEKLY", "MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL"]


# ===========================================================================
#  PHIẾU SỰ CỐ
# ===========================================================================
class IncidentCreate(BaseModel):
    """
    Người thuê (hoặc quản lý) báo sự cố.

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "room_id": "f21a...-...",
            "category": "PLUMBING",
            "title": "Vòi nước phòng 302 hỏng, nước chảy liên tục",
            "description": "Từ tối qua nước chảy không ngắt, tôi phải tắm nước ở nhà tắm chung.",
            "priority": "HIGH",
            "photos": ["incidents/2026/10/xxx-01.jpg"],
            "reported_by_tenant_id": "3f2b...-...",
        }
    })
    """

    room_id: uuid.UUID | None = Field(
        default=None, description="NULL khi sự cố ở khu vực chung (thang, hành lang)",
    )
    category: CategoryName = "OTHER"
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority: PriorityName = "NORMAL"

    #: Object key trong MinIO, KHÔNG phải URL.
    photos: list[str] = Field(
        default_factory=list, max_length=10,
        description="Danh sách object key MinIO (lấy từ endpoint upload)",
    )

    #: Người thuê báo → trỏ tenant-service.
    reported_by_tenant_id: uuid.UUID | None = None
    #: Quản lý tự ghi → trỏ auth-service.
    reported_by_user_id: uuid.UUID | None = None
    reported_by_name: str | None = Field(
        default=None, max_length=100,
        description="Bắt buộc nếu không truyền id nào (ví dụ khách vãng lai gọi điện)",
    )
    reported_by_phone: str | None = Field(default=None, max_length=15)

    @field_validator("photos")
    @classmethod
    def _check_photo_keys(cls, v: list[str]) -> list[str]:
        """
        Chặn ngay giá trị trông như URL.

        ⭐ Object key và URL trông rất giống nhau, nhưng ý nghĩa khác hẳn:
           URL có thời hạn, vài giờ sau sẽ chết → ảnh trong phiếu sự cố biến
           mất trong lúc người dùng vẫn cần xem. Object key thì vĩnh viễn ổn.
           Bắt lỗi ở đây rẻ hơn nhiều lần phát hiện sau khi đã lưu.
        """
        for key in v:
            if "://" in key or key.startswith("/"):
                raise ValueError(
                    f"'{key}' trông như URL. Hãy gửi OBJECT KEY trong MinIO "
                    "(VD: incidents/2026/10/abc.jpg), không phải URL có thời hạn."
                )
        return v

    @model_validator(mode="after")
    def _one_reporter_source(self) -> IncidentCreate:
        # ⭐ KHÔNG bắt buộc client khai "ai báo": handler luôn gán người báo từ
        #    JWT (người thuê không được tự khai tenant_id). Bắt buộc ở đây thì
        #    validator chạy TRƯỚC handler và trả 422 cho chính người thuê đang
        #    đăng nhập — form báo sự cố hỏng hoàn toàn.
        if self.reported_by_tenant_id and self.reported_by_user_id:
            raise ValueError(
                "Chỉ chọn MỘT nguồn báo: người thuê (tenant) hoặc quản lý (user)"
            )
        return self


class IncidentUpdate(BaseModel):
    """
    Cập nhật phiếu. Tất cả trường đều tuỳ chọn — chỉ gửi cái cần đổi.

    ⭐ KHÔNG cho sửa `status` ở đây. Chuyển trạng thái là hành động có
       hệ quả nghiệp vụ (đóng phiếu = kết thúc việc dừng phòng, xong việc
       = phát event cho room-service) nên có endpoint riêng. Nếu gộp,
       1 lần PATCH vô tình đóng phiếu sự cố là thay đổi trạng thái phòng
       của cả cơ sở mà không ai hề biết.
    """

    category: CategoryName | None = None
    priority: PriorityName | None = None
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    photos: list[str] | None = None
    resolution: str | None = Field(default=None, max_length=5000)
    cost: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=2,
        description="Chi phí sửa chữa (VND)",
    )


class IncidentAssign(BaseModel):
    """Gán người xử lý."""

    user_id: uuid.UUID
    user_name: str | None = Field(
        default=None, max_length=100,
        description="Chụp lại tên — lịch sử không nên đổi theo tên tài khoản",
    )
    note: str | None = Field(default=None, max_length=1000)


class IncidentResolve(BaseModel):
    """
    Đánh dấu đã xử lý xong.

    ⭐ Service PHẢI kiểm tra chéo: nếu loại sự cố thuộc nhóm nguy hiểm
       (điện/gas/kết cấu) thì `verified_by` là BẮT BUỘC. Lý do: "thợ nói
       sửa xong" không đồng nghĩa "an toàn". Một đường dây điện thay mới
       nhưng không ai kiểm tra tải là nguy cơ cháy lần sau.
    """

    resolution: str = Field(min_length=3, max_length=5000)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    verified_by: uuid.UUID | None = Field(
        default=None, description="user_id người ký xác nhận an toàn",
    )
    verified_by_name: str | None = Field(default=None, max_length=100)


class IncidentClose(BaseModel):
    """
    Đóng phiếu. Khác `resolve` ở chỗ: `resolve` là thợ/kỹ thuật viên báo xong,
    `close` là quản lý (hoặc người thuê xác nhận) chốt lại.
    """

    resolution: str | None = Field(default=None, max_length=5000)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    close_reason: str | None = Field(default=None, max_length=1000)


class IncidentRating(BaseModel):
    """Người thuê đánh giá sau khi phiếu đã RESOLVED/CLOSED."""

    rating: int = Field(ge=1, le=5, description="1 = rất tệ, 5 = rất hài lòng")
    comment: str | None = Field(default=None, max_length=2000)


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_no: str
    property_id: uuid.UUID
    room_id: uuid.UUID | None
    room_number: str | None = Field(
        default=None, description="Tra từ room-service, không lưu bản sao",
    )
    reported_by_tenant_id: uuid.UUID | None
    reported_by_user_id: uuid.UUID | None
    reported_by_name: str
    reported_by_phone: str | None
    category: str
    priority: str
    title: str
    description: str | None
    photos: list[str] = Field(default_factory=list)
    status: str
    assigned_to: uuid.UUID | None
    assigned_to_name: str | None
    assigned_at: datetime | None
    started_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    resolution: str | None
    cost: Decimal | None
    rating: int | None
    rating_comment: str | None
    created_at: datetime
    updated_at: datetime | None = None

    # ---- Thuộc tính suy ra ----
    is_open: bool = True
    is_safety_critical: bool = False
    resolution_hours: float | None = Field(
        default=None, description="Số giờ từ lúc báo đến lúc xong (MTTR của phiếu này)",
    )


class IncidentListItem(BaseModel):
    """Bản rút gọn cho danh sách — bỏ `description` và `resolution` (dài)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_no: str
    room_number: str | None
    reported_by_name: str
    category: str
    priority: str
    title: str
    status: str
    assigned_to_name: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolution_hours: float | None = None
    is_open: bool = True


class IncidentStats(BaseModel):
    """Chỉ số bảo trì — report-service dùng để dựng dashboard."""

    property_id: uuid.UUID | None
    total: int
    open: int
    resolved: int
    cancelled: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    #: Số sự cố đang quá hạn (URGENT/HIGH chưa xử lý quá 24h).
    overdue: int = 0
    #: Trung bình số giờ để sửa xong. `None` khi chưa có sự cố nào xong.
    avg_resolution_hours: float | None = None
    #: Chi phí sửa tổng cộng trong kỳ (VND).
    total_cost: Decimal = Decimal("0")
    #: Điểm hài lòng trung bình (null khi chưa có ai đánh giá).
    avg_rating: float | None = None
    as_of: datetime


# ===========================================================================
#  LỊCH BẢO TRÌ ĐỊNH KỲ
# ===========================================================================
class ScheduleTask(BaseModel):
    """1 việc trong danh sách bảo trì định kỳ."""

    task: str = Field(min_length=1, max_length=200)
    required: bool = Field(
        default=True, description="False = việc tuỳ chọn, không bắt buộc phải làm",
    )


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "property_id": "6b1f...-...",
            "scope": "BUILDING",
            "title": "Vệ sinh & kiểm tra an toàn hằng tháng",
            "task_template": [
                {"task": "Kiểm tra hệ thống điện dùng chung", "required": True},
                {"task": "Vệ sinh thang, hành lang", "required": True},
                {"task": "Kiểm tra bóng đèn hành lang", "required": False},
            ],
            "frequency": "MONTHLY",
            "next_due_date": "2026-10-31",
            "notify_tenants": False,
        }
    })

    property_id: uuid.UUID
    scope: ScopeName = "BUILDING"
    target_id: uuid.UUID | None = Field(
        default=None, description="Bắt buộc khi scope=ROOM hoặc EQUIPMENT",
    )
    title: str = Field(min_length=3, max_length=200)
    task_template: Annotated[list[ScheduleTask], Field(min_length=1, max_length=50)]
    frequency: FrequencyName = "MONTHLY"
    next_due_date: date
    #: "Ngày mục tiêu" trong tháng để neo các kỳ sau (1–31). Mặc định lấy từ
    #: `next_due_date`; chỉ cần đặt tay khi muốn lịch quay về đúng ngày cố
    #: định sau khi đã trượt qua tháng ngắn.
    anchor_day: int | None = Field(default=None, ge=1, le=31)
    notify_tenants: bool = False
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check_target(self) -> ScheduleCreate:
        # Bắt lỗi ở đây thay vì để lịch bảo trì "mồ côi" không gắn với
        # phòng nào — loại lỗi dữ liệu mà rất khó phát hiện bằng mắt.
        if self.scope == "BUILDING":
            if self.target_id is not None:
                raise ValueError("scope=BUILDING thì không cần target_id")
        elif self.target_id is None:
            raise ValueError(f"scope={self.scope} thì BẮT BUỘC phải có target_id")
        return self


class ScheduleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    task_template: Annotated[list[ScheduleTask], Field(min_length=1, max_length=50)] | None = None
    frequency: FrequencyName | None = None
    next_due_date: date | None = None
    anchor_day: int | None = Field(default=None, ge=1, le=31)
    notify_tenants: bool | None = None
    note: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class ScheduleComplete(BaseModel):
    """
    Đánh dấu đã thực hiện xong lần này.

    Hệ thống tự tính `next_due_date` tiếp theo. Cho phép ghi đè để xử lý
    trường hợp "lần này bỏ qua, sang tháng sau làm gấp".
    """

    performed_on: date | None = Field(
        default=None, description="Mặc định hôm nay",
    )
    note: str | None = Field(default=None, max_length=2000)
    next_due_date: date | None = Field(
        default=None, description="Ghi đè hạn tiếp theo thay vì tự tính",
    )
    performed_tasks: list[str] = Field(
        default_factory=list, max_length=50, description="Các việc đã làm",
    )


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    scope: str
    target_id: uuid.UUID | None
    room_number: str | None = None
    title: str
    task_template: list[dict]
    frequency: str
    next_due_date: date
    anchor_day: int = 1
    last_done_at: datetime | None
    times_completed: int
    notify_tenants: bool
    note: str | None
    is_active: bool
    created_at: datetime

    is_due: bool = False
    days_until_due: int = 0


__all__ = [
    "CategoryName",
    "FrequencyName",
    "IncidentAssign",
    "IncidentClose",
    "IncidentCreate",
    "IncidentListItem",
    "IncidentRating",
    "IncidentResolve",
    "IncidentResponse",
    "IncidentStats",
    "IncidentUpdate",
    "PriorityName",
    "ScheduleComplete",
    "ScheduleCreate",
    "ScheduleResponse",
    "ScheduleTask",
    "ScheduleUpdate",
    "ScopeName",
    "StatusName",
]
