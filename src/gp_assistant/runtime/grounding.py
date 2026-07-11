from __future__ import annotations

from ..contracts.objects import ReplyBundle, Judgment


def validate_reply(reply: ReplyBundle, judgment: Judgment) -> None:
    allowed: set[str] = set()
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
    allowed_fact_ids: set[str] = set()
    canonical = judgment.canonical_run or judgment.run
    if canonical is not None:
        for pick in canonical.picks:
            if reply.symbols and pick.symbol not in set(reply.symbols):
                continue
            serenity = dict((pick.explain_context or {}).get('serenity') or {})
            allowed_fact_ids.update(str(item) for item in (serenity.get('fact_ids') or []) if str(item))
    serenity_refs = {str(item) for item in (reply.evidence_refs or []) if str(item).startswith('serfact_')}
    if serenity_refs - allowed_fact_ids:
        raise RuntimeError('reply Serenity facts are outside grounded judgment scope')
    serenity_states = []
    if canonical is not None:
        for pick in canonical.picks:
            if reply.symbols and pick.symbol not in set(reply.symbols):
                continue
            serenity = dict((pick.explain_context or {}).get('serenity') or {})
            if serenity:
                serenity_states.append(serenity)
    reply_text = str(reply.text or '')

    def _is_binding(item: dict) -> bool:
        return (
            str(item.get('policy_state') or '') in {'probation', 'active'}
            and float(item.get('weight') or 0.0) > 0.0
            and bool(item.get('learning_eligible'))
            and abs(float(item.get('adjustment') or 0.0)) > 1e-12
            and bool(item.get('non_binding')) is False
        )

    binding = any(_is_binding(item) for item in serenity_states)
    selection_terms = (
        '排名',
        '位次',
        '顺位',
        '排序',
        '顺序',
        '入选',
        '推荐',
        'Top',
        'TOP',
        '分数',
        '权重',
    )
    effect_terms = (
        '改变',
        '调整',
        '提升',
        '推高',
        '抬高',
        '重排',
        '前移',
        '升到',
        '推动',
        '影响',
        '加分',
        '进入',
        '挤进',
    )
    explicit_non_binding = any(
        token in reply_text
        for token in (
            '未改变正式',
            '不改变正式',
            '不影响正式',
            '未进入正式排序',
            '不参与正式排序',
            '正式权重为0',
            '正式权重为 0',
        )
    )
    claims_ranking_effect = (
        any(token in reply_text for token in selection_terms)
        and any(token in reply_text for token in effect_terms)
        and not explicit_non_binding
    ) or any(
        token in reply_text
        for token in ('新闻加分', '公告加分', 'Serenity加分', 'Serenity 加分', '公告催化')
    )
    mentions_serenity = any(token in reply_text for token in ('Serenity', '公告', '新闻'))
    mixed_multi_symbol_binding = (
        len(set(reply.symbols)) > 1
        and bool(serenity_states)
        and not all(_is_binding(item) for item in serenity_states)
    )
    if (not binding or mixed_multi_symbol_binding) and mentions_serenity and claims_ranking_effect:
        raise RuntimeError('reference-only Serenity evidence cannot be described as binding')
    statuses = {str(item.get('status') or '') for item in serenity_states if item.get('status')}
    if statuses and statuses <= {'no_relevant_evidence', 'stale', 'source_error', 'not_ready'}:
        absence_claim = any(
            token in reply_text for token in ('没有', '无', '未看到', '未发现')
        ) and any(
            token in reply_text for token in ('利空', '负面', '坏消息', '风险')
        )
        if absence_claim or any(token in reply_text for token in ('公告面安全',)):
            raise RuntimeError('missing Serenity evidence cannot be asserted as positive evidence')
    if judgment.candidate_comparison is not None:
        view = judgment.candidate_comparison
        if view.selected_symbol and view.selected_symbol not in set(view.candidate_scope or view.compared_symbols):
            raise RuntimeError('candidate selection is outside grounded scope')
    if judgment.intraday_situation is not None and not judgment.intraday_situation.verified:
        text = str(reply.text or "")
        source = str(judgment.intraday_situation.source or "")
        if source == "unverified_user_input" and not any(token in text for token in ("你提供", "用户提供", "未能验证", "按你给")):
            raise RuntimeError('unverified intraday input must be disclosed')
