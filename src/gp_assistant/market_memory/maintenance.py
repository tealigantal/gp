"""Worker-owned mature evidence maintenance. No network or publication writes."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json
import signal
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

from ..application.history_daily import frames
from ..core.paths import store_dir
from ..signal_engine.daily import build_signal_events_for_symbol
from ..search.history_store import note_cleanup_error
from .store import upsert_market_events, _db_path

POLICY = "mature_breadth_v2_committed"


def contexts(history: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """Observed breadth of the explicitly bound cohort, with no future rows."""
    observations = []
    for symbol, frame in history.items():
        required = {"date", "open", "high", "low", "close", "volume", "amount"}
        if not required.issubset(frame.columns):
            raise ValueError(f"memory_missing_columns:{symbol}")
        numeric = frame[list(required - {"date"})].apply(pd.to_numeric, errors="raise")
        if not np.isfinite(numeric.to_numpy()).all() or (numeric[["open","high","low","close"]] <= 0).any().any() or (numeric[["volume","amount"]] < 0).any().any():
            raise ValueError(f"memory_invalid_bar:{symbol}")
        days = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        if days.duplicated().any() or not days.is_monotonic_increasing:
            raise ValueError(f"memory_unordered_bars:{symbol}")
        close = numeric["close"]
        average = close.rolling(20, min_periods=20).mean()
        observations.extend((day, bool(value > ma)) for day, value, ma in zip(days, close, average) if pd.notna(ma))
    buckets: dict[str, list[bool]] = {}
    for day, above in observations:
        buckets.setdefault(day, []).append(above)
    return {day: {"market_regime": "A" if sum(v)/len(v) >= .65 else "B" if sum(v)/len(v) >= .5 else "C" if sum(v)/len(v) >= .35 else "D",
                  "breadth_above_ma20": sum(v)/len(v), "observed_symbols": len(v),
                  "context_source": "date_truncated_bound_cohort"} for day, v in buckets.items()}


def _connection():
    conn = sqlite3.connect(store_dir() / "memory_maintenance.db", timeout=15)
    conn.execute("CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, target TEXT NOT NULL, policy TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL, error TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS symbols(run_id TEXT NOT NULL, symbol TEXT NOT NULL, inserted INTEGER NOT NULL, PRIMARY KEY(run_id,symbol))")
    conn.commit()
    return conn


def identity(target: str, symbols: tuple[str, ...], expected: tuple[str, ...]) -> str:
    return sha256(json.dumps([POLICY, target, sorted(symbols), sorted(expected)]).encode()).hexdigest()


def maintain(*, target: str, symbols: tuple[str, ...], now: datetime, expected: tuple[str, ...] | None = None) -> dict:
    from ..application.market_runs import MarketRunStore
    from ..search.history_store import note_cleanup_error
    import sys
    owner = MarketRunStore(store_dir() / "market_runs.db")
    clock = lambda: datetime.now(now.tzinfo)
    token = owner.acquire_lease(name="mature-memory", now=clock(), lease_sec=300)
    if token is None:
        raise RuntimeError("memory_lease_held")
    try:
        return _maintain(target=target, symbols=symbols, expected=expected, now=now,
            heartbeat=lambda: owner.heartbeat_lease(name="mature-memory", token=token, now=clock(), lease_sec=300))
    finally:
        primary = sys.exc_info()[1]
        try:
            owner.release_lease(name="mature-memory", token=token)
        except Exception as exc:
            if primary is None:
                raise
            note_cleanup_error(primary, f"memory lease release failed: {exc}")


def _maintain(*, target: str, symbols: tuple[str, ...], now: datetime, expected: tuple[str, ...] | None = None, heartbeat=None) -> dict:
    expected = symbols if expected is None else expected
    scope_id = identity(target, symbols, expected)
    # One read transaction, complete expected coverage, then immutable inputs.
    history = frames(list(symbols), limit=220, as_of=target, minimum_rows=1)
    if set(history) != set(symbols):
        raise ValueError("memory_missing_history:" + ",".join(sorted(set(symbols)-set(history))))
    missing = [s for s in expected if str(history[s].iloc[-1]["date"])[:10] != target]
    if missing:
        raise ValueError("memory_target_coverage_incomplete:" + ",".join(missing))
    market = contexts(history)
    digest = sha256()
    for symbol in sorted(history):
        digest.update(symbol.encode())
        digest.update(history[symbol].to_json(orient="split", double_precision=15).encode())
    input_digest = digest.hexdigest()
    run_id = sha256(f"{scope_id}:{input_digest}".encode()).hexdigest()
    conn = _connection()
    try:
        prior = conn.execute("SELECT state,payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if prior and prior[0] == "complete":
            return json.loads(prior[1])
        payload = {"run_id": run_id, "scope_id": scope_id, "input_digest": input_digest,
                   "target": target, "policy": POLICY, "total": len(symbols), "state": "building"}
        conn.execute("INSERT INTO runs VALUES(?,?,?,?,?,NULL) ON CONFLICT(run_id) DO UPDATE SET state='building',error=NULL", (run_id,target,POLICY,"building",json.dumps(payload)))
        conn.commit()
        completed = {r[0] for r in conn.execute("SELECT symbol FROM symbols WHERE run_id=?", (run_id,))}
        committed_runs = {r[0] for r in conn.execute("SELECT run_id FROM runs WHERE state='complete'")}
        for symbol in symbols:
            if heartbeat is not None and not heartbeat():
                raise RuntimeError("memory_lease_lost")
            if symbol in completed:
                continue
            frame = history[symbol]
            # Insufficient-history listings contribute no fabricated cases.
            result = build_signal_events_for_symbol(symbol=symbol, df=frame, as_of=target,
                market_context=market[str(frame.iloc[-1]["date"])[:10]] if len(frame) >= 20 else {},
                historical_market_context_resolver=lambda day: market[day], max_history=120)
            events = []
            prior_days = set()
            prior_ids = {}
            event_path = _db_path()
            if event_path.exists():
                reader = sqlite3.connect(event_path.resolve().as_uri()+"?mode=ro", uri=True)
                try:
                    for old_id, day, provenance_json in reader.execute("SELECT event_id,signal_trading_day,data_provenance_json FROM market_events WHERE symbol=?", (symbol,)):
                        provenance = json.loads(provenance_json)
                        if provenance.get("memory_policy") != POLICY:
                            continue
                        prior_ids[old_id] = provenance.get("maintenance_run")
                        if provenance.get("maintenance_run") in committed_runs:
                            prior_days.add(day)
                finally:
                    reader.close()
            for event in result.historical_events:
                if not event.outcome_complete or not event.outcome_available_trading_day or event.outcome_available_trading_day >= target:
                    continue
                if event.signal_trading_day in prior_days:
                    continue
                # One first-observed case per policy/symbol/signal date. Moving
                # indicator windows never multiply the same historical outcome.
                content = json.dumps([POLICY,symbol,event.signal_trading_day])
                event_id = sha256(content.encode()).hexdigest()
                if event_id in prior_ids and prior_ids[event_id] != run_id:
                    # Preserve abandoned staged versions; new input gets a new
                    # version until one complete batch establishes first-seen.
                    event_id = sha256(f"{event_id}:{run_id}".encode()).hexdigest()
                events.append(replace(event, event_id=event_id, first_seen_at=datetime.now(now.tzinfo).isoformat(),
                    data_provenance={**event.data_provenance,"memory_policy":POLICY,"maintenance_run":run_id,"input_digest":input_digest,"cohort_context":"reconstructed_bound_universe"}))
            inserted = upsert_market_events(events)
            conn.execute("INSERT INTO symbols VALUES(?,?,?)", (run_id,symbol,inserted))
            conn.commit()
            completed.add(symbol)
            if len(completed) % 100 == 0:
                print(json.dumps({"memory_progress": {"target":target,"completed":len(completed),"total":len(symbols)} }),flush=True)
        if heartbeat is not None and not heartbeat():
            raise RuntimeError("memory_lease_lost")
        payload.update(state="complete", completed=len(completed), context=market[target], completed_at=datetime.now(now.tzinfo).isoformat())
        conn.execute("UPDATE runs SET state='complete',payload=?,error=NULL WHERE run_id=?", (json.dumps(payload),run_id))
        conn.commit()
        return payload
    except Exception as exc:
        try:
            conn.execute("UPDATE runs SET state='failed',error=? WHERE run_id=? AND state!='complete'", (f"{type(exc).__name__}:{exc}",run_id))
            conn.commit()
        except Exception as secondary:
            note_cleanup_error(exc, f"memory failure persistence failed: {secondary}")
        raise
    finally:
        primary = sys.exc_info()[1]
        try:
            conn.close()
        except Exception as secondary:
            if primary is None:
                raise
            note_cleanup_error(primary, f"memory connection close failed: {secondary}")


def ready(target: str, symbols: tuple[str, ...], expected: tuple[str, ...]) -> dict:
    path = store_dir() / "memory_maintenance.db"
    if not path.exists():
        raise ValueError("mature_memory_pending")
    conn = sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
    try:
        row = conn.execute("SELECT payload FROM runs WHERE json_extract(payload,'$.scope_id')=? AND state='complete' ORDER BY rowid DESC LIMIT 1", (identity(target,symbols,expected),)).fetchone()
        if row is None:
            raise ValueError("mature_memory_pending")
        return json.loads(row[0])
    finally:
        conn.close()


def run_loop(*, interval_sec: int = 60):
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    while True:
        try:
            ledger = store_dir() / "market_runs.db"
            conn = sqlite3.connect(ledger.resolve().as_uri()+"?mode=ro",uri=True)
            try:
                row = conn.execute("SELECT trade_date,universe_json FROM daily_runs WHERE state='complete' ORDER BY trade_date DESC LIMIT 1").fetchone()
            finally:
                conn.close()
            if row:
                universe = json.loads(row[1])
                if universe["snapshot_meta"].get("fallback") or universe["snapshot_meta"].get("stale"):
                    raise ValueError("memory_universe_untrusted")
                report = maintain(target=row[0], symbols=tuple(universe["raw_symbols"]), expected=tuple(universe["expected_symbols"]), now=datetime.now(ZoneInfo("Asia/Shanghai")))
                print(json.dumps({"mature_memory":report},ensure_ascii=False),flush=True)
        except Exception as exc:
            print(json.dumps({"mature_memory_error":f"{type(exc).__name__}:{exc}"}),flush=True)
        time.sleep(interval_sec)
