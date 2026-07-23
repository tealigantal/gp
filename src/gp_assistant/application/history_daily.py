from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

import pandas as pd

from ..search.history_store import history_db_path


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
