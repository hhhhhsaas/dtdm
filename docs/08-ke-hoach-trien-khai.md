# CHƯƠNG 8 — KẾ HOẠCH TRIỂN KHAI 6 TUẦN

> Một hệ thống 21 container + 8 microservice **không thể làm xong trong 2 ngày
> cuối**. Chương này chốt **lộ trình 6 tuần** với 5 milestone, tiêu chí nghiệm
> thu đo được bằng lệnh `make`, kịch bản demo trước hội đồng, và bảng rủi ro
> đi kèm phương án dự phòng.

---

## 8.1. Vì sao phải có kế hoạch (bài học quản lý dự án)

Khảo sát các dự án phần mềm thất bại cho thấy 3 nguyên nhân hàng đầu:

| Nguyên nhân | Biểu hiện | Cách phòng trong kế hoạch này |
|---|---|---|
| Phạm vi không rõ | "Làm thêm tính năng X" suốt tuần 5 | **Phạm vi đóng băng** từ tuần 4 — tính năng mới ghi vào backlog, không vào đồ án |
| Không có tiêu chí "xong" | Service "chạy" nhưng sai nghiệp vụ | Mỗi tuần có **milestone + lệnh nghiệm thu** (`make health`, `make test-int`, `make loadtest`) |
| Tích hợp để cuối cùng | 8 service riêng lẻ chạy tốt, ghép lại vỡ | **Tích hợp liên tục**: tuần nào cũng chạy toàn bộ stack, không bao giờ có "bản riêng" |

> **Quy tắc vàng của kế hoạch này:** mỗi milestone phải kết thúc bằng một thứ
> **nhìn thấy và đo được** — không phải "code xong login" mà là "bấm vào SPA,
> đăng nhập bằng admin, thấy dashboard". Bằng chứng này chính là nguyên liệu
> cho slide và demo (chương 9).

---

## 8.2. Mục tiêu & phạm vi (6 tuần)

| | |
|---|---|
| **Mục tiêu** | Triển khai hệ thống QLPT đầy đủ 8 service + scheduler trên 1 Ubuntu server, chứng minh được: kiến trúc microservice, event-driven, CQRS, RBAC, bảo mật, giám sát, sao lưu. |
| **Thời gian** | 6 tuần × 2 buổi/tuần (mỗi buổi ~3 giờ) — hoặc nén 3 tuần nếu làm full-time |
| **Sản phẩm bàn giao** | Hệ thống chạy thật trên server + 10 tài liệu + slide + video demo |
| **KHÔNG làm (out of scope)** | Mobile app native, tích hợp cổng thanh toán thật (chỉ mô phỏng Payment), AI/smart contract, productize |

---

## 8.3. Lộ trình chi tiết 6 tuần

```mermaid
gantt
    title Lộ trình 6 tuần — Hệ thống QLPT
    dateFormat  YYYY-MM-DD
    axisFormat  "Tuần %U"

    section Tuần 1 — Nền móng
    Bootstrap server + Docker + .env + secrets :t1a, 2026-01-05, 1w
    Thư viện dùng chung (JWT, DB, event bus, telemetry) :t1b, 2026-01-05, 1w
    M0: stack trắng chạy, make health 8/8          :milestone, m0, 2026-01-11, 0d

    section Tuần 2 — 3 service đầu
    auth-service (login, RBAC, refresh token)      :t2a, 2026-01-12, 5d
    room-service + tenant-service                   :t2b, 2026-01-12, 5d
    M1: đăng nhập + xem phòng qua nginx            :milestone, m1, 2026-01-18, 0d

    section Tuần 3 — Nghiệp vụ cốt lõi
    billing-service (biểu giá, hóa đơn, thanh toán):t3a, 2026-01-19, 5d
    contract-service + outbox + idempotent          :t3b, 2026-01-19, 5d
    M2: tính tiền tháng ra hóa đơn đúng số          :milestone, m2, 2026-01-25, 0d

    section Tuần 4 — Còn lại
    notification-service (4 kênh)                   :t4a, 2026-01-26, 3d
    maintenance-service                             :t4b, 2026-01-26, 3d
    report-service (CQRS read model) + scheduler    :t4c, 2026-01-26, 5d
    M3: 8/8 service có nghiệp vụ + reconcile        :milestone, m3, 2026-02-01, 0d

    section Tuần 5 — Tích hợp & bằng chứng
    SPA web + API gateway hoàn chỉnh                :t5a, 2026-02-02, 3d
    Smoke test tích hợp + k6 load test              :t5b, 2026-02-02, 4d
    Quét bảo mật Trivy + hardening                  :t5c, 2026-02-02, 4d
    M4: test-int PASS + loadtest đạt SLA            :milestone, m4, 2026-02-08, 0d

    section Tuần 6 — Hoàn thiện
    Diễn tập backup/restore + verify                 :t6a, 2026-02-09, 2d
    Viết 10 tài liệu + slide                         :t6b, 2026-02-09, 4d
    Video demo + tổng duyệt trước hội đồng           :t6c, 2026-02-09, 4d
    M5: Sẵn sàng bảo vệ                              :milestone, m5, 2026-02-15, 0d
```

### Tuần 1 — Nền móng (Milestone M0)

| Việc | Lệnh/chi tiết | Ra được gì |
|---|---|---|
| Cài Ubuntu Server 24.04 + Docker | `scripts/01-bootstrap-ubuntu.sh` | Server sạch, Docker + Compose v2 |
| Tạo `.env` + bí mật ngẫu nhiên | `make env`, `make secrets` | File bí mật quyền 600 |
| Thư viện `common/` | JWT, DB pool, event bus, telemetry, tiền Decimal | 8 service "thân" chung |
| Lớp hạ tầng (postgres, redis, rabbitmq, minio, nginx, prometheus, grafana, loki) | `make up-infra` | 1 lệnh có cả stack giám sát |

> **Mẹo tuần 1:** `docker compose up -d postgres redis rabbitmq minio` nên chạy
> được **ngay ngày đầu**. Nếu hạ tầng ổn định từ đầu, các tuần sau chỉ tập
> trung nghiệp vụ.

### Tuần 2 — 3 service đầu (Milestone M1)

- `auth-service`: đăng nhập, JWT access/refresh, RBAC (ADMIN/MANAGER/TENANT).
- `room-service`: phòng, tầng, tiện ích; `tenant-service`: hồ sơ người thuê.
- Kết nối **nginx** làm gateway → SPA gọi `http://<IP>/api/v1/...`.

**Nghiệm thu tuần 2:** đăng nhập bằng `khach01/Tenant@12345` thấy danh sách
phòng; `khach01` **không** xem được `/rooms` quản trị (trả 403).

### Tuần 3 — Nghiệp vụ cốt lõi (Milestone M2)

Đây là tuần **đắt giá nhất** — toàn bộ số tiền và hóa đơn nằm ở đây:

- `billing-service`: biểu giá điện bậc thang + nước, sinh hóa đơn hàng loạt,
  thanh toán, công nợ; tiền luôn `Decimal`, múi giờ `Asia/Ho_Chi_Minh`.
- `contract-service`: hợp đồng, cọc, gia hạn; phát event qua **outbox**;
  consumer **idempotent**, lỗi đưa **DLQ**.
- **Lệnh chuẩn**: `make seed` (nạp "một câu chuyện" dữ liệu khớp 4 DB) rồi
  `make reconcile` (đối chiếu read model report).

> **Dấu hiệu làm đúng:** 27 hóa đơn của tháng, tổng tiền = tổng (tiền phòng +
> điện + nước + dịch vụ) với từng dòng chi tiết — cộng tay trên giấy đối được.

### Tuần 4 — 3 service còn lại + scheduler (Milestone M3)

- `notification-service`: 4 kênh EMAIL/IN_APP/SMS/ZALO, `DRY_RUN` bật sẵn.
- `maintenance-service`: sự cố, lịch bảo trì.
- `report-service`: **read model CQRS** — tự sync từ event, dashboard tổng hợp.
- `scheduler` (:8009, không publish ra ngoài): nhắc hạn hợp đồng, nhắc tiền,
  reconcile định kỳ.

**Nghiệm thu tuần 4:** khách thuê mở web thấy **badge hộp thư** (IN_APP) có
nhắc hóa đơn; dashboard report bằng đúng số liệu trong từng service (đã
reconcile).

### Tuần 5 — Tích hợp, kiểm thử, bảo mật (Milestone M4)

| Việc | Lệnh | Bằng chứng cho báo cáo |
|---|---|---|
| Giao diện web hoàn chỉnh (6 tab theo role) | Mở `http://<IP>/` | SPA chạy trên nginx |
| Kiểm thử tích hợp 6 nhóm | `make test-int` | Bảng `x/x PASS` in ra |
| Kiểm thử tải k6 (50 VU, 2 phút) | `make loadtest` | `KẾT QUẢ KIỂM THỬ TẢI` + `summary-loadtest.json` |
| Quét lỗ hổng image | `make security` | Báo cáo Trivy HIGH/CRITICAL = 0 |
| Hardening nginx + server | firewall, SSH key, giới hạn cổng | Mục chương 4 |

> **Luật tuần 5:** *không sửa nghiệp vụ* — chỉ sửa lỗi tìm thấy trong kiểm
> thử. Mọi ý tưởng mới ghi vào `BACKLOG.md`, không được chạm vào code chính.

### Tuần 6 — Sao lưu, tài liệu, demo (Milestone M5)

- Diễn tập **khôi phục thảm họa**: `make backup` → `make destroy` (xóa hết dữ
  liệu!) → `make restore F=...` → khách `khach01` vẫn đăng nhập được, hóa đơn
  vẫn còn. Quay video lúc này.
- Hoàn thiện 10 tài liệu + slide + câu hỏi bảo vệ (chương 9).
- Chạy **1 lần tổng duyệt** theo đúng kịch bản demo (mục 8.6).

---

## 8.4. Milestone & tiêu chí nghiệm thu

| MS | Tuần | Tiêu chí "xong" (chứng minh được) | Lệnh kiểm |
|---|---|---|---|
| M0 | 1 | Stack trắng chạy, 8 service + scheduler trả `/health` 200 | `make health` → 9/9 ✅ |
| M1 | 2 | Đăng nhập + xem phòng qua nginx; TENANT bị chặn quản trị | thao tác SPA |
| M2 | 3 | 27 hóa đơn đúng tổng tiền; outbox → event → IN_APP | `make seed` + `make reconcile` + hộp thư |
| M3 | 4 | 8/8 service có nghiệp vụ; dashboard khớp nguồn | `make test-int` (nhóm 4) |
| M4 | 5 | Tất cả 6 nhóm smoke PASS; k6 đạt SLA; Trivy sạch | `make test-int`, `make loadtest`, `make security` |
| M5 | 6 | Backup/restore diễn tập thành công; tài liệu + slide xong | `make verify-backup` |

---

## 8.5. Phân công (nếu làm nhóm 3 người)

| Thành viên | Trách nhiệm chính | Phần tài liệu phụ trách |
|---|---|---|
| A | Hạ tầng, `common/`, auth, nginx, triển khai | Chương 1, 3, 4, 10 |
| B | Billing, contract, event-driven, dữ liệu | Chương 2, 5, 8 |
| C | Notification, maintenance, report, web, giám sát | Chương 6, 7, 9 |
| **Tất cả** | Smoke test tuần 5, diễn tập backup tuần 6, demo | Slide — mỗi người 1/3 |

> Khi 1 người ốm: `common/` + cách "mỗi tuần tích hợp" đảm bảo không ai là
> điểm chết — dữ liệu code luôn nằm chung trên server.

---

## 8.6. Kịch bản demo trước hội đồng (~12 phút)

> Demo là lúc **kiến trúc trở nên nhìn thấy**. Nguyên tắc: *nói ít, bấm thật*,
> và **không bao giờ demo thứ chưa chạy được trước đó** (demo thử 3 lần vào
> tuần 6, đúng máy, đúng mạng).

| # | Thao tác | Câu nói đính kèm | Thời gian |
|---|---|---|---|
| 1 | `make status` — 21 container | "Ảo hóa container — resource pooling trên 1 host" | 1' |
| 2 | `make health` — 9/9 ✅ | "On-demand self-service: 1 lệnh khởi động cả hệ thống" | 1' |
| 3 | Đăng nhập `khach01` → xem hộp thư + hóa đơn | "Người thuê nhận nhắc nợ qua event bus, không phải sửa code" | 2' |
| 4 | Đăng nhập `admin` → dashboard doanh thu | "CQRS: báo cáo đọc từ read model, không đè lên DB ghi" | 2' |
| 5 | Mở Grafana → panel p95 + lỗi | "Measured service: mọi request đều đo được, p95 < 300 ms" | 2' |
| 6 | `make backup` rồi `make verify-backup` | "Sao lưu có kiểm chứng — diễn tập khôi phục đã quay video" | 1' |
| 7 | Mở nginx config → `proxy_cache` + rate limit | "Lớp biên: cache + WAF-lite — mở rộng mà không sửa app" | 1' |
| 8 | Kết: bảng k6 đạt SLA | "Hệ thống chịu 50 người đồng thời, lỗi < 1%" | 1' |

**Fallback nếu sự cố giữa chừng:** luôn có sẵn (a) video demo đã quay sẵn,
(b) ảnh chụp màn hình từng panel, (c) bảng kết quả k6 in ra giấy. Nguyên tắc:
bình tĩnh nói "để em trình chiếu bằng ảnh đã chụp sáng nay" — giám khảo quan
tâm hệ thống, không quan tâm mạng trường.

---

## 8.7. Rủi ro & phương án dự phòng

| Rủi ro | Khả năng | Ảnh hưởng | Phương án |
|---|---|---|---|
| Quên mật khẩu admin trước giờ demo | Thấp | Demo chết nhóm 3 | Mật khẩu nằm trong `secrets/admin_password.txt` + note trên giấy |
| Mất server (trường tắt máy, hết hạn VPS) | Trung bình | Mất toàn bộ | Backup hàng ngày + video đã quay + nhân bản VM |
| Seed sai do chạy lại nhiều lần | Trung bình | Hóa đơn lệch | `make reset-db` + `make seed` + `make reconcile` (đã có sẵn) |
| k6 không đạt ngưỡng phút cuối | Thấp | Mất bằng chứng SLA | Cache nginx + Redis (chương 7) là "phao" chịu tải |
| Giám khảo hỏi câu ngoài phạm vi | Chắc chắn | — | Chương 9 đã chuẩn bị sẵn 30 câu Q&A |
| Mạng trường chặn cổng 8001–8008 | Trung bình | Không mở được API docs | Tất cả ra ngoài qua nginx :80/443 — chỉ mở 2 cổng |

---

## 8.8. Chi phí ước tính (mô phỏng "measured service")

| Hạng mục | Tuỳ chọn rẻ | Tuỳ chọn đủ |
|---|---|---|
| Máy (VPS 8 vCPU/16GB) | Máy cũ trong phòng lab: **0 ₫** | VPS ~500–700 nghìn ₫/tháng |
| Domain + HTTPS | Do `.env` self-signed: **0 ₫** | ~150 nghìn ₫/năm |
| Dung lượng | Ổ SSD 100 GB | +~100 nghìn ₫/tháng |
| Dịch vụ đám mây thật (để so sánh) | — | AWS/GCP tương đương ~2–3 triệu ₫/tháng |

> Đây chính là luận điểm "**Private Cloud rẻ hơn cho quy mô này**": hệ thống
> tự chủ về chi phí và dữ liệu, nhưng vẫn giữ đủ 5 đặc trưng NIST.

---

## 8.9. Checklist trước ngày bảo vệ

**T-3 ngày**
- [ ] `make up` từ trạng thái sạch (đã `make down`) — bấm được trong 3 phút.
- [ ] `make test-int` → toàn bộ PASS, chụp màn hình.

**T-1 ngày**
- [ ] Chạy demo thử đúng phòng họp/thư viện, đúng máy sẽ mang đi.
- [ ] Backup mới nhất + `make verify-backup` xong. Sao chép video demo sang USB.

**T-0 (giờ bảo vệ)**
- [ ] Mở sẵn 4 tab: SPA, Grafana, `make status`, bảng k6.
- [ ] Giấy nháp có sẵn: tài khoản demo, lệnh nhanh, 3 điểm sáng (chương 9).

---

## 8.10. Tổng kết chương

1. Kế hoạch 6 tuần với **5 milestone**, mỗi milestone nghiệm thu bằng lệnh
   cụ thể (`make health`, `make test-int`, `make loadtest`…).
2. Tuần 3 là **trái tim** (tính tiền đúng số) — không được trễ.
3. Tuần 5 **đóng băng phạm vi** và chỉ thu bằng chứng.
4. Demo là **kịch bản đã tập**, có fallback video/ảnh/kết quả in.
5. Rủi ro lớn nhất không phải kỹ thuật mà là **không có bằng chứng** — nên
   mọi milestone đều kết thúc bằng thứ nhìn thấy được.

→ Chương tiếp theo: **slide thuyết trình & câu hỏi bảo vệ**.