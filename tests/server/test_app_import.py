from __future__ import annotations

import os
os.environ.setdefault("PYTHONPATH", "src")


def test_app_import_ok():
    import gp_assistant.gateway.app as app  # noqa: F401

