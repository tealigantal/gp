from __future__ import annotations

from typing import Any, Dict

from ..contracts.objects import TurnFrame


def plan_evidence(frame: TurnFrame) -> Dict[str, Any]:
    need = {
        "need_active_run": False,
        "need_previous_run": False,
        "need_subject_entry": False,
        "need_compare_entries": False,
        "need_validation": False,
        "need_portfolio": False,
        "publish_run": False,
    }
    if frame.request == "chat":
        return need
    if frame.request == "recommend":
        need["publish_run"] = True
        need["need_validation"] = True
        return need
    if frame.request == "pick_detail":
        need["need_active_run"] = True
        need["need_subject_entry"] = True
        return need
    if frame.request == "no_trade_explain":
        need["need_active_run"] = True
        if frame.subject == "symbol":
            need["need_subject_entry"] = True
        return need
    if frame.request == "live_entry_check":
        need["need_active_run"] = True
        need["need_subject_entry"] = True
        return need
    if frame.request == "compare":
        need["need_active_run"] = True
        need["need_compare_entries"] = True
        return need
    if frame.request == "exit_decision":
        need["need_active_run"] = True
        need["need_subject_entry"] = True
        need["need_portfolio"] = True
        return need
    if frame.request == "run_change":
        need["need_active_run"] = True
        need["need_previous_run"] = True
        return need
    return need
