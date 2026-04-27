from __future__ import annotations

from ..contracts.objects import EvidencePack, Judgment, TurnFrame
from .chat import judge_chat
from .workflow import (
    compare_workflow,
    exit_workflow,
    live_entry_workflow,
    no_trade_workflow,
    pick_detail_workflow,
    recommend_workflow,
    run_change_workflow,
)


def make_judgment(session_id: str, frame: TurnFrame, evidence: EvidencePack) -> Judgment:
    topk = int(frame.constraints.get("topk") or 3)

    if frame.request == "chat":
        return judge_chat()
    if frame.request == "recommend":
        return recommend_workflow(session_id=session_id, evidence=evidence, topk=topk)
    if frame.request == "pick_detail":
        return pick_detail_workflow(evidence)
    if frame.request == "no_trade_explain":
        return no_trade_workflow(evidence)
    if frame.request == "live_entry_check":
        return live_entry_workflow(evidence)
    if frame.request == "compare":
        return compare_workflow(evidence)
    if frame.request == "exit_decision":
        return exit_workflow(evidence)
    if frame.request == "run_change":
        return run_change_workflow(evidence)
    raise ValueError(f"Unhandled request: request={frame.request}")
