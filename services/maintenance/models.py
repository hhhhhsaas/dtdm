"""
maintenance-service — Sự cố & bảo trì.        Cổng 8007  |  db_maintenance

================================================================================
VÌ SAO SERVICE NÀY TÁCH RIÊNG, KHÔNG GỘP VÀO ROOM-SERVICE?
================================================================================
Vòng đời sự cố KHÁC HẲN vòng đời phòng:
  - Phòng tồn tại nhiều năm, sự cố thì có rồi hết trong vài giờ
  - Sự cố có người báo, người xử lý, chi phí, đánh giá → cần lịch sử riêng
  - Nhịp phát triển khác nhau: room thay đổi khi có tính năng mới (ví dụ thêm
    quản lý tiện ích), maintenance thay đổi khi có quy trình vận hành mới

Gộp chung → deploy phòng phải deploy cả quy trình sự cố, và sự cố (nghẽn,
viêm) làm chậm cả API đọc phòng. Đó là lý do kinh điển của việc tách service.

================================================================================
RỦI RO NGHIỆP VỤ LỚN NHẤT: SỰ CỐ NGHIÊM TRỌNG KHÔNG ĐƯỢC PHÁ HỢP ĐỒNG
================================================================================
`room-service` xử lý `incident.urgent` bằng cách chuyển phòng sang
MAINTENANCE — nhưng TUYỆT ĐỐI KHÔNG kết thúc hợp đồng. Người thuê đã trả
tiền tháng này, việc phòng hỏng là lỗi của chủ trọ. Nếu ta chấm dứt hợp
đồng thì họ mất chỗ ở giữa tháng và không có nhà nào khác nhận giữa kỳ.

Service này vì thế KHÔNG gọi trực tiếp sang contract-service. Nó chỉ phát
event; quyết định "hậu quả nghiệp vụ" thuộc về service sở hữu hợp đồng.

================================================================================
VÌ SAO ẢNH LƯU TRÊN MINIO, KHÔNG LƯU TRONG DB?
================================================================================
`photos` chỉ chứa OBJECT KEY (`incidents/2026/10/SC-0001-01.jpg`), không
chứa ảnh. Ba lý do:
  1. Ảnh nặng vài MB — để trong PostgreSQL sẽ phình backup và WAL
  2. Truyền ảnh qua API JSON base64 tốn ~33% và chậm
  3. Sau này đổi sang S3/GCS chỉ cần sửa cái lấy URL, không phải migrate dữ liệu

Điểm mấu chốt: **không bao giờ lưu presigned URL** trong DB. URL có thời hạn,
lưu vào DB thì vài giờ sau nó chết và ảnh trong hồ sơ sự cố "biến mất".
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from common.database import Base


class IncidentCategory(str, Enum):
    """
    Loại sự cố — quyết định ai xử lý và có cần thợ ngoài không.

    ⭐ `ELECTRICAL` và `GAS` là 2 loại NGUY HIỂM: không phải sửa xong là
       dùng được, phải kiểm tra an toàn. Chúng được phân biệt riêng để
       (a) đội bảo trì nội bộ không tự ý xử lý, (b) bắt buộc có người ký
       xác nhận trước khi đóng phiếu.
    """

    PLUMBING = "PLUMBING"          # ống nước, vòi, bồn cầu, tắc
    ELECTRIC = "ELECTRIC"          # điện: dây cháy, ổ cắm, chập cháy
    APPLIANCE = "APPLIANCE"        # thiết bị trong phòng: bóng, quạt, bình nóng lạnh
    FURNITURE = "FURNITURE"        # giường, tủ, bàn ghế
    STRUCTURE = "STRUCTURE"        # kết cấu: tường, trần, sàn, mái
    PEST = "PEST"                  # mối, chuột, gián
    GAS = "GAS"                    # rò gas, bếp gas
    OTHER = "OTHER"


#: Loại sự cố cần người ký xác nhận an toàn trước khi đóng phiếu.
SAFETY_CRITICAL_CATEGORIES: frozenset[str] = frozenset({
    IncidentCategory.ELECTRIC.value,
    IncidentCategory.GAS.value,
    IncidentCategory.STRUCTURE.value,
})


class IncidentPriority(str, Enum):
    """
    Mức độ khẩn cấp.

    ⭐ CHỈ `URGENT` mới được phép tạm dừng khai thác phòng.
       Đây là ranh giới nghiệp vụ quan trọng: nếu cho phép `HIGH` cũng dừng
       phòng, chủ trọ sẽ mất doanh thu mỗi lần có sự cố nhỏ (bóng đèn cháy).
       Mỗi phút phòng nằm không là mất tiền.
    """

    LOW = "LOW"            # có thể chờ, gộp vào lần bảo trì định kỳ
    NORMAL = "NORMAL"      # xử lý trong 1–2 ngày
    HIGH = "HIGH"          # ảnh hưởng sinh hoạt, xử lý trong ngày
    URGENT = "URGENT"      # mất an toàn / nước rò nghiêm trọng → dừng phòng


class IncidentStatus(str, Enum):
    """
    Vòng đời phiếu sự cố.

    ```mermaid
    stateDiagram-v2
        [*] --> OPEN: người thuê báo
        OPEN --> ASSIGNED: gán người xử lý
        OPEN --> IN_PROGRESS: bắt tay vào luôn
        ASSIGNED --> IN_PROGRESS
        IN_PROGRESS --> RESOLVED: xong, chờ người thuê xác nhận
        RESOLVED --> CLOSED: người thuê đánh giá / quản lý đóng
        RESOLVED --> IN_PROGRESS: chưa xong, mở lại
        OPEN --> CANCELLED: báo nhầm
        ASSIGNED --> CANCELLED
        CLOSED --> [*]
        CANCELLED --> [*]
    ```

    ⭐ `RESOLVED` ≠ `CLOSED` là cố ý.
       "Thợ nói xong" và "Người thuê xác nhận xong" là 2 sự kiện khác nhau.
       Nếu gộp làm một, thợ sửa xong rồi bỏ ngang, hệ thống vẫn tưởng đã xong.
    """

    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


#: Trạng thái coi là "đã xử lý xong" (để tính MTTR).
DONE_STATUSES: frozenset[str] = frozenset({
    IncidentStatus.RESOLVED.value,
    IncidentStatus.CLOSED.value,
})

#: Trạng thái phiếu đã đóng (không còn việc phải làm) — gồm cả phiếu hủy vì báo nhầm.
#: Dùng cho bộ lọc "chưa xử lý xong" và chặn sửa phiếu; MTTR vẫn chỉ dùng DONE_STATUSES.
CLOSED_STATUSES: frozenset[str] = DONE_STATUSES | {IncidentStatus.CANCELLED.value}


class MaintenanceScope(str, Enum):
    """Phạm vi áp dụng của lịch bảo trì định kỳ."""

    BUILDING = "BUILDING"      # cả tòa nhà: vệ sinh thang, hành lang
    ROOM = "ROOM"              # 1 phòng: vệ sinh, kiểm tra ổ cắm
    EQUIPMENT = "EQUIPMENT"    # 1 thiết bị: bình nóng lạnh, máy giặt


class Frequency(str, Enum):
    """Tần suất lặp lại của lịch bảo trì."""

    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    ANNUAL = "ANNUAL"


#: Số tháng giữa 2 lần thực hiện. Dùng để tính `next_due_date` khi đánh dấu xong.
_MONTHS_PER_STEP: dict[str, int] = {
    Frequency.WEEKLY.value: 0,          # xử lý riêng (tính theo tuần)
    Frequency.MONTHLY.value: 1,
    Frequency.QUARTERLY.value: 3,
    Frequency.SEMI_ANNUAL.value: 6,
    Frequency.ANNUAL.value: 12,
}


# ---------------------------------------------------------------------------
#  Sự cố
# ---------------------------------------------------------------------------
class Incident(Base):
    """
    Phiếu sự cố — đơn vị công việc của đội bảo trì.

    ⭐ VÌ SAO KHÔNG CÓ KHÓA NGOẠI TỚI `rooms`?
       Phòng nằm ở db_room, sự cố ở db_maintenance — 2 database khác nhau,
       PostgreSQL không thể ràng buộc FK chéo. Đây là HẬU QUẢ TRỰC TIẾP
       CỦA VIỆC CHỌN DATABASE-PER-SERVICE, và được chấp nhận có chủ đích:
       đổi lại mỗi service độc lập scale và deploy.
       Bù lại, `room_id` ở đây là bản sao phục vụ truy vấn, và ta luôn tra
       lại room-service (nguồn chuẩn) qua HTTP trước khi thao tác quan trọng.
    """

    __tablename__ = "incidents"
    __table_args__ = (
        # Bộ lọc chính của màn hình "sự cố đang mở": theo cơ sở + trạng thái.
        Index("ix_incident_property_status", "property_id", "status"),
        # Danh sách sự cố của 1 phòng, mới nhất trước.
        Index("ix_incident_room_created", "room_id", "created_at"),
        # Bảng điều phối: lọc sự cố chưa xong, sắp theo mức độ.
        Index("ix_incident_queue", "status", "priority", "created_at"),
        CheckConstraint(
            "priority IN ('LOW','NORMAL','HIGH','URGENT')", name="chk_incident_priority",
        ),
        CheckConstraint(
            "status IN ('OPEN','ASSIGNED','IN_PROGRESS','RESOLVED','CLOSED','CANCELLED')",
            name="chk_incident_status",
        ),
        # ⭐ Tiền LUÔN là `NUMERIC`, không bao giờ `FLOAT` — xem billing.
        #   CHECK phía dưới chặn chi phí âm vì "hoàn tiền vật tư" là chuyện
        #   khác, phải ghi ở hóa đơn chứ không phải ở phiếu sự cố.
        CheckConstraint("cost >= 0", name="chk_incident_cost"),
        CheckConstraint(
            "rating IS NULL OR (rating BETWEEN 1 AND 5)", name="chk_incident_rating",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: Mã phiếu hiển thị cho người thuê khi gọi điện: `SC-2026-0001`.
    #: UNIQUE toàn hệ thống (không theo cơ sở) vì người thuê có thể gọi
    #: bất kỳ cơ sở nào của hệ thống và phải tra cứu được bằng 1 mã duy nhất.
    ticket_no: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    property_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True,
        comment="Cơ sở — tra lại room-service khi cần chắc chắn",
    )
    #: NULL khi người thuê báo hư ở khu vực chung (thang, hành lang, sân).
    room_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)

    #: Ai báo — là `tenant_id` (trỏ sang db_tenant) nếu người thuê báo,
    #: hoặc `user_id` (db_auth) nếu quản lý tự ghi. Giữ 1 cột + cờ
    #: `reporter_kind` sẽ phải giải thích kiểu ở tầng ứng dụng; tách
    #: riêng 2 cột nullable rõ hơn, đánh đổi bằng 1 CHECK constraint.
    reported_by_tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    #: Tên người báo, chụp lại tại thời điểm báo. Bản sao CỐ Ý: số điện
    #: thoại và tên có thể đổi, nhưng phiếu sự cố cần giữ nguyên người đã
    #: báo ai để đối chiếu khi có tranh chấp. Đây là dữ liệu lịch sử, không
    #: phải dữ liệu nghiệp vụ đang dùng.
    reported_by_name: Mapped[str] = mapped_column(String(100), nullable=False)
    reported_by_phone: Mapped[str | None] = mapped_column(String(15))

    category: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="PLUMBING/ELECTRIC/APPLIANCE/FURNITURE/STRUCTURE/PEST/GAS/OTHER",
    )
    priority: Mapped[str] = mapped_column(
        String(10), nullable=False, default=IncidentPriority.NORMAL.value, index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    #: DANH SÁCH OBJECT KEY trong MinIO, KHÔNG phải URL.
    #: Xem giải thích ở đầu file.
    photos: Mapped[list | None] = mapped_column(ARRAY(Text), default=list)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IncidentStatus.OPEN.value, index=True,
    )

    # ---- Xử lý ----
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), index=True, comment="user_id trong auth-service",
    )
    assigned_to_name: Mapped[str | None] = mapped_column(
        String(100), comment="Chụp tên để lịch sử không đổi theo tên tài khoản",
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(Text, comment="Cách đã xử lý")

    #: Chi phí sửa. NULL = chưa biết (chưa sửa xong). 0 = sửa không mất tiền.
    #: `NUMERIC` chứ không phải `FLOAT` — xem `billing/pricing.py` để hiểu
    #: vì sao 0.1 + 0.2 != 0.3 là điều không được phép trong tiền.
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    #: Người thuê đánh giá sau khi xong (1 = rất tệ … 5 = rất hài lòng).
    #: CHỈ được đặt khi đã RESOLVED/CLOSED — xem check ở tầng nghiệp vụ.
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    rating_comment: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ---- Thuộc tính suy ra ----
    @property
    def is_open(self) -> bool:
        """Phiếu còn đang xử lý (chưa RESOLVED/CLOSED/CANCELLED)?"""
        return self.status not in (IncidentStatus.RESOLVED.value,
                                   IncidentStatus.CLOSED.value,
                                   IncidentStatus.CANCELLED.value)

    @property
    def is_safety_critical(self) -> bool:
        """Loại sự cố bắt buộc phải có người ký xác nhận an toàn?"""
        return self.category in SAFETY_CRITICAL_CATEGORIES

    @property
    def resolution_hours(self) -> float | None:
        """
        Số giờ từ lúc báo đến lúc xử lý xong (MTTR).

        ⭐ MTTR = Mean Time To Repair là chỉ số quan trọng nhất của bảo trì:
           "trung bình mất bao lâu để sửa xong một sự cố". Nhà trọ nào
           sửa nhanh hơn thì người thuê ở lâu hơn.
        """
        if self.resolved_at is None:
            return None
        return round((self.resolved_at - self.created_at).total_seconds() / 3600, 2)

    @property
    def overdue(self) -> bool:
        """Quá hạn so với cam kết với người thuê chưa?"""
        return self.is_open and self.priority in (
            IncidentPriority.URGENT.value, IncidentPriority.HIGH.value
        )

    def __repr__(self) -> str:
        return f"<Incident {self.ticket_no} [{self.status}]>"


# ---------------------------------------------------------------------------
#  Lịch bảo trì định kỳ
# ---------------------------------------------------------------------------
class MaintenanceSchedule(Base):
    """
    Lịch bảo trì định kỳ — "hàng tháng vệ sinh thang", "3 tháng kiểm tra điện".

    ⭐ VÌ SAO KHÔNG DÙNG APScheduler CHO VIỆC NÀY?
       APScheduler giữ job trong RAM. Container restart là mất sạch; scale
       từ 1 lên 3 replica thì job chạy 3 lần. Lịch bảo trì là DỮ LIỆU
       NGHIỆP VỤ (người thuê hỏi "bao giờ thay bóng đèn" thì phải trả lời
       được), nên nó phải nằm trong DB, còn job quét thì do scheduler
       container gọi API nội bộ.
    """

    __tablename__ = "maintenance_schedules"
    __table_args__ = (
        # Job quét hằng ngày: lấy các lịch đến hạn.
        Index("ix_schedule_due", "is_active", "next_due_date"),
        Index("ix_schedule_property", "property_id", "is_active"),
        CheckConstraint(
            "scope IN ('BUILDING','ROOM','EQUIPMENT')", name="chk_schedule_scope",
        ),
        CheckConstraint(
            "frequency IN ('WEEKLY','MONTHLY','QUARTERLY','SEMI_ANNUAL','ANNUAL')",
            name="chk_schedule_frequency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True,
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    #: room_id nếu scope=ROOM, equipment id nếu EQUIPMENT, NULL nếu BUILDING.
    target_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Danh sách việc cần làm, dạng cấu trúc:
    #: `[{"task": "Kiểm tra ổ cắm", "required": true}, ...]`
    #: ⭐ Lưu JSONB chứ không lưu bảng con vì danh sách này LUÔN được đọc
    #:   cùng lúc với lịch, không bao giờ truy vấn "task này thuộc lịch nào".
    task_template: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    frequency: Mapped[str] = mapped_column(
        String(20), nullable=False, default=Frequency.MONTHLY.value,
    )
    #: Hạn lần tới. Được tính tự động khi đánh dấu `complete`.
    next_due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: "Ngày mục tiêu" trong tháng (1–31) — mốc neo, lấy từ lần hạn đầu tiên.
    #: ⭐ Không có cột này thì lịch "mỗi tháng ngày 31" sẽ TRƯỢT DẦN:
    #:    31/1 → 28/2 (tháng 2 chỉ có 28 ngày) → 28/3 → 28/4 … và sau một năm
    #:    thành "ngày 28" vĩnh viễn. Người thuê hỏi "vệ sinh tháng này hôm
    #:    nào?" thì nhận câu trả lời sai mà không ai phát hiện. Xem `advance()`.
    anchor_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    last_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Số lần đã thực hiện — dùng để báo cáo "bảo trì đều đặn" và chứng minh
    #: nhà trọ có chăm sóc tài sản (pháp lý khi có tranh chấp).
    times_completed: Mapped[int] = mapped_column(Integer, default=0)
    #: Người thuê có cần biết trước không? VD thay bóng đèn không cần báo,
    #: nhưng xem dựng tường chắc phải báo 24h.
    notify_tenants: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_due(self) -> bool:
        """Đã tới hạn thực hiện chưa?"""
        return self.is_active and self.next_due_date <= date.today()

    def days_until_due(self) -> int:
        """Số ngày nữa tới hạn (âm = đã trễ hạn)."""
        return (self.next_due_date - date.today()).days

    def advance(self, from_date: date | None = None) -> date:
        """
        Tính hạn lần tới, neo theo `anchor_day` (ngày mục tiêu trong tháng).

        ⚠️  Hai bẫy ở đây, cả hai đều gây lỗi "lệch 1–3 ngày" rất khó phát hiện:

        1. Cộng tháng vào NGÀY 31: `31/1 + 1 tháng` phải ra `28/2` hay `3/3`?
           PostgreSQL trả về `3/3`, tức lịch "vệ sinh cuối tháng" chạy vào
           giữa tháng sau. Ta neo về CUỐI THÁNG khi ngày mục tiêu vượt quá
           số ngày của tháng đích.

        2. Trượt dần: nếu lấy `min()` rồi lưu kết quả làm mốc lần sau
           thì 31/1 → 28/2 → 28/3 → 28/4… và "ngày 31" biến mất vĩnh viễn.
           Vì thế `advance()` LUÔN quay về `anchor_day`, không dùng ngày của
           kết quả lần trước làm mốc.
        """
        base = from_date or date.today()
        months = _MONTHS_PER_STEP.get(self.frequency, 1)
        if months == 0:      # WEEKLY — không có vấn đề cuối tháng
            return base + timedelta(days=7)

        year = base.year + (base.month - 1 + months) // 12
        month = (base.month - 1 + months) % 12 + 1
        day = min(self.anchor_day or base.day, _days_in_month(year, month))
        return date(year, month, day)

    def __repr__(self) -> str:
        return f"<MaintenanceSchedule {self.title} hạn {self.next_due_date}>"


def _days_in_month(year: int, month: int) -> int:
    """Số ngày của tháng — tránh phụ thuộc thư viện ngoài cho 1 việc này."""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day
