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
Palette do người dùng chọn (v3, 24/10/2026):
`#4392F1` Blue Energy · `#ECE8EF` Lavender Mist · `#E3EBFF` Lavender · `#E7F0FF` Alice Blue · `#DC493A` Cinnabar.
Sáng mặc định theo hệ điều hành, người dùng đổi được (nút ở đầu trang, nhớ trong trình duyệt).

Mã gốc dùng cho NỀN và MẢNG MÀU. Chữ và nền nút dùng bản đậm hơn cùng hue, vì đo được:
chữ trắng trên #4392F1 = 3.17:1, chữ #DC493A trên #ECE8EF = 3.43:1 — dưới chuẩn AA 4.5:1.

| Token | Sáng | Vai trò |
|---|---|---|
| `--color-paper` | #ECE8EF | nền trang |
| `--color-surface` | oklch(99% 0.004 300) | thẻ |
| `--color-surface-2` | #E7F0FF | đầu bảng, ô nhập, bộ lọc |
| `--color-select` / `--color-info-soft` | #E3EBFF | dòng đang rê chuột, nhãn "trống" |
| `--color-primary` | #4392F1 | gạch chân tab, thanh tiến độ, thanh sổ thu |
| `--color-primary-strong` | oklch(54% 0.16 256) | nền nút chính, chữ xanh, vòng focus |
| `--color-accent-fill` | #DC493A | mảng màu nợ (thanh "quá hạn") |
| `--color-accent` | oklch(50% 0.18 29) | chữ đỏ: nợ, quá hạn, khẩn |
| `--color-ink` / `--color-ink-2` | oklch(24% 0.02 275) / oklch(46% 0.02 275) | chữ |

Chế độ tối: tím than cùng họ (nền oklch(18% 0.02 285)), xanh chính oklch(70% 0.15 255)
với chữ tối trên nút. Giá trị đầy đủ ở `web/app.css`.

Màu trạng thái — mỗi màu có nền nhạt `-soft`:
| Token | Nghĩa | Hue |
|---|---|---|
| `--color-ok` | đang thuê, đã thanh toán, đã xử lý | xanh lá 160 |
| `--color-info` | còn trống, chờ ký, đang xử lý | xanh 256 (họ #4392F1) |
| `--color-warn` | bảo trì, chờ thanh toán, sắp hết hạn | vàng đất 70 |
| `--color-hold` | đã giữ chỗ | tím 300 |
| `--color-accent` | nợ, quá hạn, khẩn, sự cố mới | cinnabar 29 |

Quy tắc đỏ: đỏ CHỈ có nghĩa "nợ / quá hạn / khẩn / sự cố mới". Nút chính màu xanh.
Logo giữ màu gốc (#BA0D0D) — cùng hue với cinnabar.

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
Đúng 3 loại chuyển động, mỗi loại trả lời một câu hỏi của người dùng. Không thêm loại thứ tư.

| Loại | Trả lời câu hỏi | Cách làm |
|---|---|---|
| A · Số liệu đến nơi | "Đây là dữ liệu vừa tải?" | Số "đã thu" đếm lên 600ms; thanh tiến độ + thanh sổ thu mọc ra (scaleX) một lần |
| B · Dòng vừa đổi lóe lên | "Thứ tôi vừa làm nằm đâu?" | Sau thao tác, dòng đó nền `select` nhạt dần 900ms + cuộn tới. Thay cho toast thành công |
| C · Vạch chân trượt | "Tôi vừa chuyển từ đâu sang đâu?" | Một vạch `primary` 2px trượt (translateX + scaleX) 250ms giữa tab / mục lọc |

Kèm: nút lún 1px khi bấm (100ms). Đổi màu hover 120ms.
- Easing `--ease-out: cubic-bezier(0.2, 0, 0, 1)`. Chỉ transform/opacity (riêng B đổi màu nền một lần).
- Không: thẻ nhấc lên khi hover, fade-up khi cuộn, skeleton nhấp nháy, chuyển trang trượt, lặp vô hạn.
- `prefers-reduced-motion`: tắt mọi transition/animation, số hiện ngay giá trị cuối.
- Bộ lọc là chữ + vạch chân (không dùng rãnh xám + nút nổi kiểu shadcn Tabs).

## Microinteractions stance
- Thành công thấy được trên màn hình → im lặng.
- Toast chỉ cho: lỗi, việc chạy nền, thao tác làm dòng biến khỏi danh sách đang xem.
- Thao tác tiền không hoàn tác được → xác nhận 2 bước ngay trong form.

## CTA voice
- Chính: nền `primary-strong` (xanh), chữ trắng, bo 6px, icon trong dòng + động từ ngắn.
- Phụ: viền `rule`, nền `surface`.
- Nguy hiểm: chữ + viền đỏ son — chỉ cho hủy/chấm dứt.

## Exports
### tokens.css
Khối `:root` (sáng) và `[data-theme="dark"]` / `prefers-color-scheme: dark` (tối) ở đầu
`web/app.css` là nguồn duy nhất của token.

## Provenance
Hệ thiết kế được xây cho dự án này (custom, studied: no) — 24/10/2026.
