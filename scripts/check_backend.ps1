param()
$ErrorActionPreference = "Stop"

python -m compileall src
python -m pytest -q tests/test_regress_theme_and_bands.py tests/test_contract_event_and_history.py tests/test_theme_concept_fallback_no_snapshot.py tests/test_theme_pool_snapshot_paths.py tests/test_theme_pool_impl_nan_and_scale.py tests/test_strict_no_pseudo_output.py
$env:PYTHONPATH = "src"
python -m gp_assistant.recommend.self_check_contract

