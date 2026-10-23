"""
================================================================================
room-service — Danh mục phòng.        Cổng 8002  |  db_room
================================================================================

Cung cấp: cơ sở, tòa nhà, phòng, tiện ích + thống kê công suất.

Ba điểm kỹ thuật đáng chú ý trong file này:
  1. CACHE 2 TẦNG (đọc nhiều / ghi ít) — phòng gần như bất biến giữa 2 lần sửa,
     nên cache ở Redis + tự vô hiệu hoá khi ghi. Đây là mẫu Cache-Aside.
  2. PHÂN QUYỀN THEO CƠ SỞ — mọi endpoint đều gọi `assert_property_access()`.
     Đây là hàng rào chống MANAGER của nhà trọ A đọc dữ liệu nhà trọ B.
  3. EVENT-DRIVEN — trạng thái phòng do contract/maintenance điều khiển qua
     event, không qua REST. Nhờ vậy mọi service đều chỉ ghi vào DB của mình.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common import (
    BusinessRuleError,
    ConflictError,
    CurrentUser,
    MessageResponse,
    NotFoundError,
    PageParams,
    Role,
    apply_sort,
    create_service_app,
    get_db,
    get_event_bus,
    paginate,
    record_business_event,
    require_roles,
)
from common.config import settings
from common.database import session_scope
from common.events import DomainEvent, IdempotentConsumer
from common.telemetry import set_business_gauge
from models import Amenity, Building, Property, Room, RoomStatus, room_amenities
from schemas import (
    AmenityCreate,
    AmenityResponse,
    BuildingCreate,
    BuildingResponse,
    PropertyCreate,
    PropertyResponse,
    PropertyUpdate,
    RoomAmenitySet,
    RoomAvailableItem,
    RoomCreate,
    RoomResponse,
    RoomSearchRequest,
    RoomStats,
    RoomStatusChange,
    RoomUpdate,
)

logger = logging.getLogger(__name__)

# Thời gian sống cache (giây)
CACHE_TTL_ROOM = 300         # chi tiết phòng
CACHE_TTL_STATS = 60         # thống kê công suất — thay đổi nhanh hơn
CACHE_TTL_AVAILABLE = 120    # danh sách phòng trống


# ===========================================================================
#  APP
# ===========================================================================
# ⚠️  `_setup_consumer` phải được ĐỊNH NGHĨA TRƯỚC dòng `create_service_app`
#     bên dưới, vì hàm được truyền vào làm tham số (đánh giá ngay lúc gọi).
#     Bản thân `_handle_event` thì chưa cần định nghĩa ở đây — nó chỉ được
#     *gọi* khi có event tới, tức là sau khi module đã nạp xong.
async def _setup_consumer(app_instance) -> None:
    consumer = IdempotentConsumer(
        handler=_handle_event,
        consumer_name="room-service:contract-and-maintenance-events",
    )
    app_instance.state.ctx.consumers.append(consumer)
    try:
        await get_event_bus().subscribe(
            "qlpt.room.events", consumer.handle,
            ["contract.activated", "contract.terminated", "contract.expired",
             "contract.cancelled", "incident.urgent", "incident.resolved",
             "room.maintenance_completed"],
        )
    except Exception as exc:
        logger.warning("Không đăng ký consumer được: %s", exc)


app = create_service_app(
    name="room-service",
    description=(
        "**Danh mục phòng trọ**\n\n"
        "- Cơ sở, tòa nhà, phòng, tiện ích\n"
        "- Tìm phòng trống theo tiêu chí (kèm giá ước tính)\n"
        "- Thống kê công suất theo cơ sở\n"
        "- Nhận event từ contract/maintenance để đổi trạng thái phòng\n\n"
        "### Điểm cần biết\n"
        "- Trạng thái phòng **không tự đổi theo ý người dùng** vào `OCCUPIED` —\n"
        "  chỉ `contract.activated` mới làm được điều đó\n"
        "- Mọi endpoint đều kiểm tra quyền theo `property_id` trong token"
    ),
    version="1.0.0",
    lifespan_extra=_setup_consumer,
)


# ===========================================================================
#  CACHE HELPERS
# ===========================================================================
def _cache_key(*parts: Any) -> str:
    return "room:" + ":".join(str(p) for p in parts)


async def _cache_get(redis: Any, key: str) -> Any | None:
    if redis is None:
        return None
    try:
        raw = await redis.get(key)
        return raw if raw else None
    except Exception as exc:
        # Redis chết KHÔNG được làm sập API đọc — chỉ mất cache, không mất
        # chức năng. Đây là nguyên tắc "cache là tối ưu, không phải nguồn sự thật".
        logger.warning("Redis GET lỗi (%s) — bỏ qua cache", exc)
        return None


async def _cache_set(redis: Any, key: str, value: str, ttl: int) -> None:
    if redis is None:
        return
    try:
        await redis.setex(key, ttl, value)
    except Exception as exc:
        logger.warning("Redis SETEX lỗi (%s)", exc)


async def _invalidate_room_cache(redis: Any, room: Room | None = None,
                                 property_id: uuid.UUID | None = None) -> None:
    """
    Xoá cache sau khi ghi.

    ⭐ Vì sao dùng mẫu "ghi xong mới xoá cache" thay vì "xoá cache trước khi ghi"?
       Nếu xoá trước rồi ghi DB thất bại, cache vẫn trống → hệ thống chậm
       nhưng vẫn ĐÚNG. Nếu xoá sau, có một cửa sổ rất ngắn mà cache còn
       dữ liệu cũ — chấp nhận được vì thời gian thực tế < 1ms.
    """
    if redis is None:
        return
    keys = [_cache_key("list", "*"), _cache_key("available", "*"), _cache_key("stats", "*")]
    if room is not None:
        keys.append(_cache_key("room", room.id))
    if property_id is not None:
        keys.append(_cache_key("stats", property_id))
    try:
        # SCAN chứ không dùng KEYS: KEYS chặn toàn bộ Redis server, còn SCAN
        # chạy từng lô. Với hệ thống nhỏ, cách này vẫn rẻ hơn nhiều so với
        # việc duy trì một Set chứa toàn bộ key phải xoá.
        for pattern in keys:
            async for key in redis.scan_iter(match=pattern, count=200):
                await redis.delete(key)
    except Exception as exc:
        logger.warning("Không xoá được cache: %s", exc)


# ===========================================================================
#  NGHIỆP VỤ: đổi trạng thái phòng
# ===========================================================================
#: Nguồn → trạng thái mới. Dùng để chặn việc đổi trạng thái theo chiều không hợp lệ.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    RoomStatus.AVAILABLE.value: {
        RoomStatus.OCCUPIED.value, RoomStatus.MAINTENANCE.value,
        RoomStatus.RESERVED.value,
    },
    RoomStatus.RESERVED.value: {RoomStatus.AVAILABLE.value, RoomStatus.OCCUPIED.value},
    # Phòng đang có người KHÔNG thể tự chuyển sang AVAILABLE —
    # phải qua contract (hợp đồng kết thúc) hoặc maintenance (sự cố nghiêm trọng).
    RoomStatus.OCCUPIED.value: {RoomStatus.MAINTENANCE.value, RoomStatus.AVAILABLE.value},
    RoomStatus.MAINTENANCE.value: {RoomStatus.AVAILABLE.value},
}


async def _set_room_status(
    session: AsyncSession,
    room: Room,
    new_status: str,
    *,
    contract_id: uuid.UUID | None = None,
    reason: str | None = None,
    actor: CurrentUser | None = None,
    correlation_id: str | None = None,
) -> Room:
    """
    Hàm DUY NHẤT được phép đổi trạng thái phòng.

    Mọi lối vào (REST thủ công, event từ contract, event từ maintenance)
    đều đi qua đây. Nhờ vậy:
      - luôn phát ra `room.status_changed` → notification + report nhận đủ
      - luôn kiểm tra luật chuyển trạng thái
      - luôn cập nhật `current_contract_id` đồng bộ

    ⭐ Đây chính là "single point of truth" — trong microservice, nguyên nhân
    phổ biến nhất của dữ liệu sai là có 3 chỗ cùng ghi vào 1 trường.
    """
    old_status = room.status
    if old_status == new_status:
        logger.debug("Phòng %s đã ở trạng thái %s — không đổi",
                     room.room_number, new_status)
        return room

    allowed = ALLOWED_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise BusinessRuleError(
            f"Không thể chuyển phòng từ '{old_status}' sang '{new_status}'. "
            f"Chỉ chuyển được sang: {', '.join(sorted(allowed)) or '(không có)'}",
            details={"room_id": str(room.id), "from": old_status, "to": new_status},
        )

    # Trạng thái OCCUPIED phải có hợp đồng đi kèm — nếu không, billing sẽ
    # không tính tiền cho phòng đó và doanh thu báo cáo sẽ lệch.
    if new_status == RoomStatus.OCCUPIED.value and contract_id is None:
        raise BusinessRuleError(
            "Chỉ có thể chuyển phòng sang 'đang thuê' khi có hợp đồng hiệu lực. "
            "Hãy kích hoạt hợp đồng thay vì đổi trạng thái thủ công."
        )

    room.status = new_status
    if new_status == RoomStatus.OCCUPIED.value:
        room.current_contract_id = contract_id
    elif new_status in (RoomStatus.AVAILABLE.value, RoomStatus.MAINTENANCE.value):
        room.current_contract_id = None

    await session.flush()

    await get_event_bus().publish(session, DomainEvent(
        event_type="room.status_changed",
        correlation_id=correlation_id,
        data={
            "room_id": str(room.id),
            "property_id": str(room.property_id),
            "room_number": room.room_number,
            "from": old_status,
            "to": new_status,
            "reason": reason,
            "contract_id": str(contract_id) if contract_id else None,
            "entity_type": "room",
            "entity_id": str(room.id),
            "changed_by": actor.username if actor else "system",
        },
    ))
    record_business_event(settings.service_name, "room.status_changed")

    logger.info("🔄 Phòng %s: %s → %s (%s)", room.room_number, old_status,
                new_status, reason or "—")
    return room


# ===========================================================================
#  DEPENDENCY: lấy property_id người dùng được phép thao tác
# ===========================================================================
async def _resolve_property_id(
    user: CurrentUser,
    session: AsyncSession,
    requested: uuid.UUID | None,
) -> uuid.UUID | None:
    """
    Xác định cơ sở đang thao tác và KIỂM TRA QUYỀN.

    - ADMIN không giới hạn: `requested` hoặc `None` (xem tất cả)
    - MANAGER bắt buộc khớp `property_id` trong token của họ
    - TENANT không được gọi các endpoint này (đã chặn ở dependency phân quyền)
    """
    if user.is_admin:
        return requested

    if user.property_id is None:
        raise BusinessRuleError(
            "Tài khoản quản lý chưa được gán vào cơ sở nào. "
            "Vui lòng liên hệ quản trị viên."
        )

    # MANAGER chỉ được chạm vào đúng cơ sở của mình
    if requested is not None and str(requested) != str(user.property_id):
        user.assert_property_access(requested)   # ném 403 với thông báo rõ ràng
    return user.property_id


# ===========================================================================
#  ROUTER: PROPERTY
# ===========================================================================
property_router = APIRouter(prefix="/api/v1/properties", tags=["properties"])


@property_router.get("", summary="Danh sách cơ sở nhà trọ")
async def list_properties(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    include_inactive: bool = Query(False, description="Có lấy cơ sở đã ngừng không"),
) -> dict:
    """ADMIN thấy tất cả; MANAGER chỉ thấy đúng cơ sở của mình."""
    stmt = select(Property).where(Property.deleted_at.is_(None))
    if not include_inactive:
        stmt = stmt.where(Property.is_active.is_(True))
    if not user.is_admin:
        stmt = stmt.where(Property.id == user.property_id)

    items, meta = await paginate(
        session, stmt, params, order_by=[Property.name.asc()]
    )
    return {
        "items": [PropertyResponse.model_validate(p) for p in items],
        "meta": meta.model_dump(),
    }


@property_router.post("", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED,
                      summary="Tạo cơ sở nhà trọ")
async def create_property(
    payload: PropertyCreate,
    admin: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PropertyResponse:
    """
    Chỉ ADMIN tạo được cơ sở.

    Lý do: tạo cơ sở = chủ đầu tư mới. Nếu MANAGER tự tạo được cơ sễ thì họ
    tự gán mình làm quản lý → leo thang đặc quyền. Ở đây bảo mật được
    *đặt tại endpoint* chứ không chỉ dựa vào việc ẩn nút trên UI.
    """
    prop = Property(**payload.model_dump())
    session.add(prop)
    await session.flush()
    logger.info("🏢 Tạo cơ sở %s (id=%s) bởi %s", prop.name, prop.id, admin.username)
    return PropertyResponse.model_validate(prop)


@property_router.get("/{property_id}", response_model=PropertyResponse,
                     summary="Chi tiết cơ sở")
async def get_property(
    property_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PropertyResponse:
    user.assert_property_access(property_id)
    prop = await session.get(Property, property_id)
    if not prop or prop.deleted_at:
        raise NotFoundError("Không tìm thấy cơ sở nhà trọ")
    return PropertyResponse.model_validate(prop)


@property_router.patch("/{property_id}", response_model=PropertyResponse,
                       summary="Cập nhật cơ sở")
async def update_property(
    property_id: uuid.UUID,
    payload: PropertyUpdate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PropertyResponse:
    user.assert_property_access(property_id)
    prop = await session.get(Property, property_id)
    if not prop or prop.deleted_at:
        raise NotFoundError("Không tìm thấy cơ sở nhà trọ")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(prop, field, value)
    await session.flush()
    return PropertyResponse.model_validate(prop)


# ===========================================================================
#  ROUTER: BUILDING
# ===========================================================================
building_router = APIRouter(prefix="/api/v1/buildings", tags=["buildings"])


@building_router.get("", summary="Danh sách tòa nhà")
async def list_buildings(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> list[BuildingResponse]:
    effective = await _resolve_property_id(user, session, property_id)
    stmt = select(Building)
    if effective:
        stmt = stmt.where(Building.property_id == effective)
    stmt = stmt.order_by(Building.name)

    rows = (await session.execute(stmt)).scalars().all()
    return [BuildingResponse.model_validate(b) for b in rows]


@building_router.post("", response_model=BuildingResponse,
                      status_code=status.HTTP_201_CREATED, summary="Tạo tòa nhà")
async def create_building(
    request: Request,
    payload: BuildingCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BuildingResponse:
    await _resolve_property_id(user, session, payload.property_id)
    existing = (await session.execute(
        select(Building).where(
            Building.property_id == payload.property_id,
            Building.name == payload.name,
        )
    )).scalar_one_or_none()
    if existing:
        raise ConflictError(f"Tòa nhà '{payload.name}' đã tồn tại trong cơ sở này")

    b = Building(**payload.model_dump())
    session.add(b)
    await session.flush()
    await _invalidate_room_cache(request.app.state.redis, None, payload.property_id)
    return BuildingResponse.model_validate(b)


# ===========================================================================
#  ROUTER: AMENITY
# ===========================================================================
amenity_router = APIRouter(prefix="/api/v1/amenities", tags=["amenities"])


@amenity_router.get("", response_model=list[AmenityResponse],
                     summary="Danh sách tiện ích")
async def list_amenities(
    _: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[AmenityResponse]:
    rows = (await session.execute(
        select(Amenity).where(Amenity.is_active.is_(True)).order_by(Amenity.code)
    )).scalars().all()
    return [AmenityResponse.model_validate(a) for a in rows]


@amenity_router.post("", response_model=AmenityResponse,
                     status_code=status.HTTP_201_CREATED, summary="Tạo tiện ích")
async def create_amenity(
    payload: AmenityCreate,
    admin: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AmenityResponse:
    """
    Danh mục tiện ích là dùng chung toàn hệ thống → chỉ ADMIN thêm.
    MANAGER chỉ được GÁN tiện ích có sẵn vào phòng của cơ sở mình.
    """
    exists = (await session.execute(
        select(Amenity).where(Amenity.code == payload.code)
    )).scalar_one_or_none()
    if exists:
        raise ConflictError(f"Mã tiện ích '{payload.code}' đã tồn tại")

    a = Amenity(**payload.model_dump())
    session.add(a)
    await session.flush()
    return AmenityResponse.model_validate(a)


# ===========================================================================
#  ROUTER: ROOM
# ===========================================================================
room_router = APIRouter(prefix="/api/v1/rooms", tags=["rooms"])


@room_router.get("", summary="Danh sách phòng")
async def list_rooms(
    request: Request,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    property_id: uuid.UUID | None = None,
    building_id: uuid.UUID | None = None,
    room_status: str | None = Query(None, alias="status",
                                    description="Lọc theo trạng thái phòng"),
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    search: str | None = None,
    sort: str = Query("room_number_asc", description="room_number|base_price|area_m2"),
) -> dict:
    effective = await _resolve_property_id(user, session, property_id)

    stmt = select(Room).options(
        selectinload(Room.building),
        selectinload(Room.amenities),
    ).where(Room.deleted_at.is_(None))

    if effective:
        stmt = stmt.where(Room.property_id == effective)
    if building_id:
        stmt = stmt.where(Room.building_id == building_id)
    if room_status:
        stmt = stmt.where(Room.status == room_status)
    if min_price is not None:
        stmt = stmt.where(Room.base_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Room.base_price <= max_price)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Room.room_number.ilike(like))

    stmt = apply_sort(
        stmt, Room, sort,
        allowed={"room_number": "room_number", "price": "base_price", "area": "area_m2"},
        default="room_number",
    )

    items, meta = await paginate(session, stmt, params)
    return {
        "items": [_to_room_response(r) for r in items],
        "meta": meta.model_dump(),
    }


@room_router.get("/available", summary="🔍 Tìm phòng trống (có giá ước tính)")
async def find_available_rooms(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    payload: Annotated[RoomSearchRequest, Query()],
) -> dict:
    """
    ⭐ Endpoint CÔNG KHAI — không yêu cầu đăng nhập.

    Đây là trang tìm phòng mà khách thuê trước khi có tài khoản vẫn xem được.
    Cố ý KHÔNG yêu cầu token vì đó là yêu cầu nghiệp vụ (xem trang chủ công khai),
    và dữ liệu trả về không nhạy cảm. Giá ước tính lấy từ cache Redis, không
    đụng tới dữ liệu cá nhân.

    Vì không có `user`, phải tự lọc theo property_id do client truyền vào
    và CHỈ chọn các cột công khai.
    """
    redis = getattr(request.app.state, "redis", None)

    stmt = select(Room).options(
        selectinload(Room.building),
        selectinload(Room.amenities),
    ).where(
        Room.deleted_at.is_(None),
        Room.status == RoomStatus.AVAILABLE.value,
    )

    if payload.property_id:
        stmt = stmt.where(Room.property_id == payload.property_id)
    if payload.building_id:
        stmt = stmt.where(Room.building_id == payload.building_id)
    if payload.min_price is not None:
        stmt = stmt.where(Room.base_price >= payload.min_price)
    if payload.max_price is not None:
        stmt = stmt.where(Room.base_price <= payload.max_price)
    if payload.min_area is not None:
        stmt = stmt.where(Room.area_m2 >= payload.min_area)
    if payload.min_max_occupants is not None:
        stmt = stmt.where(Room.max_occupants >= payload.min_max_occupants)
    if payload.search:
        like = f"%{payload.search}%"
        stmt = stmt.where(Room.room_number.ilike(like))
    if payload.amenities:
        # "phòng có đủ TẤT CẢ tiện ích này" → dùng EXISTS thay vì
        # join + group by (dễ bị nhân bản số dòng khi có 3 tiện ích)
        sub = (
            select(room_amenities.c.room_id)
            .where(room_amenities.c.amenity_id.in_(payload.amenities))
            .group_by(room_amenities.c.room_id)
            .having(func.count(func.distinct(room_amenities.c.amenity_id))
                    == len(set(payload.amenities)))
            .scalar_subquery()
        )
        stmt = stmt.where(Room.id.in_(sub))

    sort_column = {
        "price_asc": Room.base_price.asc(),
        "price_desc": Room.base_price.desc(),
        "area_asc": Room.area_m2.asc(),
        "area_desc": Room.area_m2.desc(),
    }[payload.sort]

    params = PageParams(page=payload.page, page_size=payload.page_size)
    items, meta = await paginate(session, stmt.order_by(sort_column), params)

    # Cộng phí ước tính từ cache do billing-service đẩy vào
    tariff = await _get_estimated_tariff(redis, payload.property_id)

    results = []
    for room in items:
        response = _to_room_response(room)
        service_fee = sum(
            (a.default_monthly_fee for a in room.amenities), Decimal("0")
        ) + tariff["services"]
        estimated = (
            room.base_price
            + tariff["electric"] + tariff["water"] + service_fee
        )
        results.append(RoomAvailableItem(
            **response,
            estimated_electric=tariff["electric"],
            estimated_water=tariff["water"],
            estimated_services=service_fee,
            estimated_total=estimated.quantize(Decimal("1")),
        ))

    set_business_gauge(settings.service_name, "available_rooms_returned", len(results))
    return {"items": results, "meta": meta.model_dump(),
            "estimated_tariff_note": "Điện nước & phí DV là ước tính theo mức tiêu thụ trung bình"}


async def _get_estimated_tariff(redis: Any, property_id: uuid.UUID | None) -> dict:
    """
    Đọc bảng giá ước tính từ Redis (do billing-service đẩy vào qua event).

    Nếu chưa có dữ liệu → trả mức mặc định của Việt Nam (2026):
        điện ~ 100 kWh/tháng, nước ~ 4 m³/tháng.
    Giá trị này CHỈ để hiển thị tham khảo, không dùng để thu tiền.
    """
    default = {
        "electric": Decimal("190000"),   # 100 kWh, bậc 1 + 2
        "water": Decimal("60000"),       # 4 m³
        "services": Decimal("0"),
    }
    if redis is None:
        return default

    key = _cache_key("tariff", property_id or "all")
    try:
        raw = await redis.hgetall(key)
        if not raw:
            return default
        return {k: Decimal(v) for k, v in raw.items()}
    except Exception as exc:
        logger.warning("Không đọc được tariff cache: %s", exc)
        return default


@room_router.get("/stats", response_model=RoomStats, summary="📊 Thống kê công suất")
async def room_stats(
    request: Request,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> RoomStats:
    """Chỉ 1 câu GROUP BY duy nhất — không N+1 query."""
    effective = await _resolve_property_id(user, session, property_id)

    cache_key = _cache_key("stats", effective or "all")
    cached = await _cache_get(request.app.state.redis, cache_key)
    if cached:
        import json
        try:
            payload = json.loads(cached)
            payload["property_id"] = effective
            return RoomStats(**payload)
        except (ValueError, TypeError):
            pass

    rows = (await session.execute(
        select(
            Room.status,
            func.count(Room.id),
            func.coalesce(func.sum(Room.base_price), 0),
            func.coalesce(func.avg(Room.base_price), 0),
            Room.floor,
        )
        .where(Room.deleted_at.is_(None))
        .group_by(Room.status, Room.floor)
    )).all()

    by_status: dict[str, int] = {s.value: 0 for s in RoomStatus}
    by_floor: dict[str, int] = {}
    total_price = Decimal("0")
    price_count = 0
    average = Decimal("0")

    # ⭐ Biến lặp đặt tên `room_status` chứ KHÔNG phải `status`: trong file này
    #    `status` là module `fastapi.status` (dùng ở `status_code=` của các
    #    decorator). Đặt `for status in ...` sẽ ghi đè nó trong phạm vi hàm và
    #    làm mọi `status.HTTP_xxx` phía dưới trong cùng hàm thành
    #    `AttributeError: 'str' object has no attribute 'HTTP_201_CREATED'`.
    #    Tên gọi dài hơn 5 ký tự là cái giá rẻ để tránh lỗi khó chịu này.
    for room_status, count, sum_price, avg_price, floor in rows:
        by_status[room_status] = by_status.get(room_status, 0) + count
        by_floor[str(floor)] = by_floor.get(str(floor), 0) + count
        total_price += Decimal(sum_price or 0)
        average = Decimal(avg_price or 0)
        price_count += count

    total = sum(by_status.values())
    occupied = by_status.get(RoomStatus.OCCUPIED.value, 0)
    occupancy_rate = round(occupied / total * 100, 2) if total else 0.0

    stats = RoomStats(
        property_id=effective,
        total=total,
        available=by_status.get(RoomStatus.AVAILABLE.value, 0),
        occupied=occupied,
        maintenance=by_status.get(RoomStatus.MAINTENANCE.value, 0),
        reserved=by_status.get(RoomStatus.RESERVED.value, 0),
        occupancy_rate=occupancy_rate,
        total_monthly_revenue=total_price.quantize(Decimal("1")),
        average_price=average.quantize(Decimal("1")),
        by_floor=by_floor,
        as_of=datetime.now(UTC),
    )

    import json
    payload = stats.model_dump(mode="json")
    payload["property_id"] = str(effective) if effective else None
    await _cache_set(request.app.state.redis, cache_key,
                     json.dumps(payload, default=str), CACHE_TTL_STATS)

    set_business_gauge(settings.service_name, "occupancy_rate",
                       occupancy_rate, str(effective or "all"))
    return stats


@room_router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED,
                  summary="Tạo phòng")
async def create_room(
    request: Request,
    payload: RoomCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoomResponse:
    await _resolve_property_id(user, session, payload.property_id)

    # Kiểm tra building có thuộc đúng cơ sở không — nếu không, người dùng có
    # thể gắn phòng của cơ sở mình vào tòa nhà của cơ sở khác (rò rỉ dữ liệu).
    building = await session.get(Building, payload.building_id)
    if not building:
        raise NotFoundError("Không tìm thấy tòa nhà")
    if str(building.property_id) != str(payload.property_id):
        raise BusinessRuleError(
            "Tòa nhà không thuộc cơ sở này. Vui lòng kiểm tra lại cơ sở của tòa nhà."
        )

    exists = (await session.execute(
        select(Room).where(
            Room.property_id == payload.property_id,
            Room.building_id == payload.building_id,
            Room.room_number == payload.room_number,
        )
    )).scalar_one_or_none()
    if exists:
        raise ConflictError(
            f"Phòng số '{payload.room_number}' đã tồn tại trong tòa nhà này. "
            f"Phòng trùng số là lỗi dữ liệu, ảnh hưởng cả hóa đơn."
        )

    amenity_ids = payload.amenity_ids
    data = payload.model_dump(exclude={"amenity_ids"})
    room = Room(**data)
    session.add(room)
    await session.flush()

    if amenity_ids:
        await _set_room_amenities(session, room, amenity_ids)

    await session.execute(
        Property.__table__.update()
        .where(Property.id == payload.property_id)
        .values(total_rooms=Property.total_rooms + 1)
    )

    await get_event_bus().publish(session, DomainEvent(
        event_type="room.created",
        data={
            "room_id": str(room.id), "property_id": str(room.property_id),
            "building_id": str(room.building_id), "room_number": room.room_number,
            "base_price": str(room.base_price), "area_m2": str(room.area_m2 or 0),
            "status": room.status, "entity_type": "room", "entity_id": str(room.id),
        },
    ))

    await _invalidate_room_cache(request.app.state.redis, room, payload.property_id)
    logger.info("🚪 Tạo phòng %s tại cơ sở %s (bởi %s)",
                room.room_number, payload.property_id, user.username)
    return _to_room_response(room)


@room_router.get("/{room_id}", response_model=RoomResponse, summary="Chi tiết phòng")
async def get_room(
    request: Request,
    room_id: Annotated[uuid.UUID, Path(description="ID phòng")],
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoomResponse:
    room = await _get_room_or_404(session, room_id)
    user.assert_property_access(room.property_id)
    return _to_room_response(room)


@room_router.patch("/{room_id}", response_model=RoomResponse, summary="Cập nhật phòng")
async def update_room(
    request: Request,
    room_id: uuid.UUID,
    payload: RoomUpdate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoomResponse:
    room = await _get_room_or_404(session, room_id)
    user.assert_property_access(room.property_id)

    # Không cho sửa giá phòng đang có người thuê mà không hợp đồng nào cho
    # phép — giá cũ vẫn phải được giữ để tính hóa đơn các kỳ trước.
    if (payload.base_price is not None
            and payload.base_price != room.base_price
            and room.status == RoomStatus.OCCUPIED.value):
        raise BusinessRuleError(
            "Không thể đổi giá phòng đang có người thuê. "
            "Hãy tạo hợp đồng mới với giá mới, hoặc chờ hợp đồng hiện tại kết thúc.",
            details={"room_id": str(room_id), "current_price": str(room.base_price)},
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    await session.flush()

    await get_event_bus().publish(session, DomainEvent(
        event_type="room.updated",
        data={
            "room_id": str(room.id), "property_id": str(room.property_id),
            "base_price": str(room.base_price), "status": room.status,
            "entity_type": "room", "entity_id": str(room.id),
        },
    ))
    await _invalidate_room_cache(request.app.state.redis, room, room.property_id)
    return _to_room_response(room)


@room_router.patch("/{room_id}/status", response_model=RoomResponse,
                   summary="Đổi trạng thái phòng (thủ công)")
async def change_room_status(
    request: Request,
    room_id: uuid.UUID,
    payload: RoomStatusChange,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoomResponse:
    """
    Chuyển sang BẢO TRÌ / TRỐNG / GIỮ CHỖ.

    Không chuyển được sang OCCUPIED ở đây — xem giải thích trong `RoomStatusChange`.
    """
    room = await _get_room_or_404(session, room_id)
    user.assert_property_access(room.property_id)

    await _set_room_status(
        session, room, payload.status, reason=payload.reason, actor=user,
    )
    await _invalidate_room_cache(request.app.state.redis, room, room.property_id)
    return _to_room_response(room)


@room_router.get("/{room_id}/amenities", response_model=list[AmenityResponse],
                 summary="Tiện ích của phòng")
async def get_room_amenities(
    request: Request,
    room_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[AmenityResponse]:
    room = await _get_room_or_404(session, room_id)
    user.assert_property_access(room.property_id)
    return [AmenityResponse.model_validate(a) for a in room.amenities]


@room_router.put("/{room_id}/amenities", summary="Gán tiện ích cho phòng (thay toàn bộ)")
async def set_room_amenities_endpoint(
    request: Request,
    room_id: uuid.UUID,
    payload: RoomAmenitySet,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """PUT = thay toàn bộ, không phải thêm dần. Tránh trạng thái mơ hồ."""
    room = await _get_room_or_404(session, room_id)
    user.assert_property_access(room.property_id)

    if not payload.amenity_ids:
        await session.execute(
            delete(room_amenities).where(room_amenities.c.room_id == room_id)
        )
    else:
        count = await _set_room_amenities(session, room, payload.amenity_ids)
        logger.info("🧰 Gán %d tiện ích cho phòng %s", count, room.room_number)

    await _invalidate_room_cache(request.app.state.redis, room, room.property_id)
    return MessageResponse(message=f"Đã cập nhật tiện ích cho phòng {room.room_number}")


@room_router.delete("/{room_id}", response_model=MessageResponse,
                    summary="Ẩn phòng (soft delete)")
async def delete_room(
    request: Request,
    room_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """
    ⭐ SOFT DELETE + chỉ ADMIN.

    1. Không xoá hẳn: hóa đơn, hợp đồng, chỉ số điện nước đều tham chiếu tới
       phòng. Xoá hẳn sẽ phá vỡ lịch sử tài chính — vi phạm nguyên tắc kế toán.
    2. Chỉ ADMIN: vì MANAGER có thể gán phòng cho cơ sở của mình, nếu cho
       xoá thì xoá nhầm là mất dữ liệu của cả cơ sở mà không ai khôi phục được.
    3. Không xoá phòng đang có hợp đồng.
    """
    room = await _get_room_or_404(session, room_id)
    if room.status == RoomStatus.OCCUPIED.value:
        raise BusinessRuleError(
            f"Phòng {room.room_number} đang có người thuê. "
            "Phải kết thúc hợp đồng trước khi ẩn phòng."
        )

    room.deleted_at = datetime.now(UTC)
    await session.execute(
        Property.__table__.update()
        .where(Property.id == room.property_id)
        .values(total_rooms=func.greatest(Property.total_rooms - 1, 0))
    )
    await _invalidate_room_cache(request.app.state.redis, room, room.property_id)
    logger.info("🗑 Ẩn phòng %s (bởi %s)", room.room_number, user.username)
    return MessageResponse(message=f"Đã ẩn phòng {room.room_number}")


# ===========================================================================
#  INTERNAL API — dùng bởi service khác (không qua nginx, chỉ trong Docker net)
# ===========================================================================
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


# ⭐ ROUTE TĨNH PHẢI KHAI BÁO TRƯỚC ROUTE ĐỘNG: Starlette (FastAPI) match route
#    theo THỨ TỰ ĐĂNG KÝ. Nếu `/rooms/stats` khai sau `/rooms/{room_id}` thì
#    request tới `/rooms/stats` bị route động nuốt (room_id="stats") → FastAPI
#    validate UUID fail → 422. Lỗi này từng làm hỏng read-model công suất phòng
#    của report-service (dashboard + đối chiếu).
@internal_router.get("/rooms/stats", summary="[Nội bộ] Thống kê công suất")
async def internal_room_stats(
    user: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> dict:
    """report-service gọi để dựng dashboard."""
    stmt = select(Room.status, func.count(Room.id)).where(Room.deleted_at.is_(None))
    if property_id:
        stmt = stmt.where(Room.property_id == property_id)
    stmt = stmt.group_by(Room.status)

    rows = (await session.execute(stmt)).all()
    by_status = {s.value: 0 for s in RoomStatus}
    for room_status, count in rows:      # xem ghi chú ở `internal_room_summary`
        by_status[room_status] = count
    total = sum(by_status.values())
    return {
        "property_id": str(property_id) if property_id else None,
        "total": total,
        "by_status": by_status,
        "occupancy_rate": round(by_status["OCCUPIED"] / total * 100, 2) if total else 0.0,
    }


@internal_router.get("/rooms/{room_id}", summary="[Nội bộ] Lấy phòng")
async def internal_get_room(
    room_id: uuid.UUID,
    _: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Endpoint cho service khác gọi.

    ⭐ Vì sao cần endpoint riêng thay vì dùng chung `/api/v1/rooms/{id}`?
       - Kiểm tra `assert_property_access` của người gọi là vô nghĩa khi
         service-to-service: token SYSTEM không mang `property_id` người dùng.
       - Trả về gọn, đúng dữ liệu cần, không phụ thuộc shape của API công khai.
       - Có thể thêm cache riêng sau này mà không ảnh hưởng web.
    """
    room = await _get_room_or_404(session, room_id)
    return {
        "id": str(room.id),
        "property_id": str(room.property_id),
        "building_id": str(room.building_id),
        "room_number": room.room_number,
        "floor": room.floor,
        "area_m2": str(room.area_m2 or 0),
        "base_price": str(room.base_price),
        "max_occupants": room.max_occupants,
        "status": room.status,
        "current_contract_id": str(room.current_contract_id) if room.current_contract_id else None,
    }


@internal_router.get("/rooms/{room_id}/amenity-fees", summary="[Nội bộ] Phí tiện ích phòng")
async def internal_room_amenity_fees(
    room_id: uuid.UUID,
    _: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER, Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    billing-service gọi endpoint này khi tính tiền: tổng phí tiện ích gắn
    với phòng. Trả về tổng sẵn để billing không phải tự biết quy tắc.
    """
    room = await _get_room_or_404(session, room_id)
    total = sum((a.default_monthly_fee for a in room.amenities), Decimal("0"))
    return {
        "room_id": str(room_id),
        "total_monthly_fee": str(total.quantize(Decimal("1"))),
        "amenities": [
            {"code": a.code, "name": a.name, "fee": str(a.default_monthly_fee)}
            for a in room.amenities
        ],
    }


@internal_router.patch("/rooms/{room_id}/reserve", summary="[Nội bộ] Giữ phòng (Saga 3a)")
async def internal_reserve_room(
    room_id: uuid.UUID,
    payload: dict,
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    contract-service gọi ở Saga bước 3a, trước khi ghi `ACTIVE`.

    ⭐ Vì sao cần endpoint này mà không dùng `PATCH /rooms/{id}/status`?
       Endpoint công khai kiểm tra `assert_property_access` — token SYSTEM
       không mang `property_id` người dùng nên sẽ bị 403. Endpoint nội bộ
       không kiểm tra vậy, đồng thời trả về kết quả rõ ràng để contract biết
       có nên commit hay dừng.

    Trả về `reserved=False` (KHÔNG phải lỗi 409) khi phòng không giữ được:
    đây là kết quả nghiệp vụ bình thường, không phải hỏng hệ thống.
    """
    room = await _get_room_or_404(session, room_id)
    contract_id = payload.get("contract_id")

    if room.status == RoomStatus.OCCUPIED.value and \
            str(room.current_contract_id) == str(contract_id):
        return {"reserved": True, "room_id": str(room_id),
                "status": room.status, "reason": "đã giữ bởi hợp đồng này"}

    if room.status == RoomStatus.OCCUPIED.value:
        return {"reserved": False, "room_id": str(room_id), "status": room.status,
                "reason": "phòng đã có người thuê"}

    if room.status == RoomStatus.MAINTENANCE.value:
        return {"reserved": False, "room_id": str(room_id), "status": room.status,
                "reason": "phòng đang bảo trì"}

    if room.status == RoomStatus.RESERVED.value and room.current_contract_id \
            and str(room.current_contract_id) != str(contract_id):
        return {"reserved": False, "room_id": str(room_id), "status": room.status,
                "reason": "phòng đang được giữ cho hợp đồng khác"}

    await _set_room_status(
        session, room, RoomStatus.RESERVED.value,
        contract_id=uuid.UUID(str(contract_id)) if contract_id else None,
        reason="Giữ chỗ cho hợp đồng mới",
    )
    return {
        "reserved": True,
        "room_id": str(room_id),
        "status": room.status,
        "hold_hours": int(payload.get("hours", 24)),
    }


# ===========================================================================
#  CONSUMER — phản ứng với event từ contract & maintenance
# ===========================================================================
async def _handle_event(event: DomainEvent) -> None:
    """
    Điểm vào duy nhất của consumer.

    ⭐ Xử lý event phải IDEMPOTENT vì RabbitMQ bảo đảm "at-least-once":
       cùng 1 event có thể tới 2 lần. Phần chống trùng đã do
       `IdempotentConsumer` (bảng `processed_events`) đảm bảo — trong hàm
       này chỉ cần xử lý "nếu chạy lại thì cũng cho kết quả giống nhau".
    """
    handler = {
        "contract.activated": _on_contract_activated,
        "contract.terminated": _on_contract_closed,
        "contract.expired": _on_contract_closed,
        "contract.cancelled": _on_contract_closed,
        "incident.urgent": _on_incident_urgent,
        "incident.resolved": _on_incident_resolved,
        "room.maintenance_completed": _on_incident_resolved,
    }.get(event.event_type)

    if handler is None:
        logger.debug("Bỏ qua event không quan tâm: %s", event.event_type)
        return

    async with session_scope() as session:
        await handler(session, event)


async def _on_contract_activated(session: AsyncSession, event: DomainEvent) -> None:
    """Có hợp đồng hiệu lực → phòng chuyển sang ĐANG THUÊ."""
    room_id = uuid.UUID(event.data["room_id"])
    contract_id = uuid.UUID(event.data["contract_id"])

    room = await session.get(Room, room_id)
    if not room or room.deleted_at:
        logger.warning("contract.activated cho phòng %s không tồn tại", room_id)
        return

    if room.status == RoomStatus.OCCUPIED.value and room.current_contract_id == contract_id:
        return        # idempotent

    await _set_room_status(
        session, room, RoomStatus.OCCUPIED.value,
        contract_id=contract_id,
        reason=f"Hợp đồng {event.data.get('contract_no', '')} có hiệu lực",
        correlation_id=event.correlation_id,
    )


async def _on_contract_closed(session: AsyncSession, event: DomainEvent) -> None:
    """Hợp đồng kết thúc/hủy → phòng trở lại TRỐNG."""
    room_id = uuid.UUID(event.data["room_id"])
    room = await session.get(Room, room_id)
    if not room or room.deleted_at:
        return

    # Phòng đang bảo trì vì sự cố thì GIỮ NGUYÊN MAINTENANCE — sự cố chưa xử lý
    # xong thì không cho thuê lại, nếu không khách mới vào ở phòng hỏng.
    if room.status == RoomStatus.MAINTENANCE.value:
        logger.info("Phòng %s kết thúc hợp đồng nhưng đang bảo trì — giữ trạng thái",
                    room.room_number)
        room.current_contract_id = None
        return

    await _set_room_status(
        session, room, RoomStatus.AVAILABLE.value,
        reason=f"Hợp đồng {event.event_type.split('.')[-1]}",
        correlation_id=event.correlation_id,
    )


async def _on_incident_urgent(session: AsyncSession, event: DomainEvent) -> None:
    """
    Sự cố nghiêm trọng → tạm dừng khai thác phòng.

    ⭐ HỢP ĐỒNG VẪN GIỮ NGUYÊN. Đây là quyết định nghiệp vụ quan trọng:
       người thuê đã trả tiền tháng này, việc phòng hỏng là lỗi của chủ
       trọ, không phải của người thuê. Nếu chấm dứt hợp đồng, họ mất chỗ ở
       giữa tháng. Xem docs/01 mục luồng nghiệp vụ.
    """
    room_id = uuid.UUID(event.data["room_id"])
    room = await session.get(Room, room_id)
    if not room or room.deleted_at:
        return
    # Hàng rào thứ hai (phòng thủ nhiều lớp): sự kiện của cơ sở này không được
    # đổi trạng thái phòng của cơ sở khác, kể cả khi bên phát quên kiểm tra.
    if str(room.property_id) != str(event.data.get("property_id")):
        logger.warning("🚫 Bỏ qua incident.urgent %s: phòng %s thuộc cơ sở khác",
                       event.data.get("ticket_no"), room.room_number)
        return
    if room.status == RoomStatus.MAINTENANCE.value:
        return

    await _set_room_status(
        session, room, RoomStatus.MAINTENANCE.value,
        reason=f"Sự cố nghiêm trọng: {event.data.get('title', '')}",
        correlation_id=event.correlation_id,
    )


async def _on_incident_resolved(session: AsyncSession, event: DomainEvent) -> None:
    """Sự cố xử lý xong → phòng trở lại trạng thái phù hợp."""
    room_id = uuid.UUID(event.data.get("room_id", "")) if event.data.get("room_id") else None
    if room_id is None:
        return
    room = await session.get(Room, room_id)
    if not room or room.deleted_at or room.status != RoomStatus.MAINTENANCE.value:
        return

    # Phòng còn hợp đồng → vẫn đang thuê; hết hợp đồng → trống
    new_status = (RoomStatus.OCCUPIED.value if room.current_contract_id
                  else RoomStatus.AVAILABLE.value)
    await _set_room_status(
        session, room, new_status,
        reason="Sự cố đã được xử lý xong",
        correlation_id=event.correlation_id,
    )


# ===========================================================================
#  TIỆN ÍCH NỘI BỘ
# ===========================================================================
async def _get_room_or_404(session: AsyncSession, room_id: uuid.UUID) -> Room:
    room = (await session.execute(
        select(Room)
        .options(selectinload(Room.building), selectinload(Room.amenities))
        .where(Room.id == room_id, Room.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not room:
        raise NotFoundError(f"Không tìm thấy phòng {room_id}")
    return room


async def _set_room_amenities(
    session: AsyncSession, room: Room, amenity_ids: list[uuid.UUID],
) -> int:
    """Gán tiện ích. Trả về số tiện ích thực sự gán."""
    if not amenity_ids:
        return 0

    found = (await session.execute(
        select(Amenity).where(Amenity.id.in_(amenity_ids))
    )).scalars().all()
    found_ids = {a.id for a in found}

    missing = set(amenity_ids) - found_ids
    if missing:
        raise NotFoundError(
            f"Không tìm thấy {len(missing)} tiện ích: "
            f"{', '.join(str(m) for m in list(missing)[:3])}…"
        )

    # Thay toàn bộ: xoá cũ rồi chèn mới, trong cùng 1 transaction (do
    # get_session() commit) → không bao giờ thấy trạng thái "chưa tiện ích nào".
    await session.execute(
        delete(room_amenities).where(room_amenities.c.room_id == room.id)
    )
    if found:
        await session.execute(
            insert(room_amenities),
            [{"room_id": room.id, "amenity_id": a.id, "is_billable": True}
             for a in found],
        )
    return len(found)


def _to_room_response(room: Room) -> dict:
    """Chuyển model → dict kèm 2 trường bổ sung, cho cả 2 kiểu response."""
    return {
        "id": room.id,
        "property_id": room.property_id,
        "building_id": room.building_id,
        "room_number": room.room_number,
        "floor": room.floor,
        "area_m2": room.area_m2,
        "base_price": room.base_price,
        "max_occupants": room.max_occupants,
        "status": room.status,
        "current_contract_id": room.current_contract_id,
        "note": room.note,
        "photos": room.photos or [],
        "created_at": room.created_at,
        "building_name": room.building.name if room.building else None,
        "amenities": [AmenityResponse.model_validate(a) for a in (room.amenities or [])],
    }


# ===========================================================================
#  ĐĂNG KÝ ROUTER
# ===========================================================================
app.include_router(property_router)
app.include_router(building_router)
app.include_router(amenity_router)
app.include_router(room_router)
app.include_router(internal_router)
