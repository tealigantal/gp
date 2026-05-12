from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from .plans import clip, derive_plan, finite_float, plan_has_prices, score_0_100


STRATEGY_NAMES = [
    "TREND_CONTINUATION_5M",
    "VOLATILITY_BREAKOUT",
    "PULLBACK_RECLAIM",
    "MORNING_STRENGTH_AFTERNOON_RELAUNCH",
    "HIGH_RELATIVE_VOLUME_MOMENTUM",
    "GAP_HOLD_AND_GO",
    "RANGE_EXPANSION_AFTER_COMPRESSION",
    "RELATIVE_STRENGTH_LEADER",
    "CONTROLLED_MEAN_REVERSION",
    "NO_TRADE_STRATEGY",
]


@dataclass
class StrategyCandidate:
    strategy_name: str
    eligible: bool
    raw_score: float = 0.0
    confidence: float = 0.0
    expected_edge_score: float = 0.0
    execution_quality_score: float = 0.0
    relative_strength_score: float = 0.0
    volume_confirmation_score: float = 0.0
    location_score: float = 0.0
    rr_score: float = 0.0
    regime_fit_score: float = 0.0
    risk_penalty: float = 0.0
    data_quality_penalty: float = 0.0
    reason_codes: List[str] = field(default_factory=list)
    reject_reasons: List[str] = field(default_factory=list)
    invalidation_rules: List[str] = field(default_factory=list)
    plan: Dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> Dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "eligible": self.eligible,
            "raw_score": round(float(self.raw_score), 4),
            "confidence": round(float(self.confidence), 4),
            "expected_edge_score": round(float(self.expected_edge_score), 4),
            "execution_quality_score": round(float(self.execution_quality_score), 4),
            "relative_strength_score": round(float(self.relative_strength_score), 4),
            "volume_confirmation_score": round(float(self.volume_confirmation_score), 4),
            "location_score": round(float(self.location_score), 4),
            "rr_score": round(float(self.rr_score), 4),
            "regime_fit_score": round(float(self.regime_fit_score), 4),
            "risk_penalty": round(float(self.risk_penalty), 4),
            "data_quality_penalty": round(float(self.data_quality_penalty), 4),
            "reason_codes": list(self.reason_codes),
            "reject_reasons": list(self.reject_reasons),
            "invalidation_rules": list(self.invalidation_rules),
            "plan": dict(self.plan),
        }


def _score_formula(
    *,
    edge_score: float,
    execution_quality_score: float,
    relative_strength_score: float,
    volume_confirmation_score: float,
    location_score: float,
    rr_score: float,
    regime_fit_score: float,
    risk_penalty: float,
    data_quality_penalty: float,
) -> float:
    score = (
        0.22 * edge_score
        + 0.18 * execution_quality_score
        + 0.16 * relative_strength_score
        + 0.14 * volume_confirmation_score
        + 0.12 * location_score
        + 0.10 * rr_score
        + 0.08 * regime_fit_score
        - risk_penalty
        - data_quality_penalty
    )
    return max(0.0, min(100.0, score))


def _base_scores(features: Dict[str, Any]) -> Dict[str, float]:
    rr = max(finite_float(features.get("rr_to_take1")), finite_float(features.get("rr_to_take2")) * 0.75)
    distance = abs(finite_float(features.get("distance_to_entry")))
    location = score_0_100(1.0 - min(distance, 0.04) / 0.04)
    extended = bool(features.get("extended_flag"))
    invalidated = bool(features.get("invalidated_flag"))
    risk = 0.0
    risk += 18.0 if extended else 0.0
    risk += 70.0 if invalidated else 0.0
    risk += finite_float(features.get("exhaustion_score")) * 0.18
    data_quality_score = finite_float(features.get("data_quality_score"), 100.0)
    return {
        "edge_score": finite_float(features.get("day_level_alpha_score")),
        "execution_quality_score": max(
            0.0,
            min(
                100.0,
                0.40 * finite_float(features.get("trend_stack_score"))
                + 0.25 * score_0_100(finite_float(features.get("price_vs_vwap")) > 0)
                + 0.20 * score_0_100(finite_float(features.get("ema5_slope")) > 0)
                + 0.15 * score_0_100(not extended),
            ),
        ),
        "relative_strength_score": max(
            0.0,
            min(
                100.0,
                50.0
                + finite_float(features.get("rs_index")) * 2500.0
                + finite_float(features.get("rs_industry")) * 1600.0
                + finite_float(features.get("rs_candidate_pool")) * 1200.0,
            ),
        ),
        "volume_confirmation_score": score_0_100(min(finite_float(features.get("slot_rel_vol")) / 1.8, 1.0)),
        "location_score": location,
        "rr_score": score_0_100((rr - 1.0) / 1.6),
        "regime_fit_score": max(0.0, min(100.0, finite_float(features.get("gate_score"), 55.0))),
        "risk_penalty": max(0.0, min(90.0, risk)),
        "data_quality_penalty": max(0.0, 100.0 - data_quality_score) * 0.35,
    }


def _candidate_from_checks(
    *,
    name: str,
    features: Dict[str, Any],
    checks: Sequence[tuple[bool, str, str]],
    plan: Dict[str, Any],
    reason_codes: List[str],
    invalidation_rules: List[str],
    score_overrides: Dict[str, float] | None = None,
) -> StrategyCandidate:
    reject_reasons = [reject for passed, _reason, reject in checks if not passed]
    passed_reasons = [reason for passed, reason, _reject in checks if passed]
    scores = _base_scores(features)
    if score_overrides:
        scores.update(score_overrides)
    raw_score = _score_formula(**scores)
    eligible = not reject_reasons and plan_has_prices(plan)
    if not plan_has_prices(plan):
        reject_reasons.append("plan_prices_missing")
    if bool(features.get("invalidated_flag")) and "invalidated_flag" not in reject_reasons:
        eligible = False
        reject_reasons.append("invalidated_flag")
    return StrategyCandidate(
        strategy_name=name,
        eligible=eligible,
        raw_score=raw_score if eligible else min(raw_score, 49.0),
        confidence=clip(raw_score / 100.0) if eligible else 0.0,
        expected_edge_score=scores["edge_score"],
        execution_quality_score=scores["execution_quality_score"],
        relative_strength_score=scores["relative_strength_score"],
        volume_confirmation_score=scores["volume_confirmation_score"],
        location_score=scores["location_score"],
        rr_score=scores["rr_score"],
        regime_fit_score=scores["regime_fit_score"],
        risk_penalty=scores["risk_penalty"],
        data_quality_penalty=scores["data_quality_penalty"],
        reason_codes=[*reason_codes, *passed_reasons],
        reject_reasons=reject_reasons,
        invalidation_rules=list(invalidation_rules),
        plan=plan if plan_has_prices(plan) else {},
    )


class BaseStrategy:
    name = ""
    required_features: List[str] = []
    invalidation_rules: List[str] = []

    def eligible(self, features: Dict[str, Any]) -> bool:
        return not self.score(features).reject_reasons

    def score(self, features: Dict[str, Any]) -> StrategyCandidate:
        return self.build_candidate(features)

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        raise NotImplementedError


class TrendContinuation5m(BaseStrategy):
    name = "TREND_CONTINUATION_5M"
    required_features = ["day_level_alpha_score", "vwap", "ema5", "ema13", "rs_index", "slot_rel_vol"]
    invalidation_rules = ["close_below_vwap", "ema5_below_ema13", "stop_breached", "slot_rel_vol_fades"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        trigger = max(finite_float(features.get("recent_range_high")), finite_float(features.get("entry_mid")), finite_float(features.get("vwap")))
        return derive_plan(
            features=features,
            entry_type="trend_continuation_trigger",
            trigger_price=trigger,
            invalidation_reason="Trend continuation fails if price loses VWAP/EMA13 or breaches stop.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["close_above_vwap", "ema_stack_up", "rs_positive", "volume_confirmed"],
            confirmation_conditions=["hold above VWAP", "slot_rel_vol stays supportive"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        checks = [
            (finite_float(features.get("day_level_alpha_score")) >= 55.0, "day_alpha_strong", "day_alpha_not_strong"),
            (finite_float(features.get("price_vs_vwap")) > 0, "close_above_vwap", "close_not_above_vwap"),
            (finite_float(features.get("trend_stack_score")) >= 55.0, "ema_trend_stack", "ema_stack_not_ready"),
            (finite_float(features.get("rs_index")) > 0, "rs_index_positive", "rs_index_not_positive"),
            (
                finite_float(features.get("rs_industry")) > 0 or finite_float(features.get("industry_strength_score")) >= 55.0,
                "industry_rs_supported",
                "industry_rs_not_supported",
            ),
            (finite_float(features.get("slot_rel_vol")) >= 0.8, "slot_volume_supported", "slot_volume_weak"),
            (finite_float(features.get("drawdown_from_intraday_high")) > -0.035, "pullback_controlled", "pullback_too_deep"),
        ]
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["trend_continuation"],
            invalidation_rules=self.invalidation_rules,
        )


class VolatilityBreakout(BaseStrategy):
    name = "VOLATILITY_BREAKOUT"
    required_features = ["compression_score", "recent_range_high", "range_breakout_score", "slot_rel_vol", "vwap"]
    invalidation_rules = ["breakout_fails_back_into_range", "close_below_vwap", "upper_shadow_exhaustion"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        return derive_plan(
            features=features,
            entry_type="range_breakout",
            trigger_price=finite_float(features.get("recent_range_high")),
            invalidation_reason="Breakout is invalid if price falls back inside the recent range or loses VWAP.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["break recent_range_high", "bar range expands", "slot_rel_vol >= 1.3"],
            confirmation_conditions=["close holds above breakout line", "no fast upper-shadow rejection"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        checks = [
            (
                finite_float(features.get("compression_score")) >= 15.0 or finite_float(features.get("range_width_recent")) <= 0.035,
                "recent_range_compressed",
                "range_not_compressed",
            ),
            (finite_float(features.get("range_breakout_score")) > 0, "breaks_recent_range_high", "no_recent_range_breakout"),
            (finite_float(features.get("volume_expansion_ratio")) >= 1.15, "bar_range_volume_expands", "bar_expansion_insufficient"),
            (finite_float(features.get("slot_rel_vol")) >= 1.3, "slot_rel_vol_confirmed", "slot_rel_vol_below_1_3"),
            (finite_float(features.get("price_vs_vwap")) > 0, "close_above_vwap", "close_not_above_vwap"),
            (finite_float(features.get("exhaustion_score")) < 65.0, "false_breakout_risk_low", "false_breakout_risk_high"),
        ]
        overrides = {
            "edge_score": min(100.0, finite_float(features.get("day_level_alpha_score")) + 10.0),
            "execution_quality_score": min(100.0, _base_scores(features)["execution_quality_score"] + 6.0),
            "location_score": score_0_100(1.0 - clip(abs(finite_float(features.get("close")) / max(finite_float(features.get("recent_range_high")), 1e-6) - 1.0) / 0.025)),
        }
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["volatility_breakout"],
            invalidation_rules=self.invalidation_rules,
            score_overrides=overrides,
        )


class PullbackReclaim(BaseStrategy):
    name = "PULLBACK_RECLAIM"
    required_features = ["day_level_alpha_score", "vwap", "ema13", "entry_mid", "previous_range_high"]
    invalidation_rules = ["reclaim_fails_below_vwap_or_ema13", "stop_breached", "selling_pressure_expands"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        trigger = max(finite_float(features.get("vwap")), finite_float(features.get("ema13")), finite_float(features.get("previous_range_high")))
        return derive_plan(
            features=features,
            entry_type="pullback_reclaim",
            trigger_price=trigger,
            invalidation_reason="Reclaim fails if price loses VWAP/EMA13 again or breaches the stop.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["pullback into VWAP/EMA/entry band", "reclaim VWAP or EMA", "close above previous bar high"],
            confirmation_conditions=["selling pressure stays low", "RS remains positive"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        near_support = finite_float(features.get("support_cluster_score")) >= 45.0 or finite_float(features.get("low")) <= max(
            finite_float(features.get("vwap")), finite_float(features.get("ema13")), finite_float(features.get("entry_mid"))
        )
        reclaim = finite_float(features.get("close")) > max(finite_float(features.get("vwap")), finite_float(features.get("ema13")))
        checks = [
            (finite_float(features.get("day_level_alpha_score")) >= 55.0, "day_alpha_still_strong", "day_alpha_not_strong"),
            (near_support, "pullback_into_support_band", "not_in_pullback_band"),
            (reclaim, "reclaimed_vwap_or_ema", "not_reclaimed_vwap_or_ema"),
            (
                finite_float(features.get("close")) > finite_float(features.get("previous_range_high")) or finite_float(features.get("ret_from_prev_close")) > 0,
                "close_reclaims_previous_level",
                "previous_level_not_reclaimed",
            ),
            (not bool(features.get("invalidated_flag")), "stop_not_breached", "stop_breached"),
            (finite_float(features.get("exhaustion_score")) < 70.0, "selling_pressure_controlled", "selling_pressure_high"),
        ]
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["pullback_reclaim"],
            invalidation_rules=self.invalidation_rules,
        )


class MorningStrengthAfternoonRelaunch(BaseStrategy):
    name = "MORNING_STRENGTH_AFTERNOON_RELAUNCH"
    required_features = ["morning_return", "morning_rs_index", "vwap", "afternoon_open_range_high", "slot_rel_vol"]
    invalidation_rules = ["afternoon_breakout_fails", "lose_vwap_after_relaunch", "overextended_after_trigger"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        trigger = max(finite_float(features.get("afternoon_open_range_high")), finite_float(features.get("morning_pivot")))
        return derive_plan(
            features=features,
            entry_type="afternoon_relaunch",
            trigger_price=trigger,
            invalidation_reason="Afternoon relaunch fails if price loses VWAP or falls back under the afternoon range.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["morning strength confirmed", "afternoon reclaim VWAP", "break afternoon range or morning pivot"],
            confirmation_conditions=["afternoon volume confirms", "not overextended"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        checks = [
            (finite_float(features.get("morning_return")) >= 0.008, "morning_return_strong", "morning_return_not_strong"),
            (finite_float(features.get("morning_rs_index")) > 0, "morning_rs_positive", "morning_rs_not_positive"),
            (bool(features.get("is_lunch_reopen_window")) or str(features.get("slot_at") or "")[11:16] >= "13:05", "afternoon_window", "not_afternoon_window"),
            (finite_float(features.get("price_vs_vwap")) > 0, "afternoon_reclaims_vwap", "afternoon_not_above_vwap"),
            (
                finite_float(features.get("close")) >= max(finite_float(features.get("afternoon_open_range_high")), finite_float(features.get("morning_pivot"))),
                "breaks_afternoon_or_morning_pivot",
                "afternoon_pivot_not_broken",
            ),
            (finite_float(features.get("slot_rel_vol")) >= 1.0, "afternoon_volume_confirmed", "afternoon_volume_weak"),
            (not bool(features.get("extended_flag")), "not_overextended", "overextended"),
        ]
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["morning_strength_afternoon_relaunch"],
            invalidation_rules=self.invalidation_rules,
        )


class HighRelativeVolumeMomentum(BaseStrategy):
    name = "HIGH_RELATIVE_VOLUME_MOMENTUM"
    required_features = ["slot_rel_vol", "cumulative_volume_run_rate", "vwap", "rs_index", "money_flow_proxy"]
    invalidation_rules = ["high_volume_reversal", "lose_vwap", "late_first_spike"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        trigger = max(finite_float(features.get("close")), finite_float(features.get("recent_range_high")), finite_float(features.get("entry_high")))
        return derive_plan(
            features=features,
            entry_type="relative_volume_momentum",
            trigger_price=trigger,
            invalidation_reason="High relative volume momentum fails if the move reverses under VWAP or appears as a late first spike.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["slot_rel_vol clearly high", "volume run-rate high", "price holds above VWAP"],
            confirmation_conditions=["money flow proxy remains positive", "not a late-session first anomaly"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        checks = [
            (finite_float(features.get("slot_rel_vol")) >= 1.6, "slot_rel_vol_high", "slot_rel_vol_not_high"),
            (finite_float(features.get("cumulative_volume_run_rate")) >= 1.25, "volume_run_rate_high", "volume_run_rate_not_high"),
            (finite_float(features.get("price_vs_vwap")) > 0, "close_above_vwap", "close_not_above_vwap"),
            (finite_float(features.get("rs_index")) > 0, "rs_index_positive", "rs_index_not_positive"),
            (finite_float(features.get("money_flow_proxy")) > 0, "money_flow_positive", "money_flow_not_positive"),
            (not bool(features.get("is_late_session")) or finite_float(features.get("cumulative_volume_run_rate")) >= 1.6, "not_late_first_spike", "late_first_spike_risk"),
        ]
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["high_relative_volume_momentum"],
            invalidation_rules=self.invalidation_rules,
        )


class GapHoldAndGo(BaseStrategy):
    name = "GAP_HOLD_AND_GO"
    required_features = ["gap_pct", "day_open", "prev_close", "vwap", "rs_index", "slot_rel_vol"]
    invalidation_rules = ["gap_support_filled", "lose_vwap", "opening_range_breakout_fails"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        trigger = max(finite_float(features.get("recent_range_high")), finite_float(features.get("vwap")), finite_float(features.get("day_open")))
        return derive_plan(
            features=features,
            entry_type="gap_hold_and_go",
            trigger_price=trigger,
            invalidation_reason="Gap-hold plan fails if price fills the gap support or loses VWAP.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["reasonable gap", "gap support holds", "break opening/recent range or hold VWAP"],
            confirmation_conditions=["RS positive", "volume support"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        gap = finite_float(features.get("gap_pct"))
        checks = [
            (0.005 <= gap <= 0.06, "gap_pct_reasonable", "gap_pct_not_reasonable"),
            (finite_float(features.get("intraday_low")) >= finite_float(features.get("prev_close")) * 0.998, "gap_support_not_filled", "gap_support_filled"),
            (
                finite_float(features.get("close")) >= finite_float(features.get("recent_range_high")) or finite_float(features.get("price_vs_vwap")) > 0,
                "opening_range_or_vwap_reclaimed",
                "opening_range_not_reclaimed",
            ),
            (finite_float(features.get("rs_index")) > 0, "rs_index_positive", "rs_index_not_positive"),
            (finite_float(features.get("slot_rel_vol")) >= 0.9, "volume_supports_gap", "volume_weak"),
        ]
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["gap_hold_and_go"],
            invalidation_rules=self.invalidation_rules,
        )


class RangeExpansionAfterCompression(BaseStrategy):
    name = "RANGE_EXPANSION_AFTER_COMPRESSION"
    required_features = ["compression_score", "range_width_recent", "range_breakout_score", "volume_expansion_ratio", "day_level_alpha_score"]
    invalidation_rules = ["expansion_reverses_into_compression", "volume_expansion_fails", "daily_direction_conflict"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        return derive_plan(
            features=features,
            entry_type="compression_expansion",
            trigger_price=finite_float(features.get("recent_range_high")),
            invalidation_reason="Compression expansion fails if price falls back into the compressed range.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["multi-bar range compression", "break compression range", "volume expansion"],
            confirmation_conditions=["daily direction remains aligned", "range expansion holds"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        checks = [
            (finite_float(features.get("compression_score")) >= 35.0, "multi_bar_compression", "compression_not_enough"),
            (finite_float(features.get("range_width_recent")) <= 0.035, "range_width_low", "range_width_not_low"),
            (finite_float(features.get("range_breakout_score")) > 0, "breaks_compression_range", "no_compression_breakout"),
            (finite_float(features.get("volume_expansion_ratio")) >= 1.2, "volume_expansion", "volume_expansion_insufficient"),
            (finite_float(features.get("day_level_alpha_score")) >= 50.0, "daily_direction_aligned", "daily_direction_not_aligned"),
        ]
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["range_expansion_after_compression"],
            invalidation_rules=self.invalidation_rules,
        )


class RelativeStrengthLeader(BaseStrategy):
    name = "RELATIVE_STRENGTH_LEADER"
    required_features = ["industry_strength_score", "peer_consensus_score", "stock_rank_in_industry", "rs_index", "rs_industry", "vwap"]
    invalidation_rules = ["loses_relative_strength", "industry_leadership_fades", "lose_vwap"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        trigger = max(finite_float(features.get("recent_range_high")), finite_float(features.get("vwap")), finite_float(features.get("entry_high")))
        return derive_plan(
            features=features,
            entry_type="relative_strength_leader",
            trigger_price=trigger,
            invalidation_reason="RS leader plan fails if industry leadership fades or price loses VWAP.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["industry and peers strong", "stock ranks near industry lead", "price above VWAP"],
            confirmation_conditions=["RS remains positive versus index and industry", "daily execution quality holds"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        rank = finite_float(features.get("stock_rank_in_industry"))
        checks = [
            (finite_float(features.get("industry_strength_score")) >= 60.0, "industry_strength_high", "industry_strength_not_high"),
            (finite_float(features.get("peer_consensus_score")) >= 55.0, "peer_consensus_high", "peer_consensus_not_high"),
            (rank > 0 and rank <= 3, "stock_rank_near_top", "stock_rank_not_leading"),
            (finite_float(features.get("rs_index")) > 0, "rs_index_positive", "rs_index_not_positive"),
            (finite_float(features.get("rs_industry")) > 0, "rs_industry_positive", "rs_industry_not_positive"),
            (finite_float(features.get("price_vs_vwap")) > 0, "close_above_vwap", "close_not_above_vwap"),
            (finite_float(features.get("day_level_alpha_score")) >= 50.0, "daily_execution_quality_ok", "daily_execution_quality_weak"),
        ]
        overrides = {
            "relative_strength_score": min(
                100.0,
                0.35 * finite_float(features.get("industry_strength_score"))
                + 0.30 * finite_float(features.get("peer_consensus_score"))
                + 0.35 * finite_float(features.get("stock_rank_score_in_industry"), 50.0),
            )
        }
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["relative_strength_leader"],
            invalidation_rules=self.invalidation_rules,
            score_overrides=overrides,
        )


class ControlledMeanReversion(BaseStrategy):
    name = "CONTROLLED_MEAN_REVERSION"
    required_features = ["support_cluster_score", "drawdown_from_intraday_high", "sell_climax_proxy", "day_level_alpha_score", "gate_score"]
    invalidation_rules = ["daybook_stop_breached", "failed_reclaim", "market_gate_worsens"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        trigger = max(finite_float(features.get("vwap")), finite_float(features.get("ema13")), finite_float(features.get("entry_mid")))
        return derive_plan(
            features=features,
            entry_type="controlled_mean_reversion_reclaim",
            trigger_price=trigger,
            invalidation_reason="Mean reversion is cancelled if daybook stop breaks or no reclaim appears.",
            invalidation_rules=self.invalidation_rules,
            trigger_conditions=["near support cluster", "sell climax appears", "reclaim VWAP/EMA/entry band"],
            confirmation_conditions=["market gate not bad", "trend not structurally broken"],
        )

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        checks = [
            (finite_float(features.get("day_level_alpha_score")) >= 60.0, "strong_daily_only", "daily_not_strong_enough"),
            (finite_float(features.get("support_cluster_score")) >= 60.0, "near_support_cluster", "not_near_support_cluster"),
            (finite_float(features.get("drawdown_from_intraday_high")) >= -0.06, "trend_not_broken", "intraday_drop_too_deep"),
            (not bool(features.get("invalidated_flag")), "daybook_stop_not_breached", "daybook_stop_breached"),
            (finite_float(features.get("sell_climax_proxy")) >= 45.0, "sell_climax_proxy_present", "no_sell_climax_proxy"),
            (
                finite_float(features.get("price_vs_vwap")) > -0.006 or finite_float(features.get("close")) > finite_float(features.get("ema13")),
                "reclaim_condition_near",
                "no_reclaim_condition",
            ),
            (finite_float(features.get("gate_score")) >= 45.0, "market_gate_not_bad", "market_gate_bad"),
        ]
        overrides = {"risk_penalty": _base_scores(features)["risk_penalty"] + 8.0}
        return _candidate_from_checks(
            name=self.name,
            features=features,
            checks=checks,
            plan=self.build_plan(features),
            reason_codes=["controlled_mean_reversion"],
            invalidation_rules=self.invalidation_rules,
            score_overrides=overrides,
        )


class NoTradeStrategy(BaseStrategy):
    name = "NO_TRADE_STRATEGY"
    required_features = ["data_quality_score"]
    invalidation_rules = ["no_eligible_strategy"]

    def build_plan(self, features: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def build_candidate(self, features: Dict[str, Any]) -> StrategyCandidate:
        reasons: List[str] = []
        if finite_float(features.get("data_quality_score")) < 45.0:
            reasons.append("data_quality_too_low")
        if bool(features.get("invalidated_flag")):
            reasons.append("invalidated_flag")
        if not reasons:
            reasons.append("no_strategy_met_entry_rr_risk_requirements")
        return StrategyCandidate(
            strategy_name=self.name,
            eligible=True,
            raw_score=0.0,
            confidence=0.0,
            reason_codes=["no_trade"],
            reject_reasons=reasons,
            invalidation_rules=self.invalidation_rules,
            plan={},
        )


class StrategyRegistry:
    def __init__(self, strategies: Iterable[BaseStrategy] | None = None):
        self.strategies = list(
            strategies
            or [
                TrendContinuation5m(),
                VolatilityBreakout(),
                PullbackReclaim(),
                MorningStrengthAfternoonRelaunch(),
                HighRelativeVolumeMomentum(),
                GapHoldAndGo(),
                RangeExpansionAfterCompression(),
                RelativeStrengthLeader(),
                ControlledMeanReversion(),
                NoTradeStrategy(),
            ]
        )

    def run_all(self, features: Dict[str, Any]) -> List[StrategyCandidate]:
        return [strategy.score(features) for strategy in self.strategies]

    def normal_strategies(self) -> List[BaseStrategy]:
        return [strategy for strategy in self.strategies if strategy.name != "NO_TRADE_STRATEGY"]


def select_champion(candidates: Sequence[StrategyCandidate]) -> StrategyCandidate:
    normal = [candidate for candidate in candidates if candidate.strategy_name != "NO_TRADE_STRATEGY"]
    eligible = [candidate for candidate in normal if candidate.eligible]
    if eligible:
        return sorted(eligible, key=lambda item: item.raw_score, reverse=True)[0]
    no_trade = next((candidate for candidate in candidates if candidate.strategy_name == "NO_TRADE_STRATEGY"), None)
    if no_trade is not None:
        merged_rejects: List[str] = []
        for candidate in normal:
            for reason in candidate.reject_reasons:
                if reason not in merged_rejects:
                    merged_rejects.append(reason)
        if merged_rejects:
            no_trade.reject_reasons = merged_rejects[:16]
        return no_trade
    return NoTradeStrategy().score({})
