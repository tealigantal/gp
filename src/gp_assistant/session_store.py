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
        content = _redact(content)
        meta = _redact_meta(meta or {})
        evt = SessionEvent(kind=kind, content=content, meta=meta, ts=time.time())
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(evt), ensure_ascii=False) + '\n')


def _redact(s: str) -> str:
    # Basic API key redaction: mask strings starting with sk-; and common env names
    import re
    s = re.sub(r"sk-[A-Za-z0-9]{4,}", "sk-***", s)
    s = re.sub(r"(api[_-]?key\s*[:=]\s*)([A-Za-z0-9_\-]{4,})", r"\1***", s, flags=re.IGNORECASE)
    s = s.replace('DEEPSEEK_API_KEY', '***')
    return s


def _redact_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    def _mask(v):
        if isinstance(v, str):
            return _redact(v)
        if isinstance(v, dict):
            return _redact_meta(v)
        if isinstance(v, list):
            return [_mask(x) for x in v]
        return v
    return {k: _mask(v) for k, v in meta.items()}
