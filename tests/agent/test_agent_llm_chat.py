from __future__ import annotations

import json

import pytest

from gp_assistant.llm import narrate as narrate_module
from gp_assistant.agent_store import (
    AgentStore,
    AgentStoreError,
    SnapshotIntegrityError,
)
from gp_assistant.chat_agent import (
    _current_serenity_reason,
    _display_number,
    _explicit_topk,
    _narration_entry_payload,
    _number_variants,
    _provider_narration_context,
    _resolve_provider_value_tokens,
    _sanitize_frame,
    _validate_narration_authority,
    _validate_narrated_symbols,
    run_chat_turn,
)
from gp_assistant.contracts.objects import AdviceRun, Judgment, ReplyBundle, TurnFrame
from gp_assistant.core.errors import APIError
from gp_assistant.runtime.concern_parser import normalize_turn_frame
from gp_assistant.runtime.grounding import validate_reply
from tests.agent.test_agent_store import make_book, patch_chat_llm


@pytest.mark.parametrize(
    "frame_request", ["term_explain", "chat", "no_trade_explain"]
)
def test_named_serenity_term_cannot_hide_explicit_candidate_request(frame_request):
    frame = TurnFrame(
        frame_id="frame-term",
        raw_message="",
        subject="run",
        request=frame_request,
        freshness="active_run",
        references={},
        constraints={},
        ambiguity={"confidence": 0.9, "notes": [], "needs_clarification": False},
    )

    normalized = _sanitize_frame(
        frame,
        "请概括当前两只候选的计划，并说明 Serenity 是否已经接入。",
    )

    assert normalized.request == "recommend"
    assert normalized.subject == "run"
    assert normalized.constraints["topk"] == 2
    assert "term_text" not in normalized.constraints


def test_explicit_topk_recognizes_chinese_candidate_count():
    assert _explicit_topk("当前前三个候选") == 3


def test_explicit_candidate_plan_wins_after_keyword_normalization():
    message = "请给出当前前三个候选的买入区、止损和第一目标。"
    frame = TurnFrame(
        frame_id="frame-plan",
        raw_message="",
        subject="holding",
        request="exit_decision",
        freshness="next_session_plan",
        references={"symbol": "002415"},
        constraints={},
        ambiguity={},
    )

    # The generic normalizer sees "止损" and classifies an exit request.
    generic = normalize_turn_frame(_sanitize_frame(frame, message))
    assert generic.request == "exit_decision"
    # The final local candidate-scope pass used by run_chat_turn restores the
    # user's concrete Top-N request and removes provider-invented references.
    resolved = _sanitize_frame(generic, message)
    assert resolved.request == "recommend"
    assert resolved.subject == "run"
    assert resolved.references == {}
    assert resolved.constraints["topk"] == 3


def test_two_stage_llm_trace_is_committed_with_snapshot(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    monkeypatch.setattr(
        "gp_assistant.chat_agent.current_llm_call_trace",
        lambda: [
            {"stage": "intent_routing", "success": True, "http_status": 200, "request_model": "test-model", "response_id": "route-1", "response_model": "test-model"},
            {"stage": "tool_evidence", "success": True, "http_status": 200, "request_model": "test-model", "response_id": "narrate-1", "response_model": "test-model"},
        ],
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id="trace-session",
        client_turn_id="trace-turn",
        user_message="推荐",
        store=store,
    )

    assert result["snapshot_id"] == "snapshot-1"
    assert [item["stage"] for item in result["llm_trace"]] == ["intent_routing", "tool_evidence"]
    assistant = store.session_turns("trace-session")[-1]
    assert assistant["payload"]["llm_trace"] == result["llm_trace"]


def test_non_trading_window_keeps_plan_but_marks_it_non_executable(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    book = make_book()
    book.publish_allowed = False
    store.publish_book(book)

    result = run_chat_turn(
        session_id="plan-session",
        client_turn_id="plan-turn",
        user_message="推荐",
        store=store,
    )

    assert result["decision"] == "recommend"
    assert result["message"]["tradeable"] is False
    assert result["message"]["reason"] == "next_session_plan"
    assert [item["symbol"] for item in result["message"]["picks"]] == ["600519"]


def test_old_protocol_snapshot_is_blocked_without_candidate_leak(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    book = make_book()
    book.daybook.source_meta["selection_policy"] = "adaptive_policy_single_path"

    with pytest.raises(
        SnapshotIntegrityError, match="native_snapshot_policy_incompatible"
    ):
        store.publish_book(book)

    assert store.current_snapshot() is None


def test_explicit_refresh_never_reuses_bound_snapshot(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id="refresh-session",
        client_turn_id="refresh-turn",
        user_message="刷新数据后重新推荐",
        store=store,
    )

    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "new_snapshot_required_for_refresh"
    assert result["symbols"] == []


def test_grounding_failure_does_not_bind_empty_session(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    monkeypatch.setattr(
        "gp_assistant.chat_agent.render_reply",
        lambda payload: "600519 的目标价是 12345.67 元。",
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent.repair_reply",
        lambda payload, validation_error: "600519 的目标价仍是 12345.67 元。",
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    with pytest.raises(APIError) as caught:
        run_chat_turn(
            session_id="failed-session",
            client_turn_id="failed-turn",
            user_message="推荐",
            store=store,
        )

    assert caught.value.status_code == 502
    assert store.stats()["sessions"] == 0
    assert store.session_turns("failed-session") == []


def test_grounding_violation_uses_one_real_llm_repair_before_commit(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    monkeypatch.setattr(
        "gp_assistant.chat_agent.render_reply",
        lambda payload: "600519建议轻仓跟踪。",
    )
    observed = {}

    def repair(payload, *, validation_error):
        observed["payload"] = payload
        observed["validation_error"] = validation_error
        return "600519保持下一交易窗口计划，并控制仓位和风险。"

    monkeypatch.setattr("gp_assistant.chat_agent.repair_reply", repair)
    monkeypatch.setattr(
        "gp_assistant.chat_agent.current_llm_call_trace",
        lambda: [
            {
                "stage": "intent_routing",
                "success": True,
                "http_status": 200,
                "request_model": "test-model",
                "response_id": "route-1",
                "response_model": "test-model",
            },
            {
                "stage": "tool_evidence",
                "success": True,
                "http_status": 200,
                "request_model": "test-model",
                "response_id": "narrate-1",
                "response_model": "test-model",
            },
            {
                "stage": "tool_evidence_repair",
                "success": True,
                "http_status": 200,
                "request_model": "test-model",
                "response_id": "repair-1",
                "response_model": "test-model",
            },
        ],
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id="repair-session",
        client_turn_id="repair-turn",
        user_message="推荐",
        store=store,
    )

    assert result["reply"] == "600519保持下一交易窗口计划，并控制仓位和风险。"
    assert "invents_position_sizing" in observed["validation_error"]
    assert "rejected_draft" not in observed["payload"]
    assert [item["stage"] for item in result["llm_trace"]] == [
        "intent_routing",
        "tool_evidence",
        "tool_evidence_repair",
    ]
    assert store.stats()["sessions"] == 1


def test_same_client_turn_id_with_different_message_is_conflict(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    run_chat_turn(
        session_id="idempotent-session",
        client_turn_id="same-id",
        user_message="推荐",
        store=store,
    )

    with pytest.raises(AgentStoreError, match="client_turn_id_content_conflict"):
        run_chat_turn(
            session_id="idempotent-session",
            client_turn_id="same-id",
            user_message="解释 600519",
            store=store,
        )


def test_missing_real_llm_stage_does_not_commit(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    monkeypatch.setattr(
        "gp_assistant.chat_agent.current_llm_call_trace",
        lambda: [
            {"stage": "intent_routing", "success": True, "http_status": 200, "request_model": "test-model", "response_model": "test-model", "response_id": "route-only"}
        ],
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    with pytest.raises(APIError) as caught:
        run_chat_turn(
            session_id="missing-stage-session",
            client_turn_id="missing-stage-turn",
            user_message="推荐",
            store=store,
        )

    assert caught.value.status_code == 502
    assert caught.value.detail["reason"].endswith(
        "product_llm_trace_missing_real_two_stage_evidence"
    )
    assert store.session_turns("missing-stage-session") == []


def test_narration_rejects_swapped_price_fields_and_nontradeable_action():
    context = {
        "judgment_result": {"decision": "no_trade", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "entry_plan": {"price": 100},
                "stop_plan": {"price": 90},
                "take_profit_plan": {"price": 110},
            }
        ],
    }

    with pytest.raises(RuntimeError, match="misbound_stop_numeric"):
        _validate_narration_authority("600519 的止损价 110，目标价 90。", context)
    with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
        _validate_narration_authority("应当建仓。", context)
    _validate_narration_authority("1. 数据未就绪。\n2. 请等待。", context)


def test_narration_binds_probability_weight_and_actions_to_each_candidate():
    details = [
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "rank": 1,
            "can_open": True,
            "scores": {"final": 0.91},
            "probability": {"up_probability_3d": 0.6},
            "serenity_alpha": {
                "alpha_value": -0.5,
                "effective_weight": 0.08,
                "score_contribution": -0.04,
            },
        },
        {
            "symbol": "000001",
            "name": "平安银行",
            "rank": 2,
            "can_open": True,
            "scores": {"final": 0.75},
            "probability": {"up_probability_3d": 0.4},
            "serenity_alpha": {
                "alpha_value": 1.0,
                "effective_weight": 0.02,
                "score_contribution": 0.02,
            },
        },
    ]
    tradeable = {
        "judgment_result": {"decision": "recommend", "tradeable": True},
        "candidate_details": details,
    }

    with pytest.raises(RuntimeError, match="misbound_probability_numeric"):
        _validate_narration_authority("600519 上涨概率40%。", tradeable)
    with pytest.raises(RuntimeError, match="misbound_weight_numeric"):
        _validate_narration_authority("600519 的 Serenity 权重是0.02。", tradeable)
    with pytest.raises(RuntimeError, match="unbound_numeric"):
        _validate_narration_authority("600519 的上涨概率是91%。", tradeable)
    with pytest.raises(RuntimeError, match="reverses_serenity_contribution"):
        _validate_narration_authority(
            "600519 的 Serenity 公告加分推动推荐。", tradeable
        )

    nontradeable = {
        **tradeable,
        "judgment_result": {"decision": "no_trade", "tradeable": False},
    }
    with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
        _validate_narration_authority("当前可以开仓买进600519。", nontradeable)
    with pytest.raises(RuntimeError, match="invents_position_sizing"):
        _validate_narration_authority("三成仓位介入600519。", nontradeable)


def test_narration_enforces_per_candidate_can_open_without_treating_symbol_as_price():
    context = {
        "judgment_result": {"decision": "recommend", "tradeable": True},
        "candidate_details": [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "rank": 1,
                "can_open": False,
                "action": "WATCH",
                "entry_plan": {"price": 100},
            }
        ],
    }
    with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
        _validate_narration_authority("600519 建议买入。", context)

    context["candidate_details"][0]["can_open"] = True
    with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
        _validate_narration_authority("600519 建议买入。", context)

    context["candidate_details"][0]["action"] = "BUY"
    _validate_narration_authority("600519 建议买入。", context)


def test_narration_accepts_a_bound_price_range_as_a_conditional_plan():
    context = {
        "judgment_result": {"decision": "no_trade", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "rank": 1,
                "can_open": False,
                "entry_plan": {"low": 100, "high": 110, "trigger_price": 111},
            }
        ],
    }

    _validate_narration_authority(
        "600519 的买入区间是100-110，等待触发价111后再判断。", context
    )


def test_narration_binds_exact_fields_and_respective_candidate_values():
    details = [
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "rank": 1,
            "action": "WATCH",
            "can_open": False,
            "entry_plan": {"low": 100, "high": 110},
            "stop_plan": {"price": 90},
            "take_profit_plan": {"price": 120},
            "scores": {"final": 0.91},
            "final_score": 0.91,
            "probability": {"up_probability_3d": 0.6},
            "serenity_alpha": {
                "alpha_value": -0.5,
                "effective_weight": 0.08,
                "score_contribution": -0.04,
            },
        },
        {
            "symbol": "000001",
            "name": "平安银行",
            "rank": 2,
            "action": "WATCH",
            "can_open": False,
            "scores": {"final": 0.75},
            "final_score": 0.75,
            "probability": {"up_probability_3d": 0.4},
            "serenity_alpha": {
                "alpha_value": 1.0,
                "effective_weight": 0.02,
                "score_contribution": 0.02,
            },
        },
    ]
    context = {
        "judgment_result": {"decision": "recommend", "tradeable": True},
        "candidate_details": details,
    }

    _validate_narration_authority(
        "600519 的3日上涨概率为60%，Serenity减分0.04。", context
    )
    _validate_narration_authority(
        "600519和000001最终分数分别为0.91和0.75。", context
    )
    with pytest.raises(RuntimeError, match="misbound_final_score_numeric"):
        _validate_narration_authority(
            "600519和000001最终分数分别为0.75和0.91。", context
        )
    with pytest.raises(RuntimeError, match="misbound_final_score_numeric"):
        _validate_narration_authority("600519 最终分数0.04。", context)
    with pytest.raises(RuntimeError, match="misbound_take1_numeric"):
        _validate_narration_authority("600519 的目标价90。", context)
    with pytest.raises(RuntimeError, match="misbound_entry_low_numeric"):
        _validate_narration_authority("600519 的买入区间110-100。", context)


def test_narration_action_assertions_require_canonical_buy_action():
    context = {
        "judgment_result": {"decision": "no_trade", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "rank": 1,
                "action": "BUY",
                "can_open": True,
            }
        ],
    }

    with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
        _validate_narration_authority("现在可以上车600519。", context)
    with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
        _validate_narration_authority("不是等待而是立即买入600519。", context)
    _validate_narration_authority("600519 买入需要等待触发条件后再判断。", context)


def test_narration_accepts_explicitly_negated_execution_wording_but_not_authorization():
    context = {
        "judgment_result": {"decision": "no_trade", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "rank": 1,
                "action": "WATCH",
                "can_open": False,
            }
        ],
    }

    _validate_narration_authority(
        "600519 当前不构成可执行买入信号，请等待确认。", context
    )
    _validate_narration_authority(
        "600519 当前不具备执行买入条件，请继续观察。", context
    )
    _validate_narration_authority(
        "600519 当前不能视为可执行买入信号。", context
    )
    with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
        _validate_narration_authority(
            "600519 当前具备执行买入条件。", context
        )


def test_narration_uses_exact_score_sources_and_normalizes_fullwidth_numbers():
    context = {
        "judgment_result": {"decision": "recommend", "tradeable": True},
        "candidate_details": [
            {
                "symbol": "600519",
                "final_score": 0.91,
                "live_score": 0.82,
                "daily_rank_score": 0.75,
                "exec_score": 0.66,
                "scores": {"final": 0.75, "adaptive": 0.7},
                "serenity_alpha": {
                    "decision_score": 0.62,
                    "score_contribution": 0.02,
                },
            }
        ],
    }

    _validate_narration_authority("600519综合得分０．９１。", context)
    _validate_narration_authority("600519决策分0.62。", context)
    _validate_narration_authority("600519实时评分0.82。", context)
    with pytest.raises(RuntimeError, match="misbound_final_score_numeric"):
        _validate_narration_authority("600519综合得分0.75。", context)
    with pytest.raises(RuntimeError, match="misbound_decision_score_numeric"):
        _validate_narration_authority("600519决策分0.91。", context)
    with pytest.raises(RuntimeError, match="unbound_numeric"):
        _validate_narration_authority("600519这个0.02很不错。", context)


def test_narration_projection_is_compact_and_fixes_display_precision():
    entry = make_book().board[0]
    probability = {
        "up_probability_3d": 0.1948218406916129,
        "expected_return_3d": -0.007547464683544156,
        "confidence": 0.3534181146419552,
        "uncertainty": 0.0726453348010617,
        "evidence": {
            "effective_sample_size": 9.724473374209609,
            "nearest_cases": [
                {
                    "features": {"pullback_quality": 0.9462552657413036},
                    "similarity": 0.9884495728626199,
                }
            ],
        },
    }
    pick = entry.pick.model_copy(
        update={
            "entry_plan": {"low": 1214.88, "high": 1227.0288},
            "stop_plan": {"price": 1176.859684139152},
            "take_profit_plan": {"price": 1254.308475707546},
            "probability": probability,
            "why_selected": "相似度约0.95",
        }
    )
    entry = entry.model_copy(
        update={
            "pick": pick,
            "final_score": 36.359375773646896,
            "live_score": 36.359375773646896,
            "execution_plan": {
                "entry_low": 1214.88,
                "entry_high": 1227.0288,
                "trigger_price": 1227.0288,
                "stop_price": 1176.859684139152,
                "take1": 1254.308475707546,
                "rr_to_take1": 0.5437543644024033,
                "entry_readiness": {
                    "ready": False,
                    "checks": [
                        {
                            "name": "price_vs_vwap",
                            "current": -0.01234567,
                            "threshold": ">= 0",
                            "passed": False,
                        },
                        {
                            "name": "private_unprojected_check",
                            "current": 99.1234,
                            "threshold": ">= 88",
                            "passed": True,
                        },
                    ],
                },
            },
            "score_breakdown": {
                "execution_quality_score": 71.24770230575506,
                "risk_penalty": 31.4611039243041,
                "data_quality_score": 65.0,
            },
        }
    )

    detail = _narration_entry_payload(entry)
    encoded = json.dumps(detail, ensure_ascii=False)

    assert detail["final_score"] == 36.36
    assert detail["entry_plan"] == {
        "entry_low": 1214.88,
        "entry_high": 1227.03,
    }
    assert detail["execution_plan"]["rr_to_take1"] == 0.54
    assert detail["price_vs_vwap"] == -0.0123
    assert detail["execution_plan"]["entry_readiness"] == {
        "ready": False,
        "checks": [
            {
                "name": "price_vs_vwap",
                "current": -0.0123,
                "threshold": ">= 0",
                "passed": False,
            }
        ],
    }
    assert detail["probability"]["up_probability_3d"] == 0.1948
    assert detail["probability"]["effective_sample_size"] == 9.7
    assert "nearest_cases" not in encoded
    assert "pullback_quality" not in encoded
    assert "0.9462552657413036" not in encoded
    assert "private_unprojected_check" not in encoded
    assert "99.1234" not in encoded
    assert "相似度约0.95" not in encoded
    assert len(encoded.encode("utf-8")) < 6000


def test_narration_accepts_indented_list_marker_and_local_display_values():
    context = {
        "judgment_result": {"decision": "recommend", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "rank": 1,
                "entry_plan": {
                    "entry_low": 1214.88,
                    "entry_high": 1227.03,
                },
                "probability": {"up_probability_3d": 0.1948},
                "execution_plan": {"rr_to_take1": 0.54},
                "action": "WATCH",
                "can_open": False,
                "invalidated": False,
            }
        ],
    }

    _validate_narration_authority(
        "  1）600519：买入区间1214.88至1227.03；"
        "首目标盈亏比0.54；3日上涨概率19.48%。",
        context,
    )


def test_rank_label_cannot_capture_a_later_target_price():
    context = {
        "judgment_result": {"decision": "recommend", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "rank": 1,
                "take_profit_plan": {"take1": 1254.31},
                "action": "WATCH",
                "can_open": False,
                "invalidated": False,
            }
        ],
    }

    _validate_narration_authority(
        "600519排名第一，第一目标1254.31。", context
    )
    _validate_narration_authority(
        "600519排名1，第一目标1254.31。", context
    )
    with pytest.raises(RuntimeError, match="unbound_numeric:2"):
        _validate_narration_authority(
            "600519排名2，第一目标1254.31。", context
        )


def test_first_target_rr_does_not_bind_as_a_first_target_price():
    context = {
        "judgment_result": {"decision": "recommend", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "002415",
                # Narration certificates round this field to the display value
                # that the provider token resolves to.
                "execution_plan": {"take1": 41.25, "rr_to_take1": 0.73},
                "action": "WATCH",
                "can_open": False,
                "invalidated": False,
            }
        ],
    }

    _validate_narration_authority("002415第一目标盈亏比0.73。", context)
    with pytest.raises(RuntimeError, match="misbound_take1_numeric:0.73"):
        _validate_narration_authority("002415第一目标0.73。", context)


def test_provider_receives_opaque_value_tokens_and_local_code_resolves_them():
    context = {
        "candidate_details": [
            {
                "symbol": "600519",
                "rank": 1,
                "entry_plan": {"entry_low": 1214.88},
                "probability": {"up_probability_3d": 0.1948},
                "serenity_alpha": {
                    "facts": [
                        {
                            "claim": "公告披露净利润同比增长35%至50%。",
                        }
                    ]
                },
            }
        ],
        "context_policy": {},
    }

    provider, token_bindings = _provider_narration_context(context)
    detail = provider["candidate_details"][0]
    rank_token = detail["rank"]
    entry_token = detail["entry_plan"]["entry_low"]
    probability_token = detail["probability"]["up_probability_3d"]
    fact_text = detail["serenity_alpha"]["facts"][0]["claim"]

    assert token_bindings[rank_token] == {
        "display": "1",
        "symbol": "600519",
        "field": "rank",
        "label": "排名",
    }
    assert token_bindings[entry_token]["display"] == "1214.88"
    assert token_bindings[entry_token]["field"] == "entry_low"
    assert token_bindings[probability_token]["display"] == "19.48%"
    assert token_bindings[probability_token]["field"] == "up_probability_3d"
    assert "35%" not in fact_text
    assert "50%" not in fact_text
    assert provider["context_policy"]["numeric_output_protocol"] == (
        "opaque_value_tokens.v1"
    )

    resolved = _resolve_provider_value_tokens(
        f"600519优先级{rank_token}，计划区间看{entry_token}，"
        f"概率参考{probability_token}。",
        token_bindings,
        context,
    )
    assert resolved == (
        "600519优先级【600519·排名 1】，计划区间看"
        "【600519·买入区间下限 1214.88】，概率参考"
        "【600519·3日上涨概率 19.48%】。"
    )
    _validate_narration_authority(resolved, context)
    with pytest.raises(RuntimeError, match="unknown_value_token"):
        _resolve_provider_value_tokens(
            "600519最终分数[[GPVAL_ZZZ]]。", token_bindings, context
        )


def test_provider_value_capsules_preserve_candidate_and_field_authority():
    context = {
        "candidate_details": [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "rank": 1,
                "execution_plan": {
                    "trigger_price": 1227.03,
                    "entry_high": 1227.03,
                },
                "ranking": {"ranking_score": 0},
                "probability": {
                    "up_probability_3d": 0.1948,
                    "expected_return_3d": -0.0075,
                    "confidence": 0.3534,
                },
                "serenity_alpha": {
                    "alpha_value": 0,
                    "effective_weight": 0,
                    "score_contribution": 0,
                },
                "action": "WATCH",
                "can_open": False,
                "invalidated": False,
            },
            {
                "symbol": "600036",
                "name": "招商银行",
                "rank": 2,
                "execution_plan": {"trigger_price": 45.67},
                "action": "WATCH",
                "can_open": False,
                "invalidated": False,
            },
        ],
        "judgment_result": {"decision": "recommend", "tradeable": False},
        "context_policy": {},
    }
    provider, bindings = _provider_narration_context(context)
    first = provider["candidate_details"][0]
    trigger = first["execution_plan"]["trigger_price"]
    ranking = first["ranking"]["ranking_score"]
    probability = first["probability"]["up_probability_3d"]
    expected_return = first["probability"]["expected_return_3d"]
    confidence = first["probability"]["confidence"]
    alpha = first["serenity_alpha"]["alpha_value"]
    weight = first["serenity_alpha"]["effective_weight"]
    contribution = first["serenity_alpha"]["score_contribution"]

    raw = (
        f"贵州茅台600519优先跟踪，确认参考{trigger}。"
        f"排序参考{ranking}，概率参考{probability}，"
        f"收益参考{expected_return}，信心参考{confidence}。"
        f"Serenity保持中性：{alpha}、{weight}、{contribution}。"
    )
    resolved = _resolve_provider_value_tokens(raw, bindings, context)
    assert "【600519·触发价 1227.03】" in resolved
    assert "【600519·排名评分 0】" in resolved
    assert "【600519·3日上涨概率 19.48%】" in resolved
    assert "【600519·3日预期收益 -0.75%】" in resolved
    assert "【600519·置信度 35.34%】" in resolved
    assert "【600519·Serenity Alpha值 0】" in resolved
    assert "【600519·Serenity权重 0】" in resolved
    assert "【600519·Serenity贡献 0】" in resolved
    _validate_narration_authority(resolved, context)

    adjacent_metrics = _resolve_provider_value_tokens(
        f"600519的3日上涨概率{probability}、预期收益{expected_return}、"
        f"置信度{confidence}。",
        bindings,
        context,
    )
    _validate_narration_authority(adjacent_metrics, context)

    with pytest.raises(RuntimeError, match="field_mismatch"):
        _resolve_provider_value_tokens(
            f"600519的置信度{probability}。", bindings, context
        )
    with pytest.raises(RuntimeError, match="field_mismatch"):
        _resolve_provider_value_tokens(
            f"600519的Serenity权重{ranking}。", bindings, context
        )
    with pytest.raises(RuntimeError, match="candidate_mismatch"):
        _resolve_provider_value_tokens(
            f"招商银行600036参考{trigger}。", bindings, context
        )
    with pytest.raises(RuntimeError, match=r"writes_raw_numeric:19\.48%"):
        _resolve_provider_value_tokens(
            "贵州茅台600519的概率是19.48%。", bindings, context
        )
    with pytest.raises(RuntimeError, match="value_token_reused"):
        _resolve_provider_value_tokens(
            f"600519参考{probability}，再次参考{probability}。",
            bindings,
            context,
        )
    for malformed in (
        "[[gpval_a]]",
        "[[GPVAL _A]]",
        "［［ＧＰＶＡＬ＿Ａ］］",
    ):
        with pytest.raises(RuntimeError, match="value_token_malformed"):
            _resolve_provider_value_tokens(
                f"贵州茅台600519参考{malformed}。", bindings, context
            )


def test_provider_structural_numbers_do_not_bypass_numeric_authority():
    context = {
        "candidate_details": [{"symbol": "600519"}],
        "judgment_result": {"decision": "recommend", "tradeable": False},
    }

    assert (
        _resolve_provider_value_tokens("1. 600519保持观察。", {}, context)
        == "1. 600519保持观察。"
    )
    dated = "记录于2026-07-14 20:23，600519保持观察。"
    assert _resolve_provider_value_tokens(dated, {}, context) == dated
    # Security codes are identifiers.  Their authorization is enforced by
    # _validate_narrated_symbols, after the numeric gate, so an unknown code
    # produces the correct symbol-boundary error rather than a false numeric
    # authority error.
    unknown_symbol = "002415保持观察。"
    assert _resolve_provider_value_tokens(unknown_symbol, {}, context) == unknown_symbol
    with pytest.raises(RuntimeError, match="contains_symbol_outside_snapshot"):
        _validate_narrated_symbols(unknown_symbol, {"600519"}, "")
    for raw in (
        "19.48. 600519保持观察。",
        "1.5. 600519保持观察。",
        "+1. 600519保持观察。",
        "第1名是600519。",
        "共3只，包含600519。",
        "Top 3：600519。",
        "未来3日观察600519。",
    ):
        with pytest.raises(RuntimeError, match="writes_raw_numeric"):
            _resolve_provider_value_tokens(raw, {}, context)


def test_display_rounding_and_percentage_authority_are_unique():
    assert _display_number(2.675, digits=2) == 2.68
    variants = _number_variants(0.1948, allow_percent=True)
    assert "19.48%" in variants
    assert "19.5%" not in variants

    context = {
        "judgment_result": {
            "decision": "recommend",
            "tradeable": False,
            "selection_meta": {"final_score": 0.99},
        },
        "candidate_details": [
            {
                "symbol": "600519",
                "final_score": 0.91,
                "probability": {"up_probability_3d": 0.1948},
                "action": "WATCH",
                "can_open": False,
                "invalidated": False,
            }
        ],
    }
    _validate_narration_authority(
        "600519的3日上涨概率19.48%。", context
    )
    with pytest.raises(RuntimeError, match="unbound_numeric"):
        _validate_narration_authority(
            "600519的3日上涨概率19.5%。", context
        )
    with pytest.raises(RuntimeError, match="unbound_numeric"):
        _validate_narration_authority("600519最终分数0.99。", context)


def test_real_narration_contract_forbids_sizing_and_uses_zero_temperature(
    monkeypatch,
):
    observed = {}

    class DummyClient:
        @staticmethod
        def available():
            return True, "ok"

        @staticmethod
        def chat(messages, **kwargs):
            observed["messages"] = messages
            observed.update(kwargs)
            return {"choices": [{"message": {"content": "控制仓位和风险。"}}]}

    monkeypatch.setattr(narrate_module, "LLMClient", DummyClient)
    result = narrate_module.render_reply(
        {
            "tool_evidence_context": {
                "candidate_details": [],
                "context_policy": {"compression_steps": []},
            }
        }
    )

    assert result == "控制仓位和风险。"
    assert observed["temperature"] == 0.0
    render_system = observed["messages"][0]["content"]
    assert "certificate has no position-allocation authority" in render_system
    assert "Use '-' bullets only" in render_system
    assert "半仓" not in render_system
    assert "轻仓" not in render_system

    repaired = narrate_module.repair_reply(
        {
            "tool_evidence_context": {
                "candidate_details": [],
                "context_policy": {"compression_steps": []},
            }
        },
        validation_error="llm_narration_writes_raw_numeric",
    )
    assert repaired == "控制仓位和风险。"
    assert observed["temperature"] == 0.0
    repair_system = observed["messages"][0]["content"]
    assert "列表只能用“-”" in repair_system
    assert "不得手写阿拉伯数字" in repair_system


def test_narration_action_and_position_sizing_have_no_phrase_bypass():
    no_trade = {
        "judgment_result": {"decision": "no_trade", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "action": "BUY",
                "can_open": True,
                "invalidated": False,
            }
        ],
    }
    for text in (
        "600519可以配置仓位。",
        "600519可以跟进。",
        "600519应当跟进。",
        "600519必须跟进。",
        "600519需要跟进。",
        "600519现在打板。",
        "600519直接扫板。",
        "600519风险不高现在可以买入。",
        "600519并不弱所以可以建仓。",
        "600519不是利空现在买进。",
        "600519条件不差建议上车。",
        "600519没有理由不买入。",
    ):
        with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
            _validate_narration_authority(text, no_trade)

    _validate_narration_authority("当前Serenity参与正式评分。", no_trade)
    _validate_narration_authority("600519当前不能买入。", no_trade)
    _validate_narration_authority("600519等待突破后再买入。", no_trade)
    for text in (
        "600519盘后不宜直接开仓。",
        "600519在信号确认前不能执行买入。",
        "600519当前不适合立即买进。",
        "600519条件不满足时不要建仓。",
    ):
        _validate_narration_authority(text, no_trade)
    _validate_narration_authority(
        "600519是下一窗口优先跟进对象，当前仍需等待确认。", no_trade
    )

    tradeable = {
        **no_trade,
        "judgment_result": {"decision": "recommend", "tradeable": True},
    }
    with pytest.raises(RuntimeError, match="overrides_non_tradeable_action"):
        _validate_narration_authority("600519建议加仓。", tradeable)
    for text in (
        "600519建议三成仓买入。",
        "600519建议半仓。",
        "600519满仓更合适。",
        "600519仓位30%。",
        "600519用小仓位参与。",
        "600519可投入少量资金。",
        "600519适合低比例配置。",
        "600519可以分批建仓。",
        "600519可以少量买入。",
    ):
        with pytest.raises(RuntimeError, match="invents_position_sizing"):
            _validate_narration_authority(text, tradeable)
    _validate_narration_authority("600519注意控制仓位和风险。", tradeable)


def test_serenity_direction_wording_understands_local_negation():
    positive = {
        "judgment_result": {"decision": "recommend", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "serenity_alpha": {"score_contribution": 0.02},
            }
        ],
    }
    negative = {
        "judgment_result": {"decision": "recommend", "tradeable": False},
        "candidate_details": [
            {
                "symbol": "600519",
                "serenity_alpha": {"score_contribution": -0.04},
            }
        ],
    }

    _validate_narration_authority(
        "600519的Serenity没有拖累，而是加分0.02。", positive
    )
    _validate_narration_authority(
        "600519的Serenity没有加分，而是减分0.04。", negative
    )


def test_current_pick_detail_cannot_bypass_market_time(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_market_time_state",
        lambda _snapshot: {"matches": False, "revision": "market-stale"},
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id="stale-detail-session",
        client_turn_id="stale-detail-turn",
        user_message="600519 为什么入选",
        store=store,
    )

    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "current_snapshot_market_time_mismatch"
    assert result["message"]["tradeable"] is False


def test_new_session_pick_detail_cannot_bypass_current_serenity_semantics(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    observed_context = {}

    def capture_redacted_context(payload):
        observed_context.update(payload["tool_evidence_context"])
        return "当前 Serenity 证据版本已变化，本轮不提供候选解释。"

    monkeypatch.setattr(
        "gp_assistant.chat_agent.render_reply", capture_redacted_context
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_serenity_check",
        lambda _book: (
            "current_serenity_semantic_revision_changed",
            {
                "semantic_revision": "advanced",
                "binding_token": "advanced",
                "available": False,
            },
        ),
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id="new-detail-serenity-session",
        client_turn_id="new-detail-serenity-turn",
        user_message="600519 为什么入选？",
        store=store,
    )

    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "current_serenity_semantic_revision_changed"
    assert result["message"]["picks"] == []
    assert result["symbols"] == []
    assert observed_context["candidate_details"] == []


def test_current_serenity_gate_blocks_recommendation_without_candidate_leak(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    observed_context = {}

    def capture_redacted_context(payload):
        observed_context.update(payload["tool_evidence_context"])
        return "当前原生 Serenity 状态已变化，本轮没有可执行标的。"

    monkeypatch.setattr(
        "gp_assistant.chat_agent.render_reply", capture_redacted_context
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_serenity_check",
        lambda _book: (
            "current_serenity_target_replaced",
            {"binding_token": "replaced", "available": False},
        ),
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id="rotated-target-session",
        client_turn_id="rotated-target-turn",
        user_message="推荐",
        store=store,
    )

    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "current_serenity_target_replaced"
    assert result["message"]["picks"] == []
    assert result["symbols"] == []
    assert result["message"]["perspective"] == "blocked_current"
    assert result["message"]["is_current"] is False
    assert observed_context["candidate_details"] == []
    selection_meta = observed_context["judgment_result"]["selection_meta"]
    assert selection_meta == {
        "decision": "no_trade",
        "decision_reason": "current_serenity_target_replaced",
        "candidate_evidence_redacted": True,
    }


@pytest.mark.parametrize(
    "request_type",
    ["candidate_compare", "intraday_situation", "chat"],
)
def test_every_current_request_obeys_market_time_gate(
    monkeypatch, tmp_path, request_type
):
    patch_chat_llm(monkeypatch)

    def route(_context, user_message):
        return TurnFrame(
            frame_id=f"frame-{request_type}",
            raw_message=user_message,
            subject="run",
            request=request_type,
            freshness="active_run",
            references={},
            constraints={"topk": 3, "allow_derived_data": True},
            ambiguity={
                "confidence": 1.0,
                "notes": [],
                "needs_clarification": False,
            },
        )

    monkeypatch.setattr("gp_assistant.chat_agent.parse_turn_frame", route)
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_market_time_state",
        lambda _snapshot: {"matches": False, "revision": "market-stale"},
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id=f"{request_type}-session",
        client_turn_id=f"{request_type}-turn",
        user_message="当前情况",
        store=store,
    )

    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "current_snapshot_market_time_mismatch"
    assert result["message"]["picks"] == []
    assert result["symbols"] == []


def test_chat_intent_cannot_surface_recommendation_candidates(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    observed_context = {}

    monkeypatch.setattr(
        "gp_assistant.chat_agent.parse_turn_frame",
        lambda _context, message: TurnFrame(
            frame_id="frame-chat",
            raw_message=message,
            subject="run",
            request="chat",
            freshness="active_run",
            references={},
            constraints={"topk": 3, "allow_derived_data": True},
            ambiguity={
                "confidence": 1.0,
                "notes": [],
                "needs_clarification": False,
            },
        ),
    )

    def render(payload):
        observed_context.update(payload["tool_evidence_context"])
        return "你好，我可以回答当前系统状态。"

    monkeypatch.setattr("gp_assistant.chat_agent.render_reply", render)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id="chat-only-session",
        client_turn_id="chat-only-turn",
        user_message="你好",
        store=store,
    )

    assert result["decision"] == "informational"
    assert result["message"]["picks"] == []
    assert result["symbols"] == []
    assert observed_context["candidate_details"] == []


def test_single_candidate_narration_meta_does_not_leak_other_candidate_data(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    observed_context = {}
    book = make_book()
    book.daybook.source_meta["non_target_payload"] = {
        "symbol": "000001",
        "fact_id": "serfact_secret_b",
        "scores": {"final": 0.123456},
    }

    def render(payload):
        observed_context.update(payload["tool_evidence_context"])
        return "600519保持既定计划并遵守风险纪律。"

    monkeypatch.setattr("gp_assistant.chat_agent.render_reply", render)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(book)
    run_chat_turn(
        session_id="meta-redaction-session",
        client_turn_id="meta-redaction-turn",
        user_message="解释600519",
        store=store,
    )

    encoded = json.dumps(observed_context, ensure_ascii=False)
    selection_meta = observed_context["judgment_result"]["selection_meta"]
    assert len(observed_context["candidate_details"]) == 1
    assert "000001" not in encoded
    assert "serfact_secret_b" not in encoded
    assert "serenity_native_attestation" not in selection_meta
    assert "serenity_candidate_target" not in selection_meta
    assert "non_target_payload" not in selection_meta


def test_blocked_market_gate_cannot_surface_plan_or_candidates(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    book = make_book()
    book.publish_allowed = False
    book.gate.state = "BLOCKED"
    book.gate.reasons = ["market_hard_block"]
    store.publish_book(book)

    result = run_chat_turn(
        session_id="blocked-gate-session",
        client_turn_id="blocked-gate-turn",
        user_message="推荐",
        store=store,
    )

    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "market_gate_not_allow"
    assert result["message"]["picks"] == []
    assert result["symbols"] == []


def test_market_time_change_during_llm_does_not_commit(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    states = iter(
        (
            {"matches": True, "revision": "market-old"},
            {"matches": True, "revision": "market-new"},
        )
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_market_time_state",
        lambda _snapshot: next(states),
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    with pytest.raises(
        SnapshotIntegrityError, match="current_market_time_changed_before_commit"
    ):
        run_chat_turn(
            session_id="market-race-session",
            client_turn_id="market-race-turn",
            user_message="推荐",
            store=store,
        )

    assert store.session_turns("market-race-session") == []


def test_tradeable_snapshot_with_incomplete_quality_fails_closed(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    book = make_book()
    book.data_quality.complete = False
    book.data_quality.freshness_state = "unknown"
    store.publish_book(book)

    result = run_chat_turn(
        session_id="quality-session",
        client_turn_id="quality-turn",
        user_message="推荐",
        store=store,
    )

    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "market_data_incomplete"
    assert result["message"]["picks"] == []


def test_current_serenity_gate_accepts_a_new_equivalent_freshness_certificate(monkeypatch):
    book = make_book()
    meta = book.daybook.source_meta
    target = dict(meta["serenity_candidate_target"])
    policy = dict(meta["serenity_policy_snapshot"])
    monkeypatch.setattr(
        "gp_assistant.chat_agent.current_native_readiness_state",
        lambda _target_id: {
            "mode": "native",
            "formula_version": meta["serenity_formula_version"],
            "target_id": meta["serenity_target_id"],
            "target_input_hash": target["input_hash"],
            "activation_observed_at": target["activation_observed_at"],
            "activation_revision": target["activation_revision"],
            "target_matches": True,
            "certificate_current": True,
            "readiness_revision": "new-complete-poll",
            "semantic_revision": meta["serenity_semantic_revision"],
            "policy_state": policy["state"],
            "policy_epoch": policy["epoch"],
            "policy_applied_weight": policy["applied_weight"],
            "policy_max_weight": policy["max_weight"],
            "native_required": True,
            "available": True,
        },
    )

    assert _current_serenity_reason(book) is None


def test_current_serenity_gate_rejects_changed_semantics(monkeypatch):
    book = make_book()
    monkeypatch.setattr(
        "gp_assistant.chat_agent.current_native_readiness_state",
        lambda _target_id: {
            "target_matches": True,
            "certificate_current": True,
            "semantic_revision": "changed-semantic-revision",
        },
    )

    assert _current_serenity_reason(book) == "current_serenity_semantic_revision_changed"


def test_serenity_state_change_during_llm_does_not_commit(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    states = iter(
        (
            (
                None,
                {
                    "semantic_revision": "semantic-old",
                    "binding_token": "binding-old",
                    "available": True,
                },
            ),
            (
                None,
                {
                    "semantic_revision": "semantic-new",
                    "binding_token": "binding-new",
                    "available": True,
                },
            ),
        )
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_serenity_check",
        lambda _book: next(states),
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    with pytest.raises(
        SnapshotIntegrityError, match="current_serenity_state_changed_before_commit"
    ):
        run_chat_turn(
            session_id="serenity-race-session",
            client_turn_id="serenity-race-turn",
            user_message="推荐",
            store=store,
        )

    assert store.session_turns("serenity-race-session") == []


def test_freshness_renewal_during_llm_commits_same_semantics(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    states = iter(
        (
            (
                None,
                {
                    "semantic_revision": "semantic-stable",
                    "binding_token": "binding-stable",
                    "freshness_token": "freshness-old",
                    "source_run_id": "poll-old",
                    "available": True,
                },
            ),
            (
                None,
                {
                    "semantic_revision": "semantic-stable",
                    "binding_token": "binding-stable",
                    "freshness_token": "freshness-new",
                    "source_run_id": "poll-new",
                    "available": True,
                },
            ),
        )
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_serenity_check",
        lambda _book: next(states),
    )
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())

    result = run_chat_turn(
        session_id="serenity-renewal-session",
        client_turn_id="serenity-renewal-turn",
        user_message="推荐",
        store=store,
    )

    assert result["snapshot_id"] == "snapshot-1"
    assert len(store.session_turns("serenity-renewal-session")) == 2


def test_same_session_pick_explanation_keeps_immutable_snapshot_evidence_when_live_serenity_advances(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    first = run_chat_turn(
        session_id="serenity-explanation-session",
        client_turn_id="serenity-explanation-first",
        user_message="推荐",
        store=store,
    )

    def live_state_must_not_be_read(_book):
        raise AssertionError("snapshot explanations must not read live Serenity state")

    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_serenity_check",
        live_state_must_not_be_read,
    )
    second = run_chat_turn(
        session_id="serenity-explanation-session",
        client_turn_id="serenity-explanation-second",
        user_message="第一名为什么排在最前？Serenity Alpha 的贡献是什么？",
        store=store,
    )

    assert second["snapshot_id"] == first["snapshot_id"] == "snapshot-1"
    assert second["decision"] == "no_trade"
    assert second["message"]["reason"] == "snapshot_explanation_only"
    assert second["message"]["tradeable"] is False
    assert second["message"]["perspective"] == "historical"
    assert second["message"]["is_current"] is False
    assert second["message"]["intent"]["request"] == "pick_detail"
    assert second["message"]["intent"]["references"]["rank"] == 1
    assert second["message"]["intent"]["references"]["symbol"] == "600519"
    assert [item["symbol"] for item in second["message"]["picks"]] == ["600519"]
    assert second["symbols"] == ["600519"]
    assert [turn["role"] for turn in store.session_turns("serenity-explanation-session")] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_same_session_live_comparison_still_obeys_current_market_time(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    run_chat_turn(
        session_id="live-comparison-session",
        client_turn_id="live-comparison-first",
        user_message="推荐",
        store=store,
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_market_time_state",
        lambda _snapshot: {"matches": False, "revision": "market-stale"},
    )

    result = run_chat_turn(
        session_id="live-comparison-session",
        client_turn_id="live-comparison-second",
        user_message="第一只和第二只谁现在更适合买？",
        store=store,
    )

    assert result["message"]["intent"]["request"] == "compare"
    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "current_snapshot_market_time_mismatch"
    assert result["message"]["picks"] == []
    assert result["symbols"] == []


def test_current_snapshot_rotation_during_llm_does_not_commit(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book("snapshot-1"))

    def rotate_then_render(payload):
        store.publish_book(make_book("snapshot-2"))
        details = payload["tool_evidence_context"].get("candidate_details") or []
        return f"{details[0]['symbol']} 保持既定买入区间与止损。"

    monkeypatch.setattr("gp_assistant.chat_agent.render_reply", rotate_then_render)

    with pytest.raises(
        SnapshotIntegrityError, match="current_snapshot_changed_before_commit"
    ):
        run_chat_turn(
            session_id="snapshot-race-session",
            client_turn_id="snapshot-race-turn",
            user_message="推荐",
            store=store,
        )

    assert store.session_turns("snapshot-race-session") == []


def test_grounding_reads_serenity_from_the_canonical_pick_payload():
    book = make_book()
    entry = book.board[0]
    serenity = {
        **entry.pick.explain_context["serenity"],
        "status": "available",
        "fact_ids": ["serfact_available"],
        "policy_state": "active",
        "effective_weight": 0.05,
        "score_contribution": 0.02,
        "learning_eligible": True,
        "non_binding": False,
    }
    entry.pick.explain_context["serenity"] = serenity
    entry.explain_context = {}
    run = AdviceRun(
        run_id="run-grounding",
        session_id="session-grounding",
        book_version=book.book_version,
        created_at=book.updated_at,
        trading_day=book.trading_day,
        picks=[entry],
    )
    judgment = Judgment(kind="pick_detail", summary="ok", run=run)
    reply = ReplyBundle(
        session_id="session-grounding",
        text="600519 的 Serenity 公告证据已纳入既定快照。",
        symbols=["600519"],
        evidence_refs=["serfact_available"],
    )

    validate_reply(reply, judgment)


def test_grounding_scopes_serenity_binding_and_missing_evidence_per_symbol():
    book = make_book()
    first = book.board[0].model_copy(deep=True)
    first_serenity = {
        **first.pick.explain_context["serenity"],
        "status": "available",
        "policy_state": "active",
        "effective_weight": 0.05,
        "score_contribution": 0.02,
        "learning_eligible": True,
        "non_binding": False,
    }
    first.pick.explain_context["serenity"] = first_serenity

    second = book.board[0].model_copy(deep=True)
    second.symbol = "000001"
    second.name = "平安银行"
    second.rank = 2
    second.pick.symbol = "000001"
    second.pick.name = "平安银行"
    second.pick.rank = 2
    second_serenity = {
        **second.pick.explain_context["serenity"],
        "status": "no_relevant_evidence",
        "policy_state": "shadow",
        "effective_weight": 0.0,
        "score_contribution": 0.0,
        "learning_eligible": False,
        "non_binding": True,
    }
    second.pick.explain_context["serenity"] = second_serenity
    run = AdviceRun(
        run_id="run-multi-grounding",
        session_id="session-multi-grounding",
        book_version=book.book_version,
        created_at=book.updated_at,
        trading_day=book.trading_day,
        picks=[first, second],
    )
    judgment = Judgment(kind="compare", summary="ok", run=run)

    validate_reply(
        ReplyBundle(
            session_id="session-multi-grounding",
            text=(
                "600519 的 Serenity 公告加分推动排名。"
                "000001 的 Serenity 证据未进入正式排序。"
            ),
            symbols=["600519", "000001"],
        ),
        judgment,
    )
    with pytest.raises(
        RuntimeError,
        match="binding Serenity evidence cannot be described as non-binding",
    ):
        validate_reply(
            ReplyBundle(
                session_id="session-multi-grounding",
                text="600519的Serenity不参与正式排序。",
                symbols=["600519", "000001"],
            ),
            judgment,
        )
    with pytest.raises(RuntimeError, match="ambiguous candidate scope"):
        validate_reply(
            ReplyBundle(
                session_id="session-multi-grounding",
                text="Serenity没有推动排名。",
                symbols=["600519", "000001"],
            ),
            judgment,
        )
    with pytest.raises(RuntimeError, match="ambiguous candidate scope"):
        validate_reply(
            ReplyBundle(
                session_id="session-multi-grounding",
                text="600519的Serenity推动000001进入排名。",
                symbols=["600519", "000001"],
            ),
            judgment,
        )

    with pytest.raises(
        RuntimeError,
        match="missing Serenity evidence cannot be asserted as positive evidence",
    ):
        validate_reply(
            ReplyBundle(
                session_id="session-multi-grounding",
                text=(
                    "600519 的 Serenity 公告加分推动排名。"
                    "000001 公告没有利空所以安全。"
                ),
                symbols=["600519", "000001"],
            ),
            judgment,
        )
    with pytest.raises(
        RuntimeError,
        match="binding Serenity evidence cannot be described as non-binding",
    ):
        validate_reply(
            ReplyBundle(
                session_id="session-multi-grounding",
                text=(
                    "600519 的 Serenity 不参与正式排序。"
                    "000001 的 Serenity 推动排名。"
                ),
                symbols=["600519", "000001"],
            ),
            judgment,
        )


def test_same_day_replaced_session_snapshot_is_historical_for_execution(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book("snapshot-1"))
    run_chat_turn(
        session_id="same-day-session",
        client_turn_id="first",
        user_message="推荐",
        store=store,
    )
    store.publish_book(make_book("snapshot-2"))

    result = run_chat_turn(
        session_id="same-day-session",
        client_turn_id="second",
        user_message="现在还能买吗",
        store=store,
    )

    assert result["decision"] == "no_trade"
    assert result["message"]["reason"] == "historical_snapshot_not_tradeable"
    assert result["message"]["picks"] == []


def test_native_ready_boolean_without_pick_alpha_payload_is_rejected_at_publish(
    monkeypatch, tmp_path
):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    book = make_book()
    book.daybook.picks[0].explain_context = {}
    book.daybook.picks[0].meta.pop("serenity", None)
    book.board[0].pick.explain_context = {}
    book.board[0].pick.meta.pop("serenity", None)
    with pytest.raises(
        SnapshotIntegrityError,
        match="native_snapshot_alpha_payload_invalid:600519",
    ):
        store.publish_book(book)
