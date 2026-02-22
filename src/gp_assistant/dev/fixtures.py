# src/gp_assistant/dev/fixtures.py
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import date as dt_date
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import load_config
from ..core.paths import store_dir


def _seed_int(symbol: str) -> int:
    h = hashlib.md5(symbol.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _parse_yyyy_mm_dd(s: Optional[str]) -> dt_date:
    if not s:
        return dt_date.today()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return dt_date.today()


def _recent_weekdays(end: dt_date, n: int) -> List[dt_date]:
    out: List[dt_date] = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    out.reverse()
    return out


def dev_ohlcv_bars(symbol: str, as_of: Optional[str] = None, limit: int = 120) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Deterministic synthetic OHLCV for frontend dev (no network).
    """
    cfg = load_config()
    end = _parse_yyyy_mm_dd(as_of) if as_of else _parse_yyyy_mm_dd(None)

    n = max(5, min(int(limit), 2000))
    dates = _recent_weekdays(end, n)

    seed = _seed_int(symbol)
    rng = random.Random(seed)

    # base price depends on symbol to keep it stable & distinguishable
    base = 8.0 + (seed % 500) / 50.0  # ~[8,18]
    price = base

    bars: List[Dict[str, Any]] = []
    for i, d in enumerate(dates):
        # small deterministic drift + noise
        drift = 0.0008 * math.sin(i / 9.0)
        shock = rng.gauss(0.0, 0.012)
        ret = drift + shock

        o = price
        c = max(0.5, price * (1.0 + ret))
        wiggle = abs(rng.gauss(0.0, 0.006))
        h = max(o, c) * (1.0 + wiggle)
        l = min(o, c) * (1.0 - wiggle)

        vol = int(max(1_000_000, abs(rng.gauss(12_000_000, 3_000_000))))
        amount = ((h + l + c) / 3.0) * float(vol)

        bars.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "open": round(o, 3),
                "high": round(h, 3),
                "low": round(l, 3),
                "close": round(c, 3),
                "volume": vol,
                "amount": int(amount),
            }
        )
        price = c

    meta = {
        "source": "dev_fixture",
        "timezone": cfg.timezone,
        "symbol": symbol,
        "len": len(bars),
        "as_of": end.strftime("%Y-%m-%d"),
    }
    return bars, meta


def _try_load_saved_recommend(as_of: str) -> Optional[Dict[str, Any]]:
    p = store_dir() / "recommend" / f"{as_of}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def dev_recommend_payload(
    date: Optional[str] = None,
    topk: int = 3,
    universe: str = "auto",
    symbols: Optional[List[str]] = None,
    risk_profile: str = "normal",
) -> Dict[str, Any]:
    """
    Fixed, frontend-friendly payload:
    - Prefer reading existing store/recommend/<date>.json if present (nice for UI replay).
    - Otherwise return a deterministic synthetic recommendation payload.
    """
    cfg = load_config()

    as_of = date or dt_date.today().strftime("%Y-%m-%d")

    # 1) if you already have a saved result, reuse it
    saved = _try_load_saved_recommend(as_of)
    if isinstance(saved, dict):
        saved.setdefault("message", "DEV_MODE: loaded from store/recommend")
        saved.setdefault("debug", {})
        saved["debug"]["mode"] = "dev"
        saved["debug"]["dev_source"] = "store/recommend"
        return saved

    # 2) else return a static-ish sample payload
    use_syms = symbols or cfg.dev_symbols
    if not use_syms:
        use_syms = ["000001", "000333", "600519"]

    topk = max(1, min(int(topk or 3), 10))
    picks_syms = use_syms[:topk]

    themes = [
        {"name": "DEV-主线-示例", "strength": "—", "evidence": ["固定输出，用于前端联调"]},
    ]
    env = {
        "grade": "B",
        "reasons": ["DEV_MODE 固定环境"],
        "recovery_conditions": [],
        "raw": {"breadth": {"mean_chg": 0.35, "up_ratio": 0.56}},
    }

    picks: List[Dict[str, Any]] = []
    for s in picks_syms:
        seed = _seed_int(s)
        # deterministic chip/indicator numbers
        avg_cost = 10.0 + (seed % 200) / 20.0
        band_low = round(avg_cost * 0.96, 3)
        band_high = round(avg_cost * 1.06, 3)

        picks.append(
            {
                "symbol": s,
                "theme": "DEV-示例主题",
                "flags": {"must_observe_only": False, "reasons": []},
                "chip": {
                    "avg_cost": round(avg_cost, 3),
                    "band_90_low": band_low,
                    "band_90_high": band_high,
                    "dist_to_90_high_pct": 0.04,
                },
                "indicators": {
                    "ma20": round(avg_cost * 0.995, 3),
                    "slope20": 0.02,
                    "atr_pct": 0.03,
                    "gap_pct": 0.0,
                },
                "champion": {"strategy": "dev_static", "score": 88},
                "trade_plan": {
                    "bands": {"S1": band_low, "S2": round(avg_cost, 3), "R1": band_high, "R2": round(band_high * 1.02, 3)},
                    "actions": {
                        "window_A": "A窗：回踩承接确认后分批",
                        "window_B": "B窗：收盘确认，不追价",
                    },
                    "invalidation": ["收盘有效跌破 S1"],
                    "risk": {"stop_loss": "跌破S1", "time_stop": "2-3日不强必走", "no_averaging_down": True},
                },
            }
        )

    payload: Dict[str, Any] = {
        "as_of": as_of,
        "timezone": cfg.timezone,
        "env": env,
        "themes": themes,
        "candidate_pool": [{"symbol": s, "source_reason": "DEV 固定候选"} for s in picks_syms],
        "picks": picks,
        "execution_checklist": ["1) 环境分层", "2) 主线限制", "3) 策略冠军与关键带"],
        "disclaimer": "DEV_MODE: 前端联调用固定输出",
        "tradeable": False,
        "message": "DEV_MODE: static payload (no network, no heavy compute)",
        "debug": {
            "mode": "dev",
            "dev_source": "generated",
            "risk_profile": risk_profile,
            "universe": universe,
        },
    }
    return payload