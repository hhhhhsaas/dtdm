"""
================================================================================================
notification-service — Thông báo đa kênh.  Cổng 8006  |  db_notify
================================================================================================

Vai trò: BIẾN event nghiệp vụ thành tin nhắn mà con người đọc được.

    billing ──invoice.issued──▶ ┐
    contract ─contract.expiring▶│
    room ─room.status_changed──▶┼──▶ notification ──▶ [ IN_APP | EMAIL | SMS | ZALO ]
    maintenance ─incident.urgent▶┘                        (Adapter pattern)

================================================================================================
BA NGUYÊN TẮC ĐỊNH HÌNH TOÀN BỘ FILE NÀY
================================================================================================
1. **KHÔNG SAO CHÉP DỮ LIỆU NGHIỆP VỤ.**
   db_notify không có bảng `invoices`, `contracts`, `incidents`... Mọi thứ nó biết về
   một hóa đơn đều đến từ `context: dict` trong event. Nhờ vậy đổi cấu trúc hóa đơn không
   phải sửa notification, và db_notify có thể xoá dựng lại bất cứ lúc nào.

2. **MỘT SỰ KIỆN NGHIỆP VỤ = MỘT THÔNG BÁO.**
   `dedupe_key` UNIQUE, tính theo CÔNG THỨC NGHIỆP VỤ chứ không theo `event_id`:

       INVOICE_ISSUED:2026-10-0001
       CONTRACT_EXPIRING:HD-2026-0001:30
       INCIDENT_CREATED:SC-0042

   Nhờ vậy scheduler chạy lại 5 lần trong ngày, người thuê vẫn chỉ nhận 1 lần.

3. **GHI, KHÔNG GỬI NGAY.**
   Consumer chỉ ghi vào bảng `notifications` với trạng thái `QUEUED`. Việc gửi thật do
   `_dispatcher_loop` đảm nhiệm. Lý do tách 2 đóa:
     - Consumer phải xử lý nhanh (prefetch=10); gửi email mất vài giây sẽ làm nghẽn
       cả hàng đợi, và 1 email treo 30 giây sẽ giữ khoá consumer.
     - Khi container chết giữa chừng, thông báo còn nằm trong DB → restart là gửi tiếp,
       không mất. Nếu gửi thẳng thì đã gửi xong rồi chết là mất dấu vết.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request, status
from jinja2 import TemplateError
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from channels import CHANNELS, get_channel, render, template_variables
from common import (
    BusinessRuleError,
    ConflictError,
    CurrentUser,
    NotFoundError,
    PageParams,
    Role,
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
from common.repository import acquire_lock, release_lock
from common.telemetry import set_business_gauge
from models import (
    PRIORITY_RANK,
    Channel,
    Notification,
    NotificationStatus,
    Priority,
    Template,
)
from schemas import (
    BulkSendRequest,
    BulkSendResponse,
    NotificationListItem,
    NotificationResponse,
    NotificationSendRequest,
    NotificationStats,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateUpsert,
)

logger = logging.getLogger(__name__)

#: Số thông báo gửi trong 1 lượt của dispatcher.
DISPATCH_BATCH = 20

#: TTL cache thông tin liên hệ của người thuê (giây). Số điện thoại/email đổi rất
#: hiếm, nhưng vẫn để TTL để khi admin sửa hồ sơ thì thông báo sau dùng đúng.
CACHE_TTL_CONTACT = 3600

#: TTL khoá phân tán của dispatcher. Lớn hơn chu kỳ quét để replica khác không giành
#: được khoá giữa 2 lượt (nếu TTL < chu kỳ thì có khoảng trống không ai gửi).
LOCK_TTL_DISPATCH = 60

#: Redis của ứng dụng, giữ ở module scope để các consumer (chạy ngoài request) dùng
#: lại được — mỗi lần tạo `redis.from_url()` sẽ tạo thêm một connection pool.
_REDIS: Any = None


# =================================================================================================
#  DỮ LIỆU THAM CHIẾU
# =================================================================================================
#: Context giả đủ số biến mà MỌI template có thể dùng. Dùng cho preview và cho
#: kiểm tra khi lưu template — nhờ vậy người dùng biết trước những biến nào "miễn phí",
#: và một template gõ sai biến bị chặn NGAY khi lưu chứ không phải lúc gửi cho 200 người.
SAMPLE_CONTEXT: dict[str, str] = {
    "tenant_name": "Nguyễn Văn An",
    "tenant_email": "an.nguyen@example.com",
    "tenant_phone": "0901234567",
    "property_name": "Nhà trọ Minh Anh",
    "room_number": "P-201",
    "invoice_no": "HD-202610-0042",
    "period": "10/2026",
    "due_date": "05/11/2026",
    "total_amount": "3.150.000đ",
    "outstanding": "1.150.000đ",
    "rent_amount": "2.500.000đ",
    "electric_amount": "380.000đ",
    "water_amount": "70.000đ",
    "service_amount": "200.000đ",
    "late_fee_amount": "0đ",
    "deposit_deducted": "0đ",
    "amount": "2.000.000đ",
    "method": "chuyển khoản ngân hàng",
    "contract_no": "HD-2026-0001",
    "start_date": "01/10/2026",
    "end_date": "30/09/2027",
    "monthly_price": "2.500.000đ",
    "days_left": "30",
    "ticket_no": "SC-0042",
    "title": "Rò rỉ nước dưới bếp",
    "category": "LEAK",
    "priority": "HIGH",
    "reported_by": "Nguyễn Văn An",
    "reported_at": "28/09/2026",
    "from_status": "trống",
    "to_status": "đang sửa chữa",
    "reason": "Sự cố nghiêm trọng",
    "detail": "Nội dung thông báo",
}

#: Mã phương thức thanh toán → tiếng Việt. Gửi "CASH" cho người thuê là gửi mã kỹ
#: thuật; họ cần đọc "tiền mặt".
_PAYMENT_METHODS: dict[str, str] = {
    "CASH": "tiền mặt",
    "BANK_TRANSFER": "chuyển khoản ngân hàng",
    "CHUYEN_KHOAN": "chuyển khoản ngân hàng",
    "MOMO": "MoMo",
    "VNPAY": "VNPay",
    "CARD": "thẻ",
    "DEPOSIT": "trừ vào tiền cọc",
}

#: Mã trạng thái phòng → tiếng Việt. Gửi "MAINTENANCE" cho chủ trọ là gửi mã kỹ
#: thuật; họ cần đọc "đang sửa chữa".
_ROOM_STATUSES: dict[str, str] = {
    "AVAILABLE": "trống",
    "OCCUPIED": "đang thuê",
    "MAINTENANCE": "đang sửa chữa",
    "RESERVED": "đã đặt giữ",
}

#: ⭐ Seed bằng `ON CONFLICT DO NOTHING` — KHÔNG ghi đè template người dùng đã sửa.
#:    Nếu dùng `DO UPDATE`, mỗi lần restart container là mất sạch chỉnh sửa câu chữ.
#:    Nguồn sự thật là bảng `templates`; Python chỉ cung cấp giá trị khởi tạo.
DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "code": "INVOICE_ISSUED",
        "channel": Channel.EMAIL.value,
        "name": "Phát hành hóa đơn tiền phòng",
        "subject": "Hóa đơn {{ invoice_no }} — hạn trả {{ due_date }}",
        "body": (
            "Xin chào {{ tenant_name }},\n\n"
            "Hóa đơn tiền phòng kỳ {{ period }} đã được phát hành:\n\n"
            "  Mã hóa đơn    : {{ invoice_no }}\n"
            "  Phòng         : {{ room_number }}\n"
            "  Tiền phòng    : {{ rent_amount }}\n"
            "  Tiền điện     : {{ electric_amount }}\n"
            "  Tiền nước     : {{ water_amount }}\n"
            "  Phí dịch vụ   : {{ service_amount }}\n"
            "  Phí trễ hạn   : {{ late_fee_amount }}\n"
            "  Trừ tiền cọc  : {{ deposit_deducted }}\n"
            "  ------------------------------------------\n"
            "  TỔNG CỘNG    : {{ total_amount }}\n\n"
            "Hạn thanh toán: {{ due_date }}. Vui lòng trả trước hạn để tránh phí trễ hạn.\n\n"
            "Trân trọng,\nBan quản lý {{ property_name }}\n"
        ),
        "description": "Gửi ngay khi billing phát hành hóa đơn (event invoice.issued).",
    },
    {
        "code": "INVOICE_OVERDUE",
        "channel": Channel.EMAIL.value,
        "name": "Nhắc hóa đơn quá hạn",
        "subject": "Hóa đơn {{ invoice_no }} đã quá hạn {{ days_overdue }} ngày",
        "body": (
            "Xin chào {{ tenant_name }},\n\n"
            "Hóa đơn {{ invoice_no }} (kỳ {{ period }}) hạn trả {{ due_date }} "
            "hiện đã quá hạn {{ days_overdue }} ngày.\n\n"
            "  Số tiền còn phải trả: {{ outstanding }}\n\n"
            "Đề nghị bạn thanh toán trong thời gian sớm nhất. Nếu đã thanh toán, "
            "xin báo lại để chúng tôi đối chiếu và cập nhật.\n\n"
            "Trân trọng,\nBan quản lý {{ property_name }}\n"
        ),
        "description": "Gửi khi hóa đơn quá hạn (event invoice.overdue).",
    },
    {
        "code": "PAYMENT_RECEIVED",
        "channel": Channel.IN_APP.value,
        "name": "Xác nhận đã nhận thanh toán",
        "subject": None,
        "body": (
            "Đã ghi nhận thanh toán {{ amount }} cho hóa đơn {{ invoice_no }} "
            "(phương thức {{ method }}).\n"
            "Phòng {{ room_number }} — người thuê {{ tenant_name }}.\n"
        ),
        "description": "Gửi cho quản lý khi ghi nhận tiền (event payment.received).",
    },
    {
        "code": "CONTRACT_ACTIVATED",
        "channel": Channel.IN_APP.value,
        "name": "Hợp đồng đã có hiệu lực",
        "subject": None,
        "body": (
            "Hợp đồng {{ contract_no }} của phòng {{ room_number }} đã có hiệu lực.\n"
            "  Người thuê : {{ tenant_name }}\n"
            "  Kỳ hạn    : {{ start_date }} → {{ end_date }}\n"
            "  Tiền phòng: {{ monthly_price }}/tháng\n"
        ),
        "description": "Thông báo cho quản lý khi hợp đồng kích hoạt (event contract.activated).",
    },
    {
        "code": "CONTRACT_EXPIRING",
        "channel": Channel.EMAIL.value,
        "name": "Nhắc gia hạn hợp đồng",
        "subject": "Hợp đồng {{ contract_no }} sắp hết hạn sau {{ days_left }} ngày",
        "body": (
            "Xin chào {{ tenant_name }},\n\n"
            "Hợp đồng {{ contract_no }} của phòng {{ room_number }} sẽ kết thúc "
            "vào ngày {{ end_date }} (còn {{ days_left }} ngày).\n\n"
            "Nếu bạn muốn tiếp tục ở, vui lòng liên hệ ban quản lý trước ngày "
            "{{ end_date }} để ký gia hạn. Nếu không gia hạn, bạn vui lòng trả "
            "phòng và bàn giao chìa khoá đúng hạn.\n\n"
            "Trân trọng,\nBan quản lý {{ property_name }}\n"
        ),
        "description": "Nhắc trước 30/7/1 ngày (event contract.expiring).",
    },
    {
        "code": "CONTRACT_EXPIRED",
        "channel": Channel.IN_APP.value,
        "name": "Hợp đồng đã kết thúc",
        "subject": None,
        "body": (
            "Hợp đồng {{ contract_no }} (phòng {{ room_number }}) đã kết thúc "
            "vào ngày {{ end_date }}.\n"
            "Người thuê: {{ tenant_name }}.\n"
            "Nhớ kiểm tra lại tiền cọc và hoá đơn cuối cùng.\n"
        ),
        "description": "Thông báo cho quản lý khi hợp đồng hết hạn (event contract.expired).",
    },
    {
        "code": "INCIDENT_CREATED",
        "channel": Channel.IN_APP.value,
        "name": "Có sự cố mới",
        "subject": None,
        "body": (
            "Sự cố {{ ticket_no }} tại phòng {{ room_number }}: {{ title }}\n"
            "  Mức độ   : {{ priority }}\n"
            "  Loại     : {{ category }}\n"
            "  Người báo: {{ reported_by }}\n"
        ),
        "description": "Báo cho quản lý khi người thuê báo sự cố (event incident.created).",
    },
    {
        "code": "INCIDENT_URGENT",
        "channel": Channel.IN_APP.value,
        "name": "Sự cố nghiêm trọng — cần xử lý ngay",
        "subject": None,
        "body": (
            "⚠ SỰ CỐ NGHIÊM TRỌNG — Phòng {{ room_number }} đã tạm ngừng cho thuê.\n"
            "  Mã sự cố : {{ ticket_no }}\n"
            "  Vấn đề   : {{ title }}\n"
            "  Người báo: {{ reported_by }}\n"
            "  Lúc      : {{ reported_at }}\n\n"
            "Hợp đồng của {{ tenant_name }} vẫn giữ nguyên — người thuê KHÔNG mất tiền "
            "vì lỗi này.\n"
        ),
        "description": "Báo ngay cho quản lý (event incident.urgent / incident.escalated).",
    },
    {
        "code": "INCIDENT_RESOLVED",
        "channel": Channel.IN_APP.value,
        "name": "Sự cố của bạn đã được xử lý",
        "subject": "Sự cố {{ ticket_no }} đã được xử lý xong",
        "body": (
            "Sự cố \"{{ title }}\" tại phòng {{ room_number }} đã được xử lý xong.\n"
            "{% if resolution %}Ghi chú: {{ resolution }}\n{% endif %}"
            "\nNếu vẫn còn vấn đề, bạn báo lại trong mục Sự cố. Bạn có thể đánh giá "
            "việc xử lý ngay trong phiếu.\n"
        ),
        "description": "Gửi cho người thuê đã báo sự cố khi phiếu được xử lý xong (event incident.resolved).",
    },
    {
        "code": "ROOM_STATUS_CHANGED",
        "channel": Channel.IN_APP.value,
        "name": "Phòng đổi trạng thái",
        "subject": None,
        "body": (
            "Phòng {{ room_number }} chuyển từ {{ from_status }} sang {{ to_status }}"
            "{% if reason %} — {{ reason }}{% endif %}\n"
        ),
        "description": "Nhật ký thay đổi trạng thái phòng (event room.status_changed).",
    },
    {
        "code": "MANUAL_NOTICE",
        "channel": Channel.IN_APP.value,
        "name": "Thông báo thủ công",
        "subject": None,
        "body": "{{ title }}\n\n{{ detail }}\n",
        "description": "Khuôn mẫu dùng chung cho thông báo gửi tay từ giao diện quản trị.",
    },
    {
        "code": "INCIDENT_URGENT_SMS",
        "channel": Channel.SMS.value,
        "name": "SMS báo sự cố nghiêm trọng (tắt mặc định)",
        "subject": None,
        "body": (
            "KHAN HIEM {{ property_name }}: phong {{ room_number }} co su co "
            "{{ title }}. Vui long lien he quan ly de xu ly gap."
        ),
        "description": (
            "Khuôn mẫu SMS dự phòng, mặc định is_active=false vì kênh SMS chưa được "
            "nối cổng. Bật sau khi cấu hình xong."
        ),
        "is_active": False,
    },
]

#: Các routing key service khác phát — khai báo 1 chỗ để dễ đối chiếu với docs/02.
SUBSCRIBED_EVENTS: list[str] = [
    "invoice.issued",
    "invoice.overdue",
    "payment.received",
    "contract.activated",
    "contract.expiring",
    "contract.expired",
    "incident.created",
    "incident.escalated",
    "incident.urgent",
    "incident.resolved",
    "room.status_changed",
]

#: Khuôn mẫu VIẾT CHO NGƯỜI THUÊ — chỉ những thư này hiện trong hộp thư /mine.
#: ⭐ Nhiều thư cho quản lý cũng mang tenant_id (để liên kết hồ sơ), ví dụ
#:    PAYMENT_RECEIVED "người thuê X vừa trả…" hay CONTRACT_EXPIRED "nhớ kiểm tra
#:    tiền cọc". Lọc theo tenant_id thôi thì người thuê đọc được thư nội bộ.
TENANT_FACING_TEMPLATES: frozenset[str] = frozenset({
    "INVOICE_ISSUED", "INVOICE_OVERDUE", "CONTRACT_EXPIRING", "INCIDENT_RESOLVED",
})


# =================================================================================================
#  CONSUMER
# =================================================================================================
# ⚠️  `_setup_consumer` phải ĐỊNH NGHĨA TRƯỚC dòng `create_service_app` bên dưới vì nó
#     được truyền vào làm tham số (đánh giá ngay lúc gọi). Bản thân `_handle_event` chỉ
#     được *gọi* khi có event tới, tức là sau khi module đã nạp xong.
async def _setup_consumer(app_instance: FastAPI) -> None:
    """Đăng ký consumer + nạp khuôn mẫu + bật job gửi nền."""
    global _REDIS

    _REDIS = getattr(app_instance.state, "redis", None)
    await _seed_templates()

    consumer = IdempotentConsumer(
        handler=_handle_event,
        consumer_name="notification-service:domain-events",
    )
    app_instance.state.ctx.consumers.append(consumer)
    try:
        await get_event_bus().subscribe(
            "qlpt.notify.events", consumer.handle, SUBSCRIBED_EVENTS,
        )
    except Exception as exc:
        # Không có broker vẫn phải chạy được API gửi tay — chỉ mất thông báo tự động.
        logger.warning("Không đăng ký consumer được: %s", exc)

    if settings.run_scheduler:
        _install_dispatcher(app_instance)
    else:
        logger.info("⏸ RUN_SCHEDULER=false — không bật job gửi nền "
                    "(thông báo vẫn được ghi vào hàng đợi QUEUED)")


async def _seed_templates() -> None:
    """
    Nạp khuôn mẫu mặc định vào bảng `templates` lúc khởi động.

    ⭐ Không seed được KHÔNG được làm container chết: các API khác vẫn chạy được,
       chỉ là chưa có khuôn mẫu để gửi. Ghi log ở mức ERROR để thấy ngay.
    """
    try:
        async with session_scope() as session:
            await session.execute(
                pg_insert(Template).values(DEFAULT_TEMPLATES).on_conflict_do_nothing()
            )
        active = sum(1 for t in DEFAULT_TEMPLATES if t.get("is_active", True))
        logger.info("📝 Đã nạp %d khuôn mẫu mặc định (%d đang bật)",
                    len(DEFAULT_TEMPLATES), active)
    except Exception as exc:
        logger.error("Không nạp được khuôn mẫu mặc định: %s", exc, exc_info=True)


# =================================================================================================
#  APP
# =================================================================================================
#: ⭐ `enable_scheduler` mặc định của factory chỉ in log mỗi 60 giây — không phải
#:    việc thật. Job gửi thật là `_dispatcher_loop`, do `_install_dispatcher` quản lý.
app = create_service_app(
    name="notification-service",
    description=(
        "**Thông báo đa kênh**\n\n"
        "- Nhận event nghiệp vụ từ billing / contract / room / maintenance\n"
        "- Render theo khuôn mẫu Jinja2 lưu trong DB (sửa câu chữ không cần deploy)\n"
        "- Gửi qua IN_APP / EMAIL / SMS / Zalo (Adapter pattern)\n"
        "- Idempotent theo công thức nghiệp vụ: 1 sự kiện = 1 thông báo\n\n"
        "### Vì sao db_notify chỉ có 2 bảng?\n"
        "Service này **không sao chép** dữ liệu nghiệp vụ. Nó nhận `context: dict`\n"
        "đã chuẩn bị từ event, nên đổi cấu trúc hóa đơn không phải sửa ở đây.\n\n"
        "### Chế độ an toàn\n"
        "`NOTIFICATION_DRY_RUN=true` (mặc định) chỉ ghi log nội dung, không gửi thật."
    ),
    version="1.0.0",
    lifespan_extra=_setup_consumer,
    enable_scheduler=False,
)


# =================================================================================================
#  VÒNG ĐỜI: BỌC LIFESPAN ĐỂ TẮT JOB NỀN ĐÚNG CÁCH
# =================================================================================================
# `lifespan_extra` của factory được AWAIT đúng 1 lần lúc khởi động → không có chỗ để
# đăng ký cleanup. Mà `app.add_event_handler("shutdown", ...)` thì VÔ DÙNG khi app đã
# có `lifespan` riêng: Starlette chỉ chạy `on_shutdown` trong `_DefaultLifespan`, tức
# là chỉ khi KHÔNG truyền `lifespan` cho FastAPI.
#
# → Cách đúng: bọc `app.router.lifespan_context` (đây chính là thuộc tính công khai
#   của Starlette mà các thư viện middleware dùng để thêm cleanup). Nhờ vậy job nền
#   được cancel và await TRƯỚC khi factory đóng event bus và dispose DB.
#
# ⚠️  Phải chụp lại lifespan gốc NGAY khi tạo app. Nếu `_install_dispatcher` đọc
#    `app.router.lifespan_context` lúc chạy (khởi động) thì nó sẽ nhận về chính
#    wrapper này → lồng vô hạn.
_FACTORY_LIFESPAN = app.router.lifespan_context
_DISPATCH_TASK: asyncio.Task | None = None


def _install_dispatcher(app_instance: FastAPI) -> None:
    global _DISPATCH_TASK

    @asynccontextmanager
    async def _lifespan(inner: FastAPI):
        global _DISPATCH_TASK
        async with _FACTORY_LIFESPAN(inner):
            _DISPATCH_TASK = asyncio.create_task(_dispatcher_loop(inner))
            logger.info("   ✓ Job gửi thông báo nền đã bật (chu kỳ %ss)",
                        settings.notification_dispatch_interval)
            try:
                yield
            finally:
                task, _DISPATCH_TASK = _DISPATCH_TASK, None
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    logger.info("   ✓ Job gửi thông báo nền đã dừng")

    app_instance.router.lifespan_context = _lifespan


# =================================================================================================
#  HÀNH ĐỘNG CHUNG: GHI THÔNG BÁO VÀO HÀNG ĐỢI
# =================================================================================================
async def _enqueue(
    session: AsyncSession,
    *,
    template_code: str,
    context: dict,
    property_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    recipient: str | None = None,
    recipient_name: str | None = None,
    channel: str | None = None,
    priority: str = Priority.NORMAL.value,
    dedupe_key: str | None = None,
    redis: Any = None,
) -> Notification | None:
    """
    Render khuôn mẫu + ghi 1 dòng `notifications` với trạng thái `QUEUED`.

    Trả về `None` khi KHÔNG THỂ gửi (thiếu khuôn mẫu, thiếu người nhận) — và đây là
    quyết định cố ý: consumer KHÔNG được ném exception vì một thông báo lỗi. Nếu ném,
    RabbitMQ đẩy message vào DLQ và cả chuỗi event liên quan bị kẹt. Một email gửi
    hỏng là chuyện bình thường, không phải lỗi hệ thống.

    ⭐ Render lỗi → vẫn ghi 1 dòng `FAILED`. Bỏ qua im lặng sẽ khiến người vận
    hành tưởng rằng không có thông báo nào được tạo, trong khi thực ra template
    đang hỏng — lỗi im lặng là loại lỗi đắt nhất.
    """
    template = (await session.execute(
        select(Template).where(
            Template.code == template_code, Template.is_active.is_(True),
        )
    )).scalar_one_or_none()

    if template is None:
        logger.error(
            "Không có khuôn mẫu '%s' đang bật — bỏ qua. Các mã có sẵn: %s",
            template_code, ", ".join(t["code"] for t in DEFAULT_TEMPLATES),
        )
        return None

    target_channel = channel or template.channel

    # ---- Tìm người nhận ----
    target = recipient or _recipient_from_context(target_channel, context)
    if not target and target_channel != Channel.IN_APP.value:
        target = await _lookup_contact(
            _REDIS if redis is None else redis, target_channel, tenant_id,
        )
    if not target:
        if target_channel == Channel.IN_APP.value:
            # Kênh trong ứng dụng: ghi định danh HỘP THƯ thay vì email. Có tiền tố
            # để cột `recipient` không lẫn UUID người thuê với UUID cơ sở (trước
            # đây cùng là chuỗi UUID trơn, không phân biệt được ai là người nhận).
            target = (f"tenant:{tenant_id}" if tenant_id
                      else f"property:{property_id}" if property_id else "system")
        else:
            logger.warning("Bỏ qua thông báo '%s': không tìm được %s của người thuê %s",
                           template_code, target_channel.lower(), tenant_id)
            return None

    display_name = context.get("tenant_name") or context.get("title") or recipient_name
    values = {**context, "property_name": context.get("property_name") or "Ban quản lý"}

    # ---- Render ----
    subject: str | None = None
    body: str | None = None
    render_error: str | None = None
    try:
        subject = render(template.subject, values) if template.subject else None
        body = render(template.body, values)
    except TemplateError as exc:
        missing = sorted(set(template_variables(template.body)) - set(values))
        render_error = (f"{exc}. Biến chưa có trong context: "
                        f"{', '.join(missing) or '(không rõ)'}")
        logger.error("❌ Render lỗi template '%s': %s", template_code, render_error)

    stmt = (
        pg_insert(Notification)
        .values(
            property_id=property_id,
            tenant_id=tenant_id,
            channel=target_channel,
            template_code=template_code,
            priority=priority,
            recipient=target[:150],
            recipient_name=str(display_name)[:150] if display_name else None,
            subject=subject[:255] if subject else None,
            body=body,
            status=(NotificationStatus.FAILED.value if render_error
                    else NotificationStatus.QUEUED.value),
            attempts=0,
            error=render_error,
            context=values,
            dedupe_key=dedupe_key,
        )
        # Không chỉ định đích conflict: UNIQUE(dedupe_key) là hàng rào ta cần, và
        # `DO NOTHING` cho mọi ràng buộc là đúng ý ở đây.
        .on_conflict_do_nothing()
        .returning(Notification)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()

    if row is None:
        logger.info("⏭ Bỏ qua thông báo trùng '%s' (%s)", template_code, dedupe_key)
        return None

    if not render_error:
        logger.info("📥 Đã xếp hàng %s → %s [%s] (mã %s, ưu tiên %s)",
                    template_code, target, target_channel,
                    dedupe_key or "thủ công", priority)
    return row


def _recipient_from_context(channel: str, context: dict) -> str | None:
    """Lấy người nhận ngay trong `context` nếu event đã mang sẵn (VD contract.expiring)."""
    if channel == Channel.EMAIL.value:
        return context.get("tenant_email") or context.get("email")
    if channel in (Channel.SMS.value, Channel.ZALO.value):
        return context.get("tenant_phone") or context.get("phone")
    return None


async def _lookup_contact(redis: Any, channel: str, tenant_id: uuid.UUID | None) -> str | None:
    """
    Hỏi tenant-service lấy email/SĐT khi event không mang sẵn.

    ⭐ Vì sao gọi HTTP mà không bắt buộc mọi event phải gửi kèm thông tin liên hệ?
        `invoice.issued` có tới 200 bản ghi/tháng. Nếu bắt billing phải join sang
        db_tenant để đính kèm email thì billing-service phụ thuộc vào dữ liệu của
        tenant-service — đúng thứ mà kiến trúc database-per-service cấm. Chỉ 1 chỗ
        duy nhất (đây) cần liên hệ, có cache 1 giờ, và nếu tenant-service chết thì
        thông báo rơi về kênh IN_APP chứ không mất.
    """
    if tenant_id is None:
        return None

    cache_key = f"notify:contact:{tenant_id}"
    profile: dict | None = None
    if redis is not None:
        try:
            raw = await redis.get(cache_key)
            if raw:
                profile = json.loads(raw)
        except Exception as exc:
            logger.warning("Redis GET contact lỗi: %s", exc)

    if profile is None:
        try:
            profile = await get_http_client("tenant").get(
                f"/internal/v1/tenants/{tenant_id}"
            )
        except Exception as exc:
            logger.warning("Không lấy được hồ sơ người thuê %s: %s", tenant_id, exc)
            return None
        if profile and redis is not None:
            with suppress(Exception):
                await redis.setex(cache_key, CACHE_TTL_CONTACT, json.dumps(profile))

    if not profile:
        return None
    if channel == Channel.EMAIL.value:
        return profile.get("email")
    if channel in (Channel.SMS.value, Channel.ZALO.value):
        return profile.get("phone")
    return None


# =================================================================================================
#  ĐỊNH DẠNG
# =================================================================================================
def _vnd(value: Any) -> str:
    """Định dạng tiền kiểu Việt Nam cho nội dung thông báo.

    ⭐ Nhận `str`/int/Decimal và ép qua `str` — KHÔNG dùng `Decimal(float)` vì số thực
    nhị phân không biểu diễn chính xác 0.1, và `float` không xuất hiện ở đây là cố ý.
    """
    return f"{Decimal(str(value or 0)):,.0f}đ"


def _day(value: Any) -> str:
    """Định dạng ngày kiểu Việt Nam; chấp nhận cả chuỗi ISO lẫn `date`/`datetime`."""
    if not value:
        return "—"
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def _month(value: Any) -> str:
    """Định dạng kỳ hóa đơn `2026-10-01` → `10/2026`."""
    if not value:
        return "—"
    try:
        parsed = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{parsed:%m/%Y}"


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Ép sang UUID nếu được, không thì `None` — event có thể thiếu trường này."""
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, AttributeError, TypeError):
        return None


# =================================================================================================
#  ROUTER: KHUÔN MẪU
# =================================================================================================
template_router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


@template_router.get("", response_model=list[TemplateResponse],
                     summary="Danh sách khuôn mẫu")
async def list_templates(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    channel: str | None = Query(None, description="Lọc theo kênh"),
    active_only: bool = Query(False, description="Chỉ lấy khuôn mẫu đang bật"),
) -> list[TemplateResponse]:
    """
    ⭐ Mọi khuôn mẫu là GLOBAL, không theo `property_id`.

    Đây là quyết định có chủ đích: nhà trọ nào cũng gửi "Hóa đơn tháng này đã phát
    hành", chỉ khác câu chữ. Nếu tách theo cơ sở thì mỗi cơ sở phải tự viết lại 11
    template, và sửa 1 lỗi câu chữ thành 11 lần. Ai cần khác biệt thì dùng trường
    `locale` (đã có sẵn trong bảng, dành cho đa ngôn ngữ sau này).
    """
    _ = user
    stmt = select(Template)
    if channel:
        stmt = stmt.where(Template.channel == channel)
    if active_only:
        stmt = stmt.where(Template.is_active.is_(True))
    rows = (await session.execute(stmt.order_by(Template.code))).scalars().all()
    return [TemplateResponse.model_validate(t) for t in rows]


@template_router.put("/{code}", response_model=TemplateResponse,
                     summary="Tạo hoặc sửa khuôn mẫu")
async def upsert_template(
    code: str,
    payload: TemplateUpsert,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TemplateResponse:
    """
    Upsert theo khoá chính `code`.

    ⭐ Kiểm tra biến NGAY tại đây, trước khi lưu. Sửa template sai biến rồi mới
    phát hiện lúc gửi cho cả trăm người thuê là cách tự tạo sự cố lớn nhất của
    hệ thống thông báo. Chặn ở tầng API thì chi phí là 1 request; để lọt thì không
    thu hồi được.
    """
    if payload.channel not in CHANNELS:
        raise BusinessRuleError(
            f"Kênh '{payload.channel}' chưa được hỗ trợ. "
            f"Các kênh hợp lệ: {', '.join(sorted(CHANNELS))}.",
        )

    required = set(template_variables(payload.body))
    if payload.subject:
        required |= set(template_variables(payload.subject))
    unknown = sorted(required - set(SAMPLE_CONTEXT))
    if unknown:
        raise BusinessRuleError(
            f"Template tham chiếu biến chưa có trong context của hệ thống: "
            f"{', '.join(unknown)}. Thông báo sẽ không bao giờ render được. "
            f"Các biến hệ thống luôn có: {', '.join(sorted(SAMPLE_CONTEXT))}.",
            details={"unknown_variables": unknown,
                     "known_variables": sorted(SAMPLE_CONTEXT)},
        )

    stmt = (
        pg_insert(Template)
        .values(
            code=code, channel=payload.channel, name=payload.name,
            subject=payload.subject, body=payload.body,
            description=payload.description, is_active=payload.is_active,
        )
        .on_conflict_do_update(
            index_elements=[Template.code],
            set_={
                "channel": payload.channel,
                "name": payload.name,
                "subject": payload.subject,
                "body": payload.body,
                "description": payload.description,
                "is_active": payload.is_active,
            },
        )
        .returning(Template)
    )
    template = (await session.execute(stmt)).scalar_one()

    logger.info("📝 %s đã lưu khuôn mẫu %s (kênh %s, biến: %s)",
                user.username, code, payload.channel, ", ".join(sorted(required)))
    return TemplateResponse.model_validate(template)


@template_router.post("/{code}/preview", response_model=TemplatePreviewResponse,
                     summary="👀 Xem trước nội dung khuôn mẫu")
async def preview_template(
    code: str,
    payload: TemplatePreviewRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TemplatePreviewResponse:
    """Render thử với dữ liệu giả — KHÔNG gửi, KHÔNG ghi DB. Dùng ngay sau khi sửa."""
    _ = user
    template = await _get_template_or_404(session, code)
    values = {**SAMPLE_CONTEXT, **payload.context}

    missing = sorted(set(template_variables(template.body)) - set(values))
    if missing:
        raise BusinessRuleError(
            f"Dữ liệu preview thiếu biến: {', '.join(missing)}. "
            "Thêm các biến này vào trường `context`.",
            details={"missing": missing},
        )

    return TemplatePreviewResponse(
        subject=render(template.subject, values) if template.subject else None,
        body=render(template.body, values),
        used_variables=_used_variables(template),
    )


# =================================================================================================
#  ROUTER: THÔNG BÁO
# =================================================================================================
notification_router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@notification_router.get("", summary="Danh sách thông báo")
async def list_notifications(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    property_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    notification_status: str | None = Query(None, alias="status"),
    channel: str | None = None,
    priority: str | None = None,
    unread_only: bool = Query(False, description="Chỉ thông báo chưa đọc"),
    since: datetime | None = Query(None, description="Từ thời điểm này"),
    sort: str = Query("queued_desc", description="queued|created|priority|status"),
) -> dict:
    """
    ⚠️ Endpoint này CHỈ dành cho ADMIN/MANAGER. Người thuê dùng `GET /mine`
    (lọc theo claim `tenant_id` trong JWT — không cần sao chép user_id vào db_notify).
    """
    effective = _resolve_property(user, property_id)

    stmt = select(Notification)
    if effective:
        stmt = stmt.where(Notification.property_id == effective)
    if tenant_id:
        stmt = stmt.where(Notification.tenant_id == tenant_id)
    if notification_status:
        stmt = stmt.where(Notification.status == notification_status)
    if channel:
        stmt = stmt.where(Notification.channel == channel)
    if priority:
        stmt = stmt.where(Notification.priority == priority)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if since:
        stmt = stmt.where(Notification.created_at >= since)

    stmt = apply_sort(
        stmt, Notification, sort,
        allowed={"queued": "queued_at", "created": "created_at",
                 "priority": "priority", "status": "status"},
        default="queued_at",
    )

    items, meta = await paginate(session, stmt, params)
    return {
        "items": [NotificationListItem.model_validate(n) for n in items],
        "meta": meta.model_dump(),
    }


@notification_router.get("/stats", response_model=NotificationStats,
                         summary="📊 Thống kê tỉ lệ gửi thành công")
async def notification_stats(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> NotificationStats:
    """
    Tỉ lệ gửi thành công là CHỈ SỐ SỐNG CÒN của hệ thống thông báo.

    Nếu nó tụt dần mà không ai để ý, thì đến lúc SMTP hết hạn tài khoản thì toàn bộ
    người thuê đều không nhận được hóa đơn — mà họ vẫn bị tính tiền như thường. Vì
    vậy trường này được đưa lên dashboard của report-service để có cảnh báo.
    """
    effective = _resolve_property(user, property_id)

    def _scope(stmt):
        return stmt.where(Notification.property_id == effective) if effective else stmt

    by_status = {s.value: 0 for s in NotificationStatus}
    for status_name, count in (await session.execute(
        _scope(select(Notification.status, func.count(Notification.id))
               .group_by(Notification.status))
    )).all():
        by_status[status_name] = count

    by_channel: dict[str, int] = {}
    for channel_name, count in (await session.execute(
        _scope(select(Notification.channel, func.count(Notification.id))
               .group_by(Notification.channel))
    )).all():
        by_channel[channel_name] = count

    unread = (await session.execute(
        _scope(select(func.count(Notification.id))
               .where(Notification.read_at.is_(None)))
    )).scalar() or 0

    total = sum(by_status.values())
    # "Đã thử gửi" = mọi thông báo trừ những cái vẫn còn nằm trong hàng đợi.
    attempted = total - by_status.get(NotificationStatus.QUEUED.value, 0)
    succeeded = (by_status.get(NotificationStatus.SENT.value, 0)
                 + by_status.get(NotificationStatus.DELIVERED.value, 0)
                 + by_status.get(NotificationStatus.READ.value, 0))

    return NotificationStats(
        total=total,
        by_status=by_status,
        by_channel=by_channel,
        unread=unread,
        success_rate=round(succeeded / attempted * 100, 2) if attempted else 100.0,
        failed=by_status.get(NotificationStatus.FAILED.value, 0),
    )


@notification_router.get("/unread-count", summary="Số thông báo chưa đọc")
async def unread_count(
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
    property_id: uuid.UUID | None = None,
) -> dict:
    """Endpoint nhẹ cho badge trên thanh điều hướng — UI gọi mỗi 30 giây."""
    effective = _resolve_property(user, property_id)
    stmt = select(func.count(Notification.id)).where(Notification.read_at.is_(None))
    if effective:
        stmt = stmt.where(Notification.property_id == effective)
    return {"unread": (await session.execute(stmt)).scalar() or 0}


@notification_router.post("/preview", response_model=TemplatePreviewResponse,
                          summary="👀 Xem trước nội dung sẽ gửi")
async def preview_send(
    payload: NotificationSendRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TemplatePreviewResponse:
    """
    Render thử chính nội dung sẽ gửi cho MỘT người nhận — không ghi DB, không gửi.

    Khác `POST /api/v1/templates/{code}/preview` ở chỗ đây lấy `context` từ payload
    THẬT (số tiền, mã hóa đơn) thay vì dữ liệu giả, nên dùng để kiểm tra trước khi
    bấm "Gửi cho 200 người".
    """
    _ = user
    template = await _get_template_or_404(session, payload.template_code)
    values = {**SAMPLE_CONTEXT, **payload.context}

    missing = sorted(set(template_variables(template.body)) - set(values))
    if missing:
        raise BusinessRuleError(
            f"Thiếu biến trong context: {', '.join(missing)}.", details={"missing": missing},
        )

    return TemplatePreviewResponse(
        subject=render(template.subject, values) if template.subject else None,
        body=render(template.body, values),
        used_variables=_used_variables(template),
    )


@notification_router.post("/send", response_model=NotificationResponse,
                          status_code=status.HTTP_202_ACCEPTED,
                          summary="✉️ Gửi thông báo thủ công")
async def send_notification(
    request: Request,
    payload: NotificationSendRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationResponse:
    """
    Tạo 1 thông báo và xếp vào hàng đợi (202 Accepted).

    ⭐ `202` chứ không phải `201` vì thông báo CHƯA được gửi — nó đang chờ job nền.
    Trả 201 khiến người dùng tưởng "đã gửi xong" rồi đóng laptop, trong khi SMTP có
    thể đang lỗi. 202 nói đúng sự thật: đã nhận việc.
    """
    notification = await _enqueue(
        session,
        template_code=payload.template_code,
        context=payload.context,
        recipient=payload.recipient,
        recipient_name=payload.recipient_name,
        channel=payload.channel,
        priority=payload.priority,
        dedupe_key=None if payload.force else _manual_dedupe_key(payload),
        redis=getattr(request.app.state, "redis", None),
    )
    if notification is None:
        raise ConflictError(
            f"Không tạo được thông báo từ khuôn mẫu '{payload.template_code}'. "
            "Kiểm tra khuôn mẫu có tồn tại và đang bật không.",
        )
    record_business_event(settings.service_name, "notification.queued")
    return NotificationResponse.model_validate(notification)


@notification_router.get("/mine", response_model=list[NotificationResponse],
                         summary="🔔 Hộp thông báo của tôi (người thuê)")
async def list_my_notifications(
    user: Annotated[CurrentUser, Depends(require_roles(Role.TENANT))],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(30, ge=1, le=100),
) -> list[NotificationResponse]:
    """
    Hộp thư của người thuê đang đăng nhập — chỉ thư viết cho người thuê
    (`TENANT_FACING_TEMPLATES`), mọi kênh, mới nhất trước.

    ⭐ Trước đây cố ý chưa có API này: db_notify không biết tài khoản nào ứng với
       hồ sơ người thuê nào. Nay JWT mang claim `tenant_id` (auth-service lấy từ
       users.tenant_id) nên lọc được mà KHÔNG phải sao chép user_id vào db_notify.
       Không nhận tenant_id từ query — đổi tham số là đọc được thư người khác.
       Đặt TRƯỚC route `/{notification_id}` để "mine" không bị hiểu là UUID.
    """
    if user.tenant_id is None:
        return []
    rows = (await session.execute(
        select(Notification)
        .where(Notification.tenant_id == user.tenant_id,
               Notification.template_code.in_(TENANT_FACING_TEMPLATES))
        .order_by(Notification.queued_at.desc())
        .limit(limit)
    )).scalars().all()
    return [NotificationResponse.model_validate(n) for n in rows]


@notification_router.post("/mine/{notification_id}/read", response_model=NotificationResponse,
                          summary="✓ Người thuê đánh dấu đã đọc")
async def mark_my_read(
    notification_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.TENANT))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationResponse:
    notification = await _get_notification_or_404(session, notification_id)
    # Thư của người khác → 404 (không phải 403): không xác nhận là id đó có tồn tại.
    if (user.tenant_id is None or notification.tenant_id != user.tenant_id
            or notification.template_code not in TENANT_FACING_TEMPLATES):
        raise NotFoundError("Không tìm thấy thông báo")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        if notification.status in (NotificationStatus.SENT.value,
                                   NotificationStatus.DELIVERED.value):
            notification.status = NotificationStatus.READ.value
        await session.flush()
    return NotificationResponse.model_validate(notification)


@notification_router.get("/{notification_id}", response_model=NotificationResponse,
                         summary="Chi tiết thông báo")
async def get_notification(
    notification_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationResponse:
    notification = await _get_notification_or_404(session, notification_id)
    user.assert_property_access(notification.property_id)
    return NotificationResponse.model_validate(notification)


@notification_router.post("/{notification_id}/read", response_model=NotificationResponse,
                          summary="✓ Đánh dấu đã đọc")
async def mark_read(
    notification_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationResponse:
    notification = await _get_notification_or_404(session, notification_id)
    user.assert_property_access(notification.property_id)

    if notification.read_at is not None:
        return NotificationResponse.model_validate(notification)      # idempotent

    notification.read_at = datetime.now(UTC)
    if notification.status in (NotificationStatus.SENT.value,
                               NotificationStatus.DELIVERED.value):
        notification.status = NotificationStatus.READ.value
    await session.flush()
    return NotificationResponse.model_validate(notification)


@notification_router.post("/{notification_id}/retry", response_model=NotificationResponse,
                          summary="🔁 Thử gửi lại")
async def retry_notification(
    notification_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationResponse:
    """
    Đưa thông báo `FAILED` về hàng đợi để job nền thử gửi lại.

    Dùng khi nguyên nhân lỗi đã được xử lý (cấu hình lại SMTP, khách sửa lại địa chỉ
    email). Cố ý KHÔNG cho thử lại thông báo đã gửi thành công — bấm 2 lần là khách
    nhận 2 bản, và người dùng sẽ quy cho hệ thống lỗi.
    """
    notification = await _get_notification_or_404(session, notification_id)
    user.assert_property_access(notification.property_id)

    if notification.status != NotificationStatus.FAILED.value:
        detail = "" if notification.error is None else f" Lỗi gần nhất: {notification.error}"
        raise BusinessRuleError(
            f"Chỉ thử gửi lại được thông báo đang lỗi. Thông báo này đang ở trạng "
            f"thái {notification.status}.{detail}",
        )

    notification.status = NotificationStatus.QUEUED.value
    notification.attempts = 0
    notification.error = None
    notification.sent_at = None
    await session.flush()

    logger.info("🔁 %s yêu cầu thử gửi lại thông báo %s (template %s)",
                user.username, notification_id, notification.template_code)
    return NotificationResponse.model_validate(notification)


@notification_router.post("/bulk", response_model=BulkSendResponse,
                          status_code=status.HTTP_202_ACCEPTED,
                          summary="📣 Gửi 1 thông báo cho nhiều người")
async def bulk_send(
    request: Request,
    payload: BulkSendRequest,
    user: Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.MANAGER))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BulkSendResponse:
    """
    Thông báo diện rộng: tăng giá, đổi nội quy, mất điện khu vực...

    ⭐ Vì sao bỏ qua lỗi từng người thay vì rollback cả lô?
        Nếu 1 trong 200 người có email sai mà cả lô rollback thì 199 người hợp lệ
        cũng không nhận được thông báo tăng giá. Gửi được 199 và báo lại 1 lỗi thì
        tốt hơn hẳn — người quản lý sửa riêng người thứ 200 bằng
        `POST /{id}/retry` hoặc gửi tay.
    """
    property_id = _resolve_property(user, None)
    errors: list[str] = []
    queued = skipped = 0

    for index, item in enumerate(payload.recipients):
        try:
            notification = await _enqueue(
                session,
                template_code=item.template_code or payload.template_code,
                context={**payload.context, **item.context},
                property_id=property_id,
                tenant_id=item.tenant_id,
                recipient=item.recipient,
                recipient_name=item.recipient_name,
                channel=item.channel or payload.channel,
                priority=item.priority,
                # Lô gửi TAY thì không khoá dedupe theo sự kiện — gửi 2 lần cùng
                # nội dung là chủ ý của người quản lý, nên `dedupe_key=None`.
                dedupe_key=None,
                redis=getattr(request.app.state, "redis", None),
            )
            if notification is None:
                skipped += 1
            else:
                queued += 1
        except Exception as exc:
            skipped += 1
            errors.append(f"[{index}] {item.recipient}: {type(exc).__name__}: {exc}")

    logger.info("📣 %s gửi hàng loạt '%s': %d thành công, %d lỗi",
                user.username, payload.template_code, queued, skipped)
    return BulkSendResponse(total=len(payload.recipients), queued=queued,
                            skipped=skipped, errors=errors)


# =================================================================================================
#  INTERNAL API — service khác gọi được
# =================================================================================================
internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


@internal_router.post("/notifications/broadcast",
                     summary="[Nội bộ] Gửi thông báo tới một người thuê")
async def internal_broadcast(
    payload: NotificationSendRequest,
    _: Annotated[CurrentUser, Depends(require_roles(Role.SYSTEM))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    maintenance-service gọi endpoint này khi có sự cố nghiêm trọng cần báo gấp.

    ⭐ Cố ý KHÔNG gọi `assert_property_access`: token SYSTEM không mang
       `property_id` của người dùng nên hàm đó sẽ ném 403 oan. Ranh giới tin cậy
       được vẽ ở tầng mạng (Docker network nội bộ, không có đường ra Internet) và
       ở vai trò SYSTEM — không phải bằng cách kiểm tra quyền hụt hiệu.
    """
    notification = await _enqueue(
        session,
        template_code=payload.template_code,
        context=payload.context,
        tenant_id=payload.tenant_id,
        recipient=payload.recipient,
        recipient_name=payload.recipient_name,
        channel=payload.channel,
        priority=payload.priority,
        dedupe_key=_manual_dedupe_key(payload),
    )
    return {
        "queued": notification is not None,
        "id": str(notification.id) if notification else None,
        "status": notification.status if notification else "SKIPPED",
    }


# =================================================================================================
#  JOB NỀN: DRAIN HÀNG ĐỢI
# =================================================================================================
#: Thứ tự ưu tiên dùng ngay trong SQL (thay vì lấy ra rồi sắp xếp bằng Python rồi mới
#: cắt lô — như vậy lấy đúng `DISPATCH_BATCH` bản ghi quan trọng nhất, kể cả khi
#: hàng đợi có hàng nghìn thông báo thường đang chờ).
_PRIORITY_ORDER = case(
    dict(PRIORITY_RANK),
    value=Notification.priority,
)


async def _dispatcher_loop(app_instance: FastAPI) -> None:
    """
    Vòng lặp nền: lấy thông báo `QUEUED` và gửi theo thứ tự ưu tiên.

    ⭐ Vì sao có khoá phân tán?
        Khi chạy 2 replica (sau khi scale), cả hai sẽ thấy cùng 20 dòng `QUEUED` và
        gửi trùng cho khách. `SET NX` trên Redis đảm bảo chỉ 1 tiến trình gửi mỗi
        lượt. Ràng buộc `with_for_update(skip_locked=True)` ở tầng DB là lớp thứ
        hai, phòng trường hợp Redis không sẵn sàng.
    """
    lock_name = "notification-dispatch"
    owner = f"{settings.service_name}:{uuid.uuid4().hex[:8]}"

    while True:
        try:
            redis = getattr(app_instance.state, "redis", None)
            locked = await acquire_lock(redis, lock_name, owner, ttl=LOCK_TTL_DISPATCH)
            try:
                sent = await _dispatch_batch(redis)
                if sent:
                    set_business_gauge(settings.service_name, "notifications_dispatched", sent)
            finally:
                if locked:
                    await release_lock(redis, lock_name, owner)
        except asyncio.CancelledError:
            raise
        except Exception:
            # ⭐ KHÔNG để một lỗi giết vòng lặp. Nếu task chết, hàng đợi tích tụ tới
            #    hàng nghìn thông báo rồi đổ 1 lần khi khởi động lại.
            logger.exception("Lỗi vòng lặp gửi thông báo — thử lại ở lượt sau")

        await asyncio.sleep(settings.notification_dispatch_interval)


async def _dispatch_batch(redis: Any) -> int:
    """
    Gửi 1 lô thông báo đang chờ. Trả về số thông báo gửi thành công.

    ⚠️  Giữ khoá dòng (`FOR UPDATE SKIP LOCKED`) trong lúc gọi mạng — nghe thì
        lạ nhưng đây là mẫu "claim" chuẩn: đổi lại, khi container bị OOM-kill giữa
        chừng thì dòng vẫn là `QUEUED` và lượt sau gửi lại, KHÔNG có trạng thái
        "đang gửi" bị bỏ rơi. Với 1 tiến trình và lô 20 bản ghi thì thời gian giữ
        khoá là vài giây — không đáng để đánh đổi.
    """
    sent = 0
    async with session_scope() as session:
        stmt = (
            select(Notification)
            .where(Notification.status == NotificationStatus.QUEUED.value)
            .order_by(_PRIORITY_ORDER, Notification.queued_at)
            .limit(DISPATCH_BATCH)
            .with_for_update(skip_locked=True)
        )
        rows = (await session.execute(stmt)).scalars().all()

        for notification in rows:
            adapter = get_channel(notification.channel)

            # Chặn sớm lỗi định dạng (email sai, SĐT sai) — để adapter không phải
            # vừa gọi nhà cung cấp vừa mới biết là sai, vừa mất tiền nếu tính phí.
            problem = adapter.precheck(notification.recipient)
            if problem:
                notification.status = NotificationStatus.FAILED.value
                notification.error = problem
                notification.attempts += 1
                logger.warning("❌ %s: %s", notification.recipient, problem)
                continue

            result = await adapter.send(
                notification.recipient, notification.subject,
                notification.body, notification.context,
            )
            notification.attempts += 1
            notification.provider_message = (
                result.provider_message[:255] if result.provider_message else None
            )

            if result.ok:
                notification.status = NotificationStatus.SENT.value
                notification.sent_at = datetime.now(UTC)
                notification.error = None
                sent += 1
                logger.info("📤 Đã gửi %s → %s [%s] (lần %d)",
                            notification.template_code, notification.recipient,
                            notification.channel, notification.attempts)
            else:
                notification.error = result.provider_message
                # Chỉ thử lại khi lỗi THOÁNG QUA. Sai địa chỉ email hay chưa cấu
                # hình SMTP thì thử 100 lần cũng thất bại, chỉ tốn thời gian.
                if result.retryable and notification.attempts < settings.notification_max_attempts:
                    logger.warning("⚠ Gửi lỗi (sẽ thử lại %d/%d): %s",
                                   notification.attempts,
                                   settings.notification_max_attempts,
                                   result.provider_message)
                else:
                    notification.status = NotificationStatus.FAILED.value
                    logger.error("❌ Gửi thất bại %s: %s",
                                 notification.recipient, result.provider_message)
    return sent


# =================================================================================================
#  CONSUMER — BIẾN EVENT THÀNH THÔNG BÁO
# =================================================================================================
async def _handle_event(event: DomainEvent) -> None:
    """
    Điểm vào duy nhất của consumer. Dispatch bằng dict để thêm/sửa handler chỉ đụng
    1 chỗ.

    ⭐ RabbitMQ bảo đảm at-least-once: cùng 1 event có thể tới 2 lần.
       `IdempotentConsumer` chặn trùng theo `event_id`; tầng còn lại là
       `dedupe_key` tính theo công thức nghiệp vụ — chặn được cả trường hợp khó
       hơn là scheduler phát lại cùng một thông báo với `event_id` khác.
    """
    handler = {
        "invoice.issued": _on_invoice_issued,
        "invoice.overdue": _on_invoice_overdue,
        "payment.received": _on_payment_received,
        "contract.activated": _on_contract_activated,
        "contract.expiring": _on_contract_expiring,
        "contract.expired": _on_contract_expired,
        "incident.created": _on_incident_created,
        "incident.urgent": _on_incident_urgent,
        "incident.escalated": _on_incident_urgent,
        "incident.resolved": _on_incident_resolved,
        "room.status_changed": _on_room_status_changed,
    }.get(event.event_type)

    if handler is None:
        logger.debug("Bỏ qua event không quan tâm: %s", event.event_type)
        return

    async with session_scope() as session:
        await handler(session, event)


#: Context dùng chung cho thông báo gửi tới người thuê. Gom vào 1 hàm để không
#: phải lặp 3 khoá ở 5 handler, và để sau này thêm trường (VD số tài khoản) chỉ
#: sửa 1 chỗ.
def _tenant_context(data: dict) -> dict:
    return {
        "tenant_name": data.get("tenant_name") or "Người thuê",
        "tenant_email": data.get("tenant_email"),
        "tenant_phone": data.get("tenant_phone"),
    }


async def _on_invoice_issued(session: AsyncSession, event: DomainEvent) -> None:
    """billing vừa phát hành hóa đơn → gửi chi tiết + tổng tiền cho người thuê."""
    data = event.data
    invoice_no = str(data.get("invoice_no") or "")

    await _enqueue(
        session,
        template_code="INVOICE_ISSUED",
        context={
            **_tenant_context(data),
            "invoice_no": invoice_no,
            "period": _month(data.get("period")),
            "due_date": _day(data.get("due_date")),
            "room_number": data.get("room_number") or "—",
            "total_amount": _vnd(data.get("total_amount")),
            # Các khoản chi tiết KHÔNG có trong event (billing chỉ gửi tổng) → ghi
            # "xem chi tiết" thay vì bịa ra số 0đ. Bịa số tiền trong thông báo là
            # loại lỗi tệ nhất: khách tin một con số, hệ thống ra một con số khác.
            "rent_amount": "xem chi tiết",
            "electric_amount": "xem chi tiết",
            "water_amount": "xem chi tiết",
            "service_amount": "xem chi tiết",
            "late_fee_amount": "0đ",
            "deposit_deducted": "0đ",
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=_uuid_or_none(data.get("tenant_id")),
        channel=Channel.EMAIL.value,
        priority=Priority.NORMAL.value,
        # ⭐ Công thức nghiệp vụ, KHÔNG phải event_id: "hóa đơn này chỉ được
        #    thông báo đúng 1 lần", kể cả khi job tính tiền bị chạy lại.
        dedupe_key=f"INVOICE_ISSUED:{invoice_no}",
    )


async def _on_invoice_overdue(session: AsyncSession, event: DomainEvent) -> None:
    """Hóa đơn quá hạn → nhắc trả. Ưu tiên CAO vì tiền đang bị giữ."""
    data = event.data
    invoice_no = str(data.get("invoice_no") or "")

    await _enqueue(
        session,
        template_code="INVOICE_OVERDUE",
        context={
            **_tenant_context(data),
            "invoice_no": invoice_no,
            "period": _month(data.get("period")),
            "due_date": _day(data.get("due_date")),
            "days_overdue": str(data.get("days_overdue") or 0),
            "outstanding": _vnd(data.get("outstanding") or data.get("total_amount")),
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=_uuid_or_none(data.get("tenant_id")),
        channel=Channel.EMAIL.value,
        priority=Priority.HIGH.value,
        # Nhắc 1 lần cho mỗi mốc trễ (mốc do billing tính), KHÔNG nhắc lặp mỗi
        # ngày — người thuê nhận 30 email trong tháng sẽ chặn cả địa chỉ.
        dedupe_key=f"INVOICE_OVERDUE:{invoice_no}:{data.get('days_overdue')}",
    )


async def _on_payment_received(session: AsyncSession, event: DomainEvent) -> None:
    """Ghi nhận thanh toán → phiếu xác nhận trong ứng dụng."""
    data = event.data
    invoice_no = str(data.get("invoice_no") or "")

    await _enqueue(
        session,
        template_code="PAYMENT_RECEIVED",
        context={
            **_tenant_context(data),
            "invoice_no": invoice_no,
            "amount": _vnd(data.get("amount")),
            "method": _PAYMENT_METHODS.get(str(data.get("method")),
                                           data.get("method") or "—"),
            "room_number": data.get("room_number") or "—",
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=_uuid_or_none(data.get("tenant_id")),
        priority=Priority.LOW.value,
        dedupe_key=f"PAYMENT_RECEIVED:{data.get('payment_id') or invoice_no}",
    )


async def _on_contract_activated(session: AsyncSession, event: DomainEvent) -> None:
    """Hợp đồng có hiệu lực → thông báo nội bộ để quản lý đối chiếu."""
    data = event.data
    contract_no = str(data.get("contract_no") or "")

    await _enqueue(
        session,
        template_code="CONTRACT_ACTIVATED",
        context={
            **_tenant_context(data),
            "contract_no": contract_no,
            "room_number": data.get("room_number") or "—",
            "start_date": _day(data.get("start_date")),
            "end_date": _day(data.get("end_date")),
            "monthly_price": _vnd(data.get("monthly_price")),
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=_uuid_or_none(data.get("tenant_id")),
        priority=Priority.NORMAL.value,
        dedupe_key=f"CONTRACT_ACTIVATED:{contract_no}",
    )


async def _on_contract_expiring(session: AsyncSession, event: DomainEvent) -> None:
    """
    Hợp đồng sắp hết hạn → nhắc gia hạn (cảnh báo quan trọng nhất về tiền).

    contract-service chỉ phát event khi bước đúng mốc T-30/T-7/T-1, nên
    `dedupe_key` ở đây chủ yếu là lưới an toàn — nhưng vẫn cần, vì "người thuê chỉ
    cần biết 1 lần" là nguyên tắc chứ không phải may mắn.
    """
    data = event.data
    contract_no = str(data.get("contract_no") or "")
    days_left = int(data.get("days_left") or 0)

    await _enqueue(
        session,
        template_code="CONTRACT_EXPIRING",
        context={
            **_tenant_context(data),
            "contract_no": contract_no,
            "room_number": data.get("room_number") or "—",
            "end_date": _day(data.get("end_date")),
            "days_left": str(days_left),
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=_uuid_or_none(data.get("tenant_id")),
        channel=Channel.EMAIL.value,
        priority=Priority.HIGH.value if days_left <= 7 else Priority.NORMAL.value,
        dedupe_key=f"CONTRACT_EXPIRING:{contract_no}:{days_left}",
    )


async def _on_contract_expired(session: AsyncSession, event: DomainEvent) -> None:
    """Hợp đồng hết hạn tự nhiên → nhắc quản lý xử lý tiền cọc + hoá đơn cuối."""
    data = event.data
    contract_no = str(data.get("contract_no") or "")

    await _enqueue(
        session,
        template_code="CONTRACT_EXPIRED",
        context={
            **_tenant_context(data),
            "contract_no": contract_no,
            "room_number": data.get("room_number") or "—",
            "end_date": _day(data.get("end_date")),
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=_uuid_or_none(data.get("tenant_id")),
        priority=Priority.NORMAL.value,
        dedupe_key=f"CONTRACT_EXPIRED:{contract_no}",
    )


async def _on_incident_created(session: AsyncSession, event: DomainEvent) -> None:
    """maintenance tạo phiếu sự cố → báo cho quản lý (nội bộ)."""
    data = event.data
    ticket_no = str(data.get("ticket_no") or data.get("incident_no") or "")

    await _enqueue(
        session,
        template_code="INCIDENT_CREATED",
        context={
            "ticket_no": ticket_no,
            "title": data.get("title") or "(không rõ)",
            "category": data.get("category") or "—",
            "priority": data.get("priority") or "NORMAL",
            "reported_by": (data.get("reported_by") or data.get("tenant_name")
                             or "Người thuê"),
            "room_number": data.get("room_number") or "—",
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=_uuid_or_none(data.get("tenant_id")),
        priority=(Priority.CRITICAL.value if data.get("priority") == "URGENT"
                  else Priority.NORMAL.value),
        dedupe_key=f"INCIDENT_CREATED:{ticket_no}",
    )


async def _on_incident_urgent(session: AsyncSession, event: DomainEvent) -> None:
    """
    Sự cố nghiêm trọng (rò rỉ, cháy, mất điện) → báo NGAY cho quản lý.

    Ưu tiên `CRITICAL` để dispatcher gửi trước hàng chục thông báo thường đang xếp
    hàng. Với kênh IN_APP thì "gửi trước" ít ý nghĩa, nhưng khi bật kênh email/SMS
    thì đây chính là lý do phải có thứ tự ưu tiên ngay từ đầu.
    """
    data = event.data
    ticket_no = str(data.get("ticket_no") or data.get("incident_no") or "")

    await _enqueue(
        session,
        template_code="INCIDENT_URGENT",
        context={
            "ticket_no": ticket_no,
            "title": data.get("title") or "(không rõ)",
            "reported_by": (data.get("reported_by") or data.get("tenant_name")
                             or "Người thuê"),
            "reported_at": _day(data.get("reported_at")),
            "room_number": data.get("room_number") or "—",
            "tenant_name": data.get("tenant_name") or "Người thuê",
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=_uuid_or_none(data.get("tenant_id")),
        priority=Priority.CRITICAL.value,
        dedupe_key=f"{event.event_type.upper()}:{ticket_no}",
    )


async def _on_incident_resolved(session: AsyncSession, event: DomainEvent) -> None:
    """Phiếu sự cố xử lý xong → báo người thuê đã báo phiếu đó (nếu người báo là người thuê)."""
    data = event.data
    tenant_id = _uuid_or_none(data.get("tenant_id"))
    if tenant_id is None:
        return          # quản lý tự ghi phiếu / bảo trì định kỳ — không có người thuê để báo
    # Bỏ các dòng nội bộ ("[Đã kiểm tra an toàn] admin (uuid)", "[Giao việc] …"):
    # người thuê chỉ cần biết kết quả, không cần id tài khoản nhân viên.
    resolution = "\n".join(line for line in str(data.get("resolution") or "").splitlines()
                           if line.strip() and not line.lstrip().startswith("["))
    ticket_no = str(data.get("ticket_no") or "")
    await _enqueue(
        session,
        template_code="INCIDENT_RESOLVED",
        context={
            "ticket_no": ticket_no,
            "title": data.get("title") or "",
            "room_number": data.get("room_number") or "—",
            "resolution": resolution,
        },
        property_id=_uuid_or_none(data.get("property_id")),
        tenant_id=tenant_id,
        priority=Priority.NORMAL.value,
        dedupe_key=f"INCIDENT_RESOLVED:{ticket_no}",
    )


async def _on_room_status_changed(session: AsyncSession, event: DomainEvent) -> None:
    """
    Phòng đổi trạng thái → nhật ký nội bộ.

    ⭐ `dedupe_key` CỐ TÌNH là `None`.
        Event này phát ra rất nhiều (mỗi lần đổi trạng thái phòng) và mỗi lần là một
        thông báo KHÁC NHAU. Khoá theo phòng sẽ chặn nhầm các lần đổi trạng thái
        hợp lệ về sau (trống → bảo trì → trống lại đều là 1 phòng).
    """
    data = event.data
    await _enqueue(
        session,
        template_code="ROOM_STATUS_CHANGED",
        context={
            "room_number": data.get("room_number") or "—",
            "from_status": _ROOM_STATUSES.get(str(data.get("from")),
                                              data.get("from") or "—"),
            "to_status": _ROOM_STATUSES.get(str(data.get("to")),
                                            data.get("to") or "—"),
            "reason": data.get("reason") or "",
        },
        property_id=_uuid_or_none(data.get("property_id")),
        priority=Priority.LOW.value,
        dedupe_key=None,
    )


# =================================================================================================
#  TIỆN ÍCH NỘI BỘ
# =================================================================================================
def _resolve_property(user: CurrentUser, requested: uuid.UUID | None) -> uuid.UUID | None:
    """
    Xác định cơ sở đang xem và kiểm tra quyền.

    ADMIN xem được tất cả (nên `requested` có thể `None` = toàn hệ thống); MANAGER
    bị khoá trong đúng cơ sở được gán.
    """
    if user.is_admin:
        return requested
    if user.property_id is None:
        raise BusinessRuleError(
            "Tài khoản chưa được gán vào cơ sở nào. Hãy liên hệ quản trị viên."
        )
    if requested is not None and str(requested) != str(user.property_id):
        user.assert_property_access(requested)
    return user.property_id


def _used_variables(template: Template) -> list[str]:
    """Danh sách biến template dùng — để UI đối chiếu với `context` gửi lên."""
    return sorted(set(template_variables(template.body))
                  | set(template_variables(template.subject or "")))


def _manual_dedupe_key(payload: NotificationSendRequest) -> str:
    """
    Khoá chống gửi trùng cho thông báo gửi TAY.

    Có NGÀY gửi trong khoá: cùng một người nhận, cùng một mã hóa đơn, nhắc lại vào
    ngày hôm sau là chuyện bình thường và cần thiết; bấm 2 lần trong cùng 1 phút
    mới là lỗi.
    """
    return (f"MANUAL:{payload.template_code}:{payload.recipient}:"
            f"{date.today().isoformat()}")


async def _get_template_or_404(session: AsyncSession, code: str) -> Template:
    template = await session.get(Template, code)
    if template is None:
        raise NotFoundError(
            f"Không có khuôn mẫu '{code}'. "
            f"Danh sách hiện có: {', '.join(t['code'] for t in DEFAULT_TEMPLATES)}.",
        )
    return template


async def _get_notification_or_404(
    session: AsyncSession, notification_id: uuid.UUID,
) -> Notification:
    notification = await session.get(Notification, notification_id)
    if notification is None:
        raise NotFoundError(f"Không tìm thấy thông báo {notification_id}")
    return notification


# =================================================================================================
#  ĐĂNG KÝ ROUTER
# =================================================================================================
# ⚠️  Thứ tự KHÔNG quan trọng giữa các router, nhưng thứ tự ĐĂNG KÝ ROUTE trong
#     `notification_router` thì có: FastAPI khớp theo thứ tự khai báo, nên
#     `/stats`, `/preview`, `/send` phải khai báo TRƯỚC `/{notification_id}`.
app.include_router(template_router)
app.include_router(notification_router)
app.include_router(internal_router)
