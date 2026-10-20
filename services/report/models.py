"""
report-service — Mô hình đọc (read model) CQRS.        db_report

================================================================================
ĐÂY LÀ SERVICE DUY NHẤT ÁP DỤNG CQRS
================================================================================
Viết trên giấy, "CQRS" nghe rất ghê gớm. Ở đây nó chỉ có một ý nghĩa rất
thực tế:

    Viết dữ liệu (command) và ĐỌC dữ liệu (query) có hình dạng khác nhau,
    nên chúng nên nằm ở hai nơi khác nhau.

Cụ thể ở hệ thống này: muốn biết "tháng này thu được bao nhiêu, trong đó phần
điện nước là bao nhiêu, tỷ lệ thu hồi ra sao" — phải gộp dữ liệu từ billing,
room, contract, maintenance. Với kiến trúc database-per-service, KHÔNG THỂ viết
một câu SQL join được. Chỉ có 2 cách:

  a) Gọi 4 service qua HTTP mỗi lần mở dashboard → 4 chuyến mạng nối tiếp,
     độ trễ p95 có thể 1–2 giây, và 1 service chết là dashboard chết theo.

  b) Dựng SẴN một mô hình đọc (read model) riêng, cập nhật liên tục từ event.
     Đọc thì 1 câu SQL trên 1 bảng, luôn nhanh, và service nguồn chết thì báo
     cáo vẫn còn (chỉ cũ thêm vài giây).

Ta chọn (b). Đó là toàn bộ ý nghĩa của CQRS trong đồ án này.

================================================================================
ĐÁNH ĐỔI ĐƯỢC CHẤP NHẬN: READ MODEL CÓ THỂ LỆCH VỚI DỮ LIỆU GỐC
================================================================================
Read model là BẢN SAO. Nó có thể lệch — và sẽ lệch, trong 2 trường hợp:

  1. Event đến trễ (vài giây) hoặc mất hẳn (RabbitMQ sập giữa lúc publish).
  2. Logic cập nhật read model có bug.

Vì vậy service này có phần **ĐỐI CHIẾU (reconciliation)**: định kỳ gọi internal
API của các service nguồn, chụp lại trạng thái hiện tại rồi ghi đè vào read
model. Đây là cách duy nhất để read model tự lành khi lệch, và cũng là câu trả
lời cho câu hỏi kinh điển: "event-driven có đáng tin không?"

Trả lời: KHÔNG đáng tin nếu để mãi. Nhưng đủ tin nếu có đường đối chiếu.

================================================================================
PHÂN LOẠI DỮ LIỆU — QUY TẮC QUAN TRỌNG NHẤT CỦA FILE NÀY
================================================================================
Mọi bảng trong db_report thuộc 1 trong 2 loại, và cách xử lý hoàn toàn KHÁC
NHAU. Nhầm lẫn 2 loại này là nguồn gốc của hầu hết bug trong hệ thống
event-driven:

  ┌─────────────────────────────┬──────────────────────────────────────────┐
  │ SỰ KIỆN BẤT BIẾN (facts)   │ TRẠNG THÁI (state)                      │
  ├─────────────────────────────┼──────────────────────────────────────────┤
  │ invoice.issued              │ Có bao nhiêu phòng đang trống hôm nay  │
  │ payment.received            │ Tỷ lệ công suất lúc này                 │
  │ contract.activated          │ Hóa đơn nào còn nợ tới hôm nay         │
  │ incident.created            │                                          │
  ├─────────────────────────────┼──────────────────────────────────────────┤
  │ CỘNG DẦN (+1, +500.000)    │ GHI ĐÈ (snapshot)                       │
  │ Chỉ cần event               │ PHẢI có đường đối chiếu                │
  │ Đến trễ thì số liệu trễ    │ Không đối chiếu thì vĩa khỏi thì hỏng   │
  │ Đến trùng thì tăng sai      │ Ghi đè nhiều lần vẫn đúng               │
  ├─────────────────────────────┼──────────────────────────────────────────┤
  │ daily_financials            │ daily_occupancy                         │
  │ daily_contract_flow         │ open_invoices                           │
  │ daily_incident_stats        │                                          │
  └─────────────────────────────┴──────────────────────────────────────────┘

Cột `source` trên bảng trạng thái cho biết dòng dữ liệu đến từ đâu:
  `event` (cập nhật khi nhận event)  |  `snapshot` (chụp lại lúc đối chiếu)
Khi hai nguồn khác nhau, `snapshot` luôn thắng — vì nó đọc thẳng từ nguồn
chuẩn, và được ghi sau cùng.

================================================================================
VÌ SAO PHÉP CỘNG NẰM TRONG SQL, KHÔNG LÀM TRONG PYTHON?
================================================================================
    # ❌ Sai — đọc rồi cộng trong Python
    row = await session.get(DailyFinancial, key)
    row.collected_amount += amount          # mất update nếu 2 consumer cùng ghi

    # ✅ Đúng — phép cộng do chính PostgreSQL thực hiện, nguyên tử
    INSERT ... ON CONFLICT (khoá) DO UPDATE SET collected = collected + :delta

RabbitMQ bảo đảm at-least-once, nên 2 consumer cùng xử lý 1 event là chuyện
bình thường (đọc-rồi-ghi bằng Python sẽ cộng 2 lần). Xem `record_financials`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from common.config import settings
from common.database import Base

#: Số ngày dữ liệu chi tiết được giữ. Báo cáo vận hành không cần dữ liệu từng
#: ngày của 5 năm trước — mà giữ thì bảng phình và index nặng. Dữ liệu cũ hơn
#: mức này được tổng hợp theo tháng rồi xoá (xem `rollup_monthly`).
RETENTION_DAYS_DAILY = 730       # ~2 năm

#: Số tháng giữ số liệu đã tổng hợp theo tháng.
RETENTION_MONTHLY = 60           # ~5 năm

#: `property_id` giả, dùng cho DÒNG TỔNG HỢP toàn hệ thống.
#: ⭐ `NULL` không dùng được làm thành phần của PRIMARY KEY trong PostgreSQL,
#:    nên dòng "tất cả cơ sở gộp lại" cần một khoá thật. Dùng UUID toàn 0 —
#:    không thể trùng với UUID sinh ra bởi `uuid4()` của các service khác.
ALL_PROPERTIES = uuid.UUID(int=0)

ZERO = Decimal("0")


# ---------------------------------------------------------------------------
#  Múi giờ nghiệp vụ
# ---------------------------------------------------------------------------
def business_tz() -> timezone | ZoneInfo:
    """
    Múi giờ dùng để gom sự kiện vào đúng "ngày".

    ⭐ Rất dễ sai ở chỗ này: server chạy UTC, sự kiện lúc 07:00 giờ VN là
       00:00 UTC cùng ngày → ghi vào đúng ngày; nhưng sự kiện lúc 01:00 giờ VN
       là 18:00 UTC **hôm trước** → nếu cắt ngày theo UTC thì hóa đơn tháng 1
       bị ghi nhận vào tháng 12. Với báo cáo doanh thu theo tháng, lỗi này làm
       sai cả tháng.
    """
    try:
        return ZoneInfo(settings.default_timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        # Image `python:3.12-slim` không cài sẵn tzdata. Trả về UTC+7 cố định
        # (VN không có giờ mùa hè) để service vẫn chạy được thay vì chết lúc
        # khởi động vì lỗi cấu hình múi giờ.
        return timezone(timedelta(hours=7), "ICT")


def business_day(moment: datetime | None = None) -> date:
    """
    Quy đổi một mốc thời gian (UTC) sang **ngày nghiệp vụ** theo giờ VN.

    Mọi event đều mang `occurred_at` ở UTC. Ta cắt ngày theo giờ VN, không
    theo UTC — xem giải thích ở `business_tz`.
    """
    moment = moment or datetime.now(tz=UTC)
    if moment.tzinfo is None:      # defensive: event cũ có thể thiếu tz
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(business_tz()).date()


def month_key(day: date) -> str:
    """`2026-03-15` → `'2026-03'`. Khoá của bảng tổng hợp tháng."""
    return f"{day.year:04d}-{day.month:02d}"


# ---------------------------------------------------------------------------
#  LOẠI 1 — SỰ KIỆN BẤT BIẾN (chỉ CỘNG dần, không bao giờ ghi đè)
# ---------------------------------------------------------------------------
class DailyFinancial(Base):
    """
    Số tài chính theo ngày — một dòng cho mỗi (cơ sở, ngày).

    ⭐ Mọi cột đều là BỘ ĐẾM/LỘI tích luỹ trong ngày, được cập nhật bằng
       `INSERT ... ON CONFLICT DO UPDATE SET cột = cột + delta`. Phép cộng
       nằm trong chính câu SQL nên an toàn kể cả khi 2 consumer cùng ghi —
       điều mà đọc-rồi-ghi bằng Python thì KHÔNG an toàn.
    """

    __tablename__ = "daily_financials"
    __table_args__ = (
        # Index theo ngày (không theo property) vì dashboard admin thường xem
        # "30 ngày gần nhất toàn hệ thống" — không lọc cơ sở.
        Index("ix_daily_fin_day", "stat_date"),
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
    )
    #: Tên cột là `stat_date` chứ không phải `day` để không đụng từ khoá
    #: ngày trong SQL (`day` là keyword của `EXTRACT`); tên rõ nghĩa cũng dễ
    #: đọc hơn khi nhìn `SELECT`.
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)

    # ---- Phát hành ----
    invoices_issued: Mapped[int] = mapped_column(Integer, default=0)
    invoiced_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 0), default=ZERO,
        comment="Tổng tiền trên các hóa đơn phát hành trong ngày",
    )
    # ---- Thu hồi ----
    payments_received: Mapped[int] = mapped_column(Integer, default=0)
    collected_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 0), default=ZERO,
        comment="Dòng tiền thực nhận (đã trừ phần hoàn tiền)",
    )
    refunded_amount: Mapped[Decimal] = mapped_column(
        Numeric(16, 0), default=ZERO,
        comment="Tiền trả lại cho người thuê khi chấm dứt hợp đồng",
    )
    # ---- Công nợ ----
    #: Số dư công nợ CUỐI NGÀY = (đã phát hành) − (đã thu) + (đã hoàn),
    #: tính lũy kế từ đầu. Đây là số dư chạy, không phải số của riêng ngày —
    #: nên cột này KHÔNG được cộng dồn khi tổng hợp theo tháng.
    outstanding: Mapped[Decimal] = mapped_column(Numeric(16, 0), default=ZERO)
    overdue_count: Mapped[int] = mapped_column(Integer, default=0)
    overdue_amount: Mapped[Decimal] = mapped_column(Numeric(16, 0), default=ZERO)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    @property
    def net_collected(self) -> Decimal:
        """Tiền thu được sau khi trừ phần hoàn — con số chủ nhà quan tâm."""
        return self.collected_amount - self.refunded_amount

    @property
    def collection_ratio(self) -> float:
        """Tỷ lệ thu hồi của ngày (%). Dùng cho biểu đồ."""
        if not self.invoiced_amount:
            return 0.0
        return round(float(self.collected_amount) / float(self.invoiced_amount) * 100, 2)

    def __repr__(self) -> str:
        return f"<DailyFinancial {self.stat_date}: thu {self.collected_amount}>"


class DailyContractFlow(Base):
    """Vòng quay hợp đồng theo ngày — chỉ cộng dần."""

    __tablename__ = "daily_contract_flow"
    __table_args__ = (Index("ix_daily_contract_day", "stat_date"),)

    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)

    created: Mapped[int] = mapped_column(Integer, default=0)
    activated: Mapped[int] = mapped_column(Integer, default=0)
    terminated: Mapped[int] = mapped_column(Integer, default=0)
    expired: Mapped[int] = mapped_column(Integer, default=0)
    cancelled: Mapped[int] = mapped_column(Integer, default=0)
    renewed: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    @property
    def net_new(self) -> int:
        """Hợp đồng mới tăng ròng trong ngày (chuyển vào − chuyển ra)."""
        return self.activated - (self.terminated + self.expired + self.cancelled)


class DailyIncidentStat(Base):
    """Số lượng & chi phí sự cố theo ngày — chỉ cộng dần."""

    __tablename__ = "daily_incident_stats"
    __table_args__ = (Index("ix_daily_incident_day", "stat_date"),)

    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)

    created: Mapped[int] = mapped_column(Integer, default=0)
    urgent: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[Decimal] = mapped_column(
        Numeric(16, 0), default=ZERO,
        comment="Chi phí sửa chữa phát sinh trong ngày",
    )
    #: Tổng giờ sửa (MTTR) của các phiếu xử lý xong trong ngày — suy ra
    #: `resolution_hours = hours / resolved` mà không cần gọi lại
    #: maintenance-service.
    resolution_hours: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=ZERO,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    @property
    def mttr_hours(self) -> float | None:
        """Mean Time To Repair — thời gian sửa trung bình của ngày."""
        if not self.resolved:
            return None
        return round(float(self.resolution_hours) / self.resolved, 2)


class MonthlyFinancial(Base):
    """
    Tổng hợp theo tháng — dữ liệu lâu dài (giữ 5 năm).

    ⭐ Chỉ tổng hợp SỰ KIỆN, không đụng tới `outstanding`. Lý do: `outstanding`
       là số dư chạy, cộng dồn theo tháng sẽ ra "34 tỷ công nợ" — vô nghĩa.
       Số dư công nợ luôn được đọc từ `daily_financials` (giữ 2 năm), vốn là
       nơi duy nhất nó có ý nghĩa.
    """

    __tablename__ = "monthly_financials"
    __table_args__ = (Index("ix_monthly_fin_period", "period"),)

    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    period: Mapped[str] = mapped_column(String(7), primary_key=True)   # 'YYYY-MM'

    invoices_issued: Mapped[int] = mapped_column(Integer, default=0)
    invoiced_amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), default=ZERO)
    payments_received: Mapped[int] = mapped_column(Integer, default=0)
    collected_amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), default=ZERO)
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), default=ZERO)

    days_covered: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="Số ngày thực sự có dữ liệu trong tháng (<=31, dùng để cảnh báo tháng thiếu)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    @property
    def net_collected(self) -> Decimal:
        return self.collected_amount - self.refunded_amount

    def __repr__(self) -> str:
        return f"<MonthlyFinancial {self.period}: thu {self.collected_amount}>"


# ---------------------------------------------------------------------------
#  LOẠI 2 — TRẠNG THÁI (GHI ĐÈ bằng snapshot, CÓ đường đối chiếu)
# ---------------------------------------------------------------------------
class DailyOccupancy(Base):
    """
    Công suất phòng tại một thời điểm.

    ⭐ KHÁC với `DailyFinancial`: đây là TRẠNG THÁI, không phải sự kiện.
       Ngày hôm nay có 3 phòng trống, tối có 2 phòng có người vào — con số
       "hôm nay" là của thời điểm gần nhất, không phải tổng cộng.

       Vì thế cột `source` cho biết dòng dữ liệu đến từ đâu:
         - `event`   : cập nhật khi nhận `room.created` / `room.status_changed`
         - `snapshot`: chụp lại từ room-service lúc đối chiếu định kỳ
    """

    __tablename__ = "daily_occupancy"
    __table_args__ = (Index("ix_daily_occ_day", "stat_date"),)

    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)

    total_rooms: Mapped[int] = mapped_column(Integer, default=0)
    available: Mapped[int] = mapped_column(Integer, default=0)
    occupied: Mapped[int] = mapped_column(Integer, default=0)
    maintenance: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)

    source: Mapped[str] = mapped_column(
        String(10), default="event", comment="event | snapshot",
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    #: Các trạng thái phòng còn lại (CLEANING, OUT_OF_SERVICE...). Không liệt kê
    #: thành cột riêng vì chúng không phải chỉ số chủ nhà theo dõi, nhưng vẫn
    #: cần phân giải `total_rooms` khi đối chiếu.
    other: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def occupancy_rate(self) -> float:
        """
        Tỷ lệ lấp đầy (%).

        ⚠️  Mẫu số là TỔNG số phòng, không phải số phòng "dùng được". Phòng
            đang sửa vẫn là phòng của cơ sở — trừ nó ra khỏi mẫu số sẽ khiến
            tỷ lệ nhảy lên 100% ngay khi sửa xong một phòng, tạo cảm giác
            "vừa có người vào ồ" trong khi thực ra chỉ là phòng hết bảo trì.
            Cách này là cách chủ nhà trọ thực sự tính.
        """
        if not self.total_rooms:
            return 0.0
        return round(self.occupied / self.total_rooms * 100, 2)

    def __repr__(self) -> str:
        return f"<DailyOccupancy {self.stat_date}: {self.occupied}/{self.total_rooms}>"


class OpenInvoice(Base):
    """
    Hình chiếu (projection) của các hóa đơn CHƯA QUÉT HẾT.

    ⭐ Đây là bảng DUY NHẤT trong report-service được cập nhật theo kiểu
       "tìm và sửa dòng" thay vì cộng dần — vì nó là TRẠNG THÁI của một
       thực thể, không phải sự kiện.

       Nó tồn tại để trả lời câu hỏi mà billing-service KHÔNG trả lời
       được: "trong số nợ đang mắc, bao nhiêu quá hạn dưới 7 ngày / 7–30 /
       trên 30?" (báo cáo phân rã công nợ — aging). Không có bảng này thì
       phải đọc TẤT CẢ hóa đơn rồi tự lọc trong Python.

    ⭐ Số tiền lưu dạng `NUMERIC`, không phải float. Xem `billing/pricing.py`
       để hiểu vì sao 0.1 + 0.2 ≠ 0.3 là điều không được phép trong tiền.
    """

    __tablename__ = "open_invoices"
    __table_args__ = (
        # Truy vấn chính của báo cáo công nợ: lọc theo cơ sở + còn nợ + sắp
        # hạn. Partial index chỉ chứa dòng CHƯA QUÉT — bảng này mỗi tháng
        # thêm vài nghìn dòng nhưng chỉ vài trăm dòng là đang mở.
        Index("ix_open_invoice_due", "property_id", "due_date",
              postgresql_where="status = 'OPEN'"),
        Index("ix_open_invoice_contract", "contract_id"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True,
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    room_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    tenant_name: Mapped[str | None] = mapped_column(String(100))

    invoice_no: Mapped[str] = mapped_column(String(30), nullable=False)
    period: Mapped[str | None] = mapped_column(
        String(10), comment="Kỳ hóa đơn, VD: 10/2026",
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 0))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 0), default=ZERO)

    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    issued_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(15), default="OPEN", index=True)
    #: Đã từng bị đánh dấu quá hạn chưa — để đếm "hóa đơn nào đã nhắc rồi".
    is_overdue_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    @property
    def remaining(self) -> Decimal:
        return max(ZERO, self.total_amount - self.paid_amount)

    def days_overdue(self, ref: date | None = None) -> int:
        """Số ngày trễ hạn (0 nếu chưa tới hạn hoặc đã quét)."""
        if self.status not in ("OPEN", "OVERDUE"):
            return 0
        return max(0, ((ref or date.today()) - self.due_date).days)

    def aging_bucket(self, ref: date | None = None) -> str:
        """
        Xếp vào nhóm tuổi nợ — cách trình bày chuẩn của báo cáo công nợ.

        ⭐ Vì sao chia nhóm thay vì đưa con số "trễ 47 ngày"?
            Chủ nhà trọ không hành động được theo "47 ngày" — họ cần biết
            "bao nhiêu tiền nằm trong nhóm nguy hiểm (>30 ngày)". Báo cáo phải
            dẫn tới quyết định, không phải chỉ mô tả dữ liệu.
        """
        days = self.days_overdue(ref)
        if days <= 0:
            return "CHUA_DEN_HAN"
        if days <= 7:
            return "1_7_NGAY"
        if days <= 30:
            return "8_30_NGAY"
        if days <= 60:
            return "31_60_NGAY"
        return "TREN_60_NGAY"

    def __repr__(self) -> str:
        return f"<OpenInvoice {self.invoice_no} còn {self.remaining}>"


# ---------------------------------------------------------------------------
#  VẬN HÀNH
# ---------------------------------------------------------------------------
class SyncRun(Base):
    """
    Nhật ký 1 lần chạy đối chiếu (reconciliation).

    ⭐ Bảng này tồn tại cho vận hành, không phải cho nghiệp vụ. Khi dashboard
       hiện số lệch với thực tế, câu hỏi đầu tiên luôn là "lần đối chiếu gần
       nhất chạy lúc nào, ra kết quả gì, có lỗi không?". Không có bảng này
       thì phải đào log container — mà log thì đã bị xoá vòng (log rotation).
    """

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: `reconcile_occupancy` | `reconcile_invoices` | `retention` | `full`
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(
        String(15), default="RUNNING", index=True,
        comment="RUNNING | SUCCESS | PARTIAL | FAILED",
    )
    rows_synced: Mapped[int] = mapped_column(Integer, default=0)
    #: Chi tiết lỗi từng nguồn (JSONB) — để biết service nào chết.
    detail: Mapped[dict | None] = mapped_column(JSON)
    message: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[SmallInteger | None] = mapped_column(SmallInteger)
    triggered_by: Mapped[str] = mapped_column(
        String(40), default="scheduler", comment="scheduler | manual | api",
    )

    def __repr__(self) -> str:
        return f"<SyncRun {self.kind} {self.status}>"


# ---------------------------------------------------------------------------
#  HÀM GHI — đây là phần "quan trọng nhất" của file
# ---------------------------------------------------------------------------
#: Các cột bộ đếm (kiểu int) của `DailyOccupancy`.
OCCUPANCY_BUCKETS = ("total_rooms", "available", "occupied", "maintenance",
                     "reserved", "other")


async def record_financials(
    session: AsyncSession,
    property_id: uuid.UUID,
    day: date,
    *,
    invoices_issued: int = 0,
    invoiced_amount: Decimal | str | int = 0,
    payments_received: int = 0,
    collected_amount: Decimal | str | int = 0,
    refunded_amount: Decimal | str | int = 0,
    overdue_count: int = 0,
    overdue_amount: Decimal | str | int = 0,
    outstanding_delta: Decimal | str | int | None = None,
) -> None:
    """
    Cộng dồn chỉ số tài chính của 1 ngày — phép cộng do PostgreSQL thực hiện.

    ⭐ `outstanding_delta` được tách riêng vì nó cần CHỐT Ở 0:

        Khách trả thừa (chuyển khoản tròn để trả tiền phòng) là chuyện rất
        thường ở Việt Nam. Nếu trừ thẳng, số dư công nợ có thể âm → báo cáo
        hiện "công nợ -500.000đ" và biểu đồ vỡ. Đây là cùng một nguyên tắc
        với R3 (không trừ quá cọc) và R3-billing (`max(0, …)` khi tính tiền).

    Mọi giá trị tiền đều ép qua `Decimal(str(...))` — xem `billing/pricing.py`.
    """
    invoiced = Decimal(str(invoiced_amount))
    collected = Decimal(str(collected_amount))
    refunded = Decimal(str(refunded_amount))
    overdue_amt = Decimal(str(overdue_amount))
    if outstanding_delta is None:
        # Mặc định: phát hành thì nợ tăng, thu thì nợ giảm, hoàn thì nợ tăng lại.
        delta = invoiced - collected + refunded
    else:
        delta = Decimal(str(outstanding_delta))

    if not any((invoices_issued, invoiced, payments_received, collected,
                refunded, overdue_count, overdue_amt, delta)):
        return                      # không có gì để ghi — đừng tạo dòng rỗng

    table = DailyFinancial.__table__
    stmt = pg_insert(table).values(
        property_id=property_id, stat_date=day,
        invoices_issued=invoices_issued, invoiced_amount=invoiced,
        payments_received=payments_received, collected_amount=collected,
        refunded_amount=refunded, overdue_count=overdue_count,
        overdue_amount=overdue_amt, outstanding=delta if delta > 0 else ZERO,
        updated_at=func.now(),
    )
    # `table.c.outstanding + delta` → SQL: outstanding + :delta
    # `func.greatest(0, …)` → chặn âm.
    clamped = func.greatest(
        0, func.coalesce(table.c.outstanding, 0) + (delta if delta else ZERO)
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["property_id", "stat_date"],
        set_={
            "invoices_issued": table.c.invoices_issued + invoices_issued,
            "invoiced_amount": table.c.invoiced_amount + invoiced,
            "payments_received": table.c.payments_received + payments_received,
            "collected_amount": table.c.collected_amount + collected,
            "refunded_amount": table.c.refunded_amount + refunded,
            "overdue_count": table.c.overdue_count + overdue_count,
            "overdue_amount": table.c.overdue_amount + overdue_amt,
            "outstanding": clamped,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)


async def bump_counters(
    session: AsyncSession,
    model: type[Base],
    property_id: uuid.UUID,
    day: date,
    deltas: dict[str, int],
) -> None:
    """
    Cộng dồn một bảng bộ đếm (hợp đồng, sự cố) — cùng nguyên tắc với
    `record_financials`: phép cộng nằm trong SQL nên chống được race condition.

    `deltas` nhận cả `int` và `Decimal` (chi phí sửa chữa, tổng giờ sửa).
    """
    deltas = {k: v for k, v in deltas.items() if v}
    if not deltas:
        return

    table = model.__table__
    stmt = pg_insert(table).values(property_id=property_id, stat_date=day, **deltas)
    stmt = stmt.on_conflict_do_update(
        index_elements=["property_id", "stat_date"],
        set_={name: table.c[name] + value for name, value in deltas.items()}
        | {"updated_at": func.now()},
    )
    await session.execute(stmt)


async def apply_occupancy_delta(
    session: AsyncSession,
    property_id: uuid.UUID,
    day: date,
    deltas: dict[str, int],
    *,
    source: str = "event",
) -> None:
    """
    Cập nhật công suất theo SỰ KIỆN (phòng được tạo / đổi trạng thái).

    Dùng phép cộng (`+1`, `-1`) vì `room.status_changed` mang CẢ trạng thái
    cũ lẫn mới: phải trừ ở nhóm cũ và cộng ở nhóm mới trong cùng một câu.

    Vẫn chặn âm bằng `GREATEST(0, …)`: nếu đã lệch trạng thái (mất event) thì
    một lần trừ quá tay sẽ tạo số âm vĩnh viễn trong báo cáo.
    """
    deltas = {k: int(v) for k, v in deltas.items() if v}
    if not deltas:
        return

    table = DailyOccupancy.__table__
    stmt = pg_insert(table).values(
        property_id=property_id, stat_date=day, source=source,
        **{name: max(0, value) for name, value in deltas.items()},
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["property_id", "stat_date"],
        set_={
            name: func.greatest(0, func.coalesce(table.c[name], 0) + value)
            for name, value in deltas.items()
        }
        | {"source": source, "captured_at": func.now()},
    )
    await session.execute(stmt)


async def set_occupancy_snapshot(
    session: AsyncSession,
    property_id: uuid.UUID,
    day: date,
    counts: dict[str, int],
    *,
    source: str = "snapshot",
) -> None:
    """
    GHI ĐÈ toàn bộ công suất bằng ảnh chụp từ room-service (đối chiếu).

    Khác `apply_occupancy_delta` ở chỗ: đây là TRẠNG THÁI, nên ghi đè chứ
    không cộng. Ghi đè nhiều lần vẫn cho cùng một kết quả — đó là lý do bảng
    trạng thái có thể tự lành.
    """
    values = {name: max(0, int(counts.get(name, 0))) for name in OCCUPANCY_BUCKETS}
    table = DailyOccupancy.__table__
    stmt = pg_insert(table).values(
        property_id=property_id, stat_date=day, source=source,
        captured_at=func.now(), **values,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["property_id", "stat_date"],
        set_=values | {"source": source, "captured_at": func.now()},
    )
    await session.execute(stmt)


async def upsert_open_invoice(session: AsyncSession, data: dict[str, Any]) -> None:
    """
    Thêm/sửa dòng công nợ — dùng cho cả 2 đường: nhận event lúc phát hành
    và đối chiếu lại từ billing.

    Dùng `excluded` (giá trị trong `VALUES`) nên thao tác này vừa là INSERT
    vừa là UPDATE, chỉ với 1 câu.

    ⭐ Chỉ nhận đúng tên cột có thật. Event đến từ 4 service khác nhau, không
       ai đảm bảo payload giống hệt nhau — lọc ở đây giúp 1 service thêm
       trường mới không làm hỏng toàn bộ pipeline đọc báo cáo.
    """
    writable = {c.name for c in OpenInvoice.__table__.columns
                if c.name not in ("created_at", "updated_at")}
    payload = {k: v for k, v in data.items() if k in writable}
    payload["updated_at"] = func.now()

    table = OpenInvoice.__table__
    stmt = pg_insert(table).values(**payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["invoice_id"],
        set_={
            name: stmt.excluded[name] for name in payload if name != "invoice_id"
        },
    )
    await session.execute(stmt)


#: Cột được dùng để gom nhóm khi tổng hợp tháng: `2026-03-15` → `'2026-03'`.
_PERIOD = func.to_char(DailyFinancial.stat_date, "YYYY-MM")


async def rollup_monthly(
    session: AsyncSession, since: date, until: date,
) -> int:
    """
    Tổng hợp `daily_financials` → `monthly_financials` cho khoảng [since, until).

    ⭐ GHI ĐÈ (`EXCLUDED`), không cộng dồn. Vì tháng đã đóng rồi thì số liệu
       của nó không được phép thay đổi nữa — nếu có event đến muộn, lần tổng
       hợp sau sẽ tính lại từ đầu cho cả tháng. Cộng dồn ở đây sẽ khiến
       doanh thu tháng bị nhân đôi.
    """
    period = _PERIOD
    source = select(
        DailyFinancial.property_id.label("property_id"),
        period.label("period"),
        func.sum(DailyFinancial.invoices_issued).label("invoices_issued"),
        func.sum(DailyFinancial.invoiced_amount).label("invoiced_amount"),
        func.sum(DailyFinancial.payments_received).label("payments_received"),
        func.sum(DailyFinancial.collected_amount).label("collected_amount"),
        func.sum(DailyFinancial.refunded_amount).label("refunded_amount"),
        func.count(DailyFinancial.stat_date).label("days_covered"),
    ).where(
        DailyFinancial.stat_date >= since,
        DailyFinancial.stat_date < until,
    ).group_by(DailyFinancial.property_id, period)

    columns = [
        "property_id", "period", "invoices_issued", "invoiced_amount",
        "payments_received", "collected_amount", "refunded_amount", "days_covered",
    ]
    stmt = pg_insert(MonthlyFinancial.__table__).from_select(columns, source)
    # `excluded.<cột>` = giá trị mới do SELECT vừa tính ra.
    stmt = stmt.on_conflict_do_update(
        index_elements=["property_id", "period"],
        set_={name: stmt.excluded[name] for name in columns[2:]}
        | {"updated_at": func.now()},
    )
    result = await session.execute(stmt)
    return int(result.rowcount or 0)


async def purge_expired(session: AsyncSession, *, today: date | None = None) -> dict:
    """
    Dọn dữ liệu quá hạn: tổng hợp trước, rồi mới xoá.

    ⭐ THỨ TỰ NÀY QUAN TRỌNG. Nếu xoá `daily_financials` rồi mới tổng hợp,
       2 năm dữ liệu chi tiết sẽ mất vĩnh viễn mà `monthly_financials` thì
       trống. Phải tổng hợp TRƯỚC, xác nhận xong mới xoá.
    """
    today = today or business_day()
    daily_cutoff = today - timedelta(days=RETENTION_DAYS_DAILY)
    monthly_cutoff = date(today.year - (RETENTION_MONTHLY // 12), today.month, 1)
    runs_cutoff = datetime.now(tz=UTC) - timedelta(days=RETENTION_MONTHLY // 6)

    rolled = await rollup_monthly(
        session, daily_cutoff - timedelta(days=40), daily_cutoff + timedelta(days=1),
    )

    daily = (await session.execute(
        DailyFinancial.__table__.delete()
        .where(DailyFinancial.stat_date < daily_cutoff)
    )).rowcount or 0
    flow = (await session.execute(
        DailyContractFlow.__table__.delete()
        .where(DailyContractFlow.stat_date < daily_cutoff)
    )).rowcount or 0
    incidents = (await session.execute(
        DailyIncidentStat.__table__.delete()
        .where(DailyIncidentStat.stat_date < daily_cutoff)
    )).rowcount or 0
    monthly = (await session.execute(
        MonthlyFinancial.__table__.delete()
        .where(MonthlyFinancial.period < month_key(monthly_cutoff))
    )).rowcount or 0
    runs = (await session.execute(
        SyncRun.__table__.delete().where(SyncRun.started_at < runs_cutoff)
    )).rowcount or 0

    return {
        "rollup_rows": rolled,
        "daily_financials_deleted": daily,
        "daily_contract_flow_deleted": flow,
        "daily_incident_stats_deleted": incidents,
        "monthly_financials_deleted": monthly,
        "sync_runs_deleted": runs,
    }
