# Implementation Notes (tealigantal/gp)

This document records the repo self-check and integration points used by the agent and tests.

## 0) Repo Snapshot (top-level)

- Entrypoints at root:
  - `assistant.py` → runs module `src/gp_assistant/cli`
  - `gpbt.py` → runs module `src/gpbt/cli`
  - `gp.py` (not modified)
- Configs:
  - `configs/assistant.yaml` (assistant settings)
  - `configs/llm.yaml` (LLM provider; default points to `http://llm-proxy:8080/v1`)
  - `configs/strategies/*.yaml` (strategy params)
- Data and outputs:
  - Universe candidates: `universe/candidate_pool_YYYYMMDD.csv`
  - Results: `results/run_*/...` (compare_strategies.csv, per-strategy outputs)
  - Data root: `data/`
- Docker & services:
  - `Dockerfile`, `docker-compose.yml`, `.env.example`
  - `services/llm_proxy/` (OpenAI-compatible pass-through)
- Tests & scripts:
  - `tests/` (offline fixtures and constraints)
  - `scripts/selfcheck.py`, `scripts/scan_secrets.py`, `scripts/test_docker.sh`

## 1) gpbt CLI (src/gpbt/cli.py)

Available and used subcommands:
- `init` – initialize directory structure (data/universe/results)
- `fetch` – fetch data; supports `--codes` to limit to pool (used for safe daily backfill)
- `build-candidates` / `build-candidates-range` – construct candidate pools by date
- `doctor` – writes `results/run_*/doctor_report.json` summarizing coverage and gaps
- `backtest` – run strategies (weekly aggregation); outputs compare CSV and metrics
- `llm-rank` – LLM (or mock/fallback) ranking for a date/template; writes ranked CSV and raw JSON cache
- `tune` / `llm-run` – retained; not required for this delivery

## 2) Assistant Entrypoint

- `assistant.py` → `src/gp_assistant/cli.py`
- `chat` command:
  - REPL interactive and one-shot mode (`--once`)
  - Natural-language triggers for “荐股/推荐/选股/topk/TopK/前5”等
  - `/pick --date YYYYMMDD|YYYY-MM-DD|YYYY/MM/DD --topk K --template momentum_v1|pullback_v1|defensive_v1 --mode auto|llm|rule`

## 3) LLM Config

- `configs/llm.yaml`: default provider `deepseek`, base_url `http://llm-proxy:8080/v1`, `api_key_env: DEEPSEEK_API_KEY`
- Supports `provider: mock` for offline deterministic ranking

## 4) File Conventions

- Candidate pool: `universe/candidate_pool_<YYYYMMDD>.csv`
- LLM cache: `data/llm_cache/outputs/date=<D>/template=<T>.json`
- Ranked CSV: `universe/candidate_pool_<D>_ranked_<T>.csv`
- Assistant picks: `store/assistant/picks/pick_<D>_<T>_<mode>.json`
- Backtest results: `results/run_*/...`

## 5) Notes on Integration

- The agent only uses allowlisted `gpbt` subcommands via a controlled runner wrapper.
- When LLM is unavailable (no key/proxy), auto mode falls back to a deterministic, interpretable rule ranking.
- All logs and persisted outputs are sanitized; no API keys are written to disk.

## 6) Docker Import Errors (Repro + Fix)

Repro inside container (before fix):
- `docker compose run --rm gp python assistant.py chat` → raised `attempted relative import beyond top-level package` due to `src/gp_assistant/actions/pick.py` using `from ...gpbt` (cross-package relative import went beyond top-level `gp_assistant`).
- `docker compose run --rm gp python -m gp_assistant.cli chat` → `ModuleNotFoundError: No module named 'gp_assistant'` because the package under `src/` was not installed/importable.

Fixes applied:
- Converted cross-package relative imports to absolute: `from gpbt.storage import ...` in `src/gp_assistant/actions/pick.py`.
- Added `pyproject.toml` with setuptools `[tool.setuptools.packages.find] where=["src"]` and updated Dockerfile to `pip install -e .` after requirements so `gp_assistant` and `gpbt` are importable.
- Switched compose command to module entry: `python -m gp_assistant.cli chat`.
- Removed `version:` key from `docker-compose.yml` to eliminate obsolete warning.

Validation (container):
- `docker compose build --no-cache gp`
- `docker compose run --rm gp python -c "import gp_assistant; print('ok')"` → ok
- `docker compose run --rm gp python -m gp_assistant.cli --help` → shows usage
- `docker compose run --rm gp` → enters REPL without relative import errors

## 7) IndentationError in gp container (Repro + Fix)

Repro (before fix):
- `docker compose run --rm gp` during import raised:
  - `IndentationError: expected an indented block after function definition on line 82`
  - File: `/app/src/gp_assistant/actions/pick.py`
  - An import statement (`from gpbt.storage import load_parquet, raw_path`) appeared at top-level immediately after a function header due to a merge artifact.

Fix:
- Consolidated imports to file top, ensured all function bodies are properly indented.
- Added tests to run `python -m compileall -q src/gp_assistant` to guard against regressions.
