from __future__ import annotations

"""Single-snapshot chat renderer.

The module deliberately contains no import of the old gateway, run, book-repo,
or V1/V2 artifact paths.  Every financial statement it emits is projected from
the immutable RecommendationSnapshot.v1 bound to the conversation turn.
"""

from typing import Any

from .agent_store import AgentStore, StoredSnapshot
from .contracts.objects import BoardEntry, MarketBook
from .runtime.utils import gen_id


def _entry_payload(entry: BoardEntry) -> dict[str, Any]:
    pick = entry.pick
    return {
        "symbol": entry.symbol,
        "name": entry.name or pick.name,
        "rank": entry.rank,
        "action": entry.action,
        "summary": entry.summary,
        "entry_plan": pick.entry_plan or entry.entry_zone,
        "stop_plan": pick.stop_plan or ({"price": entry.stop} if entry.stop is not None else {}),
        "take_profit_plan": pick.take_profit_plan or ({"prices": entry.take} if entry.take else {}),
        "risk_flags": list(dict.fromkeys([*pick.risk_flags, *entry.reason_codes])),
        "why_selected": pick.why_selected,
        "evidence_refs": list(dict.fromkeys([*pick.evidence_refs, str(entry.artifact_id or "")])),
    }


def _match_entries(book: MarketBook, message: str) -> list[BoardEntry]:
    needle = message.lower()
    return [
        entry for entry in book.board
        if entry.symbol.lower() in needle or (entry.name and entry.name.lower() in needle)
    ]


def _snapshot_is_usable(snapshot: StoredSnapshot, book: MarketBook) -> tuple[bool, str | None]:
    freshness = str(book.data_quality.freshness_state or "").lower()
    if freshness in {"stale", "unavailable", "invalid"}:
        return False, f"market_data_{freshness}"
    if snapshot.decision == "no_trade":
        return False, str(book.daybook.reason or "selection_no_trade")
    if not snapshot.tradeable:
        return False, str(book.daybook.reason or "selection_not_tradeable")
    return True, None


def _render(book: MarketBook, snapshot: StoredSnapshot, user_message: str) -> tuple[str, dict[str, Any], list[str], list[dict[str, Any]]]:
    matches = _match_entries(book, user_message)
    lower = user_message.lower()
    if len(matches) >= 2 or any(word in lower for word in ("比较", "对比", "compare")):
        selected = matches or list(book.board[:2])
        picks = [_entry_payload(entry) for entry in selected]
        reply = "比较仅基于当前推荐快照：请优先关注排名、入场条件和各自止损，未满足入场条件时不交易。"
        kind = "compare"
    elif matches:
        entry = matches[0]
        picks = [_entry_payload(entry)]
        reply = f"{entry.symbol}{(' ' + entry.name) if entry.name else ''} 的说明仅来自当前快照：{entry.summary}"
        kind = "pick_detail"
    elif any(word in lower for word in ("止损", "持仓", "卖", "退出", "exit", "stop")):
        picks = [_entry_payload(entry) for entry in book.board]
        reply = "持仓与止损问题按当前快照中的止损计划执行；快照未给出的价格或条件不作补充推断。"
        kind = "exit"
    else:
        picks = [_entry_payload(entry) for entry in book.board]
        reply = "当前快照给出的候选如下。仅在各自入场条件满足时考虑，且必须遵守止损与风险提示。"
        kind = "recommend"
    claims = [
        {
            "claim_id": gen_id("claim"),
            "type": "snapshot_pick",
            "symbol": pick["symbol"],
            "snapshot_id": snapshot.snapshot_id,
            "evidence_refs": pick["evidence_refs"],
        }
        for pick in picks
    ]
    message = {
        "message_kind": kind,
        "snapshot_id": snapshot.snapshot_id,
        "as_of": snapshot.as_of,
        "tradeable": snapshot.tradeable,
        "picks": picks,
        "risk_notice": "A 股市场存在损失风险；该结果是短期决策信息，不构成保证收益。",
    }
    return reply, message, [pick["symbol"] for pick in picks], claims


def run_chat_turn(*, session_id: str | None, client_turn_id: str, user_message: str, store: AgentStore | None = None) -> dict[str, Any]:
    """Render and atomically persist a turn against one immutable snapshot."""
    store = store or AgentStore()
    resolved_session_id = session_id or gen_id("session")
    # Once a session has committed its first turn, no later worker publication
    # may change the factual basis of its follow-ups.
    snapshot = store.session_snapshot(resolved_session_id) or store.current_snapshot()
    if snapshot is None:
        return {
            "session_id": resolved_session_id,
            "client_turn_id": client_turn_id,
            "snapshot_id": None,
            "decision": "no_trade",
            "reply": "当前没有可验证的推荐快照，系统不提供荐股。",
            "message": {"message_kind": "no_trade", "reason": "current_snapshot_unavailable", "picks": []},
            "symbols": [],
        }
    book = store.book_for_snapshot(snapshot)
    usable, reason = _snapshot_is_usable(snapshot, book)
    if not usable:
        payload = {
            "session_id": resolved_session_id,
            "client_turn_id": client_turn_id,
            "snapshot_id": snapshot.snapshot_id,
            "decision": "no_trade",
            "reply": "当前快照不满足可交易条件，系统不提供荐股。",
            "message": {"message_kind": "no_trade", "reason": reason, "picks": [], "snapshot_id": snapshot.snapshot_id},
            "symbols": [],
        }
        return store.commit_turn(
            session_id=resolved_session_id, client_turn_id=client_turn_id, user_content=user_message,
            assistant_content=payload["reply"], assistant_payload=payload, snapshot_id=snapshot.snapshot_id, claims=[],
        )
    reply, message, symbols, claims = _render(book, snapshot, user_message)
    payload = {
        "session_id": resolved_session_id,
        "client_turn_id": client_turn_id,
        "snapshot_id": snapshot.snapshot_id,
        "decision": "recommend",
        "reply": reply,
        "message": message,
        "symbols": symbols,
    }
    return store.commit_turn(
        session_id=resolved_session_id, client_turn_id=client_turn_id, user_content=user_message,
        assistant_content=reply, assistant_payload=payload, snapshot_id=snapshot.snapshot_id, claims=claims,
    )
