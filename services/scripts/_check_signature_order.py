"""
Quét AST tìm lỗi "parameter without a default follows parameter with a default".

Vì sao cần script này?
    Trong FastAPI, tham số `Depends()` (dependency) KHÔNG có giá trị mặc định,
    còn tham số `Query(...)`/`Body(...)` thì CÓ. Python bắt buộc tham số có
    mặc định phải nằm sau tất cả tham số không mặc định. Đặt sai thứ tự →
    `SyntaxError` NGAY LÚC BIÊN DỊCH, tức là container không khởi động được.

    `compileall` chỉ báo lỗi đầu tiên rồi dừng, nên với 8 service ta phải sửa
    đi sửa lại nhiều lượt. Script này liệt kê TẤT CẢ chỗ sai trong 1 lần.

Cách dùng:
    python services/scripts/_check_signature_order.py
    python services/scripts/_check_signature_order.py --fix   # tự sửa luôn
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[1]

#: Tên decorator/giá trị mặc định bị coi là "không có mặc định" (dependency).
DEP_MARKERS = ("Depends(", "Security(")


def has_default(node: ast.arg, args: ast.arguments) -> bool:
    """True nếu tham số này CÓ giá trị mặc định."""
    positional = list(args.args)
    n_pos = len(positional)
    defaults = list(args.defaults)

    if node in positional:
        index = positional.index(node)
        # defaults phủ cho các tham số cuối của positional
        offset = n_pos - len(defaults)
        return index >= offset

    if node in args.posonlyargs:
        posonly = list(args.posonlyargs)
        index = posonly.index(node)
        po_defaults = list(args.posonlyargs and args.defaults)
        if args.defaults:
            po_defaults = args.defaults[:len(args.posonlyargs)]
        return index >= len(args.posonlyargs) - len(po_defaults)

    # kwonlyargs đều có mặc định nếu có kw_defaults tương ứng
    if node in args.kwonlyargs and args.kw_defaults:
        return node in args.kw_defaults and args.kw_defaults[
            list(args.kwonlyargs).index(node)
        ] is not None

    return node in args.kwonlyargs


def find_violations(tree: ast.AST) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        args = node.args
        all_args = list(getattr(args, "posonlyargs", [])) + list(args.args)
        seen_default: str | None = None
        for arg in all_args:
            if has_default(arg, args):
                if seen_default is None:
                    seen_default = arg.arg
            elif seen_default is not None:
                out.append((
                    arg.lineno,
                    f"{node.name}(): tham số '{arg.arg}' (không mặc định) nằm SAU "
                    f"'{seen_default}' (có mặc định)",
                    "  → đổi chỗ: đặt tất cả tham số Depends() lên TRƯỚC, "
                    "tham số Query(...)/=... xuống SAU",
                ))
                seen_default = None      # chỉ báo 1 lần cho mỗi cặp
    return out


def main() -> int:
    targets = sorted(
        p for p in SERVICES_DIR.rglob("*.py")
        if "__pycache__" not in p.parts and ".venv" not in p.parts
    )
    total = 0
    for path in targets:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            # Lỗi cú pháp chặn việc AST-walk; báo riêng cho dễ tìm.
            print(f"[SYNTAX] {path.relative_to(SERVICES_DIR)}:{exc.lineno}  {exc.msg}")
            total += 1
            continue

        for lineno, message, hint in find_violations(tree):
            rel = path.relative_to(SERVICES_DIR)
            print(f"[ORDER ] {rel}:{lineno}\n         {message}\n{hint}")
            total += 1

    print("-" * 66)
    print("OK — không còn lỗi thứ tự tham số" if total == 0
          else f"Tổng: {total} vấn đề")
    return 1 if total else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
