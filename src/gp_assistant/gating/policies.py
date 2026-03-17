from __future__ import annotations

# Thresholds for item-level gating
FINAL_SCORE_BLOCK = 0.20
FINAL_SCORE_DEGRADE = 0.35

RELIABILITY_BLOCK = 0.20
RELIABILITY_DEGRADE = 0.30

# Strategy health mapping
HEALTH_BLOCK = {"killed"}
HEALTH_DEGRADE = {"degraded"}

# Run-level thresholds
WALKFORWARD_MISSING_DEGRADE_RATIO = 0.5  # if >50% strategies missing wf -> degrade run

