# Validation Ledger

## Executed — Serenity Alpha implementation checks

- **Scenario:** Real official-announcement collection, shadow scoring, counterfactual ranking, causal promotion, bounded active weight, and automatic suspension.
- **User intent:** See real Serenity evidence immediately and allow it to enter ranking only after proving forward value.
- **Preconditions:** Free source reachable; isolated Serenity store; current book available; no mutation of production Market Memory during tests.
- **Environment:** Local Python 3.11 and Docker Compose where the local Docker engine is available.
- **Representative data:** Current Top10, reserve, holdings, real CNINFO records/PDFs, and deterministic source fixtures derived from real response shapes.
- **Exact steps:** Maintained in `docs/plans/2026-07-11-serenity-alpha.md`.
- **Expected result:** Real source IDs/hashes/first-seen values; base Adaptive invariance in shadow; no T+5 leakage; automatic state transitions and rollback; bounded narration payload.
- **Actual result:**
  - `python -m compileall -q src tests` passed during implementation checkpoints.
  - Serenity source/store/policy/runtime/scheduler/narration plus Adaptive/replay/context/health targeted suites passed; the final targeted checkpoint contained 119 tests.
  - The full default suite passed all 311 tests serially with an isolated pytest base/store directory.
  - `python -m compileall -q src tests`, changed-Python-file Ruff, and `git diff --check` passed. Repository-wide Ruff remains red on 185 pre-existing legacy findings outside this change.
  - `docker compose --profile experiments config --quiet` and `docker compose --profile serenity-bootstrap config --quiet` passed. Profile inspection confirmed the experiment profile starts `gp-serenity-worker` but not bootstrap, while `serenity-bootstrap` starts the one-shot bootstrap but not the worker.
  - Docker image build and live container/API smoke could not run because the local Docker Desktop Linux engine pipe was absent. No running container was restarted or replaced.
  - Real command: `python -m gp_assistant.cli serenity-bootstrap --lookback-days 30 --symbols 000001`.
  - Real result: `source_kind=bootstrap`, 4 requests, 2 CNINFO records/PDFs, complete metadata/hydration coverage, no backlog, schema fingerprint `4cb7014a163e4a3a`, elapsed 3.64 seconds, next delay 1800 seconds, marker `serboot_9006363b1b6de1090d027602`.
  - Real status: `state=shadow`, `available=true`, `applied_weight=0`, `bootstrap_ready=true`, 2 backfill documents, 0 verified scoring facts. The system returned no relevant signal rather than manufacturing an effect.
  - A second isolated real bootstrap for `000977` returned two CNINFO documents with SSE/SZSE verification. One current earnings-guidance filing produced a verified positive fact (`direction=+1`, `confidence=0.92`, `source_quality=1`), visible immediately in narration/reference scoring. Because it was historical bootstrap data, `backfill_only=true`, `learning_eligible=false`, and the formal applied weight remained exactly 0%.
  - Hardening regressions cover append-only metadata revisions, target-independent schema fingerprints, strict response container types, persistent 429 backoff with and without `Retry-After`, source-level failure streaks after partial success, terminal scanned/truncated PDFs, transient same-hash parse retry, per-symbol cursor migration, exact/report-period correction linking, unscoped live correction zeroing, explicit trading-day sample identity, SQL pre-limit sample deduplication, and legacy transcript redaction.
- **Failure and recovery:** Source failure degrades Serenity only; policy violations atomically set weight to zero; worker restart resumes from committed cursor and lease state.
- **Evidence:** Local command outputs dated 2026-07-11; ignored runtime DB under `store/serenity/`; verified `000977` PDF `1225414299`; unit coverage for bootstrap-only readiness, fixture rejection, page/hydration resume, breaker persistence, per-symbol coverage, version revalidation, correction handling, T+6 timing, checksum tamper, atomic ledgers, reference-only backfill, and replay isolation.
- **Remaining risk:** Free endpoints have no SLA; forward performance cannot be established during implementation itself.
- **Date:** 2026-07-11.

## Remaining operational gates

- Docker image build and live API/container smoke when the local Docker daemon is available.
- Five consecutive forward shadow trading days cannot be completed in this implementation session and remain a rollout gate, not a simulated acceptance result.

Historical replay methodology and prior results remain in `docs/historical_validation.md`.
## 2026-07-11 container recommendation recovery

- Full isolated suite: 311 tests passed (`python -m pytest -q`).
- Rebuilt `gp` and `gp-worker`; all services start successfully.
- Diagnosed Docker Desktop bind-mounted SQLite WAL failure (`disk I/O error`).
- Created a non-destructive clean database copy containing 3,077 queries and 12,242,184 items; the original `history.db` remains untouched.
- Container cache probes for `000001`, `600000`, and `600519` now read through 2026-07-10 successfully.
- Rebuilt daybook `daily_eb6f6ac1d239`; current book contains a candidate. Publication remains disabled as expected during `NON_TRADING`.
## 2026-07-11 canonical recommendation recovery

- Backend compile and complete default pytest passed.
- Frontend lint, typecheck, 17 tests, and production build passed.
- Compose config resolves all six Python services to one `gp-backend:local` image and only `gp` owns the build definition.
- API, worker, and Serenity containers used the same image digest.
- Guarded ops rebuild emitted matching producer identity and produced 10 current Adaptive picks for 2026-07-10.
- `/api/book/current` and parameterless `/api/recommend_v2` returned the same 10 symbols; non-trading retained plans with execution disabled.
- Browser verification loaded the workspace without overlay/blank state and displayed Top symbols with “最近交易日计划 / 下个交易日复核”.
- Real two-turn chat passed after the final image rebuild: “今天给我3只” returned 600000/000651/000001 and “第一只为什么能进” reused the same run with grounded explanation.
- Final browser verification confirmed the first symbol, non-trading plan label and header; no framework error overlay was present.
- Serenity worker is running from the shared image at 0% weight. Its persisted policy remains safely suspended because earlier source failures triggered the documented circuit breaker; no promotion override was applied.
- Independent final review found and resolved three P1 issues: canonical fallback masking, incomplete non-execution phase gating, and explicit-zero corruption in the V2 adapter. The complete backend suite passed again afterward.
- Final-image two-turn chat passed with run `run_ddccc64eb9a5`; both turns retained symbols 600000/000651/000001 and reused the same run.
# 2026-07-13 — single-protocol cutover

- Passed backend contract tests: immutable snapshot, current pointer, atomic/idempotent turns, concurrent sequence allocation, session snapshot binding, no-snapshot `no_trade`, and exactly three public paths.
- The default pytest command now runs the nine retained single-protocol tests; retired-surface tests are ignored before import rather than acting as an implicit compatibility suite.
- Passed frontend typecheck, ESLint, one contract test, and production build.
- Stopped legacy Compose API/worker/web containers before data cutover.
- Promoted integrity-gated `store/search/history-clean.db` to the sole `store/search/history.db`; both copies had equal byte size before promotion. SQLite integrity/count/latest-item checks were executed read-only before replacement.
- Deleted `gateway.db`, book/run/recommend/portfolio/validation/cache runtime artifacts and legacy frontend/HTTP surfaces. No deployment was performed; stopped containers still contain the old image and must not be restarted without rebuilding.

# 2026-07-13 — Docker and core-engine database audit

- `docker compose config --quiet` passed. The resolved service set is exactly `api`, `worker`, and `web`; no ops, paper-execution, Workbench, or Serenity Compose service remains.
- Retained tests passed: 11 tests covering agent transactions, HTTP contract, pre-as-of completed-event retrieval, and daybook risk/entry/stop/take-profit projection.
- Frontend typecheck, ESLint, Vitest and production build passed.
- Actual database audit: `store/events/market_memory.db` contains 18,730 market events, 17 decision snapshots and 0 matured prediction outcomes; `store/search/history.db` contains 3,077 query definitions and 12,242,184 cached items, latest item time `2026-07-10`.
- The newest decision snapshot (`2026-07-13`) is `no_trade`; all candidates carry `daily_bar_not_at_as_of` and `daily_cache_not_current`, so no recommendation was published. This is correct fail-closed behavior.
- Fixed one output defect: `book.daybook._map_pick` now carries `risk.risk_flags` into the user-visible pick as well as top-level flags.
