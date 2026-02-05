from __future__ import annotations

import fnmatch
import sqlite3
from pathlib import Path
from typing import Iterable, List, Tuple

from ..config import AssistantConfig


def _supports_fts5() -> bool:
    try:
        con = sqlite3.connect(':memory:')
        con.execute('CREATE VIRTUAL TABLE t USING fts5(x)')
        con.close()
        return True
    except Exception:
        return False


def _iter_files(root: Path, includes: List[str], excludes: List[str]) -> Iterable[Path]:
    for p in root.rglob('*'):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        s = str(rel).replace('\\', '/')
        if excludes and any(fnmatch.fnmatch(s, pat) for pat in excludes):
            continue
        if includes and not any(fnmatch.fnmatch(s, pat) for pat in includes):
            continue
        yield p


def build_index(cfg: AssistantConfig, force: bool = False) -> None:
    db_path = Path(cfg.rag.index_db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists() and not force:
        return
    use_fts = _supports_fts5()
    if use_fts:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute('DROP TABLE IF EXISTS docs')
        cur.execute('CREATE VIRTUAL TABLE docs USING fts5(path,content)')
        for p in _iter_files(cfg.workspace_root, cfg.rag.include_globs, cfg.rag.exclude_globs + ['results/**', 'store/**']):
            try:
                txt = p.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            cur.execute('INSERT INTO docs(path,content) VALUES(?,?)', (str(p.relative_to(cfg.workspace_root)), txt))
        con.commit()
        con.close()
    else:
        # Fallback to a simple JSONL index
        j = db_path.with_suffix('.jsonl')
        with open(j, 'w', encoding='utf-8') as f:
            for p in _iter_files(cfg.workspace_root, cfg.rag.include_globs, cfg.rag.exclude_globs + ['results/**', 'store/**']):
                try:
                    txt = p.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    continue
                f.write('{"path": ' + _json_str(str(p.relative_to(cfg.workspace_root))) + ', "content": ' + _json_str(txt) + '}\n')


def _json_str(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'

