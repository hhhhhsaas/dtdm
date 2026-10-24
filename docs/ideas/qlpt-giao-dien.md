# QLPT — "Mực & Sổ": giao diện làm lại

> Kết quả buổi rà soát giao diện ngày 24/10/2026: audit dấu hiệu "code bằng AI"
> (6 nghiêm trọng · 11 lớn · 4 nhỏ) → chọn hướng A (Sổ thu tiền trọ) + D (Mực + 1 màu tín hiệu),
> nền sáng, làm lại toàn bộ giao diện. Người đánh giá: hội đồng + người dùng thật.

## Problem Statement

Làm sao để QLPT trông như công cụ làm riêng cho chủ trọ Việt Nam — không phải template SaaS
đổi tên — trong 3 ngày, HTML thuần, CSP chặt, mà vẫn dùng được thật?

## Recommended Direction

Hệ thống "Mực": nền giấy sáng ấm (không trắng tinh), mực gần đen, MỘT màu đỏ son chỉ dành
cho nợ / quá hạn / khẩn. Không pill màu, không ô icon, gần như không icon. Trạng thái nói bằng
chữ + nét (đặc / rỗng / gạch chéo). Hai font tự host: Be Vietnam Pro (chữ) + mono cho số.

Chất "Sổ" chỉ ở bề mặt tiền và chỉ số: trang Thu tiền là sổ cái kẻ dòng, số căn phải;
Nhập chỉ số là bảng ghi điện nước như sổ thật; hóa đơn của người thuê là biên lai
(in được khổ A5 / giấy nhiệt 80 mm bằng `@media print`).

Bố cục mới: bỏ sidebar kiểu shadcn → thanh tiêu đề trên + tab mục kiểu chia sổ (máy tính),
thanh đáy (điện thoại, cho người thuê). Trang chủ "Hôm nay": KPI thành MỘT câu
("Tháng 10 đã thu 23.104.800 đ trên 54 triệu — còn 3 phòng nợ") + danh sách việc dạng dòng kẻ,
không thẻ. Đăng nhập: một cột, không gradient, không khẩu hiệu.

Nguyên tắc triển khai: giữ nguyên phần gọi API, quản lý trạng thái và logic trong `web/app.js`;
chỉ viết lại HTML/CSS và các hàm render.

## Key Assumptions to Validate

- [ ] Font có đủ dấu tiếng Việt — gõ thử "Nguyễn Thị Hữu Ặng, phòng 302" ở mọi cỡ chữ
- [ ] 5 trạng thái phòng phân biệt được không cần màu — dựng sơ đồ trước tiên, nhờ 1 người lạ đọc thử
- [ ] Biên lai in được — Ctrl+P ra đúng 1 trang A5
- [ ] Không vỡ chức năng — chạy lại smoke test 26/26 + bấm tay hết kịch bản demo

## MVP Scope (3 ngày)

- **Ngày 1:** token màu/chữ/khoảng cách (thang 4pt, ≤ 6 cỡ chữ), tự host font, khung trang
  (đầu trang + tab + thanh đáy), đăng nhập, trang Hôm nay
- **Ngày 2:** Sơ đồ phòng (không màu), Nhập chỉ số (sổ), Hóa đơn + biên lai in
- **Ngày 3:** Hợp đồng, Người thuê, Sự cố, các màn của người thuê, kiểm tra trên điện thoại
  320–414 px, focus bàn phím, chạy lại slop test, deploy

## Not Doing (and Why)

- **Chế độ tối** — người dùng ban ngày + in ấn; tốn nửa ngày không ai cần
- **Biểu đồ** — thay bằng một câu số liệu + bảng; biểu đồ cột 30 ngày hiện tại chỉ là trang trí
- **Hình minh họa, animation, toast ăn mừng** — thành công thì im lặng, chỉ báo khi lỗi
- **Kẻ dòng ở form / modal / đăng nhập** — đó là chỗ ẩn dụ thành kitsch
- **Đụng vào logic gọi API trong app.js** — rủi ro cao nhất, không có lợi cho giao diện
- **Đổi giao diện Grafana** — ngoài phạm vi

## Open Questions

- Ô "Other" ở câu chọn hướng — có ý muốn thêm không?
- Logo: giữ chữ "QLPT" hay đặt tên riêng cho sản phẩm?
- Màn hình máy chiếu ngày bảo vệ — có cần thử độ tương phản trên máy chiếu không?
