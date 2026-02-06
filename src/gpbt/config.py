from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass
class Paths:
    data_root: Path
    universe_root: Path
    results_root: Path

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Paths":
        return cls(
            data_root=Path(d.get("data_root", "data")),
            universe_root=Path(d.get("universe_root", "universe")),
            results_root=Path(d.get("results_root", "results")),
        )


@dataclass
class Fees:
    commission_rate: float = 0.0003
    commission_cap: float = 0.0013
    transfer_fee_rate: float = 0.00001
    stamp_duty_rate: float = 0.0005
    slippage_bps: int = 3
    min_commission: float = 0.0


@dataclass
class UniverseCfg:
    min_list_days: int = 60
    exclude_st: bool = True
    min_amount: float = 1.0e7
    min_vol: int = 1


@dataclass
class BarsCfg:
    daily_adj: str = "qfq"  # none | qfq
    min_freq: str = "5min"


@dataclass
class ExperimentCfg:
    candidate_size: int = 20
    initial_cash: float = 1_000_000
    run_id: str = "default"
    require_trades: bool = False


@dataclass
class AppConfig:
    provider: str
    paths: Paths
    fees: Fees
    universe: UniverseCfg
    bars: BarsCfg
    experiment: ExperimentCfg

    @classmethod
    def load(cls, path: str | os.PathLike) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        provider = data.get("provider", "tushare")
        paths = Paths.from_dict(data)
        fees = Fees(**(data.get("fees", {}) or {}))
        uraw = (data.get("universe", {}) or {})
        # Coerce numeric types robustly (YAML like 1.0e7 may parse as str)
        if 'min_amount' in uraw:
            try:
                uraw['min_amount'] = float(uraw['min_amount'])
            except Exception:
                pass
        if 'min_vol' in uraw:
            try:
                uraw['min_vol'] = int(float(uraw['min_vol']))
            except Exception:
                pass
        universe = UniverseCfg(**uraw)
        bars = BarsCfg(**(data.get("bars", {}) or {}))
        experiment = ExperimentCfg(**(data.get("experiment", {}) or {}))
        return cls(provider, paths, fees, universe, bars, experiment)

    def ensure_dirs(self) -> None:
        # Create needed directories
        (self.paths.data_root / "raw").mkdir(parents=True, exist_ok=True)
        (self.paths.data_root / "bars" / "daily").mkdir(parents=True, exist_ok=True)
        (self.paths.data_root / "bars" / "min5").mkdir(parents=True, exist_ok=True)
        self.paths.universe_root.mkdir(parents=True, exist_ok=True)
        self.paths.results_root.mkdir(parents=True, exist_ok=True)
