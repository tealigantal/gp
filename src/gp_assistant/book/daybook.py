from __future__ import annotations

from typing import Any, Dict

from ..contracts.objects import AdvicePick, DayBook
from ..evidence.market_service import build_day_selection
from ..runtime.utils import now_iso
from ..runtime.producer import SELECTION_POLICY, producer_metadata


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
    adaptive_score = float(adaptive.get('adaptive_score') or item.get('adaptive_score') or ranking.get('ranking_score') or item.get('ranking_score') or 0.0)
    decision_score = float(adaptive.get('decision_score') if adaptive.get('decision_score') is not None else item.get('decision_score') if item.get('decision_score') is not None else adaptive_score)
    # Prefer user-visible fields; do not leak debug explain
    user_thesis = item.get('user_thesis')
    why_selected_text = item.get('why_selected_text')
    thesis_fallback = item.get('thesis')
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
            'serenity_adjustment': float(adaptive.get('serenity_adjustment') or item.get('serenity_adjustment') or 0.0),
            'ranking': float(ranking.get('ranking_score') or 0.0),
            'probability': float(probability.get('up_probability_3d') or 0.0),
            'calibrated_probability': float(adaptive.get('calibrated_probability') or item.get('calibrated_probability') or 0.0),
            'expected_return': float(probability.get('expected_return_3d') or 0.0),
            'execution_quality': float(risk.get('execution_quality') or 0.0),
            'confidence': float(adaptive.get('confidence') or probability.get('confidence') or 0.0),
            'reward_risk': float(diag.get('reward_risk') or 0.0),
            'feature_coverage': float(adaptive.get('feature_coverage') or item.get('feature_coverage') or 0.0),
        },
        risk_flags=[str(x) for x in (item.get('risk_flags') or [])],
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
            'adaptive_score': adaptive.get('adaptive_score') or item.get('adaptive_score'),
            'calibrated_probability': adaptive.get('calibrated_probability') or item.get('calibrated_probability'),
            'recommendation_strength': adaptive.get('recommendation_strength') or item.get('recommendation_strength'),
            'adaptive_action': adaptive.get('action') or item.get('adaptive_action'),
            'feature_coverage': adaptive.get('feature_coverage') or item.get('feature_coverage'),
            'expert_scores': dict(adaptive.get('expert_scores') or item.get('expert_scores') or {}),
            'expert_contributions': dict(adaptive.get('expert_contributions') or item.get('expert_contributions') or {}),
            'missing_features': list(adaptive.get('missing_features') or item.get('missing_features') or []),
            'serenity': {
                'status': adaptive.get('serenity_status') or item.get('serenity_status') or 'not_ready',
                'policy_state': adaptive.get('serenity_policy_state') or item.get('serenity_policy_state') or 'warming',
                'weight': adaptive.get('serenity_weight') if adaptive.get('serenity_weight') is not None else item.get('serenity_weight', 0.0),
                'adjustment': adaptive.get('serenity_adjustment') if adaptive.get('serenity_adjustment') is not None else item.get('serenity_adjustment', 0.0),
                'decision_score': decision_score,
                'fact_ids': list(adaptive.get('serenity_fact_ids') or item.get('serenity_fact_ids') or []),
                'learning_eligible': bool(adaptive.get('serenity_learning_eligible', item.get('serenity_learning_eligible', False))),
                'reference_snapshot_id': item.get('serenity_reference_snapshot_id'),
                'non_binding': bool(adaptive.get('serenity_non_binding', item.get('serenity_non_binding', True))),
                'would_change_topk': bool(adaptive.get('serenity_would_change_topk', item.get('serenity_would_change_topk', False))),
                'reference_would_change_topk': bool(adaptive.get('serenity_reference_would_change_topk', item.get('serenity_reference_would_change_topk', False))),
            },
        },
        signal=signal,
        probability=probability,
        risk=risk,
        ranking=ranking,
        historical_cases=list(item.get('historical_cases') or []),
        decision_context_snapshot_id=item.get('decision_context_snapshot_id'),
    )


def build_daybook(trading_day: str, *, topk: int = 10, reserve_count: int = 2, risk_profile: str = 'normal') -> DayBook:
    raw = build_day_selection(trading_day, topk=topk, risk_profile=risk_profile)
    selection_policy = str((raw.get('debug') or {}).get('selection_policy') or '')
    if selection_policy != SELECTION_POLICY:
        raise RuntimeError(f'incompatible_selection_policy:{selection_policy or "missing"}')
    freshness = raw.get('daily_freshness') or {}
    picks = [_map_pick(i + 1, item) for i, item in enumerate(raw.get('picks') or []) if str(item.get('symbol') or item.get('code') or '').strip()]
    reserve: list[str] = []
    reserve_picks: list[AdvicePick] = []
    pick_symbols = {p.symbol for p in picks}
    for cand in raw.get('candidate_pool') or []:
        sym = str(cand.get('symbol') or cand.get('code') or '').strip()
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
            'decision_context_snapshot_id': raw.get('decision_context_snapshot_id'),
            'serenity_reference_snapshot_id': raw.get('serenity_reference_snapshot_id'),
            'decision': raw.get('decision'),
            'selection_policy': selection_policy,
        },
        producer=producer_metadata(),
    )
