"""
Schema Pydantic DÙNG CHUNG cho mọi service.

Đây là *hợp đồng API*, không phải nghiệp vụ — nên thuộc về `common`:
  - Cùng một cấu trúc phân trang ở cả 8 service → client viết 1 hàm xử lý
  - Cùng một dạng lỗi → frontend/curl script không cần đoán
  - Cùng một kiểu `MessageResponse` → không lặp 8 lần

Ngược lại, entity nghiệp vụ (Room, Invoice, Contract...) TUYỆT ĐỐI không
được đặt ở đây — xem docstring `common/__init__.py`.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
#  Câu trả lời đơn giản
# ---------------------------------------------------------------------------
class MessageResponse(BaseModel):
    """Trả về khi thao tác thành công nhưng không có dữ liệu phức tạp."""

    message: str
    success: bool = True


class MessageListResponse(MessageResponse):
    """Kết quả của một lô thao tác (seed, tính tiền hàng loạt, import)."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)


class IdResponse(BaseModel):
    """Chỉ cần trả về id — dùng khi client sẽ tự điều hướng."""

    id: uuid.UUID


# ---------------------------------------------------------------------------
#  Phân trang
# ---------------------------------------------------------------------------
class PageParams(BaseModel):
    """
    Tham số phân trang chuẩn.

    ⭐ Mặc định page_size=20, TỐI ĐA 100.
       Không giới hạn → client vô tình lấy 100.000 bản ghi → nuốt bộ nhớ
       PostgreSQL và làm nghẽn event loop của FastAPI. Giới hạn ở tầng API
       rẻ hơn nhiều so với giới hạn ở tầng DB.
    """

    page: int = Field(default=1, ge=1, description="Trang thứ mấy, bắt đầu từ 1")
    page_size: int = Field(default=20, ge=1, le=100, description="Số bản ghi/trang")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PageMeta(BaseModel):
    """Khối metadata đi kèm mọi danh sách có phân trang."""

    total: int = Field(description="Tổng số bản ghi khớp điều kiện lọc")
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def build(cls, total: int, page: int, page_size: int) -> PageMeta:
        # max(1, ...) để trang rỗng vẫn có total_pages = 1 thay vì 0
        # (client dễ xử lý hơn khi luôn có ít nhất 1 trang)
        return cls(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=max(1, math.ceil(total / page_size) if page_size else 1),
        )

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Lớp bọc chuẩn cho mọi danh sách.

    Đặt `items` + `meta` tách biệt (thay vì gộp phẳng vào object) để khi sau
    này thêm `sort` hay `facets` không phá vỡ client cũ.
    """

    items: list[T]
    meta: PageMeta


# ---------------------------------------------------------------------------
#  Lọc & sắp xếp
# ---------------------------------------------------------------------------
class SortOrder(str):
    ASC = "asc"
    DESC = "desc"


class DateRange(BaseModel):
    """Khoảng thời gian — dùng chung cho báo cáo và bộ lọc."""

    start: datetime | None = None
    end: datetime | None = None

    def contains(self, moment: datetime | None) -> bool:
        if moment is None:
            return self.start is None and self.end is None
        # Khoảng mở 2 đầu (`None` = không chặn) — viết bằng phép `and` thay vì
        # 2 lệnh `if ... return False`, vì cùng một kết luận và ít nhánh hơn.
        return not ((self.start and moment < self.start)
                    or (self.end and moment > self.end))


# ---------------------------------------------------------------------------
#  Tiện ích
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """Cấu trúc /health — service.py tự sinh, khai báo ở đây cho OpenAPI."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "healthy",
            "service": "room-service",
            "version": "1.0.0",
            "uptime": "3d 4h 12m",
            "components": {
                "database": {"status": "healthy", "latency_ms": 1.8, "detail": "1.8ms"},
                "redis": {"status": "healthy"},
            },
        }
    })

    status: str
    service: str
    version: str
    uptime: str
    components: dict
