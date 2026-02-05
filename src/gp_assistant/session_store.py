from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class SessionEvent:
    kind: str  # user|assistant|tool
    content: str
    meta: Dict[str, Any]
    ts: float


class SessionStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.path = self.base_dir / f'session_{ts}.jsonl'
        self.started = time.time()

    def append(self, kind: str, content: str, meta: Optional[Dict[str, Any]] = None):
        evt = SessionEvent(kind=kind, content=content, meta=meta or {}, ts=time.time())
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(evt), ensure_ascii=False) + '\n')

