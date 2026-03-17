from __future__ import annotations

from gp_assistant.recommend.artifact_store import _enrich_scores_and_gate
from gp_assistant.validation.strategy_health import save_strategy_health


def _make_item():
    return {
        'symbol': 'AAA',
        'strategy': 'TMP_H',
        'execution_state': 'actionable',
        'actionable': True,
        'reward_risk': 1.0,
        'liquidity_grade': 'A',
        'invalidation': [],
        'invalidated_now': False,
        'evidence': {},
    }


def test_strategy_health_penalty_applied():
    # Healthy: no penalty
    save_strategy_health('TMP_H', {
        'status': 'healthy', 'reason_codes': [], 'paper_trade_summary': {}, 'event_summary': {}, 'walkforward_summary': {},
    })
    obj = {'degraded': False, 'tradeable': True, 'items': [_make_item()]}
    _enrich_scores_and_gate(obj)
    rel_healthy = float(obj['items'][0]['reliability_score'])
    final_healthy = float(obj['items'][0]['final_score'])

    # Degraded: lower reliability and final
    save_strategy_health('TMP_H', {
        'status': 'degraded', 'reason_codes': ['x'], 'paper_trade_summary': {}, 'event_summary': {}, 'walkforward_summary': {},
    })
    obj2 = {'degraded': False, 'tradeable': True, 'items': [_make_item()]}
    _enrich_scores_and_gate(obj2)
    rel_degraded = float(obj2['items'][0]['reliability_score'])
    final_degraded = float(obj2['items'][0]['final_score'])
    assert rel_degraded < rel_healthy
    assert final_degraded < final_healthy

    # Killed: even lower
    save_strategy_health('TMP_H', {
        'status': 'killed', 'reason_codes': ['x'], 'paper_trade_summary': {}, 'event_summary': {}, 'walkforward_summary': {},
    })
    obj3 = {'degraded': False, 'tradeable': True, 'items': [_make_item()]}
    _enrich_scores_and_gate(obj3)
    rel_killed = float(obj3['items'][0]['reliability_score'])
    final_killed = float(obj3['items'][0]['final_score'])
    assert rel_killed < rel_degraded
    assert final_killed < final_degraded

