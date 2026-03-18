from gp_assistant.chat import session_store as store
from gp_assistant.chat.orchestrator import handle_message


def test_exit_decision_inherits_focus():
    sid = store.ensure_session('c_focus')
    store.set_focus(sid, '600519')
    out = handle_message(sid, '要不要减仓')
    assert isinstance(out.get('reply'), str)
    assert any(k in out['reply'] for k in ['HOLD','REDUCE','SELL','WATCH'])

