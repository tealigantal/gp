from __future__ import annotations

import inspect
import pkgutil
import gp_assistant


def test_imports_from_src():
    mod = gp_assistant
    path = inspect.getfile(mod)
    assert "/src/gp_assistant/" in path.replace("\\", "/"), f"imported from wrong path: {path}"

