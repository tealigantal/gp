# Architecture and Usage (gp_core Pipeline)

This backend is structured as 3 modules plus one orchestrator pipeline:
- MarketInfo: real web search + article fetching + LLM summarization to a two‑week market context (with sources).
- StrategyEngine: LLM strategy selection + per‑strategy run/explanation using local data (gpbt) → per‑strategy results.
- AnswerComposer: LLM composition of the final recommendation using user question + profile + A/B/run results.
- Pipeline: Step1–Step5 orchestration with all prompts and raw LLM responses persisted per run.

Important: No mock/fallback in production. Missing keys will fail fast.

## Layout
- `src/gp_core/`: core modules (schemas/io/llm/search/market_info/strategies/judge/qa/pipeline)
- `src/gp/cli.py`: `gp recommend` command
- `src/gp/serve.py`: Pipeline API
- `configs/`: `llm.yaml`, `search.yaml`, `strategies.yaml`, `pipeline.yaml`
- `store/pipeline_runs/`: per‑run artifacts

## Quick Start
1) Install deps: `pip install -r requirements.txt`
2) Configure env: `cp .env.example .env` and set keys:
   - `DEEPSEEK_API_KEY` (or your LLM provider key/base_url/model)
   - `TAVILY_API_KEY` (or `BING_API_KEY`/`SERPAPI_API_KEY`)
3) Prepare data (example): `python gpbt.py init`

### CLI (Pipeline)
```
python gp.py recommend --date 2026-02-09 --question "short-term opportunities this week?" --topk 3 --profile profile.json
```
This prints the final recommendation and writes artifacts into `store/pipeline_runs/{run_id}/`:
- 01_market_context.json
- 01_sources.jsonl
- 02_selected_strategies.json
- 03_strategy_runs/{strategy_id}.json
- 04_champion.json
- 05_final_response.json
- 05_final_response.txt
- prompts/{step}_{name}.json (request messages)
- llm_raw/{step}_{name}.json (raw responses)

### Assistant (one‑shot)
```
python assistant.py chat --once "recommend for 2026-02-09; cash 26722.07; positions ..."
```
First run triggers the pipeline and stores run_id in session; follow‑ups like “why No.2?” only read the latest run artifacts.

## API (FastAPI)
- POST `/api/recommend` → run pipeline and return `{run_id, response}`
- GET  `/api/runs/{run_id}` → return `index.json`
- GET  `/api/runs/{run_id}/artifacts/{name}` → download a single artifact (json/jsonl/txt)

## Config
- `configs/llm.yaml`: must be a real provider; missing key fails.
- `configs/search.yaml`: real search provider (tavily/bing/serpapi) and matching env var.
- `configs/strategies.yaml`: registry of strategies.
- `configs/pipeline.yaml`: defaults for lookback/topk/queries.

## Repro and Audit
Each run writes `index.json` and all prompts/raw responses for full reproducibility.
