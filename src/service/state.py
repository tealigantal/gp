from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional
import json


@dataclass
class PositionState:
    ts_code: str
    shares: int
    cost: float


@dataclass
class LiveState:
    date: str
    cash: float
    positions: Dict[str, PositionState]
    last_bar_time: Optional[str] = None

    @staticmethod
    def load(path: Path) -> "LiveState":
        if not path.exists():
            raise FileNotFoundError(str(path))
        obj = json.loads(path.read_text(encoding="utf-8"))
        pos = {k: PositionState(**v) for k, v in obj.get("positions", {}).items()}
        return LiveState(date=obj.get("date", ""), cash=float(obj.get("cash", 0.0)), positions=pos, last_bar_time=obj.get("last_bar_time"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        obj = {
            "date": self.date,
            "cash": self.cash,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "last_bar_time": self.last_bar_time,
        }
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

