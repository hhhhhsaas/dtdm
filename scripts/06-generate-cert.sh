#!/usr/bin/env bash
# ============================================================================
#  TẠO CHỨNG CHỈ TLS TỰ KÝ (self-signed) CHO NGINX
#      bash scripts/06-generate-cert.sh
#
#  ⭐ VÌ SAO CẦN BƯỚC NÀY?
#     `infra/nginx/conf.d/app.conf` cấu hình HTTPS BẮT BUỘC và trỏ tới
#     /etc/nginx/certs/fullchain.pem + privkey.pem. Nếu 2 file này CHƯA có,
#     nginx sẽ không khởi động được (lỗi "cannot load certificate").
#     Script này sinh chứng chỉ tự ký để hệ thống chạy được NGAY trên IP
#     nội bộ / server chưa có domain.
#
#  Khi có domain thật: dùng Let's Encrypt (xem ghi chú cuối), hoặc đặt file
#  fullchain.pem/privkey.pem do Let's Encrypt cấp vào infra/nginx/certs/.
#
#  Không ghi đè cert đang có — dùng FORCE=1 nếu muốn tạo lại.
# ============================================================================
set -Eeuo pipefail

CERT_DIR="${CERT_DIR:-./infra/nginx/certs}"
DAYS="${DAYS:-825}"                 # 825 ngày — giới hạn khuyến nghị của Apple/Chrome cho cert tự ký
ENV_FILE="${ENV_FILE:-./.env}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[1;34m'; NC='\033[0m'
info() { printf "${BLUE}[INFO]${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}[ OK ]${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
fail() { printf "${RED}[FAIL]${NC} %s\n" "$*" >&2; exit 1; }

command -v openssl >/dev/null 2>&1 || fail "Thiếu openssl. Cài: sudo apt install -y openssl"

# --- Lấy DOMAIN / PUBLIC_IP / LAN_IPS từ .env (nếu có) ----------------------
DOMAIN=""
PUBLIC_IP=""
ENV_LAN_IPS=""
if [[ -f "$ENV_FILE" ]]; then
    DOMAIN="$(grep -E '^DOMAIN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' || true)"
    PUBLIC_IP="$(grep -E '^PUBLIC_IP=' "$ENV_FILE" | head -1 | cut -d= -f2- \
                 | awk '{print $1}' | tr -d '\r' || true)"
    ENV_LAN_IPS="$(grep -E '^LAN_IPS=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' || true)"
fi
DOMAIN="${DOMAIN:-qlpt.local}"
# Giá trị mẫu trong .env.example — coi như chưa đặt
[[ "$PUBLIC_IP" == "203.0.113.10" ]] && PUBLIC_IP=""

mkdir -p "$CERT_DIR"
chmod 700 "$CERT_DIR"

if [[ -f "$CERT_DIR/fullchain.pem" && -f "$CERT_DIR/privkey.pem" && "${FORCE:-0}" != "1" ]]; then
    warn "Chứng chỉ đã tồn tại trong $CERT_DIR — KHÔNG ghi đè (dùng FORCE=1 để tạo lại)"
    exit 0
fi

# --- Danh sách tên miền/IP mà cert hợp lệ (subjectAltName) ------------------
# ⭐ Thêm IP LAN vào SAN để máy KHÁC trong mạng nội bộ truy cập https://<IP-LAN>/
#   không bị cảnh báo cert (chỉ cần import chứng chỉ 1 lần).
#   Thứ tự ưu tiên: biến môi trường LAN_IPS > LAN_IPS trong .env > tự dò.
#   Định dạng: LAN_IPS="192.168.22.142" hoặc "192.168.22.142,10.0.0.5".
#   ⚠️ Chạy trong WSL2 (chế độ NAT): `hostname -I` trả IP NỘI BỘ của máy ảo WSL
#      (VD 172.28.x.x) — KHÔNG phải IP LAN của Windows. Muốn máy khác trong WiFi
#      vào được thì PHẢI khai LAN_IPS = IP LAN thật của Windows (xem ipconfig).
LAN_IPS="${LAN_IPS:-${ENV_LAN_IPS:-}}"
if [[ -z "$LAN_IPS" ]]; then
    LAN_IPS="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi
SAN="DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1"
if [[ -n "$PUBLIC_IP" ]]; then
    SAN="${SAN},IP:${PUBLIC_IP}"
fi
if [[ -n "$LAN_IPS" ]]; then
    IFS=',' read -r -a lan_arr <<< "$LAN_IPS"
    for ip in "${lan_arr[@]}"; do
        ip="$(printf '%s' "$ip" | tr -d '[:space:]')"
        if [[ -n "$ip" && "$ip" != "127.0.0.1" ]]; then
            SAN="${SAN},IP:${ip}"
        fi
    done
fi
# Khử trùng (VD khi cả PUBLIC_IP lẫn base đều là 127.0.0.1) — giữ nguyên thứ tự.
SAN="$(printf '%s' "$SAN" | tr ',' '\n' | awk '!seen[$0]++' | paste -sd, -)"

info "Tạo chứng chỉ self-signed cho: ${SAN}"
info "Hiệu lực ${DAYS} ngày, khóa RSA-2048"

openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "$CERT_DIR/privkey.pem" \
    -out "$CERT_DIR/fullchain.pem" \
    -days "$DAYS" \
    -subj "/C=VN/ST=VN/L=Vietnam/O=QLPT/CN=${DOMAIN}" \
    -addext "subjectAltName=${SAN}" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    2>/dev/null

chmod 600 "$CERT_DIR/privkey.pem"
chmod 644 "$CERT_DIR/fullchain.pem"

# --- Xác minh ---------------------------------------------------------------
openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -subject -enddate \
    | sed 's/^/  /'
ok "Đã tạo: $CERT_DIR/fullchain.pem + privkey.pem"

cat <<EOF

  ⚠️  Chứng chỉ TỰ KÝ: trình duyệt sẽ cảnh báo "Not secure".
      Đây là điều BÌNH THƯỜNG với môi trường demo/nội bộ.
      - Chrome/Edge: bấm "Advanced" → "Proceed to <host> (unsafe)".
      - Hoặc thêm ngoại lệ 1 lần trong cài đặt chứng chỉ của máy.

  BƯỚC TIẾP THEO:  make up   (hoặc: make prod-up)

  ⭐ KHI CÓ DOMAIN THẬT — dùng Let's Encrypt để hết cảnh báo:
      sudo apt install -y certbot
      sudo certbot certonly --webroot -w /var/lib/docker/volumes/qlpt_certbot_webroot/_data \\
           -d ${DOMAIN} --email ban@example.com --agree-tos --no-eff-email
      # rồi COPY cert vào đúng chỗ nginx đọc:
      sudo cp /etc/letsencrypt/live/${DOMAIN}/fullchain.pem $CERT_DIR/fullchain.pem
      sudo cp /etc/letsencrypt/live/${DOMAIN}/privkey.pem   $CERT_DIR/privkey.pem
      make prod-restart S=nginx

EOF