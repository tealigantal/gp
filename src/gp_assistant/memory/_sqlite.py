from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from ..core.paths import store_dir

DB_PATH = store_dir() / 'gateway.db'


def ensure_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transcript (
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                turn_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                meta_json TEXT NOT NULL,
                PRIMARY KEY (session_id, seq)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value_json TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                session_id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def gateway_stats() -> dict[str, int | str | None]:
    ensure_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM sessions) AS session_count,
                (SELECT COUNT(*) FROM transcript) AS transcript_count,
                (SELECT COUNT(*) FROM claims) AS claim_count,
                (SELECT MAX(updated_at) FROM sessions) AS latest_session_at
            """
        ).fetchone()
        return {
            'session_count': int(row['session_count'] or 0),
            'transcript_count': int(row['transcript_count'] or 0),
            'claim_count': int(row['claim_count'] or 0),
            'latest_session_at': row['latest_session_at'],
        }
    finally:
        conn.close()


@contextmanager
def get_conn():
    ensure_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
