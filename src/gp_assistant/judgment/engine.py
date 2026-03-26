from __future__ import annotations

from ..contracts.objects import EvidencePack, Judgment, TurnFrame
from .recommend import make_recommendation
from .followup import judge_followup
from .compare import compare_entries
from .exit import judge_exit


def make_judgment(session_id: str, frame: TurnFrame, evidence: EvidencePack) -> Judgment:
    topk = int(frame.constraints.get('topk') or 3)
    if frame.request == 'recommend':
        return make_recommendation(session_id=session_id, book=evidence.book, topk=topk)
    if frame.request == 'compare':
        entries = evidence.compare_entries or ([evidence.subject_entry] if evidence.subject_entry else [])
        return compare_entries(session_id=session_id, entries=entries)
    if frame.request == 'exit' and evidence.subject_entry is not None:
        return judge_exit(evidence.subject_entry, evidence.portfolio_slice)
    if evidence.subject_entry is not None:
        return judge_followup(session_id=session_id, entry=evidence.subject_entry)
    # default to recommendation if subject could not be anchored
    return make_recommendation(session_id=session_id, book=evidence.book, topk=topk)
