"""
=============================================================================
 _seed_common — Phần dùng chung cho 5 script nạp dữ liệu mẫu
=============================================================================

BÀI TOÁN LỚN NHẤT CỦA DỮ LIỆU MẪU TRONG KIẾN TRÚC DATABASE-PER-SERVICE
------------------------------------------------------------------------
Mỗi service nằm trên MỘT database riêng và các script seed chạy trên từng
container riêng — chúng KHÔNG thể trao đổi gì qua biến môi trường hay file
tạm. Nhưng `contract.property_id` phải bằng `room.property_id` phải bằng
`tenant.property_id`... Nếu để mỗi script tự `uuid.uuid4()` thì dữ liệu mẫu
sẽ là 20 cơ sở khác nhau và mọi màn hình báo cáo đều rỗng.

⭐ Giải pháp: **UUID TẤT ĐỊNH** — `uuid5(namespace, tên)`.
      Hàm băm chuẩn SHA-1: cùng tên + cùng namespace ⇒ LUÔN ra cùng một
      UUID, ở MỌI máy, MỌI lần chạy, không cần lưu đâu cả.
      (Khác với `uuid4` là ngẫu nhiên, nên "chạy seed 2 lần" sẽ ra 2 bộ
      dữ liệu khác nhau và báo cáo sai.)

Nhờ vậy `make seed` chạy lại bao nhiêu lần cũng cho ra CÙNG một bộ dữ liệu,
và script seed đều IDEMPOTENT (xem `upsert`).
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: Namespace cố định của dự án. ĐỔI giá trị này = đổi toàn bộ ID dữ liệu mẫu,
#: nên phải giữ nguyên vĩnh viễn.
NAMESPACE = uuid.UUID("7f3a9c1e-5b2d-4e8a-9f41-2c8a6d0e5b13")


def uid(*parts: str) -> uuid.UUID:
    """Sinh UUID tất định từ tên. `uid("room", "A", "101")` luôn ra 1 giá trị."""
    return uuid.uuid5(NAMESPACE, "|".join(parts))


# ---------------------------------------------------------------------------
#  Khoá thực thể dùng chung giữa 8 database
# ---------------------------------------------------------------------------
PROPERTY_ID = uid("property", "minh-khai")
PROPERTY_NAME = "Nhà trọ Minh Khai"

BUILDING_A = uid("building", "minh-khai", "A")
BUILDING_B = uid("building", "minh-khai", "B")

#: 20 phòng: A có 3 tầng × 3 phòng + 1 phòng 1 tầng; B có 2 tầng × 5 phòng.
#: (Số phòng lẻ cố ý — trọ trọng, không phải khách sạn nên phòng lẻ là bình
#: thường, và nó làm cho bảng phòng trông giống dữ liệu thật hơn là 20 phòng
#: tròn trải.)
ROOM_LAYOUT: tuple[tuple[uuid.UUID, str, int, str], ...] = tuple(
    [(BUILDING_A, "A", floor, f"A{floor}0{n}") for floor in (1, 2, 3) for n in (1, 2, 3)]
    + [(BUILDING_A, "A", 1, "A-G01")]                 # phòng trọ 1 tầng
    + [(BUILDING_B, "B", floor, f"B{floor}0{n}") for floor in (1, 2) for n in (1, 2, 3, 4, 5)]
)
ROOM_IDS: tuple[uuid.UUID, ...] = tuple(uid("room", number) for *_, number in ROOM_LAYOUT)
ROOM_NUMBERS: tuple[str, ...] = tuple(number for *_, number in ROOM_LAYOUT)

TENANT_IDS: tuple[uuid.UUID, ...] = tuple(
    uid("tenant", f"minh-khai-{i:02d}") for i in range(1, 13)
)

ADMIN_ID = uid("user", "admin")
MANAGER_ID = uid("user", "quan-ly")
SYSTEM_USER_ID = uid("user", "system")

#: Ngày "hôm nay" dùng làm mốc cho dữ liệu mẫu. Lấy động để chạy seed vào
#: bất kỳ lúc nào cũng ra dữ liệu tương đối hợp lý (hợp đồng sắp hết hạn
#: vẫn là "sắp hết hạn" vào bất kỳ ngày nào).
TODAY = date.today()


# ---------------------------------------------------------------------------
#  Danh mục NGƯỜI THUÊ — dùng chung cho 4 DB (auth, tenant, contract, billing)
# ---------------------------------------------------------------------------
# (họ tên, số điện thoại, email). Mỗi DB tách biệt không gửi được gì cho nhau
# nên danh sách phải là MỘT, đặt ở đây để ai cũng import về cùng giá trị.
TENANT_NAMES: tuple[tuple[str, str, str], ...] = (
    ("Nguyễn Văn An", "0901000001", "an.nguyen@example.com"),
    ("Trần Thị Bình", "0901000002", "binh.tran@example.com"),
    ("Lê Quốc Cường", "0901000003", "cuong.le@example.com"),
    ("Phạm Thuỳ Dung", "0901000004", "dung.pham@example.com"),
    ("Hoàng Minh Đức", "0901000005", "duc.hoang@example.com"),
    ("Vũ Thị Giang", "0901000006", "giang.vu@example.com"),
    ("Đặng Quang Huy", "0901000007", "huy.dang@example.com"),
    ("Bùi Khánh Linh", "0901000008", "linh.bui@example.com"),
    ("Đỗ Trung Kiên", "0901000009", "kien.do@example.com"),
    ("Ngô Mai Lan", "0901000010", "lan.ngo@example.com"),
    ("Dương Hải Nam", "0901000011", "nam.duong@example.com"),
    ("Lý Thu Hà", "0901000012", "ha.ly@example.com"),
)

#: Số CCCD mẫu (12 chữ số) — CÙNG một người ở 2 DB khác nhau:
#:   - tenant-service: mã hóa AES-GCM + blind index (set_id_card)
#:   - contract-service: bản chụp lúc ký, lưu plaintext theo đúng thiết kế
#:     "bản chụp là tài liệu pháp lý đóng băng, không phụ thuộc DB kia".
TENANT_IDCARDS: tuple[str, ...] = (
    "079201001001", "079201001002", "079201001003", "079201001004",
    "079201001005", "079201001006", "079201001007", "079201001008",
    "079201001009", "079201001010", "079201001011", "079201001012",
)

#: (quê quán, nghề nghiệp) để hồ sơ người thuê không trống trơn.
TENANT_PROFILES: tuple[tuple[str, str], ...] = (
    ("Hà Nội", "Nhân viên văn phòng"),
    ("Nam Định", "Nhân viên kế toán"),
    ("Hải Phòng", "Kỹ sư xây dựng"),
    ("Thanh Hoá", "Giáo viên"),
    ("Nghệ An", "Kỹ sư phần mềm"),
    ("Thái Bình", "Làm tự do"),
    ("Hà Nội", "Nhân viên bán hàng"),
    ("Hưng Yên", "Thiết kế đồ hoạ"),
    ("Bắc Ninh", "Thợ điện tử"),
    ("Nam Định", "Chăm sóc khách hàng"),
    ("Quảng Ninh", "Lái xe"),
    ("Lạng Sơn", "Sinh viên"),
)


# ---------------------------------------------------------------------------
#  Thông số PHÒNG — dùng chung room-service (base_price, area) + contract
#  (monthly_price lấy CÙNG giá để hợp đồng và bảng phòng không mâu thuẫn)
# ---------------------------------------------------------------------------
ROOM_PRICES: dict[str, str] = {
    "A101": "2500000", "A102": "2500000", "A103": "2500000",
    "A201": "2800000", "A202": "2800000", "A203": "2800000",
    "A301": "3000000", "A302": "3000000", "A303": "3000000",
    "A-G01": "1800000",
    "B101": "2300000", "B102": "2300000", "B103": "2300000",
    "B104": "2400000", "B105": "2400000",
    "B201": "2600000", "B202": "2600000", "B203": "2600000",
    "B204": "2700000", "B205": "2700000",
}
ROOM_AREAS: dict[str, str] = {
    "A101": "24", "A102": "22", "A103": "22",
    "A201": "28", "A202": "28", "A203": "28",
    "A301": "32", "A302": "32", "A303": "35",
    "A-G01": "18",
    "B101": "20", "B102": "20", "B103": "18",
    "B104": "18", "B105": "22",
    "B201": "24", "B202": "24", "B203": "24",
    "B204": "22", "B205": "25",
}
#: Số người tối đa — phòng rộng thì cho 3, vừa thì 2, nhỏ thì 1.
ROOM_MAX_OCCUPANTS: dict[str, int] = {
    room: (3 if int(ROOM_AREAS[room]) >= 28
           else 2 if int(ROOM_AREAS[room]) >= 22
           else 1)
    for room in ROOM_NUMBERS
}

#: Tiện ích (danh mục CHUNG toàn hệ thống — bảng `amenities` không có
#: property_id, xem room/models.py). `fee` là phí tháng mặc định (VND); mức
#: thu thật của từng phòng nằm ở bảng nối `room_amenities.is_billable`.
AMENITIES: tuple[dict[str, str], ...] = (
    {"uid": "WIFI", "code": "WIFI", "name": "Internet WiFi",
     "icon": "wifi", "fee": "100000",
     "desc": "Cáp quang 100 Mbps, thiết bị phát trong phòng"},
    {"uid": "PRIVATE_BATHROOM", "code": "PRIVATE_BATHROOM",
     "name": "Vệ sinh khép kín", "icon": "bath", "fee": "0",
     "desc": "Nhà vệ sinh riêng trong phòng"},
    {"uid": "WATER_HEATER", "code": "WATER_HEATER", "name": "Bình nóng lạnh",
     "icon": "droplet", "fee": "0", "desc": "Nước nóng cả mùa đông"},
    {"uid": "KITCHEN", "code": "KITCHEN", "name": "Bếp nấu ăn",
     "icon": "flame", "fee": "0", "desc": "Khu bếp riêng trong phòng"},
    {"uid": "AIRCON", "code": "AIRCON", "name": "Điều hoà",
     "icon": "snow", "fee": "0", "desc": "Điều hoà 9000 BTU, inverter"},
    {"uid": "FRIDGE", "code": "FRIDGE", "name": "Tủ lạnh",
     "icon": "box", "fee": "0", "desc": "Tủ lạnh mini trong phòng"},
    {"uid": "PARKING", "code": "PARKING", "name": "Chỗ để xe",
     "icon": "bike", "fee": "0", "desc": "Sân để xe có camera"},
)
AMENITY_IDS: dict[str, uuid.UUID] = {
    a["uid"]: uid("amenity", a["code"]) for a in AMENITIES
}


# ---------------------------------------------------------------------------
#  BỐ CỤC HỢP ĐỒNG MẪU — dùng chung room + tenant + contract + billing
# ---------------------------------------------------------------------------
# (số thứ tự hợp đồng 1..11, chỉ số người thuê 1..12, số phòng, trạng thái,
#  ngày — dương = còn N ngày hết hạn, âm = đã hết hạn N ngày, None = DRAFT)
#
# 9 hợp đồng ACTIVE (2 trong đó đang "sắp hết hạn" để job cảnh báo của
# scheduler có việc làm), 1 EXPIRED (đã trả phòng), 1 DRAFT (đang soạn).
CONTRACT_LAYOUT: tuple[tuple[int, int, str, str, int | None], ...] = (
    (1,  1, "A101", "ACTIVE",   5),
    (2,  2, "A102", "ACTIVE", 190),
    (3,  3, "A103", "ACTIVE", 320),
    (4,  4, "A201", "ACTIVE", 150),
    (5,  5, "A-G01", "ACTIVE",  95),
    (6,  6, "B101", "ACTIVE",  25),
    (7,  7, "B102", "ACTIVE", 200),
    (8,  8, "B103", "ACTIVE", 260),
    (9,  9, "B104", "ACTIVE", 180),
    (10, 10, "A202", "EXPIRED", -45),
    (11, 11, "A203", "DRAFT",   None),
)
CONTRACT_IDS: tuple[uuid.UUID, ...] = tuple(
    uid("contract", f"c{row[0]:02d}") for row in CONTRACT_LAYOUT
)
#: Phòng đang có người (9 hợp đồng ACTIVE) — room-service đặt status OCCUPIED +
#: current_contract_id; tenant-service đặt current_room_id/current_contract_id.
ACTIVE_ROOMS: dict[str, uuid.UUID] = {
    row[2]: CONTRACT_IDS[row[0] - 1]
    for row in CONTRACT_LAYOUT if row[3] == "ACTIVE"
}
EXPIRED_ROOMS: set[str] = {row[2] for row in CONTRACT_LAYOUT if row[3] == "EXPIRED"}
DRAFT_ROOMS: set[str] = {row[2] for row in CONTRACT_LAYOUT if row[3] == "DRAFT"}

#: Hợp đồng #4 dùng cọc trừ 500.000đ vào hóa đơn KỲ ĐẦU — contract-service
#: phải ghi `deposit_deducted` ĐÚNG số này để 2 DB không mâu thuẫn (R3).
DEPOSIT_USED: dict[int, str] = {4: "500000"}
#: Hợp đồng #7 được giảm 200.000đ vào hóa đơn kỳ đầu (khuyến mãi nhập trọ).
INVOICE_DISCOUNTS: dict[int, str] = {7: "200000"}


# ---------------------------------------------------------------------------
#  Tiện ích thời gian
# ---------------------------------------------------------------------------
def last_full_months(n: int = 3, ref: date | None = None) -> list[date]:
    """
    `n` tháng đầy đủ NGAY TRƯỚC tháng hiện tại (mốc `TODAY`).

    Ví dụ hôm nay 2026-09-28 → [2026-07-01, 2026-08-01, 2026-09-01].
    Lệch qua năm vẫn đúng (hôm nay 2026-01-15 → [2025-10-01..2025-12-01]).
    """
    first = (ref or TODAY).replace(day=1)
    months: list[date] = []
    for i in range(n - 1, -1, -1):
        month_number = first.month - i
        year = first.year
        if month_number <= 0:
            year, month_number = year - 1, month_number + 12
        months.append(date(year, month_number, 1))
    return months


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def env_money(name: str, default: str) -> Decimal:
    """
    Đọc giá tiền từ biến môi trường, mặc định lấy từ `default`.

    ⚠️ `Decimal(str(os.getenv(...)))` — KHÔNG `Decimal(os.getenv(...))`:
       biến môi trường luôn là chuỗi nên `str()` ở đây là thủ tục phòng thủ
       (giúp khi ai đó đổi `.env` thành số không dấu nhấp phẩy).
    """
    return Decimal(str(os.getenv(name, default)).replace("_", ""))


def env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except ValueError:
        return default


# ---------------------------------------------------------------------------
#  Ghi dữ liệu idempotent
# ---------------------------------------------------------------------------
async def upsert(
    session: AsyncSession,
    model: type,
    pk: str,
    values: dict[str, Any],
    *,
    unique_by: Sequence[str] = (),
) -> Any:
    """
    Tìm theo khoá chính (hoặc theo `unique_by`); thấy thì cập nhật, chưa có
    thì thêm.

    ⭐ VÌ SAO KHÔNG DÙNG `session.merge()`?
        `merge()` load bản ghi rồi ghi đè TOÀN BỘ cột — khiến mọi trường
        không nằm trong `values` bị đặt về `None`, xoá sạch dữ liệu đã có.
        Ở đây ta chỉ ghi đè những cột thực sự truyền vào, nên chạy seed lần
        2 vẫn giữ nguyên những thứ script không quan tâm (ví dụ `id` do
        database sinh, `created_at`).

    ⭐ `unique_by` dùng cho bảng có ràng buộc UNIQUE nghiệp vụ (ví dụ
       `meters(property_id, room_id, utility_type, period)`): hai lần seed
       phải ra 1 dòng chứ không phải 2 dòng trùng nhau.
    """
    lookup = {pk: values[pk]} if pk in values else dict(values)
    if unique_by:
        lookup = {k: values[k] for k in unique_by}

    stmt = select(model).filter_by(**lookup).limit(1)
    row = (await session.execute(stmt)).scalars().first()

    if row is None:
        row = model(**values)
        session.add(row)
    else:
        for key, value in values.items():
            if key == pk:
                continue
            setattr(row, key, value)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
#  Khung chạy chung cho 5 script seed
# ---------------------------------------------------------------------------
SeedFn = Callable[[AsyncSession], Awaitable[dict]]


async def run_seed(service: str, fn: SeedFn) -> int:
    """
    Bọc `fn` trong: cấu hình log → tạo bảng (nếu chưa có) → session → tổng kết.

    Trả về mã thoát (0 = thành công).

    ⭐ KHÔNG dùng `setup_telemetry()` của service: nó bật log JSON khi
       `ENVIRONMENT=prod`, mà script nạp dữ liệu thì người ta muốn ĐỌC —
       log dạng người hiểu được, có ký tự màu, dễ chụp ảnh đưa vào báo cáo.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from common.database import create_tables, engine, session_scope

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)-7s %(name)-20s %(message)s",
    )

    from common.config import settings

    print(f"\n{'=' * 62}")
    print(f"  NẠP DỮ LIỆU MẪU — {service}  (DB: {settings.db_name or '?'})")
    print(f"{'=' * 62}")

    try:
        # `create_tables` chỉ tạo bảng CÒN THIẾU — không đụng bảng đã có, nên
        # gọi lại mỗi lần seed đều an toàn. (Migration Alembic mới là đường
        # chính; bước này chỉ để `make seed` chạy được trên DB trắng.)
        await create_tables()
        async with session_scope() as session:
            summary = await fn(session)
    except Exception as exc:                      # script phải báo rõ, không im lặng
        print(f"\n❌ NẠP DỮ LIỆU THẤT BẠI: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n  ✅ " + " | ".join(f"{k}={v}" for k, v in summary.items()))
    await engine.dispose()
    return 0
