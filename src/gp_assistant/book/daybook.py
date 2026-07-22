from __future__ import annotations

from typing import Any, Dict

from ..contracts.objects import AdvicePick, DayBook
from ..evidence.market_service import build_day_selection
from ..runtime.utils import now_iso
from ..runtime.producer import SELECTION_POLICY, producer_metadata


def _first_not_none(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None:
            return value
    return default


def _pick_style(item: Dict[str, Any]) -> str:
    risk_flags = [str(x) for x in (item.get('risk_flags') or [])]
    ranking_score = float((item.get('ranking') or {}).get('ranking_score') or item.get('ranking_score') or 0.0)
    if any('uncertainty' in x.lower() or 'drawdown' in x.lower() for x in risk_flags):
        return 'aggressive'
    if ranking_score >= 0.0008:
        return 'balanced'
    return 'stable'


def _map_pick(rank: int, item: Dict[str, Any]) -> AdvicePick:
    trade_plan = item.get('trade_plan') or {}
    diag = trade_plan.get('diagnostics') or {}
    symbol = str(item.get('symbol') or item.get('code') or '').strip()
    probability = dict(item.get('probability') or {})
    risk = dict(item.get('risk') or {})
    ranking = dict(item.get('ranking') or {})
    signal = dict(item.get('signal') or {})
    adaptive = dict(item.get('adaptive_policy') or {})
    evidence = dict(probability.get('evidence') or {})
    adaptive_score = float(_first_not_none(adaptive.get('adaptive_score'), item.get('adaptive_score'), default=0.0))
    decision_score = float(adaptive.get('decision_score') if adaptive.get('decision_score') is not None else item.get('decision_score') if item.get('decision_score') is not None else adaptive_score)
    # Prefer user-visible fields; do not leak debug explain
    user_thesis = item.get('user_thesis')
    why_selected_text = item.get('why_selected_text')
    thesis_fallback = item.get('thesis')
    serenity = {
        'status': adaptive.get('serenity_status') or item.get('serenity_status') or 'not_ready',
        'policy_state': adaptive.get('serenity_policy_state') or item.get('serenity_policy_state') or 'warming',
        'effective_weight': _first_not_none(adaptive.get('serenity_weight'), item.get('serenity_weight'), default=0.0),
        'alpha_value': adaptive.get('serenity_alpha_value') if adaptive.get('serenity_alpha_value') is not None else item.get('serenity_alpha_value', 0.0),
        'score_contribution': _first_not_none(adaptive.get('serenity_adjustment'), item.get('serenity_adjustment'), default=0.0),
        'decision_score': decision_score,
        'fact_ids': list(adaptive.get('serenity_fact_ids') or item.get('serenity_fact_ids') or []),
        'facts': list(item.get('serenity_facts') or []),
        'learning_eligible': bool(adaptive.get('serenity_learning_eligible', item.get('serenity_learning_eligible', False))),
        'target_id': adaptive.get('serenity_target_id') or item.get('serenity_target_id'),
        'source_run_id': adaptive.get('serenity_source_run_id') or item.get('serenity_source_run_id'),
        'input_hash': adaptive.get('serenity_input_hash') or item.get('serenity_input_hash'),
        'lineage': dict(adaptive.get('serenity_lineage') or item.get('serenity_lineage') or {}),
        'reference_snapshot_id': item.get('serenity_reference_snapshot_id'),
        'non_binding': bool(adaptive.get('serenity_non_binding', item.get('serenity_non_binding', True))),
    }
    return AdvicePick(
        symbol=symbol,
        name=item.get('name'),
        rank=rank,
        strategy_id=str(item.get('signal_type') or signal.get('signal_type') or ''),
        industry=str(item.get('industry') or item.get('theme') or '').strip() or None,
        thesis=str(user_thesis or thesis_fallback or ''),
        entry_plan=trade_plan.get('entry') or item.get('entry_plan') or {},
        stop_plan=trade_plan.get('stop') or item.get('stop_plan') or {},
        take_profit_plan=trade_plan.get('take_profit') or item.get('take_profit_plan') or {},
        scores={
            'final': decision_score,
            'adaptive': adaptive_score,
            'serenity_adjustment': float(_first_not_none(adaptive.get('serenity_adjustment'), item.get('serenity_adjustment'), default=0.0)),
            'serenity_alpha': float(_first_not_none(adaptive.get('serenity_alpha_value'), item.get('serenity_alpha_value'), default=0.0)),
            'ranking': float(ranking.get('ranking_score') or 0.0),
            'probability': float(probability.get('up_probability_3d') or 0.0),
            'calibrated_probability': float(adaptive.get('calibrated_probability') or item.get('calibrated_probability') or 0.0),
            'expected_return': float(probability.get('expected_return_3d') or 0.0),
            'execution_quality': float(risk.get('execution_quality') or 0.0),
            'confidence': float(adaptive.get('confidence') or probability.get('confidence') or 0.0),
            'reward_risk': float(diag.get('reward_risk') or 0.0),
            'feature_coverage': float(adaptive.get('feature_coverage') or item.get('feature_coverage') or 0.0),
        },
        risk_flags=list(
            dict.fromkeys(
                str(flag)
                for flag in [*list(item.get('risk_flags') or []), *list(risk.get('risk_flags') or [])]
                if str(flag)
            )
        ),
        why_selected=str(why_selected_text or ''),
        why_not_others=[str(x) for x in (item.get('why_not') or [])],
        evidence_refs=[symbol],
        style_label=_pick_style(item),
        meta={
            'execution_state': str(diag.get('execution_state') or ''),
            'actionable': bool(diag.get('actionable') is True),
            'reason_codes': [str(x) for x in (item.get('reason_codes') or [])],
            'daily_last_date': item.get('last_date'),
            'daily_freshness_state': item.get('daily_freshness_state'),
            'signal_type': item.get('signal_type') or signal.get('signal_type'),
            'sample_size': evidence.get('sample_size'),
            'effective_sample_size': evidence.get('effective_sample_size'),
            'mean_similarity': evidence.get('mean_similarity'),
            'uncertainty': probability.get('uncertainty'),
            'decision_context_snapshot_id': item.get('decision_context_snapshot_id'),
            'rejected_reason': item.get('rejected_reason'),
            'adaptive_policy': adaptive,
            'adaptive_score': _first_not_none(adaptive.get('adaptive_score'), item.get('adaptive_score')),
            'calibrated_probability': _first_not_none(adaptive.get('calibrated_probability'), item.get('calibrated_probability')),
            'recommendation_strength': adaptive.get('recommendation_strength') or item.get('recommendation_strength'),
            'adaptive_action': adaptive.get('action') or item.get('adaptive_action'),
            'feature_coverage': _first_not_none(adaptive.get('feature_coverage'), item.get('feature_coverage')),
            'expert_scores': dict(adaptive.get('expert_scores') or item.get('expert_scores') or {}),
            'expert_weights': dict(adaptive.get('expert_weights') or item.get('expert_weights') or {}),
            'expert_contributions': dict(adaptive.get('expert_contributions') or item.get('expert_contributions') or {}),
            'missing_features': list(adaptive.get('missing_features') or item.get('missing_features') or []),
            'serenity': serenity,
        },
        explain_context={'serenity': serenity},
        signal=signal,
        probability=probability,
        risk=risk,
        ranking=ranking,
        historical_cases=list(item.get('historical_cases') or []),
        decision_context_snapshot_id=item.get('decision_context_snapshot_id'),
    )


def build_daybook(
    trading_day: str,
    *,
    topk: int = 10,
    reserve_count: int = 2,
    risk_profile: str = 'normal',
    decision_trade_day: str | None = None,
    observed_at: str | None = None,
) -> DayBook:
    raw = build_day_selection(
        trading_day,
        topk=topk,
        risk_profile=risk_profile,
        decision_trade_day=decision_trade_day,
        observed_at=observed_at,
    )
    selection_policy = str((raw.get('debug') or {}).get('selection_policy') or '')
    if selection_policy != SELECTION_POLICY:
        raise RuntimeError(f'incompatible_selection_policy:{selection_policy or "missing"}')
    freshness = raw.get('daily_freshness') or {}
    universe_quality = dict(raw.get('universe_quality') or {})
    candidate_universe = dict(universe_quality or raw.get('candidate_universe') or {})
    decision = str(raw.get('decision') or '')
    product_candidates_ready = bool(candidate_universe.get('complete')) and decision == 'recommend'
    picks = [
        _map_pick(i + 1, item)
        for i, item in enumerate((raw.get('picks') or []) if product_candidates_ready else [])
        if str(item.get('symbol') or item.get('code') or '').strip()
    ]
    reserve: list[str] = []
    reserve_picks: list[AdvicePick] = []
    pick_symbols = {p.symbol for p in picks}
    for cand in (raw.get('candidate_pool') or []) if product_candidates_ready else []:
        sym = str(cand.get('symbol') or cand.get('code') or '').strip()
        if not dict(cand.get('adaptive_policy') or {}) or bool(cand.get('hard_block')):
            continue
        if sym and sym not in reserve and sym not in pick_symbols:
            reserve.append(sym)
            reserve_picks.append(_map_pick(len(picks) + len(reserve_picks) + 1, cand))
        if len(reserve) >= reserve_count:
            break
    return DayBook(
        trading_day=trading_day,
        generated_at=now_iso(),
        regime=raw.get('env') or {},
        tradeable=bool(raw.get('tradeable', bool(picks))),
        reason=raw.get('message') or raw.get('reason'),
        themes=[],
        picks=picks,
        reserve_picks=reserve_picks,
        reserve_symbols=reserve,
        source_meta={
            'raw_keys': sorted(list(raw.keys())),
            'topk': topk,
            'reserve_count': reserve_count,
            'risk_profile': risk_profile,
            'daily_freshness': freshness,
            'candidate_universe': candidate_universe,
            'universe_quality': universe_quality,
            'decision_context_snapshot_id': raw.get('decision_context_snapshot_id'),
            'serenity_reference_snapshot_id': raw.get('serenity_reference_snapshot_id'),
            'serenity_target_id': raw.get('serenity_target_id'),
            'serenity_candidate_target': dict(raw.get('serenity_candidate_target') or {}),
            'serenity_native_ready': bool(raw.get('serenity_native_ready')),
            'serenity_formula_version': raw.get('serenity_formula_version'),
            'serenity_policy_snapshot': dict(raw.get('serenity_policy_snapshot') or {}),
            'serenity_source_run_id': raw.get('serenity_source_run_id'),
            'serenity_readiness_revision': raw.get('serenity_readiness_revision'),
            'serenity_semantic_revision': raw.get('serenity_semantic_revision'),
            'serenity_poll_finished_at': raw.get('serenity_poll_finished_at'),
            'serenity_poll_expires_at': raw.get('serenity_poll_expires_at'),
            'serenity_native_attestation': dict(raw.get('serenity_native_attestation') or {}),
            '_deferred_persistence': dict(raw.get('_deferred_persistence') or {}),
            'decision': raw.get('decision'),
            'decision_reason': raw.get('reason'),
            'selection_policy': selection_policy,
        },
        producer=producer_metadata(),
    )
