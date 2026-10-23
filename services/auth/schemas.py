"""Schema Pydantic của auth-service — hợp đồng API rõ ràng, có validate sẵn."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from common.schemas import MessageResponse  # noqa: F401  (re-export cho main.py)

# Ràng buộc mật khẩu: ít nhất 8 ký tự, có cả chữ và số.
# Không bắt buộc ký tự đặc biệt — nghiên cứu chứng minh độ dài quan trọng
# hơn độ phức tạp (NIST SP 800-63B).
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")
PHONE_PATTERN = re.compile(r"^(0|\+84)\d{8,10}$")

Password = Annotated[str, Field(min_length=8, max_length=128)]
Phone = Annotated[str, Field(pattern=PHONE_PATTERN)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"username": "quanly.truong", "password": "MatKhau@2026"}
        }
    )

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Số giây còn hiệu lực của access token")
    user: UserResponse


class RefreshRequest(BaseModel):
    # None khi web gửi qua cookie HttpOnly (header X-Token-Transport: cookie)
    refresh_token: str | None = Field(default=None, min_length=20)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9._-]+$")
    email: EmailStr
    password: Password
    full_name: str = Field(min_length=2, max_length=100)
    phone: Phone | None = None
    role: Literal["ADMIN", "MANAGER", "TENANT"] = "TENANT"
    property_id: uuid.UUID | None = None
    # Bắt buộc với TENANT: id hồ sơ ở tenant-service (tham chiếu logic)
    tenant_id: uuid.UUID | None = None

    @field_validator("password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        if not PASSWORD_PATTERN.match(v):
            raise ValueError(
                "Mật khẩu phải có ít nhất 8 ký tự, gồm cả chữ cái và chữ số"
            )
        return v

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return " ".join(v.split())


class UserUpdate(BaseModel):
    """Cập nhật người dùng. Không cho đổi username/role qua endpoint này
    (role đổi bằng endpoint riêng có audit log)."""

    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    phone: Phone | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: Password

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        if not PASSWORD_PATTERN.match(v):
            raise ValueError("Mật khẩu mới phải có chữ cái, chữ số, tối thiểu 8 ký tự")
        return v


class RoleAssignment(BaseModel):
    role: Literal["ADMIN", "MANAGER", "TENANT", "SYSTEM"]
    property_id: uuid.UUID | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: EmailStr
    full_name: str
    phone: str | None
    role: str
    property_id: uuid.UUID | None
    tenant_id: uuid.UUID | None = None
    is_active: bool
    is_locked: bool
    last_login_at: datetime | None
    created_at: datetime

    @property
    def permissions(self) -> list[str]:
        return {
            "ADMIN": ["*"],
            "MANAGER": [
                "room:read", "room:write", "tenant:read", "tenant:write",
                "contract:read", "contract:write", "billing:read", "billing:write",
                "maintenance:read", "maintenance:write", "report:read",
            ],
            "TENANT": [
                "own_invoice:read", "own_invoice:pay", "own_contract:read",
                "room_available:read", "incident:create", "incident:read_own",
            ],
            "SYSTEM": ["*"],
        }.get(self.role, [])


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# MessageResponse lấy từ common.schemas để cả 8 service trả về cùng một
# cấu trúc — client chỉ cần viết 1 hàm xử lý thành công / thất bại.
TokenResponse.model_rebuild()
