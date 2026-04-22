#!/usr/bin/env bash
set -euo pipefail

python -m compileall src
python -m pytest -q \
  tests/test_regress_theme_and_bands.py \
  tests/recommend/test_contracts_v2.py \
  tests/test_theme_fallback_top_movers.py \
  tests/test_theme_pool_snapshot_paths.py \
  tests/test_theme_pool_impl_nan_and_scale.py \
  tests/test_strict_no_pseudo_output.py

# Phase 2.6 / Phase 3 gates
python -m pytest -q \
  tests/recommend/test_calibration.py \
  tests/recommend/test_refresh_service_v2.py \
  tests/api/test_compare_and_pick_endpoints.py \
  tests/api/test_recommend_v2_endpoint.py \
  tests/validation/test_event_stats.py \
  tests/validation/test_walkforward_stats.py \
  tests/validation/test_paper_trade.py \
  tests/validation/test_strategy_health.py \
  tests/validation/test_lifecycle.py \
  tests/api/test_validation_endpoints.py \
  tests/validation/test_strategy_health_penalty.py
PYTHONPATH=src python -m gp_assistant.selection_engine.self_check_contract

