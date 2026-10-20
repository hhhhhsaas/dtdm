"""
Mã hóa dữ liệu nhạy cảm tầng ứng dụng — AES-256-GCM.

================================================================================
VÌ SAO KHÔNG DÙNG `pgcrypto` / TDE CỦA POSTGRES?
================================================================================
  - TDE của PostgreSQL **chưa có** ở bản community 16 (chỉ có ở bản thương mại)
  - `pgcrypto` mã hóa ở TẦNG DB: khi cần TÍNH TOÁN trên dữ liệu đó (ví dụ tìm
    người có CCCD trùng) thì phải giải mã toàn bảng trong DB → mất ý nghĩa
    của index, còn tầng ứng dụng thì vẫn index được trên ciphertext
  - Tầng ứng dụng cho phép kiểm soát vòng đời khóa (rotate) độc lập với DB

================================================================================
VÌ SAO GCM CHỨ KHÔNG PHẢI CBC?
================================================================================
  - CBC: cùng plaintext → cùng ciphertext (nếu IV cố định) → attacker đoán
    được "2 người có cùng số CCCD". IV ngẫu nhiên thì CBC vẫn **không phát hiện
    được sai lệch** (tampering) — sửa ciphertext vẫn giải mã ra rác.
  - GCM vừa BẢO MẬT vừa TOÀN VẸN: gắn 12-byte tag, sửa 1 byte ciphertext →
    giải mã thất bại ngay lập tức (InvalidTag). Đúng thứ ta cần với CCCD.

================================================================================
ĐỊNH DẠNG LƯU TRONG DB
================================================================================
    "v1$" + base64( nonce(12) || ciphertext || tag(16) )

Tiền tố "v1" cho phép đổi thuật toán/tham số sau này mà vẫn giải mã được dữ
liệu cũ — cùng ý tưởng với `schema_version` của event.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import read_secret

logger = logging.getLogger(__name__)

PREFIX: Final = "v1"
NONCE_SIZE: Final = 12      # 96 bit — giá trị chuẩn khuyến nghị cho GCM
KEY_SIZE: Final = 32        # 256 bit


class DecryptionError(Exception):
    """Sai khóa, dữ liệu bị can thiệp, hoặc định dạng không hợp lệ."""


# ---------------------------------------------------------------------------
#  Quản lý khóa
# ---------------------------------------------------------------------------
def _load_key() -> bytes:
    """
    Nạp khóa 256-bit từ Docker Secret `data_encryption_key.txt`.

    ⭐ Thiếu khóa KHÔNG được âm thầm sinh khóa mới — làm vậy mỗi lần restart
    container là dữ liệu đã mã hóa mất khả năng giải mã. Phải fail loud.
    """
    raw = read_secret("data_encryption_key.txt")
    if not raw:
        raise RuntimeError(
            "Thiếu data_encryption_key.txt. Chạy 'make secrets' để sinh khóa. "
            "KHÔNG được tự sinh khóa mới — dữ liệu đã mã hóa sẽ không giải mã được."
        )

    # Chấp nhận cả dạng hex 64 ký tự lẫn chuỗi ngẫu nhiên dài
    try:
        key = bytes.fromhex(raw)
        if len(key) == KEY_SIZE:
            return key
    except ValueError:
        pass

    # Dẫn xuất 32 byte bằng SHA-256 từ passphrase người dùng đặt
    return hashlib.sha256(raw.encode("utf-8")).digest()


# Cache khóa: nạp 1 lần, dùng cả vòng đời process
_KEY: bytes | None = None
_AESGCM: AESGCM | None = None


def get_cipher() -> AESGCM:
    global _KEY, _AESGCM
    if _AESGCM is None:
        _KEY = _load_key()
        _AESGCM = AESGCM(_KEY)
        logger.info("🔐 Đã nạp khóa mã hóa dữ liệu (AES-256-GCM)")
    return _AESGCM


def key_fingerprint() -> str:
    """
    8 ký tự đầu của SHA-256 khóa — dùng để ĐỐI CHIẾU, KHÔNG để dùng lại.

    Ví dụ log: `Khóa hiện tại: a3f1c9e2` (nếu khác key cũ `7b2e0044` → cảnh báo
    "bạn đã đổi khóa mà chưa re-encrypt dữ liệu").
    """
    return hashlib.sha256(_load_key()).hexdigest()[:8]


# ---------------------------------------------------------------------------
#  Mã hóa / giải mã
# ---------------------------------------------------------------------------
def encrypt(plaintext: str | None) -> str | None:
    """
    Mã hóa 1 chuỗi. `None` -> `None` (giữ nguyên semantics "không có dữ liệu").

    Dùng nonce ngẫu nhiên 12 byte cho MỖI lần gọi. Bắt buộc: dùng lại nonce với
    cùng khóa trong GCM là lỗi nghiêm trọng — lộ quan hệ giữa 2 bản rõ.
    """
    if plaintext is None:
        return None

    cipher = get_cipher()
    nonce = os.urandom(NONCE_SIZE)
    ct = cipher.encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"{PREFIX}${base64.urlsafe_b64encode(nonce + ct).decode('ascii')}"


def decrypt(token: str | None) -> str | None:
    """
    Giải mã. Ném `DecryptionError` nếu dữ liệu hỏng hoặc bị can thiệp.

    KHÔNG nuốt lỗi và trả None — như vậy lỗi hiển thị ra dưới dạng "trường rỗng"
    rất khó phát hiện. Ném lỗi để thấy ngay trong log và cảnh báo.
    """
    if token is None:
        return None

    version, _, payload = token.partition("$")
    if version != PREFIX or not payload:
        raise DecryptionError(
            f"Định dạng dữ liệu mã hóa không hợp lệ: {token[:24]}..."
        )

    try:
        blob = base64.urlsafe_b64decode(payload.encode("ascii"))
    except Exception as exc:
        raise DecryptionError(f"Không giải mã được base64: {exc}") from exc

    nonce, ct = blob[:NONCE_SIZE], blob[NONCE_SIZE:]
    try:
        return get_cipher().decrypt(nonce, ct, None).decode("utf-8")
    except InvalidTag as exc:
        # Sai khóa HOẶC ciphertext bị sửa. Hai khả năng này không phân biệt
        # được bằng GCM — và cũng không cần phân biệt: cả hai đều là sự cố.
        raise DecryptionError(
            "Kiểm tra tra (GCM tag) thất bại: khóa sai hoặc dữ liệu đã bị sửa"
        ) from exc


# ---------------------------------------------------------------------------
#  Tiện ích tìm kiếm / so sánh
# ---------------------------------------------------------------------------
def blind_index(value: str | None) -> str | None:
    """
    Chuỗi để TÌM KIẾM BẰNG INDEX trên dữ liệu đã mã hóa.

    Vấn đề: CCCD được mã hóa bằng nonce ngẫu nhiên → 2 hàng cùng CCCD có
    ciphertext KHÁC NHAU → `WHERE id_card_enc = ?` không bao giờ khớp.

    Cách giải quyết: tính thêm 1 cột "blind index" = HMAC-SHA256(khoá_tách,
    CCCD_đã_chuẩn_hoá), dùng khóa KHÁC khóa mã hóa. Khi đó tìm kiếm chính
    xác vẫn hoạt động trên index, còn dữ liệu vẫn được mã hóa.

    Đánh đổi (cần nói rõ trong báo cáo):
      - Lộ độ dài plaintext (đây là giới hạn cố hữu của mọi scheme có index)
      - Attacker có blind index vẫn không đọc được CCCD, chỉ xác nhận được
        "hai hàng có cùng CCCD" — chấp nhận được vì cần chống trùng CCCD
      - Vì vậy KHÔNG dùng cho trường cần tìm "nhiều giá trị khác nhau" (email
        chẳng hạn) — chỉ dùng cho khoá duy nhất cần tra cứu điểm hẹn
    """
    if not value:
        return None
    secret = _load_key()
    index_key = hashlib.sha256(secret + b"|qlpt:blind-index").digest()
    return hmac.new(
        index_key, normalize(value).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def normalize(value: str) -> str:
    """
    Chuẩn hoá trước khi băm/mã hoá: bỏ khoảng trắng thừa, viết thường.

    ⭐ Bắt buộc cho CCCD và số điện thoại: " 0123456789 " và "0123456789" là
    CÙNG một người, phải cho ra cùng blind index — nếu không sẽ tạo bản ghi
    trùng chỉ vì khác 1 dấu cách.
    """
    return "".join(value.split()).lower()


def mask(value: str | None, keep_last: int = 4) -> str | None:
    """
    Che bớt dữ liệu nhạy cảm để hiển thị — ví dụ `0912345678` -> `*******678`.

    Dùng cho response mặc định và log. Endpoint chuyên biệt mới được trả đầy đủ,
    và endpoint đó phải kiểm tra quyền + ghi audit log.
    """
    if not value:
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) <= keep_last:
        return "*" * len(digits)
    return "*" * (len(digits) - keep_last) + digits[-keep_last:]


def generate_data_key() -> str:
    """
    Sinh khóa 256-bit mới (dùng bởi scripts/02-generate-secrets.sh).

    Xuất dạng HEX để dễ đọc kiểm tra bằng mắt, và tránh vấn đề ký tự đặc biệt
    trong file secret.
    """
    return secrets.token_hex(KEY_SIZE)
