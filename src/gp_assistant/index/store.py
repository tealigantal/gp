from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Tuple


class IndexStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.jsonl = db_path.with_suffix('.jsonl')
        self.use_sqlite = db_path.exists()

    def search(self, q: str, topk: int = 6) -> List[Tuple[str, str]]:
        if self.use_sqlite:
            con = sqlite3.connect(str(self.db_path))
            cur = con.cursor()
            cur.execute('SELECT path, snippet(docs, 1, "", "", "...", 12) FROM docs WHERE docs MATCH ? LIMIT ?', (q, topk))
            rows = cur.fetchall()
            con.close()
            return [(r[0], r[1]) for r in rows]
        else:
            hits: List[Tuple[str, str]] = []
            if not self.jsonl.exists():
                return hits
            low = q.lower()
            with open(self.jsonl, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    path = obj.get('path', '')
                    content = obj.get('content', '')
                    if low in content.lower():
                        start = max(0, content.lower().find(low) - 180)
                        end = min(len(content), start + 360)
                        hits.append((path, content[start:end]))
                        if len(hits) >= topk:
                            break
            return hits

