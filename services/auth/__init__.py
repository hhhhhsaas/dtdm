"""
auth-service — Xác thực & phân quyền (Identity & Access Management).

  Cổng    : 8001
  Database: db_auth
  Entry   : main.py  (uvicorn main:app, working_dir=/app/services/auth)

⚠️  File này CỐ TÌNH rỗng (chỉ có docstring).
    Container chạy `uvicorn main:app` với `working_dir=/app/services/auth`, nên
    `main` được import như module TOP-LEVEL — không phải `auth.main`.
    Nếu thêm `from .main import app` ở đây thì:
      - Python phải nạp `services/auth` như package → kéo theo cả `common`
      - Và tệ hơn: `main` lúc đó lại import chính nó theo 2 đường khác nhau
        (`auth.main` và `main`) → tạo HAI App FastAPI riêng biệt trong 1 process.
    Giữ `__init__.py` rỗng là chủ ý, KHÔNG phải thiếu sót.
"""
