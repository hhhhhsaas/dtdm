"""
seed_contract — Hợp đồng thuê cho contract-service (db_contract).

    docker compose exec -T contract python -m scripts.seed_contract

Tạo 11 hợp đồng theo CONTRACT_LAYOUT (xem _seed_common):
  - 9 ACTIVE   (trong đó 2 hợp đồng đang "sắp hết hạn" T-5 ngày và T-25 ngày
                để job cảnh báo của scheduler có việc làm ngay sau seed)
  - 1 EXPIRED  (hết hạn tự nhiên ~45 ngày trước)
  - 1 DRAFT    (mới soạn, chưa ký, chưa thu cọc)
kèm:
  - TenantSnapshot : 10 bản chụp hồ sơ khi ký (tài liệu pháp lý, lưu CCCD
                     plaintext theo đúng thiết kế "bản chụp đóng băng")
  - ContractRoommate : 2 bạn cùng phòng ký chung
  - ContractPayment  : 10 lần thu tiền cọc (append-only)

⭐ Hợp đồng là TÀI LIỆU PHÁP LÝ: không bao giờ xoá, chỉ chuyển trạng thái.
   Seed này chạy lại bao lần cũng chỉ nâng cấp bản ghi cũ (upsert), không tạo
   bản sao — nên `make seed` 10 lần vẫn ra đúng 11 hợp đồng.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Contract,
    ContractPayment,
    ContractRoommate,
    TenantSnapshot,
)
from scripts._seed_common import (
    ADMIN_ID,
    CONTRACT_IDS,
    CONTRACT_LAYOUT,
    DEPOSIT_USED,
    MANAGER_ID,
    PROPERTY_ID,
    ROOM_PRICES,
    TENANT_IDCARDS,
    TENANT_IDS,
    TENANT_NAMES,
    TENANT_PROFILES,
    TODAY,
    uid,
    upsert,
)

#: Múi giờ của trọ — mọi mốc thời gian nghiệp vụ trong hệ thống đều theo đây
TZ = ZoneInfo("Asia/Ho_Chi_Minh")

#: Điều khoản chung — đủ để màn hình xem hợp đồng hiển thị được nội dung
TERMS: dict = {
    "thanh_toan": "Tiền phòng trả theo tháng, chậm nhất ngày 5",
    "notice_days": 30,
    "rules": [
        "Không nuôi chó mèo khi chưa được chủ trọ đồng ý",
        "Giữ gìn vệ sinh chung, không gây ồn sau 22h",
        "Đóng đủ tiền điện nước theo chỉ số đồng hồ cuối tháng",
    ],
}

METHODS = ("CASH", "BANK_TRANSFER", "MOMO")


def _local(d: datetime) -> datetime:
    """Gắn múi giờ Việt Nam cho datetime — có timezone an toàn để lưu."""
    return d.replace(tzinfo=TZ)


def _activated_at(start) -> datetime:
    """Mốc "kích hoạt": 09:00 ngày thứ 3 sau ngày bắt đầu (chờ ký + nhận phòng)."""
    return datetime.combine(start + timedelta(days=2), time(9, 0), tzinfo=TZ)


async def seed(session: AsyncSession) -> dict:
    deposits = roommates = snapshots = 0

    for cx, tx, room_no, status, days in CONTRACT_LAYOUT:
        contract_id = CONTRACT_IDS[cx - 1]
        tenant_id = TENANT_IDS[tx - 1]
        full_name, phone, email = TENANT_NAMES[tx - 1]
        monthly = Decimal(ROOM_PRICES[room_no])

        # ---- Chốt ngày theo trạng thái (xem docstring CONTRACT_LAYOUT) ----
        if status == "DRAFT":
            start, end = TODAY, TODAY + timedelta(days=365)
        elif status == "ACTIVE":
            end = TODAY + timedelta(days=days)          # days ≥ 0: còn N ngày
            start = end - timedelta(days=365)           # thuê trọn 1 năm
        else:                                           # EXPIRED
            end = TODAY + timedelta(days=days)          # days < 0: đã hết N ngày
            start = end - timedelta(days=366)

        activated = _activated_at(start) if status in ("ACTIVE", "EXPIRED") else None

        await upsert(session, Contract, "id", {
            "id": contract_id,
            "contract_no": f"HDMB-{TODAY.year}-{cx:03d}",
            "property_id": PROPERTY_ID,
            "room_id": uid("room", room_no),
            "primary_tenant_id": tenant_id,
            "primary_tenant_name": full_name,
            "primary_tenant_phone": phone,
            "primary_tenant_email": email,
            "start_date": start,
            "end_date": end,
            "monthly_price": monthly,
            "deposit_amount": monthly,                   # cọc 1 tháng tiền phòng
            "deposit_paid_at": activated,                # đóng cọc khi nhận phòng
            "deposit_deducted": Decimal(DEPOSIT_USED.get(cx, "0")),
            "payment_cycle": "MONTHLY",
            "status": status,
            "terminated_reason": None,
            "terminated_at": None,
            "renewed_from_id": None,
            "renewed_to_id": None,
            "terms": TERMS,
            "document_key": None,
            "created_by": ADMIN_ID,
            "activated_at": activated,
        })

        # ---- Bản chụp hồ sơ tại thời điểm ký (KHÔNG tạo cho DRAFT: chưa ký) --
        if status != "DRAFT":
            await upsert(session, TenantSnapshot, "id", {
                "id": uid("snapshot", f"HDMB-{TODAY.year}-{cx:03d}"),
                "contract_id": contract_id,
                "tenant_id": tenant_id,
                "full_name": full_name,
                "id_card_last4": TENANT_IDCARDS[tx - 1][-4:],
                "phone": phone,
                "email": email,
                "address": f"{TENANT_PROFILES[tx - 1][0]}, Việt Nam",
            })
            snapshots += 1

        # ---- Thu tiền cọc — append-only (không tạo cho hợp đồng DRAFT) ----
        if status != "DRAFT":
            await upsert(session, ContractPayment, "id", {
                "id": uid("payment-deposit", f"HDMB-{TODAY.year}-{cx:03d}"),
                "contract_id": contract_id,
                "amount": monthly,
                "method": METHODS[cx % 3],
                "receipt_no": f"PT-{TODAY.year}-{cx:02d}",
                "note": "Tiền cọc 1 tháng",
                "received_by": MANAGER_ID if cx % 2 == 0 else ADMIN_ID,
                "paid_at": activated,
            })
            deposits += 1

    # ---- Bạn cùng phòng ký chung (1 người có hồ sơ, 1 người ghi tay) ----
    for cx, phone, name, ref_tenant, guarantor in (
        (6, "0901000012", "Lý Thu Hà", TENANT_IDS[11], False),
        (2, "0968111222", "Trần Văn Bảo", None, False),
    ):
        await upsert(session, ContractRoommate, "id", {
            "id": uid("croommate", f"HDMB-{TODAY.year}-{cx:03d}", phone),
            "contract_id": CONTRACT_IDS[cx - 1],
            "tenant_id": ref_tenant,
            "full_name": name,
            "phone": phone,
            "id_card_last4": None,
            "is_guarantor": guarantor,
        })
        roommates += 1

    await session.flush()
    return {
        "hop_dong": len(CONTRACT_LAYOUT),
        "dang_hieu_luc": sum(1 for r in CONTRACT_LAYOUT if r[3] == "ACTIVE"),
        "da_het_han": sum(1 for r in CONTRACT_LAYOUT if r[3] == "EXPIRED"),
        "dang_soan": sum(1 for r in CONTRACT_LAYOUT if r[3] == "DRAFT"),
        "ban_chup": snapshots,
        "thu_coc": deposits,
        "ban_cung_phong": roommates,
    }


def main() -> int:
    from scripts._seed_common import run_seed

    return asyncio.run(run_seed("contract-service", seed))


if __name__ == "__main__":
    sys.exit(main())
