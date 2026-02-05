from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


def safe_read(path: str, workspace: Path, allow_roots: List[Path] | None = None, max_bytes: int = 200_000) -> Tuple[str, int]:
    p = (workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    ws = workspace.resolve()
    if not str(p).startswith(str(ws)):
        raise PermissionError("Path outside workspace")
    if allow_roots:
        ok = False
        for r in allow_roots:
            if str(p).startswith(str(r.resolve())):
                ok = True
                break
        if not ok:
            raise PermissionError("Path not in allowed roots")
    if not p.exists():
        raise FileNotFoundError(str(p))
    data = p.read_bytes()
    data = data[:max_bytes]
    try:
        return data.decode('utf-8', errors='ignore'), len(data)
    except Exception:
        return data.decode('latin-1', errors='ignore'), len(data)

