"""
seed_room — Danh mục nhà trọ cho room-service (db_room).

    docker compose exec -T room python -m scripts.seed_room

Tạo:
  - 1 Property        : «Nhà trọ Minh Khai» — trục cột của toàn bộ phân quyền
  - 2 Building        : A (3 tầng × 3 phòng + 1 phòng 1 tầng), B (2 tầng × 5)
  - 20 Room           : diện tích / giá / số người tối đa lấy từ
                        `ROOM_PRICES` + `ROOM_AREAS` + `ROOM_MAX_OCCUPANTS`
                        (định nghĩa CHUNG trong _seed_common để contract-service
                        in ra hợp đồng đúng CÙNG giá với bảng phòng)
  - 7 Amenity         : danh mục tiện ích chung + bảng nối `room_amenities`

⭐ TRẠNG THÁI PHÒNG — đặt ĐÚNG theo CONTRACT_LAYOUT (xem _seed_common):
   - 9 phòng có hợp đồng ACTIVE  → OCCUPIED kèm `current_contract_id`
   - A202 có hợp đồng EXPIRED    → AVAILABLE (người thuê đã trả phòng)
   - A203 có hợp đồng DRAFT      → AVAILABLE (mới soạn, chưa ký, chưa vào ở)
   - 9 phòng còn lại              → AVAILABLE

Nhờ vậy 3 DB (room / tenant / contract) luôn "kể một câu chuyện":
   room     nói phòng nào đang có người,
   tenant   nói ai đang ở đâu,
   contract nói quan hệ pháp lý ra sao.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models import Amenity, Building, Property, Room, room_amenities
from scripts._seed_common import (
    ACTIVE_ROOMS,
    AMENITIES,
    AMENITY_IDS,
    BUILDING_A,
    BUILDING_B,
    PROPERTY_ID,
    PROPERTY_NAME,
    ROOM_AREAS,
    ROOM_LAYOUT,
    ROOM_MAX_OCCUPANTS,
    ROOM_NUMBERS,
    ROOM_PRICES,
    uid,
    upsert,
)


#: Phòng nào gắn tiện ích nào — quy tắc theo hạng phòng (phòng càng đắt càng
#: đầy đủ). Đặt rõ ở đây để người đọc seed thấy được logic, không phải đoán.
def _amenity_codes(building_letter: str, floor: int, room_no: str) -> list[str]:
    codes = ["WIFI", "PRIVATE_BATHROOM"]          # ai cũng có wifi + vệ sinh riêng
    if room_no == "A-G01":                        # phòng 1 tầng, rẻ nhất
        return codes
    codes += ["WATER_HEATER", "KITCHEN"]          # nóng lạnh + bếp cho mọi phòng
    if floor >= 2:
        codes += ["AIRCON"]                       # tầng cao hơn đắt hơn → có điều hoà
    if building_letter == "A" and floor >= 3:
        codes += ["FRIDGE"]                       # phòng hạng cao nhất thêm tủ lạnh
    if building_letter == "B":
        codes += ["PARKING"]                      # dãy B có sân để xe
    return codes


def _room_note(room_no: str) -> str | None:
    """Vài phòng có ghi chú cho bảng phòng đỡ trống trơn (không phải dữ liệu)."""
    notes = {
        "A-G01": "Phòng 1 tầng, rẻ nhất dãy — phù hợp công nhân",
        "A101": "Phòng góc tầng 1, cửa sổ mở ra sân",
        "A301": "Phòng góc, thoáng — tầng cao nhất dãy A",
        "B105": "Cuối dãy B, yên tĩnh",
    }
    return notes.get(room_no)


async def seed(session: AsyncSession) -> dict:
    # ------------------------------------------------------------------ (1)
    #  CƠ SỞ + 2 TÒA NHÀ
    # ------------------------------------------------------------------
    await upsert(session, Property, "id", {
        "id": PROPERTY_ID,
        "name": PROPERTY_NAME,
        "address": "Số 12 ngõ 45 Minh Khai, Hai Bà Trưng, Hà Nội",
        "owner_name": "Nguyễn Văn Chủ",
        "phone": "0988111222",
        "tax_code": "0123456789",
        "total_rooms": len(ROOM_NUMBERS),
        "description": (
            "Nhà trọ 2 dãy: A 3 tầng (9 phòng) + 1 phòng 1 tầng, "
            "B 2 tầng (10 phòng). Khu vực yên tĩnh, gần chợ, cổng có khoá vân tay."
        ),
        "is_active": True,
        "deleted_at": None,
    })

    await upsert(session, Building, "id", {
        "id": BUILDING_A,
        "property_id": PROPERTY_ID,
        "name": "A",
        "note": "3 tầng, mỗi tầng 3 phòng + 1 phòng trệt A-G01",
    })
    await upsert(session, Building, "id", {
        "id": BUILDING_B,
        "property_id": PROPERTY_ID,
        "name": "B",
        "note": "2 tầng, mỗi tầng 5 phòng — có sân để xe rộng",
    })

    # ------------------------------------------------------------------ (2)
    #  DANH MỤC TIỆN ÍCH (bảng chung toàn hệ thống, KHÔNG có property_id)
    # ------------------------------------------------------------------
    for item in AMENITIES:
        await upsert(session, Amenity, "id", {
            "id": AMENITY_IDS[item["uid"]],
            "code": item["code"],
            "name": item["name"],
            "icon": item["icon"],
            "default_monthly_fee": Decimal(item["fee"]),
            "description": item["desc"],
            "is_active": True,
        })

    # ------------------------------------------------------------------ (3)
    #  20 PHÒNG — trạng thái theo CONTRACT_LAYOUT, giá theo ROOM_PRICES
    # ------------------------------------------------------------------
    count_occupied = 0
    for (building_id, _building_letter, floor, room_no) in ROOM_LAYOUT:
        contract_id = ACTIVE_ROOMS.get(room_no)
        status = "OCCUPIED" if contract_id else "AVAILABLE"
        if status == "OCCUPIED":
            count_occupied += 1

        await upsert(session, Room, "id", {
            "id": uid("room", room_no),
            "property_id": PROPERTY_ID,
            "building_id": building_id,
            "room_number": room_no,
            "floor": floor,
            "area_m2": Decimal(ROOM_AREAS[room_no]),
            "base_price": Decimal(ROOM_PRICES[room_no]),
            "max_occupants": ROOM_MAX_OCCUPANTS[room_no],
            "status": status,
            "current_contract_id": contract_id,   # None cho phòng trống / DRAFT
            "note": _room_note(room_no),
            "photos": [],
            "deleted_at": None,
        })

    # ------------------------------------------------------------------ (4)
    #  BẢNG NỐI room_amenities — XOÁ rồi ghi LẠI để chạy seed lần 2 không trùng.
    #  (Bảng này không có model class nên không dùng được `upsert`; PK là
    #   (room_id, amenity_id) nên ghi trùng sẽ vi phạm UNIQUE.)
    # ------------------------------------------------------------------
    links: list[dict] = []
    for (_, building_letter, floor, room_no) in ROOM_LAYOUT:
        for code in _amenity_codes(building_letter, floor, room_no):
            links.append({
                "room_id": uid("room", room_no),
                "amenity_id": AMENITY_IDS[code],
                # ⭐ FALSE = không thu phí qua tiện ích phòng. Các phí cố định
                # (internet/vệ sinh/rác) nằm ở `service_fees` của billing-service
                # để tính 1 lần cho cả cơ sở — tránh tính tiền 2 lần.
                "is_billable": False,
            })

    await session.execute(delete(room_amenities))
    if links:
        await session.execute(room_amenities.insert(), links)

    await session.flush()
    return {
        "co_so": 1,
        "toa_nha": 2,
        "phong": len(ROOM_NUMBERS),
        "phong_dang_o": count_occupied,
        "tien_ich": len(AMENITIES),
        "lien_ket_tien_ich": len(links),
    }


def main() -> int:
    from scripts._seed_common import run_seed

    return asyncio.run(run_seed("room-service", seed))


if __name__ == "__main__":
    sys.exit(main())
