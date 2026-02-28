from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class ChampionRecord:
    champion_id: str
    selected_at: str
    seed: int
    git_commit: Optional[str]
    strategy_type: str
    params: Dict[str, Any]
    params_hash: str
    scenario: str
    robust: Dict[str, Any]
    constraints: Dict[str, Any]
    warnings: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "champion_id": self.champion_id,
            "selected_at": self.selected_at,
            "seed": self.seed,
            "git_commit": self.git_commit,
            "strategy_type": self.strategy_type,
            "params": self.params,
            "params_hash": self.params_hash,
            "scenario": self.scenario,
            "robust": self.robust,
            "constraints": self.constraints,
            "warnings": self.warnings,
        }


def write_champion_registry(path: Path, record: ChampionRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def read_champion_registry(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

