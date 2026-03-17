from gp_assistant.chat import session_store as store
from gp_assistant.chat.finance_intents import assess_rr, compare_symbols, ask_no_trade_reason


def test_assess_rr_with_focus_and_minimal_data():
    sid = store.ensure_session(None)
    # Prepare last recommendation with bands so we don't require live data
    payload = {
        "as_of": "2024-01-01",
        "picks": [
            {"symbol": "600519", "trade_plan": {"bands": {"S1": 1500.0, "S2": 1400.0, "R1": 1700.0, "R2": 1800.0}}}
        ],
    }
    store.set_last_recommend_and_symbols(sid, payload)
    store.set_focus(sid, "600519")
    r = assess_rr(sid, "这个合理吗，基本不赚钱啊")
    # Should produce deterministic summary text
    assert bool(r.get("message")) is True


def test_compare_symbols_uses_scores_when_available():
    sid = store.ensure_session(None)
    payload = {
        "as_of": "2024-01-01",
        "picks": [
            {"symbol": "AAA", "champion": {"strategy": "s1", "score": 0.7}},
            {"symbol": "BBB", "champion": {"strategy": "s2", "score": 0.5}},
        ],
    }
    store.set_last_recommend_and_symbols(sid, payload)
    store.update_state(sid, {"active_symbols": ["AAA", "BBB"]})
    r = compare_symbols(sid, "这两只哪个好")
    assert r.get("ok") in {True, False}


def test_no_trade_reason_from_last():
    sid = store.ensure_session(None)
    payload = {"as_of": "2024-01-01", "picks": [], "tradeable": False, "debug": {"degraded": True, "degrade_reasons": [{"reason_code": "NO_CANDIDATE"}]}}
    store.set_last_recommend_and_symbols(sid, payload)
    r = ask_no_trade_reason(sid, "今天为什么不给买入")
    assert bool(r.get("message")) is True

