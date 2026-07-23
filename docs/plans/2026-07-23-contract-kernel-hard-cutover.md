# Contract Kernel Hard Cutover

## Purpose / Big Picture

Replace the distributed recommendation contract chain with the three immutable aggregates `RecommendationPlan`, `RuntimeObservation`, and `RecommendationPublication`. The finished product has one typed persistence, API, and conversation path and fails closed rather than reading a retired structure.

## Progress

- 2026-07-23: Authorized hard cutover accepted. Repository discovery confirmed that the active persistence, product endpoint, and frontend client were still bound to the retired contract chain.
- 2026-07-23: Implemented canonical models, store, services, API route, migration, retirement enforcement, frontend publication view, and replacement tests.
- 2026-07-23: Fixture migration and configured development-database replacement succeeded. The prior database was 2,474,311,680 bytes; no historical row had an exact canonical envelope. The new-only producer has subsequently created a canonical full-market plan, runtime result, publication, and LLM-backed conversation record.

## Surprises & Discoveries

- The prior schema is additive and its session/turn tables bind a retired product identity; it cannot be safely evolved in place without retaining retired semantics.
- The user-authorized cutover permits loss of rows that cannot map exactly; normal runtime must reject an unsupported schema rather than bootstrap it.

## Decision Log

- Use a new SQLite schema with an explicit `schema_metadata` record and an atomic replacement migration.
- Preserve the decision engines as evidence producers only; the new plan remains the sole selection authority and runtime observations cannot alter it.

## Context and Orientation

- Canonical contracts: `src/gp_assistant/contracts/`.
- Application ownership: `src/gp_assistant/application/`.
- Persistence and one-time migration: `src/gp_assistant/store.py` and `src/gp_assistant/migrate_contracts.py`.
- Product API: `src/gp_assistant/gateway/routes.py`.

## Plan of Work

1. Define canonical typed models, target resolution, identifiers, manifest, and registry.
2. Implement the new store and application services, then migrate API/chat/frontend bindings.
3. Add destructive fixture migration and contract lifecycle tests.
4. Delete retired production modules, API surface, stale tests, and obsolete documentation.
5. Run backend/frontend/enforcement validation and execute the authorized development-store migration only after fixture validation.

## Concrete Steps

- Use temporary databases for tests and migration fixtures.
- Require stopped writers before the development database replacement.
- Advance `current_publication` only after dependent records commit.

## Validation and Acceptance

Executed: `python -m pytest -q` (5 passed), `python -m compileall -q src tests`, `python -m gp_assistant.contracts.manifest --check`, `python -m gp_assistant.contracts.check_retired`, and `git diff --check`. A real local `/api/chat` response and idempotent retry were also verified.

Executed from `frontend/`: `npm ci`, `npm run lint`, `npm run typecheck`, `npm test -- --run` (1 passed), and `npm run build`.

## Idempotence and Recovery

- Plan, runtime, and publication identities are content-addressed.
- The migration creates a temporary sibling backup and atomically replaces the active database only after validation. It deletes its backup only after a successful smoke test.
- An old schema is rejected by normal runtime; only the migration command reads it.

## Interfaces and Dependencies

- The LLM narrates only publication-bound evidence and cannot select or rerank symbols.
- Serenity remains an additive, causally gated evidence binding.
- Deployment, publishing, secrets, and paid data are outside this task.

## Outcomes & Retrospective

The hard cutover is locally applied and validated. A rebuild/restart of local containers from this source remains separately authorized operational work.

## Artifacts and Notes

- `docs/contracts/CURRENT_CONTRACTS.md`
- `docs/contracts/RETIRED_CONTRACTS.md`
- `docs/contracts/registry.yaml`
