from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


def _atomic_replace(dst: Path, tmp_path: Path) -> None:
    """Atomically replace dst with tmp_path using os.replace.

    Ensures parent exists. Caller is responsible for writing all contents to tmp_path.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Best-effort fsync on tmp file before replace
    try:
        with open(tmp_path, "rb", buffering=0) as f:  # type: ignore[arg-type]
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception:
        pass
    os.replace(str(tmp_path), str(dst))


def write_json_atomic(path: Path, obj: Any) -> None:
    """Write JSON atomically to path.

    - Writes to a sibling temporary file then os.replace to target.
    - Uses UTF-8 encoding and pretty formatting.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create tmp file in the same directory for atomicity on the same filesystem
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), prefix=path.name + ".", suffix=".tmp") as tf:
        tmp_name = Path(tf.name)
        json.dump(obj, tf, ensure_ascii=False, indent=2)
    _atomic_replace(path, tmp_name)


def write_csv_atomic(path: Path, df: pd.DataFrame, *, index: bool = False) -> None:  # type: ignore[name-defined]
    """Write CSV atomically to path from a pandas DataFrame."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), prefix=path.name + ".", suffix=".tmp") as tf:
        tmp_name = Path(tf.name)
        df.to_csv(tf, index=index)
    _atomic_replace(path, tmp_name)


def copy_atomic(src: Path, dst: Path) -> None:
    """Atomically copy file from src to dst.

    Copies to a tmp file in dst dir and replaces.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(dst.parent), prefix=dst.name + ".", suffix=".tmp") as tf:
        tmp_name = Path(tf.name)
        with open(src, "rb") as fsrc:
            while True:
                chunk = fsrc.read(1024 * 1024)
                if not chunk:
                    break
                tf.write(chunk)
    _atomic_replace(dst, tmp_name)

