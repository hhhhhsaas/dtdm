"""
Helper truy vấn dùng chung: phân trang, sắp xếp, khoá phân tán.

Bỏ file này, mỗi service sẽ phải viết lại cùng một đoạn `count()` + `offset()`
+ `ORDER BY` → 8 bản sao, 8 chỗ dễ sai. Đặt ở `common` vì đây là hạ tầng
truy vấn, không phải nghiệp vụ.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any, Literal, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import PageMeta, PageParams

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT")


async def paginate(
    session: AsyncSession,
    stmt: Select,
    params: PageParams,
    *,
    order_by: Sequence[Any] | None = None,
) -> tuple[list[Any], PageMeta]:
    """
    Chạy 1 truy vấn có phân trang và trả về `(items, meta)`.

    Hai câu SQL thay vì một:
        SELECT count(*) FROM (stmt)      → tổng số bản ghi
        SELECT * FROM (stmt) LIMIT/OFFSET → trang hiện tại

    ⭐ Vì sao không dùng `count(*) OVER()`?
        Window function phải chạy TRÊN TOÀN BỘ tập kết quả trước khi cắt trang →
        vẫn phải scan toàn bảng. Tách thành 2 câu cho phép Postgres dùng
        index cho `LIMIT/OFFSET`. Với bảng chỉ vài nghìn dòng thì không thấy
        khác biệt, nhưng khi bảng `meter_readings` lên tới triệu dòng thì
        khác biệt là vài giây.

    ⚠️  OFFSET không ổn định khi có dữ liệu mới chèn (dòng bị lệch vị trí →
        trang 2 có thể lặp/mất dòng của trang 1). Chấp nhận được cho API
        admin dùng để duyệt danh sách; với danh sách cần phân trang ổn định
        thì dùng keyset pagination (`WHERE (created_at, id) < (:ts, :id)`).
    """
    # `stmt` thường đã có `ORDER BY` do caller truyền vào; count bọc subquery
    # để không mất thứ tự (thứ tự không ảnh hưởng count nhưng tránh cảnh báo).
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    if order_by:
        stmt = stmt.order_by(*order_by)
    stmt = stmt.offset(params.offset).limit(params.page_size)

    rows = (await session.execute(stmt)).scalars().all()
    return list(rows), PageMeta.build(total, params.page, params.page_size)


def apply_sort(
    stmt: Select,
    model: type,
    sort: str | None,
    allowed: dict[str, str],
    default: str | None = None,
) -> Select:
    """
    Áp `?sort=field_asc|field_desc` nhưng CHỈ cho phép cột trong `allowed`.

    ⭐ Không bao giờ `getattr(model, sort)` với giá trị do client gửi:
       đó là SQL injection qua tên cột (`?sort=password_hash` → lộ dữ liệu,
       `?sort=; DROP TABLE` nếu ai đó nối chuỗi). Allowlist là bắt buộc.
    """
    if not sort:
        return stmt.order_by(*[getattr(model, c) for c in _split(allowed, default)])

    direction: Literal["asc", "desc"] = "desc"
    field = sort
    if "_" in sort:
        maybe_field, maybe_dir = sort.rsplit("_", 1)
        if maybe_dir in ("asc", "desc") and maybe_field in allowed:
            field, direction = maybe_field, maybe_dir

    column_name = allowed.get(field)
    if column_name is None:
        logger.warning("Bỏ qua sort không hợp lệ: %s", sort)
        return stmt.order_by(*[getattr(model, c) for c in _split(allowed, default)])

    column = getattr(model, column_name)
    return stmt.order_by(column.desc() if direction == "desc" else column.asc())


def _split(allowed: dict[str, str], default: str | None) -> list[str]:
    if default:
        return [c.strip() for c in default.split(",") if c.strip() in allowed.values()]
    return list(allowed.values())[:1]


# ---------------------------------------------------------------------------
#  Khoá phân tán (Redis) — chống job chạy trùng khi chạy nhiều replica
# ---------------------------------------------------------------------------
_LOCK_TTL_SECONDS = 300


async def acquire_lock(redis: Any, name: str, owner: str,
                       ttl: int = _LOCK_TTL_SECONDS) -> bool:
    """
    Thử giành khoá độc quyền trong Redis bằng `SET NX EX`.

    ⭐ Đây là câu trả lời cho "scheduler chạy thế nào khi có 3 replica?".
       Mỗi replica đều thử `SET lock NX`; chỉ MỘT thắng → những cái còn lại
       bỏ qua vòng lượt này. Không cần chọn "leader" phức tạp.

    `owner` được ghi kèm để `release_lock` chỉ xoá được khoá của chính mình —
       nếu job chạy lâu hơn TTL và replica khác đã giành khoá, thì khi ta
       kết thúc KHÔNG được xoá nhầm khoá của người khác.
    """
    if redis is None:
        return True          # không có Redis thì chấp nhận chạy (dev)
    try:
        return bool(await redis.set(f"lock:{name}", owner, nx=True, ex=ttl))
    except Exception as exc:
        logger.warning("Không giành được lock %s (%s) — coi như có", name, exc)
        return True


async def release_lock(redis: Any, name: str, owner: str) -> None:
    """Thả khoá, nhưng chỉ khi `owner` khớp (xem giải thích ở `acquire_lock`)."""
    if redis is None:
        return
    try:
        current = await redis.get(f"lock:{name}")
        if current == owner:
            await redis.delete(f"lock:{name}")
    except Exception as exc:
        logger.warning("Không thả được lock %s: %s", name, exc)


# ---------------------------------------------------------------------------
#  Sinh mã số nghiệp vụ
# ---------------------------------------------------------------------------
async def next_sequence(
    session: AsyncSession,
    table: str,
    column: str,
    scope_where: str,
    scope_params: dict,
    *,
    gap: int = 1,
) -> int:
    """
    Sinh số thứ tự tiếp theo trong phạm vi (VD: mã hóa đơn theo tháng).

    Cách này dùng `SELECT max(...) ... FOR UPDATE` trên bản ghi hiện có.
    Rủi ro tranh chấp ở mức 1 hàng/khoá là chấp nhận được cho bài toán này
    (vài trăm hóa đơn/kỳ). Nếu lên tới hàng nghìn giao dịch/giây thì phải
    chuyển sang PostgreSQL SEQUENCE hoặc bảng đếm riêng theo shard.
    """
    sql = f"""
        SELECT COALESCE(MAX({column}), 0) + :gap
        FROM {table}
        WHERE {scope_where}
        FOR UPDATE
    """
    value = (await session.execute(sql, {"gap": gap, **scope_params})).scalar()
    return int(value or gap)


def new_correlation_id() -> str:
    """Mã truy vết 1 luồng nghiệp vụ xuyên qua nhiều service."""
    return str(uuid.uuid4())
