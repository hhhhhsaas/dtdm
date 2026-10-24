# EZ-Rent — "Phòng của tôi" cho người thuê

> Buổi idea-refine 24/10/2026. Người dùng chọn hướng D1 (trang tổng quan) gồm các chức năng
> 1 · Điện nước của tôi, 3 · Hợp đồng của tôi, 4 · Hộp thông báo, 6 · "Phòng của tôi".
> Thời gian: hơn 1 ngày. Được sửa backend.

## Problem Statement

Làm sao để người thuê tự trả lời được "tháng này trả bao nhiêu, điện có tăng không,
hợp đồng còn bao lâu, sự cố tới đâu rồi" mà không phải nhắn chủ trọ?

## Recommended Direction

Tab đầu tiên của người thuê đổi thành "Phòng của tôi": một màn tổng quan gồm khối tiền
cần trả (dùng lại thẻ đã thu/tổng), khối hợp đồng (còn N ngày + thanh thời gian), khối
điện nước (kWh & m³ 6 tháng, so tháng trước), khối sự cố đang mở và 3 thông báo mới.
Thêm tab "Thông báo" có đánh dấu đã đọc và số đếm chưa đọc trên tab.

Mọi API mới đều lọc theo claim `tenant_id` trong JWT, không nhận id từ client —
cùng nguyên tắc với `/invoices/mine`, là điểm nói về bảo mật khi thuyết trình.

Các hướng đã cân nhắc và bỏ:
- D2 · mỗi chức năng một tab — 6 tab, chật trên điện thoại, người thuê tự đi tìm.
- D3 · chỉ điện nước + hợp đồng — mất phần "event chạy tới tận người dùng", thứ chứng
  minh kiến trúc event-driven khi demo.

## Key Assumptions to Validate

- [x] `invoice_details` có dòng điện/nước kèm `quantity` — ELECTRIC 27 dòng (61–135 kWh),
      WATER 27 dòng (4–14 m³). Kiểm tra trên rental-server 24/10/2026.
- [x] Có thông báo IN_APP gắn `tenant_id` — 11/20 thông báo IN_APP.
- [ ] Mỗi tài khoản `khach0x` đã gắn `users.tenant_id` (đã làm ở đợt vá bảo mật — kiểm lại khi test).

## MVP Scope

Backend (2 service):
- contract: `GET /api/v1/contracts/mine` — hợp đồng hiệu lực / chờ ký của người thuê đang đăng nhập.
- notification: `GET /api/v1/notifications/mine` (IN_APP, theo `tenant_id`) +
  `POST /api/v1/notifications/{id}/read`.
- nginx: không đổi (prefix `/api/v1/contracts`, `/api/v1/notifications` đã có).

Giao diện:
- Tab "Phòng của tôi" (mới, mặc định) · tab "Thông báo" (mới) · giữ "Hóa đơn", "Báo sự cố", "Tài khoản".
- Biểu đồ điện nước: cột SVG tự vẽ (không thư viện, hợp CSP).

Thứ tự làm: từng endpoint một, deploy + test xong mới sang cái tiếp theo.

## Not Doing (and Why)

- **Mã QR chuyển khoản** — tự viết bộ tạo QR rủi ro, CSP chặn thư viện ngoài; để sau.
- **Phiếu yêu cầu** (trả phòng, gia hạn, thêm người ở) — luồng duyệt mới, không kịp.
- **Thông báo đẩy / email thật** — đang ở chế độ DRY_RUN, chỉ làm hộp thư trong app.
- **Người ở ghép có tài khoản riêng** — chưa có mô hình dữ liệu.
- **Nội quy / liên hệ chủ trọ** — cần màn cấu hình cho chủ trọ, ngoài phạm vi.

## Open Questions

- Số điện thoại chủ trọ hiện trên "Phòng của tôi" lấy từ đâu? (đề xuất: tài khoản quản lý của cơ sở)
- Trước demo có chủ động phát hành hóa đơn tháng 11 để hộp thông báo có dữ liệu mới?
