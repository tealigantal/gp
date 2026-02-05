from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable, List, Tuple


DEFAULT_INCLUDE = ["README.md", "configs/**/*.yaml", "src/**/*.py", "项目计划.txt"]
DEFAULT_EXCLUDE = ["data/**", "results/**", "EMQuantAPI_Python/**", "cache/**", "store/**"]


def iter_files(root: Path, includes: List[str], excludes: List[str]) -> Iterable[Path]:
    all_paths = root.rglob("*")
    for p in all_paths:
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        s = str(rel).replace('\\', '/')
        if excludes and any(fnmatch.fnmatch(s, pat) for pat in excludes):
            continue
        if includes and not any(fnmatch.fnmatch(s, pat) for pat in includes):
            continue
        yield p


def search(root: Path, query: str, includes: List[str] | None = None, excludes: List[str] | None = None, max_hits: int = 8) -> List[Tuple[str, str]]:
    includes = includes or DEFAULT_INCLUDE
    excludes = (excludes or DEFAULT_EXCLUDE) + ["store/assistant/**"]
    q = query.lower()
    hits: List[Tuple[str, str]] = []
    for p in iter_files(root, includes, excludes):
        try:
            txt = p.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        if q in txt.lower():
            snippet = _first_context(txt, q, 360)
            hits.append((str(p.relative_to(root)), snippet))
            if len(hits) >= max_hits:
                break
    return hits


def _first_context(text: str, q: str, window: int) -> str:
    low = text.lower()
    i = low.find(q)
    if i < 0:
        return text[:window]
    start = max(0, i - window // 2)
    end = min(len(text), i + window // 2)
    return text[start:end]

