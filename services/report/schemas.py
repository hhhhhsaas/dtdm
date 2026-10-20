"""
Schema Pydantic của report-service — hợp đồng của toàn bộ báo cáo.

⭐ Vì sao report-service có schema riêng chứ không dùng model SQLAlchemy trả
   thẳng ra? Vì báo cáo là **hợp đồng với người đọc**, không phải với DB:

     1. Ta muốn thêm cột tính toán (`collection_ratio`, `occupancy_rate`)
        mà không đụng tới bảng.
     2. Ta muốn đổi cách tính (VD: đổi cách chia nhóm tuổi nợ từ 4 nhóm lên 5)
        mà KHÔNG phá client cũ — schema là nơi chốt "những trường này luôn có".
     3. Cột `source`/`captured_at` là chi tiết kỹ thuật của read model, không
        phải thứ người dùng cần thấy → không nên lộ ra mặc định.

Mọi số tiền đều là `Decimal`. Pydantic v2 xuất `Decimal` ra JSON dưới dạng
chuỗi, nên `2500000.0` không bao giờ xuất hiện — frontend parse thoải mái mà
vẫn không mất chính xác.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

#: Nhóm tuổi nợ, đúng THỨ TỰ hiển thị trên báo cáo (từ chưa đến hạn → quá
#: hạn nặng nhất). Thứ tự này là hợp đồng UI: biểu đồ cột vẽ theo thứ tự
#: này nên không được đảo.
AGING_BUCKETS: list[tuple[str, str]] = [
    ("CHUA_DEN_HAN", "Chưa đến hạn"),
    ("1_7_NGAY", "Trễ 1–7 ngày"),
    ("8_30_NGAY", "Trễ 8–30 ngày"),
    ("31_60_NGAY", "Trễ 31–60 ngày"),
    ("TREN_60_NGAY", "Trễ hơn 60 ngày"),
]


# ---------------------------------------------------------------------------
#  Khung chung
# ---------------------------------------------------------------------------
class ReportWindow(BaseModel):
    """Khoảng thời gian mà báo cáo phủ — luôn trả về để client tự hiển thị."""

    from_date: date
    to_date: date
    days: int = Field(description="Số ngày trong khoảng (bao gồm cả 2 đầu)")
    timezone: str = Field(default="Asia/Ho_Chi_Minh",
                          description="Ngày được cắt theo múi giờ này, KHÔNG theo UTC")


class DataFreshness(BaseModel):
    """
    Độ tin cậy của số liệu.

    ⭐ Đây là câu trả lời trực tiếp cho câu hỏi "số này có chính xác không?"
       của người đọc báo cáo. Một dashboard mà không nói được mình dựa trên
       dữ liệu từ lúc nào thì y như vẽ đường rồi bảo đó là sự thật.
    """

    last_sync_at: datetime | None = Field(
        default=None, description="Lần đối chiếu gần nhất (null = chưa chạy lần nào)",
    )
    sync_status: str | None = Field(default=None, description="SUCCESS | PARTIAL | FAILED")
    is_stale: bool = Field(
        default=False, description="True khi đã quá 2 chu kỳ đối chiếu mà chưa chạy lại",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Các service nguồn mà lần đối chiếu gần nhất đã gọi",
    )
    note: str | None = Field(
        default=None,
        description="Giải thích bằng tiếng Việt khi dữ liệu có vấn đề",
    )


# ---------------------------------------------------------------------------
#  Doanh thu
# ---------------------------------------------------------------------------
class RevenuePoint(BaseModel):
    """Một ngày trong biểu đồ doanh thu."""

    stat_date: date
    invoiced: Decimal = Field(description="Tổng phát hành trong ngày")
    collected: Decimal = Field(description="Dòng tiền nhận trong ngày")
    refunded: Decimal = Field(description="Tiền trả lại trong ngày")
    net_collected: Decimal = Field(description="collected − refunded")
    outstanding: Decimal = Field(
        description="Số dư công nợ CUỐI NGÀY (lũy kế, không phải số của ngày)",
    )
    invoices_issued: int
    payments_received: int
    collection_ratio: float = Field(
        description="collected / invoiced (%). 0 khi ngày đó không phát hành gì",
    )


class RevenueReport(BaseModel):
    window: ReportWindow
    freshness: DataFreshness

    total_invoiced: Decimal
    total_collected: Decimal
    total_refunded: Decimal
    net_collected: Decimal
    total_outstanding: Decimal = Field(
        description="Công nợ còn lại TÍNH ĐẾN ngày cuối — không phải tổng trong kỳ",
    )
    invoices_issued: int
    payments_received: int

    avg_collection_ratio: float = Field(
        description="Tỷ lệ thu hồi của CẢ KỲ (tổng thu / tổng phát hành), không phải trung bình của các ngày",
    )
    best_day: RevenuePoint | None = Field(
        default=None, description="Ngày thu nhiều nhất trong kỳ",
    )
    worst_day: RevenuePoint | None = None
    #: Các ngày KHÔNG có dữ liệu trong kỳ — để client vẽ đường đứt quãng
    #: thay vì nối thẳng hai điểm xa nhau (dễ gây hiểu nhầm).
    missing_days: list[date] = Field(default_factory=list)
    points: list[RevenuePoint]


# ---------------------------------------------------------------------------
#  Công suất phòng
# ---------------------------------------------------------------------------
class OccupancyPoint(BaseModel):
    stat_date: date
    total_rooms: int
    available: int
    occupied: int
    maintenance: int
    reserved: int
    other: int
    occupancy_rate: float
    source: str = Field(description="event | snapshot — dữ liệu do event hay do đối chiếu")


class OccupancySnapshot(BaseModel):
    """Trạng thái phòng tại thời điểm hiện tại."""

    total_rooms: int = 0
    available: int = 0
    occupied: int = 0
    maintenance: int = 0
    reserved: int = 0
    other: int = 0
    occupancy_rate: float = 0.0
    stat_date: date | None = None
    source: str | None = None
    captured_at: datetime | None = None


class OccupancyReport(BaseModel):
    window: ReportWindow
    freshness: DataFreshness
    current: OccupancySnapshot = Field(
        description="Trạng thái HÔM NAY. Có thể null dữ liệu nếu hôm nay chưa có event nào",
    )
    avg_occupancy_rate: float = Field(default=0.0, description="Bình quân cả kỳ")
    peak_occupancy_rate: float = 0.0
    low_occupancy_rate: float = 0.0
    points: list[OccupancyPoint]


# ---------------------------------------------------------------------------
#  Công nợ & thu hồi
# ---------------------------------------------------------------------------
class AgingBucket(BaseModel):
    """Một nhóm tuổi nợ trong báo cáo phân rã công nợ."""

    bucket: str
    label: str
    invoice_count: int = 0
    amount: Decimal = Field(default=Decimal("0"), description="Tổng tiền còn nợ trong nhóm")
    share: float = Field(
        default=0.0, description="Tỷ trọng tiền của nhóm này trong tổng công nợ (%)",
    )


class DebtItem(BaseModel):
    """Một hóa đơn còn nợ — dòng chi tiết của báo cáo công nợ."""

    invoice_id: uuid.UUID
    invoice_no: str
    #: Mang cả `tenant_id` chứ không chỉ tên: tên người thuê có thể trùng
    #: nhau, gộp theo tên sẽ gộp nhầm 2 người thành 1 và báo cáo công nợ
    #: của người này thành của người kia.
    tenant_id: uuid.UUID | None = None
    tenant_name: str | None = None
    contract_id: uuid.UUID | None = None
    room_id: uuid.UUID | None = None
    total_amount: Decimal
    paid_amount: Decimal
    remaining: Decimal
    issued_date: date
    due_date: date
    status: str
    days_overdue: int
    bucket: str = Field(description="Nhóm tuổi nợ, xem AGING_BUCKETS")
    is_overdue_notified: bool = Field(
        default=False, description="Đã nhắc quá hạn chưa — để tránh nhắc lại lần 2",
    )


class DebtorSummary(BaseModel):
    """Gộp công nợ theo từng khách — chủ nhà cần biết AI còn nợ nhiều nhất."""

    tenant_id: uuid.UUID | None = None
    tenant_name: str = "(không rõ)"
    invoice_count: int
    total_remaining: Decimal
    max_days_overdue: int


class CollectionsReport(BaseModel):
    window: ReportWindow
    freshness: DataFreshness

    total_open: Decimal = Field(description="Tổng tiền còn nợ (mọi hóa đơn chưa quét hết)")
    open_invoice_count: int
    total_overdue: Decimal = Field(description="Phần đã quá hạn")
    overdue_invoice_count: int
    #: Nhóm "nguy hiểm" — trễ > 30 ngày. Đây là con số chủ nhà hành động
    #: được (gọi điện, đòi cọc), nên tách riêng thay vì để trong tổng.
    severe_overdue: Decimal
    severe_overdue_count: int
    collection_ratio: float = Field(
        default=0.0, description="(phát hành − còn nợ) / phát hành trong kỳ",
    )

    buckets: list[AgingBucket]
    top_debtors: list[DebtorSummary] = Field(default_factory=list)
    items: list[DebtItem] = Field(default_factory=list)
    truncated: bool = Field(
        default=False,
        description="True khi `items` bị cắt bởi giới hạn, tổng số vẫn đúng ở `buckets`",
    )


# ---------------------------------------------------------------------------
#  Vòng quay hợp đồng
# ---------------------------------------------------------------------------
class ContractFlowPoint(BaseModel):
    stat_date: date
    created: int = 0
    activated: int = 0
    terminated: int = 0
    expired: int = 0
    cancelled: int = 0
    renewed: int = 0
    net_new: int = 0


class ContractFlowReport(BaseModel):
    window: ReportWindow
    freshness: DataFreshness

    total_created: int = 0
    total_activated: int = 0
    total_terminated: int = 0
    total_expired: int = 0
    total_cancelled: int = 0
    total_renewed: int = 0
    net_new: int = 0
    #: Hợp đồng đang hiệu lực — lấy trực tiếp từ contract-service (nguồn
    #: chuẩn) chứ không suy ra từ sự kiện.
    active_contracts: int | None = None
    #: Độ chênh giữa số suy ra và số thật. Khác 0 = read model đang lệch.
    drift: int | None = Field(
        default=None,
        description="activated − terminated − expired − cancelled, trừ số active thật",
    )
    churn_rate: float = Field(
        default=0.0, description="(kết thúc) / (đang hiệu lực + kết thúc trong kỳ), %",
    )
    points: list[ContractFlowPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
#  Bảo trì (proxy từ maintenance-service)
# ---------------------------------------------------------------------------
class MaintenanceReport(BaseModel):
    """
    Báo cáo sự cố — `report-service` KHÔNG tự tính, mà gọi
    `GET /internal/v1/incidents` của maintenance-service.

    ⭐ Đây là chỗ duy nhất report-service chấp nhận gọi service khác khi đọc.
        Vì sao? Vì số liệu "đang có bao nhiêu phiếu sự cố mở" là TRẠNG THÁI
        hiện tại, không phải sự kiện lịch sử. Dựng read model riêng cho nó
        là viết thêm 1 bảng + 1 consumer + 1 đường đối chiếu, chỉ để đọc 5
        con số — trong khi maintenance đã có sẵn câu SQL group-by sẵn sàng.
        Bài toán: đọc 5 số 1 lần/ngày, không phải 1 số 1000 lần/phút.

        Đánh đổi: nếu maintenance-service chết, endpoint này trả 503 chứ
        không trả số sai. Dashboard gọi nó bằng `gather` + bỏ qua lỗi, nên
        các ô khác vẫn hiện bình thường.
    """

    property_id: uuid.UUID | None = None
    total: int = 0
    by_category: dict[str, dict[str, int]] = Field(default_factory=dict)
    total_cost: Decimal = Decimal("0")
    fetched_at: datetime
    degraded: bool = Field(
        default=False, description="True nếu không lấy được và đang dùng dữ liệu cache",
    )


# ---------------------------------------------------------------------------
#  Dashboard
# ---------------------------------------------------------------------------
class DashboardResponse(BaseModel):
    """Tổng quan 1 màn hình — endpoint quan trọng nhất của service này."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "property_id": "9a1c...-...",
            "generated_at": "2026-03-01T08:00:00+07:00",
            "freshness": {"last_sync_at": "2026-03-01T07:30:00+07:00",
                          "is_stale": False},
            "kpi": {
                "revenue_month": "184500000",
                "collection_ratio": 92.4,
                "occupancy_rate": 87.5,
                "rooms_available": 5,
                "open_debt": "12300000",
                "overdue_debt": "4200000",
                "active_contracts": 28,
                "open_incidents": 3,
            },
        }
    })

    property_id: uuid.UUID | None = None
    property_label: str = Field(
        default="Tất cả cơ sở",
        description="Chuỗi hiển thị; report không tự chứa tên cơ sở nên chỉ gắn nhãn",
    )
    generated_at: datetime
    freshness: DataFreshness

    kpi: dict[str, Decimal | float | int | None] = Field(
        description=(
            "Chỉ số chính: revenue_month, collection_ratio, occupancy_rate, "
            "rooms_available, open_debt, overdue_debt, active_contracts, "
            "open_incidents. Giá trị null = chưa đủ dữ liệu (mới cài, "
            "hoặc service nguồn chết) — KHÔNG phải số 0."
        ),
    )

    revenue_30d: list[RevenuePoint] = Field(default_factory=list)
    occupancy_30d: list[OccupancyPoint] = Field(default_factory=list)
    aging: list[AgingBucket] = Field(default_factory=list)
    #: Dịch vụ nào đang chết lúc dựng dashboard — để hiện cảnh báo thay vì
    #: âm thầm bỏ trống ô số liệu (người dùng tưởng là 0 đợt ai thu).
    degraded_sources: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
#  Đối chiếu & vận hành
# ---------------------------------------------------------------------------
class SyncRunResponse(BaseModel):
    id: int
    kind: str
    property_id: uuid.UUID | None
    status: str
    rows_synced: int
    detail: dict | None = None
    message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    triggered_by: str


class ReconcileResponse(BaseModel):
    """Kết quả 1 lần chạy đối chiếu."""

    kind: str
    status: str = Field(description="SUCCESS | PARTIAL | FAILED")
    duration_ms: int
    occupancy_synced: int = 0
    financials_synced: int = Field(
        default=0, description="Số dòng daily_financials đã dựng lại từ billing",
    )
    invoices_synced: int = 0
    retention: dict | None = Field(
        default=None, description="Thống kê dọn dữ liệu (chỉ có ở kind='full')",
    )
    errors: list[str] = Field(default_factory=list)
    finished_at: datetime


class SummaryResponse(BaseModel):
    """Tóm tắt cho service khác hoặc cho cron bên ngoài đọc nhanh."""

    as_of: datetime
    revenue_today: Decimal = Decimal("0")
    revenue_month: Decimal = Decimal("0")
    invoices_issued_month: int = 0
    open_debt: Decimal = Decimal("0")
    overdue_debt: Decimal = Decimal("0")
    occupancy_rate: float = 0.0
    total_rooms: int = 0
    available_rooms: int = 0
    is_stale: bool = False
    last_sync_at: datetime | None = None
