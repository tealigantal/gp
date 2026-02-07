from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .schemas import StrategyRunResult, StrategySelection, SelectedStrategy


@dataclass
class StrategySpec:
    id: str
    name: str
    tags: List[str]
    risk_profile: List[str]  # conservative | neutral | aggressive


DEFAULT_STRATEGIES: List[StrategySpec] = [
    StrategySpec(id="momentum_v1", name="动量V1", tags=["trend", "high_vol"], risk_profile=["neutral", "aggressive"]),
    StrategySpec(id="pullback_v1", name="回踩V1", tags=["range", "low_vol"], risk_profile=["conservative", "neutral"]),
    StrategySpec(id="defensive_v1", name="防御V1", tags=["low_vol"], risk_profile=["conservative"]),
]


def _load_appcfg(repo_root: Path):
    # Lazy import to avoid heavy imports on module load
    from src.gpbt.config import AppConfig
    p = Path(repo_root) / "configs" / "config.yaml"
    if p.exists():
        try:
            return AppConfig.load(str(p))
        except Exception:
            pass
    # Fallback minimal
    cfg = AppConfig(
        provider="local_files",
        paths=AppConfig.Paths.from_dict if False else None,  # type: ignore
        fees=None, universe=None, bars=None, experiment=None,  # type: ignore
    )
    # Above dummy path is not used; callers should supply proper cfg in tests
    return None


def screen_strategies(user_profile: Dict[str, Any], market_style: Optional[str] = None, use_llm: bool = False) -> StrategySelection:
    risk = (user_profile.get("risk_level") or "neutral").lower()
    style_pref = (user_profile.get("style_preference") or market_style or "").lower()
    sel: List[SelectedStrategy] = []
    for s in DEFAULT_STRATEGIES:
        if risk not in s.risk_profile:
            continue
        if style_pref and style_pref not in s.tags:
            # initial strict filter
            continue
        sel.append(SelectedStrategy(strategy_id=s.id, reason=f"match risk={risk}, style={style_pref or 'n/a'}", tags=s.tags))
    # If none after strict filter, relax by risk only
    if not sel:
        for s in DEFAULT_STRATEGIES:
            if risk in s.risk_profile:
                sel.append(SelectedStrategy(strategy_id=s.id, reason=f"match risk={risk}, relaxed style", tags=s.tags))
    rationale = f"rule-screen: risk={risk}, style_pref={style_pref or 'n/a'}"
    return StrategySelection(selected=sel, rationale=rationale)


def _read_daily(repo_root: Path, ts_code: str) -> pd.DataFrame:
    from src.gpbt.storage import daily_bar_path, load_parquet
    p = daily_bar_path(Path(repo_root) / "data", ts_code)
    df = load_parquet(p)
    if not df.empty:
        df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def _simple_next_day_return(repo_root: Path, ts_code: str, date: str) -> Optional[float]:
    df = _read_daily(repo_root, ts_code)
    if df.empty:
        return None
    ddf = df[df["trade_date"].astype(str) <= date].sort_values("trade_date")
    if len(ddf) < 2:
        return None
    # Buy at next open after date; sell same day close (approx)
    today = ddf.iloc[-1]
    prev = ddf.iloc[-2]
    # If date equals last row date, approximate next-day return by close/prev_close - 1
    try:
        ret = float(today["close"]) / float(prev["close"]) - 1.0
        return ret
    except Exception:
        return None


def run_strategy(repo_root: Path, strategy_id: str, end_date: str, topk: int = 3) -> Tuple[StrategyRunResult, List[Dict[str, Any]]]:
    """Run single strategy:
    - Use gpbt llm_ranker (which has provider-aware mock fallback) to pick topK
    - Compute naive next-day returns as a proxy metrics
    - Persist run results is handled by pipeline orchestrator
    Returns (run_result, picks)
    """
    provider = "mock"
    picks: List[Dict[str, Any]] = []
    try:
        from src.gpbt.config import AppConfig, Paths, Fees, UniverseCfg, BarsCfg, ExperimentCfg
        from src.gpbt.rankers.llm_ranker import rank as llm_rank
        # Load or synthesize config
        cfg_path = Path(repo_root) / "configs" / "config.yaml"
        if cfg_path.exists():
            appcfg = AppConfig.load(str(cfg_path))
        else:
            appcfg = AppConfig(
                provider="local_files",
                paths=Paths(data_root=Path(repo_root) / "data", universe_root=Path(repo_root) / "universe", results_root=Path(repo_root) / "results"),
                fees=Fees(), universe=UniverseCfg(), bars=BarsCfg(), experiment=ExperimentCfg(run_id="pipeline"),
            )
        df = llm_rank(appcfg, end_date, strategy_id, force=True, topk=topk)
        for _, r in df.iterrows():
            picks.append({
                "trade_date": end_date,
                "rank": int(r.get("rank", 0)),
                "ts_code": str(r.get("ts_code")),
                "score": float(r.get("score", 0.0)),
                "confidence": float(r.get("confidence", 0.5)),
                "reasons": str(r.get("reasons", "")),
                "risk_flags": str(r.get("risk_flags", "")),
            })
        provider = "llm"  # llm_ranker may use mock provider under the hood
    except Exception:
        # fallback: try to read candidate_pool and pick first topk
        provider = "mock"
        pool_file = Path(repo_root) / "universe" / f"candidate_pool_{end_date}.csv"
        if pool_file.exists():
            try:
                import pandas as _pd
                pool_df = _pd.read_csv(pool_file)
                codes = [str(x) for x in pool_df["ts_code"].astype(str).tolist()[: topk]]
                for i, ts in enumerate(codes, start=1):
                    picks.append({"trade_date": end_date, "rank": i, "ts_code": ts, "score": 0.0, "confidence": 0.3, "reasons": "mock pool order", "risk_flags": ""})
            except Exception:
                pass

    # Evaluate naive metrics
    rets: List[float] = []
    for p in picks:
        r = _simple_next_day_return(Path(repo_root), str(p.get("ts_code")), end_date)
        if r is not None:
            rets.append(r)
    avg_ret = float(sum(rets) / len(rets)) if rets else 0.0
    win_rate = float(sum(1 for x in rets if x > 0) / len(rets)) if rets else 0.0
    run = StrategyRunResult(
        provider=provider,
        strategy_id=strategy_id,
        name=strategy_id,
        tags=[t for s in DEFAULT_STRATEGIES if s.id == strategy_id for t in s.tags],
        period={"start": end_date, "end": end_date},
        metrics={"win_rate": win_rate, "avg_return": avg_ret, "max_drawdown": 0.0, "turnover": 0.0},
        notes="naive next-day return proxy",
        picks=picks,
    )
    return run, picks


def judge_champion(market_style: Optional[str], runs: List[StrategyRunResult]) -> Tuple[StrategyRunResult, str]:
    # rule-based scoring
    style = (market_style or "").lower()
    best = None
    best_score = -1e9
    why = ""
    for r in runs:
        wr = float(r.metrics.get("win_rate", 0.0))
        ar = float(r.metrics.get("avg_return", 0.0))
        md = float(r.metrics.get("max_drawdown", 0.0))
        sm = 0.1
        if style and any(style in t for t in r.tags):
            sm = 0.2
        score = 0.6 * wr + 0.4 * ar - 0.1 * md + sm
        if score > best_score:
            best_score = score
            best = r
            why = f"rule: wr={wr:.2f}, ar={ar:.3f}, md={md:.3f}, style_bonus={sm:.2f}"
    assert best is not None
    return best, why

