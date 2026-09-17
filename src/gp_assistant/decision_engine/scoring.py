"""One daily ranking scale. This heuristic is not a calibrated probability."""
from __future__ import annotations

import math

REVISION = "daily_score_v5_causal_memory"
ROUND_TRIP_COST = 0.003


def score_candidate(*, probability: float, execution_quality: float, confidence: float,
                    drawdown_probability: float, expected_return: float) -> dict:
    values = (probability, execution_quality, confidence, drawdown_probability, expected_return)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("nonfinite_ranking_input")
    if not all(0 <= v <= 1 for v in values[:4]):
        raise ValueError("ranking_input_out_of_range")
    net = expected_return - ROUND_TRIP_COST
    score = max(0., min(1., .5*probability + .3*execution_quality + .2*confidence - .2*drawdown_probability))
    return {"score": score, "expected_net_return": net,
            "reason_codes": () if net > 0 else ("nonpositive_net_edge",)}
