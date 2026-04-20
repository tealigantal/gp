from __future__ import annotations

from ..contracts.objects import EvidencePack, Judgment, TurnFrame
from .recommend import make_recommendation
from .followup import judge_followup
from .compare import compare_entries
from .exit import judge_exit
from .chat import judge_chat
from .explain import judge_explain
from .live_check import judge_live_check
from .run_change import judge_run_change


def make_judgment(session_id: str, frame: TurnFrame, evidence: EvidencePack) -> Judgment:
    topk = int(frame.constraints.get('topk') or 3)

    if frame.request == 'chat':
        return judge_chat()

    if frame.request == 'recommend':
        # Post-close pending: do not publish a new run; return degraded no_trade
        try:
            if (evidence.book.market_phase == 'POSTCLOSE_PENDING') and (evidence.book.data_status in {'close_pending', 'degraded'}):
                return Judgment(kind='no_trade', summary='收盘后日线确认中（close_pending），请稍后再试。')
        except Exception:
            pass
        return make_recommendation(session_id=session_id, book=evidence.book, topk=topk)

    if frame.request == 'compare':
        entries = evidence.compare_entries or ([evidence.subject_entry] if evidence.subject_entry else [])
        return compare_entries(session_id=session_id, entries=entries)

    if frame.request == 'exit':
        if evidence.subject_entry is None:
            raise ValueError('exit requires subject_entry')
        return judge_exit(evidence.subject_entry, evidence.portfolio_slice)

    if frame.request == 'explain':
        if frame.subject in ('market', 'run'):
            return judge_explain(evidence)
        # symbol/pick explain requires subject_entry
        if evidence.subject_entry is None:
            raise ValueError('explain(symbol/pick) requires subject_entry')
        return judge_explain(evidence, subject_entry=evidence.subject_entry)

    if frame.request == 'live_check':
        if evidence.subject_entry is None:
            raise ValueError('live_check requires subject_entry')
        return judge_live_check(evidence.subject_entry)

    if frame.request == 'run_change':
        return judge_run_change(evidence.active_run, evidence.previous_run)

    raise ValueError(f"Unhandled request: request={frame.request}")
