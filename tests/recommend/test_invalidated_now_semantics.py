from __future__ import annotations

from gp_assistant.selection_engine.validators import validate_pick_artifact_v2


def test_invalidated_now_only_blocks_actionable():
    obj = {
        'run_id': 'X', 'as_of': 'X', 'degraded': False, 'tradeable': True,
        'symbols': ['S1'], 'themes': [],
        'items': [
            {'pick_id':'X:S1','symbol':'S1','execution_state':'actionable','actionable':True,
             'invalidated_now': False, 'invalidation': ['close_below_S1']}
        ],
    }
    ok, errs, _ = validate_pick_artifact_v2(obj)
    # Should not error just because invalidation list is non-empty
    assert ok, errs

    obj2 = {
        'run_id': 'X', 'as_of': 'X', 'degraded': False, 'tradeable': True,
        'symbols': ['S1'], 'themes': [],
        'items': [
            {'pick_id':'X:S1','symbol':'S1','execution_state':'actionable','actionable':True,
             'invalidated_now': True, 'invalidation': []}
        ],
    }
    ok2, errs2, _ = validate_pick_artifact_v2(obj2)
    assert not ok2 and any('invalidated_now' in e for e in errs2)
