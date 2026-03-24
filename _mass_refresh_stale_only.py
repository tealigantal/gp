"""
Refresh only stale daily OHLCV caches to the latest trading day.

This scans store/search/history.db for daily queries and checks each
query's last_item_time against the resolved latest trading day (weekday
fallback). Only symbols whose cache is behind will be refreshed.

Optional env:
- LIMIT: max number of symbols to refresh (default: 50)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

import pandas as pd

import sys
root = Path.cwd(); sys.path.insert(0, str(root / 'src'))
from gp_assistant.recommend.datahub import MarketDataHub  # noqa: E402


def _db_path() -> Path:
    return Path('store/search/history.db')


def _resolve_latest_trading_day() -> pd.Timestamp:
    try:
        tz = os.getenv('TZ', 'Asia/Shanghai')
        base = pd.Timestamp.now(tz=tz).normalize()
    except Exception:
        base = pd.Timestamp.now().normalize()
    d = base
    # minimal weekend fallback; holiday exceptions not covered
    while d.weekday() >= 5:
        d = d - pd.Timedelta(days=1)
    return d


def _load_daily_queries(conn: sqlite3.Connection) -> List[Tuple[str, str, str | None]]:
    cur = conn.execute("SELECT id, params, last_item_time FROM queries")
    out: List[Tuple[str, str, str | None]] = []
    for qid, pjson, last_time in cur.fetchall():
        try:
            p = json.loads(pjson or '{}')
        except Exception:
            p = {}
        if (p or {}).get('kind') == 'daily':
            sym = str((p or {}).get('symbol') or '').strip()
            if sym:
                out.append((sym, qid, last_time))
    return out


def main() -> None:
    db = _db_path()
    if not db.exists():
        print(json.dumps({'ok': True, 'n': 0, 'reason': 'no_db'}), ensure_ascii=False)
        return
    limit = int(os.getenv('LIMIT', '50'))
    conn = sqlite3.connect(str(db))
    try:
        q = _load_daily_queries(conn)
    finally:
        conn.close()

    target = _resolve_latest_trading_day().date().isoformat()

    # dedupe symbols keeping the most recent last_item_time
    latest_map: dict[str, str | None] = {}
    for sym, _qid, last in q:
        prev = latest_map.get(sym)
        if prev is None:
            latest_map[sym] = last
        else:
            try:
                if last and (not prev or pd.to_datetime(last) > pd.to_datetime(prev)):
                    latest_map[sym] = last
            except Exception:
                pass

    stale: List[str] = []
    tgt = pd.to_datetime(target)
    for sym, last in latest_map.items():
        try:
            if not last:
                stale.append(sym)
                continue
            ld = pd.to_datetime(last).normalize()
            if ld.date() < tgt.date():
                stale.append(sym)
        except Exception:
            stale.append(sym)

    if limit > 0:
        stale = stale[:limit]

    hub = MarketDataHub()
    ok, errs = 0, []
    for i, s in enumerate(stale, 1):
        try:
            df, meta = hub.daily_ohlcv(s, as_of=target, min_len=0, prefer_cache_only=False)
            ok += 1
            print(f"[refresh] {i}/{len(stale)} {s} rows={len(df)} src={(meta or {}).get('source')} target={target}", flush=True)
        except Exception as e:  # noqa: BLE001
            errs.append({'s': s, 'err': f'{type(e).__name__}: {e}'})
            print(f"[refresh] FAIL {i}/{len(stale)} {s} {type(e).__name__}: {e}", flush=True)

    print(json.dumps({'ok': True, 'target': target, 'refreshed': ok, 'errors': errs[:10]}, ensure_ascii=False))


if __name__ == '__main__':
    main()

