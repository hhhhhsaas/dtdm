#!/usr/bin/env bash
# ============================================================================
#  KIỂM CHỨNG CHẤT LƯỢNG CUỐI CÙNG  —  chạy sau `make laptop-up && make seed`
#  Dùng:  bash scripts/07-verify-final.sh
#
#  "Không có con số nào thì không có cải tiến." — Peter Drucker
#  Script gom MỌI kiểm tra vào MỘT lệnh: container, /health từng service,
#  gateway Nginx (HTTPS), tài khoản demo và smoke test 26 kiểm tra. Thoát
#  với mã != 0 nếu có bất kỳ hạng mục nào hỏng → dùng được cho CI/cron.
# ============================================================================
set -Eeuo pipefail

COMPOSE="${COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.laptop.yml}"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'
log()  { printf "\n${B}◆ %s${N}\n" "$*"; }
ok()   { printf "${G}  ✓${N} %s\n" "$*"; }
warn() { printf "${Y}  ⚠${N} %s\n" "$*"; }
err()  { printf "${R}  ✗${N} %s\n" "$*"; FAIL=$((FAIL+1)); }

FAIL=0

# Thư mục tạm RIÊNG cho mỗi lần chạy. Dùng đường dẫn cố định trong /tmp sẽ
# hỏng khi chạy lẫn lộn user thường và root: kernel bật fs.protected_regular
# nên root không ghi đè được file do user khác tạo trong /tmp (sticky bit).
RUN_TMP="$(mktemp -d "${TMPDIR:-/tmp}/qlpt-verify.XXXXXX")"
trap 'rm -rf "$RUN_TMP"' EXIT

# ----------------------------------------------------------------------------
log "BƯỚC 1 — Tất cả container đang chạy?"
# prometheus KHÔNG có healthcheck (theo thiết kế) nên chỉ kiểm "Up".
TOTAL=0; RUNNING=0; HEALTHY=0; UNHEALTHY=0
while read -r name; do
    if [[ -z "$name" ]]; then continue; fi
    TOTAL=$((TOTAL+1))
    # ⭐ docker ps --format KHÔNG hỗ trợ .State.Health (lỗi "can't evaluate
    #   field Health in type string") → phải qua docker inspect như từng làm.
    state=$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || echo unknown)
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' \
                 "$name" 2>/dev/null || echo -)
    if [[ "$state" == "running" ]]; then RUNNING=$((RUNNING+1)); fi
    case "$health" in
        healthy)   HEALTHY=$((HEALTHY+1)) ;;
        starting)  warn "$name đang starting (start_period)…" ;;
        unhealthy) UNHEALTHY=$((UNHEALTHY+1)); err "$name UNHEALTHY" ;;
    esac
done < <(docker ps -a --format '{{.Names}}' | grep '^qlpt-' | sort)

printf "     tổng=%d  đang chạy=%d  healthy=%d\n" "$TOTAL" "$RUNNING" "$HEALTHY"
if [[ "$RUNNING" -ne "$TOTAL" ]]; then err "Có $((TOTAL-RUNNING)) container KHÔNG chạy"; fi
if [[ "$UNHEALTHY" -ne 0 ]]; then warn "$UNHEALTHY container unhealthy (xem: docker logs <tên>)"; fi
if [[ "$HEALTHY" -ge 15 ]]; then ok "$HEALTHY container healthy (prometheus không có healthcheck)"; fi

# ----------------------------------------------------------------------------
log "BƯỚC 2 — /health từng service (make health: 9/9)"
if make health --no-print-directory >"$RUN_TMP/health.txt" 2>&1; then
    ok "$(grep -c '✅' "$RUN_TMP/health.txt")/9 service trả lời"
else
    err "make health thất bại:"; sed 's/^/     /' "$RUN_TMP/health.txt" | tail -10
fi

# ----------------------------------------------------------------------------
log "BƯỚC 3 — Gateway Nginx (HTTPS, từ Windows: https://localhost)"
gw() { curl -sk -m 10 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null || echo 000; }

for path in "/" "/api/v1/rooms/available"; do
    code=$(gw "https://localhost${path}")
    [[ "$code" == "200" ]] && ok "GET ${path}  → ${code}" || err "GET ${path}  → ${code}"
done

# ⭐ Chốt chặn lỗi "Failed to fetch": endpoint API KHÔNG được trả 301/HTML.
#    (location có "/" cuối → 301 vòng lặp; route sai prefix → rơi vào SPA trả HTML)
for path in "/api/v1/rooms" "/api/v1/invoices" "/api/v1/tenants" \
            "/api/v1/contracts" "/api/v1/reports/dashboard"; do
    meta=$(curl -sk -m 10 -o /dev/null -w '%{http_code} %{content_type}' \
           "https://localhost${path}" 2>/dev/null || echo "000 -")
    code=${meta%% *}; ct=${meta#* }
    case "$code" in 301|302|307|308) bad="redirect";; *) bad="";; esac
    [[ "$ct" == *json* ]] || bad="${bad}html"
    if [[ -z "$bad" ]]; then
        ok "routing ${path} → ${code} (${ct%%;*})"
    else
        err "routing ${path} → ${meta}  (nghi 301/HTML → 'Failed to fetch')"
    fi
done

# Swagger bị tắt ở môi trường prod (docs_enabled=false) — 404 là ĐÚNG thiết kế.
code=$(gw "https://localhost/docs")
[[ "$code" == "404" ]] && ok "GET /docs → 404 (chủ ý: tắt Swagger ở production)" \
                       || warn "GET /docs → ${code} (mong đợi 404 ở môi trường prod)"

# ----------------------------------------------------------------------------
log "BƯỚC 4 — Đăng nhập qua gateway (tài khoản demo)"
# ⭐ Cách đọc mật khẩu admin ĐÚNG: ưu tiên biến môi trường, rồi file secret.
#    secrets/ thường là 700 root-only → chạy user thường sẽ không đọc được.
#    Trước đây script âm thầm dùng 'Admin@12345' (SAI) → login 401 khó hiểu;
#    giờ báo lỗi rõ ràng kèm cách khắc phục.
SECRET_FILE="secrets/admin_password.txt"
if [[ -n "${QLPT_ADMIN_PWD:-}" ]]; then
    ADMIN_PW="$QLPT_ADMIN_PWD"
    ok "Dùng mật khẩu admin từ biến môi trường QLPT_ADMIN_PWD"
elif [[ -r "$SECRET_FILE" ]]; then
    ADMIN_PW="$(cat "$SECRET_FILE")"
elif [[ -d secrets ]]; then
    err "Không đọc được $SECRET_FILE (chỉ root đọc được — file 600, thư mục secrets/ 700)."
    err "Hãy chạy bằng root:  sudo make verify  ·  hoặc đặt QLPT_ADMIN_PWD=<mật khẩu>"
    ADMIN_PW="Admin@12345"
else
    warn "Chưa có $SECRET_FILE — dùng mặc định Admin@12345 (máy mới chưa tạo secret)."
    ADMIN_PW="Admin@12345"
fi
login() {  # $1=username  $2=password  $3=tên hiển thị
    local code
    code=$(curl -sk -m 10 -o "$RUN_TMP/login.json" -w '%{http_code}' \
        -X POST "https://localhost/api/v1/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"username\":\"$1\",\"password\":\"$2\"}")
    if [[ "$code" == "200" ]] && grep -q access_token "$RUN_TMP/login.json"; then
        ok "$3 ($1) đăng nhập → 200 + access_token"
    else
        err "$3 ($1) đăng nhập → ${code}"
    fi
}
login "admin"  "$ADMIN_PW"   "Quản trị viên"
login "khach01" "Tenant@12345" "Người thuê"

# ----------------------------------------------------------------------------
log "BƯỚC 5 — Smoke test 26 kiểm tra (make test-int)"
if make test-int --no-print-directory >"$RUN_TMP/smoke.txt" 2>&1; then
    ok "$(grep -oE '[0-9]+/[0-9]+ PASS' "$RUN_TMP/smoke.txt" | tail -1)"
else
    err "Smoke test có lỗi — xem chi tiết:"; tail -35 "$RUN_TMP/smoke.txt" | sed 's/^/     /'
fi

# ----------------------------------------------------------------------------
log "BƯỚC 6 — Dữ liệu mẫu đã nạp"
for tbl in "db_room:rooms:20" "db_tenant:tenants:12" "db_contract:contracts:9" \
           "db_billing:invoices:27" "db_auth:users:14"; do
    IFS=: read -r db t min <<<"$tbl"
    n=$(docker exec qlpt-postgres psql -U qlpt -d "$db" -tAc "SELECT count(*) FROM $t;" 2>/dev/null || echo 0)
    if [[ "$n" =~ ^[0-9]+$ ]] && [[ "$n" -ge "$min" ]]; then
        ok "$db.$t = $n (>= $min)"
    else
        err "$db.$t = $n (mong đợi >= $min) — chạy: make seed"
    fi
done

# ----------------------------------------------------------------------------
printf "\n====================================================================\n"
if [[ "$FAIL" -eq 0 ]]; then
    printf "${G}  KẾT QUẢ: TẤT CẢ ĐẠT — hệ thống sẵn sàng demo${N}\n"
    printf "  • Web    : https://localhost/\n"
    printf "  • API    : 8001–8008 ; tài khoản: admin/%s ; khach01/Tenant@12345\n" "$ADMIN_PW"
    printf "  • Grafana: http://localhost:3000/ (admin/%s — dùng chung secret admin_password)\n" "$ADMIN_PW"
    printf "====================================================================\n"
    exit 0
else
    printf "${R}  KẾT QUẢ: %d hạng mục KHÔNG đạt${N}\n" "$FAIL"
    printf "====================================================================\n"
    exit 1
fi
