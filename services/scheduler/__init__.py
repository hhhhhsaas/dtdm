"""
scheduler — Trình chạy job định kỳ (cron) cho toàn hệ thống.

  Cổng    : 8009  (chỉ /health + /metrics — KHÔNG có API nghiệp vụ)
  Database: không dùng (chỉ Redis cho khoá phân tán)
  Entry   : main.py  (python -m main, working_dir=/app/services/scheduler)

⭐ Vì sao tách thành container riêng?
  Khi một service chạy N replica mà job nền nằm BÊN TRONG service đó, thì
  mỗi replica đều chạy job → ghi N lần → người thuê nhận N tin nhắn nhắc
  tiền vào 8h sáng. Tách scheduler ra khỏi service, chạy đúng 1 bản, rồi
  dùng khoá phân tán Redis (`SET NX EX`) để chống chạy trùng cả khi
  vô tình scale scheduler lên 2 bản.

File này CỐ TÌNH chỉ có docstring — xem giải thích dài ở `services/auth/__init__.py`.
"""
