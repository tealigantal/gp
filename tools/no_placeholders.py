from __future__ import annotations

import ast
from pathlib import Path


def is_empty_function(node: ast.FunctionDef) -> bool:
    body = node.body
    if not body:
        return True
    if len(body) == 1:
        if isinstance(body[0], ast.Pass):
            return True
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            return True
    return False


def main() -> int:
    root = Path("src")
    bad = []
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        low = text.lower()
        for k in ("todo", "placeholder", "notimplementederror"):
            if k in low:
                bad.append((str(py), f"token:{k}"))
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and is_empty_function(node):
                bad.append((str(py), f"empty:{node.name}"))
    if bad:
        for f, r in bad:
            print("BAD:", f, r)
        return 1
    print("OK: no placeholders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

