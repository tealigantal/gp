from __future__ import annotations

from typing import Any, List, Dict, Optional
from dataclasses import dataclass, field
import pandas as pd

from ..core.types import ToolResult
from ..core.config import load_config
from ..providers.factory import get_provider
from .market_data import normalize_daily_ohlcv
from .signals import compute_indicators


def run_universe(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    cfg = load_config()
    symbols = cfg.default_universe
    return ToolResult(
        ok=True,
        message=f"候选池 size={len(symbols)}",
        data={"symbols": symbols},
    )


# ---------- Deterministic universe builder ----------
@dataclass
class UniverseEntry:
    symbol: str
    name: str | None = None
    reason_codes: List[str] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UniverseResult:
    kept: List[UniverseEntry]
    watch_only: List[UniverseEntry]
    rejected: List[UniverseEntry]


def _gap_pct(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 0.0
    prev_close = float(df["close"].iloc[-2])
    open_t = float(df["open"].iloc[-1])
    if prev_close == 0:
        return 0.0
    return (open_t - prev_close) / prev_close


def build_universe(provider=None, config=None, as_of_date: Optional[str] = None) -> UniverseResult:  # noqa: ANN401
    cfg = config or load_config()
    p = provider or get_provider()
    symbols = list(getattr(cfg, "default_universe", ["000001", "000002"]))

    kept: List[UniverseEntry] = []
    watch: List[UniverseEntry] = []
    rej: List[UniverseEntry] = []

    as_of = as_of_date
    start = None

    # thresholds
    max_atr_pct = 0.08
    gap_watch_th = 0.02
    liquid_min = 1e7
    near_res_pct = 0.005  # within 0.5% of 20d high (yesterday)

    for sym in symbols:
        entry = UniverseEntry(symbol=sym, name=None, reason_codes=[], facts={})
        try:
            raw = p.get_daily(sym, start=start, end=as_of)
            # ST detection
            is_st = False
            st_method = None
            st_conf = None
            name_val = None
            try:
                if "is_st" in raw.columns:
                    is_st = bool(raw["is_st"].iloc[-1])
                    st_method = "provider"
                    st_conf = "high"
                elif "name" in raw.columns:
                    name_val = str(raw["name"].iloc[-1])
                    if any(t in name_val.upper() for t in ["ST", "*ST", "退", "ST "]):
                        is_st = True
                        st_method = "name_heuristic"
                        st_conf = "medium"
            except Exception:
                pass

            df_norm, meta = normalize_daily_ohlcv(raw)
            feat = compute_indicators(df_norm, None)
        except Exception as e:  # noqa: BLE001
            entry.reason_codes = ["DATA_ERROR"]
            entry.facts = {"error": str(e)}
            rej.append(entry)
            continue

        # Facts
        gap = _gap_pct(df_norm)
        atrp = float(feat["atr_pct"].iloc[-1]) if not feat["atr_pct"].isna().iloc[-1] else 0.0
        amt5 = float(feat["amount_5d_avg"].iloc[-1]) if not feat["amount_5d_avg"].isna().iloc[-1] else 0.0
        high20 = float(df_norm["high"].rolling(20).max().iloc[-2]) if len(df_norm) >= 21 else float("nan")
        close_t = float(df_norm["close"].iloc[-1])
        near_res = False
        if pd.notna(high20) and high20 > 0:
            near_res = (high20 - close_t) / high20 <= near_res_pct

        entry.facts.update({
            "amount_5d_avg": amt5,
            "atr_pct": atrp,
            "gap_pct": gap,
            "near_resistance": near_res,
        })

        # ST handling
        if 'is_st' in locals() and (is_st is True):
            entry.name = name_val
            entry.reason_codes = ["ST"]
            entry.facts.update({
                "st_detect_method": st_method or "unknown",
                "st_detect_confidence": st_conf or "low",
            })
            rej.append(entry)
            continue

        # Liquidity C -> reject (configurable)
        if amt5 <= 0 or pd.isna(amt5):
            entry.reason_codes = ["LOW_LIQ"]
            watch.append(entry)
            continue
        if amt5 < liquid_min:
            entry.reason_codes = ["LOW_LIQ"]
            watch.append(entry)
            continue

        # ATR% > 8 -> reject
        if atrp > max_atr_pct:
            entry.reason_codes = ["ATR_GT_8PCT"]
            rej.append(entry)
            continue

        # Gap > +2% -> watch_only
        if gap > gap_watch_th:
            entry.reason_codes = ["GAP_GT_2PCT"]
            watch.append(entry)
            continue

        # Near resistance -> watch_only
        if near_res:
            entry.reason_codes = ["NEAR_RESISTANCE"]
            watch.append(entry)
            continue

        # Otherwise keep
        entry.reason_codes = ["PASS"]
        kept.append(entry)

    return UniverseResult(kept=kept, watch_only=watch, rejected=rej)
