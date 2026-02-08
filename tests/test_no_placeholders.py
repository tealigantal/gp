from __future__ import annotations

import ast
from pathlib import Path


BANNED_TOKENS = ["TODO", "NotImplementedError", "placeholder"]


def is_empty_function(node: ast.FunctionDef) -> bool:
    # Only docstring or pass
    body = node.body
    if not body:
        return True
    if len(body) == 1:
        if isinstance(body[0], ast.Pass):
            return True
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            return True
    return False


def test_no_placeholders():
    root = Path("src")
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        low = text.lower()
        assert "todo" not in low
        assert "placeholder" not in low
        assert "notimplementederror" not in low
        # AST check
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert not is_empty_function(node), f"empty function in {py}: {node.name}"

