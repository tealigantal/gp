from datetime import date, datetime, timedelta, timezone
import json
import sqlite3
from types import SimpleNamespace

from gp_assistant.application.conversation_service import ConversationService
from gp_assistant.application.plan_service import PlanService
from gp_assistant.application.publication_service import PublicationService
from gp_assistant.application.real_producer import RealRecommendationProducer
from gp_assistant.application.target_resolver import resolve_plan_target
from gp_assistant.contracts.catalog import CandidateDisposition
from gp_assistant.contracts.decision import CandidateDecision, TradePlan
from gp_assistant.contracts.evidence import CandidateUniverseBinding, DecisionPolicyBinding, ProbabilityAssessment, ProducerIdentity, RankingAssessment, RiskAssessment, SerenityDecisionBinding, SignalAssessment
from gp_assistant.contracts.market import TradingCalendarRef
from gp_assistant.decision_engine.adaptive import AdaptiveDecisionEngine
from gp_assistant.serenity.parser import PdfParseResult
from gp_assistant.serenity.service import FIXED_WEIGHT, POLICY_REVISION, _commit_batch, _set_health, collect_once, load_decision, publish_target, status_snapshot
from gp_assistant.store import ContractStore


TZ = timezone(timedelta(hours=8))


def _candidate(symbol: str, score: float) -> CandidateDecision:
    return CandidateDecision(
        symbol=symbol,
        name=symbol,
        disposition=CandidateDisposition.REJECTED,
        adaptive_score=score,
        recommendation_strength="normal",
        signal=SignalAssessment(score=0.5, label="trend", reason_codes=()),
        probability=ProbabilityAssessment(probability=0.6, confidence=0.7, effective_sample_size=30, uncertainty=0.2),
        risk=RiskAssessment(score=0.7, execution_risk=0.3, reason_codes=()),
        ranking=RankingAssessment(score=score, rank=0, reason_codes=()),
        experts=(),
        trade_plan=TradePlan(entry_low=None, entry_high=None, stop_price=None, take_profit_prices=(), action="watch", reason_codes=()),
        reason_codes=(),
    )


def test_batch_is_zero_until_exact_complete_snapshot_then_fixed_three_percent(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.db"))
    observed = datetime(2026, 7, 24, 9, 0, tzinfo=TZ).isoformat()
    target = publish_target(
        ("000001", "600000", "600519"),
        market_session_date="2026-07-24",
        daily_evidence_date="2026-07-23",
        universe_digest="universe",
        base_scores={"000001": 0.6, "600000": 0.55, "600519": 0.5},
        observed_at=observed,
    )
    unavailable = load_decision(target)
    base = (_candidate("000001", 0.6), _candidate("600000", 0.55), _candidate("600519", 0.5))
    unchanged = RealRecommendationProducer._apply_serenity(base, unavailable)
    assert [item.adaptive_score for item in unchanged] == [item.adaptive_score for item in base]
    assert {item.experts[-1].weight for item in unchanged} == {0.0}

    payload = {
        "schema": "SerenityBatch.v1",
        "target_id": target.target_id,
        "completed_at": observed,
        "alphas": {"000001": 1.0, "600000": -1.0, "600519": 0.0},
        "reasons": {
            "000001": ["serenity_verified_positive"],
            "600000": ["serenity_verified_negative"],
            "600519": ["serenity_no_relevant_evidence"],
        },
        "document_version_ids": [],
    }
    batch_id = _commit_batch(target, payload, [], observed)
    _set_health("ready", target_id=target.target_id, batch_id=batch_id, updated_at=observed)
    active = load_decision(target)
    fused = RealRecommendationProducer._apply_serenity(base, active)
    assert active.applied_weight == FIXED_WEIGHT == 0.03
    assert [round(item.adaptive_score, 6) for item in fused] == [0.63, 0.52, 0.5]
    assert [item.experts[-1].contribution for item in fused] == [0.03, -0.03, 0.0]
    assert {item.experts[-1].weight for item in fused} == {0.03}

    _set_health("degraded", target_id=target.target_id, detail="source_down", updated_at=observed)
    failed_after_success = load_decision(target)
    assert failed_after_success.applied_weight == 0.0


def test_snapshot_with_missing_symbol_fails_closed_for_whole_batch(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.db"))
    observed = datetime(2026, 7, 24, 9, 0, tzinfo=TZ).isoformat()
    target = publish_target(
        ("000001", "600000"),
        market_session_date="2026-07-24",
        daily_evidence_date="2026-07-23",
        universe_digest="universe",
        base_scores={"000001": 0.6, "600000": 0.55},
        observed_at=observed,
    )
    incomplete_payload = {
        "schema": "SerenityBatch.v1",
        "target_id": target.target_id,
        "completed_at": observed,
        "alphas": {"000001": 1.0},
        "reasons": {"000001": ["serenity_verified_positive"]},
        "document_version_ids": [],
    }
    _commit_batch(target, incomplete_payload, [], observed)
    decision = load_decision(target)
    base = (_candidate("000001", 0.6), _candidate("600000", 0.55))
    fused = RealRecommendationProducer._apply_serenity(base, decision)
    assert decision.applied_weight == 0.0
    assert [item.adaptive_score for item in fused] == [0.6, 0.55]
    assert {item.experts[-1].contribution for item in fused} == {0.0}


def test_serenity_only_changes_frozen_finalists_without_truncating_candidate_scope():
    base = (
        _candidate("000001", 0.60),
        _candidate("600000", 0.55),
        _candidate("600519", 0.50),
        _candidate("000002", 0.45),
    )
    fused = RealRecommendationProducer._apply_serenity(
        base,
        SimpleNamespace(
            applied_weight=0.03,
            alphas={"000001": 1.0, "600000": -1.0, "600519": 0.0},
            reasons={},
            reason_codes=("serenity_batch_complete",),
        ),
        eligible_symbols=frozenset({"000001", "600000", "600519"}),
    )

    assert [item.symbol for item in fused] == [item.symbol for item in base]
    assert [round(item.adaptive_score, 6) for item in fused] == [0.63, 0.52, 0.5, 0.45]
    assert [item.ranking.score for item in fused] == [item.ranking.score for item in base]
    assert fused[-1] == base[-1]
    assert fused[-1].experts == ()


def test_uncovered_candidate_cannot_be_selected_after_serenity_penalizes_a_finalist():
    finalists = (_candidate("000001", 0.51),)
    uncovered = _candidate("000002", 0.50)
    fused = RealRecommendationProducer._apply_serenity(
        finalists,
        SimpleNamespace(
            applied_weight=0.03,
            alphas={"000001": -1.0},
            reasons={},
            reason_codes=("serenity_batch_complete",),
        ),
    )

    selected = AdaptiveDecisionEngine().select(
        (*fused, uncovered),
        selection_eligible_symbols=frozenset({"000001"}),
    )

    by_symbol = {item.symbol: item for item in selected}
    assert by_symbol["000001"].adaptive_score == 0.48
    assert by_symbol["000001"].disposition.value == "reserve"
    assert by_symbol["000002"].disposition.value == "reserve"


def test_serenity_semantic_revision_changes_plan_identity_but_zero_is_stable(tmp_path):
    store = ContractStore(tmp_path / "contracts.db")
    target = resolve_plan_target(
        now=datetime(2026, 7, 24, 9, 0, tzinfo=TZ),
        completed_daily_date=date(2026, 7, 23),
        calendar=TradingCalendarRef(calendar_id="cn", revision="1", source="fixture"),
        is_open=True,
        next_open_session=date(2026, 7, 27),
        required_daily_evidence_date=date(2026, 7, 23),
    )
    universe = CandidateUniverseBinding(candidate_universe_id="u", content_digest="d", total_count=1, eligible_count=1, complete=True, source="fixture")
    producer = ProducerIdentity(name="fixture", revision="2", source_digest="d")

    def create(semantic: str, weight: float):
        return PlanService(store).get_or_create(
            target=target,
            universe=universe,
            policy=DecisionPolicyBinding(revision="adaptive_kernel_v3_serenity", adaptive_policy_state_version=semantic, selection_policy="top30", risk_profile="normal"),
            producer=producer,
            evaluated_candidates=(_candidate("000001", 0.6),),
            serenity=SerenityDecisionBinding(reference_id="batch" if weight else None, policy_revision=POLICY_REVISION, applied_weight=weight, state="active" if weight else "degraded", reason_codes=()),
            generated_at=datetime(2026, 7, 24, 9, 1, tzinfo=TZ),
        ).plan

    zero_first = create("zero:target", 0.0)
    zero_retry = create("zero:target", 0.0)
    active = create("complete:content", 0.03)
    assert zero_first.plan_id == zero_retry.plan_id
    assert active.plan_id != zero_first.plan_id


def test_collector_commits_neutral_only_after_complete_exact_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.db"))
    observed = datetime(2026, 7, 24, 9, 0, tzinfo=TZ)
    target = publish_target(
        ("000001", "600000"),
        market_session_date="2026-07-24",
        daily_evidence_date="2026-07-23",
        universe_digest="universe",
        base_scores={"000001": 0.6, "600000": 0.55},
        observed_at=observed.isoformat(),
    )

    class CompleteEmptyClient:
        def load_stock_map(self):
            return {"000001": {"org_id": "a"}, "600000": {"org_id": "b"}}

        def fetch_symbol(self, *_args, **_kwargs):
            return {"complete": True, "records": []}

    class Verifier:
        def verify(self, *_args, **_kwargs):
            raise AssertionError("no document should require verification")

    report = collect_once(now=observed, client=CompleteEmptyClient(), verifier=Verifier())
    decision = load_decision(target)
    assert report["state"] == "ready"
    assert decision.applied_weight == 0.03
    assert decision.alphas == {"000001": 0.0, "600000": 0.0}


def test_collector_source_failure_never_creates_partial_weight(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.db"))
    observed = datetime(2026, 7, 24, 9, 0, tzinfo=TZ)
    target = publish_target(
        ("000001", "600000"),
        market_session_date="2026-07-24",
        daily_evidence_date="2026-07-23",
        universe_digest="universe",
        base_scores={"000001": 0.6, "600000": 0.55},
        observed_at=observed.isoformat(),
    )

    class FailingClient:
        def load_stock_map(self):
            raise RuntimeError("source_down")

    report = collect_once(now=observed, client=FailingClient(), verifier=object())
    decision = load_decision(target)
    assert report["state"] == "degraded"
    assert decision.applied_weight == 0.0
    assert status_snapshot()["state"] == "degraded"


def test_irrelevant_legal_revision_is_skipped_before_download(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.db"))
    observed = datetime(2026, 7, 24, 9, 0, tzinfo=TZ)
    target = publish_target(("000001",), market_session_date="2026-07-24", daily_evidence_date="2026-07-23", universe_digest="u", base_scores={"000001": 0.6}, observed_at=observed.isoformat())

    class Source:
        def load_stock_map(self):
            return {"000001": {"org_id": "a"}}

        def fetch_symbol(self, *_args, **_kwargs):
            return {"complete": True, "records": [{"title": "关于发行股份购买资产的补充法律意见书（二）（修订稿）", "published_at": "2026-07-20T09:00:00+08:00", "source_url": "https://example.invalid/legal.pdf", "source_record_id": "legal"}]}

        def download_pdf(self, *_args, **_kwargs):
            raise AssertionError("irrelevant title must not be downloaded")

    report = collect_once(now=observed, client=Source(), verifier=object())
    assert report["state"] == "ready"
    assert load_decision(target).applied_weight == 0.03


def test_ocr_uncertainty_fails_the_whole_batch_and_audit_stays_in_json(tmp_path, monkeypatch):
    db = tmp_path / "serenity.db"
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(db))
    observed = datetime(2026, 7, 24, 9, 0, tzinfo=TZ)
    target = publish_target(("000001",), market_session_date="2026-07-24", daily_evidence_date="2026-07-23", universe_digest="u", base_scores={"000001": 0.6}, observed_at=observed.isoformat())

    class Source:
        def load_stock_map(self):
            return {"000001": {"org_id": "a"}}

        def fetch_symbol(self, *_args, **_kwargs):
            return {"complete": True, "records": [{"title": "2026年半年度业绩预告", "published_at": "2026-07-20T09:00:00+08:00", "source_url": "https://example.invalid/report.pdf", "source_record_id": "report"}]}

        def download_pdf(self, *_args, **_kwargs):
            return b"pdf"

    class Verifier:
        def verify(self, *_args, **_kwargs):
            return True

    monkeypatch.setattr("gp_assistant.serenity.service.extract_pdf_document", lambda *_args, **_kwargs: PdfParseResult("", "ocr_uncertain", "ocr", ocr_engine="5.3", ocr_confidence=80.0))
    report = collect_once(now=observed, client=Source(), verifier=Verifier())
    assert report["state"] == "degraded"
    assert load_decision(target).applied_weight == 0.0

    monkeypatch.setattr("gp_assistant.serenity.service.extract_pdf_document", lambda *_args, **_kwargs: PdfParseResult("证券代码000001，2026年半年度业绩预告，预计净利润同比增长35%。", "parsed", "tesseract_ocr", ocr_engine="5.3", ocr_confidence=88.0))
    ready = collect_once(now=observed, client=Source(), verifier=Verifier())
    assert ready["state"] == "ready"
    conn = sqlite3.connect(db)
    try:
        document = json.loads(conn.execute("SELECT payload_json FROM document_versions").fetchone()[0])
        batch = json.loads(conn.execute("SELECT payload_json FROM batches ORDER BY completed_at DESC LIMIT 1").fetchone()[0])
    finally:
        conn.close()
    assert document["parse_method"] == "tesseract_ocr"
    assert document["ocr_confidence"] == 88.0
    assert batch["document_parse_audit"][document["version_id"]]["ocr_engine"] == "5.3"


def test_document_effective_availability_uses_stable_first_seen_time(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.db"))
    first_clock = datetime(2026, 7, 24, 11, 30, tzinfo=TZ)
    second_clock = datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    publish_target(
        ("000001",),
        market_session_date="2026-07-24",
        daily_evidence_date="2026-07-23",
        universe_digest="universe",
        base_scores={"000001": 0.6},
        observed_at=first_clock.isoformat(),
    )

    class Source:
        def load_stock_map(self):
            return {"000001": {"org_id": "a"}}

        def fetch_symbol(self, *_args, **_kwargs):
            return {
                "complete": True,
                "records": [{
                    "title": "业绩预告",
                    "published_at": "2026-07-20T09:00:00+08:00",
                    "source_url": "https://example.invalid/report.pdf",
                    "source_record_id": "record-1",
                }],
            }

        def download_pdf(self, *_args, **_kwargs):
            return b"pdf"

    class Verifier:
        def verify(self, *_args, **_kwargs):
            return True

    effective_times = []
    monkeypatch.setattr(
        "gp_assistant.serenity.service.extract_pdf_document",
        lambda *_args, **_kwargs: PdfParseResult("证券代码000001，净利润增长35%。", "parsed", "pypdf"),
    )

    def capture_evidence(**kwargs):
        effective_times.append(kwargs["effective_available_at"])
        return (), None

    monkeypatch.setattr("gp_assistant.serenity.service.build_verified_evidence", capture_evidence)

    assert collect_once(now=first_clock, client=Source(), verifier=Verifier())["state"] == "ready"
    assert collect_once(now=second_clock, client=Source(), verifier=Verifier())["state"] == "ready"
    assert effective_times == [first_clock.isoformat(), first_clock.isoformat()]


def test_public_health_exposes_only_product_level_serenity_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.db"))
    _set_health(
        "degraded",
        target_id="target",
        detail="RuntimeError:pdf_unparsed:000100",
        updated_at=datetime(2026, 7, 24, 11, 30, tzinfo=TZ).isoformat(),
    )

    health = ContractStore(tmp_path / "contracts.db").health()

    assert health["serenity"] == {
        "mode": "native",
        "state": "degraded",
        "target_ready": False,
        "batch_ready": False,
    }
    assert "RuntimeError" not in str(health)


def test_llm_receives_product_level_serenity_explanation_and_actual_contribution(tmp_path):
    captured = {}

    class Narrator:
        def available(self):
            return True, "ok"

        def chat(self, messages, **_kwargs):
            captured["messages"] = messages
            return {"choices": [{"message": {"content": "Serenity 本批次完整，按固定 3% 辅助。"}}]}

    store = ContractStore(tmp_path / "contracts.db")
    target = resolve_plan_target(
        now=datetime(2026, 7, 24, 9, 0, tzinfo=TZ),
        completed_daily_date=date(2026, 7, 23),
        calendar=TradingCalendarRef(calendar_id="cn", revision="1", source="fixture"),
        is_open=True,
        next_open_session=date(2026, 7, 27),
        required_daily_evidence_date=date(2026, 7, 23),
    )
    base = (_candidate("000001", 0.6),)
    fused = RealRecommendationProducer._apply_serenity(
        base,
        SimpleNamespace(
            applied_weight=0.03,
            alphas={"000001": 1.0},
            reasons={"000001": ("serenity_verified_positive",)},
            reason_codes=("serenity_batch_complete",),
        ),
    )
    plan = PlanService(store).get_or_create(
        target=target,
        universe=CandidateUniverseBinding(candidate_universe_id="u", content_digest="d", total_count=1, eligible_count=1, complete=True, source="fixture"),
        policy=DecisionPolicyBinding(revision="adaptive_kernel_v3_serenity", adaptive_policy_state_version="complete", selection_policy="top30", risk_profile="normal"),
        producer=ProducerIdentity(name="fixture", revision="2", source_digest="d"),
        evaluated_candidates=fused,
        serenity=SerenityDecisionBinding(reference_id="hidden", policy_revision=POLICY_REVISION, applied_weight=0.03, state="active", reason_codes=("serenity_batch_complete",)),
        generated_at=datetime(2026, 7, 24, 9, 1, tzinfo=TZ),
    ).plan
    PublicationService(store).publish(plan_id=plan.plan_id, runtime_id=None, published_at=datetime(2026, 7, 24, 9, 1, tzinfo=TZ))
    ConversationService(store, narrator=Narrator()).reply(session_id="session", client_turn_id="turn", user_message="Serenity 怎么影响本次推荐？")

    system_prompt = captured["messages"][0]["content"]
    user_payload = captured["messages"][1]["content"]
    assert "固定 3%" in system_prompt
    assert "整个批次统一归零" in system_prompt
    assert '"综合分实际改变量": 0.03' in user_payload
    assert '"reference_id"' not in user_payload
    assert '"hidden"' not in user_payload
    assert "serenity_batch_complete" not in user_payload
