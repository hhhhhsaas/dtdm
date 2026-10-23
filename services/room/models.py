"""
room-service — Danh mục phòng.  Cổng 8002  |  db_room

================================================================================
PHẠM VI SỞ HỮU DỮ LIỆU
================================================================================
Service này là nguồn duy nhất (single source of truth) cho: cơ sở nhà trọ,
tòa nhà, phòng, tiện ích. Không service nào khác được tự tạo bảng `rooms` của riêng
mình — nếu billing-service cũng có bảng phòng thì sẽ có 2 nơi quyết định
"phòng này còn trống không", và chúng sẽ mâu thuẫn.

================================================================================
BA NGUỒN THAY ĐỔI TRẠNG THÁI PHÒNG
================================================================================
  1. Người quản lý đổi tay (PATCH /rooms/{id}/status)  — trường hợp thủ công
  2. contract-service phát `contract.activated`        — có người vào ở
  3. contract-service phát `contract.terminated`       — người trả phòng
  4. maintenance-service phát `incident.urgent`         — hư hỏng nghiêm trọng

Không có service nào gọi REST để đổi trạng thái phòng của nhau. Tất cả đi qua
event. Lý do: gọi REST đồng bộ tạo ra phụ thuộc runtime — contract-service chết
thì không kích hoạt được hợp đồng; và nếu HTTP call thành công nhưng response bị
mất, contract-service không biết đã thay trạng thái hay chưa → sập. Với event
thì lỗi được xử lý bằng outbox + DLQ, không mất gì.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


# ---------------------------------------------------------------------------
#  Enum trạng thái phòng
# ---------------------------------------------------------------------------
class RoomStatus(str, Enum):
    """
    Vòng đời phòng (xem state diagram ở docs/02 mục 2.3.2).

        AVAILABLE ──có hợp đồng ACTIVE──> OCCUPIED
        OCCUPIED  ──hợp đồng kết thúc───> AVAILABLE
        *         ──báo hư nghiêm trọng──> MAINTENANCE
        MAINTENANCE ──xong bảo trì──────> AVAILABLE
    """

    AVAILABLE = "AVAILABLE"        # trống, sẵn sàng cho thuê
    OCCUPIED = "OCCUPIED"          # đang có người thuê
    MAINTENANCE = "MAINTENANCE"    # đang bảo trì / hư — tạm không khai thác
    RESERVED = "RESERVED"          # đã giữ chỗ, sẽ có người trong ngày tới

    @property
    def is_rentable(self) -> bool:
        """Có thể nhận người thuê mới không?"""
        return self is RoomStatus.AVAILABLE


# ---------------------------------------------------------------------------
#  Bảng nối nhiều-nhiều: phòng ↔ tiện ích
# ---------------------------------------------------------------------------
# Dùng `Table` (không phải class) vì đây là bảng trung gian thuần: không có
# cột nghiệp vụ riêng ngoài khoá, không cần model class.
room_amenities = Table(
    "room_amenities",
    Base.metadata,
    Column("room_id", PGUUID(as_uuid=True),
           ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column("amenity_id", PGUUID(as_uuid=True),
           ForeignKey("amenities.id", ondelete="CASCADE"), primary_key=True),
    # Đánh dấu tiện ích này có thu tiền tháng hay không, tại thời điểm gắn
    # vào phòng. Nhờ vậy billing tính đúng kể cả khi admin sau này đổi giá.
    Column("is_billable", Boolean, default=True, server_default="true"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


# ---------------------------------------------------------------------------
#  Cơ sở nhà trọ
# ---------------------------------------------------------------------------
class Property(Base):
    """
    Một địa chỉ nhà trọ do 1 chủ sở hữu vận hành.

    ⭐ `id` của property là TRỤC CỘT của toàn hệ thống phân quyền:
       mọi bảng nghiệp vụ đều mang `property_id`, và token JWT của MANAGER
       chứa đúng 1 `property_id`. Xem `CurrentUser.assert_property_access()`.
    """

    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(15))
    # Thông tin pháp lý — cần cho hợp đồng & báo cáo thuế
    tax_code: Mapped[str | None] = mapped_column(String(20))

    # Toàn cảnh vận hành, chỉ phục vụ hiển thị
    total_rooms: Mapped[int] = mapped_column(SmallInteger, default=0)
    description: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ⭐ Không cascade xoá từ cơ sở xuống tòa/phòng (DB: ON DELETE RESTRICT).
    #    Cơ sở chỉ xoá mềm; xoá cứng một cơ sở còn phòng/tòa phải bị chặn, vì
    #    phòng là đích tham chiếu của hợp đồng, hóa đơn ở DB khác.
    buildings: Mapped[list[Building]] = relationship(
        back_populates="property", cascade="save-update, merge",
        passive_deletes="all", lazy="selectin"
    )
    rooms: Mapped[list[Room]] = relationship(
        back_populates="property", cascade="save-update, merge", passive_deletes="all",
        lazy="noload", foreign_keys="Room.property_id",
    )

    def __repr__(self) -> str:
        return f"<Property {self.name}>"


# ---------------------------------------------------------------------------
#  Tòa nhà / dãy phòng
# ---------------------------------------------------------------------------
class Building(Base):
    """
    Tòa nhà hoặc dãy phòng trong một cơ sở.

    ⭐ Mô hình "dãy trọ" rất phổ biến ở Việt Nam: nhà trọ có A, B, C, D…
       Nhờ có tầng trung gian này, cùng một số phòng "101" ở 2 tòa nhà khác
       nhau vẫn phân biệt được. Nếu bỏ, phải dùng `room_number` toàn cục.
    """

    __tablename__ = "buildings"
    __table_args__ = (
        UniqueConstraint("property_id", "name", name="uq_building_property_name"),
        # Đích cho khoá ngoại kép rooms(building_id, property_id).
        UniqueConstraint("id", "property_id", name="uq_building_id_property"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("properties.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    property: Mapped[Property] = relationship(back_populates="buildings")
    rooms: Mapped[list[Room]] = relationship(
        back_populates="building", cascade="save-update, merge", passive_deletes="all",
        lazy="noload", foreign_keys="Room.building_id",
    )


# ---------------------------------------------------------------------------
#  Cờ trạng thái phòng — TÁCH RA NGOÀI `Room`
# ---------------------------------------------------------------------------
class RoomFlags:
    """
    Các thuộc tính tính toán của phòng.

    ⭐ VÌ SAO KHÔNG ĐỂ TRỰC TIẾP TRONG `class Room`?
        Bên trong thân một class, tên biến ghi đè được tên đã có. `Room` có
        quan hệ tên là `property` (`property: Mapped[Property] = relationship`),
        nên ngay từ dòng đó `property` trong thân class đã trỏ tới đối tượng
        relationship thay vì hàm dựng decorator của Python. Khi đó
        `@property` ở dưới sẽ gọi `_RelationshipDeclared` →

            TypeError: '_RelationshipDeclared' object is not callable

        Tách ra mixin là cách sạch: đặt quan hệ `property` và các thuộc
        tính tính toán ở 2 class khác nhau, không giao nhau. (Cách "lười"
        hơn là đặt `@property` TRƯỚC dòng relationship — chạy được, nhưng ai
        sau này thêm 1 dòng vào giữa là hỏng, và lỗi thì rất khó hiểu.)
    """

    @property
    def is_occupied(self) -> bool:
        return self.status == RoomStatus.OCCUPIED.value

    @property
    def is_rentable(self) -> bool:
        return self.status == RoomStatus.AVAILABLE.value

    @property
    def is_reserved(self) -> bool:
        """Phòng đang bị GIỮ trong lúc Saga "nhận phòng" chạy."""
        return self.status == RoomStatus.RESERVED.value


# ---------------------------------------------------------------------------
#  Phòng
# ---------------------------------------------------------------------------
class Room(RoomFlags, Base):
    """
    Phòng cho thuê — thực thể vật lý, nằm giữa vòng đời hợp đồng.

    ⭐ CHỐNG TRÙNG LẶP: UNIQUE (property_id, building_id, room_number).
       Ràng buộc này ở TẦNG DB, không phải chỉ ở code. Vì sao?
       Hai request tạo phòng trùng số có thể cùng đi qua check-in-Python
       (race condition: cả hai đều SELECT thấy "chưa có" trước khi INSERT).
       Chỉ UNIQUE constraint mới chặn được, và nó trả lỗi 409 rõ ràng.
    """

    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint(
            "property_id", "building_id", "room_number",
            name="uq_room_property_building_number",
        ),
        # ⭐ Khoá ngoại kép: phòng và tòa nhà của nó PHẢI cùng một cơ sở. Trước
        #    đây chỉ code ứng dụng kiểm tra; ai ghi thẳng vào DB vẫn gắn được
        #    phòng của cơ sở A vào tòa nhà của cơ sở B.
        ForeignKeyConstraint(
            ["building_id", "property_id"], ["buildings.id", "buildings.property_id"],
            name="fk_room_building_same_property", ondelete="RESTRICT",
        ),
        # Ràng buộc nghiệp vụ đặt ở DB để không thể bị vòng qua.
        # Tầng DB là "chốt chặn cuối", code chỉ để báo lỗi đẹp hơn.
        CheckConstraint("area_m2 IS NULL OR area_m2 > 0", name="chk_room_area_positive"),
        CheckConstraint("base_price >= 0", name="chk_room_price_non_negative"),
        CheckConstraint("max_occupants BETWEEN 1 AND 10", name="chk_room_max_occupants"),
        # Index phục vụ truy vấn nóng nhất: lọc theo cơ sở + trạng thái.
        # Composite (không tách 2 index riêng) vì luôn đi cùng nhau, và index
        # composite nhỏ hơn tổng của 2 index độc lập.
        Index("ix_room_property_status", "property_id", "status"),
        Index("ix_room_price", "base_price"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("properties.id", ondelete="RESTRICT"), index=True
    )
    building_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="RESTRICT")
    )

    room_number: Mapped[str] = mapped_column(String(20), nullable=False)
    floor: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    # ⭐ Tiền LUÔN LUÔN là Decimal. Float mất chính xác ở số lớn:
    #   0.1 + 0.2 != 0.3 trong IEEE-754 → sai số tích luỹ trên mỗi hóa đơn.
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    max_occupants: Mapped[int] = mapped_column(SmallInteger, default=1)

    status: Mapped[str] = mapped_column(
        String(20), default=RoomStatus.AVAILABLE.value, nullable=False, index=True
    )
    # Bản sao cục bộ của contract-service, cập nhật qua event chứ KHÔNG gọi REST.
    # Hệ quả: CÓ THỂ LỆCH khi event chưa tới. Đó là đánh đổi có chủ đích của
    # eventual consistency — nhưng thay vì im lặng sai, ta luôn kiểm tra
    # lại với contract-service (nguồn chuẩn) trước mọi thao tác nghiệp vụ
    # quan trọng (kích hoạt hợp đồng, tính tiền).
    current_contract_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    note: Mapped[str | None] = mapped_column(Text)
    # Ảnh phòng — danh sách object key trong MinIO
    photos: Mapped[list | None] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # ---- Quan hệ ----
    property: Mapped[Property] = relationship(
        back_populates="rooms", foreign_keys=[property_id]
    )
    building: Mapped[Building] = relationship(back_populates="rooms", foreign_keys=[building_id])
    amenities: Mapped[list[Amenity]] = relationship(
        secondary=room_amenities, lazy="selectin", back_populates="rooms"
    )

    def __repr__(self) -> str:
        return f"<Room {self.room_number} [{self.status}]>"


# ---------------------------------------------------------------------------
#  Tiện ích
# ---------------------------------------------------------------------------
class Amenity(Base):
    """
    Tiện ích (điều hòa, wifi, bếp, máy giặt…).

    ⭐ Danh mục tiện ích là CHUNG toàn hệ thống (bảng không có `property_id`),
       còn mức phí mặc định thì thuộc về cơ sở. Vì sao?
       Nếu mỗi cơ sở tự tạo tiện ích riêng, danh mục sẽ phình to và
       báo cáo "top tiện ích được yêu thích" sẽ gộp "AC" của 20 cơ sở
       thành 20 mục khác nhau — vô nghĩa.
    """

    __tablename__ = "amenities"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50))
    # Phí tháng mặc định (VND). Cơ sở có thể ghi đè bằng bảng `room_amenities`.
    default_monthly_fee: Mapped[Decimal] = mapped_column(Numeric(12, 0), default=0)
    description: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    rooms: Mapped[list[Room]] = relationship(
        secondary=room_amenities, back_populates="amenities", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Amenity {self.code}>"
