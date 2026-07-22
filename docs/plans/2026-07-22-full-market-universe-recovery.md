# Full-Market Candidate Universe Recovery ExecPlan

## Purpose / Big Picture

Restore the production recommendation input from a silent ten-symbol file fallback to a dated, immutable and publish-blocking full main-board universe. A valid recommendation must prove its security-master scope, completed-daily coverage, eligibility filters, scored pool and selected count. Serenity remains a bounded additive Alpha and contributes zero, without blocking the base recommendation, whenever its complete finalist batch is unavailable.

## Progress

- [x] 2026-07-22: Proved the live worker scores only the ten symbols in `store/universe/universe_symbols.txt` while reporting `symbols_expected=10`, `symbols_received=10`, `complete=true`.
- [x] 2026-07-22: Confirmed the cached market snapshot contains 5,528 unique A-share codes and 3,194 main-board codes; the official exchange-list adapters are reachable and expose code, name and listing date.
- [x] 2026-07-22: User selected full recovery, full-market filtering followed by a Top-200 scoring pool, additive Serenity failure semantics, the strict dual coverage gate, and local Docker rebuild/acceptance.
- [x] 2026-07-22: Implemented the immutable `MarketUniverseSnapshot.v1` builder/store, exchange-master normalization, deterministic filters and resumable batched daily-history refresh.
- [x] 2026-07-22: Routed production selection through the accepted universe, disabled file fallback and made incomplete universes publish explicit current no-trade snapshots.
- [x] 2026-07-22: Split the full base Adaptive pass from the Top-30 Serenity pass; incomplete Serenity batches now apply zero weight without vetoing the base result.
- [x] 2026-07-22: Exposed independent universe summaries through the canonical snapshot, health response and Workspace funnel.
- [x] 2026-07-22: Backend pytest/compileall, frontend lint/typecheck/27 Vitest tests/build, Compose config and diff checks passed.
- [x] 2026-07-22: Completed local container rebuild, full-market backfill, source-hash comparison, rendered Workspace inspection, and real Top-3 plus same-session follow-up chat acceptance.

## Surprises & Discoveries

- `build_day_selection()` passes `allow_snapshot=False`; the decision pipeline then falls back to the static universe file.
- Daily freshness is reconciled after selection, so it proves only the selected subset rather than the market input scope.
- The local full-market cache shows the planned absolute threshold is feasible: 3,194 main-board codes versus the 3,000 minimum.
- Existing SSE/SZSE AkShare adapters already expose listing metadata, so no paid or new runtime dependency is required.
- An incomplete full-market result must itself advance the current pointer to a no-trade snapshot; merely refusing to publish would leave the legacy ten-symbol recommendation current.
- A completed same-day universe can be safely reused only after its content digest and accepted pointer are revalidated; this prevents the resident worker from polling exchange master endpoints every cycle.
- The first complete universe passed, but current publication exposed a stale integrity assumption: a recommendation with Serenity degraded atomically to 0% was still required to bind a Serenity reference/pending sidecar. The validator now requires those sidecars only when the native batch is ready, with a direct publication regression test.

## Decision Log

- Use exchange security lists as master data and completed daily market data as the eligibility/ranking source; spot data must not be the sole security master.
- Accept a universe only when main-board count is at least 3,000 and at least 95% of the preceding accepted day, target-day data/metadata coverage is at least 95%, eligible count is at least 50, and scoring covers at least 95% of the bounded pool with a minimum of 20.
- Filter ST/delisting names, listings younger than 60 days, closes outside 2-500 yuan, five-day average amount below 500 million yuan, and histories shorter than 120 bars; rank by five-day average amount then symbol and score at most 200.
- Apply Serenity only to the base Top-30 finalist pool. Any incomplete Serenity batch receives effective weight zero for the whole batch, preserving the exact base ordering.
- Preserve old snapshots without mutation, but snapshots without a verified universe contract cannot become current or tradeable.

## Outcomes & Retrospective

Recovery is complete. Accepted universe `mus_20260722_12adb91c92ebb41babf6` records 3,191 main-board inputs, 3,190 target-day-ready histories (99.97%), 606 eligible symbols, a 200-symbol pool, 200 successful scores, 10 selected symbols and `fallback_used=false`. Snapshot `daily_29989bdcae26` is current; health reports `status=ok` and `product_ready=true`. Serenity reports target/coverage 30/0, effective weight 0 and `serenity_batch_incomplete`, while preserving the base recommendation.

The final `gp`, `gp-worker` and `gp-serenity-worker` containers share image `sha256:1f0ada8c202bcc88b8e987fd3e67fa909da08be01d850df9449b5e3fdf3a1b12`; all checked local/container source hashes match. The rendered Workspace showed `3191 / 3190 / 606 / 200/200 / 10` with no browser console errors. Real session `session_a2400f910864` returned Top-3 `600988 / 002648 / 603259`, then answered a same-session first-versus-second comparison from snapshot `daily_29989bdcae26` using the real LLM.

## Context and Orientation

`gp-worker` builds a `DayBook` through `book.daybook -> evidence.market_service -> decision_engine.pipeline`, then `AgentStore` publishes an immutable recommendation snapshot. `selection_engine/` contains legacy filtering ideas but is not the production ranking authority. The recovery adds a base-market universe owner ahead of the production decision pipeline and projects only a bounded summary into the product snapshot.

## Plan of Work

1. Add typed universe contracts, immutable dated storage, exchange-list normalization and a resumable worker-owned builder.
2. Apply the complete eligibility policy and provide the accepted Top-200 symbols to the decision pipeline without a production file fallback.
3. Validate scoring coverage before publication and publish an explicit empty `no_trade` result on coverage failure.
4. Refactor Serenity readiness into an additive batch certificate and update snapshot integrity/health semantics.
5. Project universe quality into API/Workspace, mark legacy snapshots unverified, and update governance docs.
6. Run backend/frontend regressions, rebuild authorized local services, and validate real full-market chat.

## Concrete Steps

- Add a versioned universe model and store under ignored `store/universe/snapshots/`, with content-addressed immutable files and an atomic per-day pointer.
- Extend the existing provider boundary for official SSE/SZSE master lists and completed-day market data; retain checkpoints and bounded retries in the worker only.
- Replace `allow_snapshot=False -> universe:file` production behavior with an explicit accepted-universe input. Explicit symbols remain available for tests and historical replay.
- Embed universe ID/quality summary in `DayBook`/`MarketBook`; require it for current readiness and surface blocking reasons in health and Workspace.
- Update tests that currently assert snapshot disabling or Serenity coverage hard-blocking to assert the new product contract.

## Validation and Acceptance

- Planned backend: focused universe/pipeline/worker/native/Serenity/health/chat tests, then `python -m pytest -q` and `python -m compileall -q src tests`.
- Planned frontend: `npm run lint`, `npm run typecheck`, `npm test -- --run`, and `npm run build`.
- Planned runtime: `docker compose config --quiet`; build `gp` and `web`; recreate `gp`, `gp-worker`, `gp-serenity-worker`, and `web` without deleting mounts or using `--remove-orphans`.
- Acceptance evidence must show main-board master >= 3,000, target data coverage >= 95%, pool 200, scored >= 190, no static fallback, matching universe IDs across snapshot/health/Workspace, matching container source hashes, and a real Top-3 plus follow-up chat.

## Idempotence and Recovery

Universe versions are content-addressed and immutable; reruns reuse the accepted target-day artifact or resume incomplete collection. Current pointers advance only after validation. A failed build publishes/retains explicit blocked state and never falls back to the ten-symbol path. Backend rollback must not restore an image capable of treating the ten-symbol file as production-ready.

## Artifacts and Notes

- Active plan: `docs/plans/2026-07-22-full-market-universe-recovery.md`.
- Architecture decision: `docs/adr/0008-full-market-universe-and-additive-serenity.md`.
- Existing audit: `docs/architecture-audit-2026-07-22-candidate-universe-and-serenity-boundaries.md`.
- Runtime universe artifacts remain ignored and must not be staged.

## Interfaces and Dependencies

`POST /api/chat` remains compatible. `MarketBook` and `/api/health` gain additive universe-quality fields. Workspace gains corresponding TypeScript fields and status presentation. The implementation uses existing Python, pandas, AkShare and Pydantic dependencies; no paid source or new package is introduced.
