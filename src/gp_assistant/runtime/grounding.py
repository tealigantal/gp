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
    if judgment.candidate_comparison is not None:
        allowed.update(judgment.candidate_comparison.compared_symbols)
        if judgment.candidate_comparison.selected_symbol:
            allowed.add(judgment.candidate_comparison.selected_symbol)
    if judgment.intraday_situation is not None and judgment.intraday_situation.symbol:
        allowed.add(judgment.intraday_situation.symbol)
    # lightweight grounding: symbols in bundle must be subset of judgment-derived symbols
    if set(reply.symbols) - allowed:
        raise RuntimeError('reply symbols are not grounded in judgment')
    if judgment.candidate_comparison is not None:
        view = judgment.candidate_comparison
        if view.selected_symbol and view.selected_symbol not in set(view.candidate_scope or view.compared_symbols):
            raise RuntimeError('candidate selection is outside grounded scope')
    if judgment.intraday_situation is not None and not judgment.intraday_situation.verified:
        text = str(reply.text or "")
        source = str(judgment.intraday_situation.source or "")
        if source == "unverified_user_input" and not any(token in text for token in ("你提供", "用户提供", "未能验证", "按你给")):
            raise RuntimeError('unverified intraday input must be disclosed')
