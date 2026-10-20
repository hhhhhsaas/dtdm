"""
=============================================================================
 scripts/ — Tiện ích vận hành chạy NGOÀI HTTP server
=============================================================================

Bao gồm 2 nhóm:

1. **Nạp dữ liệu mẫu** (`seed_*.py`) — dùng cho demo đồ án và cho môi
   trường kiểm thử. Chạy bằng `make seed`.

2. **Kiểm tra tĩnh** (`_import_check.py`, `_check_signature_order.py`) —
   chạy trong CI, KHÔNG cần database.

⚠️  Tại sao seed KHÔNG dùng HTTP API?
    Nạp 20 hợp đồng + 200 hóa đơn qua API sẽ mất vài phút và để lại đúng
    những bản ghi "xấu" (thiếu event, sai số liệu tổng hợp) — tệ hơn nhiều
    so với ghi thẳng. Bù lại, dữ liệu seed BỎ QUA event bus, nên read model
    của report-service KHÔNG tự đầy; sau khi seed phải chạy
    `POST /internal/v1/reports/reconcile` (chính là job mà container
    `scheduler` chạy mỗi 6 giờ) để đối chiếu lại từ dữ liệu gốc.
"""
