# GP Repository Operating Contract

## Product outcome

GP is a chat-first A-share main-board decision assistant for short 1–3 trading-day plans. It must ground recommendations, follow-ups, comparisons, and position decisions in the same real-data Market-Memory artifacts while keeping the LLM outside stock selection and numerical authority.

## Lifecycle stage

The repository is an initialized important project being deliberately reduced to a single-protocol chat-first recommendation agent. The active project-shaping effort is `docs/plans/2026-07-13-single-protocol-agent.md`.

## Critical journeys

- Generate a current Top-N plan or an explicit no-trade result from real market data.
- Explain why a selected or rejected symbol received its position without inventing facts.
- Answer symbol, comparison, exit, and run-change follow-ups from the same canonical run.
- Fail closed when required market data is stale or incomplete.
- Keep Serenity evidence advisory in shadow mode and automatically promote it only through the documented causal gates.
- Expose recommendation behavior only through the chat contract and one immutable current recommendation snapshot.

## Repository map and sources of truth

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
- `docs/plans/2026-07-11-serenity-alpha.md`: active ExecPlan.
- `docs/plans/2026-07-13-single-protocol-agent.md`: active single-protocol cutover ExecPlan.

## Verified entry points and commands

- Backend: `PYTHONPATH=src python -m gp_assistant serve --host 127.0.0.1 --port 8000`
- Runtime worker: `PYTHONPATH=src python -m gp_assistant runtime-loop`
- Compile: `python -m compileall -q src tests`
- Backend tests: `python -m pytest -q` (integration tests are excluded by `pytest.ini` unless explicitly selected)
- Frontend: from `frontend/`, run `npm ci`, then `npm run lint`, `npm run typecheck`, `npm test -- --run`, and `npm run build`
- Docker services: `docker compose up -d gp gp-worker web`
- Historical replay: use the isolated-store command in `docs/historical_validation.md`.

The backend has no verified Ruff or static-type-check command. Do not claim those checks ran unless the repository later adds and executes them.

## Architecture and dependency boundaries

- Adaptive Decision Engine owns selection. The LLM may route and narrate but may not invent or change candidates, scores, prices, probabilities, or actions.
- Network data collection must not run inside `/api/chat`, book locks, or decision rendering.
- Historical and adaptive learning paths must respect as-of availability and T+5 maturity; never place future outcomes in readable pending state.
- `store/`, `cache/`, and `results/` are runtime artifacts. The user explicitly authorized deletion of legacy recommendation and conversation runtime data only after the new protocol passes integrity gates; never stage runtime data.
- `selection_engine/` is legacy/reference and low-level support, not the production ranking authority.
- New evidence stores must be append-only for versions and first-seen semantics; do not reuse overwrite-oriented `history.db` for Serenity.

## Approval gates

User approval is required before deployment, publication, secret changes, paid data acquisition, destructive migration, commercial use of public data, or public API breaks. The user has authorized local free-data Serenity collection and gated automatic promotion up to an 8% add-on weight; promotion may occur only through the recorded state machine.

## Definition of done

A change is complete only when the real user flow works, causal/data-integrity invariants hold, targeted and regression tests have actually run, operational failure is observable and recoverable, documentation reflects reality, and unrelated runtime files such as `store/book/current_slot.json` remain untouched.
