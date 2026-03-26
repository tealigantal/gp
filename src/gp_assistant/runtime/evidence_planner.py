from __future__ import annotations

from typing import Any, Dict

from ..contracts.objects import TurnFrame


def plan_evidence(frame: TurnFrame) -> Dict[str, Any]:
    need = {
        'need_active_run': False,
        'need_previous_run': False,
        'need_subject_entry': False,
        'need_compare_entries': False,
        'need_validation': False,
        'need_portfolio': False,
        'publish_run': False,
    }
    if frame.request == 'recommend':
        need['publish_run'] = True
        need['need_validation'] = True
    elif frame.request == 'live_check':
        need['need_subject_entry'] = True
    elif frame.request == 'compare':
        need['need_compare_entries'] = True
    elif frame.request == 'exit':
        need['need_subject_entry'] = True
        need['need_portfolio'] = True
    elif frame.request == 'run_change':
        need['need_active_run'] = True
        need['need_previous_run'] = True
    else:
        need['need_active_run'] = True
    return need
