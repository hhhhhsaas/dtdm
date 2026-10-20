"""
HTTP client gọi service khác — có timeout, retry, circuit breaker.

⭐ ĐÂY LÀ FILE QUAN TRỌNG NHẤT KHI LÀM MICROSERVICE.
Không có file này, hệ thống sẽ sập rất nhanh: 1 service chết → mọi service
gọi tới nó đều treo → hết connection → toàn hệ thống sập (hiệu ứng domino).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from enum import Enum
from typing import Any, ClassVar

import httpx

from .config import settings
from .errors import NotFoundError, ServiceUnavailableError

logger = logging.getLogger(__name__)

#: Tiền tố của mọi endpoint dành riêng cho service khác. Chỉ các đường
#: bắt đầu bằng chuỗi này mới được gắn token SYSTEM tự động (xem
#: `ServiceClient._headers`) — đó là ranh giới giữa "gọi nội bộ" và
#: "gọi như một người dùng", và cả hai cần kiểm tra quyền khác nhau.
INTERNAL_PREFIX = "/internal/"


# ---------------------------------------------------------------------------
#  Circuit Breaker
# ---------------------------------------------------------------------------
class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # bình thường — cho phép đi qua
    OPEN = "OPEN"            # đang lỗi hàng loạt — chặn mọi request
    HALF_OPEN = "HALF_OPEN"  # thử lại 5 request để xem service đã hồi phục chưa


class CircuitBreaker:
    """
    Ngắt mạch khi service phụ thuộc lỗi liên tiếp.

    Cơ chế:
      1. CLOSED: đo tỷ lệ lỗi trong N request gần nhất
      2. Nếu lỗi > ngưỡng → OPEN: mọi request bị chặn ngay (fail fast, không chờ timeout)
      3. Sau thời gian chờ → HALF_OPEN: cho vài request thử
      4. Nếu thành công → CLOSED. Nếu thất bại → OPEN lại.

    ⭐ Không có circuit breaker, khi PostgreSQL chết:
       - Mỗi request sẽ chờ 30s (statement_timeout)
       - 8 service × 20 connection đều kẹt
       - Toàn hệ thống không nhận được request nào
       → Dịch vụ NGỪNG HOẠT ĐỘNG, chỉ cần KHÔNG PHẢI SẬP.
    """

    def __init__(self, name: str, failure_threshold: int = 20,
                 open_duration: int = 30) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.open_duration = open_duration
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.opened_at = 0.0
        self.total_requests = 0
        self.total_failures = 0
        self.trip_count = 0

    def record_success(self) -> None:
        self.successes += 1
        self.failures = 0
        if self.state is CircuitState.HALF_OPEN:
            logger.info("🔌 Circuit [%s] đã hồi phục → CLOSED", self.name)
            self.state = CircuitState.CLOSED
            self.opened_at = 0.0

    def record_failure(self) -> None:
        self.failures += 1
        self.total_failures += 1
        if self.state is CircuitState.HALF_OPEN:
            self._open()
            return
        if self.failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        if self.state is not CircuitState.OPEN:
            logger.warning(
                "🔴 Circuit [%s] MỞ sau %s lỗi liên tiếp — chặn request trong %ss",
                self.name, self.failures, self.open_duration,
            )
        self.state = CircuitState.OPEN
        self.opened_at = time.monotonic()
        self.trip_count += 1

    def allows_request(self) -> bool:
        if self.state is CircuitState.CLOSED:
            self.total_requests += 1
            return True

        if self.state is CircuitState.OPEN:
            elapsed = time.monotonic() - self.opened_at
            if elapsed >= self.open_duration:
                logger.info("🟡 Circuit [%s] → HALF_OPEN (thử lại)", self.name)
                self.state = CircuitState.HALF_OPEN
                self.failures = 0
                self.total_requests += 1
                return True
            return False

        # HALF_OPEN: chỉ cho tối đa 5 request thử
        self.total_requests += 1
        return self.total_requests % 5 == 1

    def stats(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "consecutive_failures": self.failures,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "trip_count": self.trip_count,
            "failure_rate": (
                self.total_failures / self.total_requests if self.total_requests else 0
            ),
        }


# ---------------------------------------------------------------------------
#  Service client
# ---------------------------------------------------------------------------
class ServiceClient:
    """
    Client gọi service khác. Dùng chung cho toàn hệ thống.

    Tính năng:
      - Timeout riêng cho connect / read (không dùng mặc định 5s)
      - Retry CHỈ cho request idempotent (GET/HEAD/PUT/DELETE)
      - Circuit breaker theo từng service đích
      - Tự gán X-Request-ID để truy vết xuyên service
      - Metric cho Prometheus
    """

    #: Chỉ những method này mới được thử lại tự động. `POST`/`PATCH` KHÔNG
    #: an toàn để retry: nếu server đã ghi xong mà response thất lạc, retry
    #: sẽ tạo bản ghi trùng. Muốn an toàn thì dùng khoá idempotency ở tầng
    #: nghiệp vụ (vd UNIQUE(contract_id, period)), không phải retry mù.
    IDEMPOTENT_METHODS: ClassVar[set[str]] = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}

    def __init__(self, base_url: str, service_name: str,
                 timeout: float | None = None,
                 retries: int | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.retries = retries if retries is not None else settings.downstream_max_retries
        self.timeout = timeout or settings.downstream_read_timeout
        self.circuit = CircuitBreaker(
            name=service_name,
            failure_threshold=settings.circuit_failure_threshold,
            open_duration=settings.circuit_open_duration,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(
                    timeout=self.timeout,
                    connect=settings.downstream_connect_timeout,
                    read=self.timeout,
                    write=self.timeout,
                ),
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20,
                    keepalive_expiry=30,
                ),
                headers={"User-Agent": "qlpt-client/1.0", "Accept": "application/json"},
            )
        return self._client

    def _headers(self, path: str, extra: dict | None = None) -> dict:
        """
        Header đính kèm cho mọi lời gọi ra ngoài.

        ⭐ Token SYSTEM chỉ được gắn cho đường `/internal/`. Gắn cho mọi
           request thì một lỗi lập trình ở service gọi sẽ biến thành leo
           thang đặc quyền: token SYSTEM vượt qua mọi kiểm tra vai trò ở
           endpoint công khai, và chỉ cần sửa nhầm 1 dòng là xong.
        """
        from .security import create_internal_token
        from .telemetry import get_request_id

        headers = {
            "X-Request-ID": get_request_id(),
            "X-Caller-Service": settings.service_name,
        }
        if path.startswith(INTERNAL_PREFIX) and not (extra or {}).get("Authorization"):
            headers["Authorization"] = f"Bearer {create_internal_token(self.service_name)}"
        return headers | (extra or {})

    async def request(self, method: str, path: str, **kwargs) -> Any:
        # ---- Circuit breaker: chặn sớm, tiết kiệm thời gian chờ ----
        if not self.circuit.allows_request():
            logger.warning(
                "🚫 Circuit [%s] đang MỞ — từ chối %s %s (fail fast)",
                self.service_name, method, path,
            )
            raise ServiceUnavailableError(
                f"{self.service_name} tạm thời không sẵn sàng. Vui lòng thử lại sau."
            )

        client = await self._get_client()
        headers = self._headers(path, kwargs.pop("headers", None))
        last_exc: Exception | None = None
        max_attempts = (
            self.retries + 1
            if method.upper() in self.IDEMPOTENT_METHODS
            else 1        # ⭐ POST KHÔNG retry — có thể tạo trùng
        )

        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.request(method, path, headers=headers, **kwargs)

                if response.status_code >= 500:
                    # 5xx là lỗi phía server → tính vào circuit
                    self.circuit.record_failure()
                    raise ServiceUnavailableError(
                        f"{self.service_name} trả lỗi {response.status_code}"
                    )

                self.circuit.record_success()
                response.raise_for_status()
                return self._parse(response)

            except (httpx.TimeoutException, httpx.ConnectError,
                    httpx.ReadError, ServiceUnavailableError) as exc:
                last_exc = exc
                self.circuit.record_failure()
                logger.warning(
                    "⚠ %s %s %s → %s (lần %s/%s)",
                    method, self.base_url, path, type(exc).__name__,
                    attempt, max_attempts,
                )
                if attempt < max_attempts:
                    # Exponential backoff + jitter
                    # Jitter rất quan trọng: không có jitter, tất cả client
                    # retry CÙNG LÚC tạo ra "thundering herd" làm hệ thống
                    # phụ thuộc sập nặng hơn.
                    delay = (0.1 * (2 ** (attempt - 1))) + (uuid.uuid4().int % 100) / 1000
                    await asyncio.sleep(delay)

            except httpx.HTTPStatusError as exc:
                # 4xx là lỗi logic, KHÔNG phải lỗi hệ thống → không tính circuit
                if exc.response.status_code == 404:
                    raise NotFoundError(
                        f"Không tìm thấy: {self.service_name}{path}"
                    ) from exc
                if exc.response.status_code in (401, 403):
                    raise ServiceUnavailableError(
                        f"{self.service_name} từ chối xác thực — kiểm tra token nội bộ"
                    ) from exc
                self.circuit.record_success()
                raise

        raise ServiceUnavailableError(
            f"Không gọi được {self.service_name} sau {max_attempts} lần: {last_exc}"
        ) from last_exc

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # ---- Phương thức tiện ích ----
    async def get(self, path: str, **kwargs) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> Any:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> Any:
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs) -> Any:
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> Any:
        return await self.request("DELETE", path, **kwargs)

    async def health(self) -> bool:
        """Kiểm tra nhanh service đích còn sống không (không qua circuit)."""
        try:
            client = await self._get_client()
            r = await client.get("/health", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ---------------------------------------------------------------------------
#  Registry client + FastAPI dependency
# ---------------------------------------------------------------------------
_clients: dict[str, ServiceClient] = {}


def get_http_client(service_name: str) -> ServiceClient:
    """
    Lấy (hoặc tạo) client cho 1 service.

    Dùng:  await get_http_client("room").get("/rooms/123")
    """
    if service_name in _clients:
        return _clients[service_name]

    urls = {
        "auth": settings.auth_service_url,
        "room": settings.room_service_url,
        "tenant": settings.tenant_service_url,
        "contract": settings.contract_service_url,
        "billing": settings.billing_service_url,
        "notification": settings.notification_service_url,
        "maintenance": settings.maintenance_service_url,
        "report": settings.report_service_url,
    }
    if service_name not in urls:
        raise ValueError(
            f"Không biết service '{service_name}'. "
            f"Các service hợp lệ: {sorted(urls)}"
        )

    _clients[service_name] = ServiceClient(urls[service_name], service_name)
    return _clients[service_name]


async def close_all_clients() -> None:
    for client in _clients.values():
        await client.close()
    _clients.clear()


def circuit_stats() -> dict:
    return {name: c.circuit.stats() for name, c in _clients.items()}
