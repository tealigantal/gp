from __future__ import annotations

# Lightweight shim to allow `python -m backtest.*` while keeping src-layout.
from src.backtest import *  # type: ignore

