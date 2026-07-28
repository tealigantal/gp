from __future__ import annotations

from datetime import date, datetime, time as clock_time
import math

import pandas as pd

from ..contracts.catalog import CandidateDisposition, PlanTargetState
from ..contracts.decision import CandidateDecision, TradePlan
from ..contracts.evidence import CandidateUniverseBinding, DecisionPolicyBinding, ExpertContribution, ProbabilityAssessment, ProducerIdentity, RankingAssessment, RiskAssessment, SignalAssessment
from ..market_memory.retrieval import retrieve_similar_events
from ..market_memory.store import list_events_before
from ..core.config import load_config
from ..probability_engine.engine import infer_probability
from ..risk_engine.engine import assess_candidate_risk, rank_candidate
from .history_daily import coverage_for_date, frames as history_frames
from ..serenity.policy import bind
from ..serenity.service import FIXED_WEIGHT, POLICY_REVISION, load_decision, publish_target
from ..signal_engine.daily import build_signal_events_for_symbol
from .plan_service import PlanService
from .target_resolver import resolve_plan_target
from .trading_calendar import load_cn_a_calendar
from .market_runs import FrozenUniverse


class RealRecommendationProducer:
    """Offline production producer; it reads cached full-market daily evidence only."""

    def __init__(self, store, *, spot_loader=None, spot_meta_loader=None, daily_refresher=None):
        self.store = store
        # These constructor arguments are retained only for the explicit
        # suspension-evidence helper below.  The production producer itself is
        # now read-only: MarketDayOrchestrator owns every network collection.
        self.spot_loader = spot_loader
        self.spot_meta_loader = spot_meta_loader
        self.daily_refresher = daily_refresher

    @staticmethod
    def _no_bar_expected_symbols(
        spot: pd.DataFrame,
        *,
        eligible_symbols: frozenset[str],
        snapshot_meta: dict[str, object],
        now: datetime,
        required_daily_date: date,
        is_open: bool,
    ) -> frozenset[str]:
        """Return same-session, explicitly non-trading symbols; ambiguity stays eligible."""
        if not is_open or now.timetz().replace(tzinfo=None) < clock_time(15, 0):
            return frozenset()
        if bool(snapshot_meta.get("stale")) or bool(snapshot_meta.get("missing")) or bool(snapshot_meta.get("fallback")):
            return frozenset()
        if str(snapshot_meta.get("snapshot_session_date") or "") != required_daily_date.isoformat():
            return frozenset()
        if required_daily_date != now.date():
            return frozenset()
        source = str(snapshot_meta.get("source") or "")
        if not source:
            return frozenset()
        if snapshot_meta.get("cache"):
            try:
                age = float(snapshot_meta.get("cache_age_sec"))
            except (TypeError, ValueError):
                return frozenset()
            cfg = load_config()
            limit = cfg.cache_refresh_ttl_sec if snapshot_meta.get("cache") == "file" else cfg.ak_spot_refresh_ttl_sec
            if not math.isfinite(age) or age < 0 or age > max(1, int(limit)):
                return frozenset()
        required_columns = {"code", "prev_close", "price", "open", "high", "low", "volume", "amount"}
        if not required_columns.issubset(spot.columns):
            return frozenset()
        excluded: set[str] = set()
        for row in spot[list(required_columns)].itertuples(index=False):
            values = row._asdict()
            symbol = str(values["code"]).zfill(6)
            if symbol not in eligible_symbols:
                continue
            try:
                previous = float(values["prev_close"])
                current = tuple(float(values[key]) for key in ("price", "open", "high", "low", "volume", "amount"))
            except (TypeError, ValueError):
                continue
            if previous > 0 and math.isfinite(previous) and all(math.isfinite(value) and value == 0.0 for value in current):
                excluded.add(symbol)
        return frozenset(excluded)

    def produce(self, now: datetime, *, frozen_universe: FrozenUniverse | None = None) -> object:
        """Build a plan from one completed, frozen daily-market run only.

        This method intentionally cannot refresh daily bars or obtain a new
        spot snapshot.  Keeping it read-only is the boundary that prevents an
        incomplete recovery from inventing a new denominator or publishing an
        old fallback plan.
        """
        if frozen_universe is None:
            raise ValueError("frozen_universe_required")
        trading_calendar = load_cn_a_calendar()
        is_open = trading_calendar.is_open(now.date())
        next_open = trading_calendar.next_open_after(now.date())
        market_session = now.date() if is_open and now.timetz().replace(tzinfo=None) < clock_time(15, 0) else next_open
        required_daily_date = trading_calendar.previous_open_before(market_session)
        if frozen_universe.trade_date != required_daily_date.isoformat():
            raise ValueError("frozen_universe_target_mismatch")
        raw_eligible = frozenset(frozen_universe.raw_symbols)
        expected_tradable = frozenset(frozen_universe.expected_symbols)
        no_bar_expected = frozenset(frozen_universe.excluded_symbols)
        if not raw_eligible or not expected_tradable:
            raise ValueError("frozen_universe_empty")
        covered_rows = coverage_for_date(sorted(expected_tradable), target_date=required_daily_date.isoformat())
        covered_target = frozenset(covered_rows)
        if covered_target != expected_tradable:
            raise ValueError("daily_evidence_incomplete")
        evidence_day = required_daily_date.isoformat()
        covered_symbols = set(expected_tradable)
        target = resolve_plan_target(
            now=now,
            completed_daily_date=required_daily_date,
            calendar=trading_calendar.ref,
            is_open=is_open,
            next_open_session=next_open,
            required_daily_evidence_date=required_daily_date,
        )
        digest = frozen_universe.content_digest
        print(
            f"{{\"daily_evidence_date\":\"{required_daily_date.isoformat()}\",\"expected_tradable_count\":{len(expected_tradable)},\"exact_covered_count\":{len(covered_target)},\"complete\":true}}",
            flush=True,
        )
        universe_source = f"{frozen_universe.source}+history.db:daily"
        universe = CandidateUniverseBinding(candidate_universe_id=f"universe_{evidence_day}_{digest[:16]}", content_digest=digest, total_count=len(raw_eligible), eligible_count=len(covered_symbols), complete=True, source=universe_source)
        pool = sorted(covered_symbols, key=lambda symbol: float(covered_rows[symbol].get("amount") or 0.0), reverse=True)[:200]
        base_candidates = self._candidates(history_frames(pool), evidence_day) if target.state is PlanTargetState.READY else ()
        finalists = tuple(sorted(base_candidates, key=lambda item: (-item.adaptive_score, item.symbol))[:30])
        serenity_decision = None
        if finalists and target.daily_evidence_date is not None:
            serenity_target = publish_target(
                (item.symbol for item in finalists),
                market_session_date=target.market_session_date.isoformat(),
                daily_evidence_date=target.daily_evidence_date.isoformat(),
                universe_digest=universe.content_digest,
                base_scores={item.symbol: item.adaptive_score for item in finalists},
                observed_at=now.isoformat(),
            )
            serenity_decision = load_decision(serenity_target)
        candidates = self._apply_serenity(
            base_candidates,
            serenity_decision,
            eligible_symbols=frozenset(item.symbol for item in finalists),
        )
        serenity_binding = bind(
            reference_id=serenity_decision.reference_id if serenity_decision else None,
            policy_revision=POLICY_REVISION,
            requested_weight=FIXED_WEIGHT,
            causal_ready=bool(serenity_decision and serenity_decision.applied_weight == FIXED_WEIGHT),
            reason_codes=serenity_decision.reason_codes if serenity_decision else ("serenity_target_unavailable",),
        )
        serenity_revision = serenity_decision.semantic_revision if serenity_decision else f"{POLICY_REVISION}:zero:no_target"
        command = PlanService(self.store).get_or_create(target=target, universe=universe, policy=DecisionPolicyBinding(revision="adaptive_kernel_v3_serenity", adaptive_policy_state_version=f"1:{serenity_revision}", selection_policy="full_market_liquidity_ranked_top30", risk_profile="normal"), producer=ProducerIdentity(name="real_daily_producer", revision="2", source_digest=digest), evaluated_candidates=candidates, serenity=serenity_binding, generated_at=now, selection_eligible_symbols=frozenset(item.symbol for item in finalists))
        return command

    @staticmethod
    def _apply_serenity(
        candidates: tuple[CandidateDecision, ...],
        decision,
        *,
        eligible_symbols: frozenset[str] | None = None,
    ) -> tuple[CandidateDecision, ...]:
        if decision is None:
            return candidates
        active = decision.applied_weight == FIXED_WEIGHT
        fused: list[CandidateDecision] = []
        for candidate in candidates:
            if eligible_symbols is not None and candidate.symbol not in eligible_symbols:
                fused.append(candidate)
                continue
            alpha = float(decision.alphas.get(candidate.symbol, 0.0)) if active else 0.0
            contribution = max(-FIXED_WEIGHT, min(FIXED_WEIGHT, FIXED_WEIGHT * alpha)) if active else 0.0
            # On every degraded path retain the exact base float rather than
            # recomputing base + 0, which makes the zero lane bit-for-bit inert.
            final_score = max(0.0, min(1.0, candidate.adaptive_score + contribution)) if active else candidate.adaptive_score
            reason_codes = tuple(decision.reasons.get(candidate.symbol, decision.reason_codes))
            expert = ExpertContribution(
                expert="serenity",
                contribution=contribution,
                weight=FIXED_WEIGHT if active else 0.0,
                reason_codes=reason_codes,
            )
            fused.append(
                candidate.model_copy(
                    update={
                        "adaptive_score": final_score,
                        "experts": (*candidate.experts, expert),
                    }
                )
            )
        return tuple(fused)

    def _candidates(self, frames: dict[str, pd.DataFrame], evidence_day: str | None) -> tuple[CandidateDecision, ...]:
        pool = sorted(frames, key=lambda symbol: float(frames[symbol].iloc[-1].get("amount") or 0.0), reverse=True)[:200]
        retrieval_pool = list_events_before(str(evidence_day), require_outcome=True, limit=4000)
        candidates: list[CandidateDecision] = []
        for symbol in pool:
            signal = build_signal_events_for_symbol(
                symbol=symbol,
                df=frames[symbol],
                as_of=str(evidence_day),
                market_context={"market_regime": "C"},
                # Historical events are produced by the dedicated offline
                # evidence-maintenance lane.  Building transient history here
                # would neither be persisted nor affect this current plan.
                max_history=0,
            )
            if signal.current_event is None:
                continue
            retrieval = retrieve_similar_events(signal.current_event, as_of=str(evidence_day), event_pool=retrieval_pool)
            probability = infer_probability(current_event=signal.current_event.__dict__, retrieval=retrieval)
            risk = assess_candidate_risk(signal=signal.current_event.__dict__, probability=probability)
            ranking = rank_candidate(probability=probability, risk=risk)
            features = signal.current_event.features
            score = max(0.0, min(1.0, 0.5 * probability["up_probability_3d"] + 0.3 * risk["execution_quality"] + 0.2 * probability["confidence"] - 0.2 * probability["drawdown_probability"]))
            candidates.append(CandidateDecision(symbol=symbol, name=symbol, disposition=CandidateDisposition.REJECTED, adaptive_score=score, recommendation_strength="normal" if score >= .55 else "cautious", signal=SignalAssessment(score=float(features.get("trend_strength") or 0.0), label=signal.current_event.signal_type, reason_codes=()), probability=ProbabilityAssessment(probability=probability["up_probability_3d"], confidence=probability["confidence"], effective_sample_size=probability["evidence"]["effective_sample_size"], uncertainty=probability["uncertainty"]), risk=RiskAssessment(score=risk["risk_adjustment"], execution_risk=1-risk["risk_adjustment"], reason_codes=tuple(risk["risk_flags"])), ranking=RankingAssessment(score=ranking["ranking_score"], rank=0, reason_codes=()), experts=(), trade_plan=TradePlan(entry_low=risk["entry"].get("low"), entry_high=risk["entry"].get("high"), stop_price=risk["stop"].get("price"), take_profit_prices=tuple(risk["take_profit"].get("targets") or ()), action="watch", reason_codes=tuple(risk["risk_flags"])), reason_codes=tuple(risk["risk_flags"])))
        return tuple(candidates)
