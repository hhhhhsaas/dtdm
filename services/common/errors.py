"""
Xử lý lỗi thống nhất cho toàn hệ thống.

Vì sao cần module này?
  - Client luôn nhận JSON có cùng cấu trúc → frontend viết 1 hàm xử lý lỗi duy nhất
  - Không bao giờ lộ traceback/chi tiết nội bộ ra ngoài production
  - Mỗi loại lỗi nghiệp vụ có HTTP status phù hợp
  - Mọi lỗi 5xx đều được ghi log ở mức ERROR kèm request ID
"""

from __future__ import annotations

import logging
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .telemetry import get_request_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Lỗi nghiệp vụ
# ---------------------------------------------------------------------------
class DomainError(Exception):
    """
    Lỗi nghiệp vụ — dùng để chủ động ném ra thay vì trả HTTP status từ trong logic.

    Lợi ích: business logic không phụ thuộc HTTP. Sau này chuyển service thành
    consumer gọi qua message queue, lớp DomainError vẫn dùng được nguyên vẹn.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "DOMAIN_ERROR"
    message: str = "Lỗi nghiệp vụ"

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error": {"code": self.code, "message": self.message, "details": self.details},
            "request_id": get_request_id(),
        }


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "Không tìm thấy dữ liệu"


class ValidationError_(DomainError):        # noqa: N801, N818 — cố ý giữ dấu _
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "VALIDATION_ERROR"
    message = "Dữ liệu không hợp lệ"


# Đặt tên public là `ValidationError` để service gọi đồng nhất
# (`from common import ValidationError`) — trùng với `pydantic.ValidationError`
# ở dòng trên, nên class thật phải mang dấu gạch dưới. `common/__init__.py`
# chỉ export tên đã đổi, không export `ValidationError_`.
ValidationError = ValidationError_          # noqa: F811


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "Dữ liệu xung đột với trạng thái hiện tại"


class PermissionDeniedError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "PERMISSION_DENIED"
    message = "Không có quyền thực hiện"


class UnauthorizedError(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"
    message = "Chưa xác thực"


class BusinessRuleError(DomainError):
    """
    Vi phạm quy tắc nghiệp vụ (R1–R8 trong tài liệu thiết kế).

    Dùng khi dữ liệu ĐÚNG KIỂU nhưng SAI NGHIỆP VỤ.
    Ví dụ: "không thể trừ cọc quá giá trị cọc" → BusinessRuleError
           "số phòng phải là chuỗi" → ValidationError
    """
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "BUSINESS_RULE_VIOLATION"
    message = "Vi phạm quy tắc nghiệp vụ"


class RateLimitExceeded(DomainError):         # noqa: N818 — tên nghiệp vụ rõ ràng
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    message = "Vượt quá giới hạn truy cập"


class ServiceUnavailableError(DomainError):
    """Service phụ thuộc không sẵn sàng — client nên retry với backoff."""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"
    message = "Dịch vụ tạm thời không sẵn sàng"


class DownstreamTimeout(ServiceUnavailableError):   # noqa: N818 — "timeout" là thuật ngữ chuẩn
    code = "DOWNSTREAM_TIMEOUT"
    message = "Dịch vụ phụ thuộc không phản hồi kịp"


# ---------------------------------------------------------------------------
#  Cài đặt handler
# ---------------------------------------------------------------------------
def setup_exception_handlers(app: FastAPI) -> FastAPI:
    """Đăng ký toàn bộ exception handler. Gọi 1 lần trong create_service_app()."""

    # ---- Lỗi nghiệp vụ có sẵn ----
    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        # 4xx là lỗi người dùng → WARNING. 5xx là lỗi hệ thống → ERROR.
        log = logger.warning if exc.status_code < 500 else logger.error
        log("%s | %s %s → %s",
            exc.code, request.method, request.url.path, exc.message)

        headers = {}
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            headers["Retry-After"] = "60"

        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
            headers=headers,
        )

    # ---- HTTPException của FastAPI/Starlette ----
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": f"HTTP_{exc.status_code}",
                    "message": exc.detail,
                    "details": {},
                },
                "request_id": get_request_id(),
            },
            headers=getattr(exc, "headers", None) or {},
        )

    # ---- Lỗi validate body/query của client ----
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # ⭐ Làm rõ thông báo tiếng Việt thay vì trả về thông báo mặc định của Pydantic
        fields = []
        for err in exc.errors():
            loc = [str(x) for x in err["loc"] if x not in ("body", "query", "path")]
            fields.append({
                "field": ".".join(loc) or "(body)",
                "problem": err["msg"],
                "type": err["type"],
            })

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Dữ liệu gửi lên không hợp lệ",
                    "details": {"fields": fields},
                },
                "request_id": get_request_id(),
            },
        )

    @app.exception_handler(ValidationError)
    async def _pydantic_validation(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(exc),
                    "details": {},
                },
                "request_id": get_request_id(),
            },
        )

    # ---- Lỗi ràng buộc DB ----
    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        """
        ⭐ Chuyển lỗi DB thành thông báo có ý nghĩa nghiệp vụ.

        23505 = unique_violation    23503 = foreign_key_violation
        23514 = check_violation     22001 = string_data_right_truncation
        """
        raw = str(getattr(exc, "orig", exc))
        detail = "Dữ liệu không hợp lệ"
        code = "DB_CONSTRAINT_VIOLATION"

        if "uq_contract_active_room" in raw:
            detail = "Phòng này đang có hợp đồng hiệu lực (chỉ được 1 hợp đồng/phòng)"
            code = "ROOM_ALREADY_LEASED"
        elif "ux_invoice_contract_period" in raw or "invoices_contract_id_period_key" in raw:
            detail = "Hợp đồng này đã có hóa đơn cho kỳ này (tránh tạo trùng)"
            code = "DUPLICATE_INVOICE"
        elif "invoices_tenant_id_phone_key" in raw or "uk_user" in raw:
            detail = "Thông tin đã tồn tại (email, số điện thoại hoặc mã đã dùng)"
            code = "DUPLICATE_VALUE"
        elif "23503" in raw or "foreign_key" in raw:
            detail = "Dữ liệu tham chiếu không tồn tại hoặc đang được sử dụng"
            code = "FK_VIOLATION"
        elif "23505" in raw or "unique" in raw:
            detail = "Giá trị đã tồn tại, không thể trùng lặp"
            code = "UNIQUE_VIOLATION"
        elif "23514" in raw or "chk_" in raw:
            detail = "Dữ liệu vi phạm ràng buộc nghiệp vụ"
            code = "CHECK_VIOLATION"
        elif "chk_reading" in raw or "reading_value" in raw:
            detail = "Chỉ số mới phải lớn hơn hoặc bằng chỉ số cũ (R4)"
            code = "READING_NOT_INCREASING"

        logger.warning("Ràng buộc DB vi phạm [%s]: %s", code, raw[:200])
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {"code": code, "message": detail, "details": {}},
                "request_id": get_request_id(),
            },
        )

    @app.exception_handler(OperationalError)
    async def _operational(request: Request, exc: OperationalError) -> JSONResponse:
        """
        Lỗi kết nối/timeout DB.

        Trả 503 (không phải 500) vì client có thể retry thành công.
        Nếu trả 500, client thường không retry → mất dữ liệu.
        """
        logger.error("Lỗi CSDL: %s", str(getattr(exc, "orig", exc))[:300])
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "Cơ sở dữ liệu tạm thời không sẵn sàng, vui lòng thử lại",
                    "details": {},
                },
                "request_id": get_request_id(),
            },
            headers={"Retry-After": "10"},
        )

    # ---- Bẫy cuối cùng ----
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """
        ⭐ KHÔNG BAO GIỜ để lộ traceback ra ngoài production.

        Traceback chứa đường dẫn file, tên class, cấu trúc DB — là thông tin
        giúp attacker định hướng tấn công. Trả về cho client chỉ có mã lỗi
        + request_id; chi tiết chỉ ghi vào log server.
        """
        error_id = str(uuid.uuid4())
        logger.error(
            "LỖI CHƯA XỬ LÝ [%s] %s %s\n%s",
            error_id, request.method, request.url.path,
            traceback.format_exc(),
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": (
                        "Đã xảy ra lỗi hệ thống. Nếu lỗi tiếp tục xảy ra, "
                        "vui lòng cung cấp mã lỗi cho quản trị viên."
                    ),
                    "details": {"error_id": error_id},
                },
                "request_id": get_request_id(),
            },
        )

    logger.info("Đã đăng ký %s exception handler", 8)
    return app
