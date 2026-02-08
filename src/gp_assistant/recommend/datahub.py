# 简介：行情数据枢纽。聚合本地夹带数据、数据提供者与降级合成数据，
# 统一为标准 OHLCV 格式并做必要缓存与健康元信息标注。
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import requests

from ..core.paths import store_dir
from ..core.config import load_config
from ..providers.factory import get_provider
from ..tools.market_data import normalize_daily_ohlcv


def _cache_path(kind: str, key: str) -> Path:
    p = store_dir() / "cache" / kind
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{key}.json"


def _save_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


@dataclass
class MarketDataHub:
    """Multi-source market data with caching and unified schema."""

    timeout: int = 15

    def _from_fixtures(self, symbol: str) -> Optional[pd.DataFrame]:
        # Optional offline fixtures under store/fixtures/bars/<symbol>.csv
        root = store_dir() / "fixtures" / "bars"
        for suffix in [".csv", ".parquet", ".json"]:
            fp = root / f"{symbol}{suffix}"
            if fp.exists():
                try:
                    if suffix == ".csv":
                        df = pd.read_csv(fp)
                    elif suffix == ".parquet":
                        df = pd.read_parquet(fp)
                    else:
                        df = pd.DataFrame(json.loads(fp.read_text(encoding="utf-8")))
                    return df
                except Exception:
                    continue
        return None

    def daily_ohlcv(self, symbol: str, as_of: Optional[str] = None, min_len: int = 250) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        # Try fixtures -> provider -> degrade error info but keep DataFrame minimal
        df: Optional[pd.DataFrame] = self._from_fixtures(symbol)
        meta: Dict[str, Any] = {"source": None}
        if df is not None:
            meta["source"] = "fixtures"
        else:
            try:
                provider = get_provider()
                raw = provider.get_daily(symbol, start=None, end=as_of)
                df = raw
                meta["source"] = f"provider:{provider.name}"
            except Exception as e:  # noqa: BLE001
                # last resort: try a public CSV from stooq-like endpoints (skip for stability)
                df = None
                meta["error"] = f"daily_ohlcv_failed:{e}"
        if df is None or len(df) == 0:
            # Provide a minimal 30-row synthetic flat series so indicator engine can run (marked insufficient)
            idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=30)
            df = pd.DataFrame({
                "date": idx,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 10000,
            })
            meta["source"] = meta.get("source") or "synthetic"
            meta["insufficient"] = True
        df_norm, m = normalize_daily_ohlcv(df)
        meta.update(m)
        meta["len"] = len(df_norm)
        meta["insufficient_history"] = len(df_norm) < min_len
        df_norm.attrs.update(meta)
        return df_norm, meta

    def index_daily(self, symbol: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        # re-use daily_ohlcv
        return self.daily_ohlcv(symbol, None, min_len=120)

    def market_stats(self) -> Dict[str, Any]:
        # Attempt to fetch from cached sources; if failed, return degraded info with reasons
        key = "market_stats_today"
        cp = _cache_path("market", key)
        cached = _load_json(cp)
        if cached:
            return {**cached, "source": "cache"}
        stats = {
            "total_amount": None,
            "limit_up": None,
            "limit_down": None,
            "seal_rate": None,
            "ladder_max": None,
            "ladder_breaks": None,
            "_reason": None,
        }
        try:
            # Example: scrape a lightweight page for total amount (fallback); keep robust by regex
            resp = requests.get("https://finance.sina.com.cn/stock/", timeout=self.timeout)
            resp.raise_for_status()
            # Minimal heuristic extraction
            if "A股" in resp.text or "沪深" in resp.text:
                stats["_reason"] = "webpage_ok"
        except Exception as e:  # noqa: BLE001
            stats["_reason"] = f"fetch_failed:{e}"
        _save_json(cp, stats)
        return {**stats, "source": "web+cache"}
