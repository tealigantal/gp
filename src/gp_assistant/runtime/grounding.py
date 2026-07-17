from __future__ import annotations

import re

from ..contracts.objects import ReplyBundle, Judgment


def _serenity_payload(entry) -> dict:
    return dict(
        (entry.pick.explain_context or {}).get("serenity")
        or (entry.pick.meta or {}).get("serenity")
        or {}
    )


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
            serenity = _serenity_payload(pick)
            allowed_fact_ids.update(str(item) for item in (serenity.get('fact_ids') or []) if str(item))
    serenity_refs = {str(item) for item in (reply.evidence_refs or []) if str(item).startswith('serfact_')}
    if serenity_refs - allowed_fact_ids:
        raise RuntimeError('reply Serenity facts are outside grounded judgment scope')
    serenity_states: list[tuple[object, dict]] = []
    if canonical is not None:
        for pick in canonical.picks:
            if reply.symbols and pick.symbol not in set(reply.symbols):
                continue
            serenity = _serenity_payload(pick)
            if serenity:
                serenity_states.append((pick, serenity))
    reply_text = str(reply.text or '')

    def _is_binding(item: dict) -> bool:
        weight = item.get('effective_weight') if item.get('effective_weight') is not None else item.get('weight')
        contribution = item.get('score_contribution') if item.get('score_contribution') is not None else item.get('adjustment')
        return (
            str(item.get('policy_state') or '') in {'probation', 'active'}
            and float(weight or 0.0) > 0.0
            and bool(item.get('learning_eligible'))
            and abs(float(contribution or 0.0)) > 1e-12
            and bool(item.get('non_binding')) is False
        )

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
        '增益',
        '上升',
        '增加',
        '拉高',
        '抬升',
        '改善',
        '正贡献',
        '助推',
        '进入',
        '挤进',
    )
    active_state: tuple[object, dict] | None = None
    segments = re.split(
        r"(?<=[。；;，,！？!?])|\n+|(?=但(?:是)?|而(?:且)?)",
        reply_text,
    )
    for segment in segments:
        if not segment.strip():
            continue
        explicit = [
            item
            for item in serenity_states
            if str(getattr(item[0], 'symbol', '') or '') in segment
            or (
                str(getattr(item[0], 'name', '') or '')
                and str(getattr(item[0], 'name', '') or '') in segment
            )
        ]
        if len(explicit) == 1:
            active_state = explicit[0]
        scoped_states = explicit or ([active_state] if active_state is not None else [])
        if not scoped_states and len(serenity_states) == 1:
            scoped_states = list(serenity_states)
            active_state = serenity_states[0]
        mentions_serenity = any(
            token in segment
            for token in (
                'Serenity',
                'Alpha',
                '阿尔法',
                '第九专家',
                '公告',
                '新闻',
            )
        )
        if not mentions_serenity:
            continue
        explicit_non_binding = any(
            token in segment
            for token in (
                '未改变正式',
                '不改变正式',
                '不影响正式',
                '未进入正式排序',
                '不参与正式排序',
                '未影响正式',
                '不影响正式',
                '未推动正式',
                '不推动正式',
                '正式权重为0',
                '正式权重为 0',
                '没有推动排名',
                '没有影响排名',
                '未参与排序',
                '不参与排序',
            )
        ) or bool(
            re.search(
                r"(?:没有|并未|未|不|无)[^。；，,]{0,10}"
                r"(?:推动|影响|改变|参与)[^。；，,]{0,8}"
                r"(?:排名|排序|推荐|分数|评分)",
                segment,
            )
        )
        negated_effect = bool(
            re.search(
                r"(?:没有|并未|未|不|无)[^。；，,]{0,12}"
                r"(?:加分|增益|推动|影响|改变|提升|推高|拉高|抬高|抬升|上升|增加|改善|助推)",
                segment,
            )
        )
        claims_ranking_effect = (
            any(token in segment for token in selection_terms)
            and any(token in segment for token in effect_terms)
            and not explicit_non_binding
            and not negated_effect
        ) or any(
            token in segment
            for token in (
                '新闻加分',
                '公告加分',
                'Serenity加分',
                'Serenity 加分',
                '公告催化',
            )
        ) and not negated_effect
        discusses_binding = bool(
            claims_ranking_effect
            or explicit_non_binding
            or (
                any(token in segment for token in selection_terms)
                and any(
                    token in segment
                    for token in (
                        *effect_terms,
                        '参与',
                        '纳入',
                    )
                )
            )
        )
        if discusses_binding and len(serenity_states) > 1:
            if not explicit or len(explicit) != 1:
                raise RuntimeError(
                    'Serenity ranking claim has ambiguous candidate scope'
                )
        if explicit_non_binding and (
            not scoped_states
            or any(_is_binding(item) for _, item in scoped_states)
        ):
            raise RuntimeError(
                'binding Serenity evidence cannot be described as non-binding'
            )
        if claims_ranking_effect and (
            not scoped_states
            or not all(_is_binding(item) for _, item in scoped_states)
        ):
            raise RuntimeError(
                'reference-only Serenity evidence cannot be described as binding'
            )
        statuses = {
            str(item.get('status') or '')
            for _, item in scoped_states
            if item.get('status')
        }
        absence_claim = any(
            token in segment for token in ('没有', '无', '未看到', '未发现')
        ) and any(
            token in segment for token in ('利空', '负面', '坏消息', '风险')
        )
        positive_safety_claim = any(
            token in segment
            for token in ('公告面安全', '新闻面安全', '因此安全', '所以安全')
        )
        if (absence_claim or positive_safety_claim) and (
            not scoped_states
            or (
                statuses
                and statuses
                <= {'no_relevant_evidence', 'stale', 'source_error', 'not_ready'}
            )
        ):
            raise RuntimeError(
                'missing Serenity evidence cannot be asserted as positive evidence'
            )
    if judgment.candidate_comparison is not None:
        view = judgment.candidate_comparison
        if view.selected_symbol and view.selected_symbol not in set(view.candidate_scope or view.compared_symbols):
            raise RuntimeError('candidate selection is outside grounded scope')
    if judgment.intraday_situation is not None and not judgment.intraday_situation.verified:
        text = str(reply.text or "")
        source = str(judgment.intraday_situation.source or "")
        if source == "unverified_user_input" and not any(token in text for token in ("你提供", "用户提供", "未能验证", "按你给")):
            raise RuntimeError('unverified intraday input must be disclosed')
