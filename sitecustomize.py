"""Ensure src/ is on sys.path for src-layout imports when running in repo.

Python automatically imports `sitecustomize` if present on sys.path.
This keeps `python -m gp_assistant` and `import gp_assistant` pointing to src/gp_assistant.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists():
    s = str(SRC)
    if s not in sys.path:
        sys.path.insert(0, s)

