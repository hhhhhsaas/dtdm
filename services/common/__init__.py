"""
=============================================================================
 THƯ VIỆN DÙNG CHUNG cho cả 8 microservice
=============================================================================

Nguyên tắc: code dùng chung phải là code *hạ tầng* (kết nối, bảo mật, ghi log,
giao tiếp), KHÔNG được là code *nghiệp vụ*.

  ✅ Được:  kết nối DB, đọc config, xác thực JWT, ghi log, gửi/nhận event
  ❌ Không: entity nghiệp vụ, endpoint, quy tắc tính tiền

Lý do: nếu đưa nghiệp vụ vào common, các service sẽ dần phụ thuộc lẫn nhau
và kiến trúc Microservice trở lại thành Monolith phân tán.
"""

from .clients import INTERNAL_PREFIX, ServiceClient, get_http_client
from .config import get_settings, settings
from .database import (
    Base,
    DatabaseHealth,
    create_tables,
    get_db,
    get_session,
    health_check_db,
    init_db,
    session_scope,
)
from .errors import (
    BusinessRuleError,
    ConflictError,
    DomainError,
    DownstreamTimeout,
    NotFoundError,
    PermissionDeniedError,
    RateLimitExceeded,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
    setup_exception_handlers,
)
from .events import (
    DomainEvent,
    EventBus,
    IdempotentConsumer,
    close_event_bus,
    enqueue_outbox,
    get_event_bus,
    publish,
    subscribe,
)
from .repository import (
    acquire_lock,
    apply_sort,
    new_correlation_id,
    next_sequence,
    paginate,
    release_lock,
)
from .schemas import (
    MessageListResponse,
    MessageResponse,
    PageMeta,
    PageParams,
    PaginatedResponse,
)
from .security import (
    CurrentUser,
    CurrentUserDep,
    Role,
    TokenPair,
    TokenPayload,
    constant_time_compare,
    create_access_token,
    create_internal_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    hash_token,
    rate_limit,
    require_roles,
    verify_password,
)
from .service import ServiceContext, create_service_app
from .telemetry import (
    HEALTH_STATUS,
    OUTBOX_PENDING,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    MetricsMiddleware,
    get_request_id,
    metrics_endpoint,
    record_business_event,
    record_consumed,
    set_business_gauge,
    setup_telemetry,
)

__all__ = [
    "HEALTH_STATUS",
    "INTERNAL_PREFIX",
    "OUTBOX_PENDING",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "Base",
    "BusinessRuleError",
    "ConflictError",
    "CurrentUser",
    "CurrentUserDep",
    "DatabaseHealth",
    "DomainError",
    "DomainEvent",
    "DownstreamTimeout",
    "EventBus",
    "IdempotentConsumer",
    "MessageListResponse",
    "MessageResponse",
    "MetricsMiddleware",
    "NotFoundError",
    "PageMeta",
    "PageParams",
    "PaginatedResponse",
    "PermissionDeniedError",
    "RateLimitExceeded",
    "Role",
    "ServiceClient",
    "ServiceContext",
    "ServiceUnavailableError",
    "TokenPair",
    "TokenPayload",
    "UnauthorizedError",
    "ValidationError",
    "acquire_lock",
    "apply_sort",
    "close_event_bus",
    "constant_time_compare",
    "create_access_token",
    "create_internal_token",
    "create_refresh_token",
    "create_service_app",
    "create_tables",
    "decode_token",
    "enqueue_outbox",
    "get_current_user",
    "get_db",
    "get_event_bus",
    "get_http_client",
    "get_request_id",
    "get_session",
    "get_settings",
    "hash_password",
    "hash_token",
    "health_check_db",
    "init_db",
    "metrics_endpoint",
    "new_correlation_id",
    "next_sequence",
    "paginate",
    "publish",
    "rate_limit",
    "record_business_event",
    "record_consumed",
    "release_lock",
    "require_roles",
    "session_scope",
    "set_business_gauge",
    "settings",
    "setup_exception_handlers",
    "setup_telemetry",
    "subscribe",
    "verify_password",
]

__version__ = "1.0.0"
