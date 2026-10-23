# Sơ đồ cơ sở dữ liệu — Hệ thống quản lý phòng trọ (Microservice)

> 8 database độc lập (database-per-service). Trong mỗi DB, các bảng liên kết bằng **Foreign Key thật**. Giữa các DB **không có FK** — chỉ tham chiếu logic qua UUID.
>
> **Mỗi service một role PostgreSQL riêng** (`svc_auth`, `svc_room`, …), không phải superuser, chỉ `CONNECT` được đúng database của mình. Superuser `qlpt` chỉ dùng cho postgres container và sao lưu. Xem `infra/postgres/init/01-roles-and-databases.sh` (cài mới) và `scripts/08-harden-db.sh` (nâng cấp hệ thống đang chạy).

## 1. Tổng quan quan hệ giữa các service (tham chiếu logic)

```mermaid
flowchart LR
  AUTH[(db_auth<br/>users, refresh_tokens,<br/>audit_logs, login_attempts)]
  ROOM[(db_room<br/>properties, buildings,<br/>rooms, amenities)]
  TENANT[(db_tenant<br/>tenants, roommates,<br/>tenant_history)]
  CONTRACT[(db_contract<br/>contracts, contract_payments,<br/>tenants_snapshot)]
  BILLING[(db_billing<br/>invoices, payments,<br/>meter_readings)]
  MAINT[(db_maintenance<br/>incidents,<br/>schedules)]
  NOTIFY[(db_notify<br/>notifications,<br/>templates)]
  REPORT[(db_report<br/>daily_*, monthly_*,<br/>open_invoices)]

  AUTH -. "users.property_id" .-> ROOM
  AUTH -. "users.tenant_id" .-> TENANT
  TENANT -. "property_id, current_room_id" .-> ROOM
  TENANT -. "current_contract_id" .-> CONTRACT
  CONTRACT -. "property_id, room_id" .-> ROOM
  CONTRACT -. "primary_tenant_id" .-> TENANT
  BILLING -. "property_id, room_id" .-> ROOM
  BILLING -. "contract_id" .-> CONTRACT
  BILLING -. "tenant_id" .-> TENANT
  MAINT -. "property_id, room_id" .-> ROOM
  MAINT -. "reported_by_tenant_id" .-> TENANT
  MAINT -. "reported_by_user_id, assigned_to" .-> AUTH
  NOTIFY -. "property_id" .-> ROOM
  NOTIFY -. "tenant_id" .-> TENANT
  REPORT -. "property_id" .-> ROOM
  REPORT -. "contract_id, tenant_id" .-> CONTRACT
```

> `users.tenant_id` là liên kết duy nhất giữa tài khoản đăng nhập và hồ sơ người thuê. auth-service đưa nó vào JWT (claim `tenant_id`); các service khác lọc dữ liệu "của tôi" theo claim này, **không bao giờ** theo tham số client gửi lên.

---

## 2. db_auth — Xác thực & phân quyền

```mermaid
erDiagram
  users {
    uuid id PK
    varchar username "UNIQUE khi deleted_at IS NULL"
    varchar email "UNIQUE khi deleted_at IS NULL"
    varchar password_hash "Argon2id"
    varchar full_name
    varchar phone
    varchar role
    uuid property_id
    uuid tenant_id "UNIQUE khi chưa xoá; bắt buộc với TENANT"
    boolean is_active
    boolean is_locked
    int failed_login_count
    timestamptz locked_until
    timestamptz last_login_at
    timestamptz password_changed_at
    timestamptz created_at
    timestamptz updated_at
    timestamptz deleted_at
  }
  refresh_tokens {
    uuid id PK
    uuid user_id FK
    varchar token_hash UK "SHA-256, không lưu token gốc"
    timestamptz expires_at
    timestamptz revoked_at
    varchar user_agent
    varchar ip_address
    timestamptz created_at
  }
  audit_logs {
    bigint id PK
    uuid actor_id
    varchar actor_username
    varchar actor_role
    varchar action
    varchar resource_type
    varchar resource_id
    json before
    json after
    varchar ip_address
    varchar request_id
    timestamptz created_at
  }
  login_attempts {
    bigint id PK
    uuid user_id
    varchar username_attempted
    varchar ip_address "lấy từ X-Real-IP do nginx đặt"
    varchar user_agent
    boolean success
    varchar failure_reason
    timestamptz created_at
  }

  users ||--o{ refresh_tokens : "has (CASCADE)"
```

> Giữ dữ liệu: `login_attempts` 90 ngày; `refresh_tokens` đã thu hồi/hết hạn 30 ngày (auth-service tự dọn).

---

## 3. db_room — Cơ sở, tòa nhà, phòng

```mermaid
erDiagram
  properties {
    uuid id PK
    varchar name
    text address
    varchar owner_name
    varchar phone
    varchar tax_code
    smallint total_rooms
    text description
    boolean is_active
    timestamptz created_at
    timestamptz updated_at
    timestamptz deleted_at
  }
  buildings {
    uuid id PK
    uuid property_id FK
    varchar name "UNIQUE (property_id, name)"
    varchar note
    timestamptz created_at
  }
  rooms {
    uuid id PK
    uuid property_id FK
    uuid building_id FK "FK kép (building_id, property_id)"
    varchar room_number "UNIQUE (property_id, building_id, room_number)"
    smallint floor
    numeric area_m2
    numeric base_price
    smallint max_occupants
    varchar status
    uuid current_contract_id
    text note
    json photos
    timestamptz created_at
    timestamptz updated_at
    timestamptz deleted_at
  }
  amenities {
    uuid id PK
    varchar code UK
    varchar name
    varchar icon
    numeric default_monthly_fee
    text description
    boolean is_active
    timestamptz created_at
  }
  room_amenities {
    uuid room_id PK,FK
    uuid amenity_id PK,FK
    boolean is_billable
    timestamptz created_at
  }

  properties ||--o{ buildings : "has (RESTRICT)"
  properties ||--o{ rooms : "has (RESTRICT)"
  buildings ||--o{ rooms : "contains (RESTRICT, cùng property_id)"
  rooms ||--o{ room_amenities : "has (CASCADE)"
  amenities ||--o{ room_amenities : "used in (CASCADE)"
```

> **FK kép** `rooms(building_id, property_id) → buildings(id, property_id)`: DB tự bảo đảm phòng và tòa nhà của nó cùng một cơ sở, kể cả khi ai đó ghi thẳng vào DB.
>
> Cơ sở chỉ **xoá mềm**. Xoá cứng một cơ sở còn tòa/phòng bị RESTRICT chặn — trước đây CASCADE từ `properties` mâu thuẫn với RESTRICT từ `buildings → rooms`.

---

## 4. db_tenant — Người thuê & người ở cùng

```mermaid
erDiagram
  tenants {
    uuid id PK
    uuid property_id
    json previous_property_ids
    varchar full_name
    date date_of_birth
    varchar gender
    varchar phone
    varchar email
    text address
    varchar occupation
    text note
    varchar id_card_enc "AES-256-GCM"
    varchar id_card_bidx "UNIQUE (property_id, id_card_bidx) khi chưa xoá"
    varchar id_card_last4
    varchar id_card_front
    varchar id_card_back
    varchar emergency_contact_name
    varchar emergency_contact_phone
    varchar zalo_oa_id
    boolean is_active
    varchar risk_level
    text risk_note
    uuid current_room_id
    uuid current_contract_id
    timestamptz created_at
    timestamptz updated_at
    timestamptz deleted_at
  }
  roommates {
    uuid id PK
    uuid property_id
    uuid room_id
    uuid tenant_id
    varchar full_name
    varchar phone
    boolean is_primary
    timestamptz created_at
    timestamptz deleted_at
  }
  tenant_history {
    bigint id PK
    uuid tenant_id
    uuid property_id
    uuid room_id
    varchar event_type
    json event_data "chỉ 4 số cuối CCCD, không số đầy đủ"
    uuid actor_id
    text note
    timestamptz created_at
  }

  tenants ||--o{ tenant_history : "tracked (logic)"
  tenants ||--o{ roommates : "may be primary (logic)"
```

> `tenant-service` là **service duy nhất** giữ số CCCD đầy đủ (mã hoá) và là service duy nhất được cấp khoá `data_encryption_key`.
>
> CCCD duy nhất **trong từng cơ sở** (không toàn hệ thống): UNIQUE toàn hệ thống cho phép quản lý cơ sở A thử số CCCD để biết người đó có thuê ở cơ sở B không.
>
> **Hai danh sách bạn cùng phòng, hai mục đích khác nhau:** `tenant.roommates` = ai đang **thực sự ở** trong phòng (thay đổi theo thời gian); `contract.contract_roommates` = ai **ký tên** trên hợp đồng (đóng băng lúc ký). Không đồng bộ hai bảng với nhau.

---

## 5. db_contract — Hợp đồng & tiền cọc

```mermaid
erDiagram
  contracts {
    uuid id PK
    varchar contract_no UK
    uuid property_id
    uuid room_id "UNIQUE khi status = 'ACTIVE'"
    uuid primary_tenant_id
    varchar primary_tenant_name
    varchar primary_tenant_phone
    varchar primary_tenant_email
    date start_date
    date end_date "CHECK end_date > start_date"
    numeric monthly_price
    numeric deposit_amount
    timestamptz deposit_paid_at
    numeric deposit_deducted "CHECK 0 ≤ deducted ≤ deposit_amount"
    varchar payment_cycle
    varchar status
    text terminated_reason
    timestamptz terminated_at
    uuid renewed_from_id
    uuid renewed_to_id
    json terms
    varchar document_key
    uuid created_by
    timestamptz created_at
    timestamptz updated_at
    timestamptz activated_at
  }
  contract_payments {
    uuid id PK
    uuid contract_id FK
    numeric amount "CHECK > 0"
    varchar method
    varchar receipt_no
    text note
    uuid received_by
    timestamptz paid_at
  }
  contract_roommates {
    uuid id PK
    uuid contract_id FK
    uuid tenant_id
    varchar full_name
    varchar phone
    varchar id_card_last4 "chỉ 4 số cuối"
    boolean is_guarantor
    timestamptz created_at
  }
  tenants_snapshot {
    uuid id PK
    uuid contract_id FK
    uuid tenant_id
    varchar full_name
    varchar id_card_last4 "chỉ 4 số cuối"
    varchar phone
    varchar email
    text address
    timestamptz captured_at
  }

  contracts ||--o{ contract_payments : "has (RESTRICT)"
  contracts ||--o{ contract_roommates : "has (CASCADE)"
  contracts ||--o{ tenants_snapshot : "snapshot lúc ký (RESTRICT)"
```

> **`uq_contract_active_room`** (partial unique index): mỗi phòng tối đa **một** hợp đồng ACTIVE — ép ở DB, không chỉ ở code.
>
> `tenants_snapshot.contract_id` NULL chỉ còn ở bản ghi cũ không suy ra chắc chắn được hợp đồng.

---

## 6. db_billing — Hóa đơn, thanh toán, điện nước

```mermaid
erDiagram
  invoices {
    uuid id PK
    varchar invoice_no UK
    uuid property_id
    uuid contract_id "UNIQUE (contract_id, period)"
    uuid room_id
    uuid tenant_id
    varchar tenant_name
    varchar room_number
    date period
    numeric rent_amount
    numeric electric_amount
    numeric water_amount
    numeric service_amount
    numeric late_fee_amount
    numeric discount_amount
    numeric deposit_deducted
    numeric total_amount "CHECK ≥ 0"
    numeric paid_amount "CHECK 0 ≤ paid ≤ total"
    varchar status
    date due_date "CHECK due_date ≥ period"
    timestamptz paid_at
    boolean is_final
    uuid created_by
    timestamptz created_at
    timestamptz updated_at
  }
  invoice_details {
    uuid id PK
    uuid invoice_id FK
    varchar item_type
    varchar description
    numeric quantity
    numeric unit_price
    numeric amount
    json breakdown
  }
  payments {
    uuid id PK
    uuid invoice_id FK
    numeric amount "CHECK > 0"
    varchar method
    varchar reference
    varchar receipt_no
    uuid received_by
    timestamptz received_at
    text note
  }
  meter_readings {
    uuid id PK
    uuid property_id
    uuid room_id "UNIQUE (room_id, utility_type, period)"
    varchar utility_type
    date period
    numeric reading_value "CHECK ≥ 0"
    numeric previous_value
    numeric consumption
    uuid read_by
    timestamptz read_at
    text note
  }
  price_tiers {
    uuid id PK
    uuid property_id
    varchar utility_type
    smallint tier_index
    numeric up_to_qty
    numeric unit_price
    date effective_from
    date effective_to
    timestamptz created_at
  }
  service_fees {
    uuid id PK
    uuid property_id
    varchar code "UNIQUE (property_id, code)"
    varchar name
    numeric amount
    boolean is_mandatory
    boolean is_active
    timestamptz created_at
  }
  billing_jobs {
    uuid id PK
    uuid property_id
    date period "UNIQUE (property_id, period)"
    varchar status
    smallint total_contracts
    smallint processed
    smallint succeeded
    smallint failed
    text error
    timestamptz started_at
    timestamptz finished_at
    uuid created_by
    timestamptz created_at
  }

  invoices ||--o{ invoice_details : "has (CASCADE)"
  invoices ||--o{ payments : "has (RESTRICT)"
```

> Thanh toán là **chứng từ tài chính**: xoá hóa đơn còn thanh toán bị RESTRICT chặn. Ghi nhận thanh toán khoá dòng hóa đơn (`SELECT … FOR UPDATE`) để hai người ghi cùng lúc không thu vượt; CHECK `paid_amount ≤ total_amount` là chốt chặn cuối ở DB.

---

## 7. db_maintenance — Sự cố & bảo trì định kỳ

```mermaid
erDiagram
  incidents {
    uuid id PK
    varchar ticket_no UK
    uuid property_id
    uuid room_id "phải thuộc property_id — kiểm khi tạo"
    uuid reported_by_tenant_id "từ JWT, không từ client"
    uuid reported_by_user_id
    varchar reported_by_name
    varchar reported_by_phone
    varchar category
    varchar priority
    varchar title
    text description
    text_array photos
    varchar status
    uuid assigned_to
    varchar assigned_to_name
    timestamptz assigned_at
    timestamptz started_at
    timestamptz resolved_at
    timestamptz closed_at
    text resolution
    numeric cost "CHECK ≥ 0"
    smallint rating
    text rating_comment
    timestamptz created_at
    timestamptz updated_at
    timestamptz deleted_at
  }
  maintenance_schedules {
    uuid id PK
    uuid property_id
    varchar scope
    uuid target_id
    varchar title
    json task_template
    varchar frequency
    date next_due_date
    smallint anchor_day
    timestamptz last_done_at
    int times_completed
    boolean notify_tenants
    text note
    boolean is_active
    timestamptz created_at
    timestamptz updated_at
    timestamptz deleted_at
  }
```

> `room_id` khác DB nên không có FK; maintenance-service hỏi room-service để chắc phòng thuộc đúng cơ sở của người báo. room-service kiểm thêm lần nữa khi nhận `incident.urgent` (phòng thủ hai lớp).

---

## 8. db_notify — Thông báo & mẫu tin

```mermaid
erDiagram
  notifications {
    uuid id PK
    uuid property_id
    uuid tenant_id
    varchar channel
    varchar template_code
    varchar priority
    varchar recipient "email / SĐT / 'tenant:<id>' / 'property:<id>'"
    varchar recipient_name
    varchar subject
    text body
    varchar status
    smallint attempts
    text error
    varchar provider_message
    timestamptz queued_at
    timestamptz sent_at
    timestamptz delivered_at
    timestamptz read_at
    json context
    varchar dedupe_key UK
    timestamptz created_at
  }
  templates {
    varchar code PK
    varchar channel
    varchar name
    varchar subject
    text body "render bằng Jinja2 SandboxedEnvironment"
    varchar description
    boolean is_active
    varchar locale
    timestamptz created_at
    timestamptz updated_at
  }
```

> Mẫu tin lưu trong DB và sửa được qua API, nên **bắt buộc** render trong sandbox: với `Environment` thường, ai ghi được vào `templates` là chạy được lệnh shell trong container.

---

## 9. db_report — Read model (CQRS)

```mermaid
erDiagram
  daily_contract_flow {
    uuid property_id PK
    date stat_date PK
    int created
    int activated
    int terminated
    int expired
    int cancelled
    int renewed
    timestamptz updated_at
  }
  daily_financials {
    uuid property_id PK
    date stat_date PK
    int invoices_issued
    numeric invoiced_amount
    int payments_received
    numeric collected_amount
    numeric refunded_amount
    numeric outstanding
    int overdue_count
    numeric overdue_amount
    timestamptz updated_at
  }
  daily_incident_stats {
    uuid property_id PK
    date stat_date PK
    int created
    int urgent
    int resolved
    numeric cost
    numeric resolution_hours
    timestamptz updated_at
  }
  daily_occupancy {
    uuid property_id PK
    date stat_date PK
    int total_rooms
    int available
    int occupied
    int maintenance
    int reserved
    int other
    varchar source
    timestamptz captured_at
  }
  monthly_financials {
    uuid property_id PK
    varchar period PK
    int invoices_issued
    numeric invoiced_amount
    int payments_received
    numeric collected_amount
    numeric refunded_amount
    int days_covered
    timestamptz updated_at
  }
  open_invoices {
    uuid invoice_id PK
    uuid property_id
    uuid contract_id
    uuid room_id
    uuid tenant_id
    varchar tenant_name
    varchar invoice_no
    varchar period
    numeric total_amount
    numeric paid_amount
    date due_date
    date issued_date
    varchar status
    boolean is_overdue_notified
    timestamptz created_at
    timestamptz updated_at
  }
  sync_runs {
    int id PK
    varchar kind
    uuid property_id
    varchar status
    int rows_synced
    json detail
    text message
    timestamptz started_at
    timestamptz finished_at
    smallint duration_ms
    varchar triggered_by
  }
```

> report-service **không** đọc trực tiếp DB của service khác — chỉ nhận event và gọi API nội bộ. Nhờ vậy role `svc_report` chỉ cần quyền trên `db_report`.

---

## 10. Bảng hạ tầng (có ở MỌI database)

```mermaid
erDiagram
  outbox {
    uuid id PK
    varchar event_type
    jsonb payload
    varchar aggregate_type
    varchar aggregate_id
    varchar correlation_id
    smallint schema_version
    varchar status "NEW → PUBLISHED / FAILED"
    smallint attempts
    timestamptz created_at
    timestamptz published_at
    text last_error
  }
  processed_events {
    uuid event_id PK
    varchar consumer PK
    varchar event_type
    timestamptz processed_at
  }
```

| Bảng | Mục đích | Giữ lại |
|---|---|---|
| `outbox` | Ghi event cùng transaction nghiệp vụ, publisher đẩy lên RabbitMQ — không mất event khi service chết | PUBLISHED: 7 ngày |
| `processed_events` | Consumer bỏ qua event đã xử lý (idempotent). Khoá **(event_id, consumer)** để nhiều consumer trong cùng service không chặn nhau | 30 ngày (> TTL message 7 ngày của RabbitMQ) |

---

## 11. Toàn bộ khoá ngoại thật (trong cùng database)

| DB | Bảng con → bảng cha | ON DELETE | Lý do |
|---|---|---|---|
| db_auth | refresh_tokens → users | CASCADE | Token không có ý nghĩa khi không còn user |
| db_room | buildings → properties | RESTRICT | Cơ sở chỉ xoá mềm |
| db_room | rooms → properties | RESTRICT | Phòng là đích tham chiếu của HĐ/hóa đơn |
| db_room | rooms → buildings | RESTRICT | |
| db_room | rooms(building_id, property_id) → buildings(id, property_id) | RESTRICT | Phòng và tòa cùng cơ sở |
| db_room | room_amenities → rooms / amenities | CASCADE | Bảng nối thuần |
| db_contract | contract_payments → contracts | RESTRICT | Chứng từ thu cọc |
| db_contract | contract_roommates → contracts | CASCADE | Một phần của hợp đồng |
| db_contract | tenants_snapshot → contracts | RESTRICT | Bằng chứng lúc ký |
| db_billing | invoice_details → invoices | CASCADE | Một phần của hóa đơn |
| db_billing | payments → invoices | RESTRICT | Chứng từ tài chính |

## 12. Ràng buộc nghiệp vụ ép ở tầng DB

| Ràng buộc | Bảng | Ý nghĩa |
|---|---|---|
| `uq_contract_active_room` (partial unique) | contracts | Mỗi phòng tối đa 1 hợp đồng ACTIVE |
| `chk_contract_deposit_not_over_used` | contracts | Không trừ cọc quá số đã đặt |
| `uq_invoice_contract_period` | invoices | Mỗi hợp đồng 1 hóa đơn/kỳ — bấm "tính tiền" 2 lần không ra 2 hóa đơn |
| `chk_invoice_paid_not_over_total` | invoices | Không thu vượt |
| UNIQUE (room, utility_type, period) | meter_readings | Mỗi kỳ nhập chỉ số 1 lần |
| `uq_tenant_property_id_card` (partial) | tenants | CCCD duy nhất trong cơ sở, bỏ qua hồ sơ đã xoá |
| `uq_users_*_live` (partial) | users | Username/email/hồ sơ người thuê duy nhất trong tài khoản đang dùng |

---

## 📌 Cách xem sơ đồ

- **GitHub / GitLab**: render Mermaid tự động trong file `.md`.
- **VS Code**: cài extension "Markdown Preview Mermaid Support".
- **Online**: paste vào [mermaid.live](https://mermaid.live).
