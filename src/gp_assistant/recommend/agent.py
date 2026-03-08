"""Recommendation engine (UTF-8 normalized, minimal reconstruction).

This module orchestrates the end-to-end recommendation flow:
 - Fetch snapshot once via provider (agent is the only caller)
 - Build environment and themes using the shared snapshot (or degrade when None)
 - Build candidate pool via candidate_gen (with diagnostics stats)
 - Compute minimal pick fields and write outputs
 - Centralize degradation reasons and hard tradeable decision
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pandas as pd

from ..core.config import load_config
from ..core.logging import logger
from ..observe.degrade import record as degrade_record
from ..observe.degrade import warn_once
from ..core.paths import store_dir
from .calendar import calendar_summary
from .datahub import MarketDataHub
from .market_env import score_regime
from .theme_pool import build_themes
from .theme_hints import build_mover_hints
from .strict_output import normalize_payload
from .theme_concept import last_concept_status
from .mainline import build_mainline
from ..core.strict import is_strict
from .candidate_gen import generate_candidates
from ..providers.boards import is_mainboard
from ..providers.factory import get_provider

# ---- Execution semantics thresholds (centralized constants) ----
# Gap thresholds between last_close and S1 for execution state decisions
EXEC_ACTIONABLE_MAX_GAP_PCT = 0.03  # within 3% around entry area is actionable candidate
EXEC_WAITING_MAX_GAP_PCT = 0.08     # within 8% considered waiting for pullback
# If signed gap is below this tolerance, price is considered below support
EXEC_BELOW_SUPPORT_TOL_PCT = -0.005
# Minimal reward/risk to consider actionable; missing/invalid RR cannot be actionable
MIN_RR_FOR_ACTIONABLE = 0.3
# Rerank penalties by execution state (applied in final score)
RERANK_STATE_PENALTY = {
    "actionable": 0.0,
    "waiting_pullback": -0.3,
    "observe_only": -0.8,
    "below_support": -1.0,
    "breakdown_risk": -1.0,
}
# Large divergence ratio to explain structural vs execution bands recentering
BAND_DIVERGENCE_EXPLAIN_THRESH = 0.25

# Strategy evaluation imports (full integration)
from ..strategy import library as strat_lib  # type: ignore
from ..strategy.ts_cv import purged_walk_forward  # type: ignore
from ..strategy.champion import choose_champion  # type: ignore
from ..strategy.indicators import compute_indicators  # type: ignore


def _write_outputs(as_of: str, payload: Dict[str, Any]) -> None:
    out_dir = store_dir() / "recommend"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{as_of}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{as_of}_debug.json").write_text(json.dumps(payload.get("debug", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{as_of}_sources.json").write_text(json.dumps(payload.get("debug", {}).get("sources", []), ensure_ascii=False, indent=2), encoding="utf-8")


def run(date: Optional[str] = None, topk: int = 3, universe: str = "auto", symbols: Optional[List[str]] = None, risk_profile: str = "normal") -> Dict[str, Any]:  # noqa: D401
    cfg = load_config()
    cal = calendar_summary()
    as_of = date or cal["as_of"]
    hub = MarketDataHub()

    # Fast path: when caller provides concrete symbols, skip expensive snapshot/thematic computations.
    symbols_mode = (str(universe or "").strip().lower() == "symbols" and bool(symbols))

    # 数据阶段：快照（Spot Snapshot）
    # Fetch snapshot once and share within this run (degrade to None if unavailable)
    snapshot_df: Optional[pd.DataFrame]
    snap_meta: Dict[str, Any]

    if symbols_mode:
        snapshot_df = None
        snap_meta = {
            "missing": True,
            "degrade": "symbols_mode_skip_snapshot",
            "error": None,
            "source": None,
            "cache": None,
            "fallback": False,
            "stale": False,
            "elapsed_sec": 0.0,
            "skipped_routes": [],
            "attempts": [],
        }
        try:
            print(f"[数据] 阶段=快照（spot）", flush=True)
            print(f"[快照] symbols 模式：跳过市场快照抓取（仅基于传入 symbols）", flush=True)
            print(f"[数据] 下一阶段=日线K（逐标的）", flush=True)
            print(f"[数据] 分钟线=未调用（当前版本候选与策略基于日线）", flush=True)
        except Exception:
            pass
    else:
        provider = get_provider()
        # 可观测性：打印快照抓取配置与结果
        try:
            routes = list(getattr(cfg, "ak_spot_priority", ["sina", "em"]))
        except Exception:
            routes = ["sina", "em"]
        try:
            to_sec = getattr(provider, "timeout_sec", getattr(cfg, "request_timeout_sec", None))
        except Exception:
            to_sec = getattr(cfg, "request_timeout_sec", None)
        try:
            print(f"[数据] 阶段=快照（spot）", flush=True)
            print(f"[快照] 正在获取市场快照：provider={getattr(provider, 'name', '?')}，优先级={','.join(routes)}，超时={to_sec}s", flush=True)
        except Exception:
            pass
        try:
            snapshot_df = provider.get_spot_snapshot()
            snap_meta = getattr(provider, "last_snapshot_meta", lambda: {})() or {}
            try:
                src = (snap_meta.get("source") or snap_meta.get("cache_of") or "?")
                rows = (0 if snapshot_df is None else int(len(snapshot_df)))
                elapsed = snap_meta.get("elapsed_sec", "?")
                cache = snap_meta.get("cache", None) or "none"
                print(f"[快照] 成功：source={src}，rows={rows}，elapsed={elapsed}s，cache={cache}", flush=True)
                print(f"[数据] 下一阶段=日线K（逐标的）", flush=True)
                print(f"[数据] 分钟线=未调用（当前版本候选与策略基于日线）", flush=True)
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            snapshot_df = None
            snap_meta = {"missing": True, "degrade": "no_snapshot_universe_mode", "error": str(e)}
            try:
                print(f"[快照] 失败：{e}，降级为无快照模式（将使用 universe/symbols 模式）", flush=True)
            except Exception:
                pass

    # Environ + themes
    if symbols_mode:
        env = {"grade": "C", "degrade": "symbols_mode", "missing": ["snapshot_skipped"]}
        themes = []
        mainline = {"indicator": "今日", "sectors": [], "errors": ["skipped_symbols_mode"]}
    else:
        env = score_regime(hub, snapshot=snapshot_df)
        themes = build_themes(hub, snapshot=snapshot_df)
        # Mainline （资金流主线）
        try:
            mainline = build_mainline(indicator="今日", topn=max(1, int(getattr(cfg, "mainline_top_n", 2))), snapshot=snapshot_df)
        except Exception as _e:
            mainline = {"indicator": "今日", "sectors": [], "errors": ["build_mainline_failed"]}

    # Base selection
    if universe == "symbols" and symbols:
        base = symbols
        universe_syms = symbols
        universe_meta = {"source": "symbols:param", "count_unique": len(set(symbols))}
    else:
        base = None  # candidate_gen decides based on snapshot
        universe_syms = None
        universe_meta = None

    # Candidates with stats
    pool, veto, cand_stats = generate_candidates(base, env.get("grade", "C"), topk=topk, snapshot=snapshot_df)

    # Thematic overlap scoring and optional restriction to mainline/themes
    def _compute_thematic_overlap(cand: Dict[str, Any]) -> Dict[str, Any]:
        ind = str(cand.get("industry") or "").strip()
        theme_names = [str(t.get("name")) for t in (themes or []) if isinstance(t, dict)]
        mainline_names = [str(s.get("name")) for s in (mainline.get("sectors") or []) if isinstance(s, dict)] if isinstance(mainline, dict) else []
        tscore = 0.0
        mscore = 0.0
        treasons: List[str] = []
        # Theme overlap: strict equals for industry themes; loose contains as fallback
        if ind:
            if any(ind == tn for tn in theme_names):
                tscore = 1.0
                treasons.append("industry_theme_match")
            elif any(ind in tn or tn in ind for tn in theme_names):
                tscore = 0.5
                treasons.append("industry_theme_partial")
        # Mainline overlap: loose match with sector names
        if ind:
            if any(ind == mn for mn in mainline_names):
                mscore = 1.0
            elif any(ind in mn or mn in ind for mn in mainline_names):
                mscore = 0.6
        return {"theme_overlap_score": float(tscore), "mainline_overlap_score": float(mscore), "reasons": treasons}

    themed_pool: List[Dict[str, Any]] = []
    thematic_none_count = 0
    for cand in pool:
        th = _compute_thematic_overlap(cand)
        cand.update({
            "theme_overlap_score": th["theme_overlap_score"],
            "mainline_overlap_score": th["mainline_overlap_score"],
            "thematic_reasons": th.get("reasons", []),
        })
        if (cand.get("theme_overlap_score", 0.0) or cand.get("mainline_overlap_score", 0.0)):
            themed_pool.append(cand)
        else:
            thematic_none_count += 1

    restrict_mainline = bool(getattr(cfg, "restrict_to_mainline", False))
    if restrict_mainline:
        # Filter pool if unrelated to themes/mainline
        pool = themed_pool
        if not pool:
            # keep empty pool; surface debug later
            pass

    # Strategy evaluation helpers
    def _eval_strategies_for_symbol(sym: str, df_feat: pd.DataFrame, q_grade: Optional[str]) -> Dict[str, Any]:
        """Evaluate all registered strategies for the symbol.

        Returns mapping {strategy_id: {cv: dict, event: dict}}
        """
        out: Dict[str, Any] = {}
        # CV baseline (no leakage)
        try:
            cv = purged_walk_forward(df_feat)
            cv_dict = getattr(cv, "__dict__", {})
        except Exception:
            cv_dict = {"k": 0, "win_rate_5d_mean": 0.0, "win_rate_5d_std": 0.0, "mean_return_5d_mean": 0.0, "mean_return_5d_std": 0.0, "drawdown_proxy_mean": 0.0}
        # Iterate all registered strategies
        for sid, mod in (strat_lib.REGISTRY or {}).items():
            # detect setups (best effort)
            try:
                detect = getattr(mod, "detect_setups", None)
                setups = detect(df_feat) if callable(detect) else []
            except Exception:
                setups = []
            # event study (best effort)
            ev_dict: Dict[str, Any] = {}
            try:
                ev = getattr(mod, "event_study", None)
                if callable(ev):
                    ev_stats = ev(df_feat, setups)
                    ev_dict = getattr(ev_stats, "__dict__", {})
            except Exception:
                ev_dict = {}
            # basic setup summary for freshness
            try:
                setup_idx = int(getattr(setups[-1], "idx", len(df_feat) - 1)) if setups else (len(df_feat) - 1)
            except Exception:
                setup_idx = len(df_feat) - 1
            setup_age = max(0, (len(df_feat) - 1) - setup_idx)
            out[str(sid)] = {"cv": cv_dict, "event": ev_dict, "setup": {"last_idx": setup_idx, "age": setup_age, "count": len(setups)}}
        return out

    def _trade_plan_from_strategy(mod: Any, df_feat: pd.DataFrame, pick: Dict[str, Any], q_grade: Optional[str]) -> Dict[str, Any]:
        bands: Dict[str, float] = {}
        structural_bands: Dict[str, float] = {}
        actions: Dict[str, str] = {}
        invalid: List[str] = []
        # latest setup if available
        try:
            detect = getattr(mod, "detect_setups", None)
            setups = detect(df_feat) if callable(detect) else []
            setup = setups[-1] if setups else None
        except Exception:
            setup = None
        # bands
        band_source = None
        structural_band_source = None
        execution_band_source = None
        try:
            kb = getattr(mod, "key_bands", None)
            if callable(kb) and setup is not None:
                bands = kb(df_feat, setup) or {}
                if bands:
                    band_source = "strategy_key_bands"
        except Exception:
            bands = {}
        if bands:
            structural_bands = dict(bands)
            structural_band_source = band_source or "strategy_key_bands"
        if not bands:
            chip = pick.get("chip", {}) or {}
            try:
                low = float(chip.get("band_90_low", 0.0))
                high = float(chip.get("band_90_high", 0.0))
                mid = float(chip.get("avg_cost", 0.0)) or ((low + high) / 2.0 if (low and high) else 0.0)
                bands = {"S1": low, "S2": mid, "R1": high, "R2": (high * 1.02 if high else 0.0)}
                band_source = "chip_fallback"
                # chip fallback defines structural bands too
                structural_bands = dict(bands)
                structural_band_source = "chip_fallback"
            except Exception:
                bands = {}
        # stale & sanity fallback (near-end window) + diagnostics
        try:
            import os
            diag = {}
            last_idx = len(df_feat) - 1
            setup_idx = int(getattr(setup, "idx", last_idx)) if setup is not None else last_idx
            setup_age = max(0, last_idx - setup_idx)
            stale_th = int(os.getenv("GP_KEYBAND_STALE_BARS", "10"))
            recent_n = int(os.getenv("GP_KEYBAND_RECENT_WINDOW", "60"))
            if setup_age > stale_th:
                x = df_feat.tail(max(30, recent_n))
                s1 = float(x["close"].quantile(0.30)) if "close" in x.columns else 0.0
                s2 = float(x["close"].quantile(0.50)) if "close" in x.columns else 0.0
                r1 = float(x["close"].quantile(0.80)) if "close" in x.columns else 0.0
                # structural remains the earlier one; recenter execution bands from recent window
                bands = {"S1": s1, "S2": s2, "R1": r1, "R2": (r1 * 1.02 if r1 else 0.0)}
                diag.update({"setup_age": setup_age, "stale": True, "fallback_reason": "stale_setup"})
                band_source = "recent_window_fallback"
                execution_band_source = "recent_window_fallback"
            last_close = float(df_feat["close"].iloc[-1]) if "close" in df_feat.columns else 0.0
            if last_close and bands:
                s1c = float(bands.get("S1", 0.0)); r1c = float(bands.get("R1", 0.0))
                if (s1c and s1c < 0.4 * last_close) or (r1c and r1c > 2.5 * last_close):
                    x = df_feat.tail(max(30, recent_n))
                    s1 = float(x["close"].quantile(0.30)) if "close" in x.columns else 0.0
                    s2 = float(x["close"].quantile(0.50)) if "close" in x.columns else 0.0
                    r1 = float(x["close"].quantile(0.80)) if "close" in x.columns else 0.0
                    # recenter execution bands; keep structural intact
                    bands = {"S1": s1, "S2": s2, "R1": r1, "R2": (r1 * 1.02 if r1 else 0.0)}
                    diag.update({"sanity_warning": "key_bands_out_of_scale_fallback"})
                    band_source = "recent_window_fallback"
                    execution_band_source = "recent_window_fallback"
            # Always include setup metrics even if not stale
            diag.setdefault("setup_idx", setup_idx)
            diag.setdefault("setup_age", setup_age)
            diag.setdefault("stale", False)
            if band_source:
                diag["band_source"] = band_source
            # execution vs structural bands separation and execution state
            exec_bands = dict(bands)
            entry_gap_abs = None
            signed_entry_gap = None
            reward_risk = None
            actionable = None
            state = None
            try:
                s1v = float(exec_bands.get("S1", 0.0))
                r1v = float(exec_bands.get("R1", 0.0))
                if last_close and s1v:
                    signed_entry_gap = (last_close - s1v) / last_close
                    entry_gap_abs = abs(signed_entry_gap)
                if last_close and s1v and r1v and last_close > s1v:
                    reward_risk = float((r1v - last_close) / max(1e-6, (last_close - s1v)))
                # decide state using signed gap and RR
                if signed_entry_gap is None:
                    actionable = False; state = "observe_only"
                else:
                    if signed_entry_gap <= EXEC_BELOW_SUPPORT_TOL_PCT:
                        actionable = False; state = "below_support"
                    elif signed_entry_gap <= 0.0:  # at/just below S1 but within tolerance
                        actionable = False; state = "breakdown_risk"
                    elif entry_gap_abs is not None and entry_gap_abs <= EXEC_ACTIONABLE_MAX_GAP_PCT:
                        # RR must be valid for actionable
                        if reward_risk is None or reward_risk < MIN_RR_FOR_ACTIONABLE:
                            actionable = False; state = "observe_only"
                        else:
                            actionable = True; state = "actionable"
                    elif entry_gap_abs is not None and entry_gap_abs <= EXEC_WAITING_MAX_GAP_PCT:
                        actionable = False; state = "waiting_pullback"
                    else:
                        actionable = False; state = "observe_only"
            except Exception:
                pass
            if state:
                diag.update({
                    "execution_state": state,
                    "entry_gap_pct": entry_gap_abs,
                    "signed_entry_gap_pct": signed_entry_gap,
                    "reward_risk": reward_risk,
                    "actionable": actionable,
                })
            # Explain divergence between structural and execution bands
            try:
                if structural_bands and exec_bands:
                    s_s1 = float(structural_bands.get("S1", 0.0))
                    e_s1 = float(exec_bands.get("S1", 0.0))
                    if s_s1 and e_s1:
                        div = abs(e_s1 - s_s1) / max(s_s1, 1e-6)
                        if div >= BAND_DIVERGENCE_EXPLAIN_THRESH:
                            diag["structural_execution_divergence"] = {
                                "s1_struct": s_s1,
                                "s1_exec": e_s1,
                                "ratio": div,
                                "explain": "execution bands recentered from structural due to stale/out-of-scale",
                            }
            except Exception:
                pass
        except Exception:
            diag = {}
        # actions & invalidation
        try:
            ct = getattr(mod, "confirm_text", None)
            if callable(ct):
                t = ct(setup, q_grade or "Q?")
                if isinstance(t, dict):
                    actions = {
                        "window_A": str(t.get("window_A_text", "A窗：关键带回收，承接成立")),
                        "window_B": str(t.get("window_B_text", "B窗：收盘确认，不追价")),
                    }
        except Exception:
            actions = {}
        try:
            inv = getattr(mod, "invalidation", None)
            if callable(inv):
                lst = inv(setup)
                invalid = [str(x) for x in (lst or [])]
        except Exception:
            invalid = []
        risk = {"stop_loss": "收盘有效跌破支撑带", "time_stop": "2-3日不强必走", "no_averaging_down": True}
        # Derive entry/stop/take for UI consumption
        entry = None
        take = None
        stop = None
        try:
            if bands:
                s1 = bands.get("S1")
                s2 = bands.get("S2")
                r1 = bands.get("R1")
                r2 = bands.get("R2")
                if s1 is not None and s2 is not None:
                    entry = [s1, s2]
                elif s1 is not None:
                    entry = s1
                if r1 is not None and r2 is not None:
                    take = [r1, r2]
                elif r1 is not None:
                    take = r1
        except Exception:
            pass
        stop = (risk.get("stop_loss") if isinstance(risk, dict) else None) or stop or "收盘有效跌破支撑带"
        # Resolve band sources for output clarity
        structural_band_source = structural_band_source or (band_source or "unknown")
        execution_band_source = execution_band_source or (band_source or "direct")
        return {
            "bands": exec_bands,
            "execution_bands": exec_bands,
            "structural_bands": structural_bands,
            "structural_band_source": structural_band_source,
            "execution_band_source": execution_band_source,
            "actions": actions,
            "invalidation": invalid,
            "risk": risk,
            "diagnostics": diag,
            "entry": entry,
            "stop": stop,
            "take": take,
        }

    # Evaluate strategies for pool and choose champion
    feats_by_symbol: Dict[str, pd.DataFrame] = {}
    strategies_by_symbol: Dict[str, Any] = {}
    strategy_eval_failures: List[Dict[str, Any]] = []
    for cand in pool:
        sym = str(cand.get("symbol"))
        try:
            df, _meta = hub.daily_ohlcv(sym, None, min_len=250)
            feat = compute_indicators(df)
            feats_by_symbol[sym] = feat
            strategies_by_symbol[sym] = _eval_strategies_for_symbol(sym, feat, q_grade=(cand.get("q_grade") or cand.get("indicators", {}).get("q_grade")))
        except Exception as e:  # noqa: BLE001
            strategy_eval_failures.append({"symbol": sym, "error": str(e)})
            strategies_by_symbol[sym] = {}
    # attach strategies for champion selection
    for cand in pool:
        cand["strategies"] = strategies_by_symbol.get(str(cand.get("symbol")), {})
    champions = choose_champion(pool)

    # Build picks with champion and trade_plan
    picks: List[Dict[str, Any]] = []
    for cand in pool:
        sym = str(cand.get("symbol"))
        it: Dict[str, Any] = {
            "symbol": sym,
            "theme": (cand.get("industry") or cand.get("source_reason") or "行业轮动"),
            "market_theme": (themes[0]["name"] if themes else None),
            "flags": cand.get("flags", {}),
            "chip": cand.get("chip", {}),
            "indicators": cand.get("indicators", {}),
        }
        # carry candidate score to pick for transparency
        if "candidate_score" in cand:
            it["candidate_score"] = float(cand.get("candidate_score", 0.0))
        champ = champions.get(sym) if isinstance(champions, dict) else None
        if champ:
            it["champion"] = champ
            mod = (strat_lib.REGISTRY or {}).get(str(champ.get("strategy")))
            feat = feats_by_symbol.get(sym)
            if mod is not None and feat is not None:
                it["trade_plan"] = _trade_plan_from_strategy(mod, feat, cand, q_grade=(cand.get("q_grade") or cand.get("indicators", {}).get("q_grade")))
        # attach last_close/last_date if available
        try:
            feat = feats_by_symbol.get(sym)
            if feat is not None and len(feat) > 0:
                it["last_close"] = float(feat["close"].iloc[-1]) if "close" in feat.columns else None
                # last_date: prefer explicit date column, then DatetimeIndex; never integer index
                last_date_val = None
                if "date" in feat.columns:
                    try:
                        last_date_val = str(pd.to_datetime(feat["date"].iloc[-1]).date())
                    except Exception:
                        last_date_val = str(feat["date"].iloc[-1])
                else:
                    try:
                        idx = feat.index
                        if hasattr(idx, "dtype") and str(getattr(idx, "dtype", "")).startswith("datetime64"):
                            last_date_val = str(pd.to_datetime(idx[-1]).date())
                    except Exception:
                        last_date_val = None
                it["last_date"] = last_date_val
        except Exception:
            it.setdefault("last_close", None)
            it.setdefault("last_date", None)
        picks.append(it)
    # Second-stage rerank by candidate/thematic/champion with execution penalties and breakdown
    def _score_components(item: Dict[str, Any]) -> Dict[str, float]:
        champ = item.get("champion", {}) or {}
        tp = item.get("trade_plan", {}) or {}
        diag = tp.get("diagnostics", {}) if isinstance(tp, dict) else {}
        indicators = item.get("indicators", {}) or {}
        champ_s = float(champ.get("score", 0.0))
        entry_gap = float(diag.get("entry_gap_pct") or 0.0)
        rr = float(diag.get("reward_risk") or 0.0)
        state = str(diag.get("execution_state") or "").lower()
        pen = RERANK_STATE_PENALTY.get(state, 0.0)
        # candidate base score
        cand_s = float(item.get("candidate_score", 0.0))
        # thematic components
        theme_s = float(item.get("theme_overlap_score", 0.0))
        mainline_s = float(item.get("mainline_overlap_score", 0.0))
        thematic = 0.6 * mainline_s + 0.4 * theme_s
        # soft overextension penalty if extension metrics available
        ext_pen = 0.0
        try:
            ext = 0.0
            for k in ["extension_ma10", "extension_ma20", "extension_from_cost"]:
                v = item.get("indicators", {}).get(k)
                if v is not None:
                    ext = max(ext, abs(float(v)))
            ext_pen = -min(0.5, ext)
        except Exception:
            ext_pen = 0.0
        # freshness penalty from champion if available
        fresh_pen = float((champ or {}).get("setup_penalty") or 0.0)
        return {
            "champion_component": 0.6 * champ_s,
            "candidate_component": 0.4 * cand_s,
            "thematic_component": 0.2 * thematic,
            "reward_risk_component": 0.2 * rr,
            "entry_gap_penalty": -0.3 * entry_gap,
            "execution_state_penalty": pen,
            "extension_penalty": float(ext_pen),
            "freshness_penalty": fresh_pen,
        }

    def _final_score(item: Dict[str, Any]) -> float:
        comp = _score_components(item)
        total = sum(comp.values())
        # attach breakdown and explain
        try:
            item["score_breakdown"] = dict(comp)
            item["score_breakdown"]["total"] = float(total)
            # brief explain
            champ_sc = float((item.get("champion") or {}).get("score") or 0.0)
            state = str(((item.get("trade_plan") or {}).get("diagnostics") or {}).get("execution_state") or "")
            # thematic and candidate parts in explain; plus reason text
            th = float(item.get("theme_overlap_score", 0.0) or 0.0)
            ml = float(item.get("mainline_overlap_score", 0.0) or 0.0)
            cand_base = float(item.get("candidate_score", 0.0) or 0.0)
            reason_parts = []
            if th > 0 or ml > 0:
                reason_parts.append("within_mainline")
            else:
                reason_parts.append("off_mainline_downrank")
            item["explain"] = f"champ={champ_sc:.2f}, cand={cand_base:.2f}, th={th:.2f}/ml={ml:.2f}, state={state}, rr={((item.get('trade_plan') or {}).get('diagnostics') or {}).get('reward_risk')}; {' '.join(reason_parts)}"
        except Exception:
            pass
        return float(total)

    for it in picks:
        it["final_score"] = _final_score(it)
    picks.sort(key=lambda x: float(x.get("final_score", 0.0)), reverse=True)
    picks = picks[: topk or 3]
    # Champion availability advisory (soft warning, not affecting tradeable)
    champion_missing_syms: List[str] = []
    if picks:
        for it in picks:
            ch = it.get("champion") or {}
            if not ch or str(ch.get("strategy", "NA")) in {"", "NA", "None"}:
                champion_missing_syms.append(str(it.get("symbol")))
        if champion_missing_syms:
            warn_once("CHAMPION_UNAVAILABLE", f"champion missing for {len(champion_missing_syms)} picks")
    else:
        warn_once("CHAMPION_UNAVAILABLE", "no picks -> champion not computed")

    # sources summary
    sources = [{"symbol": it["symbol"], "data_source": "provider"} for it in pool]

    payload: Dict[str, Any] = {
        "as_of": as_of,
        "timezone": cfg.timezone,
        "env": env,
        "themes": themes,
                "mainline": mainline,
"candidate_pool": pool,
        "picks": picks,
        "execution_checklist": [
            "1) 环境分层",
            "2) 主线限制",
            "3) 硬条件评估",
        ],
        "disclaimer": "本内容仅供研究与教育，不构成任何投资建议或收益承诺；市场有风险，决策需独立承担",
        "debug": {"timing": {}, "sources": sources, "failures": veto, "snapshot": snap_meta},
    }
    # Adjust execution checklist third item to reflect champion integration
    try:
        if isinstance(payload.get("execution_checklist"), list) and len(payload["execution_checklist"]) >= 3:
            payload["execution_checklist"][2] = "3) 策略冠军与关键带"
    except Exception:
        pass

    # Degradation recording and tradeable decision
    dbg = payload.setdefault("debug", {})
    dbg["candidate_stats"] = cand_stats
    # snapshot mainboard counts
    try:
        if snapshot_df is not None:
            code_col = None
            for c in ["代码", "code", "ts_code"]:
                if c in snapshot_df.columns:
                    code_col = c
                    break
            if code_col:
                total_n = int(len(snapshot_df))
                try:
                    main_n = int(snapshot_df[code_col].astype(str).map(is_mainboard).sum())
                except Exception:
                    main_n = 0
                dbg["snapshot_mainboard_counts"] = {"before": total_n, "after": main_n}
    except Exception:
        pass
    # thematic restriction info
    try:
        dbg["restrict_to_mainline"] = bool(restrict_mainline)
        dbg.setdefault("thematic_stats", {})
        dbg["thematic_stats"].update({
            "pool_unrelated_count": int(thematic_none_count),
            "pool_after_thematic_filter": int(len(pool)),
        })
        src = None
        if isinstance(themes, list) and themes:
            src = themes[0].get("source")
        dbg["thematic_stats"]["theme_source"] = src
    except Exception:
        pass
    # surface no valid mainboard theme when restricted and empty pool
    if restrict_mainline and len(pool) == 0:
        degrade_record(dbg, "NO_VALID_MAINBOARD_THEME", {})
    if champion_missing_syms:
        dbg.setdefault("advisories", []).append({"code": "CHAMPION_UNAVAILABLE", "symbols": champion_missing_syms})
    # record strategy evaluation failures if any
    try:
        for f in locals().get("strategy_eval_failures", []) or []:
            degrade_record(dbg, "STRATEGY_EVAL_FAILED", {"symbol": f.get("symbol"), "error": f.get("error")})
    except Exception:
        pass
    if snap_meta.get("missing"):
        degrade_record(dbg, "SNAPSHOT_MISSING", {k: v for k, v in snap_meta.items() if k != "missing"})
    if snap_meta.get("cache") == "memory":
        degrade_record(dbg, "SNAPSHOT_MEMORY_CACHE", {})
    if snap_meta.get("cache") == "disk":
        degrade_record(dbg, "SNAPSHOT_DISK_CACHE", {"age_sec": snap_meta.get("cache_age_sec")})
    if bool(snap_meta.get("fallback")):
        degrade_record(dbg, "SNAPSHOT_FALLBACK", {"to": snap_meta.get("source"), "reason": snap_meta.get("fallback_reason")})
    if snap_meta.get("skipped_routes"):
        degrade_record(dbg, "SNAPSHOT_ROUTE_SKIPPED", {"routes": snap_meta.get("skipped_routes")})
    if snapshot_df is None:
        degrade_record(dbg, "ENV_NEUTRALIZED", {})
        degrade_record(dbg, "THEMES_EMPTY", {})
        degrade_record(dbg, "MARKET_STATS_MISSING", {})

    # Structured cleanliness check (do not rely on source text)
    def _is_clean_live_snapshot(meta: Dict[str, Any]) -> bool:
        try:
            if meta.get("missing") is True:
                return False
            if meta.get("cache"):
                return False
            if meta.get("stale") is True:
                return False
            if meta.get("fallback") is True:
                return False
            if meta.get("skipped_routes"):
                return False
            if meta.get("error") or meta.get("error_type"):
                return False
        except Exception:
            return False
        return True

    # Threshold-based reasons
    if cand_stats.get("universe_after_filter_count", 0) < getattr(cfg, "tradeable_min_universe", 50):
        degrade_record(dbg, "UNIVERSE_TOO_SMALL", {"count": cand_stats.get("universe_after_filter_count", 0), "min": getattr(cfg, "tradeable_min_universe", 50)})
    if cand_stats.get("candidates_out_count", 0) < getattr(cfg, "tradeable_min_candidates", 20):
        degrade_record(dbg, "CANDIDATE_TOO_SMALL", {"count": cand_stats.get("candidates_out_count", 0), "min": getattr(cfg, "tradeable_min_candidates", 20)})
    if cand_stats.get("bars_too_short_count", 0) > 0:
        degrade_record(dbg, "BARS_TOO_SHORT", {"count": cand_stats.get("bars_too_short_count", 0)})
    if cand_stats.get("indicator_error_count", 0) > 0:
        degrade_record(dbg, "INDICATOR_PARTIAL", {"count": cand_stats.get("indicator_error_count", 0)})
    # Universe dirty input visibility (does not change tradeable rules)
    try:
        rem = cand_stats.get("universe_removed_counts", {}) or {}
        if any(int(v) > 0 for v in rem.values()):
            degrade_record(dbg, "UNIVERSE_DIRTY_INPUT", rem, severity="warn")
    except Exception:
        pass

    # Finalize tradeable
    tradeable = not dbg.get("degraded") and _is_clean_live_snapshot(snap_meta) \
        and cand_stats.get("universe_after_filter_count", 0) >= getattr(cfg, "tradeable_min_universe", 50) \
        and cand_stats.get("candidates_out_count", 0) >= getattr(cfg, "tradeable_min_candidates", 20)
    try:
        if bool(getattr(cfg, "require_mainline_for_tradeable", False)) and not (mainline.get("sectors")):
            degrade_record(dbg, "MAINLINE_MISSING", {})
            tradeable = False
    except Exception:
        pass
    if tradeable and dbg.get("degrade_reasons"):
        degrade_record(dbg, "INSUFFICIENT_EVIDENCE_TRADEABLE", {"reason": "degrade_reasons_present"})
        tradeable = False
    payload["tradeable"] = bool(tradeable)
    # Message with strong visibility when not tradeable
    if not payload["tradeable"]:
        rs = [str(x.get("reason_code")) for x in dbg.get("degrade_reasons", [])]
        prefix = "NOT_TRADEABLE: " + (", ".join(rs[:2]) if rs else "UNKNOWN")
        payload["message"] = prefix
    else:
        payload["message"] = f"generated {len(picks)} picks"

    # Print top 3 [DEGRADED] summaries
    if dbg.get("degraded"):
        rs = dbg.get("degrade_reasons", [])
        for r in rs[:3]:
            code = r.get("reason_code")
            detail = r.get("detail", {})
            parts = []
            for k in ("age_sec", "routes", "count", "min", "count_unique"):
                if k in detail:
                    parts.append(f"{k}={detail[k]}")
            logger.warning(f"[DEGRADED] {code} {' '.join(parts)}".strip())

    # Attach mover_hints (separate from themes; no pseudo when snapshot missing)
    payload["mover_hints"] = build_mover_hints(snapshot_df, topn=3) if snapshot_df is not None else []

    # Normalize for strict contract (drop pseudo, set None)
    payload = normalize_payload(payload)

    # Data status for contract
    ds_snapshot = {
        "ok": snapshot_df is not None,
        "source": (snap_meta.get("source") or snap_meta.get("cache_of") or None),
        "rows": (0 if snapshot_df is None else int(len(snapshot_df))),
        "elapsed_sec": snap_meta.get("elapsed_sec"),
        "cache": snap_meta.get("cache") or "none",
        "as_of_ts": snap_meta.get("as_of_ts"),
        "error": snap_meta.get("error"),
    }
    try:
        lcs = last_concept_status()
    except Exception:
        lcs = {"attempted": [], "error": None}
    ds_themes = {
        "ok": bool(payload.get("themes")),
        "source": (lcs.get("source") or ",".join(sorted(set([str(t.get("source")) for t in (payload.get("themes") or []) if isinstance(t, dict) and t.get("source")]))) or None),
        "attempted": lcs.get("attempted") or [],
        "error": lcs.get("error"),
        "as_of_ts": (lcs.get("as_of_ts") or snap_meta.get("as_of_ts")),
        "stale": bool(lcs.get("stale") or False),
    }
    ds_mainline = {
        "ok": bool(mainline.get("sectors")),
        "source": mainline.get("source") or "akshare:stock_sector_fund_flow_rank",
        "error": None if (mainline.get("sectors")) else (";".join(mainline.get("errors") or []) if mainline.get("errors") else None),
        "as_of_ts": mainline.get("as_of_ts"),
        "stale": bool((isinstance(mainline.get("source"), str) and mainline.get("source") == "cache:file") or (isinstance(mainline.get("errors"), list) and any("stale_cache_used" in str(e) for e in mainline.get("errors") or []))),
    }
    ds_daily = {
        "ok": True,
        "symbols_ok": len(feats_by_symbol),
        "symbols_fail": len(locals().get("strategy_eval_failures", []) or []),
        "error_summary": None,
    }
    payload["data_status"] = {"snapshot": ds_snapshot, "themes": ds_themes, "daily": ds_daily, "mainline": ds_mainline}

    _write_outputs(as_of, payload)
    return payload






