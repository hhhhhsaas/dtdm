"""
Mô hình dữ liệu của auth-service (db_auth).

Bảng ở đây chỉ liên quan đến DANH TÍCH. auth-service KHÔNG biết gì về
phòng, hợp đồng, hóa đơn — đó là ranh giới của service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


class Role(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    TENANT = "TENANT"
    SYSTEM = "SYSTEM"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # ⭐ UNIQUE chỉ trên tài khoản CHƯA xoá mềm. UNIQUE toàn bảng khiến
        #    username/email của tài khoản đã xoá bị chiếm vĩnh viễn.
        Index("uq_users_username_live", "username", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("uq_users_email_live", "email", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        # Một hồ sơ người thuê chỉ gắn với tối đa 1 tài khoản đang dùng.
        Index("uq_users_tenant_live", "tenant_id", unique=True,
              postgresql_where=text("tenant_id IS NOT NULL AND deleted_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    # Argon2id hash — KHÔNG BAO GIỜ lưu mật khẩu gốc
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(15))
    role: Mapped[str] = mapped_column(String(20), default=Role.TENANT.value, index=True)

    # ⭐ Ràng buộc multi-tenant: MANAGER chỉ thấy đúng cơ sở này.
    # NULL = quản trị nhiều cơ sở (ADMIN).
    property_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    # ⭐ Liên kết tài khoản TENANT ↔ hồ sơ ở tenant-service (tham chiếu logic,
    # không FK vì khác DB). Trước đây chỉ dựa vào quy ước "trùng UUID", nên
    # người thuê tạo qua API không có cách nào đăng nhập xem hóa đơn của mình.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # R7: soft delete — giữ dữ liệu để truy vết
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value

    @property
    def can_manage(self) -> bool:
        return self.role in (Role.ADMIN.value, Role.MANAGER.value)

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


class RefreshToken(Base):
    """
    Refresh token lưu dạng HASH.

    ⭐ Nếu DB bị lấy, attacker chỉ thấy hash SHA-256, không dùng được để
    đăng nhập. Đây là yêu cầu bắt buộc (OWASP).

    Lưu thêm user_agent + ip để phát hiện đăng nhập bất thường.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_valid(self) -> bool:
        return (
            self.revoked_at is None
            and self.expires_at > datetime.now(UTC)
        )


class LoginAttempt(Base):
    """
    Nhật ký đăng nhập — dùng phát hiện brute-force và điều tra sự cố.

    Ghi MỌI lần thử (thành công lẫn thất bại). Giữ 90 ngày.
    """

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    username_attempted: Mapped[str] = mapped_column(String(50), index=True)
    ip_address: Mapped[str] = mapped_column(String(45), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    success: Mapped[bool] = mapped_column(Boolean, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AuditLog(Base):
    """
    Nhật ký thao tác quản trị (R6: mọi thao tác ghi dữ liệu đều có audit log).

    Ghi vào DB riêng thay vì ghi file: truy vấn được bằng SQL, không cần
    parse log file, và không bị mất khi xoay vòng log.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    actor_username: Mapped[str | None] = mapped_column(String(50))
    actor_role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(100))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    request_id: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
