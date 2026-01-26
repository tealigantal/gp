from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..config import AppConfig


@dataclass
class PolicySpec:
    as_of_date: str
    lookback_start: str
    lookback_end: str
    ranker_template_id: str
    entry_strategy_id: str
    exit_template_id: str
    topk: int
    target_pct: float
    max_positions: int
    score: float
    metrics: Dict[str, Any]
    notes: str = ""


class PolicyStore:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.base = cfg.paths.data_root / 'policies'
        self.base.mkdir(parents=True, exist_ok=True)

    def save_current(self, spec: PolicySpec) -> Path:
        cur = self.base / 'current_policy.json'
        cur.write_text(json.dumps(asdict(spec), ensure_ascii=False, indent=2), encoding='utf-8')
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        hist_dir = self.base / 'history'
        hist_dir.mkdir(parents=True, exist_ok=True)
        hist = hist_dir / f'{ts}_policy.json'
        hist.write_text(json.dumps(asdict(spec), ensure_ascii=False, indent=2), encoding='utf-8')
        return cur

    def load_current(self) -> Dict[str, Any]:
        cur = self.base / 'current_policy.json'
        if not cur.exists():
            raise RuntimeError('current_policy.json missing; run tune first')
        return json.loads(cur.read_text(encoding='utf-8'))

    def append_score(self, row: Dict[str, Any]) -> None:
        scores = self.base / 'scores.csv'
        if not scores.exists():
            scores.write_text(','.join(row.keys()) + '\n', encoding='utf-8')
        with open(scores, 'a', encoding='utf-8') as f:
            f.write(','.join(str(row[k]) for k in row.keys()) + '\n')

