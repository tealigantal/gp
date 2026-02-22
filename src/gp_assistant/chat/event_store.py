from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import threading

from ..core.config import load_config
from ..core.paths import store_dir

# Global re-entrant lock to serialize SQLite writes within process
_WRITE_LOCK = threading.RLock()


# Lightweight Event Store for conversations/messages on top of SQLite.
# Goals:
# - Per-conversation monotonically increasing seq
# - Append-only events with id (client-provided) + server-assigned seq
# - Materialized messages table for rendering/search
# - User-level settings kept in participants table


def _db_path() -> Path:
    p = store_dir() / "sessions" / "session.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    # Add timeout and WAL mode to reduce 'database is locked' under concurrent writes
    conn = sqlite3.connect(str(_db_path()), timeout=15.0)
    try:
        # Enable WAL for better concurrent read/write, and set a sane busy timeout
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")  # 10s
    except Exception:
        # Pragmas are best-effort; continue even if unsupported
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations(
            id TEXT PRIMARY KEY,
            type TEXT,
            title TEXT,
            created_at TEXT,
            updated_at TEXT,
            last_seq INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS participants(
            conversation_id TEXT,
            user_id TEXT,
            role TEXT,
            joined_at TEXT,
            pinned_at TEXT,
            archived_at TEXT,
            mute_until TEXT,
            last_read_seq INTEGER DEFAULT 0,
            last_read_at TEXT,
            PRIMARY KEY (conversation_id, user_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events(
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            seq INTEGER,
            type TEXT,
            actor_id TEXT,
            created_at TEXT,
            data TEXT,
            UNIQUE(conversation_id, seq)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conv_messages(
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            seq_created INTEGER,
            author_id TEXT,
            kind TEXT,
            content TEXT,
            reply_to TEXT,
            edited_at TEXT,
            deleted_at TEXT,
            payload TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_messages_conv_seq ON conv_messages(conversation_id, seq_created)"
    )
    # FTS5 for offline/local search support (server-side helper)
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS conv_messages_fts USING fts5(
                id UNINDEXED,
                conversation_id UNINDEXED,
                seq_created UNINDEXED,
                content_text,
                payload_text,
                tokenize='unicode61'
            )
            """
        )
    except sqlite3.OperationalError:
        # FTS5 may be unavailable in some SQLite builds; ignore silently
        pass
    conn.commit()
    return conn


def _retry_on_locked(fn, *, retries: int = 8, base_delay: float = 0.08):
    """Retry helper for sporadic 'database is locked' OperationalError.

    Exponential backoff: base_delay * 2**attempt
    """
    for i in range(max(1, retries)):
        try:
            return fn()
        except sqlite3.OperationalError as e:  # noqa: BLE001
            msg = str(e).lower()
            if "database is locked" in msg or "database is busy" in msg:
                time.sleep(base_delay * (2 ** i))
                continue
            raise
    # One last attempt (propagate if still failing)
    return fn()


def _now_iso() -> str:
    cfg = load_config()
    tz = timezone.utc
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(cfg.timezone)
    except Exception:
        pass
    return datetime.now(tz=tz).isoformat()


def _current_user_id() -> str:
    # Single-user default; can be overridden by env GP_USER_ID
    import os

    return (os.getenv("GP_USER_ID") or "local").strip() or "local"


def ensure_conversation(conv_id: str, *, title: Optional[str] = None, conv_type: Optional[str] = None) -> None:
    with _WRITE_LOCK:
        conn = _connect()
        try:
            def _write() -> None:
                cur = conn.execute("SELECT id FROM conversations WHERE id=?", (conv_id,))
                if cur.fetchone() is None:
                    conn.execute(
                        "INSERT INTO conversations(id, type, title, created_at, updated_at, last_seq) VALUES (?,?,?,?,?,0)",
                        (conv_id, conv_type or "chat", title or conv_id, _now_iso(), _now_iso()),
                    )
                else:
                    conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now_iso(), conv_id))
                conn.commit()

            _retry_on_locked(_write)
        finally:
            conn.close()


def ensure_participant(conv_id: str, user_id: Optional[str] = None, *, role: str = "owner") -> None:
    uid = user_id or _current_user_id()
    with _WRITE_LOCK:
        conn = _connect()
        try:
            def _write() -> None:
                cur = conn.execute(
                    "SELECT conversation_id FROM participants WHERE conversation_id=? AND user_id=?",
                    (conv_id, uid),
                )
                if cur.fetchone() is None:
                    conn.execute(
                        """
                        INSERT INTO participants(conversation_id, user_id, role, joined_at, last_read_seq, last_read_at)
                        VALUES (?,?,?,?,0,?)
                        """,
                        (conv_id, uid, role, _now_iso(), _now_iso()),
                    )
                    conn.commit()

            _retry_on_locked(_write)
        finally:
            conn.close()


def _next_seq(conn: sqlite3.Connection, conv_id: str) -> int:
    cur = conn.execute("SELECT last_seq FROM conversations WHERE id=?", (conv_id,))
    row = cur.fetchone()
    last = int(row[0]) if row else 0
    return last + 1


def _bump_seq(conn: sqlite3.Connection, conv_id: str, seq: int) -> None:
    conn.execute(
        "UPDATE conversations SET last_seq=?, updated_at=? WHERE id=?",
        (seq, _now_iso(), conv_id),
    )


def append_event(
    conv_id: str,
    *,
    event_id: str,
    type: str,
    data: Dict[str, Any],
    actor_id: Optional[str] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Append an event and materialize into messages if applicable.

    Returns (seq, event_dict)
    """
    ensure_conversation(conv_id)
    ensure_participant(conv_id)
    with _WRITE_LOCK:
        conn = _connect()
        try:
            def _write() -> Tuple[int, Dict[str, Any]]:
                # Attempt insert with retry on seq conflict due to concurrency
                row = None
                for i in range(10):
                    seq = _next_seq(conn, conv_id)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO events(id, conversation_id, seq, type, actor_id, created_at, data)
                        VALUES (?,?,?,?,?,?,?)
                        """,
                        (event_id, conv_id, seq, type, actor_id or _current_user_id(), _now_iso(), json.dumps(data, ensure_ascii=False)),
                    )
                    # If duplicate event_id or successful insert, row will exist
                    cur = conn.execute(
                        "SELECT conversation_id, seq, type, actor_id, created_at, data FROM events WHERE id=?",
                        (event_id,),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        break
                    # row is None -> likely seq conflict on UNIQUE(conversation_id, seq). Backoff and retry.
                    time.sleep(0.01 * (2 ** i))
                if row is None:
                    raise RuntimeError("failed to insert or find event after retries")
                # If inserted with a previous seq due to duplicate id, keep consistency on conversations.last_seq
                seq2 = int(row[1])
                _bump_seq(conn, conv_id, max(seq2, _next_seq(conn, conv_id) - 1))
                # Materialize if message.*
                etype = str(row[2])
                edata = json.loads(row[5] or "{}")
                if etype == "message.created":
                    _materialize_message_created(conn, conv_id, seq2, row[3], edata)
                elif etype == "message.edited":
                    _materialize_message_edited(conn, edata)
                elif etype == "message.recalled":
                    _materialize_message_recalled(conn, edata)
                conn.commit()
                return seq2, {
                    "id": event_id,
                    "conversation_id": conv_id,
                    "seq": seq2,
                    "type": etype,
                    "actor_id": row[3],
                    "created_at": row[4],
                    "data": edata,
                }

            return _retry_on_locked(_write)
        finally:
            conn.close()


def _materialize_message_created(conn: sqlite3.Connection, conv_id: str, seq: int, author_id: str, data: Dict[str, Any]) -> None:
    mid = data.get("message_id") or data.get("id") or f"mid-{seq}"
    kind = data.get("kind") or "text"
    content = data.get("content") or ""
    reply_to = data.get("reply_to")
    payload = data.get("payload")
    conn.execute(
        """
        INSERT OR REPLACE INTO conv_messages(id, conversation_id, seq_created, author_id, kind, content, reply_to, edited_at, deleted_at, payload, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(mid),
            conv_id,
            seq,
            author_id,
            kind,
            content,
            str(reply_to) if reply_to else None,
            None,
            None,
            json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            _now_iso(),
        ),
    )
    # If conversation title is meaningless (e.g., default id), set it to a snippet of first user message
    try:
        cur = conn.execute("SELECT title FROM conversations WHERE id=?", (conv_id,))
        row = cur.fetchone()
        if row is not None:
            title = row[0] or ""
            if not title or title == conv_id or title.startswith("sess-"):
                snippet = str(content or "").strip()
                if snippet:
                    if len(snippet) > 24:
                        snippet = snippet[:24] + "…"
                    conn.execute(
                        "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                        (snippet, _now_iso(), conv_id),
                    )
    except Exception:
        pass
    _fts_upsert_message(conn, mid, conv_id, seq, content, payload)


def _materialize_message_edited(conn: sqlite3.Connection, data: Dict[str, Any]) -> None:
    mid = data.get("message_id") or data.get("id")
    if not mid:
        return
    content = data.get("content")
    payload = data.get("payload")
    edited_at = _now_iso()
    row = conn.execute("SELECT id FROM conv_messages WHERE id=?", (str(mid),)).fetchone()
    if row is None:
        return
    conn.execute(
        "UPDATE conv_messages SET content=COALESCE(?, content), payload=COALESCE(?, payload), edited_at=? WHERE id=?",
        (
            content,
            json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            edited_at,
            str(mid),
        ),
    )
    # fetch latest values for FTS update
    cur = conn.execute("SELECT conversation_id, seq_created, content, payload FROM conv_messages WHERE id=?", (str(mid),))
    row2 = cur.fetchone()
    if row2:
        c_id, seq, c_text, p_json = row2
        try:
            payload_obj = json.loads(p_json) if p_json else None
        except Exception:
            payload_obj = None
        _fts_upsert_message(conn, mid, c_id, int(seq or 0), content or c_text or "", payload if payload is not None else payload_obj)


def _materialize_message_recalled(conn: sqlite3.Connection, data: Dict[str, Any]) -> None:
    mid = data.get("message_id") or data.get("id")
    if not mid:
        return
    conn.execute(
        "UPDATE conv_messages SET deleted_at=? WHERE id=?",
        (_now_iso(), str(mid)),
    )


def _fts_upsert_message(
    conn: sqlite3.Connection,
    mid: str,
    conv_id: str,
    seq: int,
    content: Optional[str],
    payload: Optional[Dict[str, Any]] | Any,
) -> None:
    try:
        # Compose simple payload text
        import os as _os
        e2ee_on = (_os.getenv("GP_E2EE") or "0").lower() in {"1", "true", "yes"}
        if e2ee_on:
            payload_text = ""
        elif isinstance(payload, dict):
            payload_text = json.dumps(payload, ensure_ascii=False)
        elif payload is None:
            payload_text = None
        else:
            payload_text = str(payload)
        conn.execute(
            "INSERT OR REPLACE INTO conv_messages_fts(id, conversation_id, seq_created, content_text, payload_text) VALUES (?,?,?,?,?)",
            (str(mid), conv_id, int(seq or 0), content or "", payload_text or ""),
        )
    except sqlite3.OperationalError:
        # FTS table missing; ignore
        pass


def append_text_message(conv_id: str, *, author_id: Optional[str], content: str, message_id: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    eid = message_id or f"ev-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    data = {"message_id": eid, "kind": "text", "content": content}
    return append_event(conv_id, event_id=eid, type="message.created", data=data, actor_id=author_id)


def update_read(conv_id: str, user_id: Optional[str], last_read_seq: int) -> None:
    uid = user_id or _current_user_id()
    with _WRITE_LOCK:
        conn = _connect()
        try:
            def _write() -> None:
                conn.execute(
                    "UPDATE participants SET last_read_seq=?, last_read_at=? WHERE conversation_id=? AND user_id=?",
                    (int(last_read_seq), _now_iso(), conv_id, uid),
                )
                conn.commit()

            _retry_on_locked(_write)
        finally:
            conn.close()


def list_events_after(conv_id: str, after_seq: int, limit: int = 100) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT id, conversation_id, seq, type, actor_id, created_at, data FROM events WHERE conversation_id=? AND seq>? ORDER BY seq ASC LIMIT ?",
            (conv_id, int(after_seq), int(limit)),
        )
        out = []
        for r in cur.fetchall():
            out.append(
                {
                    "id": r[0],
                    "conversation_id": r[1],
                    "seq": int(r[2]),
                    "type": r[3],
                    "actor_id": r[4],
                    "created_at": r[5],
                    "data": json.loads(r[6] or "{}"),
                }
            )
        return out
    finally:
        conn.close()


def list_events_around(conv_id: str, center_seq: int, limit: int = 50) -> List[Dict[str, Any]]:
    half = max(1, int(limit) // 2)
    start = max(1, int(center_seq) - half)
    after = start - 1
    return list_events_after(conv_id, after, limit)


def conversation_meta(conv_id: str) -> Dict[str, Any]:
    conn = _connect()
    try:
        cur = conn.execute("SELECT id, last_seq, updated_at FROM conversations WHERE id=?", (conv_id,))
        row = cur.fetchone()
        if row is None:
            return {"id": conv_id, "last_seq": 0, "updated_at": None}
        return {"id": row[0], "last_seq": int(row[1] or 0), "updated_at": row[2]}
    finally:
        conn.close()


def list_conversations() -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT id, title, type, last_seq, updated_at FROM conversations ORDER BY last_seq DESC"
        )
        return [
            {
                "id": r[0],
                "title": r[1],
                "type": r[2],
                "last_seq": int(r[3] or 0),
                "updated_at": r[4],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def search_messages(query: str, conversation_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        try:
            if conversation_id:
                cur = conn.execute(
                    "SELECT id, conversation_id, seq_created FROM conv_messages_fts WHERE conv_messages_fts MATCH ? AND conversation_id=? LIMIT ?",
                    (query, conversation_id, int(limit)),
                )
            else:
                cur = conn.execute(
                    "SELECT id, conversation_id, seq_created FROM conv_messages_fts WHERE conv_messages_fts MATCH ? LIMIT ?",
                    (query, int(limit)),
                )
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            # FTS not available
            rows = []
        return [
            {"message_id": r[0], "conversation_id": r[1], "seq": int(r[2] or 0)} for r in rows
        ]
    finally:
        conn.close()


def export_conversation(conv_id: str) -> Dict[str, Any]:
    conn = _connect()
    try:
        meta = conversation_meta(conv_id)
        cur = conn.execute("SELECT user_id, role, pinned_at, archived_at, mute_until, last_read_seq, last_read_at FROM participants WHERE conversation_id=?", (conv_id,))
        participants = [
            {
                "user_id": r[0],
                "role": r[1],
                "pinned_at": r[2],
                "archived_at": r[3],
                "mute_until": r[4],
                "last_read_seq": int(r[5] or 0),
                "last_read_at": r[6],
            }
            for r in cur.fetchall()
        ]
        cur2 = conn.execute("SELECT id, conversation_id, seq, type, actor_id, created_at, data FROM events WHERE conversation_id=? ORDER BY seq ASC", (conv_id,))
        events = [
            {
                "id": r[0],
                "conversation_id": r[1],
                "seq": int(r[2]),
                "type": r[3],
                "actor_id": r[4],
                "created_at": r[5],
                "data": json.loads(r[6] or "{}"),
            }
            for r in cur2.fetchall()
        ]
        return {"conversation": meta, "participants": participants, "events": events}
    finally:
        conn.close()


def import_conversation(data: Dict[str, Any]) -> None:
    conv = data.get("conversation") or {}
    cid = conv.get("id")
    if not cid:
        raise ValueError("missing conversation.id")
    ensure_conversation(cid, title=conv.get("title"), conv_type=conv.get("type"))
    # participants
    for p in data.get("participants", []) or []:
        ensure_participant(cid, user_id=p.get("user_id") or _current_user_id(), role=p.get("role") or "member")
        try:
            conn = _connect()
            conn.execute(
                "UPDATE participants SET pinned_at=?, archived_at=?, mute_until=?, last_read_seq=?, last_read_at=? WHERE conversation_id=? AND user_id=?",
                (
                    p.get("pinned_at"),
                    p.get("archived_at"),
                    p.get("mute_until"),
                    int(p.get("last_read_seq") or 0),
                    p.get("last_read_at"),
                    cid,
                    p.get("user_id") or _current_user_id(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
    # events
    for e in data.get("events", []) or []:
        try:
            append_event(cid, event_id=e.get("id") or f"import-{_now_iso()}", type=e.get("type") or "unknown", data=e.get("data") or {}, actor_id=e.get("actor_id"))
        except Exception:
            # ignore duplicates
            pass


def delete_conversation(conv_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM events WHERE conversation_id=?", (conv_id,))
        try:
            conn.execute("DELETE FROM conv_messages WHERE conversation_id=?", (conv_id,))
        except Exception:
            pass
        conn.execute("DELETE FROM participants WHERE conversation_id=?", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        conn.commit()
    finally:
        conn.close()


def cleanup_conversations(mode: str = "all") -> None:
    """Cleanup conversations store.

    mode:
      - "all": delete conversations, participants, events, conv_messages (hard reset)
      - "events_only": delete events/conv_messages and reset last_seq/last_read_seq
    """
    conn = _connect()
    try:
        if mode == "events_only":
            conn.execute("DELETE FROM events")
            try:
                conn.execute("DELETE FROM conv_messages")
            except Exception:
                pass
            conn.execute("UPDATE conversations SET last_seq=0, updated_at=?", (_now_iso(),))
            conn.execute("UPDATE participants SET last_read_seq=0, last_read_at=?", (_now_iso(),))
        else:
            conn.execute("DELETE FROM events")
            try:
                conn.execute("DELETE FROM conv_messages")
            except Exception:
                pass
            conn.execute("DELETE FROM participants")
            conn.execute("DELETE FROM conversations")
        conn.commit()
    finally:
        conn.close()
