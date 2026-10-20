#!/usr/bin/env bash
# ============================================================================
#  KHÔI PHỤC TỪ BẢN SAO LƯU
#  Dùng:  bash scripts/04-restore.sh /backup/qlpt/daily/qlpt_full_20261026_020000.tar.gz
#
#  ⚠⚠⚠  SCRIPT NÀY SẼ GHI ĐÈ DỮ LIỆU HIỆN TẠI ⚠⚠⚠
#      Luôn tự động sao lưu trước khi khôi phục.
# ============================================================================
set -Eeuo pipefail

ARCHIVE="${1:-}"
APP_DIR="${APP_DIR:-/opt/qlpt}"
PG_CONTAINER="qlpt-postgres"
PG_USER="${DB_USER:-qlpt}"
SECRET_FILE="${SECRET_FILE:-$APP_DIR/secrets/db_password.txt}"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'

log()  { printf "${B}[%s]${N} %s\n" "$(date '+%H:%M:%S')" "$*"; }
ok()   { printf "${G}  ✓${N} %s\n" "$*"; }
warn() { printf "${Y}  ⚠${N} %s\n" "$*"; }
die()  { printf "${R}  ✗ %s${N}\n" "$*" >&2; exit 1; }

[[ -n "$ARCHIVE" ]] || die "Dùng: bash $0 <đường dẫn file .tar.gz>"
[[ -f "$ARCHIVE" ]] || die "Không tìm thấy file: $ARCHIVE"

# ============================================================================
log "BƯỚC 0 — Kiểm tra trước khi khôi phục"
# ============================================================================

# 1. Kiểm tra checksum
if [[ -f "$ARCHIVE.sha256" ]]; then
    log "Kiểm tra checksum..."
    ( cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE").sha256" ) \
        || die "CHECKSUM KHÔNG KHỚP — file sao lưu bị hỏng hoặc đã bị sửa đổi"
    ok "Checksum hợp lệ"
else
    warn "Không có file .sha256 — bỏ qua kiểm tra checksum"
fi

# 2. Xác nhận của người dùng
cat <<EOF

${R}╔══════════════════════════════════════════════════════════════╗
║  CẢNH BÁO: THAO TÁC NÀY SẼ GHI ĐÈ TOÀN BỘ DỮ LIỆU HIỆN TẠI      ║
╚══════════════════════════════════════════════════════════════╝${N}

  File:      $ARCHIVE
  Thời điểm: $(date '+%Y-%m-%d %H:%M:%S')
  Dung lượng: $(du -h "$ARCHIVE" | cut -f1)

  ${Y}Hệ thống sẽ dừng trong khoảng 2–5 phút.${N}

EOF
read -rp "Nhập 'RESTORE' (viết HOA) để xác nhận: " CONFIRM
[[ "$CONFIRM" == "RESTORE" ]] || die "Đã hủy thao tác"

# ============================================================================
log "BƯỚC 1 — Sao lưu an toàn dữ liệu HIỆN TẠI trước khi ghi đè"
# ============================================================================
# ⭐ Rất quan trọng: nếu file sao lưu bạn đang khôi phục bị hỏng, bạn
#   vẫn phải có dữ liệu cũ để quay lại.
PRE_BACKUP="$APP_DIR/backup/pre_restore_$(date +%Y%m%d_%H%M%S).tar.gz"
mkdir -p "$(dirname "$PRE_BACKUP")"
log "Đang tạo bản sao lưu an toàn..."
bash "$APP_DIR/scripts/03-backup.sh" >> /var/log/qlpt/backup.log 2>&1 \
    && ok "Đã sao lưu dữ liệu hiện tại" \
    || warn "Sao lưu hiện tại THẤT BẠI (vẫn tiếp tục — bạn tự chịu trách nhiệm)"

# ============================================================================
log "BƯỚC 2 — Dừng các service ứng dụng (giữ PostgreSQL chạy)"
# ============================================================================
cd "$APP_DIR"
docker compose stop auth room tenant contract billing notification maintenance report scheduler 2>/dev/null || true
ok "Đã dừng 8 service + scheduler"

# ============================================================================
log "BƯỚC 3 — Giải nén file sao lưu"
# ============================================================================
RESTORE_DIR="$(mktemp -d)"
trap 'rm -rf "$RESTORE_DIR"' EXIT
tar -xzf "$ARCHIVE" -C "$RESTORE_DIR"
DUMP_COUNT=$(find "$RESTORE_DIR" -name '*.dump' | wc -l)
[[ "$DUMP_COUNT" -gt 0 ]] || die "File sao lưu không chứa file .dump nào"
ok "Đã giải nén $DUMP_COUNT file database"

# ============================================================================
log "BƯỚC 4 — Khôi phục từng database"
# ============================================================================
export PGPASSWORD="$(cat "$SECRET_FILE")"
RESTORE_START=$(date +%s)

for dump in "$RESTORE_DIR"/*.dump; do
    db="$(basename "$dump" .dump)"
    log "  → $db"

    # 1. Ngắt kết nối tới DB (bắt buộc trước khi DROP DATABASE)
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -qc \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
         WHERE datname = '$db' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true

    # 2. Xóa & tạo lại
    if ! docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -qc \
            "DROP DATABASE IF EXISTS \"$db\";" 2>/dev/null; then
        warn "Không DROP được $db — sẽ khôi phục chồng lên dữ liệu cũ"
    else
        docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -qc \
            "CREATE DATABASE \"$db\" OWNER $PG_USER ENCODING 'UTF8';"
    fi

    # 3. Copy file dump vào container
    docker cp "$dump" "$PG_CONTAINER:/tmp/restore.dump"

    # 4. pg_restore. --clean: xóa object cũ trước; --if-exists: bỏ qua lỗi
    #    "2> /tmp/restore.err" để không dừng script khi có cảnh báo
    if docker exec "$PG_CONTAINER" pg_restore \
            -U "$PG_USER" -d "$db" \
            --clean --if-exists --no-owner --no-privileges \
            /tmp/restore.dump > /tmp/restore.out 2>&1; then
        ROWS=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$db" -tAc \
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "?")
        ok "  $db — $ROWS bảng"
    else
        # pg_restore trả về lỗi khi gặp object đã tồn tại — thường vẫn khôi phục được
        ERRORS=$(grep -c "ERROR" /tmp/restore.out 2>/dev/null || echo 0)
        if [[ "$ERRORS" -gt 0 ]]; then
            warn "  $db — $ERRORS lỗi (thường là 'đã tồn tại', thường chấp nhận được)"
            head -5 /tmp/restore.out | sed 's/^/      /'
        else
            die "  $db — KHÔI PHỤC THẤT BẠI"
        fi
    fi

    docker exec "$PG_CONTAINER" rm -f /tmp/restore.dump
done

# ============================================================================
log "BƯỚC 5 — Khôi phục object storage (MinIO)"
# ============================================================================
if [[ -d "$APP_DIR/backup/minio" ]]; then
    MINIO_USER="$(grep '^MINIO_ROOT_USER=' "$APP_DIR/.env" | cut -d= -f2)"
    MINIO_PASS="$(cat "$APP_DIR/secrets/minio_root_password.txt")"
    docker run --rm --network qlpt-data \
        -v "$APP_DIR/backup/minio:/src:ro" -v qlpt_minio_data:/dst \
        --env "MC_HOST_local=http://${MINIO_USER}:${MINIO_PASS}@qlpt-minio:9000" \
        minio/mc:latest sh -c 'mc mirror /src local/ --quiet' 2>/dev/null \
        && ok "MinIO đã khôi phục" || warn "Khôi phục MinIO thất bại (bỏ qua)"
else
    log "  Không có thư mục MinIO trong bản sao lưu — bỏ qua"
fi

# ============================================================================
log "BƯỚC 6 — Khởi động lại hệ thống"
# ============================================================================
docker compose start auth room tenant contract billing notification maintenance report scheduler
ok "Đã khởi động lại các service"
docker compose restart nginx >/dev/null 2>&1 || true

# ============================================================================
log "BƯỚC 7 — Kiểm chứng sau khôi phục"
# ============================================================================
FAILED=0
for p in 8001:auth 8002:room 8003:tenant 8004:contract \
         8005:billing 8006:notification 8007:maintenance 8008:report; do
    port="${p%%:*}"; name="${p##*:}"
    if curl -fsS "http://localhost:$port/health" >/dev/null 2>&1; then
        ok "  $name — healthy"
    else
        warn "  $name — KHÔNG healthy. Xem: docker compose logs $name"
        FAILED=$((FAILED+1))
    fi
done

ELAPSED=$(( $(date +%s) - RESTORE_START ))
printf "\n"
if [[ "$FAILED" -eq 0 ]]; then
    ok "════════════════════════════════════════════════"
    ok " KHÔI PHỤC THÀNH CÔNG  —  ${ELAPSED}s"
    ok " RTO đo được: ${ELAPSED}s"
    ok "════════════════════════════════════════════════"
    log "Ghi nhận RTO này vào báo cáo — đây là số liệu THỰC TẾ, không phải ước lượng."
else
    warn "════════════════════════════════════════════════"
    warn " ${FAILED}/8 service KHÔNG healthy sau khôi phục"
    warn " Kiểm tra: cd $APP_DIR && docker compose logs --tail 100"
    warn "════════════════════════════════════════════════"
fi
printf "\n"
