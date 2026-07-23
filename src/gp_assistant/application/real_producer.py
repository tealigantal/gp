from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from hashlib import sha256
import json

import pandas as pd

from ..contracts.catalog import CandidateDisposition, PlanTargetState
from ..contracts.decision import CandidateDecision, TradePlan
from ..contracts.evidence import CandidateUniverseBinding, DecisionPolicyBinding, ProbabilityAssessment, ProducerIdentity, RankingAssessment, RiskAssessment, SignalAssessment
from ..market_memory.retrieval import retrieve_similar_events
from ..market_memory.store import list_events_before
from ..providers.boards import is_mainboard
from ..providers.factory import get_provider
from ..probability_engine.engine import infer_probability
from ..risk_engine.engine import assess_candidate_risk, rank_candidate
from .history_daily import frames as history_frames, latest_rows
from .daily_refresh import DailyEvidenceRefresher
from ..serenity.policy import bind
from ..signal_engine.daily import build_signal_events_for_symbol
from .plan_service import PlanService
from .publication_service import PublicationService
from .target_resolver import resolve_plan_target
from .trading_calendar import load_cn_a_calendar


class RealRecommendationProducer:
    """Offline production producer; it reads cached full-market daily evidence only."""

    def __init__(self, store, *, spot_loader=None, daily_refresher=None):
        self.store = store
        self.provider = get_provider(prefer="akshare") if spot_loader is None else None
        self.spot_loader = spot_loader or self.provider.get_spot_snapshot
        self.daily_refresher = daily_refresher

    def produce(self, now: datetime, *, refresh_daily: bool = False) -> object:
        latest = latest_rows()
        spot = self.spot_loader()
        if not isinstance(spot, pd.DataFrame) or spot.empty:
            raise ValueError("candidate_universe_unavailable")
        required_columns = {"code", "name"}
        if not required_columns.issubset(set(spot.columns)):
            raise ValueError("candidate_universe_schema_invalid")
        eligible_symbols = sorted(
            {
                str(row.code).zfill(6)
                for row in spot[["code", "name"]].itertuples(index=False)
                if is_mainboard(str(row.code))
                and "ST" not in str(row.name).upper()
                and "退" not in str(row.name)
            }
        )
        if not eligible_symbols:
            raise ValueError("candidate_universe_empty")
        dates = Counter(str(row["date"])[:10] for row in latest.values())
        evidence_day, covered = dates.most_common(1)[0] if dates else (None, 0)
        covered_symbols = {
            symbol for symbol in eligible_symbols
            if symbol in latest and str(latest[symbol]["date"])[:10] == evidence_day
        }
        total = len(eligible_symbols)
        complete = bool(evidence_day and covered_symbols and len(covered_symbols) / total >= 0.999)
        trading_calendar = load_cn_a_calendar()
        is_open = trading_calendar.is_open(now.date())
        next_open = trading_calendar.next_open_after(now.date())
        market_session = now.date() if is_open and now.timetz().replace(tzinfo=None).hour < 15 else next_open
        target = resolve_plan_target(
            now=now,
            completed_daily_date=date.fromisoformat(evidence_day) if evidence_day else None,
            calendar=trading_calendar.ref,
            is_open=is_open,
            next_open_session=next_open,
            required_daily_evidence_date=trading_calendar.previous_open_before(market_session),
        )
        if refresh_daily and target.state is PlanTargetState.PENDING_DAILY_EVIDENCE:
            refresher = self.daily_refresher or DailyEvidenceRefresher(self.provider or get_provider(prefer="akshare"))
            refresher.refresh(symbols=eligible_symbols, start=target.daily_evidence_date.isoformat() if target.daily_evidence_date else target.market_session_date.isoformat(), end=now.date().isoformat())
            return self.produce(now, refresh_daily=False)
        digest = sha256("|".join(f"{symbol}:{latest[symbol]['date']}" for symbol in sorted(covered_symbols)).encode()).hexdigest()
        universe = CandidateUniverseBinding(candidate_universe_id=f"universe_{evidence_day or 'unavailable'}_{digest[:16]}", content_digest=digest, total_count=total, eligible_count=len(covered_symbols), complete=complete, source="akshare:spot+history.db:daily")
        pool = sorted(covered_symbols, key=lambda symbol: float(latest[symbol].get("amount") or 0.0), reverse=True)[:200]
        candidates = self._candidates(history_frames(pool), evidence_day) if complete and target.state is PlanTargetState.READY else ()
        command = PlanService(self.store).get_or_create(target=target, universe=universe, policy=DecisionPolicyBinding(revision="adaptive_kernel_v2", adaptive_policy_state_version="1", selection_policy="full_market_liquidity_ranked", risk_profile="normal"), producer=ProducerIdentity(name="real_daily_producer", revision="1", source_digest=digest), evaluated_candidates=candidates, serenity=bind(reference_id=None, policy_revision="native_causal_v1", requested_weight=0.0, causal_ready=False), generated_at=now)
        PublicationService(self.store).publish(plan_id=command.plan.plan_id, runtime_id=None, published_at=now)
        return command

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
