from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

import pandas as pd

from ..search.history_store import canonical_query_id, history_db_path


def latest_rows() -> dict[str, dict[str, object]]:
    path = history_db_path()
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute("""
            SELECT json_extract(q.params, '$.symbol'), i.payload, i.item_time
            FROM queries q JOIN items i ON i.query_id=q.id
            JOIN (SELECT query_id, MAX(item_time) latest_time FROM items GROUP BY query_id) latest
              ON latest.query_id=i.query_id AND latest.latest_time=i.item_time
            WHERE json_extract(q.params, '$.kind')='daily'
              AND json_extract(q.params, '$.provider')='akshare'
        """).fetchall()
        return {str(symbol): {**json.loads(payload), "date": str(item_time)} for symbol, payload, item_time in rows}
    finally:
        conn.close()


def coverage_for_date(symbols: list[str] | tuple[str, ...], *, target_date: str) -> dict[str, dict[str, object]]:
    """Read daily bars for exactly one evidence date.

    ``latest_rows`` is deliberately useful for a current decision.  It is not
    valid for a stopped-worker recovery run because a later bar hides the bar
    for the date being repaired.  The market-run ledger always verifies a
    target date through this exact query instead.
    """
    if not symbols:
        return {}
    path = history_db_path()
    if not path.exists():
        return {}
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        output: dict[str, dict[str, object]] = {}
        normalized_target = str(target_date)[:10]
        query_symbols = {
            canonical_query_id({"kind": "daily", "provider": "akshare", "symbol": str(symbol).zfill(6)}): str(symbol).zfill(6)
            for symbol in symbols
        }
        for start in range(0, len(query_symbols), 400):
            query_ids = list(query_symbols)[start:start + 400]
            placeholders = ",".join("?" for _ in query_ids)
            rows = conn.execute(
                f"""
                SELECT i.query_id, i.payload, i.item_time
                FROM items i
                WHERE i.query_id IN ({placeholders})
                  AND substr(i.item_time, 1, 10)=?
                """,
                [*query_ids, normalized_target],
            ).fetchall()
            for query_id, payload, item_time in rows:
                parsed = json.loads(payload)
                required = {"open", "high", "low", "close", "volume", "amount"}
                if not required.issubset(parsed):
                    continue
                try:
                    values = [float(parsed[field]) for field in required]
                except (TypeError, ValueError):
                    continue
                if not all(pd.notna(value) for value in values):
                    continue
                output[query_symbols[str(query_id)]] = {**parsed, "date": str(item_time)}
        return output
    finally:
        conn.close()


def latest_daily_date() -> str | None:
    """Return the newest stored daily evidence date for recovery bootstrap."""
    path = history_db_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            """
            SELECT MAX(substr(i.item_time, 1, 10)) AS day
            FROM queries q JOIN items i ON i.query_id=q.id
            WHERE json_extract(q.params, '$.kind')='daily'
              AND json_extract(q.params, '$.provider')='akshare'
            """
        ).fetchone()
        return str(row[0]) if row and row[0] else None
    finally:
        conn.close()


def frames(symbols: list[str], *, limit: int = 150) -> dict[str, pd.DataFrame]:
    if not symbols:
        return {}
    path = history_db_path()
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        output: dict[str, list[dict[str, object]]] = defaultdict(list)
        for start in range(0, len(symbols), 400):
            chunk = symbols[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(f"""
                SELECT json_extract(q.params, '$.symbol'), i.payload
                FROM queries q JOIN items i ON i.query_id=q.id
                WHERE json_extract(q.params, '$.kind')='daily'
                  AND json_extract(q.params, '$.provider')='akshare'
                  AND json_extract(q.params, '$.symbol') IN ({placeholders})
                ORDER BY i.item_time DESC
            """, chunk).fetchall()
            for symbol, payload in rows:
                if len(output[str(symbol)]) < limit:
                    output[str(symbol)].append(json.loads(payload))
        return {symbol: pd.DataFrame(list(reversed(rows))) for symbol, rows in output.items() if len(rows) >= 80}
    finally:
        conn.close()
