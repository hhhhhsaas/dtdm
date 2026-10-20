#!/usr/bin/env python3
# ============================================================================
#  SMOKE TEST TOÀN HỆ THỐNG — chạy bằng: make test-int
#
#  Ý NGHĨA: sau khi `make up && make seed`, script này đóng vai
#  "kiểm thử viên" gõ từng lệnh curl quan trọng nhất, kiểm tra đúng hợp đồng
#  (HTTP code + cấu trúc JSON), và TỔNG KẾT pass/fail để nhân viên vận hành
#  biết hệ thống còn chạy được hay không.
#
#  NGUYÊN TẮC (vì sao viết dài mà không dùng pytest):
#  - Chạy bằng Python stdlib THUẦN — server Ubuntu chỉ cần `python3`, không
#    cần cài requests/pytest. Đúng tinh thần "dev experience tối giản" của
#    phần kiểm thử vận hành (khác hẳn unit test chạy trong container).
#  - CÁC THAY ĐỔI DỮ LIỆU đều IDEMPOTENT (đăng nhập, đọc báo cáo, chạy
#    reconcile 2 lần) — chạy lại bao nhiêu lần cũng được, không phá dữ liệu.
#
#  KẾT QUẢ: 0 = mọi thứ OK ; 1 = có lỗi (dùng cho CI / cron giám sát).
# ============================================================================
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
#  CẤU HÌNH — có thể ghi đè bằng biến môi trường
# ---------------------------------------------------------------------------
BASE = os.environ.get("QLPT_BASE_URL", "http://127.0.0.1")
ADMIN_USER = os.environ.get("QLPT_ADMIN_USER", "admin")
TENANT_USER = os.environ.get("QLPT_TENANT_USER", "khach01")
TENANT_PWD = os.environ.get("QLPT_TENANT_PWD", "Tenant@12345")

#: (cổng service, tên hiển thị) — 8009 scheduler không public nên kiểm riêng
APP_PORTS = {
    8001: "auth",
    8002: "room",
    8003: "tenant",
    8004: "contract",
    8005: "billing",
    8006: "notification",
    8007: "maintenance",
    8008: "report",
}

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent

RESULT = []  # list[tuple[name, status, detail]]


# ---------------------------------------------------------------------------
#  TIỆN ÍCH MẠNG (stdlib)
# ---------------------------------------------------------------------------
def api(method: str, path: str, token: str | None = None,
        body: dict | None = None, port: int | None = None) -> tuple[int, dict]:
    """Gọi API. Trả về (status_code, json). Port mặc định = cổng 8001 (auth)."""
    url = f"{BASE}:{port or 8001}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}
    except Exception as exc:  # smoke test phải bắt mọi thứ và tiếp tục
        return -1, {"error": str(exc)}


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "✅ PASS" if ok else "❌ FAIL"
    RESULT.append((name, "PASS" if ok else "FAIL", detail))
    print(f"  {status}  {name}" + (f"  — {detail}" if detail else ""))


def shell(cmd: list[str], timeout: int = 60) -> str:
    """Chạy lệnh trên host (cho scheduler + tạo token nội bộ)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} thất bại: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
#  NHÓM 1 — SỨC KHOẺ TỪNG SERVICE
# ---------------------------------------------------------------------------
def group_health() -> None:
    print("\n[1/6] Sức khoẻ từng service (HTTP /health)…")
    all_ok = True
    for port, name in APP_PORTS.items():
        code, _ = api("GET", "/health", port=port)
        ok = code == 200
        all_ok &= ok
        check(f"/health {name}:{port}", ok, f"HTTP {code}")
    check("scheduler:8009 (qua docker compose exec)", scheduler_health(),
          "nội bộ, không public ra host")


def scheduler_health() -> bool:
    try:
        out = shell([
            "docker", "compose", "exec", "-T", "scheduler", "python", "-c",
            "import urllib.request;"
            "print(urllib.request.urlopen('http://localhost:8009/health',timeout=5).status)",
        ])
        return out == "200"
    except Exception:  # smoke test tiếp tục dù không có docker
        return False


# ---------------------------------------------------------------------------
#  NHÓM 2 — ĐĂNG NHẬP & VÒNG ĐỜI TOKEN
# ---------------------------------------------------------------------------
def group_auth() -> str:
    print("\n[2/6] Đăng nhập & vòng đời token…")

    # 2a. Sai mật khẩu → 401, thông báo KHÔNG tiết lộ tài khoản tồn tại
    code, data = api("POST", "/api/v1/auth/login",
                     body={"username": ADMIN_USER, "password": "sai-mat-khau"})
    check("Đăng nhập sai mật khẩu bị từ chối (401)", code == 401, f"HTTP {code}")

    # 2b. Đăng nhập admin thành công
    pwd = _read_admin_password()
    code, data = api("POST", "/api/v1/auth/login",
                     body={"username": ADMIN_USER, "password": pwd})
    ok = code == 200 and data.get("access_token")
    check("Đăng nhập admin", ok, "có access_token" if ok else f"HTTP {code}: {data}")
    if not ok:
        print("  ⚠️  Bạn đã chạy `make seed` chưa? Thiếu admin thì chạy lại.")
        sys.exit(1)
    token = data["access_token"]

    # 2c. /auth/me trả đúng vai trò
    code, me = api("GET", "/api/v1/auth/me", token=token)
    check("GET /auth/me", code == 200 and me.get("role") == "ADMIN",
          f"role={me.get('role')}" if code == 200 else f"HTTP {code}")

    # 2d. Endpoint staff không cho token bị thiếu
    code, _ = api("GET", "/api/v1/rooms/stats", port=8002)
    check("Thiếu token bị chặn (401)", code == 401, f"HTTP {code}")
    return token


def _read_admin_password() -> str:
    """Đọc mật khẩu admin — giống cách seed_auth đọc.

    Thứ tự ưu tiên:
      1) biến môi trường QLPT_ADMIN_PWD (tiện khi không có quyền root),
      2) file secret mount trong container (/run/secrets/admin_password.txt),
      3) secrets/admin_password.txt của dự án,
      4) .env.admin_password.txt,
      5) mặc định 'Admin@12345' (máy mới, chưa tạo secret).

    ⚠️ Thư mục secrets/ thường là 700 root-only. Nếu file secret TỒN TẠI nhưng
    KHÔNG đọc được, ta KHÔNG âm thầm dùng mật khẩu mặc định (sẽ login 401 rất
    khó hiểu) mà báo lỗi rõ ràng kèm cách khắc phục.
    """
    env = os.environ.get("QLPT_ADMIN_PWD", "").strip()
    if env:
        return env

    candidates = [
        Path("/run/secrets/admin_password.txt"),
        _PROJECT_ROOT / "secrets" / "admin_password.txt",
        _PROJECT_ROOT / ".env.admin_password.txt",
    ]
    unreadable: list[Path] = []
    for path in candidates:
        try:
            if not path.is_file():
                continue
            value = path.read_text(encoding="utf-8").strip()
        except PermissionError:
            # is_file()/read_text() ném PermissionError khi thư mục cha (secrets/)
            # không cho user hiện tại truy cập → ghi nhận để báo lỗi ở dưới.
            unreadable.append(path)
            continue
        except OSError:
            continue
        if value:
            return value

    if unreadable:
        print(f"  ❌ Không đọc được file secret: {', '.join(str(p) for p in unreadable)}")
        print("     File mật khẩu chỉ cho root đọc (file 600, thư mục secrets/ 700).")
        print("     Cách khắc phục — chọn 1 trong 2:")
        print("       • chạy bằng root :  sudo make test-int")
        print("       • truyền mật khẩu:  QLPT_ADMIN_PWD=\"$(sudo cat secrets/admin_password.txt)\" make test-int")
        sys.exit(1)

    return "Admin@12345"  # mặc định của seed_auth


# ---------------------------------------------------------------------------
#  NHÓM 3 — DỮ LIỆU MẪU ĐÃ NẠP (SỐ LIỆU THẬT CỦA MAKE SEED)
# ---------------------------------------------------------------------------
def group_seed_data(token: str) -> None:
    print("\n[3/6] Kiểm tra dữ liệu mẫu đã nạp…")

    code, stats = api("GET", "/api/v1/rooms/stats", token=token, port=8002)
    ok = code == 200 and stats.get("total", 0) >= 20
    check("Phòng (>= 20)", ok,
          f"tổng={stats.get('total')}, lấp đầy={stats.get('occupancy_rate')}%"
          if code == 200 else f"HTTP {code}")

    code, inv = api("GET", "/api/v1/invoices/stats", token=token, port=8005)
    ok = code == 200 and inv.get("total_invoices", 0) >= 27
    check("Hóa đơn (>= 27)", ok,
          f"tổng={inv.get('total_invoices')}, thu={inv.get('collection_rate')}%"
          if code == 200 else f"HTTP {code}")

    # Hợp đồng: kỳ vọng 9 ACTIVE khi chạy seed_contract
    code, con = api("GET", "/api/v1/contracts", token=token, port=8004)
    ok = code == 200 and len(con.get("items", [])) >= 9
    check("Hợp đồng (>= 9)", ok,
          f"{len(con.get('items', []))} bản" if code == 200 else f"HTTP {code}")


# ---------------------------------------------------------------------------
#  NHÓM 4 — NGHIỆP VỤ CỐT LÕI (kết quả trả về đúng cấu trúc)
# ---------------------------------------------------------------------------
def group_business(token: str) -> None:
    print("\n[4/6] Nghiệp vụ cốt lõi…")

    # Tìm phòng trống — endpoint CÔNG KHAI, không cần token
    code, avail = api("GET", "/api/v1/rooms/available", port=8002)
    ok = code == 200 and isinstance(avail.get("items", []), list)
    check("Tìm phòng trống (công khai)", ok,
          f"{len(avail.get('items', []))} phòng" if ok else f"HTTP {code}")

    # Hóa đơn trả về tiền dạng chuỗi số hợp lệ (Decimal serialize thế nào)
    code, inv = api("GET", "/api/v1/invoices?page_size=5", token=token, port=8005)
    amounts_ok = True
    if code == 200:
        for item in inv.get("items", []):
            raw = item.get("total_amount")
            try:
                float(str(raw))
            except (TypeError, ValueError):
                amounts_ok = False
                break
    check("Hóa đơn: tổng tiền là số hợp lệ", code == 200 and amounts_ok,
          f"HTTP {code}")

    # Báo cáo dashboard: cấu trúc đủ kpi (có thể chưa có dữ liệu nếu chưa reconcile)
    code, dash = api("GET", "/api/v1/reports/dashboard", token=token, port=8008)
    ok = code == 200 and "kpi" in dash and "freshness" in dash
    stale = dash.get("freshness", {}).get("is_stale", True)
    check("Dashboard báo cáo", ok,
          ("⚠️ dữ liệu chưa sync — chờ 6h hoặc chạy make reconcile" if stale
           else "dữ liệu đã sync")
          if ok else f"HTTP {code}")


# ---------------------------------------------------------------------------
#  NHÓM 5 — RBAC (phân quyền) & HỢP ĐỒNG LỖI
# ---------------------------------------------------------------------------
def group_rbac() -> None:
    print("\n[5/6] RBAC & hợp đồng lỗi…")

    # Người thuê đăng nhập được
    code, data = api("POST", "/api/v1/auth/login",
                     body={"username": TENANT_USER, "password": TENANT_PWD})
    ok = code == 200 and data.get("access_token")
    check(f"Người thuê {TENANT_USER} đăng nhập", ok, f"HTTP {code}")
    if not ok:
        check("Người thuê bị chặn truy cập danh sách phòng", False, "không có token")
        return
    tenant_token = data["access_token"]

    # Người thuê KHÔNG được xem danh sách phòng (chỉ ADMIN/MANAGER)
    code, _ = api("GET", "/api/v1/rooms", token=tenant_token, port=8002)
    check("TENANT bị chặn khi xem danh sách phòng (403)", code == 403,
          f"HTTP {code}")

    # Body JSON rác phải trả 422 (validate của Pydantic)
    code, _ = api("POST", "/api/v1/auth/login",
                  body={"username": "x", "password": 12345})
    check("Payload sai kiểu bị chặn (422)", code == 422, f"HTTP {code}")


# ---------------------------------------------------------------------------
#  NHÓM 6 — ĐỐI CHIẾU READ MODEL (make reconcile) + IDEMPOTENT
# ---------------------------------------------------------------------------
def group_reconcile() -> None:
    print("\n[6/6] Đối chiếu read model (reconcile)…")
    # 6a. Không token nội bộ → 403 (SYSTEM role bắt buộc)
    code, _ = api("POST", "/internal/v1/reports/reconcile", port=8008)
    check("Reconcile thiếu SYSTEM token bị chặn (403)", code in (401, 403),
          f"HTTP {code}")

    # 6b. Mint token nội bộ NGAY TRONG container (nơi có JWT_SECRET)
    try:
        tok = shell([
            "docker", "compose", "exec", "-T", "report", "python", "-c",
            "from common.security import create_internal_token;"
            "print(create_internal_token('smoke-test'))",
        ])
    except Exception as exc:  # không có docker thì bỏ qua nhóm này
        check("Mint token nội bộ (SYSTEM)", False, str(exc)[:200])
        return

    check("Mint token nội bộ (SYSTEM)", len(tok) > 50, "role=SYSTEM")

    code, data = api("POST", "/internal/v1/reports/reconcile",
                     token=tok, port=8008)
    ok = code == 200 and data.get("status") in ("SUCCESS", "PARTIAL")
    check("Reconcile lần 1", ok,
          f"status={data.get('status')}, hóa đơn={data.get('invoices_synced')}"
          if code == 200 else f"HTTP {code} {data}")

    # 6c. Chạy LẠI lần 2 — phải idempotent, không lỗi
    code, _ = api("POST", "/internal/v1/reports/reconcile", token=tok, port=8008)
    check("Reconcile lần 2 (idempotent)", code == 200, f"HTTP {code}")


# ---------------------------------------------------------------------------
#  MAIN
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 68)
    print("  SMOKE TEST — Hệ thống QLPT (8 microservice + scheduler)")
    print(f"  Base URL: {BASE}    Ngày: {date.today().isoformat()}")
    print("=" * 68)

    token = None
    group_health()
    token = group_auth()
    group_seed_data(token)
    group_business(token)
    group_rbac()
    token = None  # không cần token nữa
    group_reconcile()

    # ---- Tổng kết ---------------------------------------------------------
    passed = sum(1 for _, s, _ in RESULT if s == "PASS")
    failed = len(RESULT) - passed
    print("\n" + "=" * 68)
    for name, status, _detail in RESULT:
        mark = "✅" if status == "PASS" else "❌"
        print(f"  {mark} {name}")
    print("=" * 68)
    print(f"  KẾT QUẢ: {passed}/{len(RESULT)} PASS"
          + ("  — 🎉 HỆ THỐNG SẴN SÀNG" if failed == 0 else f"  — {failed} LỖI!"))
    print("=" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
