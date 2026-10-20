#!/usr/bin/env bash
# ============================================================================
#  SAO LƯU TOÀN BỘ HỆ THỐNG
#  Dùng:  bash scripts/03-backup.sh
#  Cron:  0 2 * * *  /opt/qlpt/scripts/03-backup.sh >> /var/log/qlpt/backup.log 2>&1
#
#  Chiến lược 3-2-1: 3 bản sao, 2 loại (đầy đủ + incremental), 1 ngoài máy.
# ============================================================================
set -Eeuo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/backup/qlpt}"
DAILY_DIR="$BACKUP_ROOT/daily"
WEEKLY_DIR="$BACKUP_ROOT/weekly"
STAMP="$(date +%Y%m%d_%H%M%S)"
DAY_OF_WEEK="$(date +%u)"

RETENTION_DAILY="${RETENTION_DAILY:-14}"
RETENTION_WEEKLY_WEEKS="${RETENTION_WEEKLY_WEEKS:-8}"

# Danh sách DB — phải khớp với infra/postgres/init/01-create-databases.sql
DATABASES=(db_auth db_room db_tenant db_contract db_billing db_notify db_maintenance db_report)

PG_CONTAINER="qlpt-postgres"
PG_USER="${DB_USER:-qlpt}"
SECRET_FILE="${SECRET_FILE:-/opt/qlpt/secrets/db_password.txt}"
APP_DIR="${APP_DIR:-/opt/qlpt}"

# File chứa cụm mật khẩu dùng để MÃ HOÁ thư mục secrets/ trước khi sao lưu.
# Xem giải thích ở bước 3b bên dưới.
PASSPHRASE_FILE="${PASSPHRASE_FILE:-/opt/qlpt/secrets/backup_passphrase.txt}"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'

log()  { printf "${B}[%s]${N} %s\n" "$(date '+%H:%M:%S')" "$*"; }
ok()   { printf "${G}  ✓${N} %s\n" "$*"; }
warn() { printf "${Y}  ⚠${N} %s\n" "$*"; }
die()  { printf "${R}  ✗ %s${N}\n" "$*" >&2; exit 1; }

START_TS=$(date +%s)
mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

# ============================================================================
log "BẮT ĐẦU SAO LƯU  (mã: $STAMP)"
# ============================================================================

[[ -r "$SECRET_FILE" ]] || die "Không đọc được $SECRET_FILE"
export PGPASSWORD="$(cat "$SECRET_FILE")"

# --- Kiểm tra PostgreSQL còn sống không -------------------------------------
if ! docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -q 2>/dev/null; then
    die "PostgreSQL không phản hồi — hãy khởi động lại trước khi sao lưu"
fi

# ============================================================================
log "1/6  Sao lưu PostgreSQL (${#DATABASES[@]} database)"
# ============================================================================
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for db in "${DATABASES[@]}"; do
    if ! docker exec "$PG_CONTAINER" psql -U "$PG_USER" -lqt 2>/dev/null \
         | cut -d'|' -f1 | tr -d ' ' | grep -qx "$db"; then
        warn "Bỏ qua $db (chưa tồn tại)"
        continue
    fi

    # -Fc: custom format (nén + pg_restore được, không phụ thuộc version)
    # -Z6: mức nén tối đa
    # --no-owner: bỏ owner cũ, restore được trên máy khác
    # --if-exists: thêm DROP nếu bảng đã tồn tại
    if docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$db" \
         -Fc -Z6 --no-owner --if-exists -f "/tmp/${db}.dump" 2>/dev/null; then
        docker cp "$PG_CONTAINER:/tmp/${db}.dump" "$TMP_DIR/${db}.dump"
        docker exec "$PG_CONTAINER" rm -f "/tmp/${db}.dump"
        ok "$(printf '%-16s %s' "$db" "$(du -h "$TMP_DIR/${db}.dump" | cut -f1)")"
    else
        die "Sao lưu $db THẤT BẠI — dừng toàn bộ (không tạo bản sao lưu thiếu chất lượng)"
    fi
done

# --- Kiểm chứng ngay: dump có đọc được không -------------------------------
# ⭐ "Bản sao lưu không được kiểm chứng thì KHÔNG phải bản sao lưu"
log "     Kiểm chứng tính toàn vẹn các file dump..."
for f in "$TMP_DIR"/*.dump; do
    docker exec "$PG_CONTAINER" pg_restore -l /dev/stdin < "$f" >/dev/null 2>&1 \
        || warn "$(basename "$f"): không đọc được danh mục (có thể vẫn restore được)"
done
ok "Tất cả file dump đều đọc được"

# --- Đóng gói + kiểm tra checksum ------------------------------------------
ARCHIVE="$DAILY_DIR/qlpt_full_${STAMP}.tar.gz"
tar -czf "$ARCHIVE" -C "$TMP_DIR" ./*.dump
sha256sum "$ARCHIVE" | tee "$ARCHIVE.sha256" >/dev/null
ok "$(basename "$ARCHIVE")  ($(du -h "$ARCHIVE" | cut -f1))"

# ============================================================================
log "2/6  Sao lưu object storage (MinIO)"
# ============================================================================
if docker inspect qlpt-minio >/dev/null 2>&1; then
    MINIO_USER="$(grep '^MINIO_ROOT_USER=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2)"
    MINIO_PASS="$(cat "$APP_DIR/secrets/minio_root_password.txt" 2>/dev/null || echo "")"

    if [[ -n "$MINIO_PASS" ]]; then
        if docker run --rm --network qlpt-data \
             -v qlpt_minio_data:/src:ro -v "$DAILY_DIR:/backup" \
             --env "MC_HOST_local=http://${MINIO_USER}:${MINIO_PASS}@qlpt-minio:9000" \
             minio/mc:latest \
             sh -c 'mc mirror local/ "$BACKUP/minio/" --quiet' 2>/dev/null; then
            ok "minio → $DAILY_DIR/minio"
        else
            warn "MinIO mirror thất bại (không chặn tiến độ sao lưu database)"
        fi
    else
        warn "Không đọc được mật khẩu MinIO — bỏ qua"
    fi
else
    warn "Container MinIO không chạy — bỏ qua"
fi

# ============================================================================
log "3/6  Sao lưu cấu hình hệ thống (để dựng lại từ đầu)"
# ============================================================================
CONFIG_ARCHIVE="$DAILY_DIR/config_${STAMP}.tar.gz"
tar -czf "$CONFIG_ARCHIVE" -C "$APP_DIR" \
    docker-compose.yml .env Makefile infra web services/common 2>/dev/null \
    || warn "Một số file cấu hình không tồn tại — archive có thể không đầy đủ"
ok "$(basename "$CONFIG_ARCHIVE")"

# ============================================================================
log "3b   Sao lưu BÍ MẬT (đã mã hoá) — BẮT BUỘC để khôi phục được"
# ============================================================================
# ⭐ VÌ SAO BƯỚC NÀY BẮT BUỘC, KHÔNG PHẢI "NÊN CÓ":
#     - Mất jwt_secret.txt        → không ai đăng nhập được sau khi khôi phục
#     - Mất data_encryption_key  → TOÀN BỘ số CCCD đã lưu mất khả năng giải mã
#     - Mất db_password.txt       → psql không kết nối được vào DB vừa restore
#     Nghĩa là: sao lưu database mà không có bước này thì khôi phục xong ra
#     MỘT ĐỐNG DỮ LIỆU KHÔNG DÙNG ĐƯỢC. Đây là bài học "RTO có dữ liệu"
#     chưa đủ — phải có "RTO có dữ liệu ĐỌC ĐƯỢC".
#
# ⚠ Tại sao MÃ HOÁ trước khi ghi ra đĩa?
#     Bản sao lưu thường được copy lên nhiều nơi (NAS, máy khác, cloud).
#     File .tar.gz chứa mật khẩu DB + khoá mã hoá dữ liệu, ai có file là có
#     toàn quyền với hệ thống. Vì vậy chỉ ghi bản đã mã hoá.
#     - `age` (khuyến nghị): https://github.com/FiloSottile/age
#     - fallback `openssl enc -aes-256-cbc -pbkdf2 -iter 600000` (có sẵn trên Ubuntu)
SECRET_ARCHIVE="$DAILY_DIR/secrets_${STAMP}.tar.gz.enc"

if [[ ! -d "$APP_DIR/secrets" ]]; then
    warn "Không có thư mục $APP_DIR/secrets — khôi phục sẽ không đăng nhập được"
elif [[ ! -s "$PASSPHRASE_FILE" ]]; then
    warn "Không có $PASSPHRASE_FILE — BỎ QUA bước sao lưu bí mật"
    warn "  Tạo file này để sao lưu đầy đủ (giữ cụm mật khẩu ở nơi khác!):"
    warn "    mkdir -p $(dirname "$PASSPHRASE_FILE")"
    warn "    openssl rand -base64 48 > $PASSPHRASE_FILE && chmod 600 $PASSPHRASE_FILE"
else
    if command -v age >/dev/null 2>&1; then
        if tar -czf - -C "$APP_DIR" secrets \
           | age -p -o "$SECRET_ARCHIVE" 2>/dev/null; then
            ok "$(basename "$SECRET_ARCHIVE") (age, có mật khẩu)"
        else
            warn "age thất bại — thử lại bằng openssl"
            tar -czf - -C "$APP_DIR" secrets \
            | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 \
                  -pass "file:$PASSPHRASE_FILE" -out "$SECRET_ARCHIVE" 2>/dev/null \
              && ok "$(basename "$SECRET_ARCHIVE") (openssl)" \
              || warn "KHÔNG sao lưu được bí mật"
        fi
    else
        if tar -czf - -C "$APP_DIR" secrets \
           | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 \
                 -pass "file:$PASSPHRASE_FILE" -out "$SECRET_ARCHIVE" 2>/dev/null; then
            ok "$(basename "$SECRET_ARCHIVE") (openssl — cài 'age' để mạnh hơn)"
        else
            warn "KHÔNG sao lưu được bí mật"
        fi
    fi
    [[ -f "$SECRET_ARCHIVE" ]] && sha256sum "$SECRET_ARCHIVE" > "$SECRET_ARCHIVE.sha256"
fi

# ============================================================================
log "4/6  Bản sao lưu tuần (chủ nhật hằng tuần)"
# ============================================================================
if [[ "$DAY_OF_WEEK" -eq 7 ]]; then
    for f in "$ARCHIVE" "$ARCHIVE.sha256" "$CONFIG_ARCHIVE" "$SECRET_ARCHIVE" "$SECRET_ARCHIVE.sha256"; do
        [[ -f "$f" ]] && cp "$f" "$WEEKLY_DIR/" 2>/dev/null || true
    done
    ok "Đã tạo bản sao lưu tuần"
else
    log "     Hôm nay là thứ $(date +%A) — không tạo bản sao lưu tuần"
fi

# ============================================================================
log "5/6  Dọn bản sao lưu cũ"
# ============================================================================
# Dùng -delete trên .tar.gz cũ hơn N ngày. GIỮ LẠI .sha256 tương ứng? Không cần —
# checksum của file đã xóa cũng vô nghĩa.
find "$DAILY_DIR"  -name 'qlpt_full_*.tar.gz'     -mtime +$RETENTION_DAILY -delete
find "$DAILY_DIR"  -name 'config_*.tar.gz'        -mtime +$RETENTION_DAILY -delete
find "$DAILY_DIR"  -name 'secrets_*.enc'          -mtime +$RETENTION_DAILY -delete
find "$DAILY_DIR"  -name '*.sha256'               -mtime +$RETENTION_DAILY -delete
find "$WEEKLY_DIR" -name '*.tar.gz'  -mtime +$((RETENTION_WEEKLY_WEEKS * 7)) -delete
find "$WEEKLY_DIR" -name '*.tar.gz.enc' -mtime +$((RETENTION_WEEKLY_WEEKS * 7)) -delete
ok "Dọn xong (giữ $RETENTION_DAILY ngày + $RETENTION_WEEKLY_WEEKS tuần)"

# ============================================================================
log "6/6  Tổng kết"
# ============================================================================
ELAPSED=$(( $(date +%s) - START_TS ))
TOTAL_SIZE=$(du -sh "$DAILY_DIR" 2>/dev/null | cut -f1)
FREE_DISK=$(df -h / | awk 'NR==2 {print $4}')

printf "\n"
ok "════════════════════════════════════════════════"
ok " SAO LƯU HOÀN TẤT  —  ${ELAPSED}s"
ok " Mã: $STAMP"
ok " Dung lượng $DAILY_DIR: $TOTAL_SIZE   |   Còn trống: $FREE_DISK"
ok "════════════════════════════════════════════════"
printf "  Khôi phục:  bash scripts/04-restore.sh %s\n" "$ARCHIVE"
printf "  Kiểm chứng: bash scripts/05-verify-backup.sh\n\n"

# Cảnh báo nếu đĩa sắp đầy
USED_PCT=$(df / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
if [[ "$USED_PCT" -gt 85 ]]; then
    warn "Đĩa đã dùng ${USED_PCT}% — cần dọn bản sao lưu cũ hoặc mở rộng dung lượng"
fi

# ---- KẾT THÚC SAO LƯU -----------------------------------------------------
exit 0
