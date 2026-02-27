"""候选集生成（完整实现）。

基于快照/参数/本地 Universe，拉取日线 -> 计算指标/筹码/风险 ->
给出可观测字段与必要的 veto/flags 信息，供后续策略与 UI 使用。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

import os
import math
import pandas as pd

from ..core.config import load_config
from ..providers.universe_provider import UniverseProvider
from .datahub import MarketDataHub
from ..strategy.indicators import compute_indicators
from ..strategy.chip_model import compute_chip
from ..risk.noise_q import grade_noise


def _liquidity_grade(avg5_amount: float) -> str:
    if avg5_amount >= 2e9:
        return "A"
    if avg5_amount >= 1e9:
        return "B"
    return "C"


def _pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _build_dynamic_universe_symbols(snapshot: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if snapshot is None or len(snapshot) == 0:
        return []
    snap = snapshot.copy()
    code_col = _pick_col(snap, ["code", "symbol", "ts_code", "代码"])  # required
    if not code_col:
        return []
    name_col = _pick_col(snap, ["name"])  # optional
    close_col = _pick_col(snap, ["close", "price"])  # optional
    amount_col = _pick_col(snap, ["amount", "turnover"])  # optional
    industry_col = _pick_col(snap, ["industry"])  # optional
    cols = [c for c in [code_col, name_col, close_col, amount_col, industry_col] if c]
    df = snap[cols].copy()
    # numeric
    for c in [x for x in [close_col, amount_col] if x]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        raw_code = str(r[code_col])
        s = raw_code.strip().lower()
        if "." in s:
            s = s.split(".", 1)[0]
        for p in ("sh", "sz", "bj"):
            if s.startswith(p):
                s = s[len(p):]
        digits = "".join([ch for ch in s if ch.isdigit()])
        code = digits[:6] if len(digits) >= 6 else raw_code
        out.append({
            "code": str(code),
            "name": (str(r[name_col]) if name_col else None),
            "industry": (str(r[industry_col]) if industry_col else None),
            "amount": float(r.get(amount_col, 0.0)) if amount_col else 0.0,
        })
    return out


def generate_candidates(
    symbols: List[str] | None,
    env_grade: str,
    topk: int = 3,
    *,
    snapshot: Optional[pd.DataFrame] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    cfg = load_config()
    # Cost controls (env overrides; keep logic local)
    try:
        dynamic_pool_size = int(getattr(cfg, "dynamic_pool_size", 0) or 0)
    except Exception:
        dynamic_pool_size = 0
    if dynamic_pool_size <= 0:
        try:
            dynamic_pool_size = int(os.getenv("GP_DYNAMIC_POOL_SIZE", "200"))
        except Exception:
            dynamic_pool_size = 200

    try:
        prefetch_lookback_days = int(os.getenv("GP_PREFETCH_LOOKBACK_DAYS", "60"))
    except Exception:
        prefetch_lookback_days = 60
    prefetch_lookback_days = max(0, min(365, int(prefetch_lookback_days)))

    try:
        universe_max = int(os.getenv("GP_UNIVERSE_MAX", "0"))
    except Exception:
        universe_max = 0
    hub = MarketDataHub()

    # 1) 基础股票池
    if symbols:
        base_entries: List[Dict[str, Any]] = [{"code": str(s)} for s in symbols]
        base_reason = "symbols_param"
    elif snapshot is not None:
        base_entries = _build_dynamic_universe_symbols(snapshot)
        base_reason = "dynamic_pool"
        # 对动态池做 TopN 截断（按成交额降序），以避免全市场逐标的重计算
        try:
            topn = max(int(topk) * 5, int(getattr(cfg, "dynamic_pool_size", 200)))
        except Exception:
            topn = max(int(topk) * 5, 200)
        try:
            base_entries.sort(key=lambda e: -float(e.get("amount", 0.0)))
        except Exception:
            pass
        base_entries = base_entries[: topn]
    else:
        uni = UniverseProvider()
        syms = uni.get_symbols()
        base_entries = [{"code": s} for s in syms]
        base_reason = "universe:file"
    pre_clean_len = len(base_entries)
    bad_code_removed = 0
    cleaned: List[Dict[str, Any]] = []
    for e in base_entries:
        s = str(e.get("code", "")).strip()
        if len(s) == 6 and s.isdigit():
            cleaned.append(e)
        else:
            bad_code_removed += 1

    universe_fallback: Dict[str, Any] | None = None
    if snapshot is not None and len(cleaned) == 0:
        uni = UniverseProvider()
        syms = uni.get_symbols()
        cleaned = [{"code": s} for s in syms]
        universe_fallback = {
            "from": "snapshot",
            "to": "universe_file",
            "reason": "snapshot_schema_unusable",
            "snapshot_columns": list(snapshot.columns) if hasattr(snapshot, "columns") else [],
        }

    stats: Dict[str, Any] = {
        "universe_in_count": pre_clean_len,
        "universe_after_filter_count": 0,
        "bars_missing_count": 0,
        "bars_too_short_count": 0,
        "indicator_error_count": 0,
        "skipped_symbols_sample": [],
        "candidates_out_count": 0,
        "daily_attempts_sample": [],
        "universe_removed_counts": {
            "bad_code": int(bad_code_removed),
            "insufficient_liquidity": 0,
            "insufficient_history": 0,
        },
    }
    if universe_fallback is not None:
        stats["universe_fallback"] = universe_fallback
    # Bound universe size early to avoid O(N) network/CPU blow-ups.
    truncated: Dict[str, Any] | None = None
    try:
        if base_reason == "dynamic_pool" and dynamic_pool_size > 0 and len(cleaned) > dynamic_pool_size:
            before = len(cleaned)
            try:
                cleaned.sort(key=lambda e: float(e.get("amount", 0.0) or 0.0), reverse=True)
                cleaned = cleaned[:dynamic_pool_size]
                truncated = {"from": before, "to": len(cleaned), "limit": dynamic_pool_size, "by": "amount_desc"}
            except Exception:
                cleaned = cleaned[:dynamic_pool_size]
                truncated = {"from": before, "to": len(cleaned), "limit": dynamic_pool_size, "by": "slice"}
        if base_reason == "universe:file" and universe_max and universe_max > 0 and len(cleaned) > universe_max:
            before = len(cleaned)
            cleaned = cleaned[:universe_max]
            truncated = {"from": before, "to": len(cleaned), "limit": universe_max, "by": "universe_max"}
    except Exception:
        truncated = None
    if truncated is not None:
        stats["universe_truncated"] = truncated

    # 预取（TTL 控制由 datahub 处理）
    try:
        syms = [str(e.get("code")) for e in cleaned if e.get("code")]
        if syms:
            _ = hub.daily_ohlcv_batch(syms, as_of=None, safety_lookback_days=prefetch_lookback_days)
            try:
                print(f"[预取] 已批量入库日线：{len(syms)} 个标的 lookback_days={prefetch_lookback_days}", flush=True)
            except Exception:
                pass
    except Exception:
        pass

    # 2) 逐标的构建候选
    pool: List[Dict[str, Any]] = []
    veto_reasons: List[Dict[str, Any]] = []

    for entry in cleaned:
        sym = str(entry.get("code"))
        if not sym:
            continue
        try:
            # cache 优先，长度不足时再允许回源补齐
            df, meta = hub.daily_ohlcv(sym, None, min_len=250, prefer_cache_only=True)
            if bool(meta.get("insufficient_history")) or int(meta.get("len", 0) or 0) < 120:
                df, meta = hub.daily_ohlcv(sym, None, min_len=250, prefer_cache_only=False)
        except Exception as e:  # noqa: BLE001
            stats["bars_missing_count"] += 1
            if len(stats["skipped_symbols_sample"]) < 10:
                stats["skipped_symbols_sample"].append(sym)
            try:
                print(f"[跳过] 无法获取日线 {sym} err={type(e).__name__}: {e}", flush=True)
            except Exception:
                pass
            continue

        # 指标与筹码
        indicator_first_fail = False
        try:
            feat = compute_indicators(df)
        except Exception:
            indicator_first_fail = True
            try:
                feat = compute_indicators(df)
            except Exception as e:  # noqa: BLE001
                stats["indicator_error_count"] += 1
                if len(stats["skipped_symbols_sample"]) < 10:
                    stats["skipped_symbols_sample"].append(sym)
                try:
                    print(f"[跳过] 指标失败 {sym} err={type(e).__name__}: {e}", flush=True)
                except Exception:
                    pass
                continue

        # 特征提取
        last = feat.iloc[-1]
        def _safe_float(v: Any) -> float:
            try:
                x = float(v)
                if math.isnan(x) or math.isinf(x):
                    return 0.0
                return x
            except Exception:
                return 0.0

        avg5_amount = _safe_float(feat.get("amount_5d_avg", pd.Series([0.0])).iloc[-1] if "amount_5d_avg" in feat.columns else 0.0)
        atrp = _safe_float(last.get("atr_pct", 0.0))
        gap = _safe_float(last.get("gap_pct", 0.0))
        close = _safe_float(last.get("close", 0.0))
        ma20 = _safe_float(last.get("ma20", 0.0))
        pressure = {"near_ma20": bool(ma20 and abs((close - ma20) / ma20) <= 0.005)}

        # 筹码 + 噪声等级
        chip_res, chip_meta = compute_chip(feat)
        q_grade = grade_noise(feat, env_grade if env_grade in {"A", "B", "C", "D"} else "C")

        # 硬性流动性阈值 veto
        if avg5_amount < cfg.min_avg_amount:
            veto = {"symbol": sym, "reason": "LOW_LIQ_HARD", "amount_5d_avg": avg5_amount}
            veto_reasons.append(veto)
            try:
                stats["universe_removed_counts"]["insufficient_liquidity"] += 1
            except Exception:
                pass
            if bool(meta.get("insufficient_history")):
                stats["bars_too_short_count"] += 1
                try:
                    stats["universe_removed_counts"]["insufficient_history"] += 1
                except Exception:
                    pass
            continue

        # 构造候选
        cand = {
            "symbol": sym,
            "name": entry.get("name"),
            "industry": entry.get("industry"),
            "source_reason": base_reason,
            "liquidity": {"avg5_amount": avg5_amount, "grade": _liquidity_grade(avg5_amount)},
            "atr_pct": atrp,
            "gap_pct": gap,
            "pressure_flags": pressure,
            "q_grade": q_grade,
            "chip": asdict(chip_res),
            "indicators": {
                "ma20": ma20,
                "slope20": _safe_float(feat["slope20"].iloc[-1]) if "slope20" in feat.columns else 0.0,
                "atr_pct": atrp,
                "gap_pct": gap,
            },
            "close": close,
        }

        # 观察/禁止标记
        observe_only = False
        reasons: List[str] = []
        if cand["liquidity"]["grade"] == "C":
            observe_only = True
            reasons.append("LIQ_C_OBSERVE")
        if atrp > 0.08:
            observe_only = True
            reasons.append("ATR_HIGH_OBSERVE")
        if gap > 0.02:
            observe_only = True
            reasons.append("GAP_HIGH_FORBID")
        try:
            if getattr(chip_res, "dist_to_90_high_pct", 1.0) <= 0.02:
                observe_only = True
                reasons.append("NEAR_CHIP90_HIGH_FORBID")
        except Exception:
            pass
        cand["flags"] = {"must_observe_only": bool(observe_only), "reasons": reasons}

        pool.append(cand)

    # 排序与统计
    def _liq_rank(g: str) -> int:
        return {"A": 0, "B": 1, "C": 2}.get(str(g), 3)

    pool.sort(key=lambda x: (-(x["indicators"].get("slope20") or 0.0), x["atr_pct"], _liq_rank(x["liquidity"].get("grade"))))
    stats["universe_after_filter_count"] = len(pool)
    stats["candidates_out_count"] = len(pool)

    return pool[: max(1, topk) * 5], veto_reasons, stats





