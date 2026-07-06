from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from ..core.paths import store_dir
from ..search.history_store import canonical_query_id, list_items, list_queries


_CACHE: Dict[str, Any] = {"ts": 0.0, "result": None}


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def strategy_weight_from_samples(win_rate: float, avg_return: float) -> float:
    return float(1.0 + clamp((float(win_rate) - 0.5) * 0.8 + float(avg_return) * 5.0, -0.35, 0.25))


def _recommend_files(base: Path) -> List[Path]:
    if not base.exists():
        return []
    files = []
    for path in base.glob("*_v2.json"):
        name = path.name.lower()
        if name == "latest_v2.json" or "2099" in name:
            continue
        files.append(path)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _load_artifacts(limit_files: int = 180) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for path in _recommend_files(store_dir() / "recommend")[:limit_files]:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        as_of = str(obj.get("as_of") or "").strip()
        if not as_of or as_of in seen:
            continue
        seen.add(as_of)
        out.append(obj)
    return out


def _query_by_symbol() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for entry in list_queries(kind="daily"):
        params = dict(entry.get("params") or {})
        symbol = str(params.get("symbol") or "").strip()
        if not symbol:
            continue
        out[symbol] = params
    return out


def _bars_for_symbol(symbol: str, query_params: Dict[str, Dict[str, Any]], cache: Dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    if symbol in cache:
        return cache[symbol]
    params = query_params.get(symbol)
    if not params:
        return None
    try:
        qid = canonical_query_id(params)
        rows = list_items(qid)
    except Exception:
        return None
    if not rows:
        return None
    try:
        df = pd.DataFrame([row["payload"] for row in rows])
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    except Exception:
        return None
    cache[symbol] = df
    return df


def _tail_return(df: pd.DataFrame, as_of: str) -> float | None:
    try:
        rec_day = pd.to_datetime(as_of).normalize()
    except Exception:
        return None
    future = df[df["date"] > rec_day].copy()
    if len(future) < 2:
        return None
    try:
        buy_close = float(future.iloc[0]["close"])
        sell_close = float(future.iloc[1]["close"])
        if buy_close <= 0:
            return None
        return sell_close / buy_close - 1.0
    except Exception:
        return None


def compute_tail_strategy_weights(
    *,
    recent_limit: int = 60,
    min_samples: int = 10,
) -> Dict[str, Any]:
    artifacts = _load_artifacts()
    if not artifacts:
        return {"status": "unavailable", "reason": "no_recommend_artifacts", "weights": {}}
    query_params = _query_by_symbol()
    if not query_params:
        return {"status": "unavailable", "reason": "no_daily_history", "weights": {}}

    bars_cache: Dict[str, pd.DataFrame] = {}
    samples: Dict[str, List[float]] = defaultdict(list)
    for artifact in artifacts:
        as_of = str(artifact.get("as_of") or "").strip()
        items = artifact.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            strategy = str(item.get("strategy") or "").strip()
            symbol = str(item.get("symbol") or "").strip()
            if not strategy or not symbol or len(samples[strategy]) >= recent_limit:
                continue
            df = _bars_for_symbol(symbol, query_params, bars_cache)
            if df is None:
                continue
            ret = _tail_return(df, as_of)
            if ret is not None:
                samples[strategy].append(float(ret))

    weights: Dict[str, Any] = {}
    for strategy, values in samples.items():
        n = len(values)
        if n < min_samples:
            weights[strategy] = {
                "weight": 1.0,
                "sample_count": n,
                "win_rate": None,
                "avg_return": None,
                "status": "insufficient_samples",
            }
            continue
        win_rate = sum(1 for value in values if value > 0.0) / max(1, n)
        avg_return = sum(values) / max(1, n)
        weights[strategy] = {
            "weight": strategy_weight_from_samples(win_rate, avg_return),
            "sample_count": n,
            "win_rate": float(win_rate),
            "avg_return": float(avg_return),
            "status": "available",
        }
    return {"status": "available", "reason": None, "weights": weights}


def load_tail_strategy_weights(*, ttl_sec: int = 600) -> Dict[str, Any]:
    now = time.time()
    if _CACHE.get("result") is not None and (now - float(_CACHE.get("ts") or 0.0)) <= max(1, ttl_sec):
        return dict(_CACHE["result"])
    result = compute_tail_strategy_weights()
    _CACHE.update({"ts": now, "result": result})
    return dict(result)


def weight_map(result: Dict[str, Any], strategies: Iterable[str] | None = None) -> Dict[str, float]:
    raw = result.get("weights") if isinstance(result, dict) else {}
    out: Dict[str, float] = {}
    for sid, value in (raw or {}).items():
        try:
            out[str(sid)] = float((value or {}).get("weight", 1.0))
        except Exception:
            out[str(sid)] = 1.0
    if strategies:
        for sid in strategies:
            out.setdefault(str(sid), 1.0)
    return out
