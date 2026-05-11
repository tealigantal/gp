from __future__ import annotations

import json

from gp_assistant.llm import semantics
from gp_assistant.llm.semantics import AnnouncementRiskAssessment
from gp_assistant.selection_engine import announcements


class _JsonLLM:
    def __init__(self, payload):
        self.payload = payload

    def available(self):
        return True, "ok"

    def chat(self, messages, json_mode=False, temperature=0.0, **kwargs):
        return {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}


def test_turn_semantics_reads_llm_json_not_keywords():
    signals = semantics.analyze_turn_semantics(
        user_message="口语化表达",
        frame={"request": "term_explain"},
        client=_JsonLLM(
            {
                "history_mode": True,
                "refresh_intent": "live",
                "term_text": "收盘有效跌破支撑带",
            }
        ),
    )

    assert signals.history_mode is True
    assert signals.refresh_intent == "live"
    assert signals.term_text == "收盘有效跌破支撑带"


def test_announcement_risk_uses_llm_json_assessment():
    title = "关于控股股东拟转让股份的提示性公告"
    assessment = semantics.assess_announcement_risk(
        [{"title": title}],
        client=_JsonLLM(
            {
                "risk_level": "medium",
                "evidence": [title],
                "reason": "存在治理或持股结构变化风险",
            }
        ),
    )

    assert assessment.risk_level == "medium"
    assert assessment.evidence == [title]
    assert "治理" in (assessment.reason or "")


def test_fetch_announcements_uses_semantic_risk_assessment_without_keyword_fallback(monkeypatch):
    title = "关于控股股东拟转让股份的提示性公告"

    monkeypatch.setattr(announcements, "ensure_query", lambda *args, **kwargs: None)
    monkeypatch.setattr(announcements, "compute_next_range", lambda *args, **kwargs: ("2026-01-01", "2026-01-31"))
    monkeypatch.setattr(announcements, "upsert_items", lambda *args, **kwargs: None)
    monkeypatch.setattr(announcements, "list_items", lambda *args, **kwargs: [{"payload": {"title": title}}])
    monkeypatch.setattr(
        announcements.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network disabled")),
    )
    monkeypatch.setattr(
        announcements,
        "assess_announcement_risk",
        lambda items: AnnouncementRiskAssessment(risk_level="medium", evidence=[title], reason="semantic"),
    )

    result = announcements.fetch_announcements("600519")

    assert result["risk_level"] == "medium"
    assert result["evidence"] == [title]
    assert result["risk_reason"] == "semantic"


def test_fetch_announcements_does_not_keyword_fallback_when_semantic_assessment_fails(monkeypatch):
    title = "关于控股股东减持计划的公告"

    monkeypatch.setattr(announcements, "ensure_query", lambda *args, **kwargs: None)
    monkeypatch.setattr(announcements, "compute_next_range", lambda *args, **kwargs: ("2026-01-01", "2026-01-31"))
    monkeypatch.setattr(announcements, "upsert_items", lambda *args, **kwargs: None)
    monkeypatch.setattr(announcements, "list_items", lambda *args, **kwargs: [{"payload": {"title": title}}])
    monkeypatch.setattr(
        announcements.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network disabled")),
    )
    monkeypatch.setattr(
        announcements,
        "assess_announcement_risk",
        lambda items: (_ for _ in ()).throw(RuntimeError("llm unavailable")),
    )

    result = announcements.fetch_announcements("600519")

    assert result["risk_level"] is None
    assert result["evidence"] == []
    assert "llm unavailable" in result["semantic_error"]
