# Design — EZ-Rent

Hệ thiết kế cố định cho giao diện web (`web/`). Mọi lần sửa giao diện đọc file này
trước. Muốn đổi hệ thì sửa file này trước, không ghi đè cục bộ trong từng trang.
Lý do chọn hướng: `docs/ideas/qlpt-giao-dien.md`.

## Genre
Editorial thực dụng — "Mực & Sổ". Giấy sáng, mực, một màu tín hiệu. Chất "sổ"
(dòng kẻ, số mono căn phải, biên lai) CHỈ ở bề mặt tiền và chỉ số.

## Macrostructure family
- App pages (mọi màn sau đăng nhập): Workbench — đầu trang (wordmark + tab mục
  kiểu chia sổ) → tiêu đề trang + một dòng mô tả → nội dung là bảng/sổ, không thẻ.
- Màn đăng nhập: một cột, logo đầy đủ, form, không khẩu hiệu.
- Không có trang marketing.

## Theme
Hai màu thương hiệu lấy đúng từ logo (`web/brand/`).
- `--color-paper`    oklch(97% 0.012 85)   — giấy ngà
- `--color-paper-2`  oklch(94.5% 0.016 85) — hàng tiêu đề bảng, nền dòng nhấn
- `--color-ink`      oklch(22.5% 0.013 78) — mực, = #1F1B15 của logo
- `--color-ink-2`    oklch(46% 0.012 70)   — chữ phụ
- `--color-rule`     oklch(84% 0.014 80)   — đường kẻ sổ
- `--color-accent`   oklch(50% 0.199 28.6) — đỏ son, = #BA0D0D của logo
- `--color-focus`    = ink (vòng focus 2px, hiện tức thì)

Quy tắc đỏ: ngoài logo, đỏ CHỈ có nghĩa "nợ / quá hạn / khẩn / sự cố mới".
Nút chính màu mực. Không có màu thứ ba.

## Typography
- Chữ: Be Vietnam Pro 400 / 600 / 700 (tự host, có subset tiếng Việt)
- Số: JetBrains Mono 400 / 600 — tiền, chỉ số, số phòng, mã hóa đơn
- Thang 6 bậc: 12 · 14 · 16 · 20 · 28 · 40 px (`--text-xs` … `--text-3xl`)
- Tiêu đề luôn roman, tracking -0.01em; không chữ nghiêng trong tiêu đề

## Spacing
Thang 4pt có tên (`--space-1` = 4px … `--space-12` = 48px). Không dùng giá trị thô.

## Shape
- Ô nhập, nút: bo 2px. Bảng, sổ, sơ đồ: không bo, không đổ bóng.
- Hộp thoại: viền mực 1px, nền giấy, lớp phủ mực 40%, không blur.

## Trạng thái — nói bằng chữ và nét, không bằng màu
| Trạng thái | Cách thể hiện |
|---|---|
| Đang thuê | viền liền |
| Còn trống | viền nét đứt, chữ phụ |
| Bảo trì | nền gạch chéo |
| Đã giữ chỗ | viền đôi |
| Nợ / quá hạn / khẩn | chữ đỏ son + nhãn chữ ("Nợ", "Quá hạn") |
| Đã hủy / hết hạn | chữ phụ, gạch ngang nhẹ |

Nhãn trạng thái là chữ thường có viền mảnh — không pill màu, không chấm tròn.

## Motion
- Chỉ đổi màu nền/viền, 120ms, `--ease-out: cubic-bezier(0.2, 0, 0, 1)`.
- Không skeleton nhấp nháy, không hover nhấc lên, không animation vào trang.
- `prefers-reduced-motion`: tắt hết transition.

## Microinteractions stance
- Thành công thấy được trên màn hình → im lặng (không toast).
- Toast chỉ cho: lỗi, việc chạy nền (phát hành hóa đơn), và thao tác làm dòng
  biến khỏi danh sách đang xem.
- Thao tác tiền không hoàn tác được → xác nhận 2 bước ngay trong form.

## CTA voice
- Chính: nền mực, chữ giấy, bo 2px, động từ ngắn ("Lưu chỉ số", "Phát hành").
- Phụ: viền mực, nền trong suốt.
- Nguy hiểm: chữ đỏ son, viền đỏ son — chỉ cho hủy/chấm dứt.

## Icons
Gần như không dùng. Không icon trang trí trước nhãn, KPI, ghi chú hay trạng thái trống.

## Exports

### tokens.css
Khối `:root` ở đầu `web/app.css` là nguồn duy nhất của token.

## Provenance
Hệ thiết kế được xây cho dự án này (custom, studied: no) — 24/10/2026.
