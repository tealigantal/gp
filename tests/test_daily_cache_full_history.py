import os
from datetime import datetime, timedelta
import time
from pathlib import Path

import pandas as pd


def _mk_df(start_date: str, days: int) -> pd.DataFrame:
    base = datetime.fromisoformat(start_date)
    rows = []
    for i in range(days):
        d = (base + timedelta(days=i)).date().isoformat()
        rows.append({
            "date": d,
            "open": 10 + i * 0.01,
            "high": 10.5 + i * 0.01,
            "low": 9.5 + i * 0.01,
            "close": 10.2 + i * 0.01,
            "volume": 1_000_000 + i,
            "amount": (10.2 + i * 0.01) * (1_000_000 + i),
        })
    return pd.DataFrame(rows)


class FakeProvider:
    name = "fake"

    def __init__(self, incremental_start: str, inc_days: int):
        self.incremental_start = incremental_start
        self.inc_days = inc_days

    def get_daily(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:  # noqa: D401
        # Return only incremental slice regardless of start/end
        return _mk_df(self.incremental_start, self.inc_days)

    def get_daily_batch(self, symbols, start, end):  # noqa: ANN001
        return {s: self.get_daily(s, start, end) for s in symbols}

    def healthcheck(self):  # noqa: D401
        return {"ok": True}


def test_daily_cache_merges_full_history(monkeypatch):
    # Isolate store dir (avoid system temp dir on Windows)
    base = Path.cwd() / f"store_test_{int(time.time())}"
    os.environ["GP_STORE_DIR"] = str(base)

    # Pre-populate cache with 300 rows (history)
    from gp_assistant.search.history_store import canonical_query_id, ensure_query, upsert_items
    qid = canonical_query_id({"kind": "daily", "symbol": "000001", "provider": "fake"})
    ensure_query(qid, {"kind": "daily", "symbol": "000001", "provider": "fake"})
    hist_df = _mk_df("2020-01-01", 300)
    items = []
    for _, r in hist_df.iterrows():
        d = str(r["date"])
        items.append({
            "id": d,
            "date": d,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
            "amount": float(r["amount"]),
        })
    upsert_items(qid, items, id_key="id", time_key="date", etag_key=None)

    # Fake provider returns only 2 incremental rows beyond watermark
    fake = FakeProvider(incremental_start="2020-10-27", inc_days=2)

    from gp_assistant.providers import factory as pf
    monkeypatch.setattr(pf, "get_provider", lambda prefer=None: fake, raising=True)

    from gp_assistant.selection_engine.datahub import MarketDataHub
    hub = MarketDataHub()

    df, meta = hub.daily_ohlcv("000001", as_of=None, min_len=250)

    # Cache should contain history+incremental, not just 2 rows
    assert isinstance(df, pd.DataFrame)
    assert len(df) >= 300  # 300 history + up to 2 new (minus any de-dup)
    assert meta.get("len") == len(df)
    assert meta.get("insufficient_history") is False
    # Ensure provenance indicates store/network merge when network attempted
    assert str(meta.get("source", "")).startswith("store")
