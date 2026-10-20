#!/usr/bin/env bash
# ============================================================================
#  TRIỂN KHAI TRỌN GÓI — CHẠY 1 LỆNH LÀ XONG
#
#      sudo bash scripts/00-deploy.sh
#
#  Script tự gọi tuần tự:
#     [0] Bootstrap server (Docker + Compose v2 + UFW + swap) nếu chưa có
#     [1] Tạo .env và điền PUBLIC_IP / DOMAIN / REDIS_PASSWORD
#     [2] Sinh bí mật (secrets/)
#     [3] Sinh chứng chỉ TLS tự ký (nginx cần để chạy HTTPS)
#     [4] Kiểm tra môi trường (make check)
#     [5] Khởi động production (make prod-up) — build + chờ healthy
#     [6] Nạp dữ liệu mẫu (make seed, kèm reconcile)
#     [7] Kiểm tra sức khoẻ 9 service (make health)
#
#  Tùy chọn:
#      --ip <IP>         ghi PUBLIC_IP vào .env (không hỏi)
#      --domain <TÊN>    ghi DOMAIN vào .env (mặc định qlpt.local)
#      --dev             dùng `make up` (dev) thay vì `make prod-up`
#      --laptop          dùng `make laptop-up` — chế độ gọn nhẹ cho máy 8 GB
#                        (bỏ loki/promtail/cAdvisor/node-exporter, hạ trần RAM)
#      --no-bootstrap    bỏ qua bước cài Docker (đã có sẵn)
#      --skip-seed       không nạp dữ liệu mẫu
#      -h, --help        xem hướng dẫn
# ============================================================================
set -Eeuo pipefail

# --- Về đúng thư mục gốc dự án (chứa Makefile) ------------------------------
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Mặc định ---------------------------------------------------------------
MODE="prod"
BOOTSTRAP="auto"
DO_SEED="1"
ARG_IP=""
ARG_DOMAIN=""

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[1;34m'; BOLD='\033[1m'; NC='\033[0m'
step() { printf "\n${BOLD}${BLUE}▶ %s${NC}\n" "$*"; }
ok()   { printf "${GREEN}  ✓ %s${NC}\n" "$*"; }
warn() { printf "${YELLOW}  ⚠ %s${NC}\n" "$*"; }
fail() { printf "${RED}  ✗ %s${NC}\n" "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Triển khai trọn gói QLPT.

Cách dùng:
    sudo bash scripts/00-deploy.sh [tùy chọn]

Tùy chọn:
    --ip <IP>         ghi PUBLIC_IP vào .env (không hỏi)
    --domain <TÊN>    ghi DOMAIN vào .env (mặc định qlpt.local)
    --dev             dùng `make up` (dev) thay vì `make prod-up`
    --laptop          dùng `make laptop-up` — gọn nhẹ, phù hợp máy 8 GB
    --no-bootstrap    bỏ qua bước cài Docker (đã có sẵn)
    --skip-seed       không nạp dữ liệu mẫu
    -h, --help        xem hướng dẫn này
EOF
    exit 0
}

# --- Đọc tham số ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --ip)           ARG_IP="${2:-}"; shift 2;;
        --domain)       ARG_DOMAIN="${2:-}"; shift 2;;
        --dev)          MODE="dev"; shift;;
        --laptop)       MODE="laptop"; shift;;
        --no-bootstrap) BOOTSTRAP="0"; shift;;
        --skip-seed)    DO_SEED="0"; shift;;
        -h|--help)      usage;;
        *) fail "Tham số không hợp lệ: $1  (dùng -h để xem hướng dẫn)";;
    esac
done

IS_ROOT="0"; [[ "${EUID:-$(id -u)}" -eq 0 ]] && IS_ROOT="1"
APP_USER="${APP_USER:-qlpt}"

printf "\n${BOLD}════════════════════════════════════════════════════════════${NC}\n"
printf "${BOLD}  TRIỂN KHAI HỆ THỐNG QLPT — chế độ: %s${NC}\n" "$MODE"
printf "${BOLD}════════════════════════════════════════════════════════════${NC}\n"

# ============================================================================
step "[0/7] Kiểm tra Docker / Compose"
# ============================================================================
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker đã có: $(docker --version)"
elif [[ "$BOOTSTRAP" == "0" ]]; then
    fail "Docker/Compose chưa có nhưng bạn đã --no-bootstrap. Cài thủ công rồi chạy lại."
else
    [[ "$IS_ROOT" == "1" ]] || fail "Cần quyền root để cài Docker. Chạy: sudo bash scripts/00-deploy.sh"
    warn "Docker chưa có — chạy bootstrap (mất vài phút)..."
    bash scripts/01-bootstrap-ubuntu.sh
    ok "Bootstrap xong"
fi

# ============================================================================
step "[1/7] Cấu hình .env"
# ============================================================================
set_env_var() {
    local key="$1" val="$2" esc
    esc="$(printf '%s' "$val" | sed -e 's/[\/&|]/\\&/g')"
    if grep -qE "^${key}=" .env; then
        sed -i -E "s|^${key}=.*|${key}=${esc}|" .env
    else
        printf '%s=%s\n' "$key" "$val" >> .env
    fi
}
gen_pass() { LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "${1:-40}" || true; }

if [[ ! -f .env ]]; then
    cp .env.example .env
    ok "Đã tạo .env từ .env.example"
else
    ok ".env đã tồn tại — chỉ cập nhật giá trị cần thiết"
fi

# PUBLIC_IP
CUR_IP="$(grep -E '^PUBLIC_IP=' .env | head -1 | cut -d= -f2- | awk '{print $1}' || true)"
if [[ -n "$ARG_IP" ]]; then
    set_env_var PUBLIC_IP "$ARG_IP"; ok "PUBLIC_IP = $ARG_IP"
elif [[ -z "$CUR_IP" || "$CUR_IP" == "203.0.113.10" ]]; then
    if [[ -t 0 ]]; then
        read -rp "  Nhập IP server (hoặc Enter để dùng 127.0.0.1): " ans_ip
        set_env_var PUBLIC_IP "${ans_ip:-127.0.0.1}"
        ok "PUBLIC_IP = ${ans_ip:-127.0.0.1}"
    else
        warn "PUBLIC_IP còn là giá trị mẫu — hãy sửa trong .env nếu truy cập từ máy khác"
    fi
else
    ok "PUBLIC_IP = $CUR_IP (giữ nguyên)"
fi

# DOMAIN
if [[ -n "$ARG_DOMAIN" ]]; then
    set_env_var DOMAIN "$ARG_DOMAIN"; ok "DOMAIN = $ARG_DOMAIN"
else
    ok "DOMAIN = $(grep -E '^DOMAIN=' .env | head -1 | cut -d= -f2-)"
fi

# REDIS_PASSWORD — thay giá trị mẫu bằng chuỗi ngẫu nhiên mạnh
CUR_REDIS="$(grep -E '^REDIS_PASSWORD=' .env | head -1 | cut -d= -f2- || true)"
if [[ -z "$CUR_REDIS" || "$CUR_REDIS" == doi-mot-mat-khau* ]]; then
    NEW_REDIS="$(gen_pass 40)"
    set_env_var REDIS_PASSWORD "$NEW_REDIS"
    ok "Đã sinh REDIS_PASSWORD ngẫu nhiên (40 ký tự)"
else
    ok "REDIS_PASSWORD đã đặt (giữ nguyên)"
fi

# ============================================================================
step "[2/7] Sinh file bí mật (secrets/)"
# ============================================================================
bash scripts/02-generate-secrets.sh

# RabbitMQ image deprecate RABBITMQ_DEFAULT_PASS_FILE → ghi mật khẩu từ
# secrets/ vào .env (biến thường, cùng pattern REDIS_PASSWORD)
CUR_RMQ="$(grep -E '^RABBITMQ_DEFAULT_PASS=' .env | head -1 | cut -d= -f2- || true)"
RMQ_PW="$(cat secrets/rabbitmq_password.txt 2>/dev/null || true)"
if [[ -n "$RMQ_PW" && ( -z "$CUR_RMQ" || "$CUR_RMQ" == doi-mot-mat-khau* || "$CUR_RMQ" == \#* ) ]]; then
    set_env_var RABBITMQ_DEFAULT_PASS "$RMQ_PW"
    ok "Đã ghi RABBITMQ_DEFAULT_PASS (từ secrets/rabbitmq_password.txt) vào .env"
else
    ok "RABBITMQ_DEFAULT_PASS đã đặt (giữ nguyên)"
fi

# ============================================================================
step "[3/7] Sinh chứng chỉ TLS cho nginx"
# ============================================================================
bash scripts/06-generate-cert.sh

# Nếu đang chạy bằng root, trả quyền file nhạy cảm cho user ứng dụng
if [[ "$IS_ROOT" == "1" ]] && id -u "$APP_USER" >/dev/null 2>&1; then
    chown -R "$APP_USER:$APP_USER" secrets infra/nginx/certs .env 2>/dev/null || true
    ok "Đã gán quyền sở hữu secrets/, certs/, .env cho user '$APP_USER'"
fi

# ============================================================================
step "[4/7] Kiểm tra môi trường"
# ============================================================================
command -v make >/dev/null 2>&1 || fail "Thiếu make. Cài: sudo apt install -y make"
make check

# ============================================================================
step "[5/7] Khởi động hệ thống (${MODE})"
# ============================================================================
case "$MODE" in
    prod)   make prod-up ;;
    dev)    make up ;;
    laptop) make laptop-up ;;
    *)      fail "Chế độ không hợp lệ: $MODE" ;;
esac

# ── Nạp lại cấu hình nginx sau khi backend được recreate ──────────────────
# nginx phân giải tên upstream (auth, room, …) MỘT LẦN lúc khởi động. Khi
# `up -d` recreate backend (đổi IP container), nginx vẫn trỏ IP cũ → 502 Bad
# Gateway cho các route /api/v1/*, dù service vẫn khoẻ. Reload để phân giải
# lại DNS nội bộ Docker (127.0.0.11).
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^qlpt-nginx$'; then
    docker exec qlpt-nginx nginx -s reload >/dev/null 2>&1 \
        && ok "nginx đã reload (cập nhật DNS upstream)" \
        || warn "Không reload được nginx — nếu /api 502, chạy: make reload-nginx"
fi

# ============================================================================
step "[6/7] Nạp dữ liệu mẫu"
# ============================================================================
if [[ "$DO_SEED" == "1" ]]; then
    make seed
else
    warn "Bỏ qua nạp dữ liệu mẫu (--skip-seed)"
fi

# ============================================================================
step "[7/7] Kiểm tra sức khoẻ"
# ============================================================================
make health || warn "Có service chưa healthy — xem: make logs"

# ============================================================================
#  TỔNG KẾT
# ============================================================================
IP_DISPLAY="$(grep -E '^PUBLIC_IP=' .env | head -1 | cut -d= -f2- | awk '{print $1}')"
ADMIN_PWD="$(cat secrets/admin_password.txt 2>/dev/null || echo 'xem secrets/admin_password.txt')"

printf "\n${BOLD}${GREEN}════════════════════════════════════════════════════════════${NC}\n"
printf "${BOLD}${GREEN}  ✅ TRIỂN KHAI HOÀN TẤT${NC}\n"
printf "${BOLD}${GREEN}════════════════════════════════════════════════════════════${NC}\n"
cat <<EOF

  🌐 Ứng dụng web :  https://${IP_DISPLAY}/
  📊 Grafana       :  http://${IP_DISPLAY}:3000

  👤 Tài khoản demo:
       admin  / ${ADMIN_PWD}
       quanly / ${ADMIN_PWD}
       khach01 … khach12  /  Tenant@12345

  ⚠️  Chứng chỉ tự ký → trình duyệt cảnh báo "Not secure".
      Bấm Advanced → Proceed để tiếp tục (bình thường ở môi trường demo).

  🧪 Bước kiểm thử tiếp theo (nên chạy để có bằng chứng cho báo cáo):
       make test-int     # smoke test 6 nhóm
       make loadtest     # k6 50 VU / 2 phút
       make urls         # in toàn bộ đường dẫn

EOF