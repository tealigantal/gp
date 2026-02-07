from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

from gp_core.schemas import StrategySpec


@dataclass
class StrategyRegistry:
    items: List[StrategySpec]

    @classmethod
    def load(cls, path: Path) -> "StrategyRegistry":
        raw = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        specs = [StrategySpec(**it) for it in raw.get('strategies', [])]
        if not specs:
            raise RuntimeError('strategies.yaml empty; define at least one strategy')
        return cls(items=specs)

    def by_id(self, sid: str) -> StrategySpec:
        for it in self.items:
            if it.id == sid:
                return it
        raise KeyError(sid)

