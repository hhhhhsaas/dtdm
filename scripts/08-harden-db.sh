#!/usr/bin/env bash
# ============================================================================
#  NÂNG CẤP BẢO MẬT + SỬA QUAN HỆ CHO DATABASE ĐANG CHẠY
#
#      bash scripts/02-generate-secrets.sh     # tạo các secret mới (nếu thiếu)
#      bash scripts/08-harden-db.sh            # chạy khi stack CŨ vẫn đang chạy
#      docker compose -f docker-compose.yml -f docker-compose.laptop.yml up -d --build
#
#  Cài mới từ đầu KHÔNG cần script này: infra/postgres/init/ + create_all đã
#  tạo đúng schema. Script dành cho volume pg_data đã có dữ liệu.
#
#  Chạy lại bao nhiêu lần cũng được (idempotent). Mỗi database chạy trong MỘT
#  transaction (psql -1): lỗi ở đâu thì database đó rollback nguyên vẹn.
#
#  Việc làm, theo thứ tự:
#    1. Sửa schema + dữ liệu từng DB (khoá chính processed_events, CASCADE →
#       RESTRICT, CHECK tiền, UNIQUE theo xoá mềm, bỏ CCCD bản rõ, users.tenant_id…)
#    2. Tạo role svc_<service> (KHÔNG superuser), giao quyền sở hữu DB + bảng
#    3. Đặt lại mật khẩu 12 người thuê mẫu theo secrets/tenant_demo_password.txt
#    4. VACUUM FULL bảng từng chứa CCCD bản rõ (xoá hẳn dữ liệu cũ trên đĩa)
# ============================================================================
set -Eeuo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PG_CONTAINER="${PG_CONTAINER:-qlpt-postgres}"
AUTH_CONTAINER="${AUTH_CONTAINER:-qlpt-auth}"
SUPERUSER="${DB_USER:-qlpt}"
SERVICES=(auth room tenant contract billing notify maintenance report)

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1m'; N='\033[0m'
step() { printf "\n${B}▶ %s${N}\n" "$*"; }
ok()   { printf "${G}  ✓ %s${N}\n" "$*"; }
fail() { printf "${R}  ✗ %s${N}\n" "$*" >&2; exit 1; }

psql_db() {   # $1 = database; SQL đọc từ stdin, toàn bộ trong 1 transaction
    docker exec -i "$PG_CONTAINER" psql -X -q -1 -v ON_ERROR_STOP=1 -U "$SUPERUSER" -d "$1"
}

# ----------------------------------------------------------------------------
step "Kiểm tra điều kiện"
docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER" || fail "Container $PG_CONTAINER chưa chạy"
for svc in "${SERVICES[@]}"; do
    [[ -s "secrets/db_password_${svc}.txt" ]] || fail "Thiếu secrets/db_password_${svc}.txt — chạy scripts/02-generate-secrets.sh"
done
[[ -s secrets/tenant_demo_password.txt ]] || fail "Thiếu secrets/tenant_demo_password.txt — chạy scripts/02-generate-secrets.sh"
ok "Đủ secret, postgres đang chạy"

# ----------------------------------------------------------------------------
#  SQL dùng chung cho mọi DB
# ----------------------------------------------------------------------------
# pg_temp.fk_restrict: đổi khoá ngoại ON DELETE CASCADE của 1 cột sang RESTRICT
# (giữ nguyên tên constraint). Đã là RESTRICT rồi thì không làm gì.
read -r -d '' PRELUDE <<'SQL' || true
CREATE OR REPLACE FUNCTION pg_temp.fk_restrict(tbl regclass, col text, ref text)
RETURNS void LANGUAGE plpgsql AS $f$
DECLARE c text;
BEGIN
    SELECT conname INTO c FROM pg_constraint
     WHERE conrelid = tbl AND contype = 'f' AND confdeltype = 'c'
       AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                           WHERE attrelid = tbl AND attname = col)];
    IF c IS NOT NULL THEN
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', tbl, c);
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES %s ON DELETE RESTRICT',
                       tbl, c, col, ref);
    END IF;
END $f$;

-- processed_events: khoá (event_id, consumer) thay vì chỉ event_id
-- outbox: bỏ sự kiện đã gửi quá 7 ngày (payload chứa dữ liệu cá nhân)
DO $$
BEGIN
    IF to_regclass('public.processed_events') IS NOT NULL AND EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'processed_events_pkey'
           AND conrelid = 'public.processed_events'::regclass) THEN
        ALTER TABLE processed_events DROP CONSTRAINT processed_events_pkey;
        ALTER TABLE processed_events
            ADD CONSTRAINT pk_processed_events PRIMARY KEY (event_id, consumer);
    END IF;
    IF to_regclass('public.outbox') IS NOT NULL THEN
        DELETE FROM outbox WHERE status = 'PUBLISHED'
                             AND published_at < now() - interval '7 days';
    END IF;
END $$;
SQL

declare -A SQL

SQL[auth]=$(cat <<'SQL'
-- Liên kết tài khoản TENANT ↔ hồ sơ người thuê (trước đây chỉ là quy ước trùng UUID)
ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id uuid;
UPDATE users SET tenant_id = id WHERE role = 'TENANT' AND tenant_id IS NULL;

-- UNIQUE chỉ trên tài khoản chưa xoá mềm
DROP INDEX IF EXISTS ix_users_username;
DROP INDEX IF EXISTS ix_users_email;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_key;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;
CREATE INDEX IF NOT EXISTS ix_users_username ON users (username);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_live ON users (username) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_live ON users (email) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_live ON users (tenant_id)
    WHERE tenant_id IS NOT NULL AND deleted_at IS NULL;

-- Giới hạn thời gian giữ IP/User-Agent và token đã chết
DELETE FROM login_attempts WHERE created_at < now() - interval '90 days';
DELETE FROM refresh_tokens WHERE revoked_at < now() - interval '30 days'
                              OR expires_at < now() - interval '30 days';
SQL
)

SQL[tenant]=$(cat <<'SQL'
-- CCCD duy nhất trong TỪNG cơ sở, bỏ qua hồ sơ đã xoá (hết dò chéo cơ sở)
ALTER TABLE tenants DROP CONSTRAINT IF EXISTS uq_tenant_id_card;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_property_id_card ON tenants (property_id, id_card_bidx)
    WHERE deleted_at IS NULL AND id_card_bidx IS NOT NULL;
SQL
)

SQL[contract]=$(cat <<'SQL'
ALTER TABLE tenants_snapshot  ADD COLUMN IF NOT EXISTS contract_id uuid;
ALTER TABLE tenants_snapshot  ADD COLUMN IF NOT EXISTS id_card_last4 varchar(4);
ALTER TABLE contract_roommates ADD COLUMN IF NOT EXISTS id_card_last4 varchar(4);

-- Bỏ CCCD bản rõ: chỉ giữ 4 số cuối (số đầy đủ đã mã hóa ở tenant-service)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'tenants_snapshot' AND column_name = 'id_card_number') THEN
        UPDATE tenants_snapshot SET id_card_last4 = right(id_card_number, 4)
         WHERE id_card_number IS NOT NULL AND id_card_last4 IS NULL;
        ALTER TABLE tenants_snapshot DROP COLUMN id_card_number;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'contract_roommates' AND column_name = 'id_card_number') THEN
        UPDATE contract_roommates SET id_card_last4 = right(id_card_number, 4)
         WHERE id_card_number IS NOT NULL AND id_card_last4 IS NULL;
        ALTER TABLE contract_roommates DROP COLUMN id_card_number;
    END IF;
END $$;

-- Gắn bản chụp với hợp đồng: chỉ khi người thuê có ĐÚNG 1 hợp đồng đã ký
-- (bản chụp không tạo cho DRAFT). Không suy ra chắc chắn thì để NULL.
UPDATE tenants_snapshot s SET contract_id = c.id
  FROM contracts c
 WHERE s.contract_id IS NULL AND c.primary_tenant_id = s.tenant_id AND c.status <> 'DRAFT'
   AND (SELECT count(*) FROM contracts c2
         WHERE c2.primary_tenant_id = s.tenant_id AND c2.status <> 'DRAFT') = 1;
CREATE INDEX IF NOT EXISTS ix_tenants_snapshot_contract_id ON tenants_snapshot (contract_id);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tenants_snapshot_contract_id_fkey') THEN
        ALTER TABLE tenants_snapshot ADD CONSTRAINT tenants_snapshot_contract_id_fkey
            FOREIGN KEY (contract_id) REFERENCES contracts (id) ON DELETE RESTRICT;
    END IF;
END $$;

-- Phiếu thu cọc là chứng từ: không bị xoá theo hợp đồng
SELECT pg_temp.fk_restrict('contract_payments', 'contract_id', 'contracts(id)');
SQL
)

SQL[billing]=$(cat <<'SQL'
-- Thanh toán là chứng từ: không bị xoá theo hóa đơn
SELECT pg_temp.fk_restrict('payments', 'invoice_id', 'invoices(id)');
-- Chặn thu vượt ở tầng DB
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_invoice_paid_not_over_total') THEN
        ALTER TABLE invoices ADD CONSTRAINT chk_invoice_paid_not_over_total
            CHECK (paid_amount <= total_amount);
    END IF;
END $$;
SQL
)

SQL[room]=$(cat <<'SQL'
-- Bỏ 2 đường xoá mâu thuẫn (properties CASCADE vs buildings→rooms RESTRICT)
SELECT pg_temp.fk_restrict('buildings', 'property_id', 'properties(id)');
SELECT pg_temp.fk_restrict('rooms', 'property_id', 'properties(id)');
-- Phòng và tòa nhà của nó phải cùng cơ sở (khoá ngoại kép)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_building_id_property') THEN
        ALTER TABLE buildings ADD CONSTRAINT uq_building_id_property UNIQUE (id, property_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_room_building_same_property') THEN
        ALTER TABLE rooms ADD CONSTRAINT fk_room_building_same_property
            FOREIGN KEY (building_id, property_id) REFERENCES buildings (id, property_id)
            ON DELETE RESTRICT;
    END IF;
END $$;
SQL
)

SQL[notify]=$(cat <<'SQL'
-- recipient của IN_APP: hộp thư có tiền tố, không còn là UUID trơn mơ hồ
UPDATE notifications SET recipient = 'tenant:' || recipient
 WHERE channel = 'IN_APP' AND tenant_id IS NOT NULL AND recipient = tenant_id::text;
UPDATE notifications SET recipient = 'property:' || recipient
 WHERE channel = 'IN_APP' AND property_id IS NOT NULL AND recipient = property_id::text;
SQL
)

# ----------------------------------------------------------------------------
step "1/4  Sửa schema + dữ liệu từng database"
for svc in "${SERVICES[@]}"; do
    printf '%s\n%s\n' "$PRELUDE" "${SQL[$svc]:-}" | psql_db "db_${svc}"
    ok "db_${svc}"
done

# ----------------------------------------------------------------------------
step "2/4  Role riêng cho từng service + giao quyền sở hữu"
for svc in "${SERVICES[@]}"; do
    # Mật khẩu đi qua stdin (\set), không xuất hiện trên dòng lệnh tiến trình.
    vars=$(printf "\\\\set role 'svc_%s'\n\\\\set db 'db_%s'\n\\\\set pw '%s'\n" \
                  "$svc" "$svc" "$(cat "secrets/db_password_${svc}.txt")")
    { printf '%s\n' "$vars"; cat <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'role')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')\gexec
ALTER ROLE :"role" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS CONNECTION LIMIT 40 PASSWORD :'pw';
ALTER DATABASE :"db" OWNER TO :"role";
REVOKE CONNECT, TEMPORARY ON DATABASE :"db" FROM PUBLIC;
GRANT  CONNECT, TEMPORARY ON DATABASE :"db" TO :"role";
SQL
    } | psql_db postgres

    # Bảng/sequence/kiểu do superuser tạo trước đây → chuyển cho role service.
    # (Không dùng REASSIGN OWNED: lệnh đó đổi cả chủ các DATABASE khác.)
    { printf '%s\n' "$vars"; cat <<'SQL'
SELECT format('ALTER TABLE public.%I OWNER TO %I', tablename, :'role')
  FROM pg_tables WHERE schemaname = 'public'\gexec
SELECT format('ALTER SEQUENCE public.%I OWNER TO %I', c.relname, :'role')
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'S'
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a', 'i'))\gexec
SELECT format('ALTER VIEW public.%I OWNER TO %I', viewname, :'role')
  FROM pg_views WHERE schemaname = 'public'\gexec
SELECT format('ALTER TYPE public.%I OWNER TO %I', t.typname, :'role')
  FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
 WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd')\gexec
SQL
    } | psql_db "db_${svc}"
    ok "svc_${svc} sở hữu db_${svc} (không superuser, chỉ CONNECT được DB này)"
done

# ----------------------------------------------------------------------------
step "3/4  Đặt lại mật khẩu người thuê mẫu (bỏ mật khẩu công khai Tenant@12345)"
if [[ "${SKIP_TENANT_RESET:-0}" == "1" ]]; then
    printf "${Y}  ⚠ Bỏ qua (SKIP_TENANT_RESET=1)${N}\n"
elif ! docker ps --format '{{.Names}}' | grep -qx "$AUTH_CONTAINER"; then
    printf "${Y}  ⚠ $AUTH_CONTAINER chưa chạy — bỏ qua, chạy lại script sau khi stack lên${N}\n"
else
    TENANT_PW="$(cat secrets/tenant_demo_password.txt)"
    mapfile -t TENANTS < <(docker exec "$PG_CONTAINER" psql -X -tA -U "$SUPERUSER" -d db_auth \
        -c "SELECT username FROM users WHERE role = 'TENANT' AND deleted_at IS NULL ORDER BY username")
    for u in "${TENANTS[@]}"; do
        [[ -n "$u" ]] || continue
        # Băm trong container auth (Argon2id, cùng tham số với service). Mỗi
        # tài khoản một salt riêng nên mỗi người một hash khác nhau.
        h=$(printf '%s' "$TENANT_PW" | docker exec -i "$AUTH_CONTAINER" python -c \
            "import sys; from common.security import hash_password; print(hash_password(sys.stdin.read()))")
        printf "\\\\set u '%s'\n\\\\set h '%s'\nUPDATE users SET password_hash = :'h', password_changed_at = now(), failed_login_count = 0, is_locked = false WHERE username = :'u';\n" \
            "$u" "$h" | psql_db db_auth
    done
    ok "${#TENANTS[@]} tài khoản người thuê — mật khẩu mới: secrets/tenant_demo_password.txt"
fi

# ----------------------------------------------------------------------------
step "4/4  Xoá hẳn CCCD bản rõ khỏi đĩa"
# DROP COLUMN chỉ đánh dấu cột đã xoá; dữ liệu cũ còn nằm trong trang dữ liệu
# tới khi bảng được ghi lại. VACUUM FULL viết lại bảng (không chạy trong
# transaction nên gọi riêng).
docker exec "$PG_CONTAINER" psql -X -q -U "$SUPERUSER" -d db_contract \
    -c "VACUUM FULL tenants_snapshot, contract_roommates;"
ok "tenants_snapshot, contract_roommates đã được viết lại"

cat <<EOF

${G}${B}Xong.${N} Bước tiếp theo — khởi động lại stack để service dùng role mới:

    docker compose -f docker-compose.yml -f docker-compose.laptop.yml up -d --build
    make health

${Y}Lưu ý:${N} các bản sao lưu CŨ (backups/) và file dump trên GitHub vẫn chứa
CCCD bản rõ + hash mật khẩu cũ. Xoá hoặc mã hoá chúng riêng.
EOF
