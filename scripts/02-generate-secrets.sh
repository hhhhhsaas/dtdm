#!/usr/bin/env bash
# ============================================================================
#  TẠO FILE BÍ MẬT NGẪU NHIÊN
#      bash scripts/02-generate-secrets.sh
#  Mỗi mật khẩu sinh bằng /dev/urandom — KHÔNG DÙNG openssl rand khi thiếu
# ============================================================================
set -Eeuo pipefail

SECRET_DIR="${SECRET_DIR:-./secrets}"
mkdir -p "$SECRET_DIR"
chmod 700 "$SECRET_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# Sinh chuỗi ngẫu nhiên từ /dev/urandom, chuyển sang base64 rồi bỏ ký tự đặc biệt
# (bỏ = để tránh vấn đề escape trong .env, connection string, log)
# ⚠️ `|| true`: head đóng ống khi đã đủ N ký tự → tr nhận SIGPIPE → với
#    `set -o pipefail` toàn pipeline báo lỗi 141, làm chết cả script. Chặn lại.
gen_secret() {
    local length="${1:-32}"
    local chars='A-Za-z0-9'
    LC_ALL=C tr -dc "$chars" < /dev/urandom \
      | head -c "$length" || true
}

# Ghi file bí mật chỉ khi chưa tồn tại — KHÔNG ghi đè (giữ bí mật cũ)
create_secret() {
    local filename="$1" length="$2" description="$3"

    if [[ -f "$SECRET_DIR/$filename" ]]; then
        printf "${YELLOW}⚠ Bỏ qua %-26s (đã tồn tại)${NC}\n" "$filename"
        return
    fi

    gen_secret "$length" > "$SECRET_DIR/$filename"
    chmod 600 "$SECRET_DIR/$filename"
    printf "${GREEN}✓ Tạo %-26s (%d ký tự) — %s${NC}\n" "$filename" "$length" "$description"
}

# ⚠️ QUYỀN ĐỌC CHO CONTAINER:
# docker compose (không phải Swarm) BIND-MOUNT file secrets như hiện trạng —
# container chạy non-root (app uid 10001, grafana 472, minio 65532) sẽ bị
# "Permission denied" nếu file là 0600 root. Vì vậy SAU KHI tạo xong, hạ
# quyền xuống 0644 (vẫn chặn GHI). Trên host nhiều người dùng thật nên dùng
# Docker Swarm / rootless + secret engine thay thế (xem docs/06-bao-mat.md).

echo ""
echo "═══ Tạo bí mật trong $SECRET_DIR ═══"
echo ""

create_secret db_password.txt            32  "Mật khẩu superuser PostgreSQL (chỉ cho backup/quản trị)"
# Mỗi service một role DB riêng (không phải superuser). Lộ mật khẩu của
# room-service KHÔNG mở được db_auth hay db_billing.
for svc in auth room tenant contract billing notify maintenance report; do
    create_secret "db_password_${svc}.txt" 32 "Mật khẩu role svc_${svc} (chỉ db_${svc})"
done
create_secret tenant_demo_password.txt   16  "Mật khẩu chung của 12 tài khoản người thuê mẫu"
create_secret jwt_secret.txt             64  "Khóa ký JWT — đỔI => mọi phiên đăng nhập bị vô hiệu"
create_secret admin_password.txt         20  "Mật khẩu tài khoản admin + Grafana"
create_secret minio_root_password.txt    40  "Mật khẩu root của MinIO"
create_secret rabbitmq_password.txt      28  "Mật khẩu RabbitMQ"
# 64 ký tự hex = 256 bit đúng chuẩn AES-256-GCM. `common/crypto.py` ưu tiên
# dạng hex; đổi sang chuỗi ký tự ngẫu nhiên cũng chạy (SHA-256 dẫn xuất) nhưng
# khi đó phải giữ đúng 64 ký tự cho mọi lần sinh lại.
#
# ⭐ CẢNH BÁO: mất file này = mất khả năng giải mã TOÀN BỘ số CCCD đã lưu.
#   Vì vậy nó KHÔNG được commit lên git và BẮT BUỘC nằm trong bản sao lưu
#   (mã hoá) — xem scripts/03-backup.sh và docs/05-du-lieu-sao-luu.md.
create_secret data_encryption_key.txt    64  "Khoá AES-256-GCM mã hoá CCCD — MẤT LÀ MẤT DỮ LIỆU"

echo ""
echo "═══ Danh sách file đã tạo ═══"
ls -la "$SECRET_DIR" | tail -n +2

# Hạ quyền 600 → 644 để container non-root (compose bind-mount nguyên trạng) đọc được
chmod 0644 "$SECRET_DIR"/*.txt 2>/dev/null || true
echo ""
echo "── Quyền sau khi nới cho container đọc (644) ──"

cat <<EOF

${GREEN}════════════════════════════════════════════════════════${NC}

  ${YELLOW}TUYỆT ĐỐI KHÔNG${NC} làm 3 điều sau:
    1. commit thư mục secrets/ lên git
    2. gửi file .env cho bạn bè
    3. đặt mật khẩu yếu như "123456", "admin"

  Kiểm tra .gitignore đã có dòng 'secrets/' chưa:
    grep -q 'secrets/' .gitignore && echo "  ✓ OK" || echo "  ✗ THIẾU trong .gitignore"

  Xem mật khẩu admin:
    cat secrets/admin_password.txt

${GREEN}════════════════════════════════════════════════════════${NC}

  ${YELLOW}BƯỚC CẦN LÀM THỦ CÔNG${NC} — mật khẩu mã hoá bản sao lưu:

    Script này ${YELLOW}KHÔNG${NC} tự sinh file dưới đây. Lý do: một cụm mật
    khẩu sinh tự động mà nằm CÙNG THƯ MỤC với dữ liệu nó bảo vệ thì vô
    nghĩa — lấy được bản sao lưu là có mật khẩu giải mã. Bạn phải tự nhớ
    hoặc cất ở nơi khác (mật khẩu quản lý / USB / két sắt):

      openssl rand -base64 48 > secrets/backup_passphrase.txt
      chmod 600 secrets/backup_passphrase.txt

    Không có file này thì scripts/03-backup.sh vẫn chạy (chỉ database,
    MinIO, cấu hình) nhưng sẽ ${YELLOW}CẢNH BÁO bỏ qua bước sao lưu bí
    mật${NC} — và hệ quả là khôi phục xong không ai đăng nhập được.

${GREEN}════════════════════════════════════════════════════════${NC}

EOF
