# Validation Ledger

## 2026-07-18 plain assistant-transcript output

- **Decision:** The Workspace transcript is a conversation surface, not a
  second structured decision dashboard. The right-side snapshot remains the
  single structured operational view.
- **Change:** Replaced every assistant message-kind renderer in `ChatThread`
  with one presentation projection: validated `narrative_text` (or the
  committed legacy content when metadata is absent) plus optional
  LLM-provided follow-up prompts. Removed the retired recommendation,
  comparison, live-entry, exit, run-change, no-trade, detail, and narrative
  card components. This does not change the API contract, selection, numeric
  validation, persisted data, or Serenity's native shadow/0% policy.
- **Executed validation:** Targeted ChatThread Vitest tests passed (8 tests);
  the complete frontend suite passed (25 tests); `npm run lint`, `npm run
  typecheck`, `npm run build`, `docker compose config --quiet`, and `git diff
  --check` passed.
- **Container acceptance:** Rebuilt and force-recreated `web` without
  removing runtime data. Compose also recreated its unchanged `gp` dependency;
  `gp-worker` and `gp-serenity-worker` remained running. `GET /` returned 200,
  `/api/health` returned `status=ok`, `product_ready=true`, and
  `llm_ready=true`; Serenity remained `native/shadow/0%`. The deployed Nginx
  assets no longer contain the retired `下一交易窗口策略计划` card copy.

## 2026-07-18 runtime contract consolidation

- **Cause addressed:** The default suite retained eight worker tests that
  monkeypatched deleted file-store and portfolio functions. Market-time
  consumers also relied on implicit mapping aliases such as target_day, so
  removal of the aliases could break freshness paths rather than expose a
  single explicit boundary.
- **Change:** Added contracts/runtime.py as the sole operation contract,
  removed retired worker loop/replay aliases, made intent literals strict,
  removed market-time mapping aliases, and added
  daily_freshness_target_fields() as the only projection into the persisted
  daily-freshness schema. Replaced the stale worker suite with current
  AgentStore plus MarketTimeContext coverage; it verifies rejected retired
  operations/intent labels, pending and blocked branches, no-op binding, and
  resident dispatch.
- **Executed validation:** python -m compileall -q src tests passed;
  python -m pytest tests/test_daily_freshness.py tests/test_worker_reconcile.py tests/agent/test_market_time_storage_contract.py -q passed (35 tests);
  default python -m pytest -q passed (263 tests); and git diff --check passed.
  Test cleanup removed tracked fixtures under .pytest-tmp/; they were restored
  byte-for-byte from HEAD before the final default run.
- **Frontend and container acceptance:** frontend lint, typecheck, all 25
  Vitest cases, and production build passed; docker compose config --quiet
  passed. Rebuilt and force-recreated gp, gp-worker, gp-serenity-worker, and
  web without removing mounted runtime data. The local and container SHA-256
  values matched for contracts/runtime.py, contracts/intents.py,
  runtime/market_time.py, evidence/daily_freshness.py, and worker.py. A real
  POST /api/chat committed a 214-character response with narrative_text equal
  to reply; health then returned product_ready=true, llm_ready=true, and
  llm_retryable=true. Serenity remained native/shadow at 0%.
- **Final end-to-end acceptance:** After the final source-compatible Compose
  rebuild, the real DeepSeek session `e2e-final-20260718-2215` committed a
  current three-candidate answer and a same-session follow-up about the first
  candidate's wait and cancellation conditions. The first answer kept all
  candidates in the next-session, non-executable state and used local value
  capsules for plan numbers; the follow-up correctly kept `002415` in wait,
  described the after-open confirmation conditions, stated Serenity shadow has
  no relevant evidence and zero contribution, and used the locally projected
  `31.29` stop. Both persisted assistant contents exactly equalled
  `message.narrative_text`; traces contained only real `intent_routing`,
  `tool_evidence`, and, where needed, one `tool_evidence_repair` call. Final
  health was `status=ok`, `product_ready=true`, `llm_ready=true`, and
  `llm_retryable=true`; Serenity was `native/shadow/0%` with a live worker and
  the Web returned HTTP 200. Host/container SHA-256 values matched for the
  chat, runtime-contract, intent, market-time, freshness, and worker files.
- **Regression after final repairs:** The default backend suite, compileall,
  and `git diff --check` passed. Frontend lint, typecheck, all 25 Vitest cases,
  and production build passed. The test runner's tracked `.pytest-tmp`
  fixtures were restored from HEAD before staging.

## 2026-07-18 assistant-turn presentation contract recovery

- **Root cause:** The DeepSeek call for the reported `你好` turn succeeded (HTTP 200) and committed a non-empty reply. The single-protocol writer stored that text in `turn.content`/`payload.reply`, but `message.narrative_text` was absent. Commit `268b43c` restored Workspace session reads by exposing that raw payload, while the older `ChatThread` rendered only `meta.message.narrative_text`; the result was a blank body for a valid real LLM answer. The later retryability repair did not modify provider configuration, tool calls, request payloads, or reply generation.
- **Change:** `src/gp_assistant/contracts/api.py::ChatResponse` is now the single assistant-turn presentation contract. It binds `message.narrative_text` exactly to the validated committed `reply`; `AgentStore` uses it before write, during idempotent replay, and for every persisted-turn read. Frontend rendering uses committed content only for legacy/malformed-metadata visibility and shows a warning for a truly corrupt empty row. No database migration, runtime-state deletion, LLM fallback/template, selection change, or Serenity policy change was introduced.
- **Executed validation:** targeted backend chat/health tests plus the assistant-contract suite passed (61 passed, 6 deselected); full frontend suite passed (25 tests), `npm run typecheck`, and `npm run build` passed; `git diff --check` passed. The former eight `tests/test_worker_reconcile.py` failures were subsequently repaired by the runtime-contract consolidation recorded above; the default backend suite is now green.
- **Live acceptance:** Rebuilt and force-recreated `gp`, `gp-worker`, `gp-serenity-worker`, and `web` without deleting mounted runtime data. The reported legacy session `session_ohi12fto` now projects its 426-byte committed reply into `message.narrative_text` exactly. A new real DeepSeek chat then committed a 340-byte answer; the POST response, same-key idempotent replay, `GET /api/chat/{session_id}`, and `GET /api/session/{session_id}` all carried the identical narrative. Final health was `status=ok`, `product_ready=true`, `llm_ready=true`, `llm_retryable=true`; Serenity stayed native/shadow at 0%.

## 2026-07-18 LLM narration retryability and numeric-label repair

- **Cause:** The generic `第一目标` numeric-label matcher ran before the distinct `第一目标盈亏比` matcher, so the valid displayed risk/reward `0.73` was treated as a `take1` price. Its rejected repair wrote product-chat verification `error`, and the Workspace incorrectly used that committed-chat signal to disable every future request.
- **Change:** Match `第一目标盈亏比` as its own higher-priority field while retaining strict `take1` validation. Expose `llm_retryable` separately from `llm_ready`; only a committed, fully validated real chat sets readiness, while a configured provider permits the user's next real request after a rejected response. The frontend keeps the composer enabled only in that retryable state and refreshes health immediately after a successful submission. No database schema, persisted runtime state, fallback/template answer, automatic LLM probe, or Serenity policy changed.
- **Executed validation:** `python -m compileall -q src tests`; `python -m pytest tests/agent/test_agent_llm_chat.py tests/test_llm_runtime_status.py tests/test_health_storage_stats.py tests/server/test_single_chat_contract.py --basetemp <isolated-temp>` (61 passed, 2 deselected); frontend `npm test -- --run` (22 passed), `npm run typecheck`, and `npm run build`; `git diff --check` passed before container acceptance. The hook regression verifies that a committed chat invalidates `['health']` and moves the rendered health state from retryable to ready without waiting for the polling interval.
- **Live acceptance:** Rebuilt and force-recreated `gp`, `gp-worker`, `gp-serenity-worker`, and `web` without deleting any mounted runtime directory. Directly after the rebuild health correctly reported the persisted rejected turn as `llm_ready=false`, `llm_retryable=true`; after the worker published a source-compatible native snapshot, a real DeepSeek `POST /api/chat` committed. Its same-session natural-language follow-up also committed with real `intent_routing`, `tool_evidence`, and validator-directed `tool_evidence_repair` traces. Health then reported `status=ok`, `product_ready=true`, `llm_ready=true`, and `llm_retryable=true`; Serenity remained native/shadow at its causal baseline `0%`.

## 2026-07-18 Workspace gateway and worker observability recovery

- **Cause:** The single-protocol integration commit changed the Web Nginx upstream from Compose service `gp` to nonexistent `api`, deleted the Workspace read endpoints while the frontend still requested them, and left the frontend without the required chat `client_turn_id`. The market worker also emitted no successful-loop summary, making a healthy worker look blank in Docker Desktop.
- **Change:** Restored only read-only Workspace projections from the current `AgentStore` snapshot and persisted turns; no retired book/run authority or chat fallback was reinstated. Restored Nginx upstream `gp:8000`, added browser-side idempotency keys, and added a bounded worker completion log.
- **Executed validation:** `python -m compileall -q src tests`; `python -m pytest tests/server/test_single_chat_contract.py tests/agent/test_agent_store.py -q` (18 passed); frontend `npm run typecheck`, `npm test -- --run` (18 passed), and `npm run build`; `docker compose config --quiet`; then rebuilt and force-recreated `gp`, `gp-worker`, `gp-serenity-worker`, and `web` without deleting mounted runtime directories.
- **Live acceptance:** Browser Workspace loaded with LLM connected, current Top candidates, an enabled composer, and no console errors. A real submitted two-candidate/Serenity question completed `/api/chat` with HTTP 200 and returned rendered `002415` and `601318` plan cards. Health then reported `product_ready=true`, `llm_ready=true`, Serenity available in native shadow mode at 0%, and `gp-worker` logged one artifact publish followed by safe `noop=true` cycles.

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

## 2026-07-17 local-image refresh preflight

- **Live baseline:** All four local containers were up. `GET /api/health` returned HTTP 200 with `llm_ready=true`, `book_freshness=postclose_ready`, a current compatible artifact, and 10/10 daily symbols. A real `POST /api/chat` completed with HTTP 200, exercised the LLM tool route, and returned the post-close `WAIT` plan for `000333` and `002594`.
- **Preflight checks:** `docker compose --profile experiments config --quiet` and `python -m compileall -q src tests` passed. The prescribed historical targeted test command is stale because `tests/server/test_chat_endpoint_smoke.py` no longer exists. Its current three-file subset fails during collection because `src/gp_assistant/runtime/turn_loop.py` imports `gp_assistant.memory.service` while the local `src/gp_assistant/memory/` directory contains only `__pycache__`. Git history attributes the inconsistency to merge commit `af90e6a`: relative to first parent `fb41d91`, it deleted all seven `memory` files while retaining/restoring the loop from that parent.
- **Deployment decision:** Did not build or recreate containers. The active backend image includes the missing `memory` source package and imports `turn_loop` successfully; rebuilding from the incomplete workspace would replace the verified live chat path with a startup/import failure.
- **Follow-up risk:** The real chat session's subsequent `GET /api/chat/predeploy-audit-20260717-1512` returned HTTP 404. Recheck successful-turn history retrieval after the source reconciliation and rebuild.

## 2026-07-18 native Serenity and real-chat recovery

- **Historical cause repaired:** Merge `af90e6a` deleted all seven tracked `src/gp_assistant/memory/` sources while retaining the matching runtime import. The files were restored byte-for-byte from first parent `fb41d91`; no mounted runtime data was deleted.
- **Serenity repair:** A delayed `SerenityAddon.v1` evidence bundle appeared after the first native formula cutover and was incorrectly evaluated in the native epoch. `native_formula_cutover_v2` now retires legacy pending work and starts a new auditable epoch. It returns to shadow only when the suspension is entirely attributable to that legacy formula and no current native integrity failure exists. Runtime evidence persistence also rejects non-native formula versions.
- **Authorized legacy-evidence purge:** At the user's direction, the running evidence store atomically deleted all 15 `SerenityAddon.v1` pending records, both evaluations carrying that legacy add-on formula, and their 15 exclusive reference snapshots. The worker was stopped only for the transaction, then restarted; a compact policy-ledger record retains the deletion counts without retaining legacy payloads. Post-purge verification found zero legacy pending records, evaluations, and reference snapshots.
- **Live Serenity result:** The current policy is `mode=native`, `state=shadow`, `epoch=3`, `applied_weight=0.0`, no suspension reason, a completed current poll, and target coverage `10/10` with zero incomplete symbols. The zero weight is the controller's causal baseline; it is not a missing module or a fallback path.
- **Chat repair:** Product-chat status is atomically persisted for both Uvicorn API workers. Explicit candidate requests cannot be downgraded to `term_explain` or generic `chat` merely because they mention Serenity; Chinese `两只` is normalized as Top-2.
- **Default Compose startup:** `gp-serenity-worker` no longer has an `experiments` profile. `docker compose config --services` lists `gp`, `gp-serenity-worker`, `gp-worker`, and `web`; `docker compose up -d --build --force-recreate` started all four. The resident-service test passed, and a real subsequent chat completed provider routing, evidence narration, and repair with HTTP 200, restoring `/api/health` to `status=ok`, `product_ready=true`, and `llm.verification=ready`.
- **Executed checks:** `python -m compileall -q src tests`; `python -m pytest tests/agent/test_agent_llm_chat.py tests/test_llm_runtime_status.py tests/agent/test_agent_store.py tests/test_serenity_store.py tests/test_serenity_runtime.py -q`; frontend `npm run lint`, `npm run typecheck`, `npm test -- --run`, and `npm run build`; `docker compose --profile experiments config --quiet`; and `git diff --check` all passed.
- **Container acceptance:** Rebuilt and force-recreated `gp`, `gp-worker`, `gp-serenity-worker`, and `web` without `--remove-orphans`. A real stable-snapshot `POST /api/chat` committed a recommendation with `002415` and `601318`; intent routing, tool-evidence narration, and validator-directed narration repair each had real provider HTTP 200 plus a response ID. `/api/health` then reported `status=ok`, `product_ready=true`, `llm.verification=ready`, and the Serenity state above.
- **Observed fail-closed behavior:** A separate request overlapping a worker snapshot publication returned 503 `current_snapshot_changed_before_commit`; it did not persist a stale answer. The subsequent stable request committed successfully.
- **Known unrelated test debt:** `python -m pytest tests/test_worker_reconcile.py -q` has eight failures because those tests monkeypatch removed pre-single-protocol worker functions (`load_portfolio_snapshot` and module-level `load_daybook`). No production behavior was changed to preserve that obsolete seam.

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
