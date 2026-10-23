#!/usr/bin/env bash
# ============================================================================
#  KHỞI TẠO DB LẦN ĐẦU — postgres image tự chạy file này khi volume còn trống
#  (/docker-entrypoint-initdb.d). Volume đã có dữ liệu thì KHÔNG chạy lại;
#  hệ thống đang chạy dùng scripts/08-harden-db.sh để chuyển đổi.
#
#  Tạo 8 database + 8 role, mỗi service chỉ đăng nhập được DB của mình:
#    svc_auth → db_auth, svc_room → db_room, …
#
#  ⭐ Vì sao không dùng chung superuser như trước?
#     Superuser đọc/ghi được MỌI database và chạy được `COPY … TO PROGRAM`
#     (thực thi lệnh shell trong container). Một lỗi SQL injection ở bất kỳ
#     service nào khi đó = mất cả hệ thống. Role riêng, không superuser,
#     chỉ CONNECT được đúng DB của mình → lỗ hổng bị nhốt trong 1 service.
#
#  ⭐ Đuôi .sh (không phải .sql) vì .gitignore chặn *.sql — đó là lý do bản
#     cũ của script tạo database chưa từng được commit.
# ============================================================================
set -Eeuo pipefail

for svc in auth room tenant contract billing notify maintenance report; do
    role="svc_${svc}"
    db="db_${svc}"
    pw_file="/run/secrets/db_pw_${svc}"
    if [[ ! -s "$pw_file" ]]; then
        echo "❌ Thiếu $pw_file — chạy scripts/02-generate-secrets.sh trước khi khởi động" >&2
        exit 1
    fi

    # Mật khẩu đưa qua stdin (\set), không nằm trên dòng lệnh của tiến trình.
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
\set role '${role}'
\set db '${db}'
\set pw '$(cat "$pw_file")'
SELECT format('CREATE ROLE %I LOGIN', :'role')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')\gexec
ALTER ROLE :"role" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS CONNECTION LIMIT 40 PASSWORD :'pw';
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'role')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db')\gexec
REVOKE CONNECT, TEMPORARY ON DATABASE :"db" FROM PUBLIC;
GRANT  CONNECT, TEMPORARY ON DATABASE :"db" TO :"role";
SQL
    echo "✓ ${db} (chủ sở hữu ${role})"
done
