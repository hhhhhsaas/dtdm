"""
================================================================================
 CHIẾN LƯỢC ADAPTER — vì sao đổi nhà cung cấp không phải sửa code
================================================================================

Vấn đề: hệ thống cần gửi thông báo qua email, SMS, Zalo. Mỗi nhà cung cấp một
API khác nhau, một kiểu xác thực khác nhau, một cách báo lỗi khác nhau.

Nếu viết thẳng:

    if channel == "EMAIL":
        import smtplib
        smtplib.SMTP(...).send_message(...)
    elif channel == "SMS":
        httpx.post("https://sms.fpt.vn/api", ...)

thì mỗi lần thêm 1 kênh là phải sửa lại toàn bộ logic gửi, và logic nghiệp vụ
(event → render → dedupe) bị trộn với chi tiết kỹ thuật của nhà cung cấp.

Cách giải quyết: định nghĩa 1 PROTOCOL, mỗi kênh 1 lớp hiện thực. Phần còn
lại của hệ thống chỉ biết `CHANNELS["EMAIL"].send(...)`.

    CHANNELS = {"EMAIL": EmailChannel(), "SMS": SmsChannel(), ...}
             ^^^^^^^^^^ thêm kênh mới = thêm 1 dòng, KHÔNG sửa dòng nào khác

================================================================================
 `DRY_RUN` — vì sao mặc định là BẬT
================================================================================
Khi triển khai lần đầu, một con số sai trong template có thể gửi email cho
vài trăm người thuê thật, và không thu hồi được. `NOTIFICATION_DRY_RUN=true`
(mặc định) khiến adapter chỉ ghi log nội dung sẽ gửi, rồi đánh dấu thành
công — đủ để kiểm thử toàn bộ luồng mà không gửi đi 1 email nào.

Bật gửi thật bằng cách đặt `NOTIFICATION_DRY_RUN=false` TRONG .env, SAU KHI
đã xem nội dung qua log và endpoint `/api/v1/notifications/preview`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage

from jinja2 import StrictUndefined, select_autoescape
from jinja2.sandbox import SandboxedEnvironment

from common.config import settings
from models import Channel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Jinja2
# ---------------------------------------------------------------------------
#: ⭐ `StrictUndefined` — thiếu biến thì BÁO LỖI, không render ra chuỗi rỗng.
#:   Với `Undefined` mặc định, template sai biến vẫn "gửi thành công" với
#:   nội dung kiểu "Xin chào , hóa đơn  kỳ  trị giá  đã phát hành" — người
#:   thuê nhận được email vô nghĩa mà hệ thống báo là OK. Đây là loại lỗi
#:   đắt nhất trong hệ thống thông báo: im lặng và sai.
#:
#: ⭐ `SandboxedEnvironment` chứ không phải `Environment`: nội dung mẫu nằm
#:   trong DB và sửa được qua API. Với Environment thường, ai ghi được vào
#:   bảng `templates` chỉ cần một mẫu kiểu
#:   `{{ cycler.__init__.__globals__.os.popen('id').read() }}` là chạy lệnh
#:   shell trong container. Sandbox chặn truy cập thuộc tính `__…__`.
_JINJA = SandboxedEnvironment(
    autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=StrictUndefined,
)

#: Bắt tên biến trong template để lập danh mục `used_variables` (UI preview).
_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)")


@dataclass(slots=True)
class SendResult:
    """
    Kết quả một lần gửi.

    `ok=False` KHÔNG có nghĩa thông báo hỏng vĩnh viễn. Nhiều lỗi (mạng chập
    chờn, SMTP tạm quá tải) tự hết sau vài phút — vì vậy tách `retryable`.
    """

    ok: bool
    provider_message: str | None = None
    retryable: bool = False


def render(text: str, context: dict) -> str:
    """
    Render Jinja2 với `StrictUndefined`.

    Ném `TemplateError` khi template sai. Phía gọi (hàng đời gửi) sẽ đánh
    dấu FAILED — đúng hơn là gửi cho khách một email rỗng.
    """
    return _JINJA.from_string(text).render(**context)


def template_variables(text: str) -> list[str]:
    """Trích danh sách biến được dùng trong template (cho màn hình preview)."""
    return sorted(set(_VARIABLE_RE.findall(text or "")))


# ---------------------------------------------------------------------------
#  Interface chung
# ---------------------------------------------------------------------------
class NotificationChannel(ABC):
    """
    Hợp đồng của một kênh gửi.

    Mọi lớp con phải:
      - KHÔNG ném exception ra ngoài (trả `SendResult(ok=False)`)
      - CÓ thể dry-run (không gửi thật nhưng vẫn trả ok=True)
      - CÓ `name` trùng với key trong `CHANNELS`
    """

    name: str

    @abstractmethod
    async def send(self, recipient: str, subject: str | None,
                  body: str, context: dict | None = None) -> SendResult:
        """Gửi 1 thông báo. Không được ném exception."""

    def precheck(self, recipient: str) -> str | None:
        """
        Kiểm tra nhanh định dạng người nhận TRƯỚC khi gửi.

        Trả về thông báo lỗi, hoặc `None` nếu hợp lệ. Lớp gốc cho sẵn kiểm
        tra bằng regex; lớp con có thể ghi đè nếu định dạng đặc thù.
        """
        if not recipient or not recipient.strip():
            return "Người nhận rỗng"
        return None


# ---------------------------------------------------------------------------
#  IN_APP — lưu vào db_notify
# ---------------------------------------------------------------------------
class InAppChannel(NotificationChannel):
    """
    Kênh "trong ứng dụng": bản thân việc lưu vào `notifications` ĐÃ LÀ giao
    hàng thành công, vì người dùng đọc trên web chính là lúc "nhận" thông báo.

    ⭐ Vì vậy hàm `send()` của kênh này cố tình làm gì cả: việc ghi DB do tầng
    trên lo. Còn lại chỉ cần xác nhận cho scheduler biết "thành công" để nó
    không thử gửi lại vô ích.
    """

    name = Channel.IN_APP.value

    async def send(self, recipient: str, subject: str | None,
                  body: str, context: dict | None = None) -> SendResult:
        return SendResult(ok=True, provider_message="Đã lưu vào hộp thư trong ứng dụng")


# ---------------------------------------------------------------------------
#  EMAIL — SMTP
# ---------------------------------------------------------------------------
class EmailChannel(NotificationChannel):
    """
    Gửi email qua SMTP.

    ⭐ Vì sao dùng `asyncio.to_thread`?
       `smtplib` là thư viện ĐỒNG BỘ, và một lần gửi có thể mất vài giây
       (đặc biệt khi chờ handshake TLS với server ngoài). Gọi trực tiếp sẽ
       chặn cả event loop, khiến các request HTTP khác của service phải
       xếp hàng. `to_thread` đẩy việc này sang thread pool.
    """

    name = Channel.EMAIL.value

    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

    def precheck(self, recipient: str) -> str | None:
        if not self._EMAIL_RE.match(recipient or ""):
            return f"'{recipient}' không phải địa chỉ email hợp lệ"
        return None

    async def send(self, recipient: str, subject: str | None,
                  body: str, context: dict | None = None) -> SendResult:
        if settings.notification_dry_run:
            return _dry_run_ok(self.name, recipient, subject, body)

        if not settings.smtp_configured:
            # Không phải lỗi hệ thống, và KHÔNG nên thử lại — cấu hình chưa
            # bao giờ tự sửa được. Đánh dấu FAILED luôn cho người quản lý
            # biết phải cấu hình SMTP.
            return SendResult(
                ok=False,
                provider_message=(
                    "Chưa cấu hình SMTP (SMTP_HOST/SMTP_USER/SMTP_PASSWORD). "
                    "Đặt các biến này trong .env hoặc dùng kênh IN_APP."
                ),
                retryable=False,
            )

        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._send_sync, recipient, subject, body),
                timeout=settings.smtp_timeout,
            )
            return SendResult(ok=True, provider_message="Đã gửi qua SMTP")
        except TimeoutError:
            return SendResult(
                ok=False,
                provider_message=f"SMTP không phản hồi sau {settings.smtp_timeout}s",
                retryable=True,
            )
        except smtplib.SMTPRecipientsRefused as exc:
            # Địa chỉ sai → thử lại cũng vô ích.
            return SendResult(ok=False, provider_message=f"Sai địa chỉ: {exc}", retryable=False)
        except smtplib.SMTPAuthenticationError as exc:
            return SendResult(ok=False, provider_message=f"Sai thông tin đăng nhập: {exc}",
                              retryable=False)
        except (smtplib.SMTPException, OSError) as exc:
            # Lỗi mạng / server bận → đáng thử lại.
            return SendResult(ok=False, provider_message=f"{type(exc).__name__}: {exc}",
                              retryable=True)

    def _send_sync(self, recipient: str, subject: str | None, body: str) -> None:
        """Phần đồng bộ, chạy trong thread pool."""
        message = EmailMessage()
        message["From"] = f"QLPT <no-reply@{settings.smtp_host}>"
        message["To"] = recipient
        message["Subject"] = subject or "Thông báo từ hệ thống quản lý phòng trọ"
        message.set_content(body)

        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
        ) as server:
            if settings.smtp_use_tls:
                # ⭐ STARTTLS: nâng kênh lên TLS SAU khi đã bắt tay, là cách
                #   chuẩn cho cổng 587. (Cổng 465 thì bọc TLS ngay từ đầu.)
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            server.send_message(message)


# ---------------------------------------------------------------------------
#  SMS — cổng tin nhắn
# ---------------------------------------------------------------------------
class SmsChannel(NotificationChannel):
    """
    Gửi SMS qua cổng tin nhắn (FPT / Viettel / OneSME).

    ⭐ Chưa nối API thật trong bản demo. Adapter này GIỮ NGUYÊN đúng giao diện
       của adapter thật, khi cần chỉ thay phần `_send_sync` bằng HTTP client
       (và thêm `python-dateutil`/không cần gì thêm) — không phải sửa ở đâu khác.

    Vì sao vẫn giữ lại thay vì xoá: đây là chỗ dễ nhất để sinh viên "nâng cấp"
    đồ án, và code thật sự tồn tại (dù chưa gọi được nhà cung cấp) tốt hơn
    một chỗ trống có dấu "TODO: làm sau".
    """

    name = Channel.SMS.value

    #: Độ dài 1 tin nhắn SMS chuẩn ở Việt Nam: 160 ký tự 7-bit.
    MAX_LENGTH = 160

    _PHONE_RE = re.compile(r"^(0|\+84)\d{8,11}$")

    def precheck(self, recipient: str) -> str | None:
        phone = re.sub(r"[\s.\-()]", "", recipient or "")
        if not self._PHONE_RE.match(phone):
            return f"'{recipient}' không phải số điện thoại VN hợp lệ (09xx xxx xxx)"
        return None

    async def send(self, recipient: str, subject: str | None,
                  body: str, context: dict | None = None) -> SendResult:
        if settings.notification_dry_run:
            return _dry_run_ok(self.name, recipient, subject, body)

        text = _strip_for_sms(body)
        logger.info("📱 [SMS] %s → %s (giới hạn %d ký tự, hiện dùng %d)",
                    self.name, recipient, self.MAX_LENGTH, len(text))
        return SendResult(
            ok=False,
            provider_message=(
                "Kênh SMS chưa được cấu hình (cần SMS_API_URL/SMS_API_KEY). "
                "Đã ghi log nội dung để kiểm thử. "
                "Xem docs/07 mục 'Mở rộng kênh thông báo'."
            ),
            retryable=False,
        )


# ---------------------------------------------------------------------------
#  ZALO — Zalo OA
# ---------------------------------------------------------------------------
class ZaloChannel(NotificationChannel):
    """
    Gửi tin qua Zalo Official Account (API chính thức của Zalo).

    Chưa nối OAuth trong bản demo; giữ nguyên giao diện như các adapter khác.
    """

    name = Channel.ZALO.value

    async def send(self, recipient: str, subject: str | None,
                  body: str, context: dict | None = None) -> SendResult:
        if settings.notification_dry_run:
            return _dry_run_ok(self.name, recipient, subject, body)

        logger.info("💬 [ZALO] %s → %s", self.name, recipient)
        return SendResult(
            ok=False,
            provider_message=(
                "Kênh Zalo OA chưa cấu hình (cần ZALO_OA_ID + access token). "
                "Xem docs/07 mục 'Mở rộng kênh thông báo'."
            ),
            retryable=False,
        )


# ---------------------------------------------------------------------------
#  Registry
# ---------------------------------------------------------------------------
#: ⭐ Điểm mở rộng duy nhất của hệ thống thông báo: thêm kênh = thêm 1 dòng ở
#: đây. Không có chỗ nào khác trong code cần sửa theo.
CHANNELS: dict[str, NotificationChannel] = {
    Channel.IN_APP.value: InAppChannel(),
    Channel.EMAIL.value: EmailChannel(),
    Channel.SMS.value: SmsChannel(),
    Channel.ZALO.value: ZaloChannel(),
}


def get_channel(name: str) -> NotificationChannel:
    """Lấy adapter theo tên, luôn trả về một instance (không bao giờ None)."""
    channel = CHANNELS.get(name)
    if channel is None:
        # Không có adapter nào khớp → fallback sang IN_APP, vì đó là kênh
        # luôn hoạt động. Trả lỗi 500 ở đây sẽ khiến cả consumer chết vì
        # một template gõ sai kênh.
        logger.error("Không có adapter '%s' — dùng tạm IN_APP. "
                     "Các kênh hợp lệ: %s", name, sorted(CHANNELS))
        return CHANNELS[Channel.IN_APP.value]
    return channel


# ---------------------------------------------------------------------------
#  Tiện ích
# ---------------------------------------------------------------------------
def _dry_run_ok(channel: str, recipient: str,
                subject: str | None, body: str) -> SendResult:
    """
    Ghi log nội dung sẽ gửi rồi báo thành công.

    ⭐ Log ở mức INFO và chỉ in 300 ký tự đầu — nội dung thông báo có thể
       chứa dữ liệu cá nhân (họ tên, số tiền) và log thường được gửi đi
       nơi khác (Loki, file tải về). In đủ sẽ là rò rỉ dữ liệu.
    """
    preview = " ".join((body or "").split())[:300]
    logger.info(
        "🔔 [DRY-RUN][%s] → %s | %s\n      %s",
        channel, recipient, subject or "(không tiêu đề)", preview,
    )
    return SendResult(ok=True, provider_message="DRY-RUN: chưa gửi thật (NOTIFICATION_DRY_RUN=true)")


def _strip_for_sms(text: str) -> str:
    """
    Rút gọn nội dung cho SMS.

    SMS tính tiền theo TIN NHẮN, mà 1 tin nhắn chỉ chứa 160 ký tự — gửi 2 tin
    nhắn cho một thông báo vô nghĩa là tốn gấp đôi mà đọc càng khó. Vì vậy
    chỉ lấy câu đầu tiên và cắt bớt.
    """
    first_line = (text or "").strip().split("\n\n")[0]
    compact = " ".join(first_line.split())
    if len(compact) > SmsChannel.MAX_LENGTH:
        return compact[: SmsChannel.MAX_LENGTH - 1] + "…"
    return compact


__all__ = [
    "CHANNELS",
    "EmailChannel",
    "InAppChannel",
    "NotificationChannel",
    "SendResult",
    "SmsChannel",
    "ZaloChannel",
    "get_channel",
    "render",
    "template_variables",
]
