"""
Kết nối cơ sở dữ liệu — SQLAlchemy 2.0 async + asyncpg.

Vì sao async?
  FastAPI là framework bất đồng bộ. Nếu dùng driver đồng bộ (psycopg2),
  mỗi truy vấn sẽ CHẶN cả event loop → chỉ xử lý được 1 request tại một thời điểm
  → tài nguyên phí tổn. Driver async cho phép 1 process phục vụ hàng trăm
  kết nối đồng thời chỉ với 1 thread.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from enum import Enum

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from .config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Lớp cơ sở cho tất cả model SQLAlchemy.

    Mỗi service định nghĩa model RIÊNG trên lớp cơ sở này.
    Không có quan hệ ORM giữa model của các service khác nhau.
    """

    def to_dict(self, exclude: set[str] | None = None) -> dict:
        """Chuyển model thành dict để trả về JSON."""
        exclude = exclude or set()
        return {
            col.name: getattr(self, col.name)
            for col in self.__table__.columns
            if col.name not in exclude
        }


# ---------------------------------------------------------------------------
#  Tạo engine
# ---------------------------------------------------------------------------
def _build_engine() -> AsyncEngine:
    kwargs: dict = {
        "echo": settings.sql_echo,
        "pool_pre_ping": True,        # ⭐ quan trọng: dò kết nối chết trước khi dùng
        "pool_size": settings.sql_pool_size,
        "max_overflow": settings.sql_max_overflow,
        "pool_timeout": settings.sql_pool_timeout,
        "pool_recycle": 1800,          # định kỳ hóa kết nối (30 phút)
        "connect_args": {
            "server_settings": {
                "application_name": settings.service_name,
                "timezone": "Asia/Ho_Chi_Minh",
                # ⭐ Giới hạn thời gian truy vấn: tránh 1 truy vấn chậm
                #   chiếm connection pool và kéo sập cả service.
                "statement_timeout": "30000",      # 30s
                "lock_timeout": "10000",          # 10s chờ khóa
                "idle_in_transaction_session_timeout": "60000",
            }
        },
    }

    # Trong test dùng SQLite in-memory → không hỗ trợ pool cố định
    if settings.database_url.startswith("sqlite"):
        kwargs.pop("pool_size", None)
        kwargs.pop("max_overflow", None)
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {}

    return create_async_engine(settings.database_url, **kwargs)


engine: AsyncEngine = _build_engine()

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # ⭐ quan trọng: tránh lỗi "object detached"
                             #    khi trả object ra khỏi scope sau commit
    autoflush=False,
)


# ---------------------------------------------------------------------------
#  Dependency injection
# ---------------------------------------------------------------------------
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Mỗi HTTP request = 1 transaction DB.

    Pattern quan trọng: commit/rollback ở đây, KHÔNG ở trong business logic.
    Điều này đảm bảo "một request = một đơn vị nguyên tử", tránh trạng thái
    nửa vời khi có lỗi giữa chừng.
    """
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Alias cho get_session — dùng khi cần tên rõ nghĩa hơn."""
    async for session in get_session():
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """
    Dùng cho background job / consumer (ngoài phạm vi HTTP request).

        async with session_scope() as s:
            s.add(...)
    """
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ---------------------------------------------------------------------------
#  Khởi tạo schema
# ---------------------------------------------------------------------------
async def create_tables() -> None:
    """
    Tạo bảng từ model (dùng cho dev/demo nhanh).

    ⚠️  TRONG THỰC TẾ phải dùng Alembic migration, KHÔNG dùng create_all().
        create_all() KHÔNG sửa bảng đã tồn tại — thêm cột mới sẽ không có tác dụng.
        Hãy chạy: alembic revision --autogenerate -m "add x" && alembic upgrade head
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def init_db() -> None:
    logger.info("Khởi tạo CSDL: %s", settings.db_name or settings.database_url.rsplit("/", 1)[-1])


async def dispose_db() -> None:
    """Đóng mọi connection — gọi khi container chuẩn bị dừng."""
    await engine.dispose()
    logger.info("Đã đóng toàn bộ kết nối CSDL")


# ---------------------------------------------------------------------------
#  Health check
# ---------------------------------------------------------------------------
class DatabaseHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


async def health_check_db() -> tuple[DatabaseHealth, float, str]:
    """
    Kiểm tra CSDL có sẵn sàng không. Trả về (trạng thái, độ trễ ms, chi tiết).

    Timeout cứng 3 giây: health check phải nhanh, nếu DB treo thì để timeout
    thành lỗi ngay thay vì chờ.
    """
    from sqlalchemy import text as sql_text
    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await asyncio_wait_for(
                conn.execute(sql_text("SELECT 1")), timeout=3.0
            )
        elapsed_ms = (time.perf_counter() - start) * 1000

        if elapsed_ms > 500:
            return DatabaseHealth.DEGRADED, elapsed_ms, f"Phản hồi chậm: {elapsed_ms:.0f}ms"
        return DatabaseHealth.HEALTHY, elapsed_ms, f"{elapsed_ms:.1f}ms"

    except TimeoutError:
        return DatabaseHealth.UNHEALTHY, 3000.0, "Timeout sau 3s"
    except Exception as exc:
        return DatabaseHealth.UNHEALTHY, 0.0, f"{type(exc).__name__}: {exc}"


async def asyncio_wait_for(coro, timeout: float):
    """Bọc asyncio.wait_for — tách riêng để dễ mock trong test."""
    import asyncio
    return await asyncio.wait_for(coro, timeout=timeout)


async def get_pool_stats() -> dict:
    """Thống kê connection pool — dùng cho metrics."""
    pool = engine.pool
    return {
        "size": pool.size() if hasattr(pool, "size") else 0,
        "checked_in": pool.checkedin() if hasattr(pool, "checkedin") else 0,
        "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else 0,
        "overflow": pool.overflow() if hasattr(pool, "overflow") else 0,
    }
