# Validation Ledger

## Executed — 2026-07-14 native-Alpha and real-LLM pre-rebuild gates

- **Scope:** Source-level acceptance before touching the existing Compose services or production stores.
- **Backend:** `python -m compileall -q src tests` passed. After adding resident target-pointer observation and the exact real CNINFO `announcements=null,totalpages=0,hasMore=false` regression, the complete default pytest collection passed: 166 tests across chat/session atomicity, native snapshot integrity, market time, Serenity source/store/policy/resident behavior, Adaptive ninth-expert scoring, DayBook projection, health readiness and the three-endpoint HTTP contract.
- **Frontend:** `npm run lint`, `npm run typecheck`, `npm test -- --run` (1 Vitest), and `npm run build` all passed. The PowerShell transcript warning during parallel Node commands was profile noise; every command exited 0.
- **Static runtime:** `docker compose config --quiet` and `git diff --check` passed. The worktree contains extensive pre-existing runtime deletions and `store/book/current_slot.json` changes; these were not restored, staged or treated as implementation output.
- **Critical proven invariants:** incomplete target/PDF coverage cannot publish baseline candidates; formula cutover retires legacy add-on pending rows once without misclassifying native evaluations; later bootstrap/version state cannot rewrite historical availability; target/day backlog cannot be reused; a ready DayBook cannot be hidden by a date-only noop; a resident process observes a target published during scheduler wait without source polling or lease takeover; same-day replaced sessions are historical for execution; a chat commit requires two ordered real provider traces; missing native per-pick Alpha or swapped price/action narration fails closed without a session write.
- **Not yet counted as acceptance:** Container liveness, unit mocks, or an old snapshot. Final acceptance still requires ordinary resident target/poll/snapshot publication in the existing production stores followed by a real two-stage `/api/chat` and persisted trace inspection.

## In progress — 2026-07-14 production-path acceptance

- `docker compose build api web` completed from the current source. The ordinary `api`, `worker`, `serenity`, and `web` services were recreated in place; no database, bind-mounted store or Docker volume was deleted, and Docker Desktop was not restarted.
- `/api/health` correctly reported `product_ready=false` against the old `slot_243fa975e91b` snapshot because its selection policy predates native Alpha, no current candidate target exists, and no real LLM chat has yet committed.
- The old Serenity lease was allowed to expire naturally. The first new process poll at 15:30:20 had `request_count=0` and `serenity_target_set_empty`, proving the earlier `cninfo_announcement_schema_changed` status belonged to the pre-rebuild poll rather than to a new CNINFO response.
- The first new worker EOD probe fetched all three anchors through the configured real Sina route. Each anchor still had 2026-07-13 as its latest complete daily bar, so the market-time contract remained `current_pending` with zero of three anchors ready. This is an expected fail-closed state, not production acceptance.
- A runtime observation exposed and then permanently fixed the resident one-hour no-target wait. The focused four-test resident suite, exact 16-test source suite, full 166-test default suite, compileall, and Compose render all passed; the updated backend image was recreated in place again after the source change, while the later exact-response addition was test-only.

## Executed — 2026-07-14 proxy-safe container rebuild

- **Scenario:** Rebuild the resident Compose stack after removing an obsolete host-specific build-proxy fallback.
- **User intent:** Repair the local proxy failure and reconstruct the containers so ordinary Compose startup remains usable.
- **Exact steps:** Default Python compile/test and Compose configuration checks; `docker compose build api`; `docker compose up -d --force-recreate --remove-orphans --no-build`; Compose status/log checks; API health request; read-only Serenity lease inspection.
- **Actual result:** 46 default Python tests, compilation, Compose configuration, and whitespace checks passed. Backend dependency installation ran with `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` empty and then cached successfully. Only `api` builds the shared `gp-backend` image; `worker` and `serenity` consume that image. The rebuild recreated healthy `api`, `worker`, `serenity`, and `web` containers and removed three stopped legacy Compose orphans. `/api/health` returned `status=ok` and the current immutable snapshot. Serenity first waited for the prior persisted lease without restarting, then acquired its own lease and completed a real CNINFO poll. CNINFO reported `cninfo_announcement_schema_changed`, so only Serenity opened its breaker; the core API and worker remained healthy.
- **Operational incident:** During an aborted earlier three-way Compose build, Docker Desktop 4.47 dockerd panicked in BuildKit `filterHistoryEvents` while build history was inspected. Docker Desktop restart restored the engine and existing containers; the final build avoided BuildKit-history operations and completed normally. This is a Docker Desktop defect, not a GP data or SQLite failure.
- **Failure and recovery:** Default builds now use direct network access. A proxy is an explicit, temporary build input only. Serenity lease contention waits in-process for a safe retry; it never steals a valid lease or crash-loops.

## Executed — 2026-07-13 Serenity resident reference topology

- **Scenario:** Ordinary Docker Compose startup includes the Serenity collector without enabling experimental ranking behavior.
- **User intent:** Make Serenity continuously available after `docker compose up` while keeping selection authority deterministic and independent of free-source evidence.
- **Preconditions:** Current source tree and Docker Compose CLI; no existing container is restarted or replaced.
- **Exact steps:** `python -m compileall -q src tests`; `python -m pytest -q`; `docker compose config --quiet`; rendered Compose service inspection; `git diff --check`.
- **Expected result:** `api`, `worker`, `serenity`, and `web` are rendered by default; Serenity runs `serenity-loop` in `reference` mode; legacy `auto` is normalized to reference-only; no ranking authority is enabled.
- **Actual result:** `python -m compileall -q src tests`, the 42-test default Python suite, `docker compose config --quiet`, and `git diff --check` passed. Rendered Compose includes unprofiled `serenity`, runs `python -m gp_assistant.cli serenity-loop`, waits for API health, restarts unless stopped, and resolves `GP_SERENITY_MODE=reference`. A direct policy check confirmed `default=reference`, legacy `auto=reference`, and an otherwise active legacy policy has `reference_weight=0.0`.
- **Failure and recovery:** Set `GP_SERENITY_MODE=off` to disable collection behavior. Build or source failures degrade Serenity evidence only; they do not authorize stale evidence or alter the base decision engine.
- **Decision record:** `docs/adr/0004-serenity-resident-reference-service.md`.


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

## Executed — 2026-07-13 Market-time and SQLite contract

- **Scenario:** Monday pre-open daily selection, EOD pending, immutable session follow-up, and SQLite writer/read contention.
- **User intent:** Publish only a plan grounded in the latest completed daily bars without making health/chat reads look blocked by database writes.
- **Preconditions:** Isolated pytest `agent.db` and Market Memory stores; no user runtime artifact is opened or changed.
- **Environment:** Windows, Python 3.11, SQLite DELETE journal mode, local frontend dependencies.
- **Exact steps:** `python -m pytest -q`; `python -m compileall -q src tests`; frontend `npm run lint`, `npm run typecheck`, `npm test -- --run`, `npm run build`; `docker compose config --quiet`.
- **Actual result:** 39 default backend tests passed. The restored default scope includes current worker, freshness, health, history journal, market-time, storage-race, migration-checksum, agent-store, and chat-contract coverage. The 100-reader test completed in under 500 ms while another connection held `BEGIN IMMEDIATE`. Compile and all four frontend gates passed. Compose configuration validation passed.
- **Evidence:** `tests/agent/test_market_time_storage_contract.py`, `tests/test_worker_reconcile.py`, `tests/test_daily_freshness.py`, `tests/test_history_store_journal_mode.py`, and `tests/test_health_storage_stats.py`.
- **Failure and recovery:** An EOD probe pending state returns without selection/publication. A bounded write lock becomes structured HTTP 503 with `retry_after_ms`; reads use `mode=ro` and remain independent of that write budget.
- **Live-container attempt (2026-07-13):** `docker compose build` built the web image but backend dependency installation failed because the configured build proxy `host.docker.internal:7890` refused connections. A retry overriding the proxy arguments did not complete a replacement backend image. The pre-existing 2026-07-11 backend image was started only to make a real configured-LLM request, and was stopped immediately after the check; it is not validation of this change.
- **Real LLM result (old image, diagnostic only):** The first answer to “当前可执行的三只候选” correctly described `NEXT_SESSION_PLAN`/`WATCH` data but misleadingly listed three plans. A same-session self-review answered that current executable symbols are zero, citing `POSTCLOSE_PENDING`, `can_open=false`, and `WAIT`. This supports the desired no-trade semantics, but also demonstrates why the new current/execution no-trade contract still needs a rebuilt-image acceptance run.
- **Local current-worktree/real-LLM check (2026-07-13):** With a new temporary `GP_STORE_DIR`, `GP_DATA_DIR`, cache, agent DB, and Market Memory root, `PYTHONPATH=src python -m gp_assistant.cli chat "请给我当前可执行的三只候选" --session-id local-source-real-llm-check` returned `decision=no_trade`, `message_kind=no_trade`, `reason=current_snapshot_unavailable`, and an empty pick list. The configured OpenAI-compatible LLM was then asked to independently review the recorded old-image response. It rated it “部分合理”: the self-correction to zero executable symbols was right, while presenting next-session watch plans as current candidates and mentioning null-field thresholds was not. This real-LLM call was a response-quality review only; the current source chat renderer remains snapshot-grounded and does not delegate selection to the LLM.
- **Local worker retry (2026-07-13):** `reconcile_runtime_state()` was run from the current worktree against a second new temporary store/data/cache root, followed by the same current-executable chat request. It produced a non-trade daily snapshot (`daily_e9edf2a36e9`), with `market_phase=NON_TRADING`, `daily_data_state=previous_completed`, and freshness `calendar_status=missing`, `calendar_error=trade_calendar_missing`, `blocking_reason=交易日历缺失，请先刷新 data/raw/trade_calendar.parquet。`. Chat returned `decision=no_trade`, that exact reason, and `picks=[]`. The configured real LLM independently judged that withholding all symbols under this condition is reasonable. This proves the isolated fail-closed branch; it does not prove a current real-data selection because the isolated data root intentionally had no trade calendar/history cache.
- **Production data/worker/chat/LLM validation (2026-07-13, user-authorized):** Before mutation, `store/search/history.db` (3,858,972,672 bytes) returned `PRAGMA quick_check=ok`; production `agent.db` had no current snapshot. The standard process bootstrap applied the additive agent schema migration, then one production `reconcile_runtime_state()` fetched/confirmed all ten tracked real daily series through 2026-07-13. EOD probe was `ready=true` (000001, 600000, 600519), all ten freshness states were `current`, and the worker published `daily_9f6901cc29d2` with `decision_trade_day=daybook_effective_day=2026-07-13`, `target_mode=current_ready`, and `market_phase=POSTCLOSE_PENDING`. The snapshot had `decision=recommend` but `tradeable=false`/`publish_allowed=false`; all board entries were `WATCH`, `NEXT_SESSION_PLAN`, and `can_open=false`. The real chat request “请给我当前可执行的三只候选，并说明依据。” returned structured `decision=no_trade`, `picks=[]`, citing the exploratory low-confidence 600519 evidence. The configured real LLM independently judged this user-visible no-trade response reasonable and said the board must not be shown as current executable candidates. A second production worker call returned `noop=true`; snapshots remained 1 and the current pointer remained `daily_9f6901cc29d2`.
- **Physical legacy-store cleanup (2026-07-13, user-authorized):** Removed `store/gateway.db`, stale `history.db-wal`/`history.db-shm`, 14 pytest SQLite copies (including the intentionally invalid migration fixture), and five historical replay Market Memory checkpoint copies: 22 files total. Confirmed the only retained production SQLite databases are `store/agent.db`, `store/search/history.db`, `store/events/market_memory.db`, and `store/serenity/evidence.db`. No production database was deleted or modified by this cleanup.
- **Legacy-source removal (2026-07-13, user-authorized):** Removed `src/gp_assistant/memory/`, its sole consumer `src/gp_assistant/runtime/turn_loop.py`, the dedicated legacy-path tests, and compiled bytecode. Updated current documentation to name `worker.py`, `chat_agent.py`, and `agent_store.py` as the only product chain. A source/test reference scan found no remaining import or path reference to the removed modules. `python -m compileall -q src tests`, default `python -m pytest -q` (39 passed), and `git diff --check` passed; `gateway.db` was not recreated. Pytest regenerated 11 temporary fixture databases, which were physically removed after validation; only the four production databases remain.
- **Remaining risk:** No current-image provider refresh or local image/worker-to-chat smoke was completed, so provider latency and CNINFO schema drift remain operational validation work.
- **Date:** 2026-07-13.
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

# 2026-07-14 — Serenity-native Alpha and real-LLM production acceptance

- **Static and test gates:** `python -m compileall -q src tests` passed;
  `python -m pytest -q` passed all 253 collected tests; `git diff --check`
  reported only the existing CRLF normalization warning for
  `evidence/market_service.py`. Frontend lint, typecheck, two Vitest files/five
  tests and production build had already passed with the final frontend source.
- **Container gate:** `docker compose build api worker serenity` produced
  `sha256:cd8fcf2ee0ac716dfed3b660ebb36bc8602ba7426292e20c5a9277ef1e4bde30`.
  `docker compose up -d --no-deps api worker serenity` recreated only those
  services; all three used that digest and API health was healthy. No Docker
  Desktop restart, database/volume deletion, synthetic evidence or manual
  target/signal/snapshot mutation occurred.
- **Natural lease and polling:** the new Serenity process waited for the old
  persisted lease through ordinary 30-second retries. It then acquired owner
  `worker-b2662f008e344772a1da7e516f5754f5` and completed real CNINFO polls.
  Poll `serpoll_51b68620afb445ec8d14c7b05f407ca9` had exact ten-symbol complete
  coverage and inserted zero new documents/versions/facts. A later natural poll
  `serpoll_97bde9880f0c4dd9a58d17885f9a215d` changed readiness and freshness
  identities while semantic revision
  `e15a9c6ef06102e5092798b9250cf0548b536ee44ddf042fa0a5c93913bcc175`,
  stable binding `2ae723bcd5eee6b98eb8371d6d10b2d0d898646e5d45abefd1570e6f1e18dcf2`
  and current snapshot `daily_c3af00389213` remained unchanged.
- **Real two-turn chat:** session `accept-serenity-20260714-210045` first turn
  returned HTTP 200 in 41.031 seconds on `daily_c3af00389213`, with
  600519/600036/601318 as `tradeable=false` next-window plans. Its real
  `deepseek-v4-flash` traces were intent `bb38bf11-85bd-4bcb-a25c-e4ac65fd0fc1`,
  narration `76513703-6a27-4ef6-9d2b-eeaaa8b299b3`, and validated repair
  `a3e6e4cd-5386-44a4-8074-e266f5e2fb29`, all HTTP 200.
- **Same-session explanation:** the follow-up returned HTTP 200 in 37.417
  seconds, kept the same snapshot, and returned `snapshot_explanation_only`,
  `tradeable=false`, `perspective=historical`. It explained 600519 with Alpha
  and score contribution both zero, policy `shadow`, `non_binding=true`.
  Intent/narration/repair response IDs were respectively
  `b1579c49-04df-4450-8d64-3a99d274617b`,
  `fdcc545c-8d9b-4063-ba60-2fa76da4f7dd`, and
  `1761a3b3-18dc-4b04-a976-049a74f3fb45`, all HTTP 200. History returned four
  roles, every one bound to `daily_c3af00389213`.
- **Browser gate:** official `agent-browser` loaded `http://127.0.0.1:8080`,
  submitted a real Workspace question, observed `POST /api/chat 200` followed
  by `GET /api/chat/session_ha80ycoy 200`, and rendered the user message, LLM
  answer and three plan cards on `daily_c3af00389213`. An earlier attempt was
  rejected with HTTP 502 because the repaired provider draft asserted `开仓`
  against `tradeable=false`; it committed no turn. The ordinary browser retry
  succeeded, proving both fail-closed authority and recovery without a template.
- **Final health:** `product_ready=true`, no readiness reasons, current snapshot
  `daily_c3af00389213`, live Serenity available with matching semantic revision,
  and LLM verification/product-chat status both ready/successful.
