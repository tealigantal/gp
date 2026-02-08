from __future__ import annotations

from gp_assistant.recommend import agent as rec_agent


def test_recommend_smoke():
    res = rec_agent.run(universe="symbols", symbols=["000001", "000333", "600519"], topk=3)
    assert res.get("env") and res["env"].get("grade")
    if res["env"]["grade"] == "D":
        assert "recovery_conditions" in res["env"]
    # candidate pool can be empty if env=D; else allow >0
    if res["env"]["grade"] != "D":
        assert len(res.get("candidate_pool", [])) >= 1
    # picks trade plan fields present
    for it in res.get("picks", []):
        assert "chip" in it and "band_90_high" in it["chip"]
        assert "announcement_risk" in it
        assert "event_risk" in it
        assert "q_grade" in it
    # checklist length <=5
    assert len(res.get("execution_checklist", [])) <= 5
    assert res.get("disclaimer") == "本内容仅供研究与教育，不构成任何投资建议或收益承诺；市场有风险，决策需独立承担。"

