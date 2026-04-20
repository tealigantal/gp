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
    if frame.request == 'chat':
        # No trading evidence for chat
        return need
    if frame.request == 'recommend':
        need['publish_run'] = True
        need['need_validation'] = True
        return need
    if frame.request == 'explain':
        # market/run explain: no subject entry needed; symbol/pick explain requires subject
        if frame.subject in ('market', 'run'):
            need['need_active_run'] = (frame.subject == 'run')
        else:
            need['need_active_run'] = True
            need['need_subject_entry'] = True
        # history mode: allow previous_run for explicit references
        try:
            raw = (frame.raw_message or '').strip()
            if any(k in raw for k in ['上一轮', '上一次', '前一次', '历史']):
                need['need_previous_run'] = True
        except Exception:
            pass
        return need
    if frame.request == 'live_check':
        need['need_subject_entry'] = True
        return need
    if frame.request == 'compare':
        need['need_compare_entries'] = True
        try:
            raw = (frame.raw_message or '').strip()
            if any(k in raw for k in ['上一轮', '上一次', '前一次', '历史']):
                need['need_previous_run'] = True
        except Exception:
            pass
        return need
    if frame.request == 'exit':
        need['need_subject_entry'] = True
        need['need_portfolio'] = True
        try:
            raw = (frame.raw_message or '').strip()
            if any(k in raw for k in ['上一轮', '上一次', '前一次', '历史']):
                need['need_previous_run'] = True
        except Exception:
            pass
        return need
    if frame.request == 'run_change':
        need['need_active_run'] = True
        need['need_previous_run'] = True
        return need
    return need
