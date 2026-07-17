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

## 2026-07-17 CNINFO official-envelope repair and local container refresh

- **Cause proven:** A live HTTP 200 CNINFO no-result response used the official top-level fields `classifiedAnnouncements`, `totalSecurities`, `totalAnnouncement`, `totalRecordNum`, `announcements`, `categoryList`, `hasMore`, and `totalpages`, with `announcements:null`, zero counts, `hasMore:false`, and `totalpages:0`. The old parser incorrectly required an array and raised `cninfo_announcement_schema_changed`.
- **Change:** Adopted strict `cninfo-announcement-envelope-v2`: official `announcementId` only, official nullable empty page only, exact envelope checks, and `hasMore`-only continuation. No legacy `id` or empty-array compatibility was retained.
- **Executed validation:** `python -m pytest tests/test_serenity_sources.py tests/test_serenity_runtime.py -q` passed (47 tests); `python -m pytest -q`, `python -m compileall -q src tests`, and `git diff --check` passed.
- **Live source validation:** The repaired local collector queried current CNINFO data for `002594` and completed with zero records, `backlog=false`, `total_pages=0`, `next_page=null`, and source fingerprint `6ee17c3ed8440c47`.
- **Container validation:** `docker compose --profile experiments config --quiet` passed; `docker compose build gp web` rebuilt `gp-backend:local` and `gp-web`; force recreation refreshed `gp`, `gp-worker`, `gp-serenity-worker`, and `web` without `--remove-orphans`. The in-container and local SHA-256 for `src/gp_assistant/serenity/sources.py` both equal `34ed0c58fa2ecd87d87865a0f68c4e362f0f87127746c3406ddcadf101ad38cf`.
- **Live worker recovery:** After the old worker lease naturally expired, the renewed worker was the sole lease owner. The obsolete pre-repair CNINFO breaker was cleared and its first real poll succeeded: run `serpoll_6a9a0f9de6c34be98e3b66519c3b6870`, 3 requests, 0 records, complete coverage for `002594` and `600000`, no errors, no backlog, and schema fingerprint `576ec46738c76f6b`. Base GP API and market worker are up; Serenity policy remains suspended at 0% because the forward causal gate has not changed.

## 2026-07-17 DeepSeek Beta tool-routing recovery

- Updated the local Compose environment and `.env.example` to use `https://api.deepseek.com/beta`; no `/v1` fallback remains.
- Corrected strict tool schemas so every declared object property is required and unknown routing values use JSON `null`.
- The provider's direct response identified the rejected field as thinking mode combined with `tool_choice=required`. The client now sends `thinking={"type":"disabled"}` for agent tool routing.
- Passed `python -m pytest tests/unit/test_llm_client.py tests/unit/test_card_tool_llm_explanation.py tests/test_worker_reconcile.py tests/server/test_chat_endpoint_smoke.py -q` (31 tests), `python -m compileall -q src tests`, `docker compose config --quiet`, and `git diff --check`.
- Rebuilt and recreated `gp`, `gp-worker`, and `gp-serenity-worker` with the shared `gp-backend:local` image.
- Direct live DeepSeek Beta validation with the complete GP agent schema returned HTTP 200 and selected `answer_chat`; this proves the original provider 400 is resolved.
- Full local `/api/chat` acceptance remains pending only because the worker is still refreshing and `current book unavailable` prevents routing before the provider call.

## 2026-07-15 local container refresh and compatibility check

- Recreated the local API, runtime worker, Serenity worker, and Workspace containers without deleting the mounted `store/`, `data/`, or `configs/` directories.
- A source-overlay image (`gp-backend-current:local`) compiled successfully and served `/api/health`; its current tool-calling `/api/chat` path was rejected by the configured `deepseek-v4-flash` provider with HTTP 400, so it was not retained as the live API image.
- Restored the previously validated `gp-backend:local` image with `GP_SERENITY_MODE=native`, then verified `/api/health` reported `product_ready=true` and an isolated real `/api/chat` turn completed with HTTP 200.
- The full dependency-image rebuild remains in progress through the slow external Python package source; it was not used for the live cutover.

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
## 2026-07-17 Lunch-break runtime indicator

- Frontend component test verifies that a current, complete 11:30 artifact renders `午盘数据已更新 · 11:30` independently from `publish_allowed` and tradeability.
