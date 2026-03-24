from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# Keep tests hermetic: prefer real-data off to avoid network in CI
os.environ.setdefault("STRICT_REAL_DATA", "1")
os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("GP_CACHE_REFRESH_TTL_SEC", "300")


def _mk_df(dates: List[pd.Timestamp]) -> pd.DataFrame:
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100.0,
                "amount": 150.0,
            }
        )
    return pd.DataFrame(rows)


def test_marketdatahub_rollover_forces_incremental(monkeypatch):
    # Lazy imports to ensure env vars are in place
    import gp_assistant.recommend.datahub as dh

    # In-memory history_store stubs
    store_q: Dict[str, Dict[str, Any]] = {}
    store_items: Dict[str, List[Dict[str, Any]]] = {}

    def _ensure_query(qid: str, params: Dict[str, Any]) -> None:
        store_q.setdefault(qid, {"params": params, "last_fetch_at": None, "last_item_time": None})

    def _query_meta(qid: str) -> Dict[str, Any]:
        q = store_q.get(qid) or {}
        return {
            "id": qid,
            "params": q.get("params"),
            "created_at": None,
            "updated_at": None,
            "last_fetch_at": q.get("last_fetch_at"),
            "last_item_time": q.get("last_item_time"),
        }

    def _count_items(qid: str, *, since: Optional[str] = None) -> int:
        return len(store_items.get(qid) or [])

    def _list_items(qid: str, *, since: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        rows = store_items.get(qid) or []
        if since is not None:
            rows = [r for r in rows if (r.get("item_time") or "") >= since]
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def _upsert_items(
        qid: str,
        items: List[Dict[str, Any]],
        *,
        id_key: str = "id",
        time_key: str = "time",
        etag_key: Optional[str] = None,
        payload_mapper=None,
    ) -> Dict[str, Any]:
        lst = store_items.setdefault(qid, [])
        byid = {r["item_id"]: r for r in lst}
        for it in items:
            iid = str(it.get(id_key))
            t = str(it.get(time_key))
            payload = payload_mapper(it) if payload_mapper else it
            r = {"item_id": iid, "item_time": t, "etag": None, "payload": payload, "updated_at": datetime.now().isoformat()}
            byid[iid] = r
            store_q.setdefault(qid, {})["last_item_time"] = t
            store_q.setdefault(qid, {})["last_fetch_at"] = datetime.now().isoformat()
        lst[:] = sorted(byid.values(), key=lambda x: x["item_time"])
        return {"query_id": qid, "total": len(items), "inserted": len(items), "updated": 0, "last_item_time": store_q[qid]["last_item_time"]}

    def _compute_next_range(qid: str, *, user_start: Optional[str] = None, user_end: Optional[str] = None, safety_lookback_days: int = 2) -> Tuple[Optional[str], Optional[str]]:
        # Simple passthrough: rely on provider date filtering
        return user_start, user_end

    # Monkeypatch history_store symbols inside datahub module
    monkeypatch.setattr(dh, "ensure_query", _ensure_query)
    monkeypatch.setattr(dh, "_query_meta", _query_meta)
    monkeypatch.setattr(dh, "_count_items", _count_items)
    monkeypatch.setattr(dh, "_list_items", _list_items)
    monkeypatch.setattr(dh, "upsert_items", _upsert_items)
    monkeypatch.setattr(dh, "compute_next_range", _compute_next_range)

    # Provide a simple trade calendar: mark all days open
    def _fake_load_trade_calendar():
        today = pd.Timestamp.now().normalize()
        dates = pd.date_range(today - pd.Timedelta(days=10), today, freq="D")
        return pd.DataFrame({"cal_date": [d.strftime("%Y%m%d") for d in dates], "is_open": [1] * len(dates)})

    monkeypatch.setattr(dh, "_load_trade_calendar", _fake_load_trade_calendar)

    # Fake provider
    class FakeProvider:
        name = "fake"

        def get_daily(self, symbol: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:  # noqa: D401
            ed = pd.to_datetime(end or pd.Timestamp.now().normalize())
            sd = (ed - pd.Timedelta(days=5)) if start is None else pd.to_datetime(start)
            days = pd.date_range(sd, ed, freq="D")
            return _mk_df(list(days))

    monkeypatch.setattr(dh, "get_provider", lambda: FakeProvider())

    # Prepare hub and simulate cache state: last_item_time is yesterday, last_fetch_at is recent (so TTL would block refresh)
    hub = dh.MarketDataHub()
    today = pd.Timestamp.now().normalize()
    as_of = today.date().isoformat()

    # Pre-create query meta + stale last_item_time
    qid = dh.canonical_query_id({"kind": "daily", "symbol": "600519", "provider": "fake"})
    _ensure_query(qid, {"kind": "daily", "symbol": "600519", "provider": "fake"})
    store_q[qid]["last_item_time"] = (today - pd.Timedelta(days=1)).date().isoformat()
    store_q[qid]["last_fetch_at"] = datetime.now().isoformat()  # within TTL

    df, meta = hub.daily_ohlcv("600519", as_of=as_of, min_len=0, prefer_cache_only=False)

    assert isinstance(df, pd.DataFrame) and len(df) > 0
    # Should have forced rollover despite TTL
    assert bool(meta.get("rollover_forced")) is True
    assert str(pd.to_datetime(df["date"].iloc[-1]).date()) == as_of


def test_chat_tool_stale_refresh(monkeypatch):
    from gp_assistant.chat.agent_tools import t_get_ohlcv

    today = pd.Timestamp.now().normalize()
    yesterday = today - pd.Timedelta(days=1)

    # Fake hub behavior: cache-only -> yesterday; network -> today
    class FakeHub:
        def daily_ohlcv(self, symbol: str, as_of=None, min_len: int = 0, *, prefer_cache_only: bool = False):  # noqa: ANN001
            if prefer_cache_only:
                df = _mk_df([yesterday])
                return df, {"source": "store:daily:fake"}
            df2 = _mk_df([today])
            return df2, {"source": "store+network_merge", "rollover_forced": True}

    import gp_assistant.chat.agent_tools as at

    monkeypatch.setattr(at, "MarketDataHub", lambda: FakeHub())

    r = t_get_ohlcv({"symbol": "600519", "limit": 10, "as_of": today.date().isoformat()}, _state=None)
    assert r.ok
    data = r.data or {}
    bars = data.get("bars") or []
    assert bars and bars[-1]["date"] == today.date().isoformat()

