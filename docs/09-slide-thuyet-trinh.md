# CHƯƠNG 9 — SLIDE THUYẾT TRÌNH & BẢO VỆ

> Phần lớn đồ án rớt không phải vì code sai mà vì **không thuyết phục được
> hội đồng**. Chương này cho: cấu trúc **12 slide trong 15 phút**, 3 ⭐ điểm
> sáng kiến trúc để "khoe" đúng chỗ, và **30 câu hỏi bảo vệ dự kiến kèm đáp
> án** — vì giám khảo giỏi thường hỏi *tại sao*, không hỏi *cái gì*.

---

## 9.1. Nguyên tắc vàng khi thuyết trình

| Nguyên tắc | Vì sao |
|---|---|
| 15 phút = **12 phút nói + 3 phút đệm** | Chậm rãi, thở, dừng ở sơ đồ quan trọng |
| **1 slide = 1 ý**. Nhiều nhất 5 dòng chữ | Không ai đọc được slide lúc nghe nói |
| Sơ đồ **Mermaid** > bảng > bullet > đoạn văn | Sơ đồ là "bản đồ trí nhớ" giúp người nghe theo kịp |
| Nói **con số**, không nói "nhanh/cao/tốt" | "p95 212 ms, lỗi 0,4%" thuyết phục hơn "rất nhanh" |
| **Code chỉ hiện khi được hỏi** | 12 phút không đủ để đọc code; để dành cho phần hỏi |
| Demo nằm **giữa bài**, không nằm cuối | Ngắt nhịp, tạo ấn tượng trước khi hỏi đáp |

---

## 9.2. Cấu trúc 12 slide (15 phút)

| # | Slide | Nội dung tối đa 5 dòng | Điểm nhấn | Phút |
|---|---|---|---|---|
| 1 | Bìa | Tên đồ án, tên SV, lớp | Không cần giới thiệu bản thân dài | 0,5 |
| 2 | Bài toán | 200 phòng, 2.000 người thuê; hóa đơn sai, nhọc công thu tiền | Số liệu thực tế | 1 |
| 3 | Giải pháp 1 câu | "Microservice trên private cloud, Docker hóa, tự quản" | Ảnh kiến trúc tổng (README §5) | 1 |
| 4 | **6 đặc trưng NIST** | Bảng ánh xạ 5 đặc trưng cloud (README §7) | ⭐ **Đây là sườn để giám khảo hỏi** | 1,5 |
| 5 | Bóc tách 8 service | Bảng trách nhiệm + database riêng + cổng | Mỗi service 1 DB = khác monolith | 1,5 |
| 6 | Event-driven | Mermaid outbox → RabbitMQ → consumer idempotent → DLQ | ⭐ Vẽ tay luồng 1 event `invoice.created` | 2 |
| 7 | CQRS + Saga | Mermaid read model report + saga thanh toán | ⭐ Tách đọc/ghi, đối chiếu `make reconcile` | 1,5 |
| 8 | Bảo mật | 3 ý: JWT RBAC multi-tenant · AES-256-GCM CCCD + blind index · token SYSTEM | ⭐ 3 điểm sáng bảo mật (mục 9.4) | 1,5 |
| 9 | **Demo (8 bước)** | Kịch bản chương 8.6 — bấm thật | ⭐ Bằng chứng sống | 3 |
| 10 | Giám sát + SLA | Grafana p95, K6 50 VU, bảng kết quả | Con số thật: p95, % lỗi | 1 |
| 11 | Sao lưu + mở rộng | RPO/RTO, diễn tập restore, scale theo triệu chứng | Video restore 30 giây | 1 |
| 12 | Kết | Tóm tắt 3 ⭐ + "cảm ơn, mời thầy/cô hỏi" | Không thêm ý mới ở slide cuối | 0,5 |

> **Bố cục bài nói:** ① Vì sao (slide 2–3) ② Làm thế nào (4–8) ③ Bằng chứng
> (9–11). Giám khảo chỉ nhớ 3 điều: *vi diệu ở đâu, rủi ro gì, đo bằng gì*.

---

## 9.3. Quy tắc trình bày kỹ thuật

- **Vẽ, không đọc**: mọi mermaid trong `docs/` đều có thể paste thẳng vào slide
  (GitHub/VS Code render sẵn, đừng chụp ảnh mờ).
- **Số > chữ**: mỗi lần nói tính từ cường điệu, thay bằng số: 21 container, 8
  service, 9/9 health, 50 VU, p95 < 300 ms, 0 CVE HIGH.
- **Trả lời 3 câu hỏi ngầm của hội đồng**:
  1. *Đây có phải microservice thật không?* → đưa database-per-service + event bus.
  2. *Có chạy được không?* → demo + k6 + test-int.
  3. *Hiểu sâu hay chỉ ghép code?* → trả lời tốt phần "tại sao" ở 9.5.

---

## 9.4. ⭐ Ba điểm sáng nên "khoe" khi được hỏi

Khi giám khảo hỏi *"Điểm khác biệt so với đồ án cùng đề tài?"* — đây là 3 vũ
khí, kèm code đã có trong dự án (đừng nói suông):

### ⭐ 1. Token nội bộ SYSTEM — service gọi service "có chủ quyền"

```python
# services/common/security.py
def create_internal_token(caller: str | None = None) -> str:
    name = caller or "job"
    # uuid5 TẤT ĐỊNH từ tên → mỗi service luôn mang cùng 1 sub,
    # dễ truy vết "ai đã gọi", không cần user thật trong DB.
    return create_token(
        user_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"qlpt-service.{name}"),
        role=Role.SYSTEM,
    )
```

> **Cách kể:** "Job nền reconcile (scheduler/report) cần gọi API nội bộ nhưng
> không có user trong bảng login. Thay vì làm 'user hệ thống' giả trong DB, em
> phát token ký JWT với role SYSTEM — mọi lời gọi đều có định danh và bị
> `require_roles(Role.SYSTEM)` chặn."

### ⭐ 2. Mã hóa CCCD bằng AES-256-GCM — vẫn tìm kiếm được nhờ blind index

```python
# services/common/crypto.py
def encrypt(plaintext: str | None) -> str | None:
    nonce = os.urandom(NONCE_SIZE)          # nonce ngẫu nhiên 12 byte MỖI lần
    ct = cipher.encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"{PREFIX}${base64.urlsafe_b64encode(nonce + ct).decode('ascii')}"

def blind_index(value: str | None) -> str | None:
    # HMAC-SHA256(khoá_tách biệt, CCCD_chuẩn_hoá) — tìm đúng người thuê
    # theo CCCD trên INDEX mà không bao giờ lộ plaintext.
```

> **Cách kể:** "CCCD là dữ liệu nhạy → mã hóa GCM 256 bit. Nhưng mã hóa ngẫu
> nhiên hóa làm mất khả năng WHERE theo CCCD → em thêm cột blind index (HMAC
> bằng khóa riêng). Đánh đổi biết trước: lộ độ dài chuỗi — em đã phân tích
> trong chương 6. Nếu hỏi 'tại sao không dùng hẳn deterministic encryption?'
> thì đáp: nó yếu hơn GCM khi hash bị tấn công."

### ⭐ 3. Kênh thông báo là adapter — thêm kênh không sửa nghiệp vụ

```python
# services/notification/channels.py
CHANNELS = {"EMAIL": EmailChannel(), "IN_APP": InAppChannel(),
            "SMS": SmsChannel(),     "ZALO": ZaloChannel()}
# …nghiệp vụ chỉ biết:
channel.send(notification=..., context=...)
```

> **Cách kể:** "Hộp thư trong app (IN_APP) miễn phí + đo được đã đọc; email/SMS/
> Zalo chỉ là adapter. Muốn thêm Telegram: 1 enum + 1 lớp + 1 dòng đăng ký.
> Gửi thử an toàn nhờ `NOTIFICATION_DRY_RUN` — chạy cả luồng nhưng không gửi
> thật." (chi tiết: chương 7.4–7.5)

---

## 9.5. Câu hỏi bảo vệ dự kiến — 30 câu & cách trả lời

### A. Nền tảng Cloud Computing

| # | Câu hỏi | Đáp án gợi ý (từ tài liệu) |
|---|---|---|
| 1 | Vì sao đây là *private cloud*? | Tự vận hành hạ tầng trên server riêng, đủ 5 đặc trưng NIST SP 800-145; dữ liệu không qua bên thứ ba (chương 1) |
| 2 | Chứng minh **resource pooling**? | 8 service + Postgres + Nginx… chạy chung 1 host qua Docker, CPU/RAM gộp lại và chia theo nhu cầu (README §7) |
| 3 | **Rapid elasticity** trong hệ thống? | `docker compose up -d --scale billing=3` — nhân bản không đổi code; nginx upstream cân bằng tải (chương 7) |
| 4 | **Measured service** đo gì? | Prometheus scrape `/metrics` 15s; dashboard "hóa đơn ảo" theo số request; k6 đo p95 (chương 7) |
| 5 | Sao gọi là **on-demand self-service**? | `make up` tự build, tự seed, tự healthcheck — không cần quản trị hạ tầng can thiệp từng bước |
| 6 | Vì sao không dùng cloud công cộng? | Chi phí quy mô nhỏ tự host rẻ hơn (chương 8.8); còn câu hỏi *khi nào nên lên public cloud* → khi cần khả năng co giãn vô hạn và đội vận hành chuyên nghiệp |

### B. Kiến trúc Microservice

| # | Câu hỏi | Đáp án gợi ý |
|---|---|---|
| 7 | Vì sao 8 service, không 3 hay 15? | Theo bounded context (chương 2): 1 service = 1 lĩnh vực có vòng đời riêng; ít hơn gộp domain khác nhau, nhiều hơn thừa chi phí giao tiếp |
| 8 | Database-per-service lợi hại gì? | Lợi: không ai phá schema người khác, scale độc lập, chọn DB riêng. Hại: mất JOIN xuyên service → phải dùng event + CQRS để bù |
| 9 | Vì sao chọn **event-driven** hơn gọi REST? | Khớp với nghiệp vụ "hóa đơn sinh ra → nhiều nơi cần biết"; chịu lỗi tốt, không chặn request. REST giữ cho việc cần kết quả tức thời (đăng nhập) |
| 10 | OUTBOX để làm gì? | Đảm bảo **atomic**: ghi hóa đơn + publish event cùng 1 transaction → không mất event nếu crash giữa chừng (chương 2) |
| 11 | Idempotent consumer nghĩa là gì? | Event bị gửi lại (retry) không gây trùng lặp — lưu `processed_event_id` để bỏ qua event đã xử lý (chương 2) |
| 12 | **Saga** giải quyết gì? | Giao dịch trải 2 service (đặt cọc → hóa đơn → thanh toán) không có transaction phân tán; saga bù trừ khi bước giữa thất bại (chương 3) |
| 13 | API Gateway trong hệ thống ở đâu? | Nginx: TLS, rate limit, routing `/api/v1/*`, cache, serve SPA — lợi: 1 điểm kiểm soát, dịch vụ phía sau đổi port không ảnh hưởng client |
| 14 | Vì sao giao tiếp đồng bộ vẫn còn? | Một số ca cần kết quả ngay (login, tra cứu phòng trống); trả lời: *dùng đồng bộ cho query, bất đồng bộ cho sự kiện* |

### C. Dữ liệu & nhất quán

| # | Câu hỏi | Đáp án gợi ý |
|---|---|---|
| 15 | Tiền lưu kiểu gì? | `Decimal` + lưu **số nguyên theo xu** (hoặc numeric(18,2)) — không bao giờ float vì sai số làm lệch tiền; tiền tệ VND cố định |
| 16 | Múi giờ xử lý thế nào? | `Asia/Ho_Chi_Minh` ở tầng ứng dụng, DB lưu `timestamptz` — hóa đơn "ngày 1 tháng" đúng theo giờ VN không lệch UTC |
| 17 | Hai service cùng sửa 1 phòng? | Không — mỗi dòng thuộc đúng 1 service; thay đổi phòng qua room-service, các service khác lắng nghe event |
| 18 | Reconcile (`make reconcile`) là gì? | Đối chiếu read model report với nguồn qua event; phát hiện mất sync do crash giữa chừng — bằng chứng CQRS thực thi (chương 2, 8) |
| 19 | Làm sao backup 8 DB khớp nhau? | Backup **cùng thời điểm** gần nhất + khôi phục theo thứ tự phụ thuộc; kịch bản diễn tập trong chương 5 và 8 |

### D. Bảo mật

| # | Câu hỏi | Đáp án gợi ý |
|---|---|---|
| 20 | JWT bị đánh cắp thì sao? | Access token ngắn (ví dụ 15 phút) + refresh token có thể thu hồi; client giữ secure, không lưu localStorage nếu có thể (chương 6) |
| 21 | Vì sao hash mật khẩu bằng Argon2/bcrypt? | Salt tự sinh + nặng tính toán → chống brute force và rainbow table; không dùng MD5/SHA1 |
| 22 | Multi-tenant chống nhìn trộm dữ liệu? | JWT mang `property_id`; middleware `assert_property_access` chặn truy cập chéo — MANAGER chỉ thấy cơ sở của mình (chương 6) |
| 23 | CCCD mã hóa rồi tìm kiếm thế nào? | Blind index HMAC bằng khóa riêng (mục 9.4 ⭐2); 2 khóa tách biệt nên lộ 1 khóa không vỡ toàn bộ |
| 24 | Rate limit chống gì? | Brute-force login, spam API; nginx `limit_req` — k6 giả lập 50 VU login trong khi hệ thống vẫn đứng vững |
| 25 | Token SYSTEM có nguy hiểm không? | Không user trong DB, chỉ job nội bộ; luôn ký JWT, scope `Role.SYSTEM`, và mạng nội bộ (cổng 8001–8008 ghim 127.0.0.1) |

### E. Vận hành & mở rộng

| # | Câu hỏi | Đáp án gợi ý |
|---|---|---|
| 26 | Bằng chứng SLA? | k6: p95 đọc < 300 ms, ghi < 500 ms, lỗi < 1%, 50 VU/2 phút; threshold trong `k6/smoke.js` + file `summary-loadtest.json` |
| 27 | Service chết thì sao? | Docker `restart` policy + healthcheck; Prometheus `up==0` → Alertmanager báo P1; Grafana provision sẵn dashboard |
| 28 | Scale service nào trước? | Theo triệu chứng: đọc chậm → room/read; mùng 1 → billing; báo cáo chậm → **không scale**, tăng tần suất reconcile (CQRS) |
| 29 | RPO/RTO của hệ thống? | Backup ngày + verify chủ nhật → RPO ≤ 24h; restore theo script → RTO vài chục phút (chương 5) |
| 30 | Con đường lên Kubernetes? | Vì sao giờ chưa cần (1 host, 21 container quản bằng Compose đủ); khi nhiều host → Swarm/K8s, `deploy.replicas` tái sử dụng (chương 7) |

---

## 9.6. Câu hỏi "bẫy" & cách xử lý

| Câu bẫy | Nguy hiểm | Cách xử lý |
|---|---|---|
| "Đây chỉ là Docker Compose, microservice ở đâu?" | Hạ thấp đồ án | Không cãi. Đưa ra **bằng chứng kiến trúc**: DB riêng, event bus, outbox, CQRS, scale độc lập — Compose chỉ là cách triển khai |
| "Tự làm hay copy?" | Liêm chính | Chỉ ra quyết định thiết kế của riêng mình: blind index, token SYSTEM, IN_APP, DRY_RUN, seed bằng uuid5 tất định — "cái này em chọn vì…" |
| "Vì sao không dùng Oracle/MySQL/K8s?" | Lạc đề | "Chọn theo bài toán: Postgres đủ 8 service nhỏ; K8s thừa cho 1 host — em phân tích giới hạn ở chương 7" |
| "Hệ thống sập lúc demo thì sao?" | — | "Em đã quay video diễn tập restore sáng nay" — rồi mở video |
| "Chỉ số k6 có làm trò không?" | Mất niềm tin | Nói trung thực: "Ngưỡng thực tế chúng em dùng 50 VU vì quy mô 200–500 phòng; đã đo p99 luôn, và cache nginx gánh phần lớn" |

---

## 9.7. Những câu KHÔNG nên nói

- ❌ "Máy em chạy nhanh lắm" → thay bằng số đo k6.
- ❌ "Cái này em xem trên mạng" → "Em tham khảo NIST SP 800-145 / Fowler / microservices.io và áp dụng cho bài toán này như thế…".
- ❌ "Hệ thống chạy được hết, không lỗi gì" → thừa nhận biết giới hạn: "DRY_RUN chưa gửi SMS thật vì chưa có key nhà mạng; khung đã sẵn".
- ❌ "Em không biết, chắc vậy" → nếu không chắc, nói: "Theo tài liệu X thì…, riêng trường hợp này em cần kiểm chứng lại".

---

## 9.8. Tổng kết chương

1. 12 slide trong 15 phút — **1 slide 1 ý**, sơ đồ > chữ, số > tính từ.
2. Demo **3 phút giữa bài** — bấm thật, có fallback video/ảnh.
3. 3 ⭐ điểm sáng: token SYSTEM, AES-GCM + blind index, adapter kênh thông báo.
4. 30 câu Q&A theo 5 nhóm — trả lời theo kiểu *"vì bài toán, vì dữ liệu"*.
5. Câu bẫy không phải để sợ mà để **chủ động dẫn dắt về điểm mạnh**.

→ Chương cuối: **tài liệu tham khảo chuẩn trích dẫn**.