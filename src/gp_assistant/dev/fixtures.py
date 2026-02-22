# src/gp_assistant/dev/fixtures.py
"""
开发者模式固定输出（给前端联调用）：

- dev_ohlcv_bars(): 生成确定性的“伪日K”（不走网络、不走 provider、不依赖本地海量数据）。
- dev_recommend_payload(): 生成确定性的“伪推荐结果”。
  - 若 store/recommend/{as_of}.json 已存在，会优先复用（方便你 UI 回放真实结果）。
"""

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
        if d.weekday() < 5:  # Mon-Fri
            out.append(d)
        d -= timedelta(days=1)
    out.reverse()
    return out


def dev_ohlcv_bars(symbol: str, as_of: Optional[str] = None, limit: int = 120) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Deterministic synthetic OHLCV for frontend dev (no network).
    Output matches /api/ohlcv schema.
    """
    cfg = load_config()

    end = _parse_yyyy_mm_dd(as_of)
    n = max(5, min(int(limit), 2000))

    dates = _recent_weekdays(end, n)
    seed = _seed_int(symbol)
    rng = random.Random(seed)

    # base price depends on symbol (stable & distinguishable)
    base = 8.0 + (seed % 900) / 60.0  # ~[8,23]
    price = base

    bars: List[Dict[str, Any]] = []
    for i, d in enumerate(dates):
        drift = 0.0008 * math.sin(i / 9.0)
        shock = rng.gauss(0.0, 0.012)
        ret = drift + shock

        o = price
        c = max(0.5, price * (1.0 + ret))
        wiggle = abs(rng.gauss(0.0, 0.006))
        h = max(o, c) * (1.0 + wiggle)
        l = min(o, c) * (1.0 - wiggle)

        vol = int(max(800_000, abs(rng.gauss(10_000_000, 2_800_000))))
        amount = ((h + l + c) / 3.0) * float(vol)

        bars.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "open": round(o, 3),
                "high": round(h, 3),
                "low": round(l, 3),
                "close": round(c, 3),
                "volume": float(vol),
                "amount": float(int(amount)),
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


def _q_grade_from_seed(seed: int) -> str:
    # more Q1/Q2, rarely Q3
    r = seed % 10
    if r <= 6:
        return "Q1"
    if r <= 9:
        return "Q2"
    return "Q3"


def dev_recommend_payload(
    date: Optional[str] = None,
    topk: int = 3,
    universe: str = "auto",
    symbols: Optional[List[str]] = None,
    risk_profile: str = "normal",
) -> Dict[str, Any]:
    """
    Frontend-friendly payload:
    - Prefer reading existing store/recommend/{as_of}.json if present (good for UI replay).
    - Otherwise return a deterministic synthetic recommendation payload.
    """
    cfg = load_config()
    as_of = date or dt_date.today().strftime("%Y-%m-%d")

    # 1) if you already have a saved result, reuse it
    saved = _try_load_saved_recommend(as_of)
    if isinstance(saved, dict):
        saved.setdefault("message", "DEV_MODE: loaded from store/recommend")
        saved.setdefault("debug", {})
        if isinstance(saved["debug"], dict):
            saved["debug"]["mode"] = "dev"
            saved["debug"]["dev_source"] = "store/recommend"
        return saved

    # 2) otherwise build deterministic payload
    use_syms = symbols or cfg.dev_symbols or ["000001", "000333", "600519"]
    topk = max(1, min(int(topk or 3), 10))
    pick_syms = use_syms[:topk]

    themes = [
        {"name": "DEV-主线-示例", "strength": "—", "evidence": ["固定输出，用于前端联调"]},
        {"name": "DEV-分支-示例", "strength": "—", "evidence": ["你可以后续替换成真实主线识别"]},
    ]

    env = {
        "grade": "B",
        "reasons": ["DEV_MODE 固定环境（不依赖外网/不跑重计算）"],
        "recovery_conditions": [],
        "raw": {"breadth": {"mean_chg": 0.35, "up_ratio": 0.56}, "liquidity": {"total_amount": 9.8e11}},
    }

    candidate_pool = [{"symbol": s, "source_reason": "DEV 固定候选池"} for s in pick_syms]

    picks: List[Dict[str, Any]] = []
    for idx, s in enumerate(pick_syms):
        seed = _seed_int(s)
        rng = random.Random(seed)

        avg_cost = 10.0 + (seed % 240) / 20.0  # ~[10,22]
        band_low = round(avg_cost * (0.95 - (seed % 5) * 0.002), 3)
        band_high = round(avg_cost * (1.06 + (seed % 7) * 0.002), 3)

        q_grade = _q_grade_from_seed(seed)
        atr_pct = round(0.018 + (seed % 11) * 0.002, 4)  # 1.8% ~ 4.0%
        gap_pct = round(((seed % 9) - 4) * 0.003, 4)  # -1.2% ~ +1.2%
        slope20 = round(((seed % 13) - 6) * 0.004, 4)  # negative/positive

        win_rate_5 = round(0.42 + (seed % 35) / 100.0, 2)  # 0.42~0.77
        sample_k = int(40 + (seed % 90))

        score = float(78 + (seed % 20))  # 78~97

        picks.append(
            {
                "symbol": s,
                "name": f"DEV-{s}",
                "theme": "DEV-示例主题",
                "score": score,
                "q_grade": q_grade,
                "chip": {
                    "avg_cost": round(avg_cost, 3),
                    "band_90_low": band_low,
                    "band_90_high": band_high,
                    "dist_to_90_high_pct": round(max(0.0, (band_high - avg_cost) / max(avg_cost, 1e-6)), 4),
                    "model_used": "dev_static",
                    "confidence": "medium",
                },
                "indicators": {
                    "ma20": round(avg_cost * (0.995 + idx * 0.001), 3),
                    "slope20": slope20,
                    "atr_pct": atr_pct,
                    "gap_pct": gap_pct,
                },
                "announcement_risk": {"risk_level": "low", "notes": []},
                "event_risk": {"event_risk": "low", "notes": []},
                "stats": {"win_rate_5": win_rate_5, "k": sample_k},
                "champion": {"strategy": "dev_static", "score": score},
                "trade_plan": {
                    "bands": {
                        "S1": band_low,
                        "S2": round(avg_cost, 3),
                        "R1": band_high,
                        "R2": round(band_high * 1.02, 3),
                    },
                    "actions": {
                        "window_A": "A窗：回踩承接确认后分批（不追价）",
                        "window_B": "B窗：收盘结构确认再做（不满足就放弃）",
                    },
                    "invalidation": ["收盘有效跌破 S1", "放量不涨/冲高回落反复"],
                    "risk": {"stop_loss": "跌破S1", "time_stop": "2-3日不强必走", "no_averaging_down": True},
                },
            }
        )

    payload: Dict[str, Any] = {
        "as_of": as_of,
        "timezone": cfg.timezone,
        "env": env,
        "themes": themes,
        "candidate_pool": candidate_pool,
        "picks": picks,
        "execution_checklist": ["1) 环境分层", "2) 主线限制", "3) 关键带与两窗执行"],
        "disclaimer": "DEV_MODE: 前端联调用固定输出（非真实数据链路）",
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