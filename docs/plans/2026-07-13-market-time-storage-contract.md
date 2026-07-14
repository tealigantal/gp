# Market-time and Storage Contract ExecPlan

## Purpose / Big Picture

Repair the single-protocol recommendation path so a planned trading day is never confused with the most recently completed daily-bar day, and so normal reads do not take a SQLite write lock. The user-visible result is a current, explainable plan when completed data exists, or an explicit pending/no-trade state when it does not.

## Progress

- [x] 2026-07-13: Confirmed the failure path: the worker passed the planned day into selection and daily freshness; before the 2026-07-13 open this required unavailable 2026-07-13 daily bars.
- [x] 2026-07-13: Confirmed AgentStore read getters execute `BEGIN IMMEDIATE`; worker daybook and artifact reuse branches are unreachable because their local values are always `None`.
- [x] Introduce one `MarketTimeContext` and propagate it through worker publication, freshness, and snapshot storage.
- [x] Upgrade agent storage to schema v2 with separate read/write connections and immutable session binding.
- [x] Make Market Memory reads lock-free and batch append-only event writes with maturity metadata.
- [x] Run date-matrix, concurrency, backend, frontend, and Compose configuration validation.
- [x] Run an isolated local source-chat fail-closed check with a real configured LLM as an independent response-quality reviewer (2026-07-13; no user runtime data used).
- [ ] Run an isolated local provider/worker-to-snapshot-to-chat smoke without changing user runtime data (attempted in Docker 2026-07-13; current backend image could not rebuild because its configured Docker build proxy refused connections, so no current-code worker publication acceptance exists).
- [x] Run a user-authorized production-data worker-to-snapshot-to-chat and real-LLM response-quality validation (2026-07-13).
- [x] Physically remove the legacy gateway SQLite store, its source implementation, and its dedicated legacy-path tests (2026-07-13).

## Surprises & Discoveries

- `resolve_daily_target()` already computed an earlier completed daily target, but it was used only for a freshness report; `build_daybook()` still received the planned day.
- The repository contains user-owned deletions of legacy runtime/test artifacts. They are outside this change and must remain untouched.

## Decision Log

- Keep `RecommendationSnapshot.v1` public schema identity and retain `as_of` as a read-only compatibility alias. Add explicit market-time fields in agent schema v2 instead of inferring freshness from that alias.
- Keep Docker bind-mounted SQLite in DELETE journal mode. Concurrency is addressed with short write transactions and truly read-only connections, not WAL.
- A session remains bound to its first committed snapshot. A later snapshot may not overwrite that binding.

## Context and Orientation

`src/gp_assistant/worker.py` publishes the only product snapshot through `AgentStore`. `src/gp_assistant/evidence/daily_freshness.py` determines completed daily data, while `runtime/market_clock.py` determines the planned trading day and intraday slot. `agent_store.py` is the product persistence boundary; `market_memory/store.py` is internal selection evidence.

## Plan of Work

1. Model explicit planned/effective/pulse dates and use the effective day for daily selection/data validation.
2. Persist/reuse producer-compatible immutable daybooks and publish only when a new artifact is required.
3. Bootstrap migrations only at process/write boundaries; use read-only SQLite connections for getters and health.
4. Make event evidence append-only, maturity-gated, and batched.
5. Add focused regressions before running the full project gates.

## Concrete Steps

1. Add `MarketTimeContext` around the existing calendar/EOD resolver with legacy mapping aliases during cutover.
2. Update `AgentStore` migrations, worker bootstrap, health, and chat stale-snapshot behavior.
3. Update Market Memory lock/connection ownership and event schema.
4. Add tests for Monday pre-open, EOD pending/ready, idempotent worker runs, concurrent readers/writers, and session races.

## Validation and Acceptance

Planned: complete date matrix, 100-reader/writer contention, default pytest, frontend gates, Compose config, and local container smoke. Executed results will be appended to `docs/VALIDATION.md`; no planned command is evidence until it actually runs.

## Idempotence and Recovery

Migrations validate recorded checksums and are additive. Duplicate publication retains immutable payloads. A pending EOD probe does not advance the current pointer. A write timeout returns a structured recoverable busy response; it does not drop or rebind a session.

## Artifacts and Notes

Do not stage `store/`, `cache/`, `results/`, `.pytest-tmp/`, or `.codex-remote-attachments/`. No deployment, remote push, or legacy-data restoration is in scope.

## Interfaces and Dependencies

Public routes remain `POST /api/chat`, `GET /api/chat/{session_id}`, and `GET /api/health`. `RecommendationSnapshot.v1` remains the public snapshot name; schema v2 is an internal `agent.db` migration.

## Outcomes & Retrospective

The date mismatch and read-lock causes are fixed and covered by default tests. Frontend and Compose configuration validation passed. On 2026-07-13 the requested Docker live smoke was attempted: Docker could build the web image, but backend dependency installation failed through `host.docker.internal:7890` (connection refused). The no-proxy retry did not produce a replacement backend image. A temporarily started pre-existing 2026-07-11 backend image was used only to verify the real LLM's wording, then stopped; it is not evidence for this change. The LLM correctly self-corrected to “0 current executable symbols”, but its first answer had misleadingly framed three next-session watch plans as current candidates. Two local current-worktree isolated checks passed fail-closed behavior. Finally, with explicit user authorization, the current source ran once directly against production data: history integrity was sound, the agent DB migrated additively, all ten daily series reconciled to 2026-07-13, and a production snapshot was published. Its board remained observation-only (`WATCH`, `NEXT_SESSION_PLAN`, `can_open=false`) and `tradeable=false`; chat therefore returned structured no-trade with no picks. The configured real LLM agreed that this was the correct user-visible outcome. The immediate second worker loop was a no-op and retained the same one snapshot/current pointer. The remaining release gate is only a rebuild of the current backend Docker image once its build proxy/index route is reachable.
