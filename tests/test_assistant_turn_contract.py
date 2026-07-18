from __future__ import annotations

import pytest

from gp_assistant.contracts.api import ChatResponse


def test_persisted_reply_is_projected_as_the_only_narrative_text():
    reply = "这是已经通过校验并提交的真实 LLM 回答。"
    projected = ChatResponse.project_persisted(
        {
            "session_id": "session-1",
            "client_turn_id": "turn-1",
            "snapshot_id": "snapshot-1",
            "decision": "informational",
            "reply": reply,
            "message": {"message_kind": "chat"},
            "symbols": [],
            "llm_trace": {"source": "real_llm"},
        },
        assistant_content=reply,
        session_id="session-1",
        client_turn_id="turn-1",
    )

    assert projected["reply"] == reply
    assert projected["message"]["narrative_text"] == reply
    assert projected["message"]["message_kind"] == "chat"
    assert projected["llm_trace"] == {"source": "real_llm"}


def test_legacy_payload_without_reply_uses_only_its_committed_content():
    committed_content = "旧会话中实际保存的回答。"
    projected = ChatResponse.project_persisted(
        {"message": {"message_kind": "chat"}},
        assistant_content=committed_content,
        session_id="legacy-session",
        client_turn_id="legacy-turn",
    )

    assert projected["reply"] == committed_content
    assert projected["message"]["narrative_text"] == committed_content


def test_malformed_legacy_metadata_cannot_hide_committed_content():
    committed_content = "即使旧 metadata 损坏，也必须显示已保存的回答。"
    projected = ChatResponse.project_persisted(
        {"message": "not-an-object", "symbols": "not-an-array"},
        assistant_content=committed_content,
        session_id="legacy-session",
        client_turn_id="legacy-turn",
    )

    assert projected["message"] == {
        "message_kind": "chat",
        "narrative_text": committed_content,
    }
    assert projected["symbols"] == []


def test_empty_assistant_content_cannot_be_projected_as_a_successful_turn():
    with pytest.raises(ValueError, match="assistant_turn_required_text_missing"):
        ChatResponse.project_persisted(
            {"message": {"message_kind": "chat"}},
            assistant_content="",
            session_id="broken-session",
            client_turn_id="broken-turn",
        )
