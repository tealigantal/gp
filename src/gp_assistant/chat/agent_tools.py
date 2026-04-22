from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

from ..selection_engine.datahub import MarketDataHub


@dataclass
class ToolResult:
    ok: bool
    data: Dict[str, Any]
    error: str | None = None


def t_get_ohlcv(args: Dict[str, Any], _state: Any = None) -> ToolResult:
    symbol = str((args or {}).get("symbol") or "")
    limit = int((args or {}).get("limit") or 10)
    as_of = (args or {}).get("as_of")
    hub = MarketDataHub()
    df, meta = hub.daily_ohlcv(symbol, as_of=as_of, min_len=0, prefer_cache_only=False)
    bars: List[Dict[str, Any]] = []
    if isinstance(df, pd.DataFrame) and not df.empty:
        tail = df.tail(limit).copy()
        if "date" in tail.columns:
            tail["date"] = tail["date"].astype(str)
        bars = tail.to_dict(orient="records")
    return ToolResult(ok=True, data={"symbol": symbol, "bars": bars, "meta": meta})
