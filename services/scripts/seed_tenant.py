"""
seed_tenant — Hồ sơ người thuê cho tenant-service (db_tenant).

    docker compose exec -T tenant python -m scripts.seed_tenant

Tạo:
  - 12 Tenant     : hồ sơ cá nhân + CCCD MÃ HÓA AES-256-GCM (set_id_card)
  - Roommate      : 2 bạn cùng phòng (1 có hồ sơ, 1 «vô danh» chỉ ở chung)
  - TenantHistory : nhật ký append-only (MOVED_IN / MOVED_OUT / RISK_CHANGED …)

⭐ MỐI QUAN HỆ "ai đang ở đâu" có NGUỒN CHUẨN là contract-service, bảng này
   chỉ giữ bản sao `current_room_id` / `current_contract_id` để tìm nhanh —
   đặt theo CONTRACT_LAYOUT y hệt seed_contract, nên 2 DB không mâu thuẫn.
   Người thuê #10 đã trả phòng (hợp đồng EXPIRED) → bản sao được xoá,
   người thuê #11 (hợp đồng DRAFT) & #12 (chưa có hợp đồng) → chưa có phòng.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Roommate, Tenant, TenantHistory
from scripts._seed_common import (
    ADMIN_ID,
    CONTRACT_IDS,
    CONTRACT_LAYOUT,
    PROPERTY_ID,
    TENANT_IDCARDS,
    TENANT_IDS,
    TENANT_NAMES,
    TENANT_PROFILES,
    uid,
    upsert,
)

#: Chỉ số người thuê nào đang có hợp đồng ACTIVE → (phòng, id_hợp_đồng)
ACTIVE_BY_TENANT: dict[int, tuple[str, uuid.UUID]] = {
    row[1]: (row[2], CONTRACT_IDS[row[0] - 1])
    for row in CONTRACT_LAYOUT if row[3] == "ACTIVE"
}

#: Người thuê rủi ro cao/có ghi chú — để màn hình «đánh giá rủi ro» có số liệu
RISKY_TENANTS: dict[int, tuple[str, str]] = {
    3: ("MEDIUM", "Từng trễ hạn 2 lần trong 6 tháng"),
    7: ("MEDIUM", "Hóa đơn tháng 8 chưa thanh toán"),
    10: ("MEDIUM", "Trả phòng giữa kỳ, chuyển nhà nhiều"),
}


async def seed(session: AsyncSession) -> dict:
    roommates = 0
    histories = 0

    # ------------------------------------------------------------------ (1)
    #  12 NGƯỜI THUÊ — dữ liệu cá nhân + CCCD MÃ HÓA
    # ------------------------------------------------------------------
    for idx in range(1, 13):
        tenant_id = TENANT_IDS[idx - 1]
        full_name, phone, email = TENANT_NAMES[idx - 1]
        home_town, occupation = TENANT_PROFILES[idx - 1]
        risk, risk_note = RISKY_TENANTS.get(idx, ("LOW", None))

        #: Bản sao "đang ở đâu" — CHỈ cho người có hợp đồng ACTIVE
        current = ACTIVE_BY_TENANT.get(idx)
        current_room_id = uid("room", current[0]) if current else None
        current_contract_id = current[1] if current else None

        row = await upsert(session, Tenant, "id", {
            "id": tenant_id,
            "property_id": PROPERTY_ID,
            "previous_property_ids": [],
            "full_name": full_name,
            "date_of_birth": date(1990 + (idx % 10), (idx % 12) + 1, (idx % 27) + 1),
            "gender": "M" if idx % 2 == 1 else "F",
            "phone": phone,
            "email": email,
            "address": f"{home_town}, Việt Nam",
            "occupation": occupation,
            "note": None,
            # CCCD mã hóa — set qua setter, KHÔNG gán thẳng 3 cột (xem models.py)
            "id_card_front": None,
            "id_card_back": None,
            "emergency_contact_name": None,
            "emergency_contact_phone": None,
            "zalo_oa_id": None,
            "is_active": idx not in (10,),           # người ra ở, khoá tài khoản
            "risk_level": risk,
            "risk_note": risk_note,
            "current_room_id": current_room_id,
            "current_contract_id": current_contract_id,
            "deleted_at": None,
        })
        row.set_id_card(TENANT_IDCARDS[idx - 1])

    # ------------------------------------------------------------------ (2)
    #  BẠN CÙNG PHÒNG — có UUID tất định nên `upsert` chạy lại không trùng
    # ------------------------------------------------------------------
    for room_no, phone, name, ref_tenant in (
        ("B101", "0901000012", "Lý Thu Hà", TENANT_IDS[11]),   # người có hồ sơ
        ("A101", "0967123456", "Nguyễn Minh Châu", None),       # bạn «vô danh»
    ):
        await upsert(session, Roommate, "id", {
            "id": uid("roommate", room_no, phone),
            "property_id": PROPERTY_ID,
            "room_id": uid("room", room_no),
            "tenant_id": ref_tenant,
            "full_name": name,
            "phone": phone,
            "is_primary": False,
            "deleted_at": None,
        })
        roommates += 1

    # ------------------------------------------------------------------ (3)
    #  NHẬT KÝ — bảng append-only, KHÔNG sửa/xoá. Idempotency:
    #  "lần seed đầu tiên thắng" (đã có history cho tenant thì bỏ qua).
    # ------------------------------------------------------------------
    async def add_history(tenant_id: uuid.UUID, event_type: str,
                          data: dict, note: str | None) -> None:
        nonlocal histories
        exists = (await session.execute(
            select(TenantHistory.id).where(
                TenantHistory.tenant_id == tenant_id,
                TenantHistory.event_type == event_type,
            ).limit(1)
        )).scalar_one_or_none()
        if exists is not None:
            return
        session.add(TenantHistory(
            tenant_id=tenant_id,
            property_id=PROPERTY_ID,
            room_id=data.get("room_id"),
            event_type=event_type,
            event_data=data,
            actor_id=ADMIN_ID,
            note=note,
        ))
        histories += 1

    for idx in range(1, 13):
        current = ACTIVE_BY_TENANT.get(idx)
        if current:                                     # 1..9 — đang ở
            room_no, contract_id = current
            await add_history(
                TENANT_IDS[idx - 1], "MOVED_IN",
                {"room_number": room_no, "room_id": str(uid("room", room_no)),
                 "contract_id": str(contract_id)},
                f"Nhận phòng {room_no}",
            )
        elif idx == 10:                                 # đã trả phòng
            await add_history(
                TENANT_IDS[9], "MOVED_OUT",
                {"room_number": "A202", "room_id": str(uid("room", "A202"))},
                "Đã trả phòng khi hợp đồng hết hạn",
            )
        else:                                           # 11, 12 — chưa thuê
            await add_history(
                TENANT_IDS[idx - 1], "PROFILE_UPDATED",
                {"source": "seed"}, "Tạo hồ sơ, chưa phát sinh hợp đồng",
            )

    # Điểm rủi ro thay đổi — minh hoạ event RISK_CHANGED
    for idx in (3, 7):
        await add_history(
            TENANT_IDS[idx - 1], "RISK_CHANGED",
            {"from": "LOW", "to": "MEDIUM", "reason": RISKY_TENANTS[idx][1]},
            "Cập nhật mức rủi ro do lịch sử thanh toán",
        )

    await session.flush()
    return {
        "nguoi_thue": 12,
        "dang_o": len(ACTIVE_BY_TENANT),
        "cccd_da_ma_hoa": 12,
        "ban_cung_phong": roommates,
        "nhat_ky": histories,
    }


def main() -> int:
    from scripts._seed_common import run_seed

    return asyncio.run(run_seed("tenant-service", seed))


if __name__ == "__main__":
    sys.exit(main())
