"""Candidate generation (UTF-8 normalized) with diagnostics.

This module builds a candidate pool either from a dynamic snapshot universe or
from a pre-built Universe list. It preserves existing filtering/ordering logic
and adds a minimal diagnostics stats dict returned alongside results.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

import pandas as pd

from .datahub import MarketDataHub
from ..strategy.indicators import compute_indicators
from ..strategy.chip_model import compute_chip
from ..risk.noise_q import grade_noise
from ..core.config import load_config
from ..providers.factory import get_provider


def _build_dynamic_universe_symbols(snapshot: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:
    """Build dynamic universe using spot snapshot with basic filters.

    Filters (configurable via AppConfig):
    - Exclude ST/*ST/退
    - Price in [price_min, price_max]
    - Exclude newly listed within new_stock_days (if list_date available)
    - Select top N by amount (dynamic_pool_size)
    """
    if snapshot is None:
        raise RuntimeError("_build_dynamic_universe_symbols requires snapshot")
    cfg = load_config()
    snap = snapshot
    # Resolve column names (support Chinese/English variants)
    code_col = "代码" if "代码" in snap.columns else ("code" if "code" in snap.columns else None)
    name_col = "名称" if "名称" in snap.columns else ("name" if "name" in snap.columns else None)
    price_col = None
    for c in ("最新价", "现价", "最新", "close", "收盘"):
        if c in snap.columns:
            price_col = c
            break
    amount_col = "成交额" if "成交额" in snap.columns else ("amount" if "amount" in snap.columns else None)
    list_date_col = None
    for c in ("上市时间", "上市日期", "list_date"):
        if c in snap.columns:
            list_date_col = c
            break
    if not code_col or not price_col or not amount_col:
        raise RuntimeError("snapshot missing required columns: code/price/amount")

    df = snap.copy()
    keep_cols = [code_col, name_col, price_col, amount_col] + ([list_date_col] if list_date_col else [])
    if "行业" in snap.columns and "行业" not in keep_cols:
        keep_cols.append("行业")
    if "概念" in snap.columns and "概念" not in keep_cols:
        keep_cols.append("概念")
    df = df[keep_cols].rename(columns={code_col: "code", name_col or "N": "name", price_col: "price", amount_col: "amount", **({list_date_col: "list_date"} if list_date_col else {})})
    # Basic filters
    if "name" in df.columns:
        mask_ok = ~df["name"].astype(str).str.upper().str.contains("ST|\*ST|退")
        df = df[mask_ok]
    df = df[(df["price"] >= cfg.price_min) & (df["price"] <= cfg.price_max)]
    if "list_date" in df.columns:
        try:
            d = pd.to_datetime(df["list_date"], errors="coerce")
            days = (pd.Timestamp.today().normalize() - d).dt.days
            df = df[days >= cfg.new_stock_days]
        except Exception:
            pass
    df = df.sort_values("amount", ascending=False).head(cfg.dynamic_pool_size)

    # Mainline restriction (industry preferred)
    if cfg.restrict_to_mainline:
        if "行业" in df.columns and df["行业"].notna().any():
            tmp = df.copy()
            g = tmp.groupby("行业").agg(sum_amt=("amount", "sum"), count=("code", "count")).reset_index()
            g = g.sort_values("sum_amt", ascending=False).head(max(1, cfg.mainline_top_n))
            top_groups = set(g["行业"].astype(str).tolist())
            df = df[df["行业"].astype(str).isin(top_groups)]
        else:
            # concept route best-effort (leave as-is if unavailable)
            try:
                import akshare as ak  # type: ignore
                cons_name = ak.stock_board_concept_name_ths()  # type: ignore[attr-defined]
                if cons_name is not None and len(cons_name) > 0:
                    rank_col = None
                    for c in ("涨跌幅", "涨跌幅(%)", "涨跌", "changePct"):
                        if c in cons_name.columns:
                            rank_col = c
                            break
                    if rank_col is not None:
                        cn = cons_name.copy()
                        try:
                            cn["_r"] = pd.to_numeric(cn[rank_col].astype(str).str.rstrip("% "), errors="coerce")
                        except Exception:
                            cn["_r"] = pd.to_numeric(cn[rank_col], errors="coerce")
                        cn = cn.sort_values("_r", ascending=False).head(max(1, cfg.mainline_top_n))
                        name_col = "板块名称" if "板块名称" in cn.columns else cn.columns[0]
                        top_concepts = [str(x) for x in cn[name_col].tolist()]
                        keep_codes: set[str] = set()
                        for name in top_concepts:
                            try:
                                dfc = ak.stock_board_concept_cons_em(symbol=name)  # type: ignore[attr-defined]
                                code_c = None
                                for c in ("代码", "股票代码", "code"):
                                    if c in dfc.columns:
                                        code_c = c
                                        break
                                if code_c:
                                    keep_codes.update(dfc[code_c].astype(str).tolist())
                            except Exception:
                                continue
                        if keep_codes:
                            df = df[df["code"].astype(str).isin(keep_codes)]
            except Exception:
                pass
    # Return entries with optional labels
    out: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        out.append({
            "code": str(r["code"]),
            "industry": (str(r["行业"]) if "行业" in df.columns and pd.notna(r.get("行业")) else None),
            "amount": float(r.get("amount", 0.0)),
            "name": str(r.get("name")) if "name" in df.columns else None,
        })
    return out


def _liquidity_grade(avg5_amount: float) -> str:
    if avg5_amount >= 2e9:
        return "A"
    if avg5_amount >= 1e9:
        return "B"
    return "C"


def generate_candidates(symbols: List[str] | None, env_grade: str, topk: int = 3, *, snapshot: Optional[pd.DataFrame] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    cfg = load_config()
    hub = MarketDataHub()
    pool: List[Dict[str, Any]] = []
    veto_reasons: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {
        "universe_in_count": 0,
        "universe_after_filter_count": 0,
        "bars_missing_count": 0,
        "bars_too_short_count": 0,
        "indicator_error_count": 0,
        "skipped_symbols_sample": [],
        "candidates_out_count": 0,
    }
    # Build base symbols
    if symbols:
        base_entries = ([{"code": s} for s in symbols])
    else:
        if snapshot is not None:
            base_entries = _build_dynamic_universe_symbols(snapshot)
        else:
            from ..providers.universe_provider import UniverseProvider
            uni = UniverseProvider()
            syms = uni.get_symbols()
            base_entries = ([{"code": s} for s in syms])
            # enrich stats with universe meta when available
            try:
                um = uni.last_meta()
                stats["universe_raw_count"] = int(um.get("raw_count", 0))
                stats["universe_cleaned_count"] = int(um.get("cleaned_count", len(syms)))
                stats["universe_removed_counts"] = um.get("removed_counts", {})
            except Exception:
                pass
    stats["universe_in_count"] = len(base_entries)
    stats["universe_after_filter_count"] = len(base_entries)

    for entry in base_entries:
        sym = entry.get("code")
        try:
            df, meta = hub.daily_ohlcv(sym, None, min_len=250)
        except Exception:
            stats["bars_missing_count"] += 1
            if len(stats["skipped_symbols_sample"]) < 10:
                stats["skipped_symbols_sample"].append(sym)
            continue
        try:
            if bool(meta.get("insufficient_history")):
                stats["bars_too_short_count"] += 1
        except Exception:
            pass
        try:
            feat = compute_indicators(df)
        except Exception:
            stats["indicator_error_count"] += 1
            try:
                feat = compute_indicators(df)
            except Exception:
                if len(stats["skipped_symbols_sample"]) < 10:
                    stats["skipped_symbols_sample"].append(sym)
                continue
        # facts
        last = feat.iloc[-1]
        avg5_amount = float(feat["amount_5d_avg"].iloc[-1]) if "amount_5d_avg" in feat.columns and not pd.isna(feat["amount_5d_avg"].iloc[-1]) else 0.0
        atrp = float(last.get("atr_pct", 0.0)) if not pd.isna(last.get("atr_pct", 0.0)) else 0.0
        gap = float(last.get("gap_pct", 0.0)) if not pd.isna(last.get("gap_pct", 0.0)) else 0.0
        close = float(last.get("close", 0.0)) if not pd.isna(last.get("close", 0.0)) else 0.0
        ma20 = float(last.get("ma20", 0.0)) if not pd.isna(last.get("ma20", 0.0)) else 0.0
        pressure = {"near_ma20": bool(ma20 and abs((close - ma20) / ma20) <= 0.005)}
        chip, chip_meta = compute_chip(feat)
        q_grade = grade_noise(feat, env_grade)

        cand = {
            "symbol": sym,
            "name": entry.get("name"),
            "industry": entry.get("industry"),
            "source_reason": "默认候选池",
            "liquidity": {"avg5_amount": avg5_amount, "grade": _liquidity_grade(avg5_amount)},
            "atr_pct": atrp,
            "gap_pct": gap,
            "pressure_flags": pressure,
            "q_grade": q_grade,
            "chip": chip.__dict__,
            "indicators": {
                "ma20": ma20,
                "slope20": float(feat["slope20"].iloc[-1]) if "slope20" in feat.columns else 0.0,
                "atr_pct": atrp,
                "gap_pct": gap,
            },
            "close": close,
        }
        observe_only = False
        reasons: List[str] = []
        if avg5_amount < cfg.min_avg_amount:
            veto_reasons.append({"symbol": sym, "reason": "LOW_LIQ_HARD", "amount_5d_avg": avg5_amount})
            continue
        if cand["liquidity"]["grade"] == "C":
            observe_only = True
            reasons.append("LIQ_C_OBSERVE")
        if atrp > 0.08:
            observe_only = True
            reasons.append("ATR_HIGH_OBSERVE")
        if gap > 0.02:
            observe_only = True
            reasons.append("GAP_HIGH_FORBID")
        if getattr(chip, "dist_to_90_high_pct", 1.0) <= 0.02:
            observe_only = True
            reasons.append("NEAR_CHIP90_HIGH_FORBID")
        cand["flags"] = {"must_observe_only": bool(observe_only), "reasons": reasons}
        pool.append(cand)

    pool.sort(key=lambda x: (-(x["indicators"].get("slope20") or 0.0), x["atr_pct"], x["liquidity"]["grade"]))
    stats["candidates_out_count"] = len(pool)
    return pool, veto_reasons, stats


