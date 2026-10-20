"""
billing-service — Mô hình dữ liệu.  Cổng 8005  |  db_billing  *(Core Domain)*

===============================================================================
PHẠM VI SỞ HỮU DỮ LIỆU
===============================================================================
Nguồn duy nhất cho: biểu giá, phí dịch vụ, chỉ số điện nước, hóa đơn, thanh
toán, công nợ.

⚠️  KHÔNG CÓ BẤT KỲ FOREIGN KEY NÀO TỚI DB KHÁC.
    `invoices.contract_id` là tham chiếu LOGIC, không phải ràng buộc. Đây là
    hệ quả trực tiếp của mẫu *Database-per-Service*: mỗi service tự chịu
    trách nhiệm toàn vẹn dữ liệu của mình; tính nhất quán xuyên service được
    bảo đảm bằng Saga, không bằng ràng buộc SQL.

===============================================================================
VERSIONING BIỂU GIÁ — VÌ SAO KHÔNG SỬA GIÁ CŨ
===============================================================================
Bảng `price_tiers` có `effective_from` / `effective_to`. Khi giá điện tăng,
ta ĐÓNG băng bảng giá cũ (`effective_to = hôm nay`) và MỞ bảng giá mới.
Không bao giờ `UPDATE` giá của bảng cũ.

Lý do: hóa đơn tháng 9 đã phát ra cho người thuê, trong đó có dòng tiền
điện tính theo bảng giá tháng 9. Nếu sửa bảng giá đó, báo cáo doanh thu tháng 9
sẽ tự đổi — sổ sách tài chính bị viết lại sau khi đã gửi khách. Đây là
nguyên tắc kế toán: số đã phát hành là bất biến.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


class UtilityType(str, Enum):
    ELECTRIC = "ELECTRIC"
    WATER = "WATER"

    @property
    def unit(self) -> str:
        return "kWh" if self is UtilityType.ELECTRIC else "m³"

    @property
    def label_vi(self) -> str:
        return "Điện" if self is UtilityType.ELECTRIC else "Nước"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"          # đang soạn, chưa gửi ai
    PENDING = "PENDING"      # đã phát, chờ thanh toán
    PAID = "PAID"            # đã thu đủ
    OVERDUE = "OVERDUE"      # quá hạn, chưa trả
    CANCELLED = "CANCELLED"  # huỷ (vd: hợp đồng bị huỷ giữa chừng)

    @property
    def is_editable(self) -> bool:
        """
        ⭐ R8 — hóa đơn `PAID` không sửa được.

        Một hóa đơn đã thu tiền là bằng chứng đã giao dịch. Sửa nó sau khi
        nhận tiền là sửa lịch sử tài chính — với bất kỳ hệ thống kế toán nào
        điều này đều là vi phạm. Muốn điều chỉnh thì phát hóa đơn điều chỉnh.
        """
        return self in (InvoiceStatus.DRAFT, InvoiceStatus.PENDING)


class PaymentMethod(str, Enum):
    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    MOMO = "MOMO"
    VNPAY = "VNPAY"
    CARD = "CARD"


class ItemType(str, Enum):
    RENT = "RENT"
    ELECTRIC = "ELECTRIC"
    WATER = "WATER"
    SERVICE = "SERVICE"
    LATE_FEE = "LATE_FEE"
    DEPOSIT = "DEPOSIT"
    DISCOUNT = "DISCOUNT"
    PENALTY = "PENALTY"


# ---------------------------------------------------------------------------
#  Biểu giá
# ---------------------------------------------------------------------------
class PriceTier(Base):
    """
    Một bậc của biểu giá điện/nước, có hiệu lực theo thời gian.

    `up_to_qty = NULL` nghĩa là bậc cuối, không giới hạn. Ta dùng NULL thay
    vì `Infinity` vì `Infinity` trong `Numeric` của PostgreSQL sẽ làm mọi
    phép so sánh trở nên kỳ quặc.
    """

    __tablename__ = "price_tiers"
    __table_args__ = (
        UniqueConstraint(
            "property_id", "utility_type", "tier_index", "effective_from",
            name="uq_price_tier_version",
        ),
        # Truy vấn nóng: lấy biểu giá đang hiệu lực của 1 cơ sở
        Index("ix_price_tier_lookup", "property_id", "utility_type", "effective_from"),
        CheckConstraint("unit_price >= 0", name="chk_price_tier_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    utility_type: Mapped[str] = mapped_column(String(10), nullable=False)
    tier_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Dùng Numeric chứ không phải Integer: ảnh chụp/thước đo có thể có
    # phần thập phân (đồng hồ điện 5 chữ số + 2 số thập phân).
    up_to_qty: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        top = "∞" if self.up_to_qty is None else self.up_to_qty
        return f"<PriceTier {self.utility_type}#{self.tier_index} ≤{top} @ {self.unit_price}>"


class ServiceFee(Base):
    """
    Phí dịch vụ cố định hằng tháng của một cơ sở (internet, vệ sinh, rác, xe).

    `is_mandatory=False` nghĩa là phí tuỳ chọn — người thuê không dùng thì
    không tính. Biểu giá bắt buộc vẫn nằm ở đây, KHÔNG nhân với `is_mandatory`
    (người thuê có thể không dùng xe nhưng vẫn phải trả phí rác).
    """

    __tablename__ = "service_fees"
    __table_args__ = (
        UniqueConstraint("property_id", "code", name="uq_service_fee_code"),
        CheckConstraint("amount >= 0", name="chk_service_fee_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ServiceFee {self.code} {self.amount}>"


# ---------------------------------------------------------------------------
#  Chỉ số điện nước
# ---------------------------------------------------------------------------
class MeterReading(Base):
    """
    Chỉ số đồng hồ tại một kỳ (tháng).

    ⭐ R4 — chỉ số kỳ này PHẢI LỚN HƠN kỳ trước. Đồng hồ điện nước chỉ
       tăng; nếu nhập nhỏ hơn thì hoặc là nhập sai, hoặc đổi đồng hồ. Cả hai
       đều cần xử lý như lỗi dữ liệu, không phải "chấp nhận được".

    `consumption` là Cột sinh tự động (GENERATED ALWAYS AS ... STORED): được
    PostgreSQL tự tính, ứng dụng không có cách ghi sai. Chọn STORED vì ta
    lọc/sắp xếp theo nó thường xuyên; nếu chỉ để đọc thì VIRTUAL tiết kiệm
    ổ đĩa hơn.
    """

    __tablename__ = "meter_readings"
    __table_args__ = (
        # Idempotency: cùng 1 phòng + cùng 1 kỳ chỉ nhập được 1 lần.
        # Đây là hàng rào chống "bấm nút 2 lần sinh 2 bản ghi".
        UniqueConstraint(
            "room_id", "utility_type", "period", name="uq_meter_room_type_period"
        ),
        CheckConstraint("reading_value >= 0", name="chk_reading_non_negative"),
        Index("ix_meter_property_period", "property_id", "period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    room_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    utility_type: Mapped[str] = mapped_column(String(10), nullable=False)
    period: Mapped[date] = mapped_column(
        Date, nullable=False, comment="Kỳ dạng YYYY-MM-01 (ngày 1 của tháng)"
    )
    reading_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    previous_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # `COALESCE(previous_value, reading_value)` chứ không phải
    # `reading_value - previous_value` thuần: ở kỳ ĐẦU TIÊN `previous_value`
    # là NULL, phép trừ cho NULL → consumption = NULL → vi phạm NOT NULL và
    # cả lô chỉ số tháng đầu bị từ chối. Với COALESCE, kỳ đầu cho
    # consumption = 0 (đúng nghĩa: chưa có kỳ trước thì chưa biết tiêu bao
    # nhiêu, và ta cũng không tính tiền kỳ này).
    consumption: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        Computed("reading_value - COALESCE(previous_value, reading_value)",
                 persisted=True),
    )
    read_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)

    @property
    def is_first_reading(self) -> bool:
        """Kỳ đầu tiên chưa có chỉ số trước → không tính tiền kỳ này."""
        return self.previous_value is None

    def __repr__(self) -> str:
        return f"<MeterReading {self.utility_type} {self.period} = {self.reading_value}>"


# ---------------------------------------------------------------------------
#  Hóa đơn
# ---------------------------------------------------------------------------
class Invoice(Base):
    """
    Hóa đơn tiền phòng của 1 hợp đồng trong 1 kỳ.

    ⭐ UNIQUE (contract_id, period) = chống tạo trùng. Đây là chiếc "chốt"
       quan trọng nhất khi tính tiền hàng loạt: nếu không có nó, bấm nút
       "Tính tiền tháng 10" hai lần là ra 400 hóa đơn thay vì 200.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("contract_id", "period", name="uq_invoice_contract_period"),
        CheckConstraint("total_amount >= 0", name="chk_invoice_total_non_negative"),
        CheckConstraint("paid_amount >= 0", name="chk_invoice_paid_non_negative"),
        CheckConstraint("due_date >= period", name="chk_invoice_due_after_period"),
        # Truy vấn báo cáo: doanh thu theo tháng, theo cơ sở, trạng thái
        Index("ix_invoice_property_period", "property_id", "period"),
        Index("ix_invoice_status_due", "status", "due_date"),
        Index("ix_invoice_room_period", "room_id", "period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_no: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    # Tham chiếu LOGIC sang db_contract — cố ý KHÔNG có ForeignKey
    contract_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    room_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    tenant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    room_number: Mapped[str | None] = mapped_column(String(20))

    period: Mapped[date] = mapped_column(Date, nullable=False)

    # ---- 7 khoản tiền, tách cột thay vì 1 cột JSON ----
    # Vì sao không gộp thành `items JSON`? Vì báo cáo cần CỘNG theo từng
    # khoản theo tháng (`SUM(electric_amount) WHERE period BETWEEN ...`).
    # Cột riêng thì PostgreSQL dùng được index và SUM trong một lần quét;
    # JSON thì phải `jsonb_each` — chậm hơn nhiều và không index được.
    rent_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)
    electric_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)
    water_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)
    service_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)
    late_fee_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)
    deposit_deducted: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)

    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)
    status: Mapped[str] = mapped_column(
        String(20), default=InvoiceStatus.PENDING.value, nullable=False, index=True
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Khoá chống tính lại: job thất lạc chạy lại sẽ bỏ qua hóa đơn này
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)

    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    details: Mapped[list[InvoiceDetail]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan",
        lazy="noload", order_by="Payment.received_at",
    )

    @property
    def remaining_amount(self) -> Decimal:
        """Còn phải trả = tổng − đã trả. Không bao giờ âm (trả dư không khuyến nghị)."""
        return max(Decimal("0"), self.total_amount - self.paid_amount)

    @property
    def is_paid(self) -> bool:
        return self.status == InvoiceStatus.PAID.value

    def __repr__(self) -> str:
        return f"<Invoice {self.invoice_no} {self.total_amount} [{self.status}]>"


class InvoiceDetail(Base):
    """
    Dòng chi tiết của hóa đơn — dùng để in.

    Giữ chi tiết riêng thay vì dựng lại từ các cột tổng là CỐ Ý: sau này
    biểu giá thay đổi, ta vẫn in ra ĐÚNG những gì khách đã nhận tháng đó.
    Dựng lại từ công thức hiện tại là cách sai kinh điển.
    """

    __tablename__ = "invoice_details"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 0))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    # Snapshot bậc thang tại thời điểm phát hóa đơn (JSON) — để giải thích
    # "tiền điện tháng này tính thế nào" khi khách hỏi.
    breakdown: Mapped[dict | None] = mapped_column(JSON, default=dict)

    invoice: Mapped[Invoice] = relationship(back_populates="details")

    def __repr__(self) -> str:
        return f"<InvoiceDetail {self.item_type} {self.amount}>"


# ---------------------------------------------------------------------------
#  Thanh toán
# ---------------------------------------------------------------------------
class Payment(Base):
    """
    Lần thanh toán cho một hóa đơn.

    Cho phép trả nhiều lần (trả một phần rồi trả tiếp) — thực tế ở Việt Nam
    rất phổ biến. Trạng thái hóa đơn chuyển `PAID` khi `SUM(payments) >= total`.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_payment_positive"),
        Index("ix_payment_invoice", "invoice_id", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100))
    receipt_no: Mapped[str | None] = mapped_column(String(50))
    received_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped[Invoice] = relationship(back_populates="payments")

    def __repr__(self) -> str:
        return f"<Payment {self.amount} {self.method}>"


# ---------------------------------------------------------------------------
#  Job sinh hóa đơn hàng loạt
# ---------------------------------------------------------------------------
class BillingJob(Base):
    """
    Lần chạy "tính tiền tháng X cho cơ sở Y".

    ⭐ Cần bảng này vì cuối tháng có thể 200 hợp đồng cần tính cùng lúc, và
       người dùng có thể bấm nút nhiều lần. Bảng job giúp:
         - trả về cùng 1 job cũ khi bấm lần 2 (idempotent ở tầng UI)
         - theo dõi tiến độ để hiển thị thanh tiến trình
         - xác định hóa đơn nào đã sinh để không sinh lại
    """

    __tablename__ = "billing_jobs"
    __table_args__ = (
        UniqueConstraint("property_id", "period", name="uq_billing_job_property_period"),
        Index("ix_billing_job_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    total_contracts: Mapped[int] = mapped_column(SmallInteger, default=0)
    processed: Mapped[int] = mapped_column(SmallInteger, default=0)
    succeeded: Mapped[int] = mapped_column(SmallInteger, default=0)
    failed: Mapped[int] = mapped_column(SmallInteger, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    # Xoá job cũ sau N ngày — bảng này chỉ để theo dõi, không phải dữ liệu
    # tài chính, nên không cần giữ vĩnh viễn.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @property
    def progress(self) -> float:
        total = self.total_contracts or 0
        return round(self.processed / total * 100, 1) if total else 0.0

    def __repr__(self) -> str:
        return f"<BillingJob {self.period} {self.processed}/{self.total_contracts}>"


__all__ = [
    "BillingJob",
    "Invoice",
    "InvoiceDetail",
    "InvoiceStatus",
    "ItemType",
    "MeterReading",
    "Payment",
    "PaymentMethod",
    "PriceTier",
    "ServiceFee",
    "UtilityType",
]
