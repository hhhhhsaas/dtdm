"""
Cấu hình ứng dụng — đọc từ biến môi trường & Docker Secrets.

3 nguyên tắc quan trọng:
  1. BÍ MẬT phải đọc từ file secret, KHÔNG nằm trong biến môi trường
     (biến môi trường lộ ra qua `docker inspect`, /proc/<pid>/environ, log).
  2. KHÔNG có giá trị mặc định cho bí mật → thiếu thì service KHÔNG KHỞI ĐỘNG
     (fail fast, an toàn hơn là chạy được với mật khẩu yếu).
  3. KHÔNG BAO GIỜ log giá trị bí mật, chỉ log 4 ký tự cuối để đối chiếu.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRETS_DIR = Path("/run/secrets")
LOCAL_SECRETS_DIR = Path(__file__).parent.parent.parent / "secrets"


# ---------------------------------------------------------------------------
#  Đọc Docker Secret (ưu tiên) — fallback sang file local khi dev
# ---------------------------------------------------------------------------
def read_secret(name: str) -> str | None:
    """
    Đọc bí mật theo thứ tự ưu tiên:
      1. /run/secrets/<name>   (Docker Secrets — chuẩn production)
      2. ./secrets/<name>      (chạy local)
      3. biến môi trường       (chỉ dùng cho CI)

    ⚠️ Docker Compose (không phải Swarm) mount secret theo TÊN KEY của compose
    (vd /run/secrets/jwt_secret), còn file nguồn thường có đuôi .txt
    (./secrets/jwt_secret.txt). Thử CẢ HAI tên để không phụ thuộc quy ước.
    """
    candidates = sorted({name, name + ".txt"}) if not name.endswith(".txt") \
        else sorted({name, name[: -4]})
    for base in (SECRETS_DIR, LOCAL_SECRETS_DIR):
        for cand in candidates:
            path = base / cand
            if path.is_file():
                try:
                    value = path.read_text(encoding="utf-8").strip()
                    if value:
                        return value
                except OSError:
                    continue
    return os.getenv(name.upper().replace(".", "_"))


class Settings(BaseSettings):
    """Cấu hình chung — nạp một lần, dùng lại toàn hệ thống."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- Định danh service ----------------
    service_name: str = Field(default="unknown-service")
    port: int = Field(default=8000, ge=1, le=65535)
    environment: Literal["dev", "staging", "prod"] = "prod"
    log_level: str = "INFO"

    # ---------------- Cơ sở dữ liệu ----------------
    database_url: str = Field(
        default="",
        description="postgresql+asyncpg://user:pass@host:5432/db — BẮT BUỘC",
    )
    db_name: str = ""
    sql_pool_size: int = Field(default=10, ge=1, le=100)
    sql_max_overflow: int = Field(default=10, ge=0, le=100)
    sql_pool_timeout: int = Field(default=30, ge=1)
    sql_echo: bool = False          # chỉ bật khi debug, rất tốn tài nguyên

    # ---------------- Redis ----------------
    redis_url: str = ""

    # ---------------- Message broker ----------------
    rabbitmq_url: str = ""
    rabbitmq_prefetch: int = Field(default=10, ge=1, le=500)
    outbox_poll_interval: int = Field(default=5, ge=1, le=300)

    # ---------------- Bảo mật ----------------
    jwt_secret: SecretStr = Field(
        default=SecretStr(read_secret("jwt_secret.txt") or ""),
        min_length=32,
        description="KHÔNG ĐƯỢC ĐỂ TRỐNG — tối thiểu 32 ký tự",
    )
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "qlpt-auth-service"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=365)
    # ⭐ KHÔNG có `api_key_internal` ở đây. Xác thực service-to-service đã
    #   do JWT role=SYSTEM đảm nhiệm (xem `security.create_internal_token`).
    #   Một khoá dùng chung mà không có nơi nào kiểm tra là "bảo mật trên
    #   giấy" — dễ khiến người đọc tin rằng đã có lớp bảo vệ thứ hai.

    # ---------------- CORS ----------------
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # ---------------- URL service khác ----------------
    auth_service_url: str = "http://auth:8001"
    room_service_url: str = "http://room:8002"
    tenant_service_url: str = "http://tenant:8003"
    contract_service_url: str = "http://contract:8004"
    billing_service_url: str = "http://billing:8005"
    notification_service_url: str = "http://notification:8006"
    maintenance_service_url: str = "http://maintenance:8007"
    report_service_url: str = "http://report:8008"

    # ---------------- Giới hạn & circuit breaker ----------------
    downstream_connect_timeout: float = 1.0
    downstream_read_timeout: float = 0.8      # p95 nội bộ = 300ms → 800ms là hợp lý
    downstream_max_retries: int = 1
    circuit_failure_threshold: int = Field(default=20, ge=1)
    circuit_open_duration: int = Field(default=30, ge=5)

    # ---------------- Nghiệp vụ ----------------
    default_timezone: str = "Asia/Ho_Chi_Minh"
    default_currency: str = "VND"
    notification_dry_run: bool = True        # an toàn khi demo
    run_scheduler: bool = False              # bật job nền trong chính service này

    # ---------------- Tham số job định kỳ (container `scheduler`) -----------
    #: Số ngày ân hạn trước khi hóa đơn bị đánh dấu QUÁ HẠN. 3 ngày = người
    #: thuê có cơ hội báo "em chuyển khoản sau" mà vẫn chưa bị ghi nợ.
    invoice_overdue_grace_days: int = Field(default=3, ge=0, le=31)
    #: Cửa sổ nhìn trước cho cảnh báo hợp đồng sắp hết hạn. Hợp đồng chỉ
    #: phát cảnh báo ở các mốc T-30 / T-7 / T-1 (xem contract-service), nên
    #: giá trị này chỉ quyết định "quét bao xa", không nhân bản thông báo.
    contract_expiring_lookahead_days: int = Field(default=30, ge=1, le=180)
    #: Số giây chờ các service nghiệp vụ `/health` trước khi bắt đầu chạy
    #: job (compose khởi động song song, không hứa thứ tự nào với cả stack).
    scheduler_startup_wait: int = Field(default=180, ge=0, le=900)

    # ---------------- SMTP (notification-service) ----------------
    # Không có mặc định cho user/password: thiếu thì service chỉ ghi log,
    # không gửi được. Đây là cấu hình KHÔNG bí mật nghiêm ngặt nhưng vẫn
    # nên lấy từ secret khi triển khai thật (app password của Gmail).
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: SecretStr = Field(default=SecretStr(""))
    smtp_use_tls: bool = True                # STARTTLS (port 587). 465 = TLS trực tiếp
    smtp_timeout: float = Field(default=10.0, gt=0, le=60)

    #: Số lần thử lại trước khi đánh dấu FAILED. 3 là đủ cho lỗi mạng
    #: thoáng qua; lỗi sai địa chỉ email thì thử 100 lần cũng vô ích.
    notification_max_attempts: int = Field(default=3, ge=1, le=10)
    #: Chu kỳ quét hàng đợi gửi (giây)
    notification_dispatch_interval: int = Field(default=15, ge=1, le=3600)

    # ---------------- MinIO ----------------
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = ""
    minio_secret_key: SecretStr = Field(default=SecretStr(""))
    minio_bucket: str = "qlpt-media"
    minio_secure: bool = False

    @field_validator("database_url")
    @classmethod
    def _require_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "DATABASE_URL chưa được đặt. "
                "Service KHÔNG được khởi động khi thiếu cấu hình cơ sở dữ liệu."
            )
        return v

    @model_validator(mode="after")
    def _inject_db_password(self) -> "Settings":
        """Chèn mật khẩu Postgres từ Docker Secret vào DATABASE_URL nếu thiếu.

        ⭐ VÌ SAO CẦN: compose CỐ Ý không đặt mật khẩu trong DATABASE_URL
        (nguyên tắc #1 — bí mật không nằm trong biến môi trường). Nhưng
        PostgreSQL yêu cầu `scram-sha-256` cho kết nối TCP từ container khác
        (pg_hba: `host all all all scram-sha-256`), nên URL BẮT BUỘC phải có
        mật khẩu. Ta lấy mật khẩu từ secret `db_password.txt` và chèn vào URL
        tại đây — giá trị này KHÔNG xuất hiện dạng thô trong env/compose.

        Dạng URL vào : `postgresql+asyncpg://qlpt@postgres:5432/db_auth`
        Dạng URL ra  : `postgresql+asyncpg://qlpt:<secret>@postgres:5432/db_auth`
        """
        url = self.database_url
        if not url or "://" not in url or "@" not in url:
            return self
        scheme, rest = url.split("://", 1)
        creds, hostpart = rest.split("@", 1)
        if ":" in creds:            # URL đã có mật khẩu (vd test) → không đụng
            return self
        pwd = read_secret("db_password.txt")
        if not pwd:
            return self             # không có secret → giữ nguyên, để lỗi rõ ở tầng kết nối
        self.database_url = f"{scheme}://{creds}:{quote(pwd, safe='')}@{hostpart}"
        return self

    @field_validator("jwt_secret")
    @classmethod
    def _require_strong_jwt_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError(
                "JWT_SECRET phải dài tối thiểu 32 ký tự. "
                "Chạy 'make secrets' để sinh bí mật an toàn."
            )
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def docs_enabled(self) -> bool:
        """Tắt Swagger ở production để không lộ cấu trúc API ra Internet."""
        return not self.is_production

    @property
    def smtp_configured(self) -> bool:
        """Đủ cấu hình để gửi email thật chưa?"""
        return bool(self.smtp_host and self.smtp_user
                    and self.smtp_password.get_secret_value())

    def safe_summary(self) -> dict:
        """Tóm tắt cấu hình ĐỂ ĐƯỢC LOG — tuyệt đối không chứa bí mật."""
        return {
            "service": self.service_name,
            "port": self.port,
            "env": self.environment,
            "database": self.database_url.rsplit("@", 1)[-1] if "@" in self.database_url else "N/A",
            "jwt_secret": "***" + self.jwt_secret.get_secret_value()[-4:],
            "redis": bool(self.redis_url),
            "rabbitmq": bool(self.rabbitmq_url),
            "smtp": self.smtp_configured,
            "notification_dry_run": self.notification_dry_run,
        }


@lru_cache
def get_settings() -> Settings:
    """Cache 1 instance duy nhất (Settings là bất biến trong vòng đời process)."""
    return Settings()


settings = get_settings()
