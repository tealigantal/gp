# GP Repository Operating Contract

## Product outcome

GP is a chat-first A-share main-board decision assistant for short 1–3 trading-day plans. It must ground recommendations, follow-ups, comparisons, and position decisions in the same real-data Market-Memory artifacts while keeping the LLM outside stock selection and numerical authority.

## Lifecycle stage

The repository is an initialized important project in integration and historical-validation stage. Full-market candidate-universe recovery is part of the current contract kernel; Serenity is governed by ADR 0010 and the active fixed-3% unified-worker plan.

## Critical journeys

- Generate a current Top-N plan or an explicit no-trade result from real market data.
- Explain why a selected or rejected symbol received its position without inventing facts.
- Answer symbol, comparison, exit, and run-change follow-ups from the same canonical run.
- Fail closed when required market data is stale or incomplete.
- Apply Serenity to the frozen base Top-30 only as an atomic fixed-3% batch; any incomplete, failed, stale, or mismatched batch contributes zero to every finalist.

## Repository map and sources of truth

Before changing the recommendation path, read `docs/contracts/CURRENT_CONTRACTS.md`, `docs/contracts/RETIRED_CONTRACTS.md`, and `docs/contracts/registry.yaml`.

- `README.md`: product onboarding and user-visible workflows.
- `PROJECT_GOAL.md`: durable objective, constraints, and approval gates.
- `docs/PRODUCT.md`: product behavior and recovery experience.
- `docs/ARCHITECTURE.md`: system-level ownership and dependency map.
- `src/gp_assistant/ARCHITECTURE.md`: detailed backend decision architecture and LLM boundary.
- `docs/service_contract.md`: HTTP and domain-output contracts.
- `docs/data_freshness_policy.md`: freshness and as-of rules.
- `docs/historical_validation.md`: historical replay method and recorded results.
- `docs/VALIDATION.md`: cross-cutting validation ledger.
- `docs/PROGRESS.md`: recoverable current status.
- `docs/plans/2026-07-24-serenity-fixed-three-percent-worker.md`: active Serenity fixed-3% integration ExecPlan.
- `docs/adr/0010-serenity-fixed-three-percent-unified-worker.md`: current Serenity weight and deployment decision.

## Verified entry points and commands

- Backend: `PYTHONPATH=src python -m gp_assistant serve --host 127.0.0.1 --port 8000`
- Runtime worker: `PYTHONPATH=src python -m gp_assistant worker`
- Compile: `python -m compileall -q src tests`
- Backend tests: `python -m pytest -q` (integration tests are excluded by `pytest.ini` unless explicitly selected)
- Frontend: from `frontend/`, run `npm ci`, then `npm run lint`, `npm run typecheck`, `npm test -- --run`, and `npm run build`
- Docker services: `docker compose up -d gp gp-worker web`
- Historical replay: use the isolated-store command in `docs/historical_validation.md`.

The backend has no verified Ruff or static-type-check command. Do not claim those checks ran unless the repository later adds and executes them.

## Architecture and dependency boundaries

- GP is a recommendation assistant, not a system whose success criterion is merely producing a stable response. A recommendation is valid only when its actual input scope, data freshness, and source provenance meet the product promise; a green health check, a valid schema, or an LLM response never substitutes for that evidence.
- A production "全市场" recommendation must use a current, complete, traceable full-market candidate universe. Do not silently narrow it to a static watchlist, prior picks, a cache fragment, or another small fallback. If the complete universe or its required data is unavailable, fail closed with an explicit unavailable/no-recommendation result.
- Treat any change that disables, bypasses, narrows, replaces, or degrades the production candidate-universe source as a consequential product change. Before making it, prove that the replacement preserves the required coverage and freshness, record its provenance and counts, and obtain explicit user approval when it changes the user-visible recommendation scope.
- Validate the real production journey at the coverage boundary: record and check candidate source, total input universe, eligible main-board count, scored count, selected count, as-of date, and fallback status. Freshness checks over only selected symbols must not be described as full-market completeness, and readiness must fail when the configured full-market coverage invariant is not satisfied.
- Adaptive Decision Engine owns selection. The LLM may route and narrate but may not invent or change candidates, scores, prices, probabilities, or actions.
- Do not use keyword matching or `if`/`else` text branches to produce, suppress, narrow, rerank, or replace user-facing LLM conclusions. In particular, do not treat incidental words or characters in a preference such as “收益大一点” as a fixed Top-N quantity or a single-symbol instruction.
- For a follow-up that refines a prior candidate list, preserve the complete structured candidate scope from that canonical run. Pass the relevant candidate facts to the LLM for explanation; never collapse the scope to `focus_symbol` or fabricate a keyword-triggered answer. Any deterministic filtering or ordering must consume explicit structured user constraints and must remain separate from the LLM's output generation.
- Network data collection must not run inside `/api/chat`, book locks, or decision rendering.
- Historical and adaptive learning paths must respect as-of availability and T+5 maturity; never place future outcomes in readable pending state.
- `store/`, `cache/`, and `results/` are runtime artifacts. Preserve user data and never stage them unless explicitly requested.
- `selection_engine/` is legacy/reference and low-level support, not the production ranking authority.
- New evidence stores must be append-only for versions and first-seen semantics; do not reuse overwrite-oriented `history.db` for Serenity.
- Serenity collection runs only in the isolated child process supervised by `gp-worker`. Recommendation and chat paths may publish/read a target or committed batch but never perform network collection.
- Serenity has only two effective weights: a complete exact batch uses 3%; every other state uses 0% for the whole batch. The LLM may explain bound product facts but never compute the contribution or expose storage/interface internals.

## Approval gates

User approval is required before deployment, publication, secret changes, paid data acquisition, destructive migration, commercial use of public data, or public API breaks. On 2026-07-24 the user authorized local deployment of free-data Serenity at an atomic fixed 3% weight in the unified worker and exact removal of the obsolete standalone Serenity container.

## Definition of done

A change is complete only when the real user flow works, causal/data-integrity invariants hold, targeted and regression tests have actually run, operational failure is observable and recoverable, documentation reflects reality, and unrelated runtime files such as `store/book/current_slot.json` remain untouched.
