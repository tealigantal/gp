# Refactor Plan: Single-Entry Agent + Pluggable Providers (AkShare fallback)

This document summarizes the repository refactor to a minimal, single-entry design where the Agent is the only orchestrator and all business logic is accessed as tools. Providers are pluggable with AkShare as default and Official as a future option.

## Deleted Entry Scripts (root)
- `assistant.py`
- `backtest.py`
- `gp.py`
- `gpbt.py`
- `run.py`
- `serve.py`
- `update.py`

All previous root-level wrappers are removed to enforce a single external entry.

## Current Entrypoints Observed (before refactor)
- README referenced: `python gp.py recommend ...` and `python assistant.py chat ...`
- docker-compose used: `python -m gp_assistant.cli chat`


## New Single Entry
- `python -m gp_assistant` (preferred)
  - Subcommands: `chat`, `data`, `pick`, `backtest`

Docker/compose are updated to use: `python -m gp_assistant chat`.

## Directory Structure (Before → After)

Before (highlights):
- `src/gp/` (legacy CLI/features/strategies)
- `src/gp_core/` (pipeline)
- `src/gpbt/` (backtest + providers)
- `src/gp_assistant/` (previous assistant implementation)
- Root entry wrappers (`assistant.py`, `gp.py`, etc.)

After (consolidated agent-centric):
- `src/gp_assistant/`
  - `__main__.py` (supports `python -m gp_assistant`)
  - `cli.py` (only CLI entry)
  - `agent/`
    - `agent.py` (orchestration: parse → route → exec → format)
    - `state.py` (session/runtime state)
    - `router.py` (rule-based router: data/pick/backtest/help)
  - `tools/`
    - `registry.py` (tool registry)
    - `market_data.py` (data fetch via provider)
    - `universe.py` (universe construction)
    - `signals.py` (basic indicators; placeholder)
    - `rank.py` (simple ranking; placeholder)
    - `backtest.py` (placeholder)
    - `explain.py` (optional placeholder)
  - `providers/`
    - `base.py` (MarketDataProvider interface)
    - `akshare_provider.py` (default provider)
    - `official_provider.py` (credentialed placeholder)
    - `factory.py` (single decision point for selection/fallback)
  - `core/`
    - `config.py` (env-backed config; single defaults point)
    - `paths.py` (centralized path mgmt for data/cache/store/results/universe)
    - `logging.py` (basic logging setup)
    - `errors.py` (readable exceptions)
    - `types.py` (shared types)

Other top-level folders (`configs/`, `store/`, `cache/`, etc.) are preserved.

## Provider Selection Logic
- Configuration: `DATA_PROVIDER` env (default `akshare`), `OFFICIAL_API_KEY` for future official provider.
- Selection & fallback logic exists only in `src/gp_assistant/providers/factory.py`.
  - If `official` is selected but missing credentials, do not crash; auto-downgrade to AkShare and log a clear message.
  - `provider_health()` returns `{selected, name, ok, reason}` for diagnostics.

## Compatibility (Docker)
- `Dockerfile` CMD changed to: `python -m gp_assistant chat`.
- `docker-compose.yml` command updated to: `python -m gp_assistant chat`.
- Volumes and service names unchanged; AkShare is included in `requirements.txt`.

## Notes on Rule Consolidation
- Path rules centralized in `core/paths.py` (no hardcoded relative joins in tools).
- Provider choice/fallback centralized in `providers/factory.py` (no scattered if/else).
- Defaults consolidated in `core/config.py` (tools do not read env/YAML directly).
- Remove duplicated logic across `assistant/gp/gpbt` in favor of single tool implementations.

## Smoke Tests
- Added `tools/smoke_test.py` with three checks:
  1) `provider.healthcheck()` structure and reasoning.
  2) `gp data --symbol ...` produces readable output or readable error.
  3) `gp pick` runs and outputs structured result (even if empty).

Run: `python tools/smoke_test.py`
