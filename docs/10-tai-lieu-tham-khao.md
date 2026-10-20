# CHƯƠNG 10 — TÀI LIỆU THAM KHẢO

> "Trích dẫn chuẩn là **bằng chứng** bạn đọc tài liệu gốc, không phải chỉ học
> theo video." Chương này liệt kê nguồn đã dùng, **phân theo nhóm**, kèm bản đồ
> *nguồn nào phục vụ chương nào* để khi giám khảo hỏi "cái này lấy từ đâu" bạn
> trả lời được ngay tên tài liệu + tác giả + năm.

---

## 10.1. Tiêu chuẩn & tài liệu gốc về Cloud Computing

| Tài liệu | Tác giả / Năm | Dùng ở đâu | Nội dung khai thác |
|---|---|---|---|
| **NIST SP 800-145** — *The NIST Definition of Cloud Computing* | P. Mell & T. Grance, 2011 | Chương 1, 3, 8, 9 | Định nghĩa chuẩn 5 đặc trưng: on-demand, broad access, resource pooling, rapid elasticity, measured service |
| **NIST SP 500-292** — *NIST Cloud Computing Reference Architecture* | NIST, 2011 | Chương 3 | 5 tác nhân (provider, consumer, broker…) và các lớp — dùng để phân vai trong kiến trúc triển khai |
| **NIST SP 800-63B** — *Digital Identity Guidelines: Authentication & Lifecycle Management* | NIST, 2017 (bản mới nhất) | Chương 6 | Ràng buộc mật khẩu, đa yếu tố, vòng đời thông tin xác thực — cơ sở cho chính sách mật khẩu của `auth-service` |
| **CSA Security Guidance v4** | Cloud Security Alliance, 2017 | Chương 6 | Mô hình trách nhiệm chung, ranh giới bảo mật giữa khách hàng và nhà cung cấp cloud |
| IEEE/ACM *Cloud Computing: Concepts, Technology & Architecture* (sách) | T. Erl, R. Puttini, Z. Mahmood, 2013 | Chương 1 | Thuật ngữ và phân loại mô hình triển khai (public/private/hybrid), mẫu khởi tạo tài nguyên |

> **Ghi chú học thuật:** tài liệu NIST là **public domain** — được trích dẫn,
> dịch và dùng tự do (không vi phạm bản quyền, nên có thể đưa bảng dịch 5 đặc
> trưng vào báo cáo).

---

## 10.2. Kiến trúc Microservice & các mẫu (Pattern)

| Tài liệu | Tác giả / Năm | Dùng ở đâu | Nội dung khai thác |
|---|---|---|---|
| *Microservices* — bài báo gốc | J. Lewis & M. Fowler, 2014 (martinfowler.com) | Chương 2 | Định nghĩa microservice, bounded context, database-per-service, "smart endpoints, dumb pipes" |
| *Building Microservices* (sách) | S. Newman, 2021 (2nd ed.) | Chương 2, 3 | Bóc tách domain, giao tiếp, triển khai, chọn công nghệ cho từng service |
| **microservices.io** (catalogue mẫu) | C. Richardson, 2015–nay | Chương 2, 3, 7 | Bách khoa các mẫu: Decomposition, API Gateway, Saga, CQRS, Database per Service, Transactional Outbox, Idempotent Consumer, Deployment Strategies |
| *Microservices: A Systematic Mapping Study* | P. Di Francesco, P. Lago, I. Malavolta, 2019 (Journal of Systems and Software) | Chương 2 | Nghiên cứu định lượng 96 bài — cơ sở khoa học cho việc lựa chọn 8 service và các mẫu phổ biến |
| *A Pattern Language for Microservices* | S. Haselböck, R. Weinreich, G. Buchinger, 2017 (EuroPLoP) | Chương 2, 7 | Mẫu "Backend for Frontend", "Config-as-Code", "Health Probe" — áp dụng cho nginx + SPA + healthcheck |
| *Successful patterns for microservices…* (khảo sát kiến trúc) | A. Taibi & V. Lenarduzzi, 2018 (QUATIC) | Chương 2 | Phân tích ảnh hưởng của các pattern đến maintainability/performance |
| *Enterprise Integration Patterns* (sách) | G. Hohpe & B. Woolf, 2003 | Chương 2 | Message Broker, Message Channel, Dead Letter, Idempotent Receiver — gốc của outbox/DLQ/idempotency |
| *CQRS* — bài viết | M. Fowler, 2011; C. Richardson (microservices.io) | Chương 2, 7 | Tách Command (ghi) / Query (đọc), read model — áp dụng cho report-service |

> **Cách trích trong slide:** "Theo Fowler and Lewis (2014), microservice là
> *single responsibility per service* — em chia 8 service theo bounded context…"
> — câu này đủ "đậm chất học thuật".

---

## 10.3. Công nghệ nền tảng (tài liệu chính thức)

| Công nghệ | Tài liệu | Dùng ở đâu |
|---|---|---|
| Python + FastAPI | Tài liệu chính thức FastAPI (Tiangolo), Starlette, Pydantic v2 | Mọi service |
| PostgreSQL 16 | Tài liệu chính thức PostgreSQL; `numeric`/`money`, transaction, `pg_dump` | DB + sao lưu (chương 5) |
| Redis 7 | Tài liệu chính thức Redis; các module cache, TTL | Cache + lưu refresh token (chương 3, 7) |
| RabbitMQ 3 | Tài liệu RabbitMQ: Work Queues, Publisher Confirms, QoS/Prefetch, DLX | Event bus, DLQ (chương 2) |
| MinIO | Tài liệu MinIO / Amazon S3 API (tương thích) | Lưu ảnh hợp đồng, backup (chương 3, 5) |
| NGINX | Tài liệu người dùng NGINX: reverse proxy, `proxy_cache`, `limit_req`, upstream | API Gateway (chương 3) |
| Docker & Compose | Docker docs; Compose Specification (OCI) | Triển khai (chương 3, 4) |
| Prometheus | Prometheus docs: metric types, `rate`, `histogram_quantile`, alerting | Giám sát (chương 7) |
| Grafana | Grafana docs: provisioning, dashboard variables | Dashboard (chương 7) |
| Loki + Promtail | Grafana Labs docs | Gom log (chương 7) |
| k6 | Grafana k6 docs: options, thresholds, custom metrics | Load test (chương 7, 8) |
| Alembic | Alembic docs (SQLAlchemy migration) | Migration (chương 4) |

---

## 10.4. Bảo mật (chuẩn & thực hành)

| Tài liệu | Tác giả / Năm | Nội dung khai thác |
|---|---|---|
| **OWASP Top 10** (2021) | OWASP Foundation | Xếp hạng rủi ro web — dùng làm checklist rà soát API (injection, broken auth, misconfig…) |
| **OWASP ASVS** | OWASP Foundation | Tiêu chí kiểm thử bảo mật ứng dụng ở các mức 1–3 |
| **RFC 7519** — *JSON Web Token* | M. Jones et al., 2015 | Cấu trúc JWT (header, payload, signature) — mô tả chính xác token trong hệ thống |
| **RFC 8725** — *JWT Best Current Practices* | Sheffer, Hardt, Jones, 2020 | Cảnh báo thuật toán yếu, thời hạn token, cách dùng `jti` — cơ sở thiết kế refresh token |
| **NIST SP 800-38D** — *Recommendation for GCM* | NIST, 2007 | Chuẩn mã hóa xác thực GCM — cơ sở cho `crypto.py` (AES-256-GCM, nonce 12 byte) |
| **RFC 9106** — *Argon2* | Biryukov, Dinu, Khovratovich, 2021 | Thuật toán băm mật khẩu chống GPU — dùng cho `hash_password` |
| *Password Storage Cheat Sheet* | OWASP | Muối (salt), cost factor, khi nào nâng cấp hash |
| *The Twelve-Factor App* | A. Wiggins (Heroku), 2011 | Config qua biến môi trường, log ra stdout, xử lý theo process — kiến trúc service của dự án tuân theo |

---

## 10.5. Vận hành, DevOps & SRE

| Tài liệu | Tác giả / Năm | Nội dung khai thác |
|---|---|---|
| *Site Reliability Engineering* (sách, bản miễn phí online) | B. Beyer et al. (Google), 2016 | SLO, cấp độ cảnh báo (P1–P3), toil — áp dụng bảng SLO ở chương 7 |
| *The DevOps Handbook* / *Accelerate* | G. Kim, J. Humble / N. Forsgren | Nền tảng CI/CD, delivery pipeline — cơ sở cho `make update` và chuỗi kiểm thử |
| *Continuous Delivery* | J. Humble & D. Farley, 2010 | Pipeline triển khai, môi trường dev/staging/prod |

---

## 10.6. Bản đồ nguồn → chương (dùng để "bảo vệ" phần trích dẫn)

| Chương | Nguồn chính (đọc trước) | Nguồn bổ trợ |
|---|---|---|
| 01 — Bài toán & nghiệp vụ | Erl et al. (2013); NIST SP 800-145 | — |
| 02 — Thiết kế microservice | Lewis & Fowler (2014); Richardson (microservices.io); Di Francesco et al. (2019); Hohpe & Woolf (2003) | Haselböck et al. (2017); Taibi (2018) |
| 03 — Kiến trúc triển khai đám mây | NIST SP 500-292; NIST SP 800-145; Docker/NGINX docs | Newman (2021) |
| 04 — Docker trên Ubuntu Server | Docker docs; Compose Specification | OWASP ASVS (hardening) |
| 05 — Sao lưu & khôi phục | PostgreSQL docs (`pg_dump`/restore); MinIO/S3 docs | 12-Factor (dữ liệu ngoài container) |
| 06 — Bảo mật | RFC 7519, RFC 8725; NIST SP 800-38D; RFC 9106; OWASP Top 10 | NIST SP 800-63B; CSA v4 |
| 07 — Vận hành & hiệu năng | Prometheus docs; Grafana docs; Google SRE book; k6 docs | Richardson (patterns); Newman (2021) |
| 08 — Kế hoạch triển khai | *Accelerate*; NIST SP 800-145 (5 đặc trưng để nghiệm thu) | SRE book |
| 09 — Slide & bảo vệ | Toàn bộ — bản đồ này chính là "bảng ghi nhớ" khi hỏi đáp | — |
| 10 — Tài liệu tham khảo | Chương này | — |

---

## 10.7. Lưu ý liêm chính học thuật & cách đưa vào báo cáo

1. **Không cắt xén mất nghĩa:** mỗi khi trích ý NIST/Fowler, đọc kỹ ngữ cảnh
   gốc trước khi dịch — ví dụ "measured service" phải đủ ý *theo dõi và kiểm
   soát tài nguyên tự động*, không chỉ "có đếm request".
2. **Ghi rõ nguồn trong slide** (chữ nhỏ chân trang): `NIST SP 800-145 (2011)`,
   `Fowler (2014)`, `OWASP Top 10 (2021)`.
3. **Phân biệt "mô phỏng" với "triển khai thật":** SMS/Zalo kênh đang ở mức
   khung + DRY_RUN, không phải đã kết nối nhà cung cấp — nói đúng trong phần
   giới hạn (liêm chính > "nghe hay").
4. Nếu dùng AI hỗ trợ viết, **giữ lại các câu hỏi thiết kế và quyết định của
   mình** làm phần "bàn luận" — đó chính là phần giám khảo chấm.

---

## 10.8. Tổng kết

1. 4 nhóm nguồn: **chuẩn đám mây** (NIST/CSA), **microservice & pattern**
   (Fowler, Richardson, mapping study), **tài liệu công nghệ chính thức**,
   **an toàn & vận hành** (OWASP/RFC, Google SRE).
2. Bản đồ 10.6 cho biết *đọc gì trước khi bảo vệ từng chương*.
3. Trích dẫn đúng = điểm cộng "hiểu sâu"; nói sai nguồn = mất điểm nghiêm trọng
   hơn cả không trích.

---

> **Kết thúc bộ tài liệu 10 chương.** Từ bài toán (01) → thiết kế (02) → kiến
> trúc đám mây (03) → cài đặt/vận hành/sao lưu/bảo mật (04–07) → kế hoạch &
> bảo vệ (08–10). Toàn bộ code kèm theo chạy được với `make up && make seed` —
> xem `README.md` để bắt đầu.