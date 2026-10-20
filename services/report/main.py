"""
================================================================================
report-service — Báo cáo, dashboard & phân tích.       Cổng 8008  |  db_report
================================================================================

Đây là service DUY NHẤT trong hệ thống không "sở hữu" nghiệp vụ nào. Nó chỉ:

    1. Lắng nghe event của 4 service khác → cập nhật read model trong db_report
    2. Trả lời câu hỏi báo cáo bằng CÁCH ĐỌC 1 BẢNG
    3. Định kỳ ĐỐI CHIẾU lại với nguồn để read model tự lành khi lệch

Vì sao cần tới nó: câu hỏi "tháng này thu bao nhiêu, tỷ lệ thu hồi ra sao" cần
dữ liệu từ billing + room + contract + maintenance. Với database-per-service
không có 1 câu SQL join nào làm được. Nếu gọi 4 service mỗi lần mở dashboard
thì p95 1–2 giây và 1 service chết là dashboard chết theo.

--------------------------------------------------------------------------------
SƠ ĐỒ LUỒNG DỮ LIỆU
--------------------------------------------------------------------------------

```mermaid
flowchart LR
    subgraph SRC["Nguồn chuẩn (nguồn sự thật)"]
        R[room-service<br/>db_room]
        C[contract-service<br/>db_contract]
        B[billing-service<br/>db_billing]
        M[maintenance-service<br/>db_maintenance]
    end

    subgraph BUS["RabbitMQ — topic exchange"]
        EV{{"room.*<br/>contract.*<br/>invoice.*<br/>payment.*<br/>incident.*"}}
    end

    subgraph RP["report-service · db_report"]
        CONS["Consumer<br/>(IdempotentConsumer)"]
        W1["daily_financials<br/>daily_contract_flow<br/>daily_incident_stats<br/>═══ CỘNG DẦN"]
        W2["daily_occupancy<br/>open_invoices<br/>═══ GHI ĐÈ"]
        API["API báo cáo<br/>1 câu SQL / 1 bảng"]
    end

    R --> EV
    C --> EV
    B --> EV
    M --> EV
    EV --> CONS
    CONS -->|"facts: +1, +500.000"| W1
    CONS -->|"state: tìm & sửa dòng"| W2
    W1 --> API
    W2 --> API

    API -.->|"ĐỐI CHIẾU định kỳ<br/>gọi nội bộ, ghi đè"| R
    API -.-> C
    API -.-> B
    API -.-> M
```

--------------------------------------------------------------------------------
BA NGUYÊN TẮC CỦA FILE NÀY
--------------------------------------------------------------------------------

1. **Phân biệt rõ SỰ KIỆN với TRẠNG THÁI.** Sự kiện chỉ CỘNG DẦN; trạng
   thái GHI ĐÈ. Nhầm 2 loại này là nguồn gốc của hầu hết bug event-driven.
2. **Phép cộng nằm trong SQL.** `INSERT ... ON CONFLICT DO UPDATE SET c = c +
   delta` — đọc-rồi-ghi bằng Python sẽ mất số khi 2 consumer cùng ghi.
3. **Không bao giờ để báo cáo chết vì service nguồn chết.** Endpoint đọc trả
   `null` kèm cờ `degraded`, không phải 500 và không phải số 0 (0 là một lời
   nói dối — "không có nợ" khác hẳn "không biết có bao nhiêu nợ").
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common import (
    BusinessRuleError,
    CurrentUser,
    Role,
    ServiceUnavailableError,
    create_service_app,
    get_db,
    get_event_bus,
    get_http_client,
    record_business_event,
    require_roles,
    set_business_gauge,
)
from common.config import settings
from common.database import session_scope
from common.events import DomainEvent, IdempotentConsumer
from common.repository import acquire_lock, release_lock
from models import (
    ALL_PROPERTIES,
    ZERO,
    DailyContractFlow,
    DailyFinancial,
    DailyIncidentStat,
    DailyOccupancy,
    MonthlyFinancial,
    OpenInvoice,
    SyncRun,
    apply_occupancy_delta,
    bump_counters,
    business_day,
    business_tz,
    purge_expired,
    record_financials,
    set_occupancy_snapshot,
    upsert_open_invoice,
)
from schemas import (
    AGING_BUCKETS,
    AgingBucket,
    CollectionsReport,
    ContractFlowPoint,
    ContractFlowReport,
    DashboardResponse,
    DataFreshness,
    DebtItem,
    DebtorSummary,
    MaintenanceReport,
    OccupancyPoint,
    OccupancyReport,
    OccupancySnapshot,
    ReconcileResponse,
    ReportWindow,
    RevenuePoint,
    RevenueReport,
    SummaryResponse,
    SyncRunResponse,
)

logger = logging.getLogger(__name__)

#: Chu kỳ đối chiếu (giây). 30 phút: đọc model chỉ lệch vài giây sau event, nên
#: 30 phút là "biên an toàn" chứ không phải nhu cầu thực. Giảm xuống 5 phút
#: cũng chạy được, chỉ tốn thêm vài chục lời gọi nội bộ mỗi giờ.
RECONCILE_INTERVAL = 1800

#: TTL khoá phân tán > chu kỳ, để 2 vòng liên tiếp không chạy chồng nhau.
LOCK_TTL_RECONCILE = RECONCILE_INTERVAL + 300

#: Chu kỳ dọn dữ liệu quá hạn (giây) — 1 lần/ngày là thừa.
RETENTION_INTERVAL = 86400
LOCK_TTL_RETENTION = RETENTION_INTERVAL + 600

#: TTL cache cho 2 con số "đọc trực tiếp" (hợp đồng đang hiệu lực, sự cố mở).
#: ⭐ Ngắn (60s) vì đây là dữ liệu TÌNH THỜI; cache dài sẽ hiện số cũ khi
#:    có người vừa dọn phòng.
CACHE_TTL_LIVE = 60

#: Trạng thái hóa đơn ở billing-service còn được coi là "đang nợ".
OPEN_INVOICE_STATUSES = ("PENDING", "OVERDUE", "OPEN")

#: BOM đặt đầu file CSV. Không có nó, Excel mở file UTF-8 bằng codepage cũ
#: sẽ hiện "Nguyá»…n Văn Ánh" thay vì tên tiếng Việt. Đặt tên hằng thay vì
#: gõ ký tự vô hình trong chuỗi — ký tự đó không hiện trong editor nên rất
#: dễ bị mất khi ai đó sửa dòng này.
CSV_BOM = "\ufeff"

#: Trạng thái phòng (room-service) → cột trong `daily_occupancy`.
_OCCUPANCY_COLUMN: dict[str, str] = {
    "AVAILABLE": "available",
    "OCCUPIED": "occupied",
    "MAINTENANCE": "maintenance",
    "RESERVED": "reserved",
}

#: Sự kiện hợp đồng → cột bộ đếm trong `daily_contract_flow`.
_CONTRACT_FLOW_COLUMN: dict[str, str] = {
    "contract.created": "created",
    "contract.activated": "activated",
    "contract.terminated": "terminated",
    "contract.expired": "expired",
    "contract.cancelled": "cancelled",
    "contract.renewed": "renewed",
}

#: Toàn bộ sự kiện report-service lắng nghe. Đăng ký tường minh (không dùng
#: `#`) để RabbitMQ chỉ đẩy event liên quan — 1 hàng đợi "báo cáo" nhận mọi
#: thứ sẽ kéo tải vô ích lên report-service mỗi khi ai đó đăng nhập.
SUBSCRIBED_EVENTS: list[str] = [
    "room.created", "room.status_changed",
    "contract.created", "contract.activated", "contract.terminated",
    "contract.expired", "contract.cancelled", "contract.renewed",
    "invoice.issued", "invoice.overdue", "invoice.refunded",
    "payment.received",
    "incident.created", "incident.urgent", "incident.resolved",
]


# =================================================================================
#  CONSUMER — phản ứng với event của 4 service khác
#
#  ⭐ Định nghĩa TRƯỚC `create_service_app` vì `lifespan_extra` được đánh giá
#     ngay lúc gọi. Đảo thứ tự → NameError.
# =================================================================================
async def _setup_consumers(app_instance) -> None:
    consumer = IdempotentConsumer(
        handler=_handle_event,
        consumer_name="report-service:read-model",
    )
    app_instance.state.ctx.consumers.append(consumer)
    try:
        await get_event_bus().subscribe(
            "qlpt.report.readmodel", consumer.handle, SUBSCRIBED_EVENTS,
        )
    except Exception as exc:
        # Không chết: các API báo cáo vẫn chạy được, chỉ là dữ liệu không
        # được cập nhật tự động cho tới khi RabbitMQ quay lại.
        logger.error("Không đăng ký consumer report được: %s", exc)


async def _handle_event(event: DomainEvent) -> None:
    handler = {
        "room.created": _on_room_created,
        "room.status_changed": _on_room_status_changed,
        "invoice.issued": _on_invoice_issued,
        "invoice.overdue": _on_invoice_overdue,
        "invoice.refunded": _on_invoice_refunded,
        "payment.received": _on_payment_received,
        "incident.created": _on_incident_created,
        "incident.urgent": _on_incident_urgent,
        "incident.resolved": _on_incident_resolved,
    }.get(event.event_type)

    if handler is None and event.event_type in _CONTRACT_FLOW_COLUMN:
        handler = _on_contract_flow
    if handler is None:
        return

    async with session_scope() as session:
        await handler(session, event)


# ---------------------------------------------------------------------------
#  NGUYÊN TẮC CHUNG CHO MỌI HANDLER
# ---------------------------------------------------------------------------
def _property_of(event: DomainEvent) -> uuid.UUID | None:
    """
    Lấy `property_id` từ event.

    ⭐ `ALL_PROPERTIES` là dòng tổng hợp toàn hệ thống, chỉ sinh ra khi event
       không mang cơ sở cụ thể. Handler KHÔNG được ghi vào nó bằng phép cộng —
       vì cộng một phần vào tổng là vô nghĩa (tổng phải chứa tất cả). Vì vậy ta
       trả `None` để handler bỏ qua, và để đường đối chiếu lo.
    """
    raw = event.data.get("property_id")
    if not raw:
        return None
    try:
        value = uuid.UUID(str(raw))
    except ValueError:
        logger.warning("Event %s có property_id sai định dạng: %r",
                       event.event_type, raw)
        return None
    return None if value == ALL_PROPERTIES else value


def _num(value: Any) -> Decimal:
    """Ép về `Decimal` an toàn — xem `billing/pricing.py` về lý do."""
    return Decimal(str(value or 0))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
#  PHÒNG  →  daily_occupancy (TRẠNG THÁI, cập nhật bằng phép cộng ±1)
# ---------------------------------------------------------------------------
async def _on_room_created(session: AsyncSession, event: DomainEvent) -> None:
    property_id = _property_of(event)
    if property_id is None:
        return
    status = str(event.data.get("status") or "AVAILABLE").upper()
    day = business_day(event.occurred_at)

    deltas: dict[str, int] = {"total_rooms": 1}
    column = _OCCUPANCY_COLUMN.get(status, "other")
    deltas[column] = 1
    await apply_occupancy_delta(session, property_id, day, deltas)

    record_business_event(settings.service_name, "report.room_created")


async def _on_room_status_changed(session: AsyncSession, event: DomainEvent) -> None:
    """
    Phòng chuyển trạng thái → trừ ở nhóm cũ, cộng ở nhóm mới.

    ⭐ Đây là chỗ dễ sai nhất của trạng thái: nếu chỉ cộng ở nhóm mới mà quên
       trừ nhóm cũ, tổng số phòng sẽ tăng vô hạn theo thời gian (mỗi lần có
       người vào là cộng thêm 1, không bao giờ trừ đi) và tỷ lệ lấp đầy vượt
       100% sau vài ngày.
    """
    property_id = _property_of(event)
    if property_id is None:
        return

    old = str(event.data.get("from") or "").upper()
    new = str(event.data.get("to") or "").upper()
    deltas: dict[str, int] = {}
    if old:
        key = _OCCUPANCY_COLUMN.get(old, "other")
        deltas[key] = deltas.get(key, 0) - 1
    if new:
        key = _OCCUPANCY_COLUMN.get(new, "other")
        deltas[key] = deltas.get(key, 0) + 1
    if not deltas:
        return

    await apply_occupancy_delta(
        session, property_id, business_day(event.occurred_at), deltas,
    )
    record_business_event(settings.service_name, "report.room_status_changed")


# ---------------------------------------------------------------------------
#  HÓA ĐƠN & THANH TOÁN  →  daily_financials (SỰ KIỆN) + open_invoices (TRẠNG THÁI)
# ---------------------------------------------------------------------------
async def _on_invoice_issued(session: AsyncSession, event: DomainEvent) -> None:
    property_id = _property_of(event)
    if property_id is None:
        return
    data = event.data
    day = business_day(event.occurred_at)
    total = _num(data.get("total_amount"))

    # Loại 1 — sự kiện: cộng dồn.
    await record_financials(
        session, property_id, day, invoices_issued=1, invoiced_amount=total,
    )
    # Loại 2 — trạng thái: mở 1 dòng công nợ.
    await upsert_open_invoice(session, {
        "invoice_id": uuid.UUID(str(data["invoice_id"])),
        "property_id": property_id,
        "contract_id": _maybe_uuid(data.get("contract_id")),
        "room_id": _maybe_uuid(data.get("room_id")),
        "tenant_id": _maybe_uuid(data.get("tenant_id")),
        "tenant_name": (data.get("tenant_name") or None),
        "invoice_no": data.get("invoice_no") or "",
        "period": data.get("period"),
        "total_amount": total,
        "paid_amount": ZERO,
        "due_date": _maybe_date(data.get("due_date")),
        "issued_date": day,
        "status": "OPEN",
        "is_overdue_notified": False,
    })
    record_business_event(settings.service_name, "report.invoice_issued")


async def _on_payment_received(session: AsyncSession, event: DomainEvent) -> None:
    property_id = _property_of(event)
    if property_id is None:
        return
    data = event.data
    day = business_day(event.occurred_at)
    amount = _num(data.get("amount"))

    await record_financials(
        session, property_id, day, payments_received=1, collected_amount=amount,
    )

    invoice_id = _maybe_uuid(data.get("invoice_id"))
    if invoice_id is None:
        return
    if data.get("invoice_paid"):
        # Hóa đơn đã quét hết → KHÔNG còn là công nợ. Gỡ khỏi bảng thay vì
        # để nguyên với status='PAID': giữ lại sẽ làm báo cáo công nợ tính
        # nhầm và bảng phình vô tận.
        await session.execute(
            OpenInvoice.__table__.delete().where(
                OpenInvoice.invoice_id == invoice_id
            )
        )
    else:
        await session.execute(
            OpenInvoice.__table__.update()
            .where(OpenInvoice.invoice_id == invoice_id)
            .values(
                paid_amount=OpenInvoice.paid_amount + amount,
                updated_at=func.now(),
            )
        )
    record_business_event(settings.service_name, "report.payment_received")


async def _on_invoice_overdue(session: AsyncSession, event: DomainEvent) -> None:
    property_id = _property_of(event)
    if property_id is None:
        return
    data = event.data
    day = business_day(event.occurred_at)
    outstanding = _num(data.get("outstanding"))

    await record_financials(
        session, property_id, day,
        overdue_count=1, overdue_amount=outstanding,
    )
    invoice_id = _maybe_uuid(data.get("invoice_id"))
    if invoice_id is not None:
        await session.execute(
            OpenInvoice.__table__.update()
            .where(OpenInvoice.invoice_id == invoice_id)
            .values(
                status="OVERDUE",
                is_overdue_notified=True,
                updated_at=func.now(),
            )
        )
    record_business_event(settings.service_name, "report.invoice_overdue")


async def _on_invoice_refunded(session: AsyncSession, event: DomainEvent) -> None:
    """
    Hoàn tiền khi chấm dứt hợp đồng.

    ⭐ Ghi `refunded_amount` riêng chứ không chỉ bừa trừ vào `collected_amount`.
       Chủ nhà cần biết "thu được 100tr, hoàn lại 3tr" khác hẳn với
       "thu được 97tr" — con số thứ hai giấu mất việc mình đã trả tiền cho
       khách, và báo cáo lợi nhuận sẽ sai.
    """
    property_id = _property_of(event)
    if property_id is None:
        return
    amount = _num(event.data.get("amount"))
    await record_financials(
        session, property_id, business_day(event.occurred_at),
        refunded_amount=amount,
        # `record_financials` tự tính `outstanding += amount` (người thuê đã
        # nhận lại tiền → nợ phải tăng lại). Không truyền `outstanding_delta`.
    )
    record_business_event(settings.service_name, "report.invoice_refunded")


# ---------------------------------------------------------------------------
#  HỢP ĐỒNG  →  daily_contract_flow (chỉ cộng dần)
# ---------------------------------------------------------------------------
async def _on_contract_flow(session: AsyncSession, event: DomainEvent) -> None:
    property_id = _property_of(event)
    if property_id is None:
        return
    column = _CONTRACT_FLOW_COLUMN[event.event_type]
    await bump_counters(
        session, DailyContractFlow, property_id,
        business_day(event.occurred_at), {column: 1},
    )
    record_business_event(settings.service_name, f"report.{column}")


# ---------------------------------------------------------------------------
#  SỰ CỐ  →  daily_incident_stats (chỉ cộng dần)
# ---------------------------------------------------------------------------
async def _on_incident_created(session: AsyncSession, event: DomainEvent) -> None:
    property_id = _property_of(event)
    if property_id is None:
        return
    deltas = {"created": 1}
    if str(event.data.get("priority") or "") == "URGENT":
        deltas["urgent"] = 1
    await bump_counters(
        session, DailyIncidentStat, property_id,
        business_day(event.occurred_at), deltas,
    )
    record_business_event(settings.service_name, "report.incident_created")


async def _on_incident_urgent(session: AsyncSession, event: DomainEvent) -> None:
    """
    Phiếu được NÂNG lên URGENT.

    ⭐ CỐ Ý KHÔNG trừ lại số đã đếm lúc `incident.created`. Vì thời điểm phát
       `incident.urgent` không nói được phiếu đó đã được tính vào ngày nào,
       nên không có cách nào "bỏ điểm cũ" chính xác. Tính thêm là lựa chọn
       ít sai hơn — và ta ghi chú ở đây để người đọc sau không tưởng là bug.
    """
    property_id = _property_of(event)
    if property_id is None:
        return
    await bump_counters(
        session, DailyIncidentStat, property_id,
        business_day(event.occurred_at), {"urgent": 1},
    )
    record_business_event(settings.service_name, "report.incident_urgent")


async def _on_incident_resolved(session: AsyncSession, event: DomainEvent) -> None:
    property_id = _property_of(event)
    if property_id is None:
        return
    data = event.data
    deltas: dict[str, Any] = {"resolved": 1}
    hours = data.get("resolution_hours")
    if hours is not None:
        deltas["resolution_hours"] = _num(hours)
    cost = data.get("cost")
    if cost is not None:
        deltas["cost"] = _num(cost)
    await bump_counters(
        session, DailyIncidentStat, property_id,
        business_day(event.occurred_at), deltas,
    )
    record_business_event(settings.service_name, "report.incident_resolved")


# =================================================================================
#  APP
# =================================================================================
app = create_service_app(
    name="report-service",
    description=(
        "**Báo cáo, dashboard & phân tích** — service CQRS duy nhất của hệ thống\n\n"
        "- Dựng read model riêng từ event của 4 service khác\n"
        "- Đọc báo cáo = **1 câu SQL trên 1 bảng**, không cần join\n"
        "- Định kỳ đối chiếu lại nguồn để read model tự lành khi lệch\n\n"
        "### Sự kiện vs Trạng thái — quy tắc của service này\n"
        "| Loại | Bảng | Cách cập nhật |\n"
        "|---|---|---|\n"
        "| Sự kiện bất biến | `daily_financials`, `daily_contract_flow`, "
        "`daily_incident_stats` | CỘNG DẦN (`cột = cột + delta`) |\n"
        "| Trạng thái | `daily_occupancy`, `open_invoices` | GHI ĐÈ (có đường đối chiếu) |\n\n"
        "### Độ tin cậy\n"
        "Mọi báo cáo đều trả kèm `freshness` — thời điểm đối chiếu gần nhất và "
        "cờ `is_stale`. Khi service nguồn chết, số liệu liên quan là `null` "
        "chứ không phải `0`."
    ),
    version="1.0.0",
    lifespan_extra=_setup_consumers,
    # Job thật là `_reconcile_loop` bên dưới, không phải scheduler mặc định
    # của factory (vốn chỉ in log mỗi 60s). Xem `_install_background_jobs`.
    enable_scheduler=False,
)


# =================================================================================
#  JOB NỀN: ĐỐI CHIẾU & DỌN DỮ LIỆU
# =================================================================================
# ⚠️  Phải chụp `lifespan_context` NGAY sau `create_service_app`. Nếu đọc lúc
#     chạy, ta sẽ nhận về chính wrapper này → lồng vô hạn.
#     (Starlette chỉ chạy `on_startup`/`on_shutdown` trong `_DefaultLifespan`,
#     nên `app.add_event_handler("shutdown", …)` sẽ KHÔNG bao giờ chạy khi app
#     đã có `lifespan` — đó là lý do phải bọc thủ công.)
_FACTORY_LIFESPAN = app.router.lifespan_context
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _install_background_jobs(app_instance) -> None:
    @asynccontextmanager
    async def _lifespan(inner):
        async with _FACTORY_LIFESPAN(inner):
            if settings.run_scheduler:
                # ⭐ Giữ tham chiếu: task không được giữ sẽ bị GC dừng lấp
                #   (`asyncio` chỉ giữ tham chiếu yếu — "Task Reference").
                _BACKGROUND_TASKS.update({
                    asyncio.create_task(_reconcile_loop(inner)),
                    asyncio.create_task(_retention_loop(inner)),
                })
                logger.info(
                    "   ✓ Job nền đã bật: đối chiếu mỗi %ss, dọn dữ liệu mỗi %ss",
                    RECONCILE_INTERVAL, RETENTION_INTERVAL,
                )
            try:
                yield
            finally:
                for task in list(_BACKGROUND_TASKS):
                    task.cancel()
                for task in list(_BACKGROUND_TASKS):
                    with suppress(asyncio.CancelledError):
                        await task
                _BACKGROUND_TASKS.clear()
                logger.info("   ✓ Job nền đã dừng")

    app_instance.router.lifespan_context = _lifespan


_install_background_jobs(app)


async def _reconcile_loop(app_instance) -> None:
    """
    Vòng lặp đối chiếu read model với nguồn chuẩn.

    ⭐ Khoá phân tán ở đây không phải cho đẹp. Khi scale report lên 2 replica,
       cả hai sẽ gọi billing/room cùng lúc và ghi đè lẫn nhau — không hỏng dữ
       liệu (vì ta GHI ĐÈ chứ không cộng) nhưng tốn gấp đôi lời gọi mạng và làm
       chậm chính service đang cần đối chiếu. `SET NX` trên Redis bảo đảm mỗi
       vòng chỉ một tiến trình chạy.
    """
    lock_name = "report-reconcile"
    owner = f"{settings.service_name}:{uuid.uuid4().hex[:8]}"

    while True:
        try:
            redis = getattr(app_instance.state, "redis", None)
            if await acquire_lock(redis, lock_name, owner, ttl=LOCK_TTL_RECONCILE):
                try:
                    result = await _run_reconcile(
                        kind="reconcile", triggered_by="scheduler",
                    )
                    if result.status != "SUCCESS":
                        logger.warning("⚠ Đối chiếu %s: %s",
                                       result.status, result.errors)
                finally:
                    await release_lock(redis, lock_name, owner)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lỗi trong vòng đối chiếu")
        await asyncio.sleep(RECONCILE_INTERVAL)


async def _retention_loop(app_instance) -> None:
    """Dọn dữ liệu quá hạn + tổng hợp tháng. Chạy 1 lần/ngày là thừa."""
    lock_name = "report-retention"
    owner = f"{settings.service_name}:{uuid.uuid4().hex[:8]}"

    while True:
        try:
            redis = getattr(app_instance.state, "redis", None)
            if await acquire_lock(redis, lock_name, owner, ttl=LOCK_TTL_RETENTION):
                try:
                    async with session_scope() as session:
                        stats = await purge_expired(session)
                    logger.info("🧹 Dọn dữ liệu quá hạn: %s", stats)
                except Exception:
                    logger.exception("Lỗi dọn dữ liệu quá hạn")
                finally:
                    await release_lock(redis, lock_name, owner)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lỗi trong vòng dọn dữ liệu")
        await asyncio.sleep(RETENTION_INTERVAL)


async def _run_reconcile(
    kind: str,
    property_id: uuid.UUID | None = None,
    triggered_by: str = "manual",
    *,
    with_retention: bool = False,
) -> ReconcileResponse:
    """
    Chạy 1 lần đối chiếu. Trả về kết quả để endpoint `/reconcile` trả lại
    cho scheduler — không nuốt lỗi im lặng.

    ⭐ Mỗi nhóm nguồn chạy trong transaction RIÊNG và lỗi được gom lại thay vì
       làm hỏng cả lượt. Nếu billing chết, công suất phòng vẫn phải được chốt —
       dashboard số 5 trên 8 mà số 6 trống thì người dùng mất niềm tin vào
       cả trang.
    """
    started = time.perf_counter()
    errors: list[str] = []
    occ_synced = fin_synced = inv_synced = 0
    retention: dict | None = None

    async with session_scope() as session:
        run = SyncRun(
            kind=kind, property_id=property_id, status="RUNNING",
            triggered_by=triggered_by,
        )
        session.add(run)
        await session.flush()
        run_id = run.id

    try:
        occ_synced = await _reconcile_occupancy(property_id)
    except Exception as exc:
        logger.exception("Đối chiếu công suất thất bại")
        errors.append(f"room-service: {exc}")

    try:
        fin_synced, inv_synced = await _reconcile_financials(property_id)
    except Exception as exc:
        logger.exception("Đối chiếu tài chính thất bại")
        errors.append(f"billing-service: {exc}")

    if with_retention:
        try:
            async with session_scope() as session:
                retention = await purge_expired(session)
        except Exception as exc:
            logger.exception("Dọn dữ liệu thất bại")
            errors.append(f"retention: {exc}")

    duration_ms = int((time.perf_counter() - started) * 1000)
    status = "FAILED" if len(errors) > 1 else ("PARTIAL" if errors else "SUCCESS")
    finished = datetime.now(UTC)

    async with session_scope() as session:
        run = await session.get(SyncRun, run_id)
        if run is not None:
            run.status = status
            run.rows_synced = occ_synced + fin_synced + inv_synced
            run.detail = {
                "occupancy_synced": occ_synced,
                "financials_synced": fin_synced,
                "invoices_synced": inv_synced,
                "errors": errors,
            }
            run.message = "; ".join(errors)[:1000] or None
            run.finished_at = finished
            run.duration_ms = min(duration_ms, 32767)   # cột SmallInteger

    record_business_event(
        settings.service_name, f"report.reconcile.{status.lower()}"
    )
    logger.info(
        "🔄 Đối chiếu %s (%dms): %d dòng công suất, %d dòng tài chính, "
        "%d hóa đơn mở",
        status, duration_ms, occ_synced, fin_synced, inv_synced,
    )
    return ReconcileResponse(
        kind=kind, status=status, duration_ms=duration_ms,
        occupancy_synced=occ_synced, financials_synced=fin_synced,
        invoices_synced=inv_synced, retention=retention, errors=errors,
        finished_at=finished,
    )


# ---------------------------------------------------------------------------
#  ĐỐI CHIẾU — CÔNG SUẤT (nguồn: room-service)
# ---------------------------------------------------------------------------
async def _reconcile_occupancy(property_id: uuid.UUID | None) -> int:
    """
    Chụp lại công suất phòng từ `GET /internal/v1/rooms/stats`.

    ⭐ Ghi ĐÈ (không cộng). Đây là mô hình "event là tối ưu, snapshot là
       chuẩn": event cho độ trễ ~1 giây giữa các lần mở dashboard, còn lần
       đối chiếu định kỳ bảo đảm sai số không tồn tại quá 30 phút.
    """
    targets: list[uuid.UUID | None] = [property_id]
    if property_id is None:
        targets = await _known_property_ids() + [None]

    client = get_http_client("room")
    results = await asyncio.gather(
        *(client.get("/internal/v1/rooms/stats",
                     params={"property_id": str(p)} if p else None)
          for p in targets),
        return_exceptions=True,
    )

    today = business_day()
    synced = 0
    for target, result in zip(targets, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("Không lấy được thống kê phòng của %s: %s",
                           target or "toàn hệ thống", result)
            continue
        by_status = (result or {}).get("by_status") or {}
        total = _as_int((result or {}).get("total"))
        counts = {column: _as_int(by_status.get(status))
                  for status, column in _OCCUPANCY_COLUMN.items()}
        counts["total_rooms"] = total
        # Phần không thuộc 4 trạng thái đã biết (phòng "đang dọn", "ngừng
        # khai thác"…). Tính phần dư thay vì để 0 — nếu không, tổng các nhóm
        # sẽ không bằng `total` và báo cáo tự mâu thuẫn với chính nó.
        counts["other"] = max(0, total - sum(counts.values()))

        # `target is None` → ghi vào DÒNG TỔNG HỢP, không phải dòng nào cả.
        key = target if target is not None else ALL_PROPERTIES
        async with session_scope() as session:
            await set_occupancy_snapshot(session, key, today, counts)
        synced += 1
    return synced


async def _known_property_ids() -> list[uuid.UUID]:
    """
    Các cơ sở đã từng xuất hiện trong read model.

    ⭐ report-service KHÔNG có bảng `properties` (nguồn chuẩn ở room-service)
       và cũng không nên hỏi "xin danh sách cơ sở" mỗi vòng đối chiếu. Ta lấy
       danh sách từ chính read model: chỉ những cơ sở đã có phòng/công nợ mới
       cần chụp lại. Cơ sở mới tạo mà chưa có phòng thì chưa có gì để báo cáo.
    """
    async with session_scope() as session:
        from_occ = select(DailyOccupancy.property_id).distinct()
        from_debt = select(OpenInvoice.property_id).distinct()
        rows = (await session.execute(from_occ.union(from_debt))).scalars().all()
    return [r for r in rows if r and r != ALL_PROPERTIES]


# ---------------------------------------------------------------------------
#  ĐỐI CHIẾU — TÀI CHÍNH & CÔNG NỢ (nguồn: billing-service)
# ---------------------------------------------------------------------------
async def _reconcile_financials(
    property_id: uuid.UUID | None,
) -> tuple[int, int]:
    """
    DỰNG LẠI `daily_financials` + `open_invoices` từ ảnh chụp của billing.

    ⭐ Vì sao phải DỰNG LẠI chứ không chỉ "gọi lại từng hóa đơn đang mở"? Vì
       có hai đường vào dữ liệu mà event KHÔNG đi qua: dữ liệu nạp thẳng lúc
       seed và event bị mất khi consumer/RabbitMQ gặp sự cố. Đường event chỉ
       CỘNG DẦN nên không bao giờ tự phát hiện "dòng lẽ ra phải có mà lại
       không có". Chỉ đối chiếu theo kiểu ảnh chụp mới làm read model tự lành
       được trong cả hai tình huống đó.

    ⭐ GHI ĐÈ theo phạm vi (xoá rồi ghi lại), KHÔNG cộng dồn: đây là số liệu
       dẫn xuất từ billing, nên billing là chân lý. Chạy 10 lần vẫn ra đúng
       một kết quả — đó là tính chất bắt buộc của một thao tác đối chiếu.

    ⭐ Tiền đã hoàn (`refunded_amount`) được GIỮ LẠI từ read model hiện có:
       billing không có bảng hoàn tiền riêng (nó trừ thẳng vào `total_amount`
       của hóa đơn), nên khi dựng lại ta không thể suy ra. Xoá mà không giữ
       là một lần đối chiếu âm thầm xoá mất lịch sử hoàn tiền — dữ liệu đúng
       biến thành sai.

    Trả về `(số dòng ngày đã ghi, số hóa đơn mở đã ghi)`.
    """
    client = get_http_client("billing")
    snapshot = await client.get(
        "/internal/v1/financials/snapshot",
        params={"property_id": str(property_id)} if property_id else None,
    )
    invoices = (snapshot or {}).get("invoices") or []
    payments = (snapshot or {}).get("payments") or []

    # (cơ sở, ngày) → bộ đếm. Dùng chung cho cả 2 bảng nên chỉ gọi billing 1 lần.
    days: dict[tuple[uuid.UUID, date], dict[str, Any]] = {}

    def _cell(pid: uuid.UUID, day: date) -> dict[str, Any]:
        cell = days.get((pid, day))
        if cell is None:
            cell = {
                "invoices_issued": 0, "invoiced_amount": ZERO,
                "payments_received": 0, "collected_amount": ZERO,
                "refunded_amount": ZERO, "overdue_count": 0,
                "overdue_amount": ZERO,
            }
            days[(pid, day)] = cell
        return cell

    for inv in invoices:
        pid = _maybe_uuid(inv.get("property_id"))
        if pid is None:
            continue
        day = _event_day(inv.get("issued_at")) or business_day()
        cell = _cell(pid, day)
        cell["invoices_issued"] += 1
        cell["invoiced_amount"] += _num(inv.get("total_amount"))

        # Hóa đơn đang quá hạn → ghi phần còn lại vào NGÀY TỚI HẠN để biểu đồ
        # "nợ quá hạn" có dữ liệu (event `invoice.overdue` cũng ghi như vậy).
        if str(inv.get("status") or "").upper() == "OVERDUE":
            remaining = _num(inv.get("total_amount")) - _num(inv.get("paid_amount"))
            if remaining > ZERO:
                overdue_cell = _cell(pid, _maybe_date(inv.get("due_date")) or day)
                overdue_cell["overdue_count"] += 1
                overdue_cell["overdue_amount"] += remaining

    for pay in payments:
        pid = _maybe_uuid(pay.get("property_id"))
        if pid is None:
            continue
        day = _event_day(pay.get("received_at")) or business_day()
        cell = _cell(pid, day)
        cell["payments_received"] += 1
        cell["collected_amount"] += _num(pay.get("amount"))

    async with session_scope() as session:
        # ---- Giữ lại lịch sử hoàn tiền (billing không cung cấp được) ----
        refund_stmt = select(
            DailyFinancial.property_id,
            DailyFinancial.stat_date,
            DailyFinancial.refunded_amount,
        ).where(DailyFinancial.refunded_amount != 0)
        if property_id is not None:
            refund_stmt = refund_stmt.where(
                DailyFinancial.property_id == property_id
            )
        for pid, day, refunded in (await session.execute(refund_stmt)).all():
            if refunded and _num(refunded) > ZERO:
                _cell(pid, day)["refunded_amount"] += _num(refunded)

        # ---- Ghi đè `daily_financials` ----
        delete_fin = delete(DailyFinancial)
        if property_id is not None:
            delete_fin = delete_fin.where(
                DailyFinancial.property_id == property_id
            )
        await session.execute(delete_fin)

        financial_rows = 0
        by_property: dict[uuid.UUID, list[date]] = {}
        for pid, day in days:
            by_property.setdefault(pid, []).append(day)
        for pid, day_list in by_property.items():
            running = ZERO      # số dư công nợ chạy của từng cơ sở
            for day in sorted(day_list):
                cell = days[(pid, day)]
                running = max(
                    ZERO,
                    running + cell["invoiced_amount"]
                    - cell["collected_amount"] + cell["refunded_amount"],
                )
                session.add(DailyFinancial(
                    property_id=pid, stat_date=day,
                    invoices_issued=cell["invoices_issued"],
                    invoiced_amount=cell["invoiced_amount"],
                    payments_received=cell["payments_received"],
                    collected_amount=cell["collected_amount"],
                    refunded_amount=cell["refunded_amount"],
                    outstanding=running,
                    overdue_count=cell["overdue_count"],
                    overdue_amount=cell["overdue_amount"],
                ))
                financial_rows += 1

        # ---- Ghi đè `open_invoices` ----
        delete_inv = delete(OpenInvoice)
        if property_id is not None:
            delete_inv = delete_inv.where(OpenInvoice.property_id == property_id)
        await session.execute(delete_inv)

        open_rows = 0
        for inv in invoices:
            status = str(inv.get("status") or "").upper()
            if status not in OPEN_INVOICE_STATUSES:
                continue
            invoice_id = _maybe_uuid(inv.get("id"))
            pid = _maybe_uuid(inv.get("property_id"))
            total = _num(inv.get("total_amount"))
            paid = _num(inv.get("paid_amount"))
            if invoice_id is None or pid is None or max(ZERO, total - paid) <= ZERO:
                continue
            await upsert_open_invoice(session, {
                "invoice_id": invoice_id,
                "property_id": pid,
                "contract_id": _maybe_uuid(inv.get("contract_id")),
                "room_id": _maybe_uuid(inv.get("room_id")),
                "tenant_id": _maybe_uuid(inv.get("tenant_id")),
                "tenant_name": inv.get("tenant_name") or None,
                "invoice_no": inv.get("invoice_no") or "",
                "period": inv.get("period"),
                "total_amount": total,
                "paid_amount": paid,
                "due_date": _maybe_date(inv.get("due_date")) or business_day(),
                "issued_date": _event_day(inv.get("issued_at")) or business_day(),
                "status": "OVERDUE" if status == "OVERDUE" else "OPEN",
                "is_overdue_notified": status == "OVERDUE",
            })
            open_rows += 1

    logger.info(
        "🧾 Dựng lại read model tài chính: %d dòng ngày, %d hóa đơn mở",
        financial_rows, open_rows,
    )
    return financial_rows, open_rows


# =================================================================================
#  TIỆN ÍCH
# =================================================================================
def _maybe_uuid(value: Any) -> uuid.UUID | None:
    """`None` cho mọi thứ không phải UUID — payload event có thể thiếu hoặc rỗng."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _maybe_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return business_day(value)
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _event_day(value: Any) -> date | None:
    """
    Quy một MỐC THỜI GIAN đầy đủ (ISO string từ service khác) về ngày nghiệp vụ.

    ⭐ Khác `_maybe_date`: `_maybe_date` chỉ cắt 10 ký tự đầu của chuỗi, tức là
       lấy ngày theo UTC. Với payload JSON mang `2026-10-01T18:00:00+00:00`
       (01:00 giờ VN ngày 10-02) thì cắt thẳng sẽ ra nhầm ngày 10-01. Hàm này
       parse thành `datetime` rồi mới quy đổi qua giờ VN.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return business_day(value)
    if isinstance(value, date):
        return value
    try:
        return business_day(datetime.fromisoformat(str(value)))
    except (ValueError, TypeError):
        return _maybe_date(value)


def _resolve_property(
    user: CurrentUser, requested: uuid.UUID | None,
) -> uuid.UUID | None:
    """
    Xác định cơ sở cần xem.

    ⭐ `None` nghĩa là "TẤT CẢ CƠ SỞ" và được ánh xạ thành `ALL_PROPERTIES` ở
       tầng truy vấn — vì `NULL` không dùng được làm thành phần của PRIMARY KEY.
    """
    if user.is_admin:
        return requested
    if user.property_id is None:
        raise BusinessRuleError("Tài khoản chưa được gán vào cơ sở nào")
    if requested is not None and str(requested) != str(user.property_id):
        user.assert_property_access(requested)
    return user.property_id


def _report_key(property_id: uuid.UUID | None) -> uuid.UUID:
    """Khoá read model: `None` → dòng tổng hợp toàn hệ thống."""
    return property_id if property_id is not None else ALL_PROPERTIES


def _window(days: int, to_date: date | None) -> ReportWindow:
    """Khoảng thời gian báo cáo, tính theo NGÀY NGHIỆP VỤ (giờ VN)."""
    end = to_date or business_day()
    start = end - timedelta(days=days - 1)      # days=30 → 30 ngày gồm cả hôm nay
    return ReportWindow(
        from_date=start, to_date=end, days=days, timezone=str(business_tz()),
    )


async def _freshness(
    session: AsyncSession, sources: list[str] | None = None,
) -> DataFreshness:
    """
    Độ tin cậy của số liệu — đọc từ bảng `sync_runs`.

    ⭐ `is_stale` = đã quá 2 chu kỳ đối chiếu mà chưa chạy. Dashboard hiện cảnh
       báo khi điều này thay vì im lặng. Người quản lý thấy "số liệu có thể đã
       cũ 1 giờ" thì kiểm tra được; không thấy gì thì họ tin nhầm số 0 là
       "không có ai nợ".
    """
    last = (await session.execute(
        select(SyncRun)
        .where(SyncRun.status.in_(("SUCCESS", "PARTIAL")),
               SyncRun.kind.in_(("reconcile", "full")))
        .order_by(SyncRun.finished_at.desc().nullslast())
        .limit(1)
    )).scalars().first()

    note: str | None = None
    is_stale = True
    if last is None:
        note = ("Chưa từng chạy đối chiếu. Số liệu dựa hoàn toàn vào event — "
                "chạy 'make reconcile' nếu nghi ngờ số liệu lệch.")
    elif last.finished_at is not None:
        age = (datetime.now(UTC) - last.finished_at).total_seconds()
        is_stale = age > RECONCILE_INTERVAL * 2
        if is_stale:
            note = (f"Lần đối chiếu gần nhất cách đây {int(age // 60)} phút. "
                    "Có thể service nguồn vừa gặp sự cố.")
        elif last.status == "PARTIAL":
            is_stale = False
            note = ("Lần đối chiếu gần nhất chưa thành công hoàn toàn — "
                    "một số nguồn đang không phản hồi.")

    return DataFreshness(
        last_sync_at=last.finished_at if last else None,
        sync_status=last.status if last else None,
        is_stale=is_stale,
        sources=sources or [],
        note=note,
    )


async def _cached_live(
    cache_key: str, loader: Callable[[], Awaitable[Any]],
) -> tuple[Any, bool]:
    """
    Gọi 1 service khác kèm cache Redis ngắn.

    Trả `(giá trị, degraded)`. `degraded=True` nghĩa là không lấy được và đang
    dùng dữ liệu cache cũ (hoặc `None`) — caller phải nói với người dùng, không
    được im lặng thay bằng 0.
    """
    redis = getattr(app.state, "redis", None)
    if redis is not None:
        with suppress(Exception):
            raw = await redis.get(cache_key)
            if raw:
                return json.loads(raw), False

    try:
        value = await loader()
    except Exception as exc:
        logger.warning("Không lấy được %s: %s", cache_key, exc)
        if redis is not None:
            with suppress(Exception):
                stale = await redis.get(cache_key)
                if stale:
                    return json.loads(stale), True
        return None, True

    if redis is not None:
        with suppress(Exception):
            await redis.set(cache_key, json.dumps(value, default=str),
                            ex=CACHE_TTL_LIVE)
    return value, False


async def _active_contract_count(property_id: uuid.UUID | None) -> int | None:
    """
    Số hợp đồng đang hiệu lực — lấy TRỰC TIẾP từ contract-service.

    ⭐ Vì sao không suy ra từ `daily_contract_flow`? Vì đó là SỰ KIỆN LỊCH SỬ
       (đã kích hoạt bao nhiêu, đã kết thúc bao nhiêu), không phải trạng thái
       hiện tại. Một hợp đồng bị huỷ rồi tạo lại, hay chỉ lệch đúng 1 event,
       là con số suy ra sai ngay. Đây là 1 lời gọi nội bộ cache 60s — rẻ hơn
       nhiều so với việc sai.
    """
    async def _load() -> list[dict]:
        return await get_http_client("contract").get(
            "/internal/v1/contracts/active",
            params={"property_id": str(property_id)} if property_id else None,
        )

    data, _degraded = await _cached_live(
        f"report:active-contracts:{property_id or 'ALL'}", _load,
    )
    return None if data is None else len(data)


# ---------------------------------------------------------------------------
#  ĐỌC READ MODEL
# ---------------------------------------------------------------------------
async def _financial_rows(
    session: AsyncSession, key: uuid.UUID, start: date, end: date,
) -> list[DailyFinancial]:
    """
    Đọc `daily_financials` cho 1 phạm vi.

    ⭐ `key == ALL_PROPERTIES` (xem "tất cả cơ sở") KHÔNG có sẵn một dòng tổng
       hợp: `record_financials` luôn ghi theo TỪNG cơ sở (event nào cũng mang
       `property_id`). Vì vậy tổng hệ thống phải CỘNG DỒN khi ĐỌC.

       Không ghi sẵn dòng ALL lúc nhận event vì phép cộng "một phần vào tổng"
       là vô nghĩa khi tổng do nhiều nguồn cùng đóng góp, và ghi kép dễ sinh
       lệch. Cộng lúc đọc luôn đúng với dữ liệu hiện có — kể cả dữ liệu được
       nạp lại bởi đối chiếu.

    ⭐ Dòng `ALL_PROPERTIES` (nếu tồn tại từ trước) bị LOẠI khỏi phép cộng để
       không đếm trùng.
    """
    if key != ALL_PROPERTIES:
        return list((await session.execute(
            select(DailyFinancial)
            .where(DailyFinancial.property_id == key,
                   DailyFinancial.stat_date >= start,
                   DailyFinancial.stat_date <= end)
            .order_by(DailyFinancial.stat_date)
        )).scalars().all())

    rows = (await session.execute(
        select(DailyFinancial)
        .where(DailyFinancial.property_id != ALL_PROPERTIES,
               DailyFinancial.stat_date >= start,
               DailyFinancial.stat_date <= end)
    )).scalars().all()

    merged: dict[date, DailyFinancial] = {}
    for row in rows:
        acc = merged.get(row.stat_date)
        if acc is None:
            acc = DailyFinancial(
                property_id=ALL_PROPERTIES, stat_date=row.stat_date,
                invoices_issued=0, invoiced_amount=ZERO,
                payments_received=0, collected_amount=ZERO,
                refunded_amount=ZERO, outstanding=ZERO,
                overdue_count=0, overdue_amount=ZERO,
            )
            merged[row.stat_date] = acc
        acc.invoices_issued += row.invoices_issued or 0
        acc.invoiced_amount += _num(row.invoiced_amount)
        acc.payments_received += row.payments_received or 0
        acc.collected_amount += _num(row.collected_amount)
        acc.refunded_amount += _num(row.refunded_amount)
        # `outstanding` là số dư chạy theo từng cơ sở → tổng = cộng các số dư.
        acc.outstanding += _num(row.outstanding)
        acc.overdue_count += row.overdue_count or 0
        acc.overdue_amount += _num(row.overdue_amount)

    return [merged[day] for day in sorted(merged)]


async def _occupancy_rows(
    session: AsyncSession, key: uuid.UUID, start: date, end: date,
) -> list[DailyOccupancy]:
    return list((await session.execute(
        select(DailyOccupancy)
        .where(DailyOccupancy.property_id == key,
               DailyOccupancy.stat_date >= start,
               DailyOccupancy.stat_date <= end)
        .order_by(DailyOccupancy.stat_date)
    )).scalars().all())


def _date_span(start: date, end: date) -> list[date]:
    """Danh sách ngày LIÊN TỤC từ start → end (dùng để lấp chỗ trống)."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _revenue_points(
    rows: list[DailyFinancial], start: date, end: date,
) -> tuple[list[RevenuePoint], list[date]]:
    """
    Chuyển dòng `daily_financials` thành điểm biểu đồ.

    ⭐ Ngày KHÔNG có dữ liệu KHÔNG được điền 0. Ta liệt kê nó vào
       `missing_days` để client vẽ đường đứt quãng. Điền 0 sẽ khiến biểu đồ
       rơi thẳng xuống sàn rồi bật lên ở ngày có dữ liệu, và người đọc hiểu
       nhầm là doanh thu bị bằng 0 — một lời nói dối nghiêm trọng hơn nhiều so
       với việc thiếu 1 điểm.
    """
    by_date = {row.stat_date: row for row in rows}
    points: list[RevenuePoint] = []
    missing: list[date] = []

    for day in _date_span(start, end):
        row = by_date.get(day)
        if row is None:
            missing.append(day)
            continue
        points.append(RevenuePoint(
            stat_date=day,
            invoiced=row.invoiced_amount,
            collected=row.collected_amount,
            refunded=row.refunded_amount,
            net_collected=row.net_collected,
            outstanding=row.outstanding,
            invoices_issued=row.invoices_issued,
            payments_received=row.payments_received,
            collection_ratio=row.collection_ratio,
        ))
    return points, missing


def _occupancy_points(
    rows: list[DailyOccupancy], start: date, end: date,
) -> list[OccupancyPoint]:
    by_date = {row.stat_date: row for row in rows}
    points: list[OccupancyPoint] = []
    for day in _date_span(start, end):
        row = by_date.get(day)
        if row is None:
            continue        # không lấp: thiếu dữ liệu ≠ 0 phòng
        points.append(OccupancyPoint(
            stat_date=day,
            total_rooms=row.total_rooms, available=row.available,
            occupied=row.occupied, maintenance=row.maintenance,
            reserved=row.reserved, other=row.other,
            occupancy_rate=row.occupancy_rate, source=row.source,
        ))
    return points


def _to_snapshot(row: DailyOccupancy | None) -> OccupancySnapshot:
    if row is None:
        return OccupancySnapshot()
    return OccupancySnapshot(
        total_rooms=row.total_rooms, available=row.available,
        occupied=row.occupied, maintenance=row.maintenance,
        reserved=row.reserved, other=row.other,
        occupancy_rate=row.occupancy_rate, stat_date=row.stat_date,
        source=row.source, captured_at=row.captured_at,
    )


# =================================================================================
#  TIỆN ÍCH CHO ROUTER
# =================================================================================
#: Nhóm tuổi nợ coi là "đã quá hạn" (mọi nhóm trừ `CHUA_DEN_HAN`).
_OVERDUE_BUCKETS = frozenset(code for code, _label in AGING_BUCKETS[1:])

#: Nhóm "nguy hiểm" — trễ hơn 30 ngày. Đây là phần chủ nhà hành động được
#: (gọi điện, đòi cọc) nên luôn tách riêng khỏi tổng quá hạn.
_SEVERE_BUCKETS = frozenset({"31_60_NGAY", "TREN_60_NGAY"})

#: Số khách nợ nhiều nhất hiện trong báo cáo công nợ.
TOP_DEBTOR_LIMIT = 10


def _month_bounds(day: date) -> tuple[date, date]:
    """Khoảng `[ngày 1, ngày cuối]` của tháng chứa `day`."""
    start = day.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1) - timedelta(days=1)
    return start, end


def _money(value: Any) -> str:
    """
    Định dạng tiền cho CSV.

    ⭐ KHÔNG dùng `f"{value:,}"` — dấu phân cách nghìn kiểu Việt Nam là dấu
    chấm (1.500.000) nhưng Excel mặc định đọc theo kiểu Mỹ nên đọc thành
    1.5. Xuất dạng số nguyên trần là cách duy nhất mà cả Excel Việt lẫn
    Python đều hiểu đúng.
    """
    return str(int(_num(value)))


def _remaining(row: OpenInvoice) -> Decimal:
    """
    Số tiền còn nợ của 1 hóa đơn — CHỐT Ở 0.

    ⭐ Cùng nguyên tắc với R3 (không trừ quá cọc): khách trả thửa cho tròn
    là chuyện thường, và số dư âm trong báo cáo công nợ là con số vô nghĩa.
    """
    return max(ZERO, _num(row.total_amount) - _num(row.paid_amount))


async def _load_open_invoices(
    session: AsyncSession, key: uuid.UUID, *, limit: int | None = None,
) -> list[OpenInvoice]:
    """
    Hóa đơn còn nợ, sắp theo hạn cũ nhất trước.

    ⭐ Sắp theo `due_date` tăng dần vì đó là thứ tự chủ nhà cần xử lý: hóa
       đơn sắp quá hạn nhất phải lên đầu, không phải cái đã trễ 3 tháng
       (thứ đó cần gọi điện chứ không phải để nhắc).

    ⭐ `key == ALL_PROPERTIES` thì KHÔNG lọc theo cơ sở: `open_invoices` vốn
       đã lưu đúng 1 dòng cho mỗi hóa đơn (kèm `property_id`), nên "tất cả cơ
       sở" chỉ là bỏ điều kiện lọc — không cần cộng dồn.
    """
    stmt = (
        select(OpenInvoice)
        .where(OpenInvoice.status.in_(("OPEN", "OVERDUE")))
        .order_by(OpenInvoice.due_date, OpenInvoice.total_amount.desc())
    )
    if key != ALL_PROPERTIES:
        stmt = stmt.where(OpenInvoice.property_id == key)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


def _build_aging(
    rows: list[OpenInvoice], ref: date,
) -> tuple[list[DebtItem], list[AgingBucket]]:
    """
    Tách danh sách hóa đơn còn nợ thành: (a) từng dòng chi tiết, (b) 5 nhóm tuổi nợ.

    `ref` là ngày dùng để tính "đã trễ bao nhiêu ngày" — truyền `to_date` của báo
    cáo, KHÔNG dùng `date.today()` (ngày hệ thống của container là UTC).
    """
    items: list[DebtItem] = []
    amounts = {code: ZERO for code, _ in AGING_BUCKETS}
    counts = {code: 0 for code, _ in AGING_BUCKETS}

    for row in rows:
        left = _remaining(row)
        if left <= ZERO:
            continue          # đã quét đủ → không phải công nợ
        code = row.aging_bucket(ref)
        amounts[code] += left
        counts[code] += 1
        items.append(DebtItem(
            invoice_id=row.invoice_id, invoice_no=row.invoice_no,
            tenant_id=row.tenant_id, tenant_name=row.tenant_name,
            contract_id=row.contract_id,
            room_id=row.room_id, total_amount=_num(row.total_amount),
            paid_amount=_num(row.paid_amount), remaining=left,
            issued_date=row.issued_date, due_date=row.due_date,
            status=row.status, days_overdue=row.days_overdue(ref), bucket=code,
            is_overdue_notified=bool(row.is_overdue_notified),
        ))

    total = sum(amounts.values(), ZERO)
    buckets = [
        AgingBucket(
            bucket=code, label=label, invoice_count=counts[code],
            amount=amounts[code],
            share=round(float(amounts[code]) / float(total) * 100, 2)
            if total > ZERO else 0.0,
        )
        for code, label in AGING_BUCKETS
    ]
    return items, buckets


def _debtor_summaries(items: list[DebtItem], limit: int = TOP_DEBTOR_LIMIT) -> list[DebtorSummary]:
    """
    Gộp công nợ theo từng khách, xếp theo tiền còn nợ giảm dần.

    ⭐ Sắp theo TỔNG TIỀN chứ không theo số hóa đơn: một người nợ 2 triệu
       trong 1 hóa đơn đáng để gọi hơn một người nợ 3 triệu rải trong 8
       hóa đơn cũ vụn — chủ nhà gọi được người nào trả nhiều nhất.
    """
    grouped: dict[tuple[uuid.UUID | None, str], list[DebtItem]] = {}
    for item in items:
        grouped.setdefault((item.tenant_id, item.tenant_name or "(không rõ)"), []).append(item)

    summaries = [
        DebtorSummary(
            tenant_id=tenant_id, tenant_name=tenant_name,
            invoice_count=len(group),
            total_remaining=sum((i.remaining for i in group), ZERO),
            max_days_overdue=max(i.days_overdue for i in group),
        )
        for (tenant_id, tenant_name), group in grouped.items()
    ]
    summaries.sort(key=lambda s: s.total_remaining, reverse=True)
    return summaries[:limit]


async def _contract_flow_rows(
    session: AsyncSession, key: uuid.UUID, start: date, end: date,
) -> list[DailyContractFlow]:
    return list((await session.execute(
        select(DailyContractFlow)
        .where(DailyContractFlow.property_id == key,
               DailyContractFlow.stat_date >= start,
               DailyContractFlow.stat_date <= end)
        .order_by(DailyContractFlow.stat_date)
    )).scalars().all())


#: Cột bộ đếm của `daily_contract_flow` — thứ tự cũng là thứ tự cột CSV.
CONTRACT_FLOW_COLUMNS = ("created", "activated", "terminated",
                         "expired", "cancelled", "renewed")


async def _contract_flow_totals(
    session: AsyncSession, key: uuid.UUID,
) -> dict[str, int]:
    """
    Tổng vòng quay hợp đồng TOÀN BỘ lịch sử (không giới hạn ngày).

    ⭐ Chỉ dùng cho phép so `drift`. Phải là CẢ LỊCH SỬ chứ không phải kỳ:
       `(đã kích hoạt) − (đã kết thúc)` tính trong 30 ngày cho ra "hợp đồng
       mới ròng trong tháng", còn số hợp đồng đang hiệu lực là TÍCH LŨY từ
       đầu. Trừ hai thứ khác đơn vị sẽ ra một con số vô nghĩa — cộng thêm
       vào nó là tự tạo ra "sai số" để rồi đi sửa.
    """
    stmt = select(*(
        func.coalesce(func.sum(getattr(DailyContractFlow, name)), 0)
        for name in CONTRACT_FLOW_COLUMNS
    )).where(DailyContractFlow.property_id == key)
    row = (await session.execute(stmt)).one()
    return {name: _as_int(value) for name, value in zip(CONTRACT_FLOW_COLUMNS, row, strict=True)}


async def _open_incident_summary(
    property_id: uuid.UUID | None,
) -> tuple[dict | None, bool]:
    """
    Tổng hợp sự cố đang mở — proxy qua maintenance-service.

    ⭐ Đây là TRẠNG THÁI hiện tại, không phải sự kiện lịch sử, nên report
       KHÔNG dựng read model cho nó (xem `schemas.MaintenanceReport` để đọc
       lý do). Chỉ có 1 lời gọi + cache 60s.
    """
    async def _load() -> dict:
        return await get_http_client("maintenance").get(
            "/internal/v1/incidents",
            params={"property_id": str(property_id)} if property_id else None,
        )

    return await _cached_live(
        f"report:incidents:{property_id or 'ALL'}", _load,
    )


# =================================================================================
#  ROUTER: BÁO CÁO
# =================================================================================
report_router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

#: Ai được xem báo cáo? Chủ nhà (ADMIN) và quản lý (MANAGER).
#:
#: ⭐ KHÔNG cho TENANT. Báo cáo doanh thu của nhà trọ là thông tin của cả
#:    những người thuê khác — người thuê chỉ được xem hóa đơn CỦA MÌNH, và
#:    đó là câu hỏi của billing-service chứ không phải của báo cáo tổng hợp.
REPORT_ROLES = (Role.ADMIN, Role.MANAGER)

#: Chuỗi hiển thị khi không lọc theo cơ sở. report-service cố ý không chứa
#: bảng `properties` (nguồn chuẩn ở room-service) nên không có tên để hiện.
ALL_LABEL = "Tất cả cơ sở"


@report_router.get("/dashboard", response_model=DashboardResponse,
                   summary="Tổng quan 1 màn hình")
async def report_dashboard(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = Query(
        None, description="Bỏ trống = tất cả cơ sở (ADMIN mới được xem toàn hệ thống)",
    ),
    to_date: date | None = Query(
        None, description="Mốc cuối (mặc định = hôm nay theo giờ VN)",
    ),
) -> DashboardResponse:
    """
    Endpoint quan trọng nhất: gom 8 chỉ số vận hành vào 1 chỗ.

    ⭐ 2 con số (`active_contracts`, `open_incidents`) là TRẠNG THÁI hiện tại
       nên phải gọi service khác, và ta gọi SONG SONG bằng
       `return_exceptions=True`. Nếu không, một service chết sẽ làm cả
       dashboard trả 500 — trong khi 6 ô còn lại vẫn có dữ liệu đúng. Tệ hơn
       nữa: báo cáo chết thì người quản lý không thấy ô "công nợ" đang
       tăng, tức là mất đúng thông tin lúc cần nhất.
    """
    pid = _resolve_property(user, property_id)
    key = _report_key(pid)
    today = business_day()
    window = _window(30, to_date)
    month_start, _month_end = _month_bounds(window.to_date)
    degraded: list[str] = []

    fin_rows = await _financial_rows(session, key, window.from_date, window.to_date)
    month_rows = await _financial_rows(session, key, month_start, window.to_date)
    occ_rows = await _occupancy_rows(session, key, window.from_date, window.to_date)
    debt_rows = await _load_open_invoices(session, key)

    revenue_points, _missing = _revenue_points(fin_rows, window.from_date, window.to_date)
    occupancy_points = _occupancy_points(occ_rows, window.from_date, window.to_date)
    debt_items, aging = _build_aging(debt_rows, window.to_date)

    invoiced = sum((_num(r.invoiced_amount) for r in month_rows), ZERO)
    collected = sum((_num(r.collected_amount) for r in month_rows), ZERO)
    open_debt = sum((i.remaining for i in debt_items), ZERO)
    overdue_debt = sum(
        (i.remaining for i in debt_items if i.bucket in _OVERDUE_BUCKETS), ZERO,
    )
    today_occ = next((r for r in occ_rows if r.stat_date == today), None)
    snapshot = _to_snapshot(today_occ)

    contracts_result, incidents_result = await asyncio.gather(
        _active_contract_count(pid), _open_incident_summary(pid),
        return_exceptions=True,
    )

    active_contracts: int | None
    if isinstance(contracts_result, BaseException):
        logger.warning("Dashboard: không lấy được số hợp đồng đang hiệu lực: %s",
                       contracts_result)
        active_contracts = None
    else:
        active_contracts = contracts_result
    if active_contracts is None:
        degraded.append("contract-service")

    if isinstance(incidents_result, BaseException):
        degraded.append("maintenance-service")
        incident_data: dict | None = None
    else:
        incident_data, incident_degraded = incidents_result
        if incident_degraded:
            degraded.append("maintenance-service")
    open_incidents = (
        None if incident_data is None
        else sum(_as_int(v.get("open"))
                 for v in (incident_data.get("by_category") or {}).values())
    )

    # Gauge cho Prometheus: cảnh báo được ngay mà không cần ai mở dashboard.
    label = str(pid) if pid else "-"
    set_business_gauge(settings.service_name, "rooms_available",
                       float(snapshot.available), label)
    set_business_gauge(settings.service_name, "occupancy_rate",
                       float(snapshot.occupancy_rate), label)
    set_business_gauge(settings.service_name, "open_debt", float(open_debt), label)

    return DashboardResponse(
        property_id=pid,
        property_label=(str(pid) if pid else ALL_LABEL),
        generated_at=datetime.now(UTC),
        freshness=await _freshness(session, ["billing", "room", "contract", "maintenance"]),
        kpi={
            "revenue_month": collected,
            "collection_ratio": (round(float(collected) / float(invoiced) * 100, 2)
                                 if invoiced > ZERO else 0.0),
            "occupancy_rate": snapshot.occupancy_rate if today_occ else None,
            "rooms_available": snapshot.available if today_occ else None,
            "open_debt": open_debt,
            "overdue_debt": overdue_debt,
            "active_contracts": active_contracts,
            "open_incidents": open_incidents,
        },
        revenue_30d=revenue_points,
        occupancy_30d=occupancy_points,
        aging=aging,
        degraded_sources=sorted(set(degraded)),
    )


@report_router.get("/revenue", response_model=RevenueReport,
                   summary="Doanh thu, thu hồi & công nợ")
async def report_revenue(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = Query(None),
    days: int = Query(30, ge=1, le=730, description="Số ngày (tối đa 730 = hạn lưu chi tiết)"),
    to_date: date | None = Query(None),
) -> RevenueReport:
    """
    Doanh thu theo ngày.

    ⭐ `total_outstanding` là số dư công nợ CUỐI KỲ, lấy từ dòng ngày cuối
       cùng — KHÔNG cộng dồn các ngày. Vì `outstanding` là số dư chạy: cộng
       3 triệu trong 30 ngày vào 3 triệu hôm nay sẽ ra "90 triệu công nợ",
       một con số không mô tả được gì.
    """
    pid = _resolve_property(user, property_id)
    window = _window(days, to_date)
    rows = await _financial_rows(
        session, _report_key(pid), window.from_date, window.to_date,
    )
    points, missing = _revenue_points(rows, window.from_date, window.to_date)

    invoiced = sum((_num(r.invoiced_amount) for r in rows), ZERO)
    collected = sum((_num(r.collected_amount) for r in rows), ZERO)
    refunded = sum((_num(r.refunded_amount) for r in rows), ZERO)

    return RevenueReport(
        window=window,
        freshness=await _freshness(session, ["billing", "contract"]),
        total_invoiced=invoiced,
        total_collected=collected,
        total_refunded=refunded,
        net_collected=collected - refunded,
        total_outstanding=_num(rows[-1].outstanding) if rows else ZERO,
        invoices_issued=sum(r.invoices_issued for r in rows),
        payments_received=sum(r.payments_received for r in rows),
        avg_collection_ratio=(
            round(float(collected) / float(invoiced) * 100, 2)
            if invoiced > ZERO else 0.0
        ),
        best_day=max(points, key=lambda p: p.collected, default=None),
        worst_day=min(points, key=lambda p: p.collected, default=None),
        missing_days=missing,
        points=points,
    )


@report_router.get("/occupancy", response_model=OccupancyReport,
                   summary="Công suất phòng")
async def report_occupancy(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = Query(None),
    days: int = Query(30, ge=1, le=730),
    to_date: date | None = Query(None),
) -> OccupancyReport:
    """Tỷ lệ lấp đầy phòng theo ngày + trạng thái hiện tại."""
    pid = _resolve_property(user, property_id)
    window = _window(days, to_date)
    rows = await _occupancy_rows(
        session, _report_key(pid), window.from_date, window.to_date,
    )
    points = _occupancy_points(rows, window.from_date, window.to_date)

    # Ưu tiên dòng của HÔM NAY. Nếu hôm nay chưa có event nào (mới cài, hoặc
    # 3 giờ sáng chưa ai thay phòng) thì lùi về dòng gần nhất — dashboard
    # trắng trơn lúc nửa đêm là tệ hơn là hiện số hơi cũ, và `freshness`
    # đã nói rõ số liệu được chụp lúc nào.
    today = business_day()
    current = next((r for r in rows if r.stat_date == today), None) or (
        rows[-1] if rows else None
    )

    rates = [p.occupancy_rate for p in points]
    return OccupancyReport(
        window=window,
        freshness=await _freshness(session, ["room"]),
        current=_to_snapshot(current),
        avg_occupancy_rate=(round(sum(rates) / len(rates), 2) if rates else 0.0),
        peak_occupancy_rate=max(rates, default=0.0),
        low_occupancy_rate=min(rates, default=0.0),
        points=points,
    )


@report_router.get("/collections", response_model=CollectionsReport,
                   summary="Phân rã công nợ (aging) & danh sách khách nợ")
async def report_collections(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = Query(None),
    days: int = Query(30, ge=1, le=365, description="Kỳ tính tỷ lệ thu hồi"),
    to_date: date | None = Query(None),
    include_items: bool = Query(
        True, description="Tắt để chỉ lấy tổng + phân rã (nhẹ hơn nhiều)",
    ),
    limit: int = Query(200, ge=1, le=1000, description="Số dòng chi tiết tối đa"),
) -> CollectionsReport:
    """
    Báo cáo công nợ — câu hỏi mà billing-service cố ý không trả lời được.

    ⭐ Không có limit khi tính TỔNG: tổng phải đúng tuyệt đối, giới hạn chỉ
       áp cho danh sách chi tiết. Nếu giới hạn luôn thì tổng của cơ sở có
       5.000 hóa đơn nợ sẽ nhỏ hơn thật — và người quản lý đi đòi tiền
       thiếu rồi lại bị báo "đã thu đủ". `truncated` nói rõ phần nào bị cắt.
    """
    pid = _resolve_property(user, property_id)
    window = _window(days, to_date)
    key = _report_key(pid)

    rows = await _load_open_invoices(session, key)
    items, buckets = _build_aging(rows, window.to_date)

    total_open = sum((i.remaining for i in items), ZERO)
    overdue_items = [i for i in items if i.bucket in _OVERDUE_BUCKETS]
    severe_items = [i for i in items if i.bucket in _SEVERE_BUCKETS]

    fin_rows = await _financial_rows(session, key, window.from_date, window.to_date)
    invoiced = sum((_num(r.invoiced_amount) for r in fin_rows), ZERO)
    ratio = 0.0
    if invoiced > ZERO:
        ratio = max(0.0, min(100.0, round(
            float(invoiced - total_open) / float(invoiced) * 100, 2,
        )))

    shown = items[:limit] if include_items else []
    return CollectionsReport(
        window=window,
        freshness=await _freshness(session, ["billing"]),
        total_open=total_open,
        open_invoice_count=len(items),
        total_overdue=sum((i.remaining for i in overdue_items), ZERO),
        overdue_invoice_count=len(overdue_items),
        severe_overdue=sum((i.remaining for i in severe_items), ZERO),
        severe_overdue_count=len(severe_items),
        collection_ratio=ratio,
        buckets=buckets,
        top_debtors=_debtor_summaries(items),
        items=shown,
        truncated=len(shown) < len(items),
    )


@report_router.get("/contracts", response_model=ContractFlowReport,
                   summary="Vòng quay hợp đồng & tỷ lệ khách rời đi")
async def report_contracts(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = Query(None),
    days: int = Query(90, ge=1, le=730),
    to_date: date | None = Query(None),
) -> ContractFlowReport:
    """
    Bao nhiêu hợp đồng mới / kết thúc trong kỳ, và có bao nhiêu đang hiệu lực.

    ⭐ `drift` là CHỈ BÁO SỨC KHOẺ của read model: `(đã kích hoạt − đã kết
       thúc) TÍNH CẢ LỊCH SỬ` trừ `active_contracts` lấy thật từ
       contract-service. Chênh khác 0 nghĩa là read model đang lệch — và
       vì `active_contracts` đến từ nguồn chuẩn nên nó là "đáp án đúng".
    """
    pid = _resolve_property(user, property_id)
    window = _window(days, to_date)
    key = _report_key(pid)

    rows = await _contract_flow_rows(session, key, window.from_date, window.to_date)
    points = [
        ContractFlowPoint(
            stat_date=r.stat_date, created=r.created, activated=r.activated,
            terminated=r.terminated, expired=r.expired,
            cancelled=r.cancelled, renewed=r.renewed, net_new=r.net_new,
        )
        for r in rows
    ]
    totals = {name: sum(getattr(r, name) for r in rows)
              for name in CONTRACT_FLOW_COLUMNS}

    history = await _contract_flow_totals(session, key)
    active = await _active_contract_count(pid)
    drift = None
    if active is not None:
        drift = (history["activated"]
                 - history["terminated"] - history["expired"]
                 - history["cancelled"]) - active

    left = totals["terminated"] + totals["expired"] + totals["cancelled"]
    churn_base = left + (active or 0)
    return ContractFlowReport(
        window=window,
        freshness=await _freshness(session, ["contract"]),
        total_created=totals["created"],
        total_activated=totals["activated"],
        total_terminated=totals["terminated"],
        total_expired=totals["expired"],
        total_cancelled=totals["cancelled"],
        total_renewed=totals["renewed"],
        net_new=sum(p.net_new for p in points),
        active_contracts=active,
        drift=drift,
        churn_rate=(round(left / churn_base * 100, 2) if churn_base else 0.0),
        points=points,
    )


@report_router.get("/maintenance", response_model=MaintenanceReport,
                   summary="Tình hình sự cố (proxy maintenance-service)")
async def report_maintenance(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORT_ROLES))],
    property_id: uuid.UUID | None = Query(None),
) -> MaintenanceReport:
    """
    ⭐ Endpoint DUY NHẤT của report-service gọi service khác khi đọc, và
       KHÔNG có read model riêng — vì nó đọc 5 con số 1 lần/ngày. Xem
       `schemas.MaintenanceReport` để đọc lý do đầy đủ.

    Khác mọi endpoint khác: khi maintenance-service chết hẳn (không có cache
    để dùng), ta ném 503 thay vì trả `0`. Trả 0 nghĩa là "không có sự cố
    nào" — đúng cái tin tủy nhất mà người quản lý có thể nhận lúc nhà trọ
    đang cháy. 503 thì client biết phải báo "tạm chưa lấy được".
    """
    pid = _resolve_property(user, property_id)
    data, degraded = await _open_incident_summary(pid)
    if data is None:
        raise ServiceUnavailableError(
            "maintenance-service không phản hồi và cache đã hết hạn. "
            "Báo cáo sự cố tạm không lấy được — thử lại sau ít phút."
        )
    return MaintenanceReport(
        property_id=pid,
        total=_as_int(data.get("total")),
        by_category=data.get("by_category") or {},
        total_cost=_num(data.get("total_cost")),
        fetched_at=datetime.now(UTC),
        degraded=degraded,
    )


@report_router.get("/monthly", summary="Doanh thu đã tổng hợp theo tháng (giữ ~5 năm)")
async def report_monthly(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = Query(None),
    months: int = Query(24, ge=1, le=60, description="Số tháng gần nhất (tối đa 60)"),
) -> list[dict]:
    """
    Đọc bảng `monthly_financials` — dữ liệu đã qua 730 ngày được tổng hợp
    theo tháng rồi mới xoá chi tiết, nên xem lịch sử dài ở đây.

    ⭐ Cột `outstanding` không có ở đây, và cũng không thể có: đó là số dư
       chạy, cộng dồn theo tháng sẽ ra "34 tỷ công nợ". Số dư công nợ chỉ
       có ý nghĩa ở `daily_financials`.
    """
    pid = _resolve_property(user, property_id)
    rows = (await session.execute(
        select(MonthlyFinancial)
        .where(MonthlyFinancial.property_id == _report_key(pid))
        .order_by(MonthlyFinancial.period.desc())
        .limit(months)
    )).scalars().all()

    return [
        {
            "period": r.period,
            "invoices_issued": r.invoices_issued,
            "invoiced_amount": str(r.invoiced_amount),
            "payments_received": r.payments_received,
            "collected_amount": str(r.collected_amount),
            "refunded_amount": str(r.refunded_amount),
            "net_collected": str(r.net_collected),
            "days_covered": r.days_covered,
        }
        for r in reversed(rows)
    ]


#: Các báo cáo được phép xuất CSV.
EXPORT_KINDS = ("revenue", "occupancy", "collections", "contracts")


@report_router.get("/export", summary="Xuất báo cáo ra CSV (mở được bằng Excel)")
async def report_export(
    user: Annotated[CurrentUser, Depends(require_roles(*REPORT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    report: str = Query("revenue", description=f"Một trong: {', '.join(EXPORT_KINDS)}"),
    property_id: uuid.UUID | None = Query(None),
    days: int = Query(30, ge=1, le=730),
    to_date: date | None = Query(None),
) -> Response:
    """
    Xuất CSV để mở bằng Excel/Tiến Việt.

    ⭐ Đầu file có BOM (`\\ufeff`): không có nó, Excel đọc UTF-8 bằng codepage
       cũ và hiện "Nguyá»…n Văn Ánh" thay vì tên tiếng Việt — chi tiết nhỏ
       nhưng là thứ khiến cả báo cáo trông như lỗi.
    """
    if report not in EXPORT_KINDS:
        raise BusinessRuleError(
            f"Không có báo cáo '{report}'. Chọn một trong: {', '.join(EXPORT_KINDS)}"
        )

    pid = _resolve_property(user, property_id)
    window = _window(days, to_date)
    key = _report_key(pid)
    rows: list[list] = []

    if report == "revenue":
        fin = await _financial_rows(session, key, window.from_date, window.to_date)
        rows.append([
            "Ngay", "Phat hanh", "Da thu", "Da hoan", "Thuan thu",
            "Con no (cuoi ky)", "So hoa don", "So lan thu", "Ty le thu (%)",
        ])
        for r in fin:
            rows.append([
                r.stat_date.isoformat(), _money(r.invoiced_amount),
                _money(r.collected_amount), _money(r.refunded_amount),
                _money(r.net_collected), _money(r.outstanding),
                r.invoices_issued, r.payments_received, r.collection_ratio,
            ])

    elif report == "occupancy":
        occ = await _occupancy_rows(session, key, window.from_date, window.to_date)
        rows.append([
            "Ngay", "Tong phong", "Trong", "Co nguoi", "Dang sua",
            "Da giu cho", "Khac", "Ty le lap day (%)", "Nguon",
        ])
        for r in occ:
            rows.append([
                r.stat_date.isoformat(), r.total_rooms, r.available, r.occupied,
                r.maintenance, r.reserved, r.other, r.occupancy_rate, r.source,
            ])

    elif report == "collections":
        debts = await _load_open_invoices(session, key)
        items, _buckets = _build_aging(debts, window.to_date)
        rows.append([
            "So hoa don", "Nguoi thue", "Ngay phat hanh", "Han tra",
            "Tong tien", "Da tra", "Con no", "Tre (ngay)", "Nhom tuoi no",
            "Trang thai", "Da nhac qua han",
        ])
        for i in items:
            rows.append([
                i.invoice_no, i.tenant_name or "", i.issued_date.isoformat(),
                i.due_date.isoformat(), _money(i.total_amount),
                _money(i.paid_amount), _money(i.remaining), i.days_overdue,
                i.bucket, i.status, "co" if i.is_overdue_notified else "khong",
            ])

    else:   # contracts
        flow = await _contract_flow_rows(session, key, window.from_date, window.to_date)
        rows.append(["Ngay", "Tao moi", "Kich hoat", "Cham dung", "Het han",
                     "Huy", "Gia han", "Tang rong"])
        for r in flow:
            rows.append([
                r.stat_date.isoformat(), r.created, r.activated, r.terminated,
                r.expired, r.cancelled, r.renewed, r.net_new,
            ])

    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    filename = f"qlpt-{report}-{window.from_date}_den_{window.to_date}.csv"
    return Response(
        content=CSV_BOM + buffer.getvalue(),   # BOM: Excel mới đọc đúng tiếng Việt
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =================================================================================
#  INTERNAL API
# =================================================================================
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


@internal_router.post("/reports/reconcile", response_model=ReconcileResponse,
                      summary="[Nội bộ] Chạy 1 lần đối chiếu read model")
async def internal_reconcile(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    property_id: uuid.UUID | None = Query(
        None, description="Bỏ trống = đối chiếu toàn hệ thống",
    ),
    with_retention: bool = Query(
        True, description="Kèm tổng hợp tháng + dọn dữ liệu quá hạn",
    ),
) -> ReconcileResponse:
    """
    Được container `scheduler` gọi định kỳ (và `make reconcile` gọi tay).

    ⭐ KHÔNG khoá phân tán ở đây — job nền `_reconcile_loop` đã giữ khoá
       rồi. Endpoint cố ý cho phép gọi chồng (nó idempotent, chỉ tốn vài
       chục lời gọi nội bộ) vì nếu khoá luôn thì `make reconcile` lúc đang
       có sự cố sẽ không làm được gì cả, và người vận hành mất đường sửa.

    Trả về `ReconcileResponse` chứ không phải `MessageResponse` — scheduler
    cần BIẾT kết quả từng nhóm để ghi log cảnh báo.
    """
    return await _run_reconcile(
        kind="reconcile", property_id=property_id,
        triggered_by="scheduler", with_retention=with_retention,
    )


@internal_router.get("/reports/summary", response_model=SummaryResponse,
                     summary="[Nội bộ] Tóm tắt nhanh (cho cron/giám sát ngoài)")
async def internal_summary(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM, Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = Query(None),
) -> SummaryResponse:
    """
    Một màn hình số chạy được bằng 1 lệnh `curl` — dành cho container
    `scheduler` in ra log hằng ngày, hoặc Uptime Kiem tra có dùng được hay
    không mà không cần biết cấu trúc báo cáo đầy đủ.

    ⭐ Đọc thẳng read model, KHÔNG gọi service khác: mục đích của endpoint
       này là "còn sống không, số liệu có đang chạy không" — thêm lời gọi
       mạng vào đây thì lúc nó cần nhất (khi 1 service đang chết) chính nó
       sẽ chết theo.
    """
    key = _report_key(property_id)
    today = business_day()
    month_start, _month_end = _month_bounds(today)

    today_row = (await session.execute(
        select(DailyFinancial).where(
            DailyFinancial.property_id == key,
            DailyFinancial.stat_date == today,
        )
    )).scalars().first()
    month_rows = await _financial_rows(session, key, month_start, today)

    debts = await _load_open_invoices(session, key)
    items, _buckets = _build_aging(debts, today)
    snapshot = _to_snapshot((await session.execute(
        select(DailyOccupancy).where(
            DailyOccupancy.property_id == key,
            DailyOccupancy.stat_date == today,
        )
    )).scalars().first())

    freshness = await _freshness(session, ["billing", "room", "contract"])
    return SummaryResponse(
        as_of=datetime.now(UTC),
        revenue_today=_num(today_row.collected_amount) if today_row else ZERO,
        revenue_month=sum((_num(r.collected_amount) for r in month_rows), ZERO),
        invoices_issued_month=sum(r.invoices_issued for r in month_rows),
        open_debt=sum((i.remaining for i in items), ZERO),
        overdue_debt=sum(
            (i.remaining for i in items if i.bucket in _OVERDUE_BUCKETS), ZERO,
        ),
        occupancy_rate=snapshot.occupancy_rate,
        total_rooms=snapshot.total_rooms,
        available_rooms=snapshot.available,
        is_stale=freshness.is_stale,
        last_sync_at=freshness.last_sync_at,
    )


@internal_router.get("/reports/sync-runs", response_model=list[SyncRunResponse],
                     summary="[Nội bộ] Lịch sử các lần đối chiếu")
async def internal_sync_runs(
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM, Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=200),
) -> list[SyncRunResponse]:
    """
    Khi số liệu trên dashboard lệch với thực tế, câu hỏi đầu tiên luôn là
    "lần đối chiếu gần nhất chạy lúc nào, ra kết quả gì, lỗi ở đâu?".
    Có bảng này thì trả lời được; không có thì phải đào log container — mà
    log thì đã bị xoá vòng.
    """
    rows = (await session.execute(
        select(SyncRun)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    )).scalars().all()
    return [
        SyncRunResponse(
            id=r.id, kind=r.kind, property_id=r.property_id, status=r.status,
            rows_synced=r.rows_synced, detail=r.detail, message=r.message,
            started_at=r.started_at, finished_at=r.finished_at,
            duration_ms=r.duration_ms, triggered_by=r.triggered_by,
        )
        for r in rows
    ]


# =================================================================================
#  ĐĂNG KÝ ROUTER
# =================================================================================
app.include_router(report_router)
app.include_router(internal_router)
