# 简介：工具 - 回测入口/辅助，提供简单策略回放与结果导出。
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
from pathlib import Path
import json
import hashlib
import pandas as pd
try:
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None  # type: ignore

from ..core.types import ToolResult
from ..core.paths import store_dir, configs_dir


@dataclass
class StrategyDef:
    id: str
    name: str
    enabled: bool = True
    event_rule: Dict[str, Any] | None = None  # {name: str, params: dict}
    lookback_days: int = 250
    forward_days: List[int] | None = None  # e.g., [2,5,10]
    min_samples: int = 5


@dataclass
class BacktestStats:
    symbol: str
    strategy_id: str
    as_of_date: str
    k: int
    win_rate_2: float
    win_rate_5: float
    win_rate_10: float
    avg_return_2: float
    avg_return_5: float
    avg_return_10: float
    mdd10_avg: float
    sample_warning: bool
    data_hash: str


def _default_strategies() -> List[StrategyDef]:
    return [
        StrategyDef(
            id="S1",
            name="Bias6 CrossUp",
            enabled=True,
            event_rule={"name": "bias6_cross_up", "params": {}},
            lookback_days=250,
            forward_days=[2, 5, 10],
            min_samples=5,
        )
    ]


def load_strategies(config=None) -> List[StrategyDef]:  # noqa: ANN401
    fp = configs_dir() / "strategies.yaml"
    if not fp.exists():
        return _default_strategies()
    if yaml is None:
        return _default_strategies()
    try:
        cfg = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    except Exception:
        return _default_strategies()
    items: List[StrategyDef] = []
    for it in cfg.get("strategies", []):
        items.append(
            StrategyDef(
                id=str(it.get("id", "S1")),
                name=str(it.get("name", "Strategy")),
                enabled=bool(it.get("enabled", True)),
                event_rule=it.get("event_rule") or {"name": "bias6_cross_up", "params": {}},
                lookback_days=int(it.get("lookback_days", it.get("params", {}).get("lookback_days", 250))),
                forward_days=list(it.get("forward_days", [2, 5, 10])),
                min_samples=int(it.get("min_samples", 5)),
            )
        )
    if not items:
        items = _default_strategies()
    return items


def _event_mask(df_feat: pd.DataFrame, strategy: StrategyDef) -> pd.Series:
    name = (strategy.event_rule or {}).get("name", "bias6_cross_up")
    if name == "bias6_cross_up":
        return df_feat.get("bias6_cross_up", pd.Series(False, index=df_feat.index)).astype(bool)
    # Fallback: no events
    return pd.Series(False, index=df_feat.index)


def _data_hash(df_feat: pd.DataFrame) -> str:
    last_date = str(df_feat["date"].iloc[-1]) if "date" in df_feat.columns and len(df_feat) else ""
    payload = f"{len(df_feat)}|{last_date}|{float(df_feat['close'].iloc[-1]) if len(df_feat) else 0.0}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def run_event_backtest(df_feat: pd.DataFrame, strategy: StrategyDef, config=None) -> BacktestStats:  # noqa: ANN401
    as_of = pd.to_datetime(df_feat["date"].iloc[-1]).strftime("%Y-%m-%d") if len(df_feat) else ""
    mask = _event_mask(df_feat, strategy)
    idxs = list(df_feat.index[mask])
    fds = strategy.forward_days or [2, 5, 10]
    returns: dict[int, list[float]] = {n: [] for n in fds}
    mdds: list[float] = []
    for i in idxs:
        t1 = i + 1
        if t1 >= len(df_feat):
            continue
        entry = float(df_feat.loc[t1, "close"])  # proxy: next close
        horizon = min(10, len(df_feat) - t1 - 1)
        if horizon <= 0:
            continue
        future = df_feat.loc[t1 : t1 + horizon, "close"].astype(float)
        rel = future / entry
        mdd = float(rel.min() - 1.0)
        mdds.append(mdd)
        for n in fds:
            tN = t1 + n
            if tN < len(df_feat):
                r = float(df_feat.loc[tN, "close"]) / entry - 1.0
                returns[n].append(r)
    k = min((len(v) for v in returns.values()), default=0)

    def win_rate(lst: list[float]) -> float:
        if not lst:
            return 0.0
        return float(sum(1 for x in lst if x > 0) / len(lst))

    stats = BacktestStats(
        symbol=str(df_feat.attrs.get("symbol", "UNKNOWN")),
        strategy_id=str(strategy.id),
        as_of_date=as_of,
        k=int(k),
        win_rate_2=win_rate(returns.get(2, [])),
        win_rate_5=win_rate(returns.get(5, [])),
        win_rate_10=win_rate(returns.get(10, [])),
        avg_return_2=float(pd.Series(returns.get(2, [])).mean() if returns.get(2) else 0.0),
        avg_return_5=float(pd.Series(returns.get(5, [])).mean() if returns.get(5) else 0.0),
        avg_return_10=float(pd.Series(returns.get(10, [])).mean() if returns.get(10) else 0.0),
        mdd10_avg=float(pd.Series(mdds).mean() if mdds else 0.0),
        sample_warning=bool(int(k) < (strategy.min_samples or 5)),
        data_hash=_data_hash(df_feat),
    )
    return stats


def _cache_path(symbol: str, strategy_id: str, as_of_date: str, data_hash: str) -> Path:
    key = f"{symbol}_{strategy_id}_{as_of_date}_{data_hash[:8]}"
    return store_dir() / "backtest" / f"{key}.json"


def save_stats(stats: BacktestStats) -> None:
    p = _cache_path(stats.symbol, stats.strategy_id, stats.as_of_date, stats.data_hash)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(stats.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


def run_backtest(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    strategy_id = args.get("strategy") or "S1"
    return ToolResult(
        ok=False,
        message=f"回测请使用 CLI: python -m gp_assistant backtest --strategy {strategy_id}",
        data=None,
    )
