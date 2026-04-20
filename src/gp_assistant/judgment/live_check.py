from __future__ import annotations

from ..contracts.objects import Judgment, BoardEntry


def judge_live_check(entry: BoardEntry) -> Judgment:
    # Use pulse when available; otherwise fall back to execution fields
    pulse = entry.pulse
    if pulse is not None:
        state = pulse.execution_state
        invalidated = pulse.invalidated
        summary = f"live_check: state={state}, invalidated={invalidated}"
    else:
        summary = f"live_check: state={entry.execution_state}, can_open={entry.can_open}, invalidated={entry.invalidated}"
    return Judgment(kind='live_check', summary=summary, subject_entry=entry)

