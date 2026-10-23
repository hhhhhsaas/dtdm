"""
seed_auth — Nạp tài khoản người dùng cho auth-service (db_auth).

    docker compose exec -T auth python -m scripts.seed_auth

Tạo:
  - 1 ADMIN      : toàn quyền, quản nhiều cơ sở (property_id = NULL)
  - 1 MANAGER    : quản lý trọ, CHỈ thấy đúng cơ sở Minh Khai
  - 12 TENANT    : tài khoản `khach01`…`khach12` cho 12 người thuê (dùng để
                   demo góc nhìn "hộp thư của tôi" và các báo cáo theoten)

⭐ KHÔNG tạo tài khoản `SYSTEM`:
  Token service-to-service (role=SYSTEM) do `common.security.create_internal_token()`
  phát ra, với `sub = uuid5(NAMESPACE_DNS, "qlpt-service.<tên>")` — không liên
  quan gì tới bảng `users`. Tạo 1 user SYSTEM trong DB chỉ khiến người đọc
  tưởng rằng hệ thống có thể "đăng nhập bằng quyền SYSTEM" — một con đường
  tấn công không tồn tại. Các bản ghi seed cần `created_by`/`read_by`/`received_by`
  sẽ trỏ về ADMIN_ID hoặc MANAGER_ID.

⭐ Mật khẩu mẫu: đọc từ `secrets/admin_password.txt` nếu có, không thì dùng
   `Admin@12345`. Với tài khoản demo, việc đặt mật khẩu yếu là chấp nhận
   được — nhưng file `.env.example` đã mặc định `NOTIFICATION_DRY_RUN=true`
   và `make check` chặn deploy thiếu secret, nên kịch bản "chạy demo rồi quên
   đổi mật khẩu" vẫn bị chặn ở bước trước.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from common.security import hash_password
from models import Role, User
from scripts._seed_common import (
    ADMIN_ID,
    MANAGER_ID,
    PROPERTY_ID,
    TENANT_IDS,
    TENANT_NAMES,
)

#: Mật khẩu mặc định khi CHƯA có secret (máy dev mới).
DEFAULT_PASSWORD = "Admin@12345"
#: ⭐ Mật khẩu người thuê mẫu lấy từ secret tenant_demo_password, KHÔNG viết
#:   cứng trong code nữa: chuỗi "Tenant@12345" nằm trong repo công khai và
#:   trong file dump, nên 12 tài khoản mẫu thực chất ai cũng đăng nhập được.
DEFAULT_TENANT_PASSWORD = "Tenant@12345"

#: Tên file secret giống hệt cách `common/config.py` đọc (LOCAL_SECRETS_DIR).
_SECRETS_DIR = Path("/run/secrets")
_FALLBACK_DIR = Path(__file__).resolve().parents[2] / "secrets"


def _read_secret_or(name: str, default: str) -> str:
    """Đọc secret theo tên; thiếu thì dùng mặc định (chỉ hợp lý trên máy dev)."""
    # Compose mount secret theo TÊN KEY (admin_password); file nguồn có .txt —
    # thử cả 2 quy ước (cùng cách common/config.read_secret).
    for base in (_SECRETS_DIR, _FALLBACK_DIR):
        for cand in (name, name + ".txt"):
            path = base / cand
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
    return default


def _read_admin_password() -> str:
    return _read_secret_or("admin_password", DEFAULT_PASSWORD)


async def seed(session: AsyncSession) -> dict:
    now = datetime.now(UTC)
    admin_pwd = _read_admin_password()
    tenant_pwd = _read_secret_or("tenant_demo_password", DEFAULT_TENANT_PASSWORD)
    created = 0

    async def put(user_id, username, email, full_name, phone, role, password,
                  property_id, tenant_id=None) -> None:
        nonlocal created
        existing = await session.get(User, user_id)
        if existing is None:
            session.add(User(
                id=user_id,
                username=username,
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                phone=phone,
                role=role,
                property_id=property_id,
                tenant_id=tenant_id,
                is_active=True,
                password_changed_at=now,
            ))
            created += 1
        else:
            # ⭐ Không băm lại mật khẩu khi đã tồn tại: Argon2id cố ý chậm
            #    (~100ms/lần), chạy seed cho 12 user mỗi lần sẽ tốn hơn 1s
            #    vô nghĩa. Đổi mật khẩu thì dùng API `PUT /api/v1/auth/password`.
            existing.full_name = full_name
            existing.email = email
            existing.phone = phone
            existing.role = role
            existing.property_id = property_id
            existing.tenant_id = tenant_id
            existing.is_active = True
            existing.deleted_at = None

    # --- Quản trị viên: property_id = NULL nghĩa là không bị ràng buộc cơ sở ---
    await put(
        ADMIN_ID, "admin", "admin@example.com", "Quản trị viên",
        "0900000000", Role.ADMIN.value, admin_pwd, None,
    )
    # --- Quản lý trọ: bị ràng buộc đúng 1 cơ sở ---
    await put(
        MANAGER_ID, "quanly", "quanly@example.com", "Nguyễn Quản Lý",
        "0900000001", Role.MANAGER.value, admin_pwd, PROPERTY_ID,
    )

    for i, (full_name, phone, email) in enumerate(TENANT_NAMES, start=1):
        await put(
            TENANT_IDS[i - 1], f"khach{i:02d}", email, full_name, phone,
            Role.TENANT.value, tenant_pwd, PROPERTY_ID,
            tenant_id=TENANT_IDS[i - 1],
        )

    # Tài khoản kỹ thuật cho các job nền — KHÔNG tạo ở đây, xem docstring.

    await session.flush()
    return {
        "tai_khoan_moi": created,
        "tong_tai_khoan": len(TENANT_NAMES) + 2,   # 1 admin + 1 manager + 12 tenant
        "mat_khau_admin": "theo secrets/admin_password.txt" if admin_pwd != DEFAULT_PASSWORD
                           else f"{DEFAULT_PASSWORD} (mặc định — nên đổi)",
    }


def main() -> int:
    from scripts._seed_common import run_seed

    return asyncio.run(run_seed("auth-service", seed))


if __name__ == "__main__":
    sys.exit(main())
