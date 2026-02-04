from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


DEFAULTS: Dict[str, Any] = {
    "paths": {
        "root": ".",
        "store": "store",
        "cache": "cache",
        "results": "results",
        "universe": "universe",
        "schemas": "schema",
    },
    "datapool": {
        "engine": "duckdb+parquet",
        "parquet_compression": "zstd",
    },
    "fetch": {
        "rate_limit_per_host_per_sec": 2,
        "retries": 2,
        "timeout_sec": 15,
        "user_agent": "gp/0.1 (+https://local)",
        "proxies": None,
    },
    "report": {
        "disclaimer": (
            "本报告仅供研究与教育用途，不构成任何投资建议。"
            "策略执行严格遵守：两段盯盘、Gap/压力带禁买、时间止损、禁摊平、Q0–Q3 噪声约束。"
        )
    },
}


@dataclass
class Config:
    raw: Dict[str, Any]

    @property
    def root(self) -> Path:
        return Path(self.raw["paths"]["root"]).resolve()

    @property
    def store(self) -> Path:
        return self.root / self.raw["paths"]["store"]

    @property
    def cache(self) -> Path:
        return self.root / self.raw["paths"]["cache"]

    @property
    def results(self) -> Path:
        return self.root / self.raw["paths"]["results"]

    @property
    def universe(self) -> Path:
        return self.root / self.raw["paths"]["universe"]

    @property
    def schemas(self) -> Path:
        return self.root / self.raw["paths"]["schemas"]


def deep_update(d: Dict[str, Any], u: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in u.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def load_config() -> Config:
    # Load from configs/config.yaml if present; else use defaults
    repo_root = Path.cwd()
    cfg_path_candidates = [
        repo_root / "config.yaml",
        repo_root / "configs" / "config.yaml",
    ]
    cfg: Dict[str, Any] = DEFAULTS.copy()
    found = None
    for p in cfg_path_candidates:
        if p.exists():
            found = p
            with p.open("r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            cfg = deep_update(cfg, user_cfg)
            break
    # Env overrides (simple): GP_STORE, GP_CACHE, HTTP_PROXY, HTTPS_PROXY
    if os.getenv("GP_STORE"):
        cfg["paths"]["store"] = os.getenv("GP_STORE")
    if os.getenv("GP_CACHE"):
        cfg["paths"]["cache"] = os.getenv("GP_CACHE")
    if os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY"):
        cfg.setdefault("fetch", {})["proxies"] = {
            "http": os.getenv("HTTP_PROXY"),
            "https": os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY"),
        }
    return Config(cfg)

