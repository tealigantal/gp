from __future__ import annotations

from ..contracts.objects import ReplyBundle, Judgment


def validate_reply(reply: ReplyBundle, judgment: Judgment) -> None:
    allowed = set(reply.symbols)
    if judgment.run is not None:
        allowed.update(e.symbol for e in judgment.run.picks)
    if judgment.subject_entry is not None:
        allowed.add(judgment.subject_entry.symbol)
    if judgment.single_stock_analysis is not None:
        allowed.add(judgment.single_stock_analysis.symbol)
    # lightweight grounding: symbols in bundle must be subset of judgment-derived symbols
    if set(reply.symbols) - allowed:
        raise RuntimeError('reply symbols are not grounded in judgment')
