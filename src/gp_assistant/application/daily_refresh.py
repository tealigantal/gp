from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from ..search.history_store import canonical_query_id, ensure_query, upsert_items


class DailyEvidenceRefresher:
    """Offline-only incremental daily-bar writer for the verified universe."""

    def __init__(self, provider):
        self.provider = provider

    def refresh(self, *, symbols: Iterable[str], start: str, end: str) -> dict[str, int]:
        requested = sorted({str(symbol).zfill(6) for symbol in symbols})
        received = 0
        failed = 0
        for offset in range(0, len(requested), 100):
            batch = requested[offset : offset + 100]
            frames = self.provider.get_daily_batch(batch, start, end)
            for symbol in batch:
                frame = frames.get(symbol)
                if not isinstance(frame, pd.DataFrame) or frame.empty:
                    failed += 1
                    continue
                params = {"kind": "daily", "provider": "akshare", "symbol": symbol}
                query_id = canonical_query_id(params)
                ensure_query(query_id, params)
                rows = frame.to_dict("records")
                for row in rows:
                    value = row.get("date")
                    day = value.date().isoformat() if hasattr(value, "date") else str(value)[:10]
                    row["date"] = day
                    row["id"] = day
                    row["time"] = day
                upsert_items(query_id, rows, id_key="id", time_key="time")
                received += 1
            print(f"daily_refresh {min(offset + len(batch), len(requested))}/{len(requested)} received={received} failed={failed}", flush=True)
        return {"requested": len(requested), "received": received, "failed": failed}
