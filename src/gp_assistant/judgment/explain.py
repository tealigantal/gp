from __future__ import annotations

from typing import Optional

from ..contracts.objects import Judgment, EvidencePack, BoardEntry


def judge_explain(evidence: EvidencePack, *, subject_entry: Optional[BoardEntry] = None) -> Judgment:
    # Market/run explain: rely on book and optionally active_run; no subject_entry needed
    if subject_entry is None:
        daybook = evidence.book.daybook
        tradeable = bool(getattr(daybook, 'tradeable', False))
        reason = getattr(daybook, 'reason', None) or ''
        summary = f"market_explain: tradeable={tradeable}, reason={reason}".strip()
        return Judgment(kind='explain', summary=summary)

    # Symbol/pick explain: use entry thesis/why_selected
    pick = subject_entry.pick
    why = pick.why_selected or ''
    th = pick.thesis or ''
    summary = (why or th or 'symbol_explain')
    return Judgment(kind='explain', summary=summary, subject_entry=subject_entry)

