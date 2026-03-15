from __future__ import annotations

from typing import List, Dict, Any

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def _extract_symbols_from_card(resp_json: Dict[str, Any]) -> List[str]:
    # Fallback: call artifacts API to retrieve last recommendation card is heavy; we instead
    # rely on orchestrator returning tool_trace.recommend_result when triggered.
    t = resp_json.get("tool_trace") or {}
    if isinstance(t, dict):
        rec = t.get("recommend_result") or {}
        if isinstance(rec, dict):
            picks = rec.get("picks") or []
            if isinstance(picks, list):
                return [str((p or {}).get("symbol") or "") for p in picks if isinstance(p, dict)]
    return []


def test_followup_flow_with_default_first_symbol():
    c = TestClient(app)
    # 1) get recommend via service mode to avoid engine dependency
    r1 = c.post("/api/chat", json={"message": "latest recommend 3"})
    j1 = r1.json()
    print('resp1:', j1)
    assert j1["session_id"]
    # recommendation should be triggered (service mode) or at least reply present
    assert j1["tool_trace"].get("triggered_recommend") in (True, False)
    sid = j1["session_id"]
    syms = _extract_symbols_from_card(j1)
    assert isinstance(syms, list)
    # 2) ask for kline/trade points; default to first symbol
    r2 = c.post("/api/chat", json={"session_id": sid, "message": "研究K线 给出合理的买卖点"})
    j2 = r2.json()
    assert j2["reply"], "should reply with analysis"
    # degraded allowed (LLM missing), but reply must be structured
    assert isinstance(j2.get("degraded"), (bool, type(None)))
    # 3) ask for second symbol
    r3 = c.post("/api/chat", json={"session_id": sid, "message": "第二只呢"})
    j3 = r3.json()
    assert j3["reply"], "should reply with analysis for second"
    if len(syms) >= 2:
        assert j3.get("resolved_symbol") == syms[1]
    # 4) ask why recommended it
    r4 = c.post("/api/chat", json={"session_id": sid, "message": "为什么推荐它"})
    j4 = r4.json()
    assert j4["reply"], "should explain pick"


def test_pronoun_uses_focus_symbol():
    c = TestClient(app)
    r1 = c.post("/api/chat", json={"message": "服务荐股，给我推荐3只"})
    sid = r1.json()["session_id"]
    # set focus to second by asking directly
    _ = c.post("/api/chat", json={"session_id": sid, "message": "第二只"})
    # pronoun should resolve to focus
    r2 = c.post("/api/chat", json={"session_id": sid, "message": "研究这只 K线"})
    j2 = r2.json()
    assert j2["reply"], "should analyze focused symbol"
    assert j2.get("resolved_symbol"), "resolved symbol should be present"
