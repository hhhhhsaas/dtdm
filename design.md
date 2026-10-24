# Design — EZ-Rent

Hệ thiết kế cố định cho giao diện web (`web/`). Mọi lần sửa giao diện đọc file này
trước. Muốn đổi hệ thì sửa file này trước, không ghi đè cục bộ trong từng trang.
Lý do chọn hướng: `docs/ideas/qlpt-giao-dien.md`.

## Lịch sử
- v1 (24/10/2026): "Mực & Sổ" thuần — giấy, mực, một màu đỏ, không thẻ, không icon.
  Phản hồi người dùng: sạch nhưng quá trơn, thua bản cũ về màu, chiều sâu, icon, nền tối.
- v2 (24/10/2026): giữ xương sống v1 (logo, font, số mono, đỏ son = nợ, im lặng khi
  thành công) và thêm lại màu trạng thái dịu, thẻ có chiều sâu, icon trong dòng,
  chế độ tối ấm.

## Genre
Editorial thực dụng — "Mực & Sổ". Chất "sổ" (số mono căn phải, đường kẻ đôi dưới
tiêu đề bảng, biên lai) ở bề mặt tiền và chỉ số.

## Macrostructure family
- App pages: Workbench — đầu trang (wordmark + tab mục) → tiêu đề trang → thẻ nội dung.
- Trang chủ: thẻ chính (tiền tháng này + thanh tiến độ thu) chiếm 2/3, lưới 2×2 thẻ phụ
  bên cạnh — không phải 4 thẻ bằng nhau.
- Màn đăng nhập: một thẻ giữa trang, logo đầy đủ, không khẩu hiệu.

## Theme
Hai màu thương hiệu lấy đúng từ logo (`web/brand/`). Sáng mặc định theo hệ điều hành,
người dùng đổi được (nút ở đầu trang, nhớ trong trình duyệt).

| Token | Sáng | Tối |
|---|---|---|
| `--color-paper` (nền trang) | oklch(96% 0.012 85) | oklch(17.5% 0.012 65) |
| `--color-surface` (thẻ) | oklch(99.2% 0.005 85) | oklch(21.5% 0.013 65) |
| `--color-surface-2` (đầu bảng, ô nhập) | oklch(94.5% 0.014 85) | oklch(25.5% 0.014 65) |
| `--color-ink` | oklch(22.5% 0.013 78) | oklch(93% 0.01 85) |
| `--color-ink-2` | oklch(46% 0.012 70) | oklch(72% 0.012 80) |
| `--color-rule` | oklch(87% 0.014 80) | oklch(31% 0.012 65) |
| `--color-accent` (đỏ son) | oklch(50% 0.199 28.6) | oklch(65% 0.18 28) |

Màu trạng thái — tự pha, độ bão hòa thấp, mỗi màu có nền nhạt `-soft`:
| Token | Nghĩa | Hue |
|---|---|---|
| `--color-ok` | đang thuê, đã thanh toán, đã xử lý | xanh rêu 155 |
| `--color-info` | còn trống, chờ ký, đang xử lý | xanh xám 245 |
| `--color-warn` | bảo trì, chờ thanh toán, sắp hết hạn | vàng đất 70 |
| `--color-hold` | đã giữ chỗ | tím mận 320 |
| `--color-accent` | nợ, quá hạn, khẩn, sự cố mới | đỏ son 28.6 |

Quy tắc đỏ: đỏ son CHỈ có nghĩa "nợ / quá hạn / khẩn / sự cố mới". Nút chính màu mực.

## Typography
- Chữ: Be Vietnam Pro 400 / 600 / 700 (tự host, có subset tiếng Việt)
- Số: JetBrains Mono 400 / 600 — tiền, chỉ số, số phòng, mã hóa đơn
- Thang 6 bậc: 12 · 14 · 16 · 20 · 28 · 40 px
- Tiêu đề luôn roman; không chữ nghiêng trong tiêu đề

## Spacing
Thang 4pt có tên (`--space-1` = 4px … `--space-12` = 48px).

## Shape & depth
- Thẻ: nền `surface`, viền `rule` 1px, bo 10px, bóng sát (sáng) / không bóng mà sáng
  hơn nền (tối). Không lồng thẻ trong thẻ.
- Ô nhập, nút, nhãn: bo 6px. Ô phòng: bo 8px.
- Hộp thoại: thẻ nổi, lớp phủ mực 50%, không blur.

## Trạng thái — màu + nét (không chỉ màu)
| Trạng thái | Cách thể hiện |
|---|---|
| Đang thuê | nền `ok-soft`, viền `ok` |
| Còn trống | nền `info-soft`, viền nét đứt `info` |
| Bảo trì | nền gạch chéo `warn` |
| Đã giữ chỗ | nền `hold-soft`, viền đôi `hold` |
| Nợ | nhãn "Nợ" đỏ son + số phòng đỏ |

Nhãn trạng thái: chữ màu trạng thái trên nền `-soft`, bo 6px, không chấm tròn.

## Icons
Một bộ nét 2px (kiểu Lucide, nhúng sprite trong `index.html`). Icon đặt TRONG DÒNG
trước nhãn tab, tiêu đề thẻ, nhãn số liệu, nút chính, dòng việc cần làm. Không ô vuông
tô màu chứa icon, không icon trang trí ở trạng thái trống.

## Motion
- Đổi màu nền/viền 120ms, `--ease-out: cubic-bezier(0.2, 0, 0, 1)`.
- Không skeleton nhấp nháy, không hover nhấc lên, không animation vào trang.
- `prefers-reduced-motion`: tắt hết transition.

## Microinteractions stance
- Thành công thấy được trên màn hình → im lặng.
- Toast chỉ cho: lỗi, việc chạy nền, thao tác làm dòng biến khỏi danh sách đang xem.
- Thao tác tiền không hoàn tác được → xác nhận 2 bước ngay trong form.

## CTA voice
- Chính: nền mực, chữ nền, bo 6px, icon trong dòng + động từ ngắn.
- Phụ: viền `rule`, nền `surface`.
- Nguy hiểm: chữ + viền đỏ son — chỉ cho hủy/chấm dứt.

## Exports
### tokens.css
Khối `:root` (sáng) và `[data-theme="dark"]` / `prefers-color-scheme: dark` (tối) ở đầu
`web/app.css` là nguồn duy nhất của token.

## Provenance
Hệ thiết kế được xây cho dự án này (custom, studied: no) — 24/10/2026.
