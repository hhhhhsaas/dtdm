"""
Giao tiếp bất đồng bộ: Outbox Pattern + RabbitMQ.

=============================================================================
VÌ SAO CẦN OUTBOX? — "Dual Write Problem"
=============================================================================
Tình huống: cần ghi hóa đơn vào DB *và* gửi thông báo cho người thuê.

    Cách SAI (dual write):
        await db.save(invoice)      # ← bước 1
        await broker.publish(evt)   # ← bước 2
        return success

    Nếu container bị OOM kill giữa bước 1 và bước 2?
        → Hóa đơn ĐÃ TẠO, nhưng người thuê KHÔNG NHẬN ĐƯỢC thông báo.
        → Dữ liệu và thông báo LỆCH NHAU vĩnh viễn. Không phát hiện được.

    Cách ĐÚNG (transactional outbox):
        # Cùng MỘT transaction:
        await db.save(invoice)
        await db.add_outbox_event(evt)   # ghi event vào BẢNG outbox
        await db.commit()                 # ← cả hai cùng thành công hoặc cùng hủy

        # Publisher chạy riêng, đọc bảng outbox rồi gửi đi
        # → Nếu chết trước khi gửi: event vẫn còn trong bảng, lần sau sẽ gửi
        # → Nếu gửi xong rồi chết: gửi trùng → consumer phải idempotent

    Đánh đổi: chấp nhận **GỬI TRÙNG** để đổi lấy **KHÔNG BAO GIỜ MẤT**.

=============================================================================
VÌ SAO CONSUMER PHẢI IDEMPOTENT?
=============================================================================
RabbitMQ bảo đảm "at-least-once" delivery: nếu consumer chết sau khi xử lý
nhưng chưa ACK, message sẽ được gửi lại → xử lý 2 lần.

Giải pháp: bảng processed_events có UNIQUE trên event_id. Insert trong CÙNG
transaction với xử lý nghiệp vụ → nếu insert trùng thì cả transaction rollback
→ tự động bỏ qua.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Bảng outbox & processed events — dùng chung cho MỌI service.
#  Đây là ngoại lệ hợp lệ duy nhất của nguyên tắc "database-per-service":
#  bảng này thuộc hạ tầng giao tiếp, không phải dữ liệu nghiệp vụ.
# ---------------------------------------------------------------------------
OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS outbox (
    id             UUID PRIMARY KEY,
    event_type     VARCHAR(100) NOT NULL,
    payload        JSONB        NOT NULL,
    aggregate_type VARCHAR(100),
    aggregate_id   VARCHAR(100),
    correlation_id VARCHAR(100),
    schema_version SMALLINT     NOT NULL DEFAULT 1,
    status         VARCHAR(20)  NOT NULL DEFAULT 'NEW',
    attempts       SMALLINT     NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    published_at   TIMESTAMPTZ,
    last_error     TEXT
);

-- Index phục vụ publisher: chỉ quét event CHƯA gửi
CREATE INDEX IF NOT EXISTS ix_outbox_pending
    ON outbox (status, created_at)
    WHERE status = 'NEW';

CREATE INDEX IF NOT EXISTS ix_outbox_aggregate
    ON outbox (aggregate_type, aggregate_id);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id     UUID        PRIMARY KEY,
    event_type   VARCHAR(100) NOT NULL,
    consumer     VARCHAR(100) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_processed_at
    ON processed_events (processed_at);
"""

PROCESSED_DDL = """
CREATE TABLE IF NOT EXISTS processed_events (
    event_id     UUID        PRIMARY KEY,
    event_type   VARCHAR(100) NOT NULL,
    consumer     VARCHAR(100) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ---------------------------------------------------------------------------
#  Tạo bảng hạ tầng giao tiếp (outbox + processed_events)
# ---------------------------------------------------------------------------
_schema_ensured = False


async def ensure_outbox_schema(executor) -> None:
    """Tạo bảng `outbox` + `processed_events` (idempotent, 1 lần/tiến trình).

    ⭐ VÌ SAO PHẢI TÁCH TỪNG CÂU LỆNH: driver asyncpg chỉ cho phép MỘT câu
    lệnh trong một prepared statement. Chạy cả khối OUTBOX_DDL (nhiều câu
    cách nhau dấu `;`) sẽ lỗi:
        asyncpg.exceptions.PostgresSyntaxError:
        cannot insert multiple commands into a prepared statement
    → mọi thao tác ghi event (outbox) và cả vòng lặp publisher đều thất bại.
    Vì vậy ta tách DDL theo `;`, bỏ các dòng chú thích `--`, rồi thực thi lần lượt.

    `executor` nhận cả AsyncSession lẫn AsyncConnection (đều có `.execute`).
    """
    global _schema_ensured
    if _schema_ensured:
        return
    for raw in OUTBOX_DDL.split(";"):
        stmt = "\n".join(
            line for line in raw.splitlines() if not line.lstrip().startswith("--")
        ).strip()
        if stmt:
            await executor.execute(text(stmt))
    _schema_ensured = True



# ---------------------------------------------------------------------------
#  Định nghĩa Event
# ---------------------------------------------------------------------------
class EventStatus(str, Enum):
    NEW = "NEW"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


@dataclass(slots=True)
class DomainEvent:
    """
    Event nghiệp vụ. Bất biến (immutable) — sai thì phát event mới, không sửa.

    Bắt buộc có:
      event_id        — chống xử lý trùng
      event_type      — routing key
      occurred_at     — thời điểm xảy ra nghiệp vụ
      schema_version  — tương thích ngược khi thêm/bớt trường
      correlation_id  — truy vết xuyên suốt 1 luồng nghiệp vụ
    """

    event_type: str
    data: dict[str, Any]
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    producer: str = ""
    schema_version: int = 1
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self):
        if not self.producer:
            self.producer = settings.service_name

    def to_dict(self) -> dict:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.isoformat(),
            "producer": self.producer,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, raw: dict) -> DomainEvent:
        return cls(
            event_id=uuid.UUID(raw["event_id"]),
            event_type=raw["event_type"],
            data=raw.get("data", {}),
            occurred_at=datetime.fromisoformat(raw["occurred_at"]),
            producer=raw.get("producer", "unknown"),
            schema_version=raw.get("schema_version", 1),
            correlation_id=raw.get("correlation_id"),
            causation_id=raw.get("causation_id"),
        )

    @property
    def routing_key(self) -> str:
        """
        Routing key trên RabbitMQ topic exchange.

        Quy ước: <domain>.<sự kiện>, dùng dấu chấm để binding key #.* khớp.
        """
        return self.event_type


# ---------------------------------------------------------------------------
#  Ghi event vào outbox (TRONG CÙNG TRANSACTION với dữ liệu nghiệp vụ)
# ---------------------------------------------------------------------------
async def enqueue_outbox(
    session: AsyncSession,
    event: DomainEvent,
) -> uuid.UUID:
    """
    ⭐ HÀM QUAN TRỌNG NHẤT của kiến trúc event-driven.

    Gọi SAU khi thêm/sửa dữ liệu nghiệp vụ, TRƯỚC khi commit:

        session.add(invoice)
        await enqueue_outbox(session, DomainEvent(
            event_type="invoice.issued",
            data={...},
        ))
        # commit diễn ra trong get_session()
    """
    await ensure_outbox_schema(session)

    await session.execute(
        text("""
            INSERT INTO outbox
                (id, event_type, payload, aggregate_type, aggregate_id,
                 correlation_id, schema_version, status)
            VALUES
                (:id, :etype, CAST(:payload AS jsonb), :agg_type, :agg_id,
                 :corr_id, :ver, 'NEW')
        """),
        {
            "id": str(event.event_id),
            "etype": event.event_type,
            "payload": event.to_json(),
            "agg_type": event.data.get("entity_type"),
            "agg_id": str(event.data.get("entity_id", "")) or None,
            "corr_id": event.correlation_id,
            "ver": event.schema_version,
        },
    )
    logger.info("📤 Outbox +1: %s (%s)", event.event_type, event.event_id)
    return event.event_id


# ---------------------------------------------------------------------------
#  Abstract broker
# ---------------------------------------------------------------------------
class MessageBroker(ABC):
    """Interface của broker — cho phép thay RabbitMQ bằng Kafka/NATS mà không sửa code."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def publish(self, exchange: str, routing_key: str, body: str,
                      correlation_id: str | None = None,
                      headers: dict | None = None) -> None: ...

    @abstractmethod
    async def consume(self, queue: str, handler: Callable[[DomainEvent], Awaitable[None]],
                      routing_keys: list[str] | None = None) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    def is_ready(self) -> bool:
        """Broker đã kết nối và kênh còn mở chưa (để EventBus biết cần kết nối lại)."""
        return False


class RabbitMQBroker(MessageBroker):
    """Triển khai cụ thể bằng aio-pika."""

    TOPIC_EXCHANGE = "qlpt.topic"
    DLX_EXCHANGE = "qlpt.dlx"
    DLQ_QUEUE = "qlpt.dlq"

    def __init__(self) -> None:
        self._conn = None
        self._channel = None
        self._url = settings.rabbitmq_url
        self._consumer_tags: list[str] = []

    def is_ready(self) -> bool:
        return self._channel is not None and not self._channel.is_closed

    async def connect(self) -> None:
        if not self._url:
            logger.warning("Không có RABBITMQ_URL — bỏ qua kết nối broker")
            return
        # ⭐ Nếu kênh đang mở thì không tạo kết nối mới (tránh rò rỉ connection
        #    khi EventBus gọi connect() định kỳ để "chắc chắn" đã kết nối).
        if self.is_ready():
            return
        try:
            import aio_pika

            self._conn = await asyncio.wait_for(
                aio_pika.connect_robust(self._url, heartbeat=30), timeout=15
            )
            self._channel = await self._conn.channel()
            await self._channel.set_qos(prefetch_count=settings.rabbitmq_prefetch)

            # ⭐ Toàn bộ topology (exchange/queue/binding) do CODE tự khai báo —
            #    definitions.json chỉ còn lo user/vhost/quyền. Nhờ vậy không còn
            #    tình trạng queue khai sẵn trong definitions lệch tham số với
            #    lần declare của service (từng gây PRECONDITION_FAILED).
            await self._channel.declare_exchange(
                self.TOPIC_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
            )
            dlx = await self._channel.declare_exchange(
                self.DLX_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True
            )
            # Hàng đợi chữa cháy (DLQ): nhận mọi message bị reject từ các queue
            # tiêu thụ (các queue đó trỏ x-dead-letter-exchange về DLX).
            dlq = await self._channel.declare_queue(self.DLQ_QUEUE, durable=True)
            await dlq.bind(dlx)   # exchange fanout → không cần routing key
            logger.info("🐰 Đã kết nối RabbitMQ (%s)", self._url.split("@")[-1])
        except Exception as exc:
            # KHÔNG chết vì broker lỗi — service vẫn phục vụ được các API đồng bộ.
            # Outbox sẽ giữ event cho tới khi kết nối lại (đây là lý do dùng outbox).
            logger.error("Không kết nối được RabbitMQ: %s", exc)
            self._conn = None
            self._channel = None

    async def publish(self, exchange: str, routing_key: str, body: str,
                      correlation_id: str | None = None,
                      headers: dict | None = None) -> None:
        import aio_pika

        if self._channel is None or self._channel.is_closed:
            raise ConnectionError("RabbitMQ chưa sẵn sàng")

        message = aio_pika.Message(
            body=body.encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # ⭐ phải bền với hàng đợi
            content_type="application/json",
            correlation_id=correlation_id,
            message_id=headers.get("message_id") if headers else None,
            headers=headers or {},
            timestamp=datetime.now(UTC),
        )
        topic = await self._channel.get_exchange(exchange)
        await topic.publish(message, routing_key=routing_key)

    async def consume(self, queue: str, handler: Callable[[DomainEvent], Awaitable[None]],
                      routing_keys: list[str] | None = None) -> None:
        """Đăng ký consumer. Handler phải tự xử lý idempotent + retry + DLQ."""
        import aio_pika

        if self._channel is None:
            logger.warning("Không có channel — bỏ qua consumer %s", queue)
            return

        # ⭐ Khai báo queue kèm x-dead-letter-exchange để message bị reject
        #    (xem `_on_message`) được đưa sang DLQ thay vì biến mất.
        ch = await self._channel.declare_queue(
            queue, durable=True,
            arguments={"x-dead-letter-exchange": self.DLX_EXCHANGE},
        )
        exchange = await self._channel.get_exchange(self.TOPIC_EXCHANGE)

        for key in routing_keys or ["#"]:
            await ch.bind(exchange, routing_key=key)

        async def _on_message(message: aio_pika.IncomingMessage) -> None:
            async with message.process(requeue=False, ignore_processed=True):
                try:
                    raw = json.loads(message.body)
                    event = DomainEvent.from_dict(raw)
                    await handler(event)
                except json.JSONDecodeError:
                    logger.error("Event không phải JSON hợp lệ → bỏ qua (không requeue)")
                except Exception:
                    # nack(requeue=False) → message vào DLQ nếu queue có
                    # x-dead-letter-exchange. Không requeue để tránh
                    # vòng lặp vô hạn với event hỏng vĩnh viễn.
                    logger.exception("Xử lý event thất bại → chuyển DLQ")
                    await message.reject(requeue=False)

        consumer_tag = await ch.consume(_on_message, no_ack=False)
        self._consumer_tags.append(consumer_tag)
        logger.info("🐰 Consumer đăng ký: %s (routing: %s)",
                    queue, routing_keys or ["#"])

    async def close(self) -> None:
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
        if self._conn and not self._conn.is_closed:
            await self._conn.close()
        logger.info("🐰 Đã đóng kết nối RabbitMQ")


# ---------------------------------------------------------------------------
#  EventBus + Outbox Publisher
# ---------------------------------------------------------------------------
class EventBus:
    """
    Điểm vào duy nhất để publish/subscribe event.

    Luồng publish:
        DomainEvent → ghi bảng outbox (cùng transaction) → publisher đọc → RabbitMQ
    """

    def __init__(self, broker: MessageBroker | None = None) -> None:
        self.broker = broker or RabbitMQBroker()
        self._publisher_task: asyncio.Task | None = None
        self._running = False
        # Ghi nhớ mọi đăng ký consumer để đăng ký LẠI sau khi kết nối lại.
        self._subscriptions: list[
            tuple[str, Callable[[DomainEvent], Awaitable[None]], list[str] | None]
        ] = []

    async def start(self) -> None:
        await self.broker.connect()
        self._running = True
        self._publisher_task = asyncio.create_task(self._publish_loop())
        logger.info("EventBus đã khởi động (outbox poll mỗi %ss)",
                    settings.outbox_poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._publisher_task:
            self._publisher_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._publisher_task
        await self.broker.close()
        logger.info("EventBus đã dừng")

    async def _ensure_connected(self) -> None:
        """
        ⭐ Tự kết nối lại khi mất kết nối broker.

        `aio_pika.connect_robust` tự khôi phục nếu kết nối ĐÃ được thiết lập
        rồi bị rớt. Nhưng nếu lần `connect()` ĐẦU TIÊN thất bại (broker chưa
        lên, sai yêu cầu, exchange lệch tham số...), code cũ bỏ luôn đối tượng
        kết nối và KHÔNG ai gọi lại → outbox đứng im mãi mãi, consumer không
        bao giờ đăng ký. Hàm này bù đắp: kết nối lại rồi ĐĂNG KÝ LẠI toàn bộ
        consumer đã ghi nhớ.
        """
        if self.broker.is_ready():
            return
        await self.broker.connect()
        if not self.broker.is_ready():
            return
        for queue, handler, keys in self._subscriptions:
            try:
                await self.broker.consume(queue, handler, keys)
            except Exception:
                logger.exception("Đăng ký lại consumer %s thất bại", queue)

    # ---- Outbox publisher loop ----
    async def _publish_loop(self) -> None:
        """
        ⭐ Vòng lặp nền: mỗi N giây, lấy event chưa gửi từ bảng outbox và phát.

        Cần xử lý:
          - Retry với backoff khi broker lỗi
          - Giới hạn số event/lần để không tràn bộ nhớ
          - Cập nhật metrics để Prometheus cảnh báo được
        """
        from .database import session_scope

        batch_size = 100
        while self._running:
            # ⭐ Bảo đảm broker đã kết nối (và consumer đã đăng ký) TRƯỚC khi
            #    thử publish — kể cả khi lần kết nối đầu tiên đã thất bại.
            await self._ensure_connected()

            try:
                async with session_scope() as session:
                    await ensure_outbox_schema(session)

                    rows = (
                        await session.execute(
                            text("""
                                SELECT id, event_type, payload, correlation_id
                                FROM outbox
                                WHERE status = 'NEW'
                                ORDER BY created_at
                                LIMIT :limit
                            """),
                            {"limit": batch_size},
                        )
                    ).fetchall()

                    for row in rows:
                        try:
                            await self.broker.publish(
                                exchange=RabbitMQBroker.TOPIC_EXCHANGE,
                                routing_key=row.event_type,
                                body=json.dumps(row.payload, ensure_ascii=False, default=str),
                                correlation_id=row.correlation_id,
                                headers={"message_id": str(row.id)},
                            )
                            await session.execute(
                                text("""
                                    UPDATE outbox
                                    SET status = 'PUBLISHED', published_at = now()
                                    WHERE id = :id
                                """),
                                {"id": str(row.id)},
                            )
                        except ConnectionError as exc:
                            # Broker chưa sẵn sàng → dừng lại, thử lại vòng sau
                            await session.execute(
                                text("""
                                    UPDATE outbox SET attempts = attempts + 1,
                                                        last_error = :err
                                    WHERE id = :id
                                """),
                                {"id": str(row.id), "err": str(exc)[:500]},
                            )
                            logger.warning("Broker chưa sẵn sàng: %s", exc)
                            break
                        except Exception as exc:
                            await session.execute(
                                text("""
                                    UPDATE outbox
                                    SET attempts = attempts + 1, last_error = :err,
                                        status = CASE WHEN attempts > 5
                                                      THEN 'FAILED' ELSE 'NEW' END
                                    WHERE id = :id
                                """),
                                {"id": str(row.id), "err": str(exc)[:500]},
                            )
                            logger.exception("Lỗi publish event %s", row.id)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Lỗi trong outbox publisher loop")

            await asyncio.sleep(settings.outbox_poll_interval)

    # ---- API công khai ----
    async def publish(self, session: AsyncSession, event: DomainEvent) -> uuid.UUID:
        """Ghi event vào outbox — GỌI TRONG transaction nghiệp vụ."""
        return await enqueue_outbox(session, event)

    async def subscribe(self, queue: str, handler, routing_keys: list[str] | None = None) -> None:
        # Ghi nhớ để có thể đăng ký lại nếu broker phải kết nối lại.
        self._subscriptions.append((queue, handler, routing_keys))
        await self.broker.consume(queue, handler, routing_keys)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


async def close_event_bus() -> None:
    global _bus
    if _bus is not None:
        await _bus.stop()
        _bus = None


async def publish(session: AsyncSession, event: DomainEvent) -> uuid.UUID:
    """Hàm ngắn gọn."""
    return await get_event_bus().publish(session, event)


async def subscribe(queue: str, handler, routing_keys: list[str] | None = None) -> None:
    await get_event_bus().subscribe(queue, handler, routing_keys)


# ---------------------------------------------------------------------------
#  Idempotent consumer
# ---------------------------------------------------------------------------
class IdempotentConsumer:
    """
    Bọc handler để bảo đảm mỗi event chỉ được xử lý ĐÚNG MỘT LẦN.

    Cách dùng:

        async def handle_invoice_issued(event: DomainEvent):
            ...

        consumer = IdempotentConsumer(
            handler=handle_invoice_issued,
            consumer_name="notification-service:invoice-issued",
        )
        await bus.subscribe("qlpt.billing.invoice.generated",
                            consumer.handle,
                            ["billing.invoice.issued"])
    """

    def __init__(self, handler: Callable[[DomainEvent], Awaitable[None]],
                 consumer_name: str, max_retries: int = 3) -> None:
        self.handler = handler
        self.consumer_name = consumer_name
        self.max_retries = max_retries
        self.processed = 0
        self.duplicates = 0
        self.failures = 0

    async def handle(self, event: DomainEvent) -> None:
        from .database import session_scope

        try:
            async with session_scope() as session:
                await session.execute(text(PROCESSED_DDL))

                # Insert trước. Nếu event đã xử lý → unique violation → bỏ qua.
                # Nhờ cùng transaction, nếu handler lỗi thì cả insert cũng rollback
                # → event sẽ được thử lại (đúng behavior mong muốn).
                result = await session.execute(
                    text("""
                        INSERT INTO processed_events (event_id, event_type, consumer)
                        VALUES (:eid, :etype, :cname)
                        ON CONFLICT (event_id) DO NOTHING
                    """),
                    {
                        "eid": str(event.event_id),
                        "etype": event.event_type,
                        "cname": self.consumer_name,
                    },
                )

                if result.rowcount == 0:
                    self.duplicates += 1
                    logger.info(
                        "⏭ Bỏ qua event trùng %s (%s) — đã xử lý trước đó",
                        event.event_id, event.event_type,
                    )
                    return  # commit, coi như đã xử lý

                await self.handler(event)

            self.processed += 1
            logger.info("✅ Đã xử lý %s (%s)", event.event_type, event.event_id)

        except Exception:
            self.failures += 1
            logger.exception("❌ Xử lý thất bại: %s (%s)",
                             event.event_type, event.event_id)
            raise  # nack → DLQ

    def stats(self) -> dict:
        return {
            "consumer": self.consumer_name,
            "processed": self.processed,
            "duplicates_skipped": self.duplicates,
            "failures": self.failures,
        }
