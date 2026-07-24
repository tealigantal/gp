from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time as clock_time
from hashlib import sha256
import json
import math

import pandas as pd

from ..contracts.catalog import CandidateDisposition, PlanTargetState
from ..contracts.decision import CandidateDecision, TradePlan
from ..contracts.evidence import CandidateUniverseBinding, DecisionPolicyBinding, ExpertContribution, ProbabilityAssessment, ProducerIdentity, RankingAssessment, RiskAssessment, SignalAssessment
from ..market_memory.retrieval import retrieve_similar_events
from ..market_memory.store import list_events_before
from ..providers.boards import is_mainboard
from ..providers.factory import get_provider
from ..core.config import load_config
from ..probability_engine.engine import infer_probability
from ..risk_engine.engine import assess_candidate_risk, rank_candidate
from .history_daily import frames as history_frames, latest_rows
from .daily_refresh import DailyEvidenceRefresher
from ..serenity.policy import bind
from ..serenity.service import FIXED_WEIGHT, POLICY_REVISION, load_decision, publish_target
from ..signal_engine.daily import build_signal_events_for_symbol
from .plan_service import PlanService
from .publication_service import PublicationService
from .target_resolver import resolve_plan_target
from .trading_calendar import load_cn_a_calendar


class RealRecommendationProducer:
    """Offline production producer; it reads cached full-market daily evidence only."""

    def __init__(self, store, *, spot_loader=None, spot_meta_loader=None, daily_refresher=None):
        self.store = store
        self.provider = get_provider(prefer="akshare") if spot_loader is None else None
        self.spot_loader = spot_loader or self.provider.get_spot_snapshot
        self.spot_meta_loader = spot_meta_loader or (
            self.provider.last_snapshot_meta if self.provider is not None else (lambda: {})
        )
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

    def produce(self, now: datetime, *, refresh_daily: bool = False) -> object:
        latest = latest_rows()
        spot = self.spot_loader()
        snapshot_meta = dict(self.spot_meta_loader() or {})
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
        trading_calendar = load_cn_a_calendar()
        is_open = trading_calendar.is_open(now.date())
        next_open = trading_calendar.next_open_after(now.date())
        market_session = now.date() if is_open and now.timetz().replace(tzinfo=None) < clock_time(15, 0) else next_open
        required_daily_date = trading_calendar.previous_open_before(market_session)
        raw_eligible = frozenset(eligible_symbols)
        no_bar_expected = self._no_bar_expected_symbols(
            spot,
            eligible_symbols=raw_eligible,
            snapshot_meta=snapshot_meta,
            now=now,
            required_daily_date=required_daily_date,
            is_open=is_open,
        )
        expected_tradable = raw_eligible - no_bar_expected

        def exact_covered(rows: dict[str, dict[str, object]]) -> frozenset[str]:
            return frozenset(
                symbol
                for symbol in expected_tradable
                if symbol in rows and str(rows[symbol].get("date") or "")[:10] == required_daily_date.isoformat()
            )

        covered_target = exact_covered(latest)
        complete = bool(expected_tradable and covered_target == expected_tradable)
        refresh_report: dict[str, int] | None = None
        if refresh_daily and not complete:
            missing = sorted(expected_tradable - covered_target)
            refresher = self.daily_refresher or DailyEvidenceRefresher(self.provider or get_provider(prefer="akshare"))
            refresh_report = refresher.refresh(
                symbols=missing,
                start=required_daily_date.isoformat(),
                end=required_daily_date.isoformat(),
                target_date=required_daily_date.isoformat(),
            )
            latest = latest_rows()
            covered_target = exact_covered(latest)
            complete = bool(expected_tradable and covered_target == expected_tradable)

        dates = Counter(
            str(latest[symbol].get("date") or "")[:10]
            for symbol in raw_eligible
            if symbol in latest and str(latest[symbol].get("date") or "")[:10] != required_daily_date.isoformat()
        )
        fallback_day = dates.most_common(1)[0][0] if dates else None
        evidence_day = required_daily_date.isoformat() if complete else fallback_day
        covered_symbols = {
            symbol
            for symbol in expected_tradable
            if evidence_day and symbol in latest and str(latest[symbol].get("date") or "")[:10] == evidence_day
        }
        target = resolve_plan_target(
            now=now,
            completed_daily_date=date.fromisoformat(evidence_day) if evidence_day else None,
            calendar=trading_calendar.ref,
            is_open=is_open,
            next_open_session=next_open,
            required_daily_evidence_date=required_daily_date,
        )
        digest_payload = {
            "schema": "CandidateUniverseEvidence.v2",
            "target_daily_date": required_daily_date.isoformat(),
            "raw_eligible_symbols": sorted(raw_eligible),
            "no_bar_expected_symbols": sorted(no_bar_expected),
            "exact_covered_symbols": sorted(covered_target),
        }
        digest = sha256(json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        print(
            json.dumps(
                {
                    "daily_evidence_date": required_daily_date.isoformat(),
                    "raw_mainboard_count": len(raw_eligible),
                    "no_bar_expected_count": len(no_bar_expected),
                    "expected_tradable_count": len(expected_tradable),
                    "exact_covered_count": len(covered_target),
                    "missing_count": len(expected_tradable - covered_target),
                    "complete": complete,
                    "refresh": refresh_report,
                    "snapshot_source": str(snapshot_meta.get("cache_of") or snapshot_meta.get("source") or "unknown"),
                    "snapshot_session_date": str(snapshot_meta.get("snapshot_session_date") or ""),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        universe = CandidateUniverseBinding(candidate_universe_id=f"universe_{evidence_day or 'unavailable'}_{digest[:16]}", content_digest=digest, total_count=len(raw_eligible), eligible_count=len(covered_symbols), complete=complete, source="akshare:spot+history.db:daily")
        pool = sorted(covered_symbols, key=lambda symbol: float(latest[symbol].get("amount") or 0.0), reverse=True)[:200]
        base_candidates = self._candidates(history_frames(pool), evidence_day) if complete and target.state is PlanTargetState.READY else ()
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
        current_publication = self.store.current_publication()
        current_plan = self.store.load_plan(current_publication.plan_id) if current_publication else None
        lunch_is_current = bool(
            current_plan
            and current_plan.market_session_date == command.plan.market_session_date
            and current_plan.producer.name == "lunch_5m_producer"
        )
        if not lunch_is_current and (current_publication is None or current_publication.plan_id != command.plan.plan_id):
            PublicationService(self.store).publish(plan_id=command.plan.plan_id, runtime_id=None, published_at=now)
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
