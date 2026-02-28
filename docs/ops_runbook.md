# Ops Runbook

This runbook describes day-to-day operations for the unified research + live recommendation system.

Prerequisites
- Configure `configs/config.yaml` (fees, slippage, max_positions, vol_unit)
- Ensure directories exist: `data/`, `universe/`, `store/`, `results/`

1) Data Update
- Basics + Daily bars:
  - python gpbt.py fetch --provider tushare --start 20250101 --end 20250131
- Candidate pool (daily):
  - python gpbt.py build-candidates --date 20250106 --pool_size 20
- Minute bars for pool (optional refresh):
  - python gpbt.py fetch-min5-for-pool --provider tushare --date 20250106

2) Research Update
- Experiment grid:
  - python gpbt.py experiment --config configs/config.yaml --experiments configs/experiments/demo_grid.yaml --start 20250101 --end 20250131 --exp_id jan_grid
- Tournament realistic (select champion OOS):
  - python gpbt.py tournament --config configs/config.yaml --strategies configs/strategies/*.yaml --start 20250101 --end 20250131 --mode realistic --training_window 5 --reselect_interval weekly --tournament_id jan_tour --emit_registry store/registry/champion.json

3) Service Run (Daily)
- Preopen (generate picks and publish):
  - python gpbt.py service preopen --date 20250106 --topk 10
- Intraday (idempotent, can run periodically every 5 minutes):
  - python gpbt.py service intraday --date 20250106 --once
- Close (finalize day and publish):
  - python gpbt.py service close --date 20250106
- Publish (re-publish latest as needed):
  - python gpbt.py service publish --date 20250106

Cron Examples (Linux crontab)
- Preopen 09:10 CST:
  - 10 9 * * 1-5 cd /app/gp && /usr/bin/python gpbt.py service preopen --date $(date +\%Y\%m\%d) --topk 10
- Intraday every 10 minutes 09:30–15:00:
  - */10 9-15 * * 1-5 cd /app/gp && /usr/bin/python gpbt.py service intraday --date $(date +\%Y\%m\%d) --once
- Close 15:10 CST:
  - 10 15 * * 1-5 cd /app/gp && /usr/bin/python gpbt.py service close --date $(date +\%Y\%m\%d)

Health Checks
- Gate A: Basic
  - python -m compileall -q .
  - python -m pytest -q
  - python -m backtest.runner_weekly --config configs/config.yaml --strategies configs/strategies/*.yaml --start 20250106 --end 20250110 --run_id demo_fixture
  - python gpbt.py doctor --level basic
- Gate B: Service
  - python gpbt.py service preopen --date 20250106
  - python gpbt.py service intraday --date 20250106 --once
  - python gpbt.py service close --date 20250106
- Gate C: Research
  - python gpbt.py experiment --config configs/config.yaml --experiments configs/experiments/demo_grid.yaml --start 20250106 --end 20250110 --exp_id demo_matrix
  - python gpbt.py tournament --config configs/config.yaml --strategies configs/strategies/*.yaml --start 20250106 --end 20250131 --mode realistic --training_window 5 --reselect_interval weekly --tournament_id demo_real --emit_registry store/registry/champion.json

