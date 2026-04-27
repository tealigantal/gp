from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cli_module_executes_main():
    env = dict(os.environ)
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(src) if not existing else os.pathsep.join([str(src), existing])
    proc = subprocess.run(
        [sys.executable, "-m", "gp_assistant.cli"],
        capture_output=True,
        text=True,
        cwd=str(root),
        env=env,
    )
    assert proc.returncode != 0
    assert "usage:" in (proc.stderr or "").lower() or "required" in (proc.stderr or "").lower()
