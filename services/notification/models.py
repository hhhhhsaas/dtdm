"""
notification-service — Mô hình dữ liệu.  Cổng 8006  |  db_notify

================================================================================
PHẠM VI SỞ HỮU DỮ LIỆU
================================================================================
Chỉ 2 bảng: `templates` (khuôn mẫu) và `notifications` (lịch sử gửi).

⭐ VÌ SAO DB NÀY CỐ TÌNH "CHỈ CÓ 2 BẢNG" VÀ KHÔNG CÓ DỮ LIỆU NGHIỆP VỤ?
   Một service mới làm thường bị kéo theo "cho tôi xin bảng hóa đơn để render
   email", "cho tôi bảng hợp đồng để biết hết hạn". Từ đó db_notify thành bản
   sao của db_billing/db_contract, và mọi bug sẽ xuất hiện ở 2 nơi.

   Nguyên tắc thay thế: notification KHÔNG BIẾT HÓA ĐƠN LÀ GÌ. Nó chỉ nhận
   `context: dict` đã render sẵn từ event, ví dụ:
       {"invoice_no": "HD-202610-0001", "total": "3.150.000đ", ...}
   Nhờ vậy:
     - Đổi cấu trúc hóa đơn không phải sửa notification.
     - Test được template mà không cần dựng cả database hóa đơn.
     - db_notify có thể xoá và dựng lại bất cứ lúc nào mà không mất gì
       (ngoại trừ lịch sử gửi, vốn chỉ để tra cứu).

================================================================================
IDEMPOTENCY — `dedupe_key`
================================================================================
RabbitMQ bảo đảm at-least-once: cùng một event `invoice.issued` có thể tới 2
lần. Nếu mỗi lần đều gửi email thì người thuê nhận 2 hóa đơn và mất niềm tin
vào hệ thống.

`dedupe_key` là UNIQUE và được tính theo CÔNG THỨC NGHIỆP VỤ, không phải theo
`event_id` (vì `IdempotentConsumer` đã chặn trùng theo `event_id` rồi):

    INVOICE_ISSUED:2026-10-0001
    CONTRACT_EXPIRING:HD-2026-0001:30
    INCIDENT_CREATED:SC-0042

Cách tính này chặn được cả trường hợp khó hơn: scheduler chạy lại và phát lại
cùng một thông báo "hợp đồng sắp hết hạn còn 30 ngày" — `event_id` khác nhau
nhưng `dedupe_key` giống nhau → vẫn chỉ gửi 1 lần. Đây mới là idempotency đúng
nghĩa: "người thuê chỉ cần biết 1 lần".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


# ---------------------------------------------------------------------------
#  Enum
# ---------------------------------------------------------------------------
class Channel(str, Enum):
    """Kênh gửi. Thêm kênh mới = thêm 1 lớp trong `channels.py`, không sửa service."""

    IN_APP = "IN_APP"    # lưu vào db_notify, hiện trên web — luôn bật, miễn phí
    EMAIL = "EMAIL"      # SMTP
    SMS = "SMS"          # cổng SMS (FPT/Viettel) hoặc Zalo ZNS
    ZALO = "ZALO"        # Zalo OA


class NotificationStatus(str, Enum):
    """
    Vòng đời thông báo:

        QUEUED ──gửi thành công──> SENT ──đọc trên web──> READ
           │                         │
           └──thất bại hết lần───> FAILED

    ⭐ `DELIVERED` dành cho kênh có xác nhận (email có thể trả về
       "delivered" từ nhà cung cấp). Kênh `IN_APP` nhảy thẳng QUEUED → SENT vì
       việc ghi vào DB chính là lúc người dùng nhận được.
    """

    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    READ = "READ"

    @property
    def is_terminal(self) -> bool:
        """Không thay đổi được nữa (trừ việc thử gửi lại khi FAILED)."""
        return self in (NotificationStatus.SENT,
                        NotificationStatus.DELIVERED,
                        NotificationStatus.READ)

    @property
    def is_failed(self) -> bool:
        return self is NotificationStatus.FAILED


class Priority(str, Enum):
    """Mức ưu tiên khi có nhiều thông báo chờ trong hàng đợi."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"        # hóa đơn quá hạn, hợp đồng sắp hết hạn
    CRITICAL = "CRITICAL"  # rò rỉ nước, cháy, mất điện — cần gửi ngay


#: Số thứ tự ưu tiên — cao hơn = gửi trước.
PRIORITY_RANK: dict[str, int] = {
    Priority.CRITICAL.value: 0,
    Priority.HIGH.value: 1,
    Priority.NORMAL.value: 2,
    Priority.LOW.value: 3,
}


# ---------------------------------------------------------------------------
#  Khuôn mẫu thông báo
# ---------------------------------------------------------------------------
class Template(Base):
    """
    Khuôn mẫu nội dung thông báo, viết bằng Jinja2.

    ⭐ Vì sao lưu template vào DB thay vì hard-code trong Python?
       1. Chủ trọ sửa câu chữ ("quý khách" → "bạn") KHÔNG CẦN deploy lại.
       2. So sánh A/B: giữ 2 template cùng `code`, khác `version`.
       3. Một bản dịch khác cho cùng nội dung.
       Cái giá phải trả: phải xử lý lỗi template lúc runtime — xem
       `render_template` trong `channels.py`.
    """

    __tablename__ = "templates"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255))
    #: Nội dung Jinja2. `{{ biến }}` được thay bằng dữ liệu từ `context`.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Ngôn ngữ — để sẵn sàng cho đa ngôn ngữ mà không cần đổi cấu trúc bảng.
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="vi")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
#  Lịch sử gửi
# ---------------------------------------------------------------------------
class Notification(Base):
    """
    Một lần gửi thông báo cho một người nhận.

    ⭐ `context` lưu JSON nguyên trạng đã dùng để render. Nếu không lưu:
        - Sau 6 tháng không ai nhớ nội dung email tháng trước gửi gì.
        - Không thể tái tạo lại lỗi render.
        - Không thể gửi lại cho người khác ("anh gửi bạn cái này").
        Chi phí: vài trăm byte mỗi thông báo — không đáng để đánh đổi.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # Truy vấn nóng: hộp thư của 1 người, mới nhất trước
        Index("ix_notification_inbox", "tenant_id", "created_at"),
        # Hàng đợi gửi: lấy QUEUED sắp gửi, ưu tiên cao trước
        Index("ix_notification_queue", "status", "priority", "created_at"),
        CheckConstraint("attempts >= 0", name="chk_notification_attempts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    #: Người nhận. `NULL` khi thông báo gửi cho quản lý (không có hồ sơ người thuê).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    template_code: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(10), nullable=False, default=Priority.NORMAL.value
    )

    recipient: Mapped[str] = mapped_column(String(150), nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(150))
    subject: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(15), nullable=False, default=NotificationStatus.QUEUED.value
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    #: Mã lỗi của nhà cung cấp (vd Zalo trả `error_code`) — giúp tra khi
    #: khách nói "tôi không nhận được" mà log chỉ có "gửi lỗi".
    provider_message: Mapped[str | None] = mapped_column(String(255))

    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Dữ liệu đã dùng để render — xem giải thích ở docstring class.
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    #: ⭐ Khoá idempotency. Xem "IDEMPOTENCY" ở docstring đầu file.
    dedupe_key: Mapped[str | None] = mapped_column(String(255), unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    @property
    def can_retry(self) -> bool:
        """Có nên thử gửi lại không?"""
        return self.status == NotificationStatus.FAILED.value and self.attempts < 5
