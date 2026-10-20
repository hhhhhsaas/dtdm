"""Schema Pydantic của notification-service — template, thông báo, gửi thử."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChannelName = Literal["IN_APP", "EMAIL", "SMS", "ZALO"]
StatusName = Literal["QUEUED", "SENT", "DELIVERED", "FAILED", "READ"]


# ===========================================================================
#  TEMPLATE
# ===========================================================================
class TemplateUpsert(BaseModel):
    """Tạo hoặc sửa khuôn mẫu thông báo."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "channel": "EMAIL",
            "name": "Nhắc trả hóa đơn",
            "subject": "Hóa đơn {{ invoice_no }} — trả trước {{ due_date }}",
            "body": "Xin chào {{ tenant_name }},\n\n"
                    "Hóa đơn {{ invoice_no }} kỳ {{ period }} "
                    "trị giá {{ total }} đã phát hành...\n",
        }
    })

    channel: ChannelName
    name: str = Field(min_length=1, max_length=150)
    subject: str | None = Field(default=None, max_length=255)
    body: str = Field(min_length=1, max_length=20000)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    channel: str
    name: str
    subject: str | None
    body: str
    description: str | None
    is_active: bool
    locale: str
    updated_at: datetime | None = None


class TemplatePreviewRequest(BaseModel):
    """
    Xem trước thông báo với dữ liệu giả.

    ⭐ Rất quan trọng khi sửa template: nếu sửa xong mới phát hiện biến
    `{{ ten_khong_co }}` bị sai, thì người thuê đã nhận 200 email lỗi rồi.
    Render thử với dữ liệu mẫu là cách rẻ nhất để tránh điều đó.
    """

    context: dict = Field(
        default_factory=dict,
        description="Dữ liệu giả để render (VD {'tenant_name': 'Nguyễn Văn A'})",
    )


class TemplatePreviewResponse(BaseModel):
    subject: str | None = None
    body: str
    #: Các tên biến dùng trong template — để đối chiếu với `context`.
    used_variables: list[str] = Field(default_factory=list)


# ===========================================================================
#  NOTIFICATION
# ===========================================================================
class NotificationSendRequest(BaseModel):
    """
    Gửi thông báo thủ công (quản lý bấm tay).

    Dùng cho các trường hợp hệ thống KHÔNG tự sinh thông báo: nhắc tiền riêng,
    thông báo đổi giá, gửi tin nhắn chào mừng...
    """

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "template_code": "MANUAL_NOTICE",
            "channel": "EMAIL",
            "recipient": "an.nguyen@example.com",
            "recipient_name": "Nguyễn Văn An",
            "tenant_id": "3f2b...-...",
            "context": {"title": "Báo thay đổi giá điện", "detail": "Từ 01/11"},
        }
    })

    template_code: str = Field(min_length=2, max_length=50)
    channel: ChannelName = "IN_APP"
    recipient: str = Field(
        min_length=3, max_length=150,
        description="Email, số điện thoại (dạng 09xxxxxxxx) hoặc user_id Zalo",
    )
    recipient_name: str | None = Field(default=None, max_length=150)
    tenant_id: uuid.UUID | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "NORMAL"
    context: dict = Field(default_factory=dict)
    #: Bỏ qua khoá idempotency (gửi lại cùng 1 nội dung có chủ đích).
    force: bool = Field(
        default=False, description="Bỏ qua dedupe_key — dùng khi cần gửi lại"
    )

    @field_validator("recipient")
    @classmethod
    def _check_recipient(cls, v: str) -> str:
        """
        Kiểm tra định dạng người nhận theo đúng kênh đã chọn.

        ⭐ Bắt lỗi sớm ở đây thay vì để tới lúc gửi: 1 email sai định dạng
        tốn 1 lần gọi API của nhà cung cấp (có thể mất tiền) và trả về lỗi
        khó hiểu cho người quản lý.
        """
        v = v.strip()
        if "@" not in v and not v.replace(" ", "").isdigit():
            raise ValueError(
                "Người nhận phải là email (có @) hoặc số điện thoại chỉ gồm chữ số"
            )
        return v


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID | None
    tenant_id: uuid.UUID | None
    channel: str
    template_code: str
    priority: str
    recipient: str
    recipient_name: str | None
    subject: str | None
    body: str | None
    status: str
    attempts: int
    error: str | None
    queued_at: datetime
    sent_at: datetime | None
    read_at: datetime | None
    context: dict = Field(default_factory=dict)


class NotificationListItem(BaseModel):
    """Bản rút gọn cho danh sách — không kèm `body` (thường dài)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: str
    template_code: str
    priority: str
    recipient_name: str | None
    subject: str | None
    status: str
    queued_at: datetime
    sent_at: datetime | None
    read_at: datetime | None
    is_read: bool = False


class NotificationStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_channel: dict[str, int]
    unread: int
    #: Tỉ lệ gửi thành công (%). Chỉ tính trên các bản ghi đã thử gửi.
    success_rate: float = 0.0
    #: Số thông báo hỏng cần người quản lý xử lý tay.
    failed: int = 0


class BulkSendRequest(BaseModel):
    """Gửi 1 thông báo cho nhiều người (VD thông báo tăng giá toàn cơ sở)."""

    template_code: str = Field(min_length=2, max_length=50)
    channel: ChannelName = "IN_APP"
    #: Danh sách người nhận.
    recipients: Annotated[list[NotificationSendRequest], Field(min_length=1, max_length=500)]
    context: dict = Field(default_factory=dict)


class BulkSendResponse(BaseModel):
    total: int
    queued: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
