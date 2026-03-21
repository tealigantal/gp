from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import session_store as store
from . import event_store
from ..kernel.facade import get_gated_artifact_v2


def _safe_json_load(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        import json

        return json.loads(s)
    except Exception:
        return None


def _recent_thread_items(cid: str, limit: int = 12) -> List[Dict[str, Any]]:
    # Minimal mirror of server.thread items: only user text + assistant_bundle
    conn = event_store._connect()  # reuse same DB/PRAGMA
    try:
        cur = conn.execute(
            """
            SELECT id, seq_created, author_id, kind, content, payload, created_at
            FROM conv_messages
            WHERE conversation_id=? AND deleted_at IS NULL
            ORDER BY seq_created DESC
            LIMIT ?
            """,
            (cid, int(limit)),
        )
        rows = list(reversed(cur.fetchall() or []))
    except Exception:
        rows = []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            mid, seq, author_id, kind, content, payload_json, created_at = r
            role = "assistant" if (str(author_id or "").lower().strip() == "assistant") else "user"
            k = (kind or "text").strip().lower()
            if k == "text" and role == "user":
                out.append({
                    "role": "user",
                    "text": str(content or ""),
                    "kind": "text",
                    "card_types": [],
                    "active_run_id": None,
                })
            elif k == "assistant_bundle" and role == "assistant":
                payload = _safe_json_load(payload_json) or {}
                rp = (payload.get("right_panel") or {}) if isinstance(payload, dict) else {}
                cards = list((payload.get("cards") or []) if isinstance(payload, dict) else [])
                out.append({
                    "role": "assistant",
                    "text": str((payload.get("text") or "") if isinstance(payload, dict) else ""),
                    "kind": "assistant_bundle",
                    "card_types": [str((c or {}).get("type") or "") for c in cards if isinstance(c, dict)],
                    "active_run_id": rp.get("active_run_id"),
                })
        except Exception:
            continue
    return out


def _build_active_artifact_summary(run_id: Optional[str]) -> Dict[str, Any]:
    if not run_id:
        return {
            "active_run_id": None,
            "tradeable": None,
            "run_gating": None,
            "ordered_symbols": [],
            "top_items": [],
        }
    try:
        art = get_gated_artifact_v2(run_id=run_id)
    except Exception:
        art = {}
    items = (art.get("items") or []) if isinstance(art, dict) else []
    syms = []
    top_items: List[Dict[str, Any]] = []
    for idx, it in enumerate(items[:5]):  # cap top items for compactness
        try:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "")
            if sym:
                syms.append(sym)
            top_items.append({
                "symbol": sym or None,
                "strategy_label": it.get("strategy_label") or it.get("strategy"),
                "thesis": it.get("thesis"),
                "actionable": it.get("actionable"),
            })
        except Exception:
            continue
    return {
        "active_run_id": art.get("run_id") or run_id,
        "tradeable": art.get("tradeable"),
        "run_gating": art.get("run_gating"),
        "ordered_symbols": syms,
        "top_items": top_items,
    }


def build_turn_context(session_id: str) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    st = store.get_state(sid)

    # Layer 1: session state (compact)
    session_state = {
        "active_run_id": st.get("active_run_id"),
        "previous_run_id": st.get("previous_run_id"),
        "focus_symbol": st.get("focused_symbol") or st.get("current_focus_symbol"),
        "active_symbols": list(st.get("active_symbols") or []),
        "pending_action": st.get("pending_action"),
        "pending_symbols": list(st.get("pending_symbols") or []),
        "pending_cursor": st.get("pending_cursor"),
        "last_reference_resolution": st.get("last_reference_resolution"),
        "last_surface_kind": st.get("last_surface_kind"),
    }

    # Layer 2: active artifact summary (ground truth base)
    art_summary = _build_active_artifact_summary(session_state.get("active_run_id"))

    # Layer 3/4: dialogue + tool trace summaries
    recent_dialogue = _recent_thread_items(sid, limit=10)
    # tool trace summary from latest assistant bundles (up to 3)
    recent_tool_trace_summary: List[Dict[str, Any]] = []
    try:
        # Traverse from the end for assistant_bundle items
        bundles = [d for d in reversed(recent_dialogue) if d.get("role") == "assistant" and d.get("kind") == "assistant_bundle"]
        # Fetch original payloads to extract grounding fields
        if bundles:
            conn = event_store._connect()
            try:
                cur = conn.execute(
                    """
                    SELECT payload FROM conv_messages
                    WHERE conversation_id=? AND deleted_at IS NULL AND kind='assistant_bundle'
                    ORDER BY seq_created DESC
                    LIMIT 3
                    """,
                    (sid,),
                )
                rows = cur.fetchall() or []
            finally:
                conn.close()
            for row in rows:
                try:
                    payload = _safe_json_load(row[0]) or {}
                    g = (payload.get("grounding") or {}) if isinstance(payload, dict) else {}
                    rp = (payload.get("right_panel") or {}) if isinstance(payload, dict) else {}
                    recent_tool_trace_summary.append({
                        "tools_used": list((g.get("tools_used") or [])),
                        "used_symbols": list((g.get("used_symbols") or [])),
                        "active_run_id": rp.get("active_run_id") or g.get("active_run_id"),
                        "tradeable": g.get("tradeable"),
                    })
                except Exception:
                    continue
    except Exception:
        pass

    # Layer 5: continuation state (derived)
    can_continue = False
    try:
        if session_state.get("pending_action") and (
            (session_state.get("pending_symbols") or []) or (session_state.get("pending_cursor") is not None)
        ):
            can_continue = True
    except Exception:
        can_continue = False

    continuation_state = {
        "pending_action": session_state.get("pending_action"),
        "pending_symbols": session_state.get("pending_symbols"),
        "pending_cursor": session_state.get("pending_cursor"),
        "can_continue": bool(can_continue),
    }

    return {
        "session_state": session_state,
        "active_artifact_summary": art_summary,
        "recent_dialogue": recent_dialogue,
        "recent_tool_trace_summary": recent_tool_trace_summary,
        "continuation_state": continuation_state,
    }
