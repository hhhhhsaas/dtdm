"""
contract-service — Hợp đồng thuê.  Cổng 8004  |  db_contract  *(Core Domain)*

===============================================================================
PHẠM VI SỞ HỮU DỮ LIỆU
===============================================================================
Nguồn duy nhất cho: hợp đồng, tiền cọc, bạn cùng phòng, lịch sử trạng thái.

Hợp đồng là "hợp đồng" theo nghĩa thật của pháp luật — mỗi lần đổi trạng thái
đều phải để lại dấu vết. Vì vậy service này KHÔNG bao giờ xoá hợp đồng, kể cả
hợp đồng bị huỷ: nó chuyển sang CANCELLED và giữ nguyên để đối chiếu.

===============================================================================
BA BẢN SAO — VÌ SAO CÓ, KHÔNG PHẢI ĐỂ LỤC
===============================================================================
  1. `tenants_snapshot`     — chụp lại họ tên/4 số cuối CCCD/điện thoại lúc ký.
  2. `monthly_price` trong `contracts` — KHÔNG tham chiếu `rooms.base_price`.
  3. `deposit_amount`       — ghi rõ bao nhiêu, không suy ra từ lịch sử cọc.

Cả 3 đều là bản sao CỐ Ý. Nếu hợp đồng tham chiếu sang DB khác và người thuê
đổi số điện thoại 2 năm sau, hợp đồng cũ sẽ đổi theo — hợp đồng đã ký mà
nội dung thay đổi là vô hiệu về pháp lý. Bản sao là bản đóng băng tại thời điểm
ký, đúng tinh thần luật.
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
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


# ---------------------------------------------------------------------------
#  Trạng thái hợp đồng
# ---------------------------------------------------------------------------
class ContractStatus(str, Enum):
    """Vòng đời hợp đồng (xem state diagram ở docs/02 mục 2.3.4)."""

    DRAFT = "DRAFT"                  # vừa soạn, chưa gửi
    PENDING_SIGN = "PENDING_SIGN"    # đã gửi người thuê, chờ ký + đặt cọc
    ACTIVE = "ACTIVE"                # đang hiệu lực ← trạng thái duy nhất "có người"
    EXPIRED = "EXPIRED"              # hết hạn tự nhiên
    TERMINATED = "TERMINATED"        # chấm dứt sớm (cần lý do)
    CANCELLED = "CANCELLED"          # huỷ trước khi ký
    RENEWED = "RENEWED"              # đã gia hạn → sinh hợp đồng mới

    @property
    def is_open(self) -> bool:
        """Hợp đồng còn hiệu lực (dùng để lọc danh sách "đang thuê")."""
        return self is ContractStatus.ACTIVE


#: Nguồn → đích hợp lệ. Mọi lối vào đều đi qua bảng này, không có ngoại lệ.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ContractStatus.DRAFT.value: {ContractStatus.PENDING_SIGN.value,
                                ContractStatus.CANCELLED.value},
    ContractStatus.PENDING_SIGN.value: {ContractStatus.ACTIVE.value,
                                       ContractStatus.CANCELLED.value},
    ContractStatus.ACTIVE.value: {ContractStatus.EXPIRED.value,
                                  ContractStatus.TERMINATED.value},
    # Gia hạn KHÔNG sửa hợp đồng cũ mà tạo hợp đồng mới; hợp đồng cũ chuyển
    # sang RENEWED chỉ để dễ tra cứu "lịch sử thuê của phòng này".
    ContractStatus.EXPIRED.value: {ContractStatus.RENEWED.value},
    ContractStatus.TERMINATED.value: {ContractStatus.RENEWED.value},
    # CANCELLED / RENEWED là trạng thái cuối — không đi được đâu nữa.
    ContractStatus.CANCELLED.value: set(),
    ContractStatus.RENEWED.value: set(),
}


# ---------------------------------------------------------------------------
#  Bảng chụp hồ sơ người thuê tại thời điểm ký hợp đồng
# ---------------------------------------------------------------------------
class TenantSnapshot(Base):
    """
    Bản chụp hồ sơ người thuê, đóng băng tại thời điểm ký hợp đồng.

    ⭐ KHÔNG có `ON DELETE CASCADE` tới `db_tenant` — vì không có FK xuyên DB
       (database-per-service). Xoá hồ sơ ở tenant-service KHÔNG được xoá
       bản chụp ở đây: hợp đồng cũ vẫn phải dùng được.
    """

    __tablename__ = "tenants_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Bản chụp thuộc hợp đồng nào (cùng DB → FK thật). Trước đây thiếu cột
    # này nên không truy ngược được bản chụp của hợp đồng nào. NULL chỉ còn ở
    # bản ghi cũ không suy ra được hợp đồng.
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contracts.id", ondelete="RESTRICT"), index=True
    )
    # KHÔNG có ForeignKey — chỉ là tham chiếu logic tới tenant-service.
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # ⭐ Chỉ lưu 4 số cuối CCCD. Số đầy đủ đã được mã hóa AES-256-GCM ở
    #    tenant-service; chép bản rõ sang đây làm mọi công sức mã hóa vô
    #    nghĩa (lấy được db_contract hay bản backup là có CCCD của tất cả).
    id_card_last4: Mapped[str | None] = mapped_column(String(4))
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    email: Mapped[str | None] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<TenantSnapshot {self.full_name}>"


# ---------------------------------------------------------------------------
#  Hợp đồng
# ---------------------------------------------------------------------------
class Contract(Base):
    """
    Hợp đồng thuê phòng.

    ⭐ R2 — "mỗi phòng chỉ 1 hợp đồng ACTIVE" được ép bằng PARTIAL UNIQUE INDEX
       ở tầng DB:
           CREATE UNIQUE INDEX ... ON contracts(room_id) WHERE status='ACTIVE'
       Vì sao phải ở DB? Vì 2 request kích hoạt chạy song song (2 người cùng
       bấm nút) đều SELECT thấy "chưa có hợp đồng ACTIVE" rồi cùng INSERT.
       Check bằng `if` trong Python KHÔNG chặn được. Partial unique index thì
       có: database trả lỗi unique_violation và `errors.py` dịch thành 409.
    """

    __tablename__ = "contracts"
    __table_args__ = (
        CheckConstraint("end_date > start_date", name="chk_contract_date_order"),
        CheckConstraint("monthly_price >= 0", name="chk_contract_price_non_negative"),
        CheckConstraint("deposit_amount >= 0", name="chk_contract_deposit_non_negative"),
        # R3: không bao giờ được trừ quá số cọc đã đặt.
        CheckConstraint(
            "deposit_deducted >= 0 AND deposit_deducted <= deposit_amount",
            name="chk_contract_deposit_not_over_used",
        ),
        # ⭐ Partial unique index = R2 ở tầng DB.
        Index(
            "uq_contract_active_room",
            "room_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        # Truy vấn nóng: "phòng này có hợp đồng nào đang chạy"
        Index("ix_contract_room_status", "room_id", "status"),
        # Báo cáo doanh thu/người thuê: lọc theo khoảng ngày
        Index("ix_contract_dates", "start_date", "end_date"),
        Index("ix_contract_property_status", "property_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    contract_no: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )

    property_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    room_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    # R1 — người đứng tên chính, là chủ hợp đồng
    primary_tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    primary_tenant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    primary_tenant_phone: Mapped[str] = mapped_column(String(15), nullable=False)
    primary_tenant_email: Mapped[str | None] = mapped_column(String(150))

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Bản sao giá tại thời điểm ký — KHÔNG đọc từ rooms.base_price
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    deposit_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 0), default=0, nullable=False
    )
    deposit_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # R3 — đã trừ dần khỏi cọc vào các hóa đơn trước
    deposit_deducted: Mapped[Decimal] = mapped_column(
        Numeric(12, 0), default=0, nullable=False
    )

    payment_cycle: Mapped[str] = mapped_column(String(20), default="MONTHLY", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ContractStatus.DRAFT.value, nullable=False, index=True
    )
    terminated_reason: Mapped[str | None] = mapped_column(Text)
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Hợp đồng mà hợp đồng này gia hạn từ đó (null nếu hợp đồng đầu tiên)
    renewed_from_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    renewed_to_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    # Điều khoản riêng của cơ sở (kiểu biểu, quy định bãi xe…)
    terms: Mapped[dict | None] = mapped_column(JSON, default=dict)
    # `comment=` (không phải `description=`) — SQLAlchemy 2.0 bỏ `description`
    # khỏi `Column`. Xem giải thích ở `tenant/models.py`.
    document_key: Mapped[str | None] = mapped_column(
        String(255), comment="Object key file hợp đồng PDF trong MinIO"
    )

    created_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ---- Quan hệ ----
    roommates: Mapped[list[ContractRoommate]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list[ContractPayment]] = relationship(
        back_populates="contract",
        # Phiếu thu cọc là chứng từ: không xoá theo hợp đồng (DB: ON DELETE RESTRICT).
        cascade="save-update, merge",
        passive_deletes="all",
        lazy="noload",
        order_by="ContractPayment.paid_at",
    )

    # ---- Thuộc tính nghiệp vụ ----
    @property
    def remaining_deposit(self) -> Decimal:
        """
        Tiền cọc còn lại. Đây là hàm DUY NHẤT được phép tính số cọc còn lại.

        R3 được ép ở 2 nơi: `CheckConstraint` ở DB (chặn `deposit_deducted >
        deposit_amount`) và hàm này (chặn logic). Cả hai đều cần — constraint bảo
        vệ tính toàn vẹn dữ liệu, hàm bảo vệ tính đúng của nghiệp vụ.
        """
        return max(Decimal("0"), self.deposit_amount - self.deposit_deducted)

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days

    @property
    def is_active(self) -> bool:
        return self.status == ContractStatus.ACTIVE.value

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in ALLOWED_TRANSITIONS.get(self.status, set())

    def __repr__(self) -> str:
        return f"<Contract {self.contract_no} [{self.status}]>"


# ---------------------------------------------------------------------------
#  Bạn cùng phòng
# ---------------------------------------------------------------------------
class ContractRoommate(Base):
    """
    Bạn cùng phòng ký chung hợp đồng.

    ⭐ R1 — tối đa 3 người/phòng (1 chủ + 2 bạn). Kiểm tra ở tầng ứng dụng
       (`main.py`) chứ không ở DB, vì giới hạn này phụ thuộc `max_occupants`
       của phòng — thứ nằm ở DB khác.
    """

    __tablename__ = "contract_roommates"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    # null = người thuê chưa có tài khoản (chỉ ghi tạm để ký giấy tay)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    # Chỉ 4 số cuối — xem giải thích ở TenantSnapshot.id_card_last4.
    id_card_last4: Mapped[str | None] = mapped_column(String(4))
    # Người ký là người bảo lãnh tiền cọc chung, không thì ai chịu trách nhiệm?
    is_guarantor: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    contract: Mapped[Contract] = relationship(back_populates="roommates")

    def __repr__(self) -> str:
        return f"<Roommate {self.full_name}>"


# ---------------------------------------------------------------------------
#  Lịch sử thanh toán tiền cọc
# ---------------------------------------------------------------------------
class ContractPayment(Base):
    """
    Ghi nhận tiền cọc đã thu.

    Append-only: không sửa, không xoá. Nếu nhận nhầm số tiền thì tạo bản ghi
    điều chỉnh âm, giữ nguyên bản ghi cũ — giống hạch toán kế toán.
    """

    __tablename__ = "contract_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_contract_payment_positive"),
        Index("ix_contract_payment_contract", "contract_id", "paid_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contracts.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)   # CASH/BANK_TRANSFER/MOMO
    receipt_no: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    received_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    contract: Mapped[Contract] = relationship(back_populates="payments")

    def __repr__(self) -> str:
        return f"<ContractPayment {self.amount} {self.method}>"


__all__ = [
    "ALLOWED_TRANSITIONS",
    "Contract",
    "ContractPayment",
    "ContractRoommate",
    "ContractStatus",
    "TenantSnapshot",
]
