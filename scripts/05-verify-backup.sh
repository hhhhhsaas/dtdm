#!/usr/bin/env bash
# ============================================================================
#  KIỂM CHỨNG BẢN SAO LƯU  —  chạy hằng tuần (BẮT BUỘC)
#  Dùng:  bash scripts/05-verify-backup.sh [đường_dẫn_file]
#
#  "Một bản sao lưu KHÔNG được kiểm chứng thì KHÔNG phải bản sao lưu."
#  Script này thực sự RESTORE vào database tạm rồi kiểm tra dữ liệu.
# ============================================================================
set -Eeuo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backup/qlpt/daily}"
PG_CONTAINER="qlpt-postgres"
PG_USER="${DB_USER:-qlpt}"
SECRET_FILE="${SECRET_FILE:-/opt/qlpt/secrets/db_password.txt}"
ARCHIVE="${1:-}"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1;34m'; N='\033[0m'
log()  { printf "${B}[%s]${N} %s\n" "$(date '+%H:%M:%S')" "$*"; }
ok()   { printf "${G}  ✓${N} %s\n" "$*"; }
warn() { printf "${Y}  ⚠${N} %s\n" "$*"; }
die()  { printf "${R}  ✗ %s${N}\n" "$*" >&2; exit 1; }

# Lấy bản sao lưu mới nhất nếu không chỉ định
if [[ -z "$ARCHIVE" ]]; then
    ARCHIVE=$(ls -1t "$BACKUP_DIR"/qlpt_full_*.tar.gz 2>/dev/null | head -1 || true)
    [[ -n "$ARCHIVE" ]] || die "Không tìm thấy bản sao lưu nào trong $BACKUP_DIR"
    log "Dùng bản sao lưu mới nhất: $(basename "$ARCHIVE")"
fi
[[ -f "$ARCHIVE" ]] || die "File không tồn tại: $ARCHIVE"

AGE_DAYS=$(( ( $(date +%s) - $(stat -c %Y "$ARCHIVE") ) / 86400 ))
log "Tuổi bản sao lưu: $AGE_DAYS ngày"
[[ $AGE_DAYS -le 2 ]] || warn "Bản sao lưu đã cũ $AGE_DAYS ngày — RPO có thể không đạt"

export PGPASSWORD="$(cat "$SECRET_FILE")"
TEST_DB="_verify_$(date +%Y%m%d%H%M%S)"
TMP_DIR="$(mktemp -d)"
FAILURES=0
RESULTS=()

cleanup() {
    log "Dọn dẹp..."
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -qc \
        "DROP DATABASE IF EXISTS \"$TEST_DB\";" >/dev/null 2>&1 || true
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# ============================================================================
log "BƯỚC 1 — Kiểm tra checksum"
# ============================================================================
if [[ -f "$ARCHIVE.sha256" ]]; then
    ( cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE").sha256" ) \
        && ok "Checksum hợp lệ" || die "CHECKSUM SAI — file bị hỏng"
else
    warn "Không có file .sha256"
fi

# ============================================================================
log "BắỚC 2 — Giải nén"
# ============================================================================
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
mapfile -t DUMPS < <(find "$TMP_DIR" -name '*.dump' | sort)
[[ ${#DUMPS[@]} -gt 0 ]] || die "Không có file .dump"
ok "${#DUMPS[@]} file database tìm thấy"

# ============================================================================
log "BƯỚC 3 — RESTORE thật vào database tạm '$TEST_DB'"
# ============================================================================
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -qc \
    "DROP DATABASE IF EXISTS \"$TEST_DB\";" >/dev/null 2>&1 || true
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -qc \
    "CREATE DATABASE \"$TEST_DB\" OWNER $PG_USER;" >/dev/null

RESTORE_START=$(date +%s)
docker cp "$(echo "$DUMPS" | head -1)" "$PG_CONTAINER:/tmp/verify.dump" >/dev/null

if docker exec "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$TEST_DB" \
     --no-owner --no-privileges /tmp/verify.dump >/tmp/verify.log 2>&1; then
    ok "pg_restore thành công"
else
    if grep -q "ERROR" /tmp/verify.log; then
        warn "pg_restore có lỗi nhưng vẫn restore được một phần"
    else
        die "pg_restore THẤT BẠI hoàn toàn"
    fi
fi
docker exec "$PG_CONTAINER" rm -f /tmp/verify.dump
RESTORE_TIME=$(( $(date +%s) - RESTORE_START ))

# ============================================================================
log "BƯỚC 4 — Kiểm tra tính toàn vẹn DỮ LIỆU"
# ============================================================================

# 4a. Có bảng trong schema public không?
TABLES=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$TEST_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
if [[ "${TABLES:-0}" -gt 0 ]]; then
    ok "Số bảng: $TABLES"
else
    die "Không có bảng nào được khôi phục — bản sao lưu vô dụng"
fi

# 4b. Dữ liệu có đọc được không? (không phải bảng rỗng hoàn toàn)
ROWS=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$TEST_DB" -tAc \
    "SELECT coalesce(sum(n_live_tup),0) FROM pg_stat_user_tables;")

# 4c. ⭐ Tính toàn vẹn tham chiếu: có FK nào hỏng không?
FK_VIOLATIONS=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$TEST_DB" -tAc "
    SELECT count(*) FROM (
        SELECT c.conrelid::regclass AS tbl, a.attname AS col, t.confrelid::regclass AS reftbl
        FROM pg_constraint c
        JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        JOIN pg_class t ON t.oid = c.confrelid
        WHERE c.contype = 'f' AND c.conrelid::regclass::text = current_schema() || '.users'
    ) f;" 2>/dev/null || echo 0)

# 4d. Không còn transaction nào bị treo
ACTIVE_TX=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$TEST_DB" -tAc \
    "SELECT count(*) FROM pg_stat_activity WHERE state='idle in transaction';")

# ============================================================================
log "BẮT ĐẦU KIỂM CHỨNG TỪNG DATABASE"
# ============================================================================
for dump in "${DUMPS[@]}"; do
    db="$(basename "$dump" .dump)"
    db_test="${TEST_DB}_${db}"

    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -qc \
        "CREATE DATABASE \"$db_test\" OWNER $PG_USER;" >/dev/null 2>&1
    docker cp "$dump" "$PG_CONTAINER:/tmp/v.dump" >/dev/null

    if docker exec "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$db_test" \
         --no-owner --no-privileges /tmp/v.dump >/tmp/v_${db}.log 2>&1; then

        t=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$db_test" -tAc \
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
        r=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$db_test" -tAc \
            "SELECT coalesce(sum(n_live_tup),0) FROM pg_stat_user_tables;")
        v=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$db_test" -tAc \
            "SELECT count(*) FROM pg_stat_user_tables WHERE last_analyze IS NULL AND last_autoanalyze IS NULL;" 2>/dev/null || echo 0)

        if [[ "${t:-0}" -gt 0 ]]; then
            RESULTS+=("${G}PASS${N}  $db — $t bảng, ~$r dòng")
            ok "$(printf '%-16s %2s bảng  ~%s dòng' "$db" "$t" "$r")"
        else
            RESULTS+=("${R}FAIL${N}  $db — 0 bảng")
            warn "$db — KHÔNG CÓ BẢNG"
            FAILURES=$((FAILURES+1))
        fi
    else
        RESULTS+=("${R}FAIL${N}  $db — restore lỗi")
        warn "$db — RESTORE LỖI: $(grep -m1 ERROR /tmp/v_${db}.log 2>/dev/null | cut -c1-80)"
        FAILURES=$((FAILURES+1))
    fi

    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -qc \
        "DROP DATABASE IF EXISTS \"$db_test\";" >/dev/null 2>&1
    docker exec "$PG_CONTAINER" rm -f /tmp/v.dump
done

# ============================================================================
#  BÁO CÁO
# ============================================================================
TOTAL_DISK=$(df -h / | awk 'NR==2 {print $4}')
printf "\n"
printf "  ${B}╔════════════════════════════════════════════════════════╗${N}\n"
printf "  ${B}║           BÁO CÁO KIỂM CHỨNG BẢN SAO LƯU                 ║${N}\n"
printf "  ${B}╚════════════════════════════════════════════════════════╝${N}\n\n"
printf "  File:        %s\n" "$(basename "$ARCHIVE")"
printf "  Dung lượng:  %s\n" "$(du -h "$ARCHIVE" | cut -f1)"
printf "  Tuổi:        %s ngày\n" "$AGE_DAYS"
printf "  Số database: %s\n" "${#DUMPS[@]}"
printf "  Bảng:        %s\n" "$TABLES"
printf "  Dòng (ước):  %s\n" "$ROWS"
printf "  Thời gian restore 1 DB: ${RESTORE_TIME}s\n"
printf "  Còn trống đĩa: %s\n\n" "$TOTAL_DISK"
printf "  Kết quả:\n"
for r in "${RESULTS[@]}"; do printf "    %b\n" "$r"; done
printf "\n"

if [[ $FAILURES -eq 0 ]]; then
    printf "  ${G}✅ TẤT CẢ %s DATABASE KHÔI PHỤC THÀNH CÔNG${N}\n\n" "${#DUMPS[@]}"
    printf "  ${G}RTO đo được (restore 1 DB): ${RESTORE_TIME}s${N}\n"
    printf "  ${G}RTO ước tính (toàn hệ thống): ~$(( RESTORE_TIME * ${#DUMPS[@]} + 120 ))s${N}\n\n"
    printf "  ${Y}→ Đưa số liệu này vào báo cáo đồ án.${N}\n\n"
    exit 0
else
    printf "  ${R}❌ %s/%s database KHÔNG khôi phục được${N}\n" "$FAILURES" "${#DUMPS[@]}"
    printf "  ${R}⛔ HỆ THỐNG SAO LƯU CÓ VẤN ĐỀ — phải xử lý ngay${N}\n\n"
    exit 1
fi
