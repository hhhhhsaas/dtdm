"""
================================================================================
maintenance-service — Sự cố & bảo trì.        Cổng 8007  |  db_maintenance
================================================================================

Bốn điểm đáng chú ý:

  1. SAGA "SỰ CỐ NGHIÊM TRỌNG" — chỉ `URGENT` mới được dừng phòng, và
     TUYỆT ĐỐI không kết thúc hợp đồng. Xem `_escalate_to_urgent`.
  2. `RESOLVED` ≠ `CLOSED` — thợ báo xong khác với quản lý chốt lại.
  3. Ảnh lưu MinIO, DB chỉ giữ OBJECT KEY (không phải URL có thời hạn).
  4. Job nền quét lịch bảo trì đến hạn → tự tạo phiếu.

Sơ đồ luồng nghiệp vụ chính:

```mermaid
sequenceDiagram
    autonumber
    participant T as Người thuê
    participant MS as maintenance
    participant MINIO as MinIO
    participant RB as RabbitMQ
    participant RS as room-service
    participant NT as notification

    T->>MS: POST /incidents (ảnh đã upload)
    MS->>MINIO: lưu ảnh → trả object key
    MS->>MS: tạo phiếu SC-2026-0001, status=OPEN
    MS->>RB: incident.created
    RB->>NT: báo cho quản lý

    Note over MS,RS: Khi nâng lên URGENT (rò rỉ, cháy, mất điện)
    MS->>RB: incident.urgent
    RB->>RS: phòng → MAINTENANCE (HĐ giữ nguyên)
    RB->>NT: báo người thuê "tạm dừng khai thác"

    Note over MS: Thợ sửa xong
    MS->>RB: incident.resolved
    RB->>RS: phòng → OCCUPIED/AVAILABLE
```
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common import (
    BusinessRuleError,
    ConflictError,
    CurrentUser,
    MessageResponse,
    NotFoundError,
    PageParams,
    Role,
    ServiceUnavailableError,
    apply_sort,
    create_service_app,
    get_db,
    get_event_bus,
    get_http_client,
    paginate,
    record_business_event,
    require_roles,
)
from common.config import settings
from common.database import session_scope
from common.events import DomainEvent, IdempotentConsumer
from common.repository import acquire_lock, next_sequence, release_lock
from common.telemetry import set_business_gauge
from models import (
    DONE_STATUSES,
    Incident,
    IncidentCategory,
    IncidentPriority,
    IncidentStatus,
    MaintenanceSchedule,
)
from schemas import (
    IncidentAssign,
    IncidentClose,
    IncidentCreate,
    IncidentListItem,
    IncidentRating,
    IncidentResolve,
    IncidentResponse,
    IncidentStats,
    IncidentUpdate,
    ScheduleComplete,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
)

logger = logging.getLogger(__name__)

#: Bucket con cho ảnh sự cố — tách khỏi ảnh CCCD (dữ liệu nhạy cảm hơn nhiều).
#: Ranh giới quyền truy cập ở tầng hạ tầng rẻ hơn nhiều so với dựa vào tiền tố
#: tên file trong cùng 1 bucket.
MEDIA_BUCKET_SUFFIX = "-incidents"

#: TTL cache thông tin phòng (số phòng, cơ sở). Phòng đổi tên rất hiếm.
CACHE_TTL_ROOM = 600

#: Chu kỳ quét lịch bảo trì đến hạn (giây). 1 giờ là quá đủ: việc bảo trì
#: tháng không cần độ trễ 1 phút, mà quét dày chỉ tốn truy vấn DB vô ích.
SCAN_INTERVAL = 3600

#: TTL khoá phân tán khi quét lịch (giâng). Lớn hơn chu kỳ quét để 2 vòng
#: liên tiếp không chạy chồng nhau.
LOCK_TTL_SCAN = SCAN_INTERVAL + 300

#: Kích thước ảnh tối đa: 8 MB. Ảnh sự cố chụp bằng điện thoại nén tốt
#: thường dưới 2 MB; 8 MB là trần hợp lý, chặn file 100 MB làm đầy bucket.
MAX_PHOTO_BYTES = 8 * 1024 * 1024

#: Định dạng ảnh cho phép. KHÔNG tin `content_type` do client gửi (có thể giả);
#: ta kiểm tra magic number thật sự của file.
ALLOWED_PHOTO_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}

#: Mã loại sự cố → tiếng Việt. Gửi "PLUMBING" cho người thuê là gửi mã kỹ
#: thuật; họ cần đọc "ống nước".
_CATEGORY_LABELS: dict[str, str] = {
    "PLUMBING": "ống nước",
    "ELECTRIC": "hệ thống điện",
    "APPLIANCE": "thiết bị trong phòng",
    "FURNITURE": "nội thất",
    "STRUCTURE": "kết cấu công trình",
    "PEST": "côn trùng, động vật gây hại",
    "GAS": "hệ thống gas",
    "OTHER": "khác",
}


# =================================================================================
#  CONSUMER — phản ứng với `room.status_changed`
#
#  ⭐ Định nghĩa TRƯỚC `create_service_app` vì `lifespan_extra` được đánh giá
#     ngay lúc gọi. Đảo thứ tự → NameError.
# =================================================================================
async def _setup_consumer(app_instance) -> None:
    consumer = IdempotentConsumer(
        handler=_handle_event, consumer_name="maintenance-service:room-events",
    )
    app_instance.state.ctx.consumers.append(consumer)
    try:
        await get_event_bus().subscribe(
            "qlpt.maintenance.events", consumer.handle, ["room.status_changed"],
        )
    except Exception as exc:
        logger.warning("Không đăng ký consumer được: %s", exc)


async def _handle_event(event: DomainEvent) -> None:
    handler = {
        "room.status_changed": _on_room_status_changed,
    }.get(event.event_type)
    if handler is None:
        return
    async with session_scope() as session:
        await handler(session, event)


async def _on_room_status_changed(session: AsyncSession, event: DomainEvent) -> None:
    """
    Phòng rời trạng thái MAINTENANCE mà phiếu sự cố vẫn còn URGENT chưa xử lý.

    ⭐ Đây là LƯỚI AN TOÀN (safety net), không phải luồng chính.
       Luồng chính là: thợ báo xong → `incident.resolved` → room-service mở
       lại phòng. Nhưng chủ trọ có thể tự tay đổi trạng thái phòng trên UI mà
       quên đóng phiếu sự cố. Khi đó báo cáo sẽ hiện "1 sự cố URGENT đang mở"
       mãi mãi dù phòng đã khai thác lại từ lâu — dữ liệu báo cáo sai.

       Ta tự đóng phiếu kèm ghi chú giải thích, thay vì để người đọc báo cáo
       phải tự nhận ra. Đây là dữ liệu SỰ KIỆN (đã xảy ra), nên ghi chú làm
       rõ là hoàn toàn hợp lý.
    """
    if event.data.get("to") == IncidentStatus.RESOLVED.value:
        return          # chưa cần, phòng chưa về khai thác

    room_id_raw = event.data.get("room_id")
    if not room_id_raw:
        return
    new_status = str(event.data.get("to") or "")
    if new_status == "MAINTENANCE":
        return          # vừa vào bảo trì — chuyện bình thường

    room_id = uuid.UUID(room_id_raw)
    open_urgent = (await session.execute(
        select(Incident).where(
            Incident.room_id == room_id,
            Incident.priority == IncidentPriority.URGENT.value,
            Incident.status.notin_(DONE_STATUSES),
            Incident.deleted_at.is_(None),
        )
    )).scalars().all()

    if not open_urgent:
        return

    now = datetime.now(UTC)
    for incident in open_urgent:
        incident.status = IncidentStatus.CLOSED.value
        incident.closed_at = now
        incident.resolution = (
            f"[Tự động] Phòng đã được đưa vào khai thác lúc "
            f"{now:%d/%m/%Y %H:%M} (trạng thái: {new_status}) mà phiếu chưa được "
            f"đóng. Lý do chuyển trạng thái: {event.data.get('reason') or '—'}"
        )
        logger.info(
            "🔒 Tự động đóng phiếu %s: phòng %s đã rời MAINTENANCE nhưng phiếu "
            "URGENT còn treo", incident.ticket_no, event.data.get("room_number"),
        )
        await _publish_event(
            session, "incident.resolved",
            {
                "incident_id": str(incident.id),
                "ticket_no": incident.ticket_no,
                "room_id": str(room_id),
                "property_id": str(incident.property_id),
                "auto_closed": True,
                "reason": event.data.get("reason"),
            },
            correlation_id=event.correlation_id,
        )
    record_business_event(settings.service_name, "incident.auto_closed")


# =================================================================================
#  APP
# =================================================================================
app = create_service_app(
    name="maintenance-service",
    description=(
        "**Sự cố & bảo trì**\n\n"
        "- Người thuê báo hư kèm ảnh (MinIO)\n"
        "- Điều phối xử lý: gán → xử lý → xong → đóng\n"
        "- Đánh giá MTTR (thời gian sửa trung bình)\n"
        "- Lịch bảo trì định kỳ, tự sinh phiếu khi đến hạn\n\n"
        "### Quy tắc nghiệp vụ quan trọng\n"
        "- Chỉ mức `URGENT` mới được tạm dừng khai thác phòng\n"
        "- Sự cố **không** kết thúc hợp đồng — người thuê đã trả tiền tháng này\n"
        "- Sự cố điện/gas/kết cấu bắt buộc có người ký xác nhận an toàn"
    ),
    version="1.0.0",
    lifespan_extra=_setup_consumer,
    # Job quét lịch bảo trì KHÔNG dùng scheduler mặc định của factory (vốn chỉ
    # in log mỗi 60s). Xem `_install_schedule_scanner` bên dưới.
    enable_scheduler=False,
)

# =================================================================================
#  JOB NỀN: QUÉT LỊCH BẢO TRÌ ĐẾN HẠN
# =================================================================================
# ⚠️  Phải chụp `lifespan_context` NGAY sau `create_service_app`. Nếu đọc lúc
#     chạy, ta sẽ nhận về chính wrapper này → lồng vô hạn.
_FACTORY_LIFESPAN = app.router.lifespan_context
_SCAN_TASK: asyncio.Task | None = None


def _install_schedule_scanner(app_instance) -> None:
    @asynccontextmanager
    async def _lifespan(inner):
        global _SCAN_TASK
        async with _FACTORY_LIFESPAN(inner):
            if settings.run_scheduler:
                _SCAN_TASK = asyncio.create_task(_scan_loop(inner))
                logger.info("   ✓ Job quét lịch bảo trì đã bật (chu kỳ %ss)",
                            SCAN_INTERVAL)
            try:
                yield
            finally:
                task, _SCAN_TASK = _SCAN_TASK, None
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    logger.info("   ✓ Job quét lịch bảo trì đã dừng")

    app_instance.router.lifespan_context = _lifespan


_install_schedule_scanner(app)


async def _scan_loop(app_instance) -> None:
    """
    Vòng lặp nền: tìm lịch bảo trì đến hạn và sinh phiếu tương ứng.

    ⭐ Khoá phân tán ở đây không phải cho đẹp. Khi scale maintenance lên 2
       replica, cả hai sẽ thấy cùng lịch đến hạn và cùng tạo phiếu → người
       thuê nhận 2 thông báo "bảo trì hôm nay". `SET NX` trên Redis đảm bảo
       mỗi lượt chỉ 1 tiến trình quét.
    """
    lock_name = "maintenance-schedule-scan"
    owner = f"{settings.service_name}:{uuid.uuid4().hex[:8]}"

    while True:
        try:
            redis = getattr(app_instance.state, "redis", None)
            if await acquire_lock(redis, lock_name, owner, ttl=LOCK_TTL_SCAN):
                try:
                    created = await _create_due_incidents()
                    if created:
                        logger.info("📅 Đã sinh %d phiếu bảo trì định kỳ", created)
                finally:
                    await release_lock(redis, lock_name, owner)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lỗi khi quét lịch bảo trì")
        await asyncio.sleep(SCAN_INTERVAL)


async def _create_due_incidents() -> int:
    """
    Sinh phiếu cho các lịch bảo trì đã tới hạn.

    ⭐ Mỗi lịch được xử lý trong transaction RIÊNG. Nếu gộp tất cả vào 1
       transaction, 1 lịch lỗi (ví dụ `room_id` không tồn tại ở room-service)
       làm HỎNG CẢ ĐỢT — 50 lịch còn lại cũng không tạo được phiếu.
    """
    async with session_scope() as session:
        due = (await session.execute(
            select(MaintenanceSchedule).where(
                MaintenanceSchedule.is_active.is_(True),
                MaintenanceSchedule.next_due_date <= date.today(),
                MaintenanceSchedule.deleted_at.is_(None),
            ).order_by(MaintenanceSchedule.next_due_date).limit(50)
        )).scalars().all()

    created = 0
    for schedule in due:
        try:
            async with session_scope() as one:
                if await _spawn_incident_from_schedule(one, schedule.id):
                    created += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            # Lỗi 1 lịch KHÔNG được làm sập cả vòng quét — lần sau sẽ thử lại.
            logger.exception("Không tạo được phiếu cho lịch %s", schedule.id)
    return created


async def _spawn_incident_from_schedule(
    session: AsyncSession, schedule_id: uuid.UUID,
) -> bool:
    """Tạo 1 phiếu bảo trì cho 1 lịch, rồi dời hạn sang kỳ tiếp theo."""
    schedule = await session.get(MaintenanceSchedule, schedule_id)
    if schedule is None or schedule.deleted_at or not schedule.is_active:
        return False
    if schedule.next_due_date > date.today():
        return False        # đã được xử lý bởi vòng quét khác

    room_number = None
    if schedule.target_id:
        room_number = await _room_number(schedule.target_id)

    tasks = [t.get("task", "") for t in (schedule.task_template or [])]
    incident = Incident(
        ticket_no=await _next_ticket_no(session),
        property_id=schedule.property_id,
        room_id=schedule.target_id if schedule.scope == "ROOM" else None,
        reported_by_user_id=None,
        reported_by_name=f"Bảo trì định kỳ: {schedule.title}",
        category=IncidentCategory.OTHER.value,
        priority=IncidentPriority.NORMAL.value,
        title=f"[Định kỳ] {schedule.title}",
        description=(
            "Lịch bảo trì định kỳ"
            + (f" — phòng {room_number}" if room_number else "")
            + ".\nDanh sách việc:\n"
            + "\n".join(f"  • {t}" for t in tasks)
        ),
        status=IncidentStatus.OPEN.value,
    )
    session.add(incident)
    await session.flush()

    schedule.last_done_at = datetime.now(UTC)
    schedule.times_completed += 1
    schedule.next_due_date = schedule.advance(schedule.next_due_date)
    await session.flush()

    await _publish_event(
        session, "incident.created",
        {
            "incident_id": str(incident.id),
            "ticket_no": incident.ticket_no,
            "property_id": str(incident.property_id),
            "room_id": str(incident.room_id) if incident.room_id else None,
            "room_number": room_number or "—",
            "title": incident.title,
            "category": incident.category,
            "priority": incident.priority,
            "reported_by": "Lịch bảo trì định kỳ",
            "scheduled": True,
        },
    )
    record_business_event(settings.service_name, "incident.scheduled")
    return True


# =================================================================================
#  TIỆN ÍCH
# =================================================================================
async def _next_ticket_no(session: AsyncSession) -> str:
    """
    Sinh mã phiếu `SC-2026-0042` — theo NĂM, không theo cơ sở.

    ⭐ Vì sao theo năm? Vì mã là thứ người thuê đọc qua điện thoại để tra
       cứu. `SC-0001` mà không có năm thì sau 2 năm sẽ có hai phiếu "SC-0001"
       ở hai cơ sở khác nhau, và ai cũng tra nhầm.
    """
    year = date.today().year
    seq = await next_sequence(
        session, "incidents", "ticket_no",
        "ticket_no LIKE :prefix", {"prefix": f"SC-{year}-%"},
    )
    return f"SC-{year}-{seq:04d}"


async def _room_number(room_id: uuid.UUID) -> str | None:
    """
    Tra số phòng từ room-service (nguồn chuẩn), có cache Redis 10 phút.

    ⭐ KHÔNG lưu bản sao `room_number` trong DB. Lý do: đổi tên phòng là việc
       có thật (gộp 2 phòng, đánh lại số theo mặt bằng mới). Bản sao sẽ lệch
       và hồ sơ sự cố cũ sẽ ghi sai — mà hồ sơ sự cố là bằng chứng, sai
       một chữ là mất giá trị.

    Trả `None` nếu room-service chết: sự cố vẫn tạo được, chỉ mất số phòng
    trong thông báo. Đây là lựa chọn CỐ Ý — không để hạ tầng phụ chặn nghiệp
    vụ chính.
    """
    cache_key = f"maint:room:{room_id}"
    try:
        redis = getattr(app.state, "redis", None)
        if redis is not None:
            cached = await redis.get(cache_key)
            if cached:
                return cached
    except Exception:
        pass        # Redis lỗi → bỏ qua cache, không được làm hỏng request

    try:
        info = await get_http_client("room").get(f"/internal/v1/rooms/{room_id}")
        number = info.get("room_number")
    except NotFoundError:
        number = None
    except Exception as exc:
        logger.warning("Không tra được phòng %s: %s", room_id, exc)
        return None

    if number:
        with suppress(Exception):
            redis = getattr(app.state, "redis", None)
            if redis is not None:
                await redis.set(cache_key, number, ex=CACHE_TTL_ROOM)
    return number


def _resolve_property(user: CurrentUser, requested: uuid.UUID | None) -> uuid.UUID | None:
    """ADMIN xem được tất cả; MANAGER bị khoá trong đúng cơ sở được gán."""
    if user.is_admin:
        return requested
    if user.property_id is None:
        raise BusinessRuleError("Tài khoản chưa được gán vào cơ sở nào")
    if requested is not None and str(requested) != str(user.property_id):
        user.assert_property_access(requested)
    return user.property_id


async def _get_incident_or_404(session: AsyncSession, incident_id: uuid.UUID) -> Incident:
    incident = (await session.execute(
        select(Incident).where(
            Incident.id == incident_id, Incident.deleted_at.is_(None)
        )
    )).scalar_one_or_none()
    if not incident:
        raise NotFoundError(f"Không tìm thấy phiếu sự cố {incident_id}")
    return incident


def _to_response(incident: Incident, room_number: str | None = None) -> IncidentResponse:
    return IncidentResponse(
        **{
            **{c.name: getattr(incident, c.name) for c in Incident.__table__.columns},
            "room_number": room_number,
            "is_open": incident.is_open,
            "is_safety_critical": incident.is_safety_critical,
            "resolution_hours": incident.resolution_hours,
        }
    )


def _to_list_item(incident: Incident, room_number: str | None) -> IncidentListItem:
    return IncidentListItem(
        id=incident.id,
        ticket_no=incident.ticket_no,
        room_number=room_number,
        reported_by_name=incident.reported_by_name,
        category=incident.category,
        priority=incident.priority,
        title=incident.title,
        status=incident.status,
        assigned_to_name=incident.assigned_to_name,
        created_at=incident.created_at,
        resolved_at=incident.resolved_at,
        resolution_hours=incident.resolution_hours,
        is_open=incident.is_open,
    )


async def _publish_event(
    session: AsyncSession, event_type: str, data: dict,
    correlation_id: str | None = None,
) -> None:
    """Bọc `publish` để không bao giờ làm hỏng transaction nghiệp vụ."""
    try:
        await get_event_bus().publish(
            session, DomainEvent(event_type=event_type, data=data,
                                 correlation_id=correlation_id),
        )
    except Exception as exc:
        # Event nằm trong outbox — publisher sẽ gửi lại sau. Việc ghi dữ liệu
        # nghiệp vụ vẫn thành công, đúng như thiết kế Outbox Pattern.
        logger.warning("Không ghi được event %s vào outbox: %s", event_type, exc)


def _minio_bucket() -> str:
    return f"{settings.minio_bucket}{MEDIA_BUCKET_SUFFIX}"


def _minio_client():
    """Tạo client MinIO khi cần (không giữ ở module scope để test được)."""
    from minio import Minio

    if not settings.minio_access_key or not settings.minio_secret_key.get_secret_value():
        raise BusinessRuleError(
            "Chưa cấu hình MinIO (MINIO_ACCESS_KEY/MINIO_SECRET_KEY) nên không "
            "upload được ảnh. Hãy gửi phiếu sự cố không kèm ảnh."
        )
    return Minio(
        settings.minio_endpoint.replace("http://", "").replace("https://", ""),
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
    )


def _sniff_image_type(data: bytes) -> str | None:
    """
    Đọc magic number để kiểm tra đúng là ảnh.

    ⭐ KHÔNG tin `UploadFile.content_type` — client gửi header này lên, tức là
       client kiểm soát được nó. Đây là lỗ hổng kinh điển: gửi
       `content_type: image/jpeg` nhưng thực tế là file `.sh` hay `.php`
       để lên web root. Kiểm tra chữ ký file là cách duy nhất đáng tin.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image/heic"
    return None


def _photo_object_key(property_id: uuid.UUID, filename: str, content_type: str) -> str:
    """
    Sinh object key có cấu trúc: `incidents/<property>/<năm>/<uuid>.<ext>`.

    ⭐ Dùng UUID thay vì tên file gốc vì 2 người có thể tải lên cùng tên
       `IMG_1234.jpg` (điện thoại đặt tên tự động) và sẽ đè lên nhau.
       Ngoài ra tên file gốc có thể chứa ký tự lạ / đường dẫn (`../`), giữ
       lại nó là mở cửa cho path traversal ở tầng đọc file sau này.
    """
    year = date.today().year
    return (f"incidents/{property_id}/{year}/"
            f"{uuid.uuid4().hex}{ALLOWED_PHOTO_TYPES[content_type]}")


def _days(count: int):
    """`timedelta` gọn hơn `datetime.timedelta` khi import chỉ dùng cho việc này."""
    from datetime import timedelta

    return timedelta(days=count)


async def _store_photo(file: UploadFile, property_id: uuid.UUID) -> str:
    """
    Lưu 1 ảnh lên MinIO và trả về object key.

    ⚠️  Kiểm tra thứ tự rất quan trọng: đọc và kiểm tra magic number TRƯỚC,
        rồi mới gọi MinIO. Nếu gọi MinIO trước rồi mới phát hiện file không
        phải ảnh, ta tốn 1 request mạng và để lại 1 file rác trong bucket.
    """
    data = await file.read()
    if not data:
        raise BusinessRuleError("Tệp rỗng")
    if len(data) > MAX_PHOTO_BYTES:
        raise BusinessRuleError(
            f"Ảnh nặng {len(data) / 1024 / 1024:.1f} MB, vượt giới hạn "
            f"{MAX_PHOTO_BYTES // (1024 * 1024)} MB. Hãy chụp ở độ phân giải thấp hơn."
        )

    content_type = _sniff_image_type(data)
    if content_type is None:
        raise BusinessRuleError(
            "Tệp tải lên không phải ảnh (jpg/png/webp/heic). "
            "Định dạng được chấp nhận được kiểm tra bằng chữ ký file, không tin "
            "Content-Type do trình duyệt gửi lên."
        )

    key = _photo_object_key(property_id, file.filename or "photo", content_type)
    client = _minio_client()
    bucket = _minio_bucket()
    if not await asyncio.to_thread(client.bucket_exists, bucket):
        await asyncio.to_thread(client.make_bucket, bucket)
        logger.info("📦 Đã tạo bucket MinIO '%s'", bucket)

    # `asyncio.to_thread`: thư viện `minio` là ĐỒNG BỘ (dùng urllib3 blocking).
    # Gọi thẳng trong coroutine sẽ chặn cả event loop trong thời gian upload —
    # mọi request khác của service phải đứng chờ, dù service có 8 CPU.
    await asyncio.to_thread(
        client.put_object, bucket, key, io.BytesIO(data), length=len(data),
        content_type=content_type,
    )
    logger.info("🖼  Đã lưu ảnh %s (%s, %.0f KB)", key, content_type, len(data) / 1024)
    return key


async def _room_info(room_id: uuid.UUID) -> dict:
    """Lấy thông tin phòng từ room-service (nguồn chuẩn), có cache."""
    cache_key = f"maint:room:{room_id}"
    try:
        redis = getattr(app.state, "redis", None)
        if redis is not None:
            cached = await redis.get(cache_key + ":info")
            if cached:
                return json.loads(cached)
    except Exception:
        pass

    info = await get_http_client("room").get(f"/internal/v1/rooms/{room_id}")
    with suppress(Exception):
        redis = getattr(app.state, "redis", None)
        if redis is not None:
            await redis.set(cache_key + ":info", json.dumps(info), ex=CACHE_TTL_ROOM)
    return info


async def _room_numbers(room_ids: list) -> dict[str, str]:
    """
    Tra số phòng cho N phòng, gom phần trùng lặp.

    ⭐ Dùng `gather` + dict cache trong lượt: danh sách 100 phiếu có thể chỉ
       nói tới 12 phòng khác nhau. Gọi 100 lần HTTP (hoặc 12 lần tuần tự)
       đều lãng phí. `gather` chạy đồng thời nên độ trễ = lần chậm nhất
       chứ không phải tổng.
    """
    unique = {str(r) for r in room_ids if r}
    if not unique:
        return {}

    result: dict[str, str] = {}

    async def _one(room_id: str) -> None:
        try:
            number = await _room_number(uuid.UUID(room_id))
            if number:
                result[room_id] = number
        except Exception as exc:
            logger.debug("Bỏ qua phòng %s: %s", room_id, exc)

    await asyncio.gather(*(_one(r) for r in unique))
    return result


async def _schedule_responses(rows: list[MaintenanceSchedule]) -> list[ScheduleResponse]:
    """Chuyển model lịch bảo trì → response, gắn số phòng nếu có."""
    numbers = await _room_numbers(
        [r.target_id for r in rows if r.scope == "ROOM" and r.target_id]
    )
    return [
        ScheduleResponse(
            **{c.name: getattr(r, c.name) for c in MaintenanceSchedule.__table__.columns},
            room_number=numbers.get(str(r.target_id)) if r.scope == "ROOM" else None,
            is_due=r.is_due,
            days_until_due=r.days_until_due(),
        )
        for r in rows
    ]


# =================================================================================
#  ROUTER: PHIẾU SỰ CỐ
# =================================================================================
incident_router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

#: Người thuê ĐƯỢC báo sự cố (đó là vai trò chính của họ trong hệ thống này).
REPORTER_ROLES = (Role.ADMIN, Role.MANAGER, Role.TENANT)


@incident_router.get("", summary="Danh sách phiếu sự cố")
async def list_incidents(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORTER_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    property_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status", description="Lọc theo trạng thái"),
    priority: str | None = None,
    category: str | None = None,
    assigned_to: uuid.UUID | None = None,
    is_open: bool | None = Query(None, description="True = chỉ phiếu chưa xử lý xong"),
    search: str | None = Query(None, description="Tìm theo mã phiếu hoặc tiêu đề"),
    sort: str = "created_at_desc",
) -> dict:
    effective = _resolve_property(user, property_id)

    stmt = select(Incident).where(Incident.deleted_at.is_(None))
    if effective:
        stmt = stmt.where(Incident.property_id == effective)
    # ⭐ Người thuê chỉ thấy phiếu của mình. Không có endpoint riêng cho họ
    #    vì bộ lọc này rẻ hơn nhiều so với nhân bản toàn bộ router.
    if user.role is Role.TENANT:
        stmt = stmt.where(Incident.reported_by_user_id == user.id)
    if room_id:
        stmt = stmt.where(Incident.room_id == room_id)
    if status_filter:
        stmt = stmt.where(Incident.status == status_filter)
    if priority:
        stmt = stmt.where(Incident.priority == priority)
    if category:
        stmt = stmt.where(Incident.category == category)
    if assigned_to:
        stmt = stmt.where(Incident.assigned_to == assigned_to)
    if is_open:
        stmt = stmt.where(Incident.status.notin_(DONE_STATUSES))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            Incident.ticket_no.ilike(like) | Incident.title.ilike(like)
        )

    stmt = apply_sort(
        stmt, Incident, sort,
        allowed={
            "created": "created_at", "priority": "priority",
            "status": "status", "resolved": "resolved_at",
        },
        default="created_at",
    )
    items, meta = await paginate(session, stmt, params)

    # Số phòng lấy từ room-service. Cache 10 phút nên 1 lần gọi cho mọi phòng
    # khác nhau, nhưng vẫn là N lần gọi HTTP với N phòng khác nhau.
    # Chấp nhận được: đây là danh sách quản trị, N nhỏ, và có circuit breaker.
    numbers = await _room_numbers([i.room_id for i in items if i.room_id])

    return {
        "items": [_to_list_item(i, numbers.get(str(i.room_id))) for i in items],
        "meta": meta.model_dump(),
    }


@incident_router.get("/stats", response_model=IncidentStats, summary="📊 Thống kê sự cố")
async def incident_stats(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORTER_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
    days: int = Query(30, ge=1, le=365, description="Khoảng thống kê (ngày gần nhất)"),
) -> IncidentStats:
    """
    Chỉ số bảo trì — đây là những con số chủ nhà thực sự quan tâm:
    bao lâu thì sửa xong 1 sự cố (MTTR), tốn bao nhiêu tiền, khách có hài
    lòng không.
    """
    effective = _resolve_property(user, property_id)
    since = datetime.now(UTC) - _days(days)

    base = select(Incident).where(
        Incident.deleted_at.is_(None), Incident.created_at >= since,
    )
    if effective:
        base = base.where(Incident.property_id == effective)
    ids = select(base.subquery().c.id)

    rows = (await session.execute(
        select(Incident.status, Incident.priority, Incident.category,
               func.count(Incident.id), func.coalesce(func.sum(Incident.cost), 0))
        .where(Incident.id.in_(ids))
        .group_by(Incident.status, Incident.priority, Incident.category)
    )).all()

    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_category: dict[str, int] = {}
    total = resolved = cancelled = 0
    total_cost = Decimal("0")
    for st, pri, cat, count, cost in rows:
        by_status[st] = by_status.get(st, 0) + count
        by_priority[pri] = by_priority.get(pri, 0) + count
        by_category[cat] = by_category.get(cat, 0) + count
        total += count
        total_cost += Decimal(str(cost or 0))
        if st in DONE_STATUSES:
            resolved += 1
        if st == IncidentStatus.CANCELLED.value:
            cancelled += 1

    # MTTR: chỉ tính phiếu ĐÃ xử lý xong. Phiếu đang mở không có
    # `resolved_at` nên đưa vào mẫu số sẽ ra con số vô nghĩa.
    times = (await session.execute(
        select(Incident.resolved_at, Incident.created_at).where(
            Incident.id.in_(ids), Incident.resolved_at.isnot(None),
        )
    )).all()
    avg_hours = (
        round(sum((r - c).total_seconds() / 3600 for r, c in times) / len(times), 2)
        if times else None
    )

    rating = (await session.execute(
        select(func.avg(Incident.rating)).where(
            Incident.id.in_(ids), Incident.rating.isnot(None),
        )
    )).scalar()

    overdue = sum(
        1 for st, pri, count, *_ in rows
        if st not in DONE_STATUSES and pri in ("URGENT", "HIGH")
    )

    stats = IncidentStats(
        property_id=effective, total=total, open=total - resolved - cancelled,
        resolved=resolved, cancelled=cancelled,
        by_status=by_status, by_priority=by_priority, by_category=by_category,
        overdue=overdue, avg_resolution_hours=avg_hours, total_cost=total_cost,
        avg_rating=round(float(rating), 2) if rating else None,
        as_of=datetime.now(UTC),
    )
    set_business_gauge(settings.service_name, "open_incidents", stats.open)
    return stats


@incident_router.post("", response_model=IncidentResponse,
                      status_code=status.HTTP_201_CREATED,
                      summary="📢 Báo sự cố")
async def create_incident(
    payload: IncidentCreate,
    user: Annotated[CurrentUser, Depends(require_roles(*REPORTER_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    """
    Người thuê báo hư — thao tác QUAN TRỌNG NHẤT của service này vì nó là
    điểm chạm đầu tiên của người dùng với hệ thống.

    ⭐ Không tra cứu trước phòng để kiểm tra quyền: gọi room-service thêm 1
       vòng HTTP chỉ để lấy `property_id` làm mất ~40ms vào mỗi lần báo hư.
       Thay vào đó ta dùng `property_id` của người dùng (MANAGER/TENANT đều
       đã được gán sẵn) và chỉ hỏi room-service khi admin tạo phiếu hộ.
    """
    property_id = user.property_id
    if user.is_admin and payload.room_id:
        info = await _room_info(payload.room_id)
        property_id = uuid.UUID(info["property_id"])
    if property_id is None:
        raise BusinessRuleError(
            "Không xác định được cơ sở. Vui lòng chọn cơ sở khi tạo phiếu."
        )

    # ⭐ `room_id` do client gửi lên → PHẢI thuộc đúng cơ sở của người báo.
    #    Không kiểm tra thì người thuê cơ sở A báo URGENT cho phòng cơ sở B
    #    và room-service sẽ dừng khai thác phòng đó. Đổi ~40ms lấy hàng rào
    #    ranh giới cơ sở là đáng.
    if payload.room_id and not user.is_admin:
        try:
            info = await _room_info(payload.room_id)
        except ServiceUnavailableError:
            # Không xác minh được → bỏ gắn phòng: phiếu vẫn tạo được nhưng
            # không thể kích hoạt việc dừng khai thác phòng.
            logger.warning("⚠️ room-service không phản hồi — bỏ room_id %s của phiếu mới",
                           payload.room_id)
            payload.room_id = None
        else:
            if str(info.get("property_id")) != str(property_id):
                raise NotFoundError("Không tìm thấy phòng này trong cơ sở của bạn")

    # Người thuê: không tin `reported_by_tenant_id` từ client (có thể báo hư
    # hộ nhà mình để gây phiền cơ sở khác). Luôn gán theo tài khoản đang đăng.
    reporter_name = payload.reported_by_name or user.username
    if user.role is Role.TENANT:
        payload.reported_by_tenant_id = None
        payload.reported_by_user_id = user.id
        reporter_name = user.username

    incident = Incident(
        ticket_no=await _next_ticket_no(session),
        property_id=property_id,
        room_id=payload.room_id,
        reported_by_tenant_id=payload.reported_by_tenant_id,
        reported_by_user_id=payload.reported_by_user_id,
        reported_by_name=reporter_name,
        reported_by_phone=payload.reported_by_phone,
        category=payload.category,
        priority=payload.priority,
        title=payload.title,
        description=payload.description,
        photos=list(payload.photos),
        status=IncidentStatus.OPEN.value,
    )
    session.add(incident)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            f"Không tạo được phiếu sự cố (mã bị trùng): {exc.orig}"
        ) from exc

    room_number = await _room_number(payload.room_id) if payload.room_id else None

    await _publish_event(
        session, "incident.created",
        {
            "incident_id": str(incident.id),
            "ticket_no": incident.ticket_no,
            "property_id": str(property_id),
            "room_id": str(incident.room_id) if incident.room_id else None,
            "room_number": room_number or "—",
            "title": incident.title,
            "category": incident.category,
            "category_label": _CATEGORY_LABELS.get(incident.category, incident.category),
            "priority": incident.priority,
            "reported_by": reporter_name,
            "reported_at": incident.created_at.isoformat(),
            "reported_by_phone": incident.reported_by_phone,
        },
    )
    # ⭐ Nâng URGENT ngay lúc tạo cũng phải dừng phòng. Nếu chờ đến lúc
    #    quản lý bấm "nâng cấp" thì có thể đã quá 30 phút.
    if incident.priority == IncidentPriority.URGENT.value:
        await _escalate_to_urgent(session, incident, room_number)

    record_business_event(settings.service_name, "incident.created")
    logger.info("📢 Phiếu %s: %s (%s) — %s", incident.ticket_no, incident.title,
                _CATEGORY_LABELS.get(incident.category, incident.category), reporter_name)
    return _to_response(incident, room_number)


@incident_router.get("/{incident_id}", response_model=IncidentResponse,
                    summary="Chi tiết phiếu sự cố")
async def get_incident(
    incident_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(*REPORTER_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)
    if user.role is Role.TENANT and incident.reported_by_user_id != user.id:
        raise NotFoundError("Không tìm thấy phiếu sự cố")
    return _to_response(
        incident, await _room_number(incident.room_id) if incident.room_id else None
    )


@incident_router.patch("/{incident_id}", response_model=IncidentResponse,
                      summary="Cập nhật phiếu (chưa đổi trạng thái)")
async def update_incident(
    incident_id: uuid.UUID,
    payload: IncidentUpdate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)

    if incident.status in DONE_STATUSES:
        raise BusinessRuleError(
            f"Phiếu {incident.ticket_no} đã {incident.status} nên không sửa được. "
            "Hãy mở lại phiếu trước khi cập nhật."
        )

    changes = payload.model_dump(exclude_unset=True)
    photos = changes.pop("photos", None)
    for field, value in changes.items():
        setattr(incident, field, value)
    if photos is not None:
        incident.photos = list(photos)
    await session.flush()

    # Đổi mức độ lên URGENT thì phải chạy hệ quả dừng phòng.
    if incident.priority == IncidentPriority.URGENT.value:
        room_number = await _room_number(incident.room_id) if incident.room_id else None
        await _escalate_to_urgent(session, incident, room_number)

    return _to_response(
        incident, await _room_number(incident.room_id) if incident.room_id else None
    )


@incident_router.post("/{incident_id}/assign", response_model=IncidentResponse,
                      summary="Gán người xử lý")
async def assign_incident(
    incident_id: uuid.UUID,
    payload: IncidentAssign,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)

    if incident.status in DONE_STATUSES:
        raise BusinessRuleError(f"Phiếu {incident.ticket_no} đã đóng")
    if incident.status == IncidentStatus.OPEN.value:
        incident.status = IncidentStatus.ASSIGNED.value

    incident.assigned_to = payload.user_id
    incident.assigned_to_name = payload.user_name
    incident.assigned_at = datetime.now(UTC)
    if payload.note:
        incident.resolution = (incident.resolution or "") + f"\n[Giao việc] {payload.note}"
    await session.flush()

    logger.info("👷 Gán phiếu %s cho %s", incident.ticket_no,
                payload.user_name or payload.user_id)
    record_business_event(settings.service_name, "incident.assigned")
    return _to_response(
        incident, await _room_number(incident.room_id) if incident.room_id else None
    )


@incident_router.post("/{incident_id}/start", response_model=IncidentResponse,
                      summary="Bắt đầu xử lý")
async def start_incident(
    incident_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)

    if incident.status in (IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value):
        raise BusinessRuleError(f"Phiếu {incident.ticket_no} đã xử lý xong")
    if incident.status == IncidentStatus.CANCELLED.value:
        raise BusinessRuleError(f"Phiếu {incident.ticket_no} đã bị huỷ")

    # ⭐ "Bắt đầu" là MỐC THỜI GIAN MTTR. Không dùng `created_at` làm mốc
    #    bắt đầu vì lúc đó người thuê mới báo, thợ còn chưa tới.
    incident.status = IncidentStatus.IN_PROGRESS.value
    incident.started_at = incident.started_at or datetime.now(UTC)
    if not incident.assigned_to:
        incident.assigned_to = user.id
        incident.assigned_to_name = user.username
    await session.flush()

    record_business_event(settings.service_name, "incident.started")
    return _to_response(
        incident, await _room_number(incident.room_id) if incident.room_id else None
    )


@incident_router.post("/{incident_id}/resolve", response_model=IncidentResponse,
                      summary="✅ Đánh dấu đã xử lý xong")
async def resolve_incident(
    incident_id: uuid.UUID,
    payload: IncidentResolve,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    """
    Thợ báo "xong". Chưa phải đóng phiếu — người thuê/quản lý còn phải xác nhận.

    ⭐ Sự cố điện/gas/kết cấu BẮT BUỘC có người ký xác nhận. Lý do nằm ở
       thực tế: một đường dây được thay nhưng bóc chưa đúng cách thì 3 tháng
       sau cháy, và lúc đó không ai chịu trách nhiệm vì hệ thống ghi "đã xử
       lý xong". Buộc có người ký biến việc xác nhận thành trách nhiệm có
       tên.
    """
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)

    if incident.status in (IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value):
        raise BusinessRuleError(f"Phiếu {incident.ticket_no} đã xử lý xong")
    if incident.status == IncidentStatus.CANCELLED.value:
        raise BusinessRuleError(f"Phiếu {incident.ticket_no} đã bị huỷ")

    if incident.is_safety_critical and not payload.verified_by:
        raise BusinessRuleError(
            f"Loại sự cố '{_CATEGORY_LABELS.get(incident.category, incident.category)}' "
            "là loại nguy hiểm (điện/gas/kết cấu) — bắt buộc phải có người ký "
            "xác nhận đã kiểm tra an toàn trước khi đánh dấu xong."
        )

    incident.status = IncidentStatus.RESOLVED.value
    incident.resolved_at = datetime.now(UTC)
    incident.resolution = payload.resolution
    if payload.cost is not None:
        incident.cost = payload.cost
    if payload.verified_by:
        who = payload.verified_by_name or str(payload.verified_by)
        incident.resolution += f"\n[Đã kiểm tra an toàn] {who}"
    await session.flush()

    room_number = await _room_number(incident.room_id) if incident.room_id else None
    await _publish_event(
        session, "incident.resolved",
        {
            "incident_id": str(incident.id),
            "ticket_no": incident.ticket_no,
            "property_id": str(incident.property_id),
            "room_id": str(incident.room_id) if incident.room_id else None,
            "room_number": room_number or "—",
            "title": incident.title,
            "resolution": incident.resolution[:500],
            "cost": str(incident.cost) if incident.cost is not None else None,
            "resolution_hours": incident.resolution_hours,
        },
    )
    record_business_event(settings.service_name, "incident.resolved")
    logger.info("✅ Phiếu %s xử lý xong sau %s giờ", incident.ticket_no,
                incident.resolution_hours)
    return _to_response(incident, room_number)


@incident_router.post("/{incident_id}/close", response_model=IncidentResponse,
                      summary="Đóng phiếu (chốt)")
async def close_incident(
    incident_id: uuid.UUID,
    payload: IncidentClose,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    """
    Chốt phiếu. Chỉ gọi được khi đã RESOLVED — `PATCH` cũng vậy.

    ⭐ Thêm bước chốt (thay vì RESOLVED là xong) là để bảo đảm không ai
       đóng phiếu khi thợ còn đang sửa dở. Nếu gộp, "thợ báo xong" và
       "phiếu đóng" là một sự kiện, mà thợ báo xong rồi bỏ ngang là
       chuyện rất hay xảy ra.
    """
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)

    if incident.status == IncidentStatus.CLOSED.value:
        raise ConflictError(f"Phiếu {incident.ticket_no} đã đóng từ trước")
    if incident.status == IncidentStatus.CANCELLED.value:
        raise BusinessRuleError(f"Phiếu {incident.ticket_no} đã bị huỷ")
    if incident.status != IncidentStatus.RESOLVED.value:
        raise BusinessRuleError(
            f"Phiếu {incident.ticket_no} chưa xử lý xong (đang {incident.status}). "
            "Hãy bấm 'Đánh dấu đã xử lý xong' trước khi đóng."
        )

    incident.status = IncidentStatus.CLOSED.value
    incident.closed_at = datetime.now(UTC)
    if payload.resolution:
        incident.resolution += f"\n[Chốt] {payload.resolution}"
    if payload.cost is not None:
        incident.cost = payload.cost
    if payload.close_reason:
        incident.resolution += f"\n[Lý do đóng] {payload.close_reason}"
    await session.flush()

    record_business_event(settings.service_name, "incident.closed")
    return _to_response(
        incident, await _room_number(incident.room_id) if incident.room_id else None
    )


@incident_router.post("/{incident_id}/cancel", response_model=IncidentResponse,
                      summary="Huỷ phiếu (báo nhầm)")
async def cancel_incident(
    incident_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    reason: str = Query(..., min_length=3, max_length=500, description="Lý do huỷ"),
) -> IncidentResponse:
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)

    if incident.status in DONE_STATUSES:
        raise BusinessRuleError(f"Phiếu {incident.ticket_no} đã đóng")
    incident.status = IncidentStatus.CANCELLED.value
    incident.resolution = f"[Huỷ] {reason}"
    incident.closed_at = datetime.now(UTC)
    await session.flush()

    record_business_event(settings.service_name, "incident.cancelled")
    return _to_response(
        incident, await _room_number(incident.room_id) if incident.room_id else None
    )


@incident_router.post("/{incident_id}/rating", response_model=IncidentResponse,
                      summary="⭐ Đánh giá (người thuê)")
async def rate_incident(
    incident_id: uuid.UUID,
    payload: IncidentRating,
    user: Annotated[CurrentUser, Depends(require_roles(*REPORTER_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    """
    Người thuê chấm điểm sau khi sự cố xử lý xong.

    ⭐ Ràng buộc: chỉ đánh giá được phiếu ĐÃ XỬ LÝ XONG. Chấm điểm cho phiếu
       đang mở là vô nghĩa và làm số liệu hài lòng sai.
    """
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)

    if incident.status not in DONE_STATUSES:
        raise BusinessRuleError(
            f"Phiếu {incident.ticket_no} chưa xử lý xong nên chưa thể đánh giá"
        )
    if user.role is Role.TENANT and incident.reported_by_user_id != user.id:
        raise NotFoundError("Không tìm thấy phiếu sự cố")
    if incident.rating is not None:
        raise ConflictError(f"Phiếu {incident.ticket_no} đã được đánh giá rồi")

    incident.rating = payload.rating
    incident.rating_comment = payload.comment
    await session.flush()

    record_business_event(settings.service_name, "incident.rated")
    return _to_response(
        incident, await _room_number(incident.room_id) if incident.room_id else None
    )


@incident_router.post("/{incident_id}/photos", response_model=IncidentResponse,
                      summary="📷 Thêm ảnh sự cố")
async def upload_incident_photo(
    incident_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="Ảnh chụp sự cố (jpg/png/webp/heic)")],
    user: Annotated[CurrentUser, Depends(require_roles(*REPORTER_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    incident = await _get_incident_or_404(session, incident_id)
    user.assert_property_access(incident.property_id)
    if user.role is Role.TENANT and incident.reported_by_user_id != user.id:
        raise NotFoundError("Không tìm thấy phiếu sự cố")
    if incident.status in DONE_STATUSES:
        raise BusinessRuleError(f"Phiếu {incident.ticket_no} đã đóng, không thêm ảnh")

    key = await _store_photo(file, incident.property_id)
    incident.photos = [*(incident.photos or []), key]
    await session.flush()

    return _to_response(
        incident, await _room_number(incident.room_id) if incident.room_id else None
    )


# =================================================================================
#  NÂNG CẤP SỰ CỐ → DỪNG KHAI THÁC PHÒNG
# =================================================================================
async def _escalate_to_urgent(
    session: AsyncSession, incident: Incident, room_number: str | None,
) -> None:
    """
    Sự cố nghiêm trọng → phát `incident.urgent`.

    ⭐ HỢP ĐỒNG KHÔNG BỊ ĐỤNG TỚI. Đây là quyết định nghiệp vụ quan trọng
       nhất của service này, và cũng là chỗ dễ sai nhất:

         Người thuê đã trả tiền tháng này. Phòng hỏng là lỗi của chủ trọ,
         không phải của họ. Nếu vì một vòi nước hỏng mà ta chấm dứt hợp
         đồng, họ mất chỗ ở giữa tháng — và không có nhà trọ nào khác nhận
         giữa kỳ. Chủ trọ mất tiền, người thuê mất nhà, hệ thống mất uy tín.

       Ta chỉ phóng sự kiện; room-service chuyển phòng sang MAINTENANCE và
       giữ nguyên hợp đồng. Quyết định "hậu quả nghiệp vụ" thuộc về service
       sở hữu hợp đồng, không phải service này.

    ⭐ `dedupe_key` không liên quan ở đây (chỉ notification-service dùng);
       ở đây chống gửi trùng bằng cách chỉ phát khi phiếu VỪA chuyển sang
       URGENT, không phát lại mỗi lần PATCH.
    """
    if not incident.room_id:
        logger.warning("⚠ Phiếu %s mức URGENT nhưng không có room_id — "
                       "không thể dừng phòng", incident.ticket_no)
        return

    await _publish_event(
        session, "incident.urgent",
        {
            "incident_id": str(incident.id),
            "ticket_no": incident.ticket_no,
            "property_id": str(incident.property_id),
            "room_id": str(incident.room_id),
            "room_number": room_number or "—",
            "title": incident.title,
            "category": incident.category,
            "category_label": _CATEGORY_LABELS.get(incident.category, incident.category),
            "reported_by": incident.reported_by_name,
            "reported_at": incident.created_at.isoformat(),
            "reported_by_phone": incident.reported_by_phone,
            # Cờ cho room-service biết KHÔNG được chấm dứt hợp đồng.
            "keep_contract": True,
        },
    )
    record_business_event(settings.service_name, "incident.urgent")
    logger.warning("🚨 Sự cố NGHIÊM TRỌNG %s — dừng khai thác phòng %s "
                   "(hợp đồng giữ nguyên)", incident.ticket_no, room_number)


# =================================================================================
#  ROUTER: LỊCH BẢO TRÌ ĐỊNH KỲ
# =================================================================================
schedule_router = APIRouter(prefix="/api/v1/maintenance-schedules",
                            tags=["maintenance-schedules"])


@schedule_router.get("", response_model=list[ScheduleResponse],
                     summary="Danh sách lịch bảo trì")
async def list_schedules(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    due_only: bool = Query(False, description="Chỉ lịch đã tới hạn"),
) -> list[ScheduleResponse]:
    effective = _resolve_property(user, property_id)
    stmt = select(MaintenanceSchedule).where(MaintenanceSchedule.deleted_at.is_(None))
    if effective:
        stmt = stmt.where(MaintenanceSchedule.property_id == effective)
    if is_active is not None:
        stmt = stmt.where(MaintenanceSchedule.is_active.is_(is_active))
    if due_only:
        stmt = stmt.where(MaintenanceSchedule.next_due_date <= date.today())

    rows = (await session.execute(
        stmt.order_by(MaintenanceSchedule.next_due_date)
    )).scalars().all()
    return await _schedule_responses(rows)


@schedule_router.post("", response_model=ScheduleResponse,
                      status_code=status.HTTP_201_CREATED,
                      summary="Tạo lịch bảo trì")
async def create_schedule(
    payload: ScheduleCreate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleResponse:
    user.assert_property_access(payload.property_id)
    if payload.scope == "ROOM":
        info = await _room_info(payload.target_id)
        if str(info["property_id"]) != str(payload.property_id):
            raise BusinessRuleError("Phòng này không thuộc cơ sở đã chọn")

    schedule = MaintenanceSchedule(**payload.model_dump())
    # Mốc neo lấy từ ngày hạn đầu tiên, trừ khi người dùng chỉ định rõ.
    schedule.anchor_day = payload.anchor_day or payload.next_due_date.day
    session.add(schedule)
    await session.flush()

    logger.info("📅 Tạo lịch bảo trì: %s (%s, hạn %s)", schedule.title,
                schedule.frequency, schedule.next_due_date)
    record_business_event(settings.service_name, "schedule.created")
    return (await _schedule_responses([schedule]))[0]


@schedule_router.get("/{schedule_id}", response_model=ScheduleResponse,
                     summary="Chi tiết lịch bảo trì")
async def get_schedule(
    schedule_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleResponse:
    schedule = (await session.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.id == schedule_id,
            MaintenanceSchedule.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not schedule:
        raise NotFoundError(f"Không tìm thấy lịch bảo trì {schedule_id}")
    user.assert_property_access(schedule.property_id)
    return (await _schedule_responses([schedule]))[0]


@schedule_router.patch("/{schedule_id}", response_model=ScheduleResponse,
                      summary="Cập nhật lịch bảo trì")
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleResponse:
    schedule = (await session.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.id == schedule_id,
            MaintenanceSchedule.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not schedule:
        raise NotFoundError(f"Không tìm thấy lịch bảo trì {schedule_id}")
    user.assert_property_access(schedule.property_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)
    await session.flush()
    return (await _schedule_responses([schedule]))[0]


@schedule_router.post("/{schedule_id}/complete", response_model=ScheduleResponse,
                      summary="✔ Đánh dấu đã thực hiện")
async def complete_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleComplete,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleResponse:
    """
    Đã làm xong lần bảo trì này → hệ thống tự dời hạn sang kỳ tiếp theo.

    ⭐ `times_completed` tăng lên là BẰNG CHỨNG quan trọng: khi có tranh chấp
       "anh có bảo trì định kỳ không", đây là thứ chủ trọ đưa ra được.
    """
    schedule = (await session.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.id == schedule_id,
            MaintenanceSchedule.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not schedule:
        raise NotFoundError(f"Không tìm thấy lịch bảo trì {schedule_id}")
    user.assert_property_access(schedule.property_id)

    performed_on = payload.performed_on or date.today()
    schedule.last_done_at = datetime.now(UTC)
    schedule.times_completed += 1
    schedule.next_due_date = payload.next_due_date or schedule.advance(performed_on)
    if payload.note:
        done = [
            f"{performed_on:%d/%m/%Y} — {p}"
            for p in (payload.performed_tasks or [])
        ]
        schedule.note = (schedule.note or "") + "\n" + "\n".join(done)
        if not payload.performed_tasks:
            schedule.note = (schedule.note or "") + f"\n{performed_on:%d/%m/%Y} — xong"
    await session.flush()

    logger.info("✔ Lịch '%s' hoàn thành, kỳ sau hạn %s", schedule.title,
                schedule.next_due_date)
    record_business_event(settings.service_name, "schedule.completed")
    return (await _schedule_responses([schedule]))[0]


@schedule_router.delete("/{schedule_id}", response_model=MessageResponse,
                        summary="Xoá lịch bảo trì (soft delete)")
async def delete_schedule(
    schedule_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    schedule = (await session.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.id == schedule_id,
            MaintenanceSchedule.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not schedule:
        raise NotFoundError(f"Không tìm thấy lịch bảo trì {schedule_id}")
    user.assert_property_access(schedule.property_id)

    schedule.deleted_at = datetime.now(UTC)
    schedule.is_active = False
    return MessageResponse(message=f"Đã xoá lịch bảo trì '{schedule.title}'")


# =================================================================================
#  INTERNAL API
# =================================================================================
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


@internal_router.get("/incidents/{incident_id}", summary="[Nội bộ] Lấy phiếu sự cố")
async def internal_get_incident(
    incident_id: uuid.UUID,
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    report-service gọi khi dựng báo cáo MTTR & chi phí bảo trì.

    ⭐ Cố ý KHÔNG gọi `assert_property_access`: token SYSTEM không mang
       `property_id` người dùng nên hàm đó sẽ ném 403 oan. Ranh giới tin cậy
       được vẽ ở tầng mạng nội bộ + vai trò SYSTEM.
    """
    incident = await _get_incident_or_404(session, incident_id)
    return {
        "id": str(incident.id),
        "ticket_no": incident.ticket_no,
        "property_id": str(incident.property_id),
        "room_id": str(incident.room_id) if incident.room_id else None,
        "category": incident.category,
        "priority": incident.priority,
        "status": incident.status,
        "cost": str(incident.cost) if incident.cost is not None else None,
        "rating": incident.rating,
        "created_at": incident.created_at.isoformat(),
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "resolution_hours": incident.resolution_hours,
    }


@internal_router.get("/incidents", summary="[Nội bộ] Tổng hợp sự cố")
async def internal_incident_summary(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> dict:
    """report-service gọi để dựng dashboard. Trả về số liệu tổng hợp sẵn
    để report không phải tự viết lại câu SQL đếm theo nhóm."""
    stmt = select(Incident.status, Incident.category, Incident.priority,
                  func.count(Incident.id), func.coalesce(func.sum(Incident.cost), 0))
    stmt = stmt.where(Incident.deleted_at.is_(None))
    if property_id:
        stmt = stmt.where(Incident.property_id == property_id)
    rows = (await session.execute(stmt.group_by(
        Incident.status, Incident.category, Incident.priority
    ))).all()

    by_category: dict[str, dict[str, int]] = {}
    total_cost = Decimal("0")
    total = 0
    for st, cat, _priority, count, cost in rows:
        bucket = by_category.setdefault(cat, {"total": 0, "open": 0})
        bucket["total"] += count
        if st not in DONE_STATUSES:
            bucket["open"] += count
        total += count
        total_cost += Decimal(str(cost or 0))

    return {
        "property_id": str(property_id) if property_id else None,
        "total": total,
        "by_category": by_category,
        "total_cost": str(total_cost),
    }


# =================================================================================
#  ĐĂNG KÝ ROUTER
# =================================================================================
app.include_router(incident_router)
app.include_router(schedule_router)
app.include_router(internal_router)
