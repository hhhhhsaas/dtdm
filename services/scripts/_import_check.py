"""
Kiểm tra nhanh: mọi service có import được không (không cần chạy server).

Cách dùng (từ thư mục gốc dự án):
    python services/scripts/_import_check.py            # tất cả
    python services/scripts/_import_check.py billing    # chỉ billing

Vì sao cần script này?
    Vì `main.py` của mỗi service có phần định nghĩa consumer được truyền vào
    `create_service_app(..., lifespan_extra=...)` — sai thứ tự thì lỗi
    `NameError` chỉ xuất hiện lúc IMPORT, không xuất hiện lúc viết code kiểu
    "chắc là được". Ở production, lỗi đó làm container không khởi động.

Script này KHÔNG kết nối database, KHÔNG cần RabbitMQ. Nó chỉ chứng minh
"module graph đúng" — điều kiện cần nhưng chưa đủ để hệ thống chạy.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# ---- Môi trường tối thiểu cho Settings ---------------------------------------
# Tên biến phải khớp CHÍNH XÁC với `Settings` trong `common/config.py`
# (pydantic-settings đọc theo tên trường, case-insensitive). Sai tên ở đây
# không báo "thiếu biến" mà báo "giá trị rỗng không hợp lệ" — rất khó đoán.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("JWT_SECRET", "x" * 48)
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "1" * 64)

# Windows: stdout mặc định dùng cp1252, in tiếng Việt sẽ vỡ UnicodeEncodeError
# và che mất thông báo lỗi thật sự. Đây chỉ là cách hiển thị, không liên quan
# gì tới logic của hệ thống.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SERVICES_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICES_DIR))

#: (tên thư mục, cổng, cờ "không phải microservice")
TARGETS: list[tuple[str, int]] = [
    ("auth", 8001),
    ("room", 8002),
    ("tenant", 8003),
    ("contract", 8004),
    ("billing", 8005),
    ("notification", 8006),
    ("maintenance", 8007),
    ("report", 8008),
    # Scheduler KHÔNG phải microservice nhưng có `app` ở cấp module (chỉ
    # /health + /metrics) nên kiểm tra được y hệt. Nhờ vậy lỗi import trong
    # scheduler cũng bị bắt ở CI chứ không chỉ lúc deploy.
    ("scheduler", 8009),
]


def check(name: str, port: int) -> bool:
    """
    Import `main.py` của service với `working_dir` giống hệt container.

    Mỗi service được nạp trong 1 tiến trình con riêng (`subprocess`) vì
    `main` là module top-level: nếu nạp nhiều service trong cùng tiến trình,
    module `main` của service thứ 2 sẽ đè lên service thứ 1 và ta sẽ tưởng
    cả 8 đều OK trong khi thực ra chỉ 1 cái được kiểm tra. Đây đúng là loại
    lỗi "test pass nhưng deploy fail" kinh điển.
    """
    import subprocess

    service_dir = SERVICES_DIR / name
    # ⭐ `cwd` phải là THƯ MỤC SERVICE, không phải `services/`.
    #   Trong container, compose đặt `working_dir: /app/services/<name>` và
    #   `PYTHONPATH=/app`. Nhờ vậy `from models import ...` (import top-level,
    #   không có `models.`) resolve được. Nếu check ở `services/` thì import
    #   thành công trên máy dev nhưng FAIL trong container — hoặc ngược lại.
    #   Đây chính là lý do compose khai báo `working_dir` cho từng service
    #   thay vì để uvicorn tự dò.
    env = dict(os.environ)
    env["SERVICE_NAME"] = f"{name}-service"
    env["PORT"] = str(port)
    env["PYTHONPATH"] = str(SERVICES_DIR)

    code = (
        "import importlib;"
        f"m = importlib.import_module('{name}.main');"
        "app = m.app;"
        "routes = sorted({r.path for r in app.routes});"
        "print('ROUTES=' + str(len(routes)));"
        "print('DOC=' + (app.description or '').splitlines()[0][:70])"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(service_dir), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print(f"FAIL  {name}-service")
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        for line in tail:
            print("      " + line)
        return False

    out = proc.stdout.strip().splitlines()
    routes = next((line for line in out if line.startswith("ROUTES=")), "ROUTES=?")
    print(f"OK    {name:<13} ({routes.removeprefix('ROUTES=')} route)")
    return True


def main() -> int:
    wanted = sys.argv[1:]
    targets = [t for t in TARGETS if not wanted or t[0] in wanted]
    missing = [t[0] for t in targets if not (SERVICES_DIR / t[0] / "main.py").exists()]

    results = [check(name, port) for name, port in targets if name not in missing]

    print("-" * 62)
    for name in missing:
        print(f"SKIP  {name}-service  (chưa có main.py)")
    print(f"Kết quả: {sum(results)}/{len(targets)} service import được")

    if not results:
        print("Không có service nào để kiểm tra.")
        return 1
    return 0 if all(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                     # pragma: no cover - chỉ để log rõ
        traceback.print_exc()
        sys.exit(2)
