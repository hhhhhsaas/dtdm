"""
=============================================================================
 scheduler — Trình chạy job định kỳ (cron) cho toàn hệ thống
=============================================================================

VAI TRÒ
-------
Container này KHÔNG chứa nghiệp vụ, không có bảng dữ liệu riêng, không mở
cổng ra ngoài. Nó làm đúng một việc: **đúng giờ** gọi các endpoint nội bộ
`/internal/v1/...` của những service khác. Toàn bộ logic nằm ở service đích —
nếu cần sửa "hợp đồng hết hạn thì chuyển trạng thái thành gì", sửa ở
contract-service, KHÔNG sửa ở đây.

DANH SÁCH JOB
-------------
    | job                       | lịch      | gọi vào                          |
    |---------------------------|-----------|----------------------------------|
    | contract-expire-due       | 02:00 hằng ngày | contract `/contracts/expire-due`     |
    | contract-notify-expiring  | 08:00 hằng ngày | contract `/contracts/notify-expiring`|
    | invoice-mark-overdue      | 08:30 hằng ngày | billing  `/invoices/mark-overdue`   |
    | report-reconcile          | mỗi 6 giờ | report  `/reports/reconcile`       |
    | report-summary-log        | 09:00 hằng ngày | report  `/reports/summary`     |

TẠI SAO CÁC MỐC GIỜ LẠI KHÁC NHAU?
------------------------------------
  - 02:00 nằm giữa đêm: người thuê ngủ, nhà trọ vắng, chuyển trạng thái
    phòng từ "đang thuê" sang "trống" diễn ra lúc ít người quan sát nhất.
  - 08:00–08:30 là giờ người thuê đã thức dậy và mở điện thoại → tin nhắc
    cảnh báo hợp đồng hết hạn và nhắc quá hạn có tỉ lệ đọc cao nhất.
  - Có 30 phút giữa hai job nhắc tiền vì cả hai đều sinh event gửi cho
    cùng một người; dồn vào một thời điểm sẽ tạo 2 tin nhắn liên tiếp.

⭐ BA NGUYÊN TẮC ĐÃ CỐ Ý GIỮ
  1. **IDEMPOTENT**: mọi endpoint đích đều an toàn khi gọi lại nhiều lần
     (điều kiện lọc luôn là "trạng thái chưa xử lý"). Nhờ vậy nếu scheduler
     chết giữa chừng, container restart là chạy lại được ngay, không cần
     cơ chế phân tích lịch (DAG, watermark…) phức tạp.
  2. **KHÔNG CẦN BIẾT NGHIỆP VỤ**: scheduler chỉ biết URL. Đổi logic nghiệp
     vụ không đụng tới file này.
  3. **FAIL LOUD, KHÔNG FAIL SILENT**: một job hỏng phải để lại dấu vết rõ
     ràng trong log + metric, vì "im lặng không chạy" là kiểu sự cố khó
     phát hiện nhất vì hệ thống vẫn trông bình thường.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import Counter, Gauge, Histogram
from redis.asyncio import Redis
from uvicorn import Config, Server

from common.clients import ServiceClient
from common.config import settings
from common.errors import DomainError
from common.repository import acquire_lock, release_lock
from common.telemetry import metrics_endpoint, setup_telemetry

logger = logging.getLogger("scheduler")

#: Định danh duy nhất của tiến trình này, dùng làm `owner` cho khoá phân tán.
INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}"
RUN_ID = uuid.uuid4().hex[:8]

#: Mốc khởi động — chỉ để in "đã chạy được bao lâu" lúc tắt.
_STARTED_AT = time.time()

#: Timeout cho MỌI lời gọi ra service khác. Lớn hơn hẳn `downstream_read_timeout`
#: (0.8s) vì đây không phải đường nóng của người dùng: chậm 30s còn hơh báo
#: động và bỏ sót việc chuyển trạng thái hợp đồng.
CALL_TIMEOUT = 30.0

#: Số lần thử lại ngoài cùng. Endpoint nội bộ đều idempotent nên thử lại an
#: toàn; nhưng KHÔNG thử vô hạn — job hỏng thật sẽ đốt cả chu kỳ ngày.
JOB_RETRIES = 2

#: Khoá Redis sống bao lâu. Phải LỚN HƠN thời gian job chạy thật, nếu không
#: replica khác sẽ giành được khoá và chạy chồng lên job đang dở.
LOCK_TTL = 900

# ---------------------------------------------------------------------------
#  Metrics riêng của scheduler
# ---------------------------------------------------------------------------
JOB_RUNS = Counter(
    "scheduler_job_runs_total",
    "Số lần chạy job định kỳ",
    ["job", "result"],          # result = success | failed | skipped | locked
)
JOB_DURATION = Histogram(
    "scheduler_job_duration_seconds",
    "Thời gian chạy 1 job (giây)",
    ["job"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)
LAST_RUN_AT = Gauge(
    "scheduler_job_last_run_timestamp",
    "Mốc thời gian Unix lần chạy THÀNH CÔNG gần nhất",
    ["job"],
)
LAST_ERROR_AT = Gauge(
    "scheduler_job_last_error_timestamp",
    "Mốc thời gian Unix lần chạy THẤT BẠI gần nhất",
    ["job"],
)
SCHEDULER_UP = Gauge(
    "scheduler_running",
    "1 = scheduler đang chạy, 0 = đã dừng",
)


# ---------------------------------------------------------------------------
#  Múi giờ
# ---------------------------------------------------------------------------
def _local_tz() -> tzinfo:
    """
    Lấy múi giờ nghiệp vụ.

    ⭐ `Asia/Ho_Chi_Minh` KHÔNG có DST (từ 1975), nên kể cả khi image thiếu
       gói `tzdata` thì rơi về UTC+7 cố định vẫn đúng 100% với mọi ngày.
       Cách này tránh trường hợp container chết vì lý thuần toán giờ — một lỗi
       rất đáng tiếc khi toàn bộ job vốn được cấu hình chạy đúng giờ.
    """
    try:
        return ZoneInfo(settings.default_timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        logger.warning(
            "Không tìm thấy tzdata cho '%s' — dùng UTC+7 cố định",
            settings.default_timezone,
        )
        return timezone(timedelta(hours=7))


#: Múi giờ dùng cho toàn bộ lịch trình.  Giải phóng biến sớm ở cấp module để
#: log lỗi ở lúc import không bị nuốt mất.
VN_TZ: tzinfo = _local_tz()


def now_local() -> datetime:
    """Thời điểm hiện tại theo giờ Việt Nam — dùng cho mọi mốc thời gian log."""
    return datetime.now(VN_TZ)


# ---------------------------------------------------------------------------
#  Redis & client gọi service
# ---------------------------------------------------------------------------
_redis: Redis | None = None


async def get_redis() -> Redis | None:
    """
    Mở kết nối Redis (lazy) để dùng làm khoá phân tán.

    Trả `None` nếu `REDIS_URL` rỗng: khi đó `acquire_lock` coi như có khoá và
    cho job chạy. Đây là cơ chế chấp nhận được vì scheduler vốn đã chạy
    đúng 1 bản; khoá chỉ là lưới an toàn, không phải điều kiện để chạy.
    """
    global _redis
    if _redis is None and settings.redis_url:
        _redis = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        logger.info("🔗 Đã mở kết nối Redis (dùng cho khoá phân tán)")
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


#: Cache client theo tên service — tự tạo vì client trong registry dùng
#: timeout 0.8s, quá ngắn cho job chạy nền (xem `ServiceClient.__init__`).
_clients: dict[str, ServiceClient] = {}


def client_for(name: str) -> ServiceClient:
    if name not in _clients:
        urls = {
            "contract": settings.contract_service_url,
            "billing": settings.billing_service_url,
            "report": settings.report_service_url,
        }
        if name not in urls:
            raise ValueError(f"Scheduler không gọi service '{name}'")
        _clients[name] = ServiceClient(
            urls[name], name, timeout=CALL_TIMEOUT, retries=0,
        )
        logger.info("🔌 Client nội bộ → %s (%s)", name, urls[name])
    return _clients[name]


async def close_clients() -> None:
    for c in _clients.values():
        await c.close()
    _clients.clear()


# ---------------------------------------------------------------------------
#  Các job — mỗi job chỉ là MỘT lời gọi HTTP
# ---------------------------------------------------------------------------
async def job_contract_expire_due() -> dict:
    """
    Hợp đồng hết hạn mà vẫn `ACTIVE` → `EXPIRED`, phongỏa trả về trống.

    Chạy lúc **02:00** vì đây là lúc người thuê đi làm về/ký sáng mai: phòng
    trống nhưng người thuê chưa kịp dọn, chủ vẫn có thể vào xem phòng. Gọi
    chiềm tối sẽ báo phòng trống khi người thuê còn đang ở trong.
    """
    return await client_for("contract").post("/internal/v1/contracts/expire-due")


async def job_contract_notify_expiring() -> dict:
    """
    Nhắc người thuê khi hợp đồng sắp hết hạn (T-30 / T-7 / T-1).

    Chạy lúc **08:00** — giờ người thuê đã thức dậy. Nhắc lúc 02:00 thì tin
    nhắn sẽ nằm im lặng dưới 15 tin khác của đêm.
    """
    return await client_for("contract").post(
        f"/internal/v1/contracts/notify-expiring?days={settings.contract_expiring_lookahead_days}"
    )


async def job_invoice_mark_overdue() -> dict:
    """
    Hóa đơn quá hạn vượt mốc ân hạn → `OVERDUE` + phát event nhắc khách.

    Chạy lúc **08:30**, cố ý lệch 30 phút so với nhắc hợp đồng: hai tin
    nhắn dồn vào cùng một giờ dễ bị người dùng bỏ qua cả hai.
    """
    return await client_for("billing").post(
        f"/internal/v1/invoices/mark-overdue?grace_days={settings.invoice_overdue_grace_days}"
    )


async def job_report_reconcile() -> dict:
    """
    Đối chiếu read model báo cáo với dữ liệu gốc.

    Chạy mỗi **6 giờ** thay vì 1 lần/ngày: đối chiếu là cơ chế tự chữa
    lành khi consumer bỏ sót event (nhân bản thêm report-service, deploy
    đang chạy, broker restart…). Chạy 6 giờ một lần thì sai số hiển thị trên
    dashboard không bao giờ kéo dài quá 6 giờ.
    """
    return await client_for("report").post("/internal/v1/reports/reconcile")


async def job_report_summary() -> dict:
    """
    Ghi 1 dòng tổng kết trong log mỗi sáng.

    Nhỏ nhưng giá trị bất ngờ: khi có người hỏi "tháng này thu được bao nhiêu,
    còn nợ bao nhiêu", 1 dòng log trả lời được ngay mà không cần mở Grafana
    hay đăng nhập hệ thống.
    """
    return await client_for("report").get("/internal/v1/reports/summary")


# ---------------------------------------------------------------------------
#  Định nghĩa lịch
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class JobSpec:
    """Một job: tên, lịch chạy, hàm thực thi, và mô tả để hiện ra log."""

    name: str
    trigger: CronTrigger
    run: Callable[[], Awaitable[dict]]
    description: str
    #: TTL khoá phân tán (giây) — phải > thời gian chạy thật.
    lock_ttl: int = LOCK_TTL
    #: Số lần thử lại ngoài cùng (0 = không thử lại).
    retries: int = JOB_RETRIES
    #: Chạy bù 1 lần ngay khi scheduler khởi động. CHỈ bật cho job idempotent
    #: và không gửi tin nhắn (chạy bù job nhắc nợ = người thuê nhận tin 2 lần).
    catch_up: bool = False

    @property
    def lock_name(self) -> str:
        return f"job:{self.name}"


def build_jobs() -> list[JobSpec]:
    """
    Khai báo toàn bộ lịch trình.

    Mốc giờ KHÔNG dùng `0 2 * * *` mà dùng kwargs rõ nghĩa (`hour=2, minute=0`)
    vì đọc `docker logs` phải hiểu được ngay là 02:00 chứ không phải 2 giờ
    lẻ. Cũng tránh lỗi hiểu nhầm "0 = chạy liên tục" của cron.
    """
    return [
        JobSpec(
            name="contract-expire-due",
            trigger=CronTrigger(hour=2, minute=0, timezone=VN_TZ),
            run=job_contract_expire_due,
            description="Chuyển HĐ hết hạn → EXPIRED, trả phòng về trống",
            # ⭐ Máy demo/VM thường TẮT lúc 02:00 → job lỡ hẹn quá 1 giờ thì
            #    APScheduler bỏ qua hẳn, hợp đồng hết hạn vẫn ACTIVE nhiều ngày
            #    (dữ liệu thật: HDMB-2026-001 hết hạn 15/10 vẫn ACTIVE ngày 20/10).
            catch_up=True,
        ),
        JobSpec(
            name="contract-notify-expiring",
            trigger=CronTrigger(hour=8, minute=0, timezone=VN_TZ),
            run=job_contract_notify_expiring,
            description="Nhắc người thuê khi HĐ sắp hết hạn (T-30/T-7/T-1)",
        ),
        JobSpec(
            name="invoice-mark-overdue",
            trigger=CronTrigger(hour=8, minute=30, timezone=VN_TZ),
            run=job_invoice_mark_overdue,
            description="Đánh dấu hóa đơn quá hạn, phát tin nhắc nhắc nợ",
        ),
        JobSpec(
            name="report-reconcile",
            # Mỗi 6 giờ: 00:00, 06:00, 12:00, 18:00
            trigger=CronTrigger(hour="*/6", minute=5, timezone=VN_TZ),
            run=job_report_reconcile,
            description="Đối chiếu read model báo cáo với dữ liệu gốc",
            # Đối chiếu là job nặng nhất (quét cả 8 DB) — khoá sống lâu hơn để
            # không bị replica khác cướp mất khi job vẫn đang chạy.
            lock_ttl=1800,
            catch_up=True,      # chỉ đọc + ghi read model, không gửi tin
        ),
        JobSpec(
            name="report-summary-log",
            trigger=CronTrigger(hour=9, minute=0, timezone=VN_TZ),
            run=job_report_summary,
            description="Ghi 1 dòng tổng kết doanh thu/nợ phải thu ra log",
            # Job chỉ đọc, chạy nhanh → khoá ngắn là đủ.
            lock_ttl=120,
            retries=1,
        ),
    ]


# ---------------------------------------------------------------------------
#  Thực thi job: khoá phân tán → thử lại → ghi log & metric
# ---------------------------------------------------------------------------
#: Chặn trên cùng cho cả 1 lần chạy job (kể cả các lần thử lại). Nếu để
#: mở, một job gọi mãi vào service đang treo sẽ giữ coroutine sống vô hạn
#: và chặn mọi job khác — cùng một bệnh như "dịch vụ treo, chỉ cần KHÔNG sập".
HARD_TIMEOUT = 300.0

#: Thời gian chờ giữa 2 lần thử lại. Cộng thêm jitter ngẫu nhiên để khi cả
#: N replica cùng thử lại sau một sự cố chung, chúng không dồn lời gọi vào
#: đúng một mili-giây (thundering herd) và làm service phụ thuộc nặng hơn.
RETRY_BACKOFF = 5.0


async def run_job(spec: JobSpec) -> dict | None:
    """
    Chạy 1 job theo đúng thứ tự: **khoá → thử lại → ghi log → đo**.

    Trả về payload của endpoint đích, hoặc `None` nếu bản khác đang giữ khoá
    (trường hợp bình thường khi chạy nhiều bản, KHÔNG phải lỗi).

    ⭐ Vì sao khoá lấy TRƯỚC rồi mới thử lại?
        Vì nếu thử lại xong mới khoá, giữa các lần thử sẽ có khoảng thời
        gian không ai giữ khoá → 2 bản chạy cùng một job cùng lúc.
    """
    redis = await get_redis()
    owner = f"{INSTANCE_ID}/{RUN_ID}/{spec.name}"

    if not await acquire_lock(redis, spec.lock_name, owner, ttl=spec.lock_ttl):
        logger.info("⏭  Bỏ qua job %s — bản khác đang giữ khoá", spec.name)
        JOB_RUNS.labels(job=spec.name, result="locked").inc()
        return None

    started = time.perf_counter()
    try:
        async def _attempt() -> dict:
            return await asyncio.wait_for(spec.run(), timeout=HARD_TIMEOUT)

        try:
            result = await _with_retry(spec, _attempt)
        except Exception as exc:                     # job phải sống sót
            duration = time.perf_counter() - started
            JOB_RUNS.labels(job=spec.name, result="failed").inc()
            JOB_DURATION.labels(job=spec.name).observe(duration)
            LAST_ERROR_AT.labels(job=spec.name).set(time.time())
            logger.error(
                "❌ Job %s THẤT BẠI sau %.1fs: %s: %s",
                spec.name, duration, type(exc).__name__, exc,
            )
            return None

        duration = time.perf_counter() - started
        JOB_RUNS.labels(job=spec.name, result="success").inc()
        JOB_DURATION.labels(job=spec.name).observe(duration)
        LAST_RUN_AT.labels(job=spec.name).set(time.time())
        _log_result(spec, result, duration)
        return result

    finally:
        # Phải thả khoá trong `finally`: nếu job ném exception mà không thả,
        # mọi lần chạy sau đều bị coi là "bản khác đang giữ khoá" cho tới
        # hết TTL — tức là hệ thống im lặng 15 phút sau MỘT lỗi.
        await release_lock(redis, spec.lock_name, owner)


async def _with_retry(spec: JobSpec, call: Callable[[], Awaitable[dict]]) -> dict:
    """
    Thử `call` tối đa `spec.retries + 1` lần, nghỉ luỹ thừa giữa các lần.

    An toàn vì mọi endpoint đích đều idempotent: `expire-due` chỉ chuyển
    những hợp đồng **còn** ở trạng thái ACTIVE, `mark-overdue` chỉ chuyển
    hóa đơn **còn** PENDING — gọi lại là gọi lại trên tập rỗng, không sinh
    bản ghi trùng.
    """
    last: Exception | None = None
    for attempt in range(1, spec.retries + 2):
        try:
            return await call()
        except (TimeoutError, DomainError, httpx.HTTPError) as exc:
            last = exc
            if attempt > spec.retries:
                break
            delay = RETRY_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 2)
            logger.warning(
                "⚠ Job %s lỗi lần %d/%d (%s) — thử lại sau %.1fs",
                spec.name, attempt, spec.retries + 1, type(exc).__name__, delay,
            )
            await asyncio.sleep(delay)
    assert last is not None
    raise last


def _log_result(spec: JobSpec, result: Any, duration: float) -> None:
    """
    Ghi log kết quả.

    Không in thẳng `result` vì nó có thể là danh sách hợp đồng ID dài vài
    trăm phần tử → log 1 dòng 40KB, Loki khó index, và người đọc không
    thấy thông tin quan trọng là "bao nhiêu bản ghi".
    """
    detail = ""
    if isinstance(result, dict):
        counts = {
            k: v for k, v in result.items()
            if isinstance(v, int) and not isinstance(v, bool)
        }
        detail = " ".join(f"{k}={v}" for k, v in counts.items())
    elif isinstance(result, list):
        detail = f"items={len(result)}"

    logger.info(
        "✅ Job %s xong trong %.2fs%s — %s",
        spec.name, duration, f" ({detail})" if detail else "", spec.description,
    )


# ---------------------------------------------------------------------------
#  Chờ service đích sẵn sàng
# ---------------------------------------------------------------------------
#: Khoảng cách giữa 2 lần thăm `/health`.
PROBE_INTERVAL = 3.0


async def _ping_redis() -> bool:
    redis = await get_redis()
    if redis is None:
        return False
    try:
        return bool(await redis.ping())
    except Exception as exc:
        logger.debug("Redis ping lỗi: %s", exc)
        return False


async def wait_for_services() -> dict[str, bool]:
    """
    Chờ các service đích trả lời `/health` trước khi bắt đầu chạy job.

    ⭐ `docker compose up` khởi động MỌI container SONG SONG, nên lúc
       scheduler sẵn sàng thì contract-service có thể mới vừa khởi động. Nếu
       chạy job luôn thì 3 job đầu tiên sẽ thất bại và cả ngày hôm đó không
       có ai chuyển hợp đồng hết hạn. Chờ ở đây rẻ hơn nhiều so với phải
       canh chừng thủ công.

    Hết thời gian chờ thì **vẫn chạy tiếp** (chỉ cảnh báo): scheduler chết
    vì chờ mãi là tệ hơn nhiều so với chạy rồi thất bại, khi mà cơ chế thử
    lại sẽ tự xử lý.
    """
    targets = {
        "contract": settings.contract_service_url,
        "billing": settings.billing_service_url,
        "report": settings.report_service_url,
    }
    budget = settings.scheduler_startup_wait
    if budget <= 0:
        return {n: False for n in targets}

    logger.info("⏳ Chờ tối đa %ss cho %s…", budget, ", ".join(targets))
    deadline = time.monotonic() + budget
    status: dict[str, bool] = {}

    while time.monotonic() < deadline:
        status = {
            name: await client_for(name).health() for name in targets
        }
        ready = sum(status.values())
        logger.info("   sẵn sàng %d/%d: %s", ready, len(targets), status)
        if ready == len(targets):
            logger.info("✅ Tất cả service đích đã sẵn sàng")
            return status
        await asyncio.sleep(PROBE_INTERVAL)

    missing = [n for n, ok in status.items() if not ok]
    logger.warning(
        "⚠ Hết %ss, vẫn chưa sẵn sàng: %s — vẫn khởi động, job sẽ tự thử lại",
        budget, ", ".join(missing) or "?",
    )
    return status


# ---------------------------------------------------------------------------
#  HTTP phụ trợ: /health + /metrics
# ---------------------------------------------------------------------------
#: Tham chiếu tới APScheduler của tiến trình đang chạy. Để ở cấp module
#: (thay vì truyền qua closure) để `app` có thể được tạo ngay lúc import —
#: nhờ vậy `docker exec … python -c "import main; print(main.app)"` chạy được
#: mà không cần khởi động cả scheduler.
_SCHEDULER: AsyncIOScheduler | None = None


def build_app() -> FastAPI:
    """
    App HTTP tối giản cho scheduler.

    ⭐ Tại sao cần app HTTP cho một tiến trình không làm API?
        1. Docker HEALTHCHECK gọi `/health` — không có nó thì container bị
           gắn nhãn `unhealthy` vĩnh viễn và giám sát báo động giả liên tục.
        2. Prometheus cần chỗ để cào metrics. Không có chỗ cào thì job hỏng
           là vô hình — mọi sự cố của scheduler diễn ra lúc 2h sáng, đúng
           lúc không ai nhìn log.
        3. `GET /health` trả lời "job nào sắp chạy, chạy lúc mấy giờ" mà
           không cần vào trong container.

    ⭐ `docs_url=None`: đây KHÔNG phải API nghiệp vụ, không cần và không nên
        mở Swagger — tránh lộ cấu trúc hệ thống ra ngoài.
    """
    app = FastAPI(
        title="QLPT Scheduler",
        description="Trình chạy job định kỳ — chỉ có /health và /metrics",
        docs_url=None, redoc_url=None, openapi_url=None,
    )

    @app.get("/health", tags=["ops"], summary="Trạng thái scheduler & lịch sắp chạy")
    async def health() -> dict:
        scheduler = _SCHEDULER
        running = bool(scheduler and scheduler.running)
        jobs = []
        for job in (scheduler.get_jobs() if scheduler else []):
            nxt = getattr(job, "next_run_time", None)
            jobs.append({
                "id": job.id,
                "next_run_at": (
                    nxt.astimezone(VN_TZ).isoformat(timespec="seconds")
                    if nxt is not None else None
                ),
            })
        redis_ok = await _ping_redis()
        return {
            # "degraded" khi Redis hỏng: scheduler VẪN chạy job (chỉ mất chống
            # chạy trùng), nên KHÔNG báo unhealthy — cảnh báo sai sẽ khiến
            # người vận hành restart một thứ vốn không cần restart.
            "status": (
                "healthy" if running and redis_ok
                else "degraded" if running
                else "starting"
            ),
            "service": settings.service_name,
            "instance": INSTANCE_ID,
            "scheduler_running": running,
            "timezone": str(VN_TZ),
            "now": now_local().isoformat(timespec="seconds"),
            "jobs_total": len(jobs),
            "jobs": sorted(jobs, key=lambda j: j["id"]),
            "redis": "up" if redis_ok else "down",
        }

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        return await metrics_endpoint(request)

    return app


#: App được tạo sẵn ở cấp module — xem giải thích cạnh `_SCHEDULER`.
app = build_app()


# ---------------------------------------------------------------------------
#  Khởi động / tắt êm
# ---------------------------------------------------------------------------
def _install_signal_handlers(stop: asyncio.Event) -> None:
    """
    Bắt SIGTERM (docker stop) và SIGINT (Ctrl+C) để tắt êm.

    ⭐ `loop.add_signal_handler` KHÔNG có trên Windows → bắt
       `NotImplementedError` và rơi về `signal.signal`. Nếu không có nhánh
       fallback này thì chỉ cần chạy `python main.py` trên Windows là
       crash, dù toàn bộ code còn lại hoàn toàn đa nền tảng.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError, ValueError):
            try:
                signal.signal(sig, lambda *_: stop.set())
            except (OSError, ValueError):
                logger.warning("Không cài được handler cho signal %s", sig)


def _describe_schedule(scheduler: AsyncIOScheduler) -> None:
    for job in scheduler.get_jobs():
        nxt = getattr(job, "next_run_time", None)
        when = nxt.astimezone(VN_TZ).isoformat(timespec="seconds") if nxt else "?"
        logger.info("   📅 %-28s → lần chạy kế tiếp %s", job.id, when)


async def main() -> None:
    """
    Vòng đời của tiến trình scheduler.

    Thứ tự khởi động CỐ Ý:
        telemetry → chờ service → đăng ký lịch → chạy HTTP → chờ tín hiệu dừng

    Nếu đảo thứ tự (chạy HTTP trước rồi mới chờ), sẽ có một khoảng thời gian
    `/health` báo "healthy" trong khi job vẫn chưa đăng ký xong → giám sát
    tưởng ổn nhưng thực tế chưa.
    """
    global _SCHEDULER

    setup_telemetry()
    logger.info(
        "🚀 %s khởi động | instance=%s | múi giờ=%s",
        settings.service_name, INSTANCE_ID, VN_TZ,
    )

    await wait_for_services()

    scheduler = AsyncIOScheduler(
        timezone=VN_TZ,
        job_defaults={
            # ⭐ coalesce=True: nếu container chết lúc 02:00 rồi khởi động
            #   lúc 02:30, chỉ chạy job đó MỘT LẦN thay vì bù cả chục lần.
            "coalesce": True,
            # max_instances=1: job của lần trước còn chạy thì lần sau bỏ qua
            #   (còn hơn là chồng 2 lần quét toàn bảng hợp đồng).
            "max_instances": 1,
            # Cho phép chạy bù job lỡ hẹn trong 1 giờ. Job ở đây đều idempotent
            # nên chạy bù hoàn toàn an toàn; chỉ cần giới hạn để container
            # mới khởi động không phải chạy bù cả ngày.
            "misfire_grace_time": 3600,
        },
    )
    for spec in build_jobs():
        scheduler.add_job(
            run_job,
            trigger=spec.trigger,
            args=[spec],
            id=spec.name,
            name=spec.name,
            replace_existing=True,
        )
    # Chạy bù các job đánh dấu catch_up ngay sau khi khởi động (endpoint đích
    # idempotent: chỉ đổi bản ghi CÒN cần đổi, chạy lại trên tập rỗng là no-op).
    for spec in build_jobs():
        if spec.catch_up:
            scheduler.add_job(run_job, trigger="date", args=[spec],
                              id=f"{spec.name}:catch-up", name=f"{spec.name} (chạy bù)")
    _SCHEDULER = scheduler
    scheduler.start()
    SCHEDULER_UP.set(1)
    logger.info("⏰ Đã đăng ký %d job định kỳ", len(scheduler.get_jobs()))
    _describe_schedule(scheduler)

    # --- HTTP phụ trợ chạy SONG SONG trên cùng event loop --------------------
    server = Server(Config(
        app,
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,          # /health bị Docker gọi mỗi 30s → log đầy rác
        timeout_keep_alive=30,
    ))
    http_task = asyncio.create_task(server.serve(), name="scheduler-http")
    logger.info("🌐 HTTP phụ trợ sẵn sàng trên cổng %d (/health, /metrics)", settings.port)

    # --- Chờ tín hiệu dừng --------------------------------------------------
    stop = asyncio.Event()
    _install_signal_handlers(stop)

    stop_task = asyncio.create_task(stop.wait(), name="stop-signal")
    done, _pending = await asyncio.wait(
        {stop_task, http_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    http_died = http_task in done

    # Dọn dẹp LUÔN cả 2 nhánh (dừng bằng tín hiệu, hay HTTP tự chết) — rồi mới
    # báo lỗi. Báo lỗi trước rồi thoát sẽ bỏ sót `scheduler.shutdown()`, để lại
    # job nửa chừng trong bộ nhớ.
    logger.info(
        "🛑 %s — tắt êm…",
        "HTTP phụ trợ đã dừng bất thường" if http_died else "Nhận tín hiệu dừng",
    )
    _SCHEDULER = None
    SCHEDULER_UP.set(0)

    # wait=True: chờ job đang chạy kết thúc. `docker stop` mặc định chỉ cho
    # 10 giây, nên nếu bị cắt giữa đường thì job sẽ tự thử lại ở lần chạy
    # kế tiếp — an toàn vì mọi endpoint đích đều idempotent.
    scheduler.shutdown(wait=True)
    if http_died:
        # Đã chết rồi thì không cần (và không nên) chờ thêm.
        stop_task.cancel()
    else:
        server.should_exit = True
        await http_task
        stop_task.cancel()

    await close_clients()
    await close_redis()
    logger.info("👋 Đã tắt êm — tổng thời gian chạy %.0fs", time.time() - _STARTED_AT)

    if http_died:
        # ⭐ Server HTTP chết = container vô dụng (không /health, không /metrics).
        #   Thoát với mã lỗi để `restart: unless-stopped` của Docker dựng lại,
        #   thay vì để một scheduler chạy mà không ai giám sát được.
        raise RuntimeError("HTTP server của scheduler đã dừng bất thường")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Ctrl+C ở cửa sổ terminal: signal handler đã xử lý rồi, nhưng nếu
        # Ctrl+C đến trước lúc handler cài xong thì rơi vào đây.
        logging.getLogger("scheduler").info("👋 Bị gián đoạn bởi người dùng")
