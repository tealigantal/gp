from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Tuple


DATE_RX = re.compile(r"^(\d{4})(?:-|)?(\d{2})(?:-|)?(\d{2})")


def _now_tz() -> datetime:
    # Keep simple: default to UTC to be consistent across envs
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(os.getenv("TZ", "UTC"))
    except Exception:
        tz = timezone.utc
    return datetime.now(tz)


def parse_date_from_name(name: str) -> datetime | None:
    m = DATE_RX.match(name)
    if not m:
        return None
    try:
        y, mo, d = map(int, m.groups())
        return datetime(y, mo, d, tzinfo=timezone.utc)
    except Exception:
        return None


def prune_recommendations(reco_dir: Path, keep_days: int, keep_latest_n: int = 1, keep_samples: Iterable[str] = ()) -> Tuple[int, int]:
    reco_dir.mkdir(parents=True, exist_ok=True)
    files = [p for p in reco_dir.glob("*.json") if p.name != "latest.json"]
    # Partition dated files and non-dated (debug/sources)
    dated: list[tuple[Path, datetime]] = []
    others: list[Path] = []
    for p in files:
        if p.name in set(keep_samples):
            continue
        dt = parse_date_from_name(p.stem)
        if dt is None or ("_debug" in p.name or "_source" in p.name or "_sources" in p.name):
            others.append(p)
        else:
            dated.append((p, dt))
    # Keep last N by date, drop rest beyond keep_days
    dated.sort(key=lambda x: x[1])
    keep_set = set()
    if dated:
        keep_set.update(p for p, _ in dated[-max(0, keep_latest_n):])
    cutoff = _now_tz() - timedelta(days=max(0, keep_days))
    removed = 0
    scanned = 0
    for p, dt in dated:
        scanned += 1
        if p in keep_set:
            continue
        if dt < cutoff:
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
    # Purge debug/sources older than 1 day by default
    for p in others:
        try:
            p.unlink(missing_ok=True)
            removed += 1
        except Exception:
            pass
    return scanned, removed


def _connect_sqlite(p: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(p), timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return conn


def prune_sessions_db(db_path: Path, keep_days: int) -> None:
    if not db_path.exists():
        return
    cutoff = (_now_tz() - timedelta(days=max(0, keep_days))).isoformat()
    conn = _connect_sqlite(db_path)
    try:
        conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM sessions WHERE created_at < ?", (cutoff,))
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()


def prune_search_history_db(db_path: Path, keep_days: int) -> None:
    if not db_path.exists():
        return
    cutoff = (_now_tz() - timedelta(days=max(0, keep_days))).isoformat()
    conn = _connect_sqlite(db_path)
    try:
        # Items by item_time
        conn.execute("DELETE FROM items WHERE item_time < ?", (cutoff,))
        # Optionally prune queries that have no recent items
        conn.execute(
            "DELETE FROM queries WHERE (last_item_time IS NULL) OR (last_item_time < ?)",
            (cutoff,)
        )
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()


def prune_assistant_sessions_logs(sess_dir: Path, keep_days: int) -> Tuple[int, int]:
    if not sess_dir.exists():
        return 0, 0
    cutoff = _now_tz() - timedelta(days=max(0, keep_days))
    cnt = 0
    rm = 0
    for p in sess_dir.glob("*.jsonl"):
        cnt += 1
        try:
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except Exception:
            ts = cutoff - timedelta(days=1)
        if ts < cutoff:
            try:
                p.unlink(missing_ok=True)
                rm += 1
            except Exception:
                pass
    return cnt, rm


def main() -> None:
    ap = argparse.ArgumentParser(description="Runtime retention & cleanup for store/* and caches")
    ap.add_argument("--keep-days", type=int, default=14, help="Keep window for sessions/history/reco (days)")
    ap.add_argument("--store", type=str, default=str(Path.cwd() / "store"), help="Store directory (default ./store)")
    args = ap.parse_args()

    store = Path(args.store)
    reco_dir = store / "recommend"
    sessions_db = store / "sessions" / "session.db"
    search_db = store / "search" / "history.db"
    assist_logs = store / "assistant" / "sessions"

    # Whitelist a minimal sample if present
    keep_samples = ["2026-03-11.json"]
    scanned, removed = prune_recommendations(reco_dir, keep_days=args.keep_days, keep_latest_n=1, keep_samples=keep_samples)
    print(json.dumps({"recommend_scanned": scanned, "recommend_removed": removed}, ensure_ascii=False))

    prune_sessions_db(sessions_db, keep_days=args.keep_days)
    prune_search_history_db(search_db, keep_days=args.keep_days)
    cnt, rm = prune_assistant_sessions_logs(assist_logs, keep_days=args.keep_days)
    print(json.dumps({"assistant_sessions_scanned": cnt, "assistant_sessions_removed": rm}, ensure_ascii=False))


if __name__ == "__main__":
    main()

