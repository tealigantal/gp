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
from typing import Any, Dict, List, Optional, Tuple
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from ..core.config import load_config
from ..core.logging import logger
from ..observe.degrade import record as degrade_record
import os
from ..observe.degrade import warn_once
from ..core.paths import store_dir
from .contracts import build_v2_from_v1
from .validators import validate_pick_artifact_v2
from .calibration import apply_scores_to_v2_item, compute_no_trade_gate
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
    # main files
    (out_dir / f"{as_of}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{as_of}_debug.json").write_text(json.dumps(payload.get("debug", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    # stage-oriented source summary (never empty)
    dbg = payload.get("debug", {}) or {}
    ds = payload.get("data_status", {}) or {}
    cand_stats = (dbg.get("candidate_stats") or {})
    them_stats = (dbg.get("thematic_stats") or {})
    strat_counts = (dbg.get("strategy_eval_counts") or {})
    reasons = [r.get("reason_code") for r in (dbg.get("degrade_reasons") or []) if isinstance(r, dict)]
    snap = (ds.get("snapshot") or {})
    th = (ds.get("themes") or {})
    ml = (ds.get("mainline") or {})
    sources_obj = {
        "snapshot": {
            "ok": bool(snap.get("ok")),
            "source": snap.get("source"),
            "elapsed_sec": snap.get("elapsed_sec"),
            "cache": snap.get("cache"),
            "as_of_ts": snap.get("as_of_ts"),
            "error": snap.get("error"),
        },
        "themes": {
            "ok": bool(th.get("ok")),
            "source": th.get("source"),
            "attempted": th.get("attempted"),
            "error": th.get("error"),
            "as_of_ts": th.get("as_of_ts"),
            "stale": th.get("stale"),
        },
        "mainline": {
            "ok": bool(ml.get("ok")),
            "source": ml.get("source"),
            "error": ml.get("error"),
            "as_of_ts": ml.get("as_of_ts"),
            "stale": ml.get("stale"),
            "restrict_to_mainline": bool(dbg.get("restrict_to_mainline")),
            "restrict_effective": bool(dbg.get("restrict_to_mainline_effective")),
        },
        "candidate": {
            "universe_in_count": cand_stats.get("universe_in_count"),
            "universe_after_mainboard_filter_count": cand_stats.get("universe_after_mainboard_filter_count"),
            "universe_after_code_clean_count": cand_stats.get("universe_after_code_clean_count"),
            "bars_missing_count": cand_stats.get("bars_missing_count"),
            "bars_too_short_count": cand_stats.get("bars_too_short_count"),
            "indicator_error_count": cand_stats.get("indicator_error_count"),
            "pool_pre_thematic_count": cand_stats.get("pool_pre_thematic_count") or cand_stats.get("candidates_out_count"),
        },
        "filters": {
            "pool_before_thematic_filter": them_stats.get("pool_before_thematic_filter"),
            "pool_after_theme_filter": them_stats.get("pool_after_theme_filter"),
            "pool_after_mainline_filter": them_stats.get("pool_after_mainline_filter"),
            "pool_after_thematic_mainline_filter": them_stats.get("pool_after_thematic_mainline_filter"),
        },
        "strategy": {
            "symbols": strat_counts.get("symbols", 0),
            "strategies": strat_counts.get("strategies"),
        },
        "final": {
            "degraded": bool(dbg.get("degraded")),
            "reasons": reasons,
        },
    }
    p_sources = out_dir / f"{as_of}_sources.json"
    p_sources.write_text(json.dumps(sources_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    # Backward/alternative filename for tooling convenience
    try:
        (out_dir / f"{as_of}_source.json").write_text(p_sources.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass
    # --- Phase 2.6: also persist V2 artifact via unified helper ---
    try:
        from .artifact_store import build_v2_dict_from_v1, persist_artifact_v2

        v2_fixed = build_v2_dict_from_v1(payload)
        rid = str(v2_fixed.get("run_id") or as_of)
        persist_artifact_v2(rid, v2_fixed)
    except Exception as e:  # noqa: BLE001
        try:
            logger.error(f"[V2_WRITE] failed as_of={as_of} err={type(e).__name__}:{e}")
        except Exception:
            pass


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

    # Prepare early thematic/mainline prefilter (cheap shrink)
    try:
        theme_names_pref = [str(t.get("name")) for t in (themes or []) if isinstance(t, dict)]
    except Exception:
        theme_names_pref = []
    try:
        mainline_names_pref = [str(s.get("name")) for s in (mainline.get("sectors") or [])] if isinstance(mainline, dict) else []
    except Exception:
        mainline_names_pref = []
    restrict_for_prefilter = bool(getattr(cfg, "restrict_to_mainline", False) and (isinstance(mainline, dict) and (mainline.get("sectors") or [])))
    industry_prefilter = list({*theme_names_pref, *mainline_names_pref}) if restrict_for_prefilter else None

    # Candidates with stats (build once; share features in-run to avoid recomputation)
    t0 = time.perf_counter()
    gen_out = generate_candidates(base, env.get("grade", "C"), topk=topk, snapshot=snapshot_df, return_features=True, as_of=as_of, industry_filter=industry_prefilter)
    # mypy-friendly unpack
    if len(gen_out) == 4:  # type: ignore[truthy-function]
        pool, veto, cand_stats, feats_precomp = gen_out  # type: ignore[misc]
    else:  # pragma: no cover - compatibility
        pool, veto, cand_stats = gen_out[:3]  # type: ignore[index]
        feats_precomp = {}
    t1 = time.perf_counter()

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
    theme_only_pool: List[Dict[str, Any]] = []
    mainline_only_pool: List[Dict[str, Any]] = []
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
        # collect per-dimension pools for diagnostics
        try:
            if float(th["theme_overlap_score"]) > 0.0:
                theme_only_pool.append(cand)
            if float(th["mainline_overlap_score"]) > 0.0:
                mainline_only_pool.append(cand)
        except Exception:
            pass

    restrict_mainline = bool(getattr(cfg, "restrict_to_mainline", False))
    # detect mainline availability: sectors present -> available; errors + empty sectors -> unavailable
    mainline_available = bool(isinstance(mainline, dict) and (mainline.get("sectors") or []))
    mainline_errors = (list(mainline.get("errors") or []) if isinstance(mainline, dict) else [])
    restrict_effective = bool(restrict_mainline and mainline_available)
    pool_before_thematic = int(len(pool))
    if restrict_effective:
        # Filter pool only when mainline is available (union with themes)
        pool = themed_pool
    else:
        # mainline unavailable or restriction disabled -> do not hard filter here
        pass
    # Empty-source diagnostics (before strategy evaluation)
    empty_reason: Optional[str] = None
    if cand_stats.get("candidates_out_count", 0) == 0:
        empty_reason = "no_candidate_after_universe"
    elif restrict_effective and len(pool) == 0:
        # handled via MAINLINE_FILTERED_ALL below to avoid duplicate/conflicting reasons
        empty_reason = None

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
        # Iterate all registered strategies (lazy/cheap-first gate)
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
                # Cheap pass: skip expensive event study when obviously ineligible
                # - no setups -> skip
                # - stale setups beyond threshold -> skip
                # - strategies explicitly prefer observation_only -> still compute minimal metadata only
                ev = getattr(mod, "event_study", None)
                st_meta = (getattr(strat_lib, "METADATA", {}) or {}).get(str(sid), {})
                prefer_obs = bool(st_meta.get("prefer_observation_only", False))
                setup_idx = int(getattr(setups[-1], "idx", len(df_feat) - 1)) if setups else (len(df_feat) - 1)
                setup_age = max(0, (len(df_feat) - 1) - setup_idx)
                stale_th = 15
                if callable(ev) and setups and setup_age <= stale_th and not prefer_obs:
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
                                "debug_explain": "execution bands recentered from structural due to stale/out-of-scale",
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
        # Unified trade plan objects derived from bands
        try:
            _s1 = float(bands.get("S1")) if (bands and bands.get("S1") is not None) else None
        except Exception:
            _s1 = None
        try:
            _s2 = float(bands.get("S2")) if (bands and bands.get("S2") is not None) else None
        except Exception:
            _s2 = None
        try:
            _r1 = float(bands.get("R1")) if (bands and bands.get("R1") is not None) else None
        except Exception:
            _r1 = None
        try:
            _r2 = float(bands.get("R2")) if (bands and bands.get("R2") is not None) else None
        except Exception:
            _r2 = None
        entry_obj = {"kind": "zone", "low": (_s1 if _s1 is not None else None), "high": (_s2 if _s2 is not None else None), "price": (_s1 if _s1 is not None else None)}
        _stop_text = "收盘有效跌破支撑带"
        stop_obj = {"kind": "close_below_support", "price": (_s1 if _s1 is not None else None), "invalidation": _stop_text, "text": _stop_text}
        take_obj = {"kind": "targets", "price": (_r1 if _r1 is not None else None), "targets": [x for x in [_r1, _r2] if x is not None]}
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
            "entry": entry_obj,
            "stop": stop_obj,
            "take_profit": take_obj,
        }

    # Evaluate strategies for pool and choose champion
    feats_by_symbol: Dict[str, pd.DataFrame] = {}
    strategies_by_symbol: Dict[str, Any] = {}
    strategy_eval_failures: List[Dict[str, Any]] = []
    # Seed with precomputed features from candidate stage
    if isinstance(feats_precomp, dict):
        feats_by_symbol.update({str(k): v for k, v in feats_precomp.items() if isinstance(k, str)})

    # Optional bounded concurrency for per-symbol evaluation (CPU-bound, safe to parallelize)
    try:
        import os  # lazy
        max_workers_env = int(os.getenv("GP_EVAL_WORKERS", "0") or 0)
    except Exception:
        max_workers_env = 0
    try:
        cfg_workers = int(getattr(cfg, "parallel_workers", 0) or 0)
    except Exception:
        cfg_workers = 0
    max_workers = max(0, max(max_workers_env, cfg_workers))
    if max_workers <= 0:
        max_workers = 1  # conservative default: serial

    def _ensure_feat(sym: str) -> pd.DataFrame:
        if sym in feats_by_symbol:
            return feats_by_symbol[sym]
        df, _meta = hub.daily_ohlcv(sym, as_of=as_of, min_len=250)
        feat2 = compute_indicators(df)
        feats_by_symbol[sym] = feat2
        return feat2

    def _eval_one(sym: str, q_grade: Optional[str]) -> Tuple[str, Dict[str, Any]]:
        try:
            feat = _ensure_feat(sym)
            res = _eval_strategies_for_symbol(sym, feat, q_grade)
            return sym, res
        except Exception as e:  # noqa: BLE001
            strategy_eval_failures.append({"symbol": sym, "error": str(e)})
            return sym, {}

    t2 = time.perf_counter()
    if pool:
        if max_workers > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = []
                for cand in pool:
                    sym = str(cand.get("symbol"))
                    qg = (cand.get("q_grade") or cand.get("indicators", {}).get("q_grade"))
                    futs.append(ex.submit(_eval_one, sym, qg))
                for fut in as_completed(futs):
                    s, strat_res = fut.result()
                    strategies_by_symbol[s] = strat_res
        else:
            for cand in pool:
                sym = str(cand.get("symbol"))
                qg = (cand.get("q_grade") or cand.get("indicators", {}).get("q_grade"))
                s, strat_res = _eval_one(sym, qg)
                strategies_by_symbol[s] = strat_res
    t3 = time.perf_counter()
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
            "theme_overlap_score": float(cand.get("theme_overlap_score", 0.0) or 0.0),
            "mainline_overlap_score": float(cand.get("mainline_overlap_score", 0.0) or 0.0),
        }
        if cand.get("penalty_tags"):
            it["penalty_tags"] = list(cand.get("penalty_tags") or [])
        if cand.get("thematic_reasons"):
            it["thematic_reasons"] = list(cand.get("thematic_reasons") or [])
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
            # Avoid double-penalizing when candidate_score already included extension
            cand_penalized = False
            try:
                tags = set(item.get("penalty_tags", []) or [])
                cand_penalized = ("extension" in tags)
            except Exception:
                cand_penalized = False
            ext_pen = 0.0 if cand_penalized else -min(0.5, ext)
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
        # attach breakdown and explanations (user/debug split)
        try:
            item["score_breakdown"] = dict(comp)
            item["score_breakdown"]["total"] = float(total)
            # brief explanations: split user-facing vs debug
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
            # Debug-only string
            item["debug_explain"] = (
                f"champ={champ_sc:.2f}, cand={cand_base:.2f}, th={th:.2f}/ml={ml:.2f}, "
                f"state={state}, rr={((item.get('trade_plan') or {}).get('diagnostics') or {}).get('reward_risk')}; "
                + " ".join(reason_parts)
            )
            # Structured reason codes
            rc: List[str] = [*reason_parts]
            try:
                rr = ((item.get('trade_plan') or {}).get('diagnostics') or {}).get('reward_risk')
                if rr is not None:
                    rc.append('rr_known')
                rc.append(f"state={state}")
            except Exception:
                pass
            item["reason_codes"] = rc
            # User-facing thesis in Chinese (generic)
            if state == 'actionable':
                user_msg = "接近计划买点，执行条件较充分，留意盘中确认。"
            elif state in {'waiting_pullback', 'observe_only'}:
                user_msg = "结构候选靠前，但当前执行条件一般，建议观察等待更优位置。"
            elif state in {'below_support', 'breakdown_risk'}:
                user_msg = "状态偏弱或跌破支撑，建议谨慎，等待重回计划区间。"
            else:
                user_msg = "候选结构较优，具体执行以盘中信号为准。"
            if 'off_mainline_downrank' in reason_parts:
                user_msg += " 主线覆盖不足，排序有下调。"
            item["user_thesis"] = user_msg
            item["why_selected_text"] = "相对同组候选综合条件更优。"
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
    # Timing
    try:
        dbg["timing"] = {
            "candidates_sec": round(t1 - t0, 3),
            "strategy_eval_sec": round(t3 - t2, 3),
        }
    except Exception:
        pass
    # Empty-result classification (pre-normalize)
    if empty_reason:
        degrade_record(dbg, empty_reason.upper(), {})
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
    # thematic/mainline diagnostic stats
    try:
        dbg.setdefault("thematic_stats", {})
        dbg["restrict_to_mainline"] = bool(restrict_mainline)
        dbg["restrict_to_mainline_effective"] = bool(restrict_effective)
        dbg["thematic_stats"].update({
            "pool_before_thematic_filter": int(pool_before_thematic),
            "pool_unrelated_count": int(thematic_none_count),
            "pool_after_theme_filter": int(len(theme_only_pool)),
            "pool_after_mainline_filter": (int(len(mainline_only_pool)) if ("mainline_only_pool" in locals()) and mainline_available else None),
            "pool_after_thematic_mainline_filter": (int(len(pool)) if restrict_effective else None),
            "theme_source": (themes[0].get("source") if isinstance(themes, list) and themes else None),
            "mainline_ok": bool(mainline_available),
            "mainline_errors": (";".join(mainline_errors) if mainline_errors else None),
        })
    except Exception:
        pass
    # Stage-specific degrade reasons for thematic/mainline
    if restrict_mainline and (not restrict_effective):
        # Mainline unavailable shouldn't block tradeability; record as warning only
        degrade_record(dbg, "MAINLINE_UNAVAILABLE", {"errors": mainline_errors, "restrict_to_mainline": True}, severity="warn")
    # Only claim filtered-all if there were candidates before thematic and restriction was effectively applied
    if restrict_effective and int(pool_before_thematic) > 0 and len(pool) == 0:
        degrade_record(dbg, "MAINLINE_FILTERED_ALL", {})
    if champion_missing_syms:
        dbg.setdefault("advisories", []).append({"code": "CHAMPION_UNAVAILABLE", "symbols": champion_missing_syms})
    # record strategy evaluation failures if any
    try:
        for f in locals().get("strategy_eval_failures", []) or []:
            degrade_record(dbg, "STRATEGY_EVAL_FAILED", {"symbol": f.get("symbol"), "error": f.get("error")})
    except Exception:
        pass
    # 非交易日：关于快照可用性的降级只记为警告，不触发 tradeable=false
    _is_non_trading = False
    try:
        from datetime import datetime as _dt
        from .calendar import is_trading_day as _is_td
        _is_non_trading = not _is_td(_dt.now())
    except Exception:
        _is_non_trading = False

    if snap_meta.get("missing"):
        degrade_record(dbg, "SNAPSHOT_MISSING", {k: v for k, v in snap_meta.items() if k != "missing"}, severity=("warn" if _is_non_trading else "degrade"))
    if snap_meta.get("cache") == "memory":
        degrade_record(dbg, "SNAPSHOT_MEMORY_CACHE", {}, severity=("warn" if _is_non_trading else "degrade"))
    if snap_meta.get("cache") == "disk":
        degrade_record(dbg, "SNAPSHOT_DISK_CACHE", {"age_sec": snap_meta.get("cache_age_sec")}, severity=("warn" if _is_non_trading else "degrade"))
    if bool(snap_meta.get("fallback")):
        # Treat fallback as a warning in trading sessions to avoid over-blocking
        degrade_record(dbg, "SNAPSHOT_FALLBACK", {"to": snap_meta.get("source"), "reason": snap_meta.get("fallback_reason")}, severity="warn")
    if snap_meta.get("skipped_routes"):
        degrade_record(dbg, "SNAPSHOT_ROUTE_SKIPPED", {"routes": snap_meta.get("skipped_routes")}, severity=("warn" if _is_non_trading else "degrade"))
    if snapshot_df is None:
        degrade_record(dbg, "ENV_NEUTRALIZED", {}, severity=("warn" if _is_non_trading else "degrade"))
        degrade_record(dbg, "THEMES_EMPTY", {}, severity=("warn" if _is_non_trading else "degrade"))
        degrade_record(dbg, "MARKET_STATS_MISSING", {}, severity=("warn" if _is_non_trading else "degrade"))

    # Structured cleanliness check (do not rely on source text)
    def _is_clean_live_snapshot(meta: Dict[str, Any]) -> bool:
        try:
            # 非交易日放宽门槛：不因为缓存/回退/路线跳过而判定为不干净
            try:
                from datetime import datetime as _dt
                from .calendar import is_trading_day as _is_td  # weekday Mon-Fri
                if not _is_td(_dt.now()):
                    return True
            except Exception:
                pass
            if meta.get("missing") is True:
                return False
            # Relax: cache/fallback/route-skipped no longer mark snapshot unclean on trading days
            if meta.get("stale") is True:
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
    # BARS_TOO_SHORT: degrade only when ratio exceeds threshold; else warn
    try:
        short_ct = int(cand_stats.get("bars_too_short_count", 0) or 0)
        uni_ct = int(cand_stats.get("universe_after_filter_count", 0) or 0)
        ratio = (float(short_ct) / float(max(1, uni_ct))) if uni_ct else 0.0
        ratio_thr = float(os.getenv("GP_BARS_TOO_SHORT_WARN_RATIO", "0.3"))
        severity = "degrade" if ratio >= ratio_thr else "warn"
        if short_ct > 0:
            degrade_record(dbg, "BARS_TOO_SHORT", {"count": short_ct, "ratio": round(ratio, 3), "thr": ratio_thr}, severity=severity)
    except Exception:
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
    # Only block when blocking degrade codes present; else allow with warnings
    if tradeable:
        try:
            blk_env = os.getenv("GP_BLOCKING_DEGRADE_CODES", "SNAPSHOT_MISSING,MAINLINE_FILTERED_ALL,UNIVERSE_TOO_SMALL,CANDIDATE_TOO_SMALL")
            blocking = {c.strip() for c in blk_env.split(',') if c.strip()}
        except Exception:
            blocking = {"SNAPSHOT_MISSING", "MAINLINE_FILTERED_ALL", "UNIVERSE_TOO_SMALL", "CANDIDATE_TOO_SMALL"}
        present = {str(x.get("reason_code")) for x in (dbg.get("degrade_reasons") or [])}
        if blocking & present:
            degrade_record(dbg, "INSUFFICIENT_EVIDENCE_TRADEABLE", {"reason": "blocking_degrade_present", "blocking": sorted(list(blocking & present))})
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
    # Post-strict empty classification
    try:
        if isinstance(payload.get("picks"), list) and len(payload["picks"]) == 0:
            dropped = (payload.get("debug", {}) or {}).get("dropped_picks") or []
            if dropped:
                degrade_record(dbg, "STRICT_DROPPED_ALL", {"dropped": len(dropped)})
            else:
                # champion/trade plan missing only if strategies actually evaluated
                try:
                    _sym_eval_cnt = int((dbg.get("strategy_eval_counts") or {}).get("symbols", 0))
                except Exception:
                    _sym_eval_cnt = 0
                if _sym_eval_cnt > 0:
                    degrade_record(dbg, "NO_EXECUTABLE_AFTER_CHAMPION", {})
    except Exception:
        pass

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
    # Strategy evaluation counters (rough)
    try:
        total_syms = int(len(pool))
        total_strats = int(len(getattr(strat_lib, "REGISTRY", {}) or {}))
        dbg.setdefault("strategy_eval_counts", {})
        dbg["strategy_eval_counts"].update({
            "symbols": total_syms,
            "strategies": total_strats,
        })
    except Exception:
        pass
    payload["data_status"] = {"snapshot": ds_snapshot, "themes": ds_themes, "daily": ds_daily, "mainline": ds_mainline}

    _write_outputs(as_of, payload)
    return payload
