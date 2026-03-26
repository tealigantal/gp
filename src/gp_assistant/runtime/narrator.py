from __future__ import annotations

from typing import Any, Dict

from ..llm.narrate import render_reply
from ..contracts.objects import ReplyBundle, Judgment, TurnFrame, EvidencePack


def build_reply(session_id: str, frame: TurnFrame, evidence: EvidencePack, judgment: Judgment) -> ReplyBundle:
    text = render_reply({
        'frame': frame.model_dump(),
        'judgment': judgment.model_dump(),
        'evidence_summary': {
            'book_version': evidence.book.book_version,
            'board_symbols': [e.symbol for e in evidence.book.board[:6]],
            'active_run_id': evidence.active_run.run_id if evidence.active_run else None,
        },
    })
    symbols = []
    if judgment.run is not None:
        symbols = [e.symbol for e in judgment.run.picks]
    elif judgment.subject_entry is not None:
        symbols = [judgment.subject_entry.symbol]
    elif judgment.compare_entries:
        symbols = [e.symbol for e in judgment.compare_entries]
    right_panel = {
        'book_version': evidence.book.book_version,
        'trading_day': evidence.book.trading_day,
        'top_board': [e.model_dump() for e in evidence.book.board[:5]],
    }
    return ReplyBundle(
        session_id=session_id,
        text=text,
        run_id=judgment.run.run_id if judgment.run else None,
        symbols=symbols,
        right_panel=right_panel,
        ui_items=[{'type': 'symbol', 'symbol': s} for s in symbols],
        evidence_refs=judgment.evidence_refs,
        planner_trace={'frame': frame.model_dump()},
    )
