"""
tenant-service — Hồ sơ người thuê.  Cổng 8003  |  db_tenant

================================================================================
VÌ SAO SERVICE NÀY TÁCH RIÊNG, KHÔNG GỘP VÀO CONTRACT?
================================================================================
Người thuê là THỰC THỂ có vòng đời riêng: một người thuê ở nhà trọ A năm 2025,
sang nhà trọ B năm 2026 — vẫn là cùng một hồ sơ (cùng CCCD, cùng lịch sử).
Hợp đồng thì chỉ là MỘT mốc quan hệ giữa người thuê và phòng.

Gộp chung sẽ tạo ra bảng `contracts` chứa cả thông tin cá nhân, mỗi lần một
người thuê chuyển nhà lại phải nhân bản hồ sơ → dữ liệu trùng lặp và mâu thuẫn.

================================================================================
DỮ LIỆU NHẠY CẢM — CCCD
================================================================================
`id_card_number` là dữ liệu cá nhân theo Nghị định 13/2023/NĐ-CP. Biện pháp:

  1. MÃ HÓA AES-256-GCM ở tầng ứng dụng (common/crypto.py), KHÔNG lưu plaintext.
  2. BLIND INDEX (HMAC) cho phép tìm "trùng CCCD" mà vẫn dùng được index.
  3. Mặc định trả về đã CHE (*******678); endpoint riêng `/id-card` mới trả
     đầy đủ, và endpoint đó kiểm tra quyền + ghi audit log.
  4. Ảnh mặt trước/sau CCCD nằm trên MinIO với bucket riêng, không public.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from common.crypto import blind_index, decrypt, encrypt, mask
from common.database import Base


class Gender(str, Enum):
    MALE = "M"
    FEMALE = "F"
    OTHER = "OTHER"


class TenantStatus(str, Enum):
    """Trạng thái quan hệ với nhà trọ — suy ra từ hợp đồng, không lưu thẳng.

    ⭐ Ở đây chỉ lưu 2 trạng thái độc lập với hợp đồng:
       `is_active` và `risk_level`. Còn "đang thuê ở đâu" thuộc về
       contract-service — tenant-service cập nhật nó qua event.
       Hai nơi cùng quyết định "ai đang thuê" chính là nguồn gốc của
       90% bug dữ liệu trong hệ thống nhiều service.
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RiskLevel(str, Enum):
    LOW = "LOW"          # thuê đều đặn, trả đúng hạn
    MEDIUM = "MEDIUM"    # từng trễ hạn 1–2 lần
    HIGH = "HIGH"        # nợ kéo dài / chuyển nhà nhiều


# ---------------------------------------------------------------------------
#  Tenant
# ---------------------------------------------------------------------------
class Tenant(Base):
    """
    Hồ sơ người thuê.

    ⭐ Vì sao KHÔNG có cột `room_id` hay `contract_id`?
       Vì một người có thể ở nhiều nơi (phòng mới + phòng cũ chưa dọn),
       và quan hệ đó thay đổi theo thời gian. Nếu đặt `room_id` vào bảng này,
       nó chỉ mô tả được đúng 1 khoảnh khắc. Quan hệ đúng nằm ở contract-service.
       Ở đây giữ `current_room_id` như bản sao để tìm kiếm nhanh, cập nhật qua
       event `contract.activated` — và luôn coi là thông tin phụ.
    """

    __tablename__ = "tenants"
    __table_args__ = (
        # Blind index của CCCD: cho phép chặn trùng mà vẫn giữ dữ liệu mã hóa.
        # UNIQUE + NULL cho phép nhiều người không cung cấp CCCD.
        UniqueConstraint("id_card_bidx", name="uq_tenant_id_card"),
        Index("ix_tenant_property_status", "property_id", "is_active"),
        Index("ix_tenant_phone", "phone"),
        CheckConstraint("gender IS NULL OR gender IN ('M','F','OTHER')",
                        name="chk_tenant_gender"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Người thuê thuộc 1 cơ sở. Khi chuyển cơ sở, tạo hồ sơ mới? KHÔNG —
    # xem `previous_property_ids` bên dưới.
    property_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    # Lịch sử các cơ sở từng ở — JSONB dạng mảng, thay vì bảng con,
    # vì dữ liệu nhỏ (<10 phần tử) và chỉ đọc kèm hồ sơ.
    previous_property_ids: Mapped[list | None] = mapped_column(JSON, default=list)

    # ---- Thông tin cá nhân ----
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(10))
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), index=True)
    # `comment=` chứ không phải `description=`: SQLAlchemy 2.0 đã bỏ
    # `description` khỏi `Column`, dùng lại sẽ ném TypeError ngay lúc import.
    # `comment` sinh ra `COMMENT ON COLUMN` trong DDL — mục đích giống hệt:
    # giải thích ý nghĩa cột ngay trong database.
    address: Mapped[str | None] = mapped_column(Text, comment="Quê quán")
    occupation: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)

    # ---- CCCD: MÃ HÓA ----
    # id_card_enc lưu "v1$<base64>" — không bao giờ plaintext
    id_card_enc: Mapped[str | None] = mapped_column(String(255))
    # HMAC của CCCD đã chuẩn hoá — dùng để tra cứu trùng lặp
    id_card_bidx: Mapped[str | None] = mapped_column(String(64))
    # 4 số cuối để HIỂN THỊ (không phải để tra cứu) — chấp nhận được vì
    # 4 số không đủ để định danh một người
    id_card_last4: Mapped[str | None] = mapped_column(String(4))

    # ---- Ảnh CCCD trên MinIO (object key, không phải URL) ----
    id_card_front: Mapped[str | None] = mapped_column(String(255))
    id_card_back: Mapped[str | None] = mapped_column(String(255))

    # ---- Liên hệ khẩn cấp ----
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(15))
    # Zalo OA ID để gửi thông báo (rẻ hơn SMS nhiều lần)
    zalo_oa_id: Mapped[str | None] = mapped_column(String(50))

    # ---- Trạng thái ----
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    risk_level: Mapped[str] = mapped_column(
        String(10), default=RiskLevel.LOW.value, index=True
    )
    risk_note: Mapped[str | None] = mapped_column(Text)

    # Bản sao cục bộ từ contract-service (xem docstring class)
    current_room_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), index=True
    )
    current_contract_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # R7: soft delete — giữ lại vì hợp đồng & hóa đơn tham chiếu tới
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # ---- Hàm tiện ích cho lớp mã hóa ----
    @property
    def id_card_decrypted(self) -> str | None:
        """Giải mã CCCD. CHỈ dùng trong endpoint có kiểm tra quyền."""
        return decrypt(self.id_card_enc)

    @property
    def id_card_masked(self) -> str | None:
        """CCCD đã che — dùng cho mọi response thông thường."""
        if self.id_card_last4:
            return f"********{self.id_card_last4}"
        return mask(self.id_card_decrypted)

    def set_id_card(self, plain: str | None) -> None:
        """
        Gán CCCD (đã mã hóa + sinh blind index).

        Dùng setter thay vì gán thẳng `id_card_enc = ...` ở nhiều nơi:
        nếu ai đó gán trực tiếp, `id_card_bidx` sẽ thành NULL và tra cứu
        trùng lặp âm thầm hỏng — loại bug rất khó phát hiện.
        """
        if not plain:
            self.id_card_enc = None
            self.id_card_bidx = None
            self.id_card_last4 = None
            return
        self.id_card_enc = encrypt(plain)
        self.id_card_bidx = blind_index(plain)
        digits = "".join(c for c in plain if c.isdigit())
        self.id_card_last4 = digits[-4:] if len(digits) >= 4 else None

    def __repr__(self) -> str:
        return f"<Tenant {self.full_name} ({self.phone})>"


# ---------------------------------------------------------------------------
#  Bạn cùng phòng
# ---------------------------------------------------------------------------
class Roommate(Base):
    """
    Bạn cùng phòng — người ở chung nhưng KHÔNG đứng tên hợp đồng.

    ⭐ R1: tối đa 3 người/phòng (2 bạn cùng phòng + 1 chủ hợp đồng).
       Ràng buộc này kiểm ở tầng service (trả lỗi 422 rõ ràng) VÀ
       index phụ trong `contract_roommates` của contract-service —
       vì bản ghi ở 2 service khác nhau, DB không tự biết.

    Vì sao bạn cùng phòng nằm ở tenant-service chứ không phải contract?
       Vì "ai ở cùng phòng với tôi" là câu hỏi mang tính hồ sơ, được trả lời
       cả khi chưa có hợp đồng (khách xem phòng, hỏi "chung phòng với ai").
    """

    __tablename__ = "roommates"
    __table_args__ = (
        # 1 người chỉ được là bạn cùng phòng của 1 phòng tại 1 thời điểm
        Index("ix_roommate_room_phone", "room_id", "phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    # Nếu bạn cùng phòng cũng có hồ sơ đầy đủ thì trỏ tới; nếu là người
    # thuê "vô danh" (chỉ là bạn cùng phòng) thì NULL.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="Người đứng tên chính (chủ hợp đồng)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Roommate {self.full_name} phòng {self.room_id}>"


# ---------------------------------------------------------------------------
#  Lịch sử
# ---------------------------------------------------------------------------
class TenantHistory(Base):
    """
    Nhật ký thay đổi hồ sơ & quá trình thuê.

    ⭐ Bảng này CHỈ GHI THÊM, KHÔNG BAO GIỜ SỬA/XOÁ.
       Là bằng chứng khi có tranh chấp ("anh đã nộp cọc hồi tháng 3"),
       nên thiết kế append-only là bắt buộc, không phải lựa chọn.
    """

    __tablename__ = "tenant_history"
    __table_args__ = (
        Index("ix_history_tenant_time", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    property_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    room_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)

    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    #   MOVED_IN / MOVED_OUT / RENEWED / PROFILE_UPDATED / RISK_CHANGED
    #   / ID_CARD_UPDATED / CONTRACT_TERMINATED / NOTE_ADDED
    event_data: Mapped[dict | None] = mapped_column(JSON)
    # Ai đã ghi (user id trong auth-service)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
