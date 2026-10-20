"""
Application Factory — khung chung cho cả 8 microservice.

Mỗi service chỉ cần:
    app = create_service_app("room", "Quản lý danh mục phòng")
    app.include_router(room_router)

Phần còn lại (config, DB, metrics, health, exception handler, event bus,
Redis, vòng đời) đã có sẵn ở đây. Đây chính là giá trị của "hạ tầng dùng
chung": viết nghiệp vụ 1 lần, không phải lặp lại 8 lần plumbing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.requests import Request

from .clients import close_all_clients
from .config import settings
from .database import (
    DatabaseHealth,
    create_tables,
    dispose_db,
    engine,
    get_pool_stats,
    health_check_db,
    init_db,
)
from .errors import setup_exception_handlers
from .events import ensure_outbox_schema, get_event_bus
from .telemetry import (
    DB_POOL_SIZE,
    HEALTH_STATUS,
    OUTBOX_PENDING,
    MetricsMiddleware,
    metrics_endpoint,
    setup_telemetry,
)

logger = logging.getLogger(__name__)


@dataclass
class ServiceContext:
    """
    Context dùng chung cho toàn bộ vòng đời service.

    Giữ các tài nguyên ở app.state để router/service khác truy cập được,
    thay vì tạo lại connection ở mỗi nơi.
    """

    name: str
    redis: object | None = None
    event_bus: object | None = None
    started_at: float = field(default_factory=time.time)
    consumers: list = field(default_factory=list)

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.started_at

    @property
    def uptime_human(self) -> str:
        s = int(self.uptime_seconds)
        d, rem = divmod(s, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        return f"{d}d {h}h {m}m" if d else (f"{h}h {m}m" if h else f"{m}m {s % 60}s")


# ---------------------------------------------------------------------------
#  Factory
# ---------------------------------------------------------------------------
def create_service_app(
    name: str,
    description: str,
    version: str = "1.0.0",
    lifespan_extra: Callable | None = None,
    enable_scheduler: bool = False,
) -> FastAPI:
    """
    Tạo FastAPI app đã cấu hình đầy đủ cho 1 microservice.

    Args:
        name:            tên service (khớp biến SERVICE_NAME)
        description:     mô tả, hiện trong OpenAPI
        lifespan_extra:  hàm async context manager bổ sung để service
                         tự đăng ký consumer/job riêng
        enable_scheduler: bật scheduler nền trong service này
    """

    # ---- Ghi log: phải bật TRƯỚC mọi thứ khác ----
    setup_telemetry()
    ctx = ServiceContext(name=name)

    # ---- Vòng đời ứng dụng ----
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("🚀 %s khởi động (port %s, env=%s)",
                    name, settings.port, settings.environment)
        logger.info("   Cấu hình: %s", settings.safe_summary())

        await init_db()

        # --- Redis (không bắt buộc phải có) ---
        if settings.redis_url:
            try:
                import redis.asyncio as aioredis

                ctx.redis = aioredis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_keepalive=True,
                    health_check_interval=30,
                )
                await ctx.redis.ping()
                logger.info("   ✓ Redis kết nối thành công")
            except Exception as exc:
                logger.warning("   ⚠ Redis không khả dụng (%s) — tiếp tục không cache", exc)
                ctx.redis = None

        app.state.ctx = ctx
        app.state.redis = ctx.redis

        # --- Bảng hạ tầng giao tiếp (outbox + processed_events) ---
        try:
            async with engine.begin() as conn:
                await ensure_outbox_schema(conn)
            logger.info("   ✓ Bảng outbox/processed_events sẵn sàng")
        except Exception as exc:
            logger.warning("   ⚠ Không tạo được bảng outbox: %s", exc)

        # --- Event bus (outbox publisher) ---
        if settings.rabbitmq_url:
            ctx.event_bus = get_event_bus()
            try:
                await ctx.event_bus.start()
            except Exception as exc:
                logger.error("   ✗ EventBus lỗi: %s — event sẽ tích tụ trong outbox", exc)

        # --- Tạo bảng nghiệp vụ ---
        try:
            await create_tables()
            logger.info("   ✓ Schema đã sẵn sàng")
        except Exception as exc:
            logger.warning("   ⚠ create_tables: %s (hãy dùng Alembic migration)", exc)

        # --- Scheduler nền (nếu có) ---
        scheduler_task = None
        if enable_scheduler:
            scheduler_task = asyncio.create_task(_run_scheduler(app))
            logger.info("   ✓ Scheduler nền đã bật")

        # --- Consumer riêng của service ---
        if lifespan_extra:
            await lifespan_extra(app)

        logger.info("✅ %s sẵn sàng nhận request", name)

        yield   # ──────── ứng dụng đang chạy ────────

        # ---------- Dừng ----------
        logger.info("🛑 %s đang dừng...", name)
        if scheduler_task:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
        if ctx.event_bus:
            await ctx.event_bus.stop()
        if ctx.redis:
            with suppress(Exception):
                await ctx.redis.aclose()
        await close_all_clients()
        await dispose_db()
        logger.info("👋 %s đã dừng sau %s", name, ctx.uptime_human)

    # ---- Tạo app ----
    app = FastAPI(
        title=f"QLPT · {name}",
        description=description,
        version=version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
        # Đặt contact cho tài liệu API trông chuyên nghiệp
        contact={"name": "QLPT Team", "url": "https://qlpt.vn"},
        license_info={"name": "MIT"},
    )

    # ---------------- Middleware (thứ tự quan trọng) ----------------
    # Ghi log/metrics phải CHẠY ĐẦU TIÊN để bao trọn thời gian của các
    # middleware phía sau. BaseHTTPMiddleware chạy theo thứ tự đăng ký.
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Cache-Status"],
        max_age=3600,
    )

    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*"],   # nginx đã lọc Host; siết lại nếu có domain cụ thể
        )

    # ---------------- Xử lý lỗi ----------------
    setup_exception_handlers(app)

    # ---------------- Endpoint hệ thống ----------------
    _register_system_routes(app, ctx, name, version)

    logger.info("Đã tạo app factory cho %s", name)
    return app


# ---------------------------------------------------------------------------
#  Endpoint hệ thống
# ---------------------------------------------------------------------------
def _register_system_routes(app: FastAPI, ctx: ServiceContext,
                            name: str, version: str) -> None:
    """
    4 endpoint dưới đây là BẮT BUỘC cho mọi microservice trong kiến trúc
    này — chúng là hợp đồng giữa service với hạ tầng vận hành:

      /health    → Docker healthcheck + load balancer
      /ready     → sẵn sàng nhận traffic (khác /health: có thể chưa sẵn sàng
                   trong lúc đang khởi động)
      /metrics   → Prometheus
      /system/info → thông tin phiên bản cho quản trị
    """

    @app.get("/health", tags=["system"],
             summary="Kiểm tra sức khỏe (Docker healthcheck dùng endpoint này)")
    async def health() -> JSONResponse:
        db_status, db_ms, db_msg = await health_check_db()
        HEALTH_STATUS.labels(service=name, component="database").set(
            1 if db_status is DatabaseHealth.HEALTHY else 0
        )

        redis_ok = True
        if ctx.redis is not None:
            try:
                await ctx.redis.ping()
            except Exception:
                redis_ok = False
        HEALTH_STATUS.labels(service=name, component="redis").set(1 if redis_ok else 0)

        # Degraded = vẫn phục vụ được nhưng có phụ thuộc chưa sẵn sàng.
        # Quan trọng: KHÔNG trả unhealthy nếu chỉ Redis chết — service
        # vẫn dùng được, chỉ mất cache.
        overall = "healthy"
        if db_status is DatabaseHealth.UNHEALTHY:
            overall = "unhealthy"
        elif db_status is DatabaseHealth.DEGRADED or not redis_ok:
            overall = "degraded"

        # 503 nếu CSDL chết → Docker sẽ restart container
        status_code = 503 if overall == "unhealthy" else 200

        return JSONResponse(
            status_code=status_code,
            content={
                "status": overall,
                "service": name,
                "version": version,
                "uptime": ctx.uptime_human,
                "components": {
                    "database": {"status": db_status.value, "latency_ms": round(db_ms, 1),
                                 "detail": db_msg},
                    "redis": {"status": "healthy" if redis_ok else "unavailable"},
                },
            },
        )

    @app.get("/ready", tags=["system"],
             summary="Sẵn sàng nhận traffic (khác /health ở chỗ tách DB khỏi Redis)")
    async def ready() -> JSONResponse:
        db_status, _, _ = await health_check_db()
        ok = db_status is not DatabaseHealth.UNHEALTHY
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"ready": ok, "database": db_status.value},
        )

    @app.get("/metrics", tags=["system"],
             summary="Metrics Prometheus")
    async def metrics(request: Request) -> JSONResponse:
        # Cập nhật metric pool + outbox trước khi trả về
        try:
            stats = await get_pool_stats()
            DB_POOL_SIZE.labels(service=name, state="size").set(stats["size"])
            DB_POOL_SIZE.labels(service=name, state="checked_out").set(stats["checked_out"])
        except Exception:
            pass

        try:
            async with engine.connect() as conn:
                n = (await conn.execute(
                    text("SELECT count(*) FROM outbox WHERE status='NEW'")
                )).scalar() or 0
            OUTBOX_PENDING.labels(service=name).set(n)
        except Exception:
            OUTBOX_PENDING.labels(service=name).set(-1)

        return await metrics_endpoint(request)

    @app.get("/system/info", tags=["system"], summary="Thông tin hệ thống")
    async def system_info() -> dict:
        from .clients import circuit_stats

        return {
            "service": name,
            "version": version,
            "environment": settings.environment,
            "uptime_seconds": round(ctx.uptime_seconds),
            "uptime_human": ctx.uptime_human,
            "python": __import__("sys").version.split()[0],
            "config": settings.safe_summary(),
            "consumers": [c.stats() for c in ctx.consumers if hasattr(c, "stats")],
            "circuits": circuit_stats(),
            "pool": await get_pool_stats(),
        }

    @app.get("/", tags=["system"], include_in_schema=False)
    async def root() -> dict:
        return {
            "service": name,
            "version": version,
            "docs": "/docs" if settings.docs_enabled else "(tắt ở production)",
            "health": "/health",
            "metrics": "/metrics",
        }


# ---------------------------------------------------------------------------
#  Scheduler nền
# ---------------------------------------------------------------------------
async def _run_scheduler(app: FastAPI) -> None:
    """
    Task nền chạy song song với ứng dụng.

    ⚠️  Khi chạy NHIỀU bản sao (replica), chỉ ĐỂ 1 bản chạy scheduler.
        Cách chắc chắn: dùng khóa phân tán Redis, hoặc tách scheduler ra
        container riêng (cách dùng trong docker-compose.yml của dự án này).
    """
    from .config import get_settings
    from .telemetry import set_business_gauge

    s = get_settings()
    tick = 0
    while True:
        try:
            tick += 1
            logger.info("⏰ Scheduler tick #%s", tick)
            set_business_gauge(s.service_name, "scheduler_ticks", tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lỗi scheduler tick")
        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
#  Tiện ích cho router
# ---------------------------------------------------------------------------
def make_router(name: str, prefix: str, tags: list[str],
                dependencies: list | None = None) -> APIRouter:
    """Tạo router chuẩn — gom phần lặp trong 8 service."""
    return APIRouter(
        prefix=prefix,
        tags=tags or [name],
        dependencies=dependencies or [],
    )
