"""
Giám sát: metrics Prometheus + log có cấu trúc + request ID.

Vì sao cần?
  - Biết hệ thống có thực sự khỏe không (trước khi người dùng báo)
  - Biết service nào là nút thắt
  - Chứng minh SLA bằng số liệu, không bằng cảm tính
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import ClassVar

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest
from prometheus_client.core import CollectorRegistry
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .config import settings

# ---------------------------------------------------------------------------
#  ContextVar — truy vết request xuyên suốt các lớp
# ---------------------------------------------------------------------------
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
current_user_ctx: ContextVar[str] = ContextVar("current_user", default="-")


def get_request_id() -> str:
    return request_id_ctx.get()


# ---------------------------------------------------------------------------
#  Metrics
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Tổng số HTTP request",
    ["service", "method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Thời gian xử lý HTTP request (giây)",
    ["service", "method", "endpoint"],
    # Buckets tinh vi ở vùng quan tâm: SLA là 300–500ms
    # Buckets mặc định (0.005 → 10s) bỏ sót toàn bộ vùng p95 của hệ thống này
    buckets=(0.005, 0.010, 0.025, 0.050, 0.075, 0.100, 0.150, 0.200,
             0.300, 0.500, 0.750, 1.0, 2.5, 5.0, 10.0),
)

REQUEST_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Số request đang xử lý",
    ["service", "endpoint"],
)

OUTBOX_PENDING = Gauge(
    "outbox_pending_events",
    "Số event chưa gửi trong outbox",
    ["service"],
)

HEALTH_STATUS = Gauge(
    "healthcheck_status",
    "1 = healthy, 0 = unhealthy",
    ["service", "component"],
)

EVENT_PUBLISHED = Counter(
    "domain_events_published_total",
    "Số event nghiệp vụ đã phát",
    ["service", "event_type"],
)

EVENT_CONSUMED = Counter(
    "domain_events_consumed_total",
    "Số event nghiệp vụ đã xử lý",
    ["service", "event_type", "result"],
)

DB_POOL_SIZE = Gauge(
    "db_pool_connections",
    "Số kết nối trong pool",
    ["service", "state"],
)

BUSINESS_GAUGE = Gauge(
    "business_metric",
    "Chỉ số nghiệp vụ (tỷ lệ lấp đầy, tỷ lệ thu hồi tiền...)",
    ["service", "metric", "property"],
)

# Bộ đếm cho script kiểm thử tích hợp (smoke_test)
SMOKE_TOTAL = Counter(
    "smoke_test_requests_total",
    "Tổng số request kiểm thử tích hợp",
    ["endpoint", "result"],
)
SMOKE_LATENCY = Histogram(
    "smoke_test_duration_seconds",
    "Thời gian kiểm thử tích hợp",
    ["endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)


def record_business_event(service: str, event_type: str) -> None:
    EVENT_PUBLISHED.labels(service=service, event_type=event_type).inc()


def record_consumed(service: str, event_type: str, ok: bool = True) -> None:
    EVENT_CONSUMED.labels(
        service=service, event_type=event_type, result="ok" if ok else "error"
    ).inc()


def set_business_gauge(service: str, metric: str, value: float, property_id: str = "-") -> None:
    BUSINESS_GAUGE.labels(service=service, metric=metric, property=property_id).set(value)


# ---------------------------------------------------------------------------
#  Log có cấu trúc (JSON) — Loki/Promtail đọc được
# ---------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    """Log dạng JSON: đủ trường để truy vấn, lọc, cảnh báo trong Grafana."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": settings.service_name,
            "request_id": getattr(record, "request_id", request_id_ctx.get()),
            "user": getattr(record, "user", current_user_ctx.get()),
        }

        # ⭐ Chỉ ghi extra đã được khai báo tường minh.
        #   KHÔNG đưa toàn bộ record.__dict__ vào log: dễ lộ mật khẩu/token
        #   nếu ai đó vô tình log(extra=locals()).
        for field in ("http_method", "http_path", "http_status",
                      "http_duration_ms", "event_type", "user_id",
                      "property_id", "error_type", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class ContextFilter(logging.Filter):
    """Tự động gắn request_id vào mọi log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.service = settings.service_name
        return True


def setup_telemetry() -> None:
    """Cấu hình logging. Gọi 1 lần khi khởi động service."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    # Production → JSON (Loki đọc). Dev → dạng người đọc được.
    handler.setFormatter(
        JsonFormatter()
        if settings.is_production
        else logging.Formatter("%(asctime)s │ %(levelname)-7s │ %(name)-22s │ %(message)s")
    )
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Tắt log ồn ào của thư viện
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "aio_pika", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "📊 Telemetry sẵn sàng | cấu hình: %s", settings.safe_summary()
    )


# ---------------------------------------------------------------------------
#  Middleware
# ---------------------------------------------------------------------------
class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Ghi metrics cho mỗi request + gán request ID.

    ⭐ Chỉ gắn nhãn endpoint theo MẪU ĐƯỜNG DẪN, KHÔNG dùng URL thật.
       Nếu dùng URL thật, mỗi /rooms/{uuid} tạo ra một chuỗi metric mới →
       cardinality bùng nổ, Prometheus tốn hết bộ nhớ. Đây là lỗi phổ biến nhất
       khi tự viết metrics.
    """

    #: Các đường dẫn KHÔNG ghi vào metric. Nếu đo cả chúng, `curl /health` mỗi
    #: 15 giây sẽ làm tăng số chuỗi `http_requests_total` vô ích — bài toán
    #: cardinality của Prometheus nổ tung trước khi ta kịp đoán.
    EXCLUDED: ClassVar[set[str]] = {
        "/health", "/metrics", "/favicon.ico", "/docs", "/redoc", "/openapi.json",
    }

    async def dispatch(self, request: Request, call_next: ASGIApp) -> Response:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        request.state.request_id = rid

        endpoint = self._route_template(request)
        start = time.perf_counter()
        status_code = 500

        REQUEST_IN_PROGRESS.labels(
            service=settings.service_name, endpoint=endpoint
        ).inc()

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            duration = time.perf_counter() - start

            if endpoint not in self.EXCLUDED:
                REQUEST_COUNT.labels(
                    service=settings.service_name,
                    method=request.method,
                    endpoint=endpoint,
                    status=str(status_code),
                ).inc()
                REQUEST_LATENCY.labels(
                    service=settings.service_name,
                    method=request.method,
                    endpoint=endpoint,
                ).observe(duration)

            REQUEST_IN_PROGRESS.labels(
                service=settings.service_name, endpoint=endpoint
            ).dec()

            # Log ở mức WARNING trở lên; request chậm cũng được ghi
            if duration > 1.0 or status_code >= 500:
                logging.getLogger("http.access").warning(
                    "%s %s → %s (%.0fms)",
                    request.method, request.url.path, status_code, duration * 1000,
                    extra={
                        "http_method": request.method,
                        "http_path": request.url.path,
                        "http_status": status_code,
                        "http_duration_ms": round(duration * 1000, 1),
                    },
                )

            request_id_ctx.reset(token)

    @staticmethod
    def _route_template(request: Request) -> str:
        """
        Lấy mẫu đường dẫn từ route đã khớp, ví dụ /rooms/{room_id}
        thay vì /rooms/8f3a-2b1c-...
        """
        route = request.scope.get("route")
        if route is not None and getattr(route, "path", None):
            return route.path
        return "unmatched"


async def metrics_endpoint(request: Request) -> Response:
    """Handler cho GET /metrics."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# Registry riêng để test có thể reset
TEST_REGISTRY = CollectorRegistry()
