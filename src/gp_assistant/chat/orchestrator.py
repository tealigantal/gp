from __future__ import annotations

"""
Chat orchestrator: the single entry for chat mainline.

Pipeline:
  user message -> deterministic tool registry -> canonical gated PickArtifactV2
  -> assistant bundle/cards -> session/event persistence

This module does not contain LLM logic. It coordinates deterministic tools only.
"""

from typing import Any, Dict, List, Optional

from . import session_store as store
from . import event_store
from .assistant_bundle import AssistantBundle, Card
from .tool_registry import build_registry
from .context_builder import build_turn_context  # kept for context summary only


def _append_user_message(session_id: str, content: str, message_id: Optional[str]) -> None:
    try:
        event_store.append_text_message(session_id, author_id="user", content=content, message_id=message_id)
    except Exception:
        # Non-critical; do not break chat on event persistence issues
        pass


def _append_assistant_bundle(session_id: str, bundle: Dict[str, Any]) -> None:
    # Persist as canonical assistant_bundle thread item
    try:
        event_store.append_event(
            session_id,
            event_id=bundle.get("id") or f"bundle-{session_id}",
            type="message.created",
            data={
                "kind": "assistant_bundle",
                "content": str(bundle.get("text") or ""),
                "payload": bundle,
            },
            actor_id="assistant",
        )
    except Exception:
        pass


def _build_bundle_for_turn(session_id: str, message: str, *, ensure_topk: int = 3) -> Dict[str, Any]:
    reg = build_registry()

    # 1) Ensure an active valid run and summarize selection set (canonical artifact via gating)
    rec = reg.ensure_recommendation(session_id, topk=ensure_topk, refresh=False)
    items = rec.get("items") or []
    symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict)]

    # 2) Ask for selection explanation deterministically; never fabricate symbols
    explain = reg.explain_selection_set(session_id)

    # 3) If a focus_symbol exists, include pick_detail deterministically
    detail: Optional[Dict[str, Any]] = None
    try:
        st = store.get_state(session_id)
        focus = st.get("focused_symbol") or st.get("current_focus_symbol")
        if focus:
            detail = reg.get_pick_detail(session_id, str(focus))
    except Exception:
        detail = None

    # 4) Compose bundle
    cards: List[Dict[str, Any]] = []
    # selection set card
    cards.append(
        Card(
            "selection_set",
            "当前推荐集合",
            {"mode": "tradeable_recommendation" if bool(rec.get("tradeable")) else "observe_only_selection"},
            symbols=symbols,
            run_id=str(rec.get("active_run_id") or ""),
        )
    )
    # focus pick detail if available
    if detail and isinstance(detail, dict) and detail.get("symbol"):
        cards.append(
            Card(
                "pick_detail",
                f"{detail.get('symbol')} 细节",
                {
                    "entry_zone": detail.get("entry_zone"),
                    "stop": detail.get("stop"),
                    "take_profit": detail.get("take_profit"),
                    "reward_risk": detail.get("reward_risk"),
                    "execution_state": detail.get("execution_state"),
                },
                focus_symbol=str(detail.get("symbol")),
                run_id=str(rec.get("active_run_id") or ""),
            )
        )

    # Tool trace for grounding
    tool_results: List[Dict[str, Any]] = []
    tool_results.append({"tool": "ensure_recommendation", "result": rec})
    tool_results.append({"tool": "explain_selection_set", "result": explain})
    if detail:
        tool_results.append({"tool": "get_pick_detail", "result": detail})

    # Grounding + right panel view
    grounding = {
        "source": "orchestrator",
        "active_run_id": rec.get("active_run_id"),
        "previous_run_id": store.get_state(session_id).get("previous_run_id"),
        "focus_symbol": store.get_focus(session_id),
        "active_symbols": symbols,
        "used_symbols": [s for s in symbols[:3] if s],
        "tradeable": rec.get("tradeable"),
        "run_gating": rec.get("run_gating"),
        "tools_used": ["ensure_recommendation", "explain_selection_set"] + (["get_pick_detail"] if detail else []),
    }

    # Safe user-visible text, avoiding buy semantics on no-trade bundles
    safe_txt = (
        "已生成最新的选择集合；若不可执行，以观察为主。"
        if (rec.get("tradeable") is not True)
        else "为你整理了当前优先关注的标的集合。"
    )

    bundle = AssistantBundle.build(
        conversation_id=session_id,
        text=safe_txt,
        cards=cards,
        right_panel={
            "active_run_id": rec.get("active_run_id"),
            "previous_run_id": store.get_state(session_id).get("previous_run_id"),
            "focus_symbol": store.get_focus(session_id),
            "active_symbols": symbols,
            "tradeable": rec.get("tradeable"),
            "run_gating": rec.get("run_gating"),
            "reused_run": rec.get("reused_run"),
            "stale": rec.get("stale"),
            "refresh_reason": rec.get("refresh_reason"),
        },
        tool_calls=[],  # tool call chain is deterministic and not LLM-driven
        tool_results=tool_results,
        grounding=grounding,
    ).to_payload()
    return bundle


def handle_message(session_id: Optional[str], message: str, message_id: Optional[str]) -> Dict[str, Any]:
    # Ensure session exists
    sid = store.ensure_session(session_id)

    # Append user message into event stream
    _append_user_message(sid, message, message_id)

    # Build bundle using deterministic tools
    bundle = _build_bundle_for_turn(sid, message)

    # Persist assistant bundle and update last visible summary
    _append_assistant_bundle(sid, bundle)
    try:
        store.update_state(sid, {"last_right_panel": dict(bundle.get("right_panel") or {})})
    except Exception:
        pass

    # Flatten minimal ChatResp-compatible dict
    reply_text = str(bundle.get("text") or "")
    return {
        "session_id": sid,
        "reply": reply_text,
        "right_panel": bundle.get("right_panel") or {},
        "assistant_bundle": bundle,
    }

