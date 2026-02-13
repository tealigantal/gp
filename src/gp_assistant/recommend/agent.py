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
from .candidate_gen import generate_candidates
from ..providers.factory import get_provider

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

    # 数据阶段：快照（Spot Snapshot）
    # Fetch snapshot once and share within this run (degrade to None if unavailable)
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
    snapshot_df: Optional[pd.DataFrame]
    snap_meta: Dict[str, Any]
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
    env = score_regime(hub, snapshot=snapshot_df)
    themes = build_themes(hub, snapshot=snapshot_df)

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
            out[str(sid)] = {"cv": cv_dict, "event": ev_dict}
        return out

    def _trade_plan_from_strategy(mod: Any, df_feat: pd.DataFrame, pick: Dict[str, Any], q_grade: Optional[str]) -> Dict[str, Any]:
        bands: Dict[str, float] = {}
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
        try:
            kb = getattr(mod, "key_bands", None)
            if callable(kb) and setup is not None:
                bands = kb(df_feat, setup) or {}
        except Exception:
            bands = {}
        if not bands:
            chip = pick.get("chip", {}) or {}
            try:
                low = float(chip.get("band_90_low", 0.0))
                high = float(chip.get("band_90_high", 0.0))
                mid = float(chip.get("avg_cost", 0.0)) or ((low + high) / 2.0 if (low and high) else 0.0)
                bands = {"S1": low, "S2": mid, "R1": high, "R2": (high * 1.02 if high else 0.0)}
            except Exception:
                bands = {}
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
        return {"bands": bands, "actions": actions, "invalidation": invalid, "risk": risk}

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
            "theme": themes[0]["name"] if themes else "行业轮动",
            "flags": cand.get("flags", {}),
            "chip": cand.get("chip", {}),
            "indicators": cand.get("indicators", {}),
        }
        champ = champions.get(sym) if isinstance(champions, dict) else None
        if champ:
            it["champion"] = champ
            mod = (strat_lib.REGISTRY or {}).get(str(champ.get("strategy")))
            feat = feats_by_symbol.get(sym)
            if mod is not None and feat is not None:
                it["trade_plan"] = _trade_plan_from_strategy(mod, feat, cand, q_grade=(cand.get("q_grade") or cand.get("indicators", {}).get("q_grade")))
        picks.append(it)
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
            degrade_record(dbg, "UNIVERSE_DIRTY_INPUT", rem)
    except Exception:
        pass

    # Finalize tradeable
    tradeable = not dbg.get("degraded") and _is_clean_live_snapshot(snap_meta) \
        and cand_stats.get("universe_after_filter_count", 0) >= getattr(cfg, "tradeable_min_universe", 50) \
        and cand_stats.get("candidates_out_count", 0) >= getattr(cfg, "tradeable_min_candidates", 20)
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

    _write_outputs(as_of, payload)
    return payload
