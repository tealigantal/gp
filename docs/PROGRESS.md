# Current Progress

Last updated: 2026-07-14

## Active Delivery State

- **Active Goal:** Restore the existing production Compose stack so Serenity Alpha is a mandatory candidate-bound ninth Adaptive expert and `/api/chat` uses a real LLM for both routing and grounded narration.
- **Active ExecPlan:** `docs/plans/2026-07-14-serenity-native-alpha-and-llm-chat.md`.
- **Current Milestone:** Source, storage, worker, snapshot and chat contracts are implemented; the backend/default 166-test suite and frontend checks pass; the ordinary production Compose services now run the rebuilt image. Product readiness is intentionally waiting for the real 2026-07-14 EOD bar before the worker can publish the candidate target.
- **Decision Path:** Market Memory preselects and publishes one immutable target; the resident Serenity service completes exact-target official coverage; Adaptive performs one nine-expert score; the resulting target lineage and per-pick Alpha are frozen into `RecommendationSnapshot.v1`.
- **No-fallback Contract:** Partial target coverage, stale or unparsed documents, target switches, invalid legacy modes, missing native payload, old market-time snapshots, or LLM trace/grounding failure cannot expose an eight-expert recommendation or fixed response template.
- **LLM Contract:** Every committed chat turn proves ordered real `intent_routing` (or repair) and `tool_evidence` provider calls with 2xx/model/response IDs. Local code owns symbols, refresh scope, decision, action and every number.
- **Health Contract:** API HTTP 200 is liveness only. `product_ready=true/status=ok` additionally requires a current market-time snapshot, complete embedded native-Alpha lineage, exact active target readiness, a live Serenity lease, and a recent successfully committed two-stage LLM turn.
- **Verified Locally:** `python -m compileall -q src tests`; all 166 default pytest tests; frontend lint, typecheck, Vitest and production build; Compose render; whitespace check; in-place backend/frontend image builds and ordinary four-service recreation. Exact runtime evidence is recorded in `docs/VALIDATION.md`.
- **Runtime Data Boundary:** Existing `agent.db`, Market Memory/history databases, Serenity evidence, Docker volumes and unrelated tracked runtime deletions are preserved. No isolated acceptance store, injected source, manual bootstrap, fallback mode, or temporary production path is used.
- **Next Work:** Let the resident EOD probe observe the real close, then let worker/Serenity naturally publish the target and native snapshot; execute a real first-turn and follow-up chat, inspect persisted LLM evidence, and visually verify the existing Workspace.
- **Blockers:** Free official sources have no SLA and scanned PDFs have no OCR. Either condition is an explicit unavailable/pending state, not permission to continue with baseline ranking.
- **Resume Instructions:** Read `AGENTS.md`, `PROJECT_GOAL.md`, and the active ExecPlan; preserve runtime state; continue from ordinary resident-service logs and `product_ready/readiness_reasons` without manually seeding readiness.

## Snapshot

The repository is currently centered on one active product surface and one production decision path:

- `gateway/` exposes the FastAPI API
- `worker.py` owns market-time resolution, daybook reuse, selection, and snapshot publication
- `chat_agent.py` and `agent_store.py` own snapshot-grounded chat, session binding, transcript, and claims
- `book/` builds the daybook and actionable board
- `judgment/` produces recommendation, follow-up, compare, and exit decisions
- `signal_engine/` emits structural daily signal events
- `market_memory/` stores normalized feature-vector events and decision snapshots
- `probability_engine/` infers evidence-backed probabilities from nearest historical cases
- `risk_engine/` handles execution risk, drawdown risk, and mathematical ranking
- `decision_engine/` runs Adaptive Decision Engine selection, Decision Context, Thesis Lifecycle, Decision Synthesizer, validator, and snapshot persistence
- `evaluation_engine/` owns historical replay, AB validation, calibration, counterfactuals, and error attribution
- `frontend/` renders the chat-first Workspace with a right-side decision snapshot

The current product direction is:

- one Workspace page
- one continuous assistant conversation
- one shared Market-Memory decision source for recommendation, follow-up, comparison, exit, and run-change answers

## Recent Changes

### 2026-07-14 — Serenity native Alpha and real-LLM restoration

- Replaced the post-hoc Serenity add-on with an exact-target native ninth expert inside the one Adaptive score. Complete known-empty official coverage is neutral; incomplete coverage yields formal no-trade with no baseline candidate leakage.
- Added additive target-pointer/progress/withdrawal/formula-epoch migrations, as-of bootstrap/version semantics, full-TTL correction re-observation, strict PDF hydration, immutable DCS/reference checksums, and resident target-switch/DayBook promotion handling.
- Added bounded resident observation of the local target pointer while a source poll is sleeping, so a target created after process startup is consumed promptly without manual polling, source churn or lease takeover.
- Replaced fixed chat rendering with mandatory real-LLM intent routing and grounded narration. The session stores ordered provider evidence, and commits only after snapshot integrity, field-number/action authority and reply grounding validation.
- Expanded health from process liveness to explicit product readiness across current market time, native snapshot contents, Serenity worker/coverage and recent committed LLM evidence.
- ADR 0005 supersedes the reference-only ranking authority in ADR 0004; the resident Compose topology remains.

### 2026-07-11 — Serenity Alpha vertical slice

- Added `gp_assistant/serenity/` with official CNINFO discovery/PDF collection, SSE/SZSE verification, conservative deterministic parsing, append-only SQLite WAL persistence, metadata/content version chains, same-ID revalidation, correction fail-close, per-symbol coverage, resumable pagination/hydration, a persistent source breaker, and renewable worker lease.
- Added a real-bootstrap-only readiness marker. Injected clients/fixtures and ordinary live polls cannot unlock shadow.
- Added an independent 0%–8% add-on after Adaptive scoring. Backfill can produce a labeled reference counterfactual but binding and learning require live verified facts.
- Added nine frozen arms, v2 reference sidecars with explicit trading-day identity and frozen risk plans, opaque pending refs, next-trading-day T+6 evaluation, decision-day bootstrap statistics, one-standard-error weight selection, CAS transitions, atomic ledgers, and automatic suspension.
- Disabled Serenity completely for historical replay/backtests to prevent production-store reads/writes and future leakage.
- Added target-only narration (maximum three facts), no raw Serenity routing context, grounding guards, `/api/health` status, four CLI commands, and separate Compose worker/bootstrap profiles.
- Real `000001` bootstrap: 4 requests, 2 PDF records, 3.64 seconds, complete coverage, marker `serboot_9006363b1b6de1090d027602`, zero qualifying facts, state `shadow`, applied weight 0%.
- Real `000977` bootstrap: 2 PDF records and one verified positive earnings-guidance fact at 0.92 confidence; it remained `backfill_only`, non-learning and non-binding at 0%.
- Final targeted suite passed 119 tests; the isolated full default suite passed all 311 tests; compileall, changed-file Ruff, diff check, and both Compose profile renders passed. Docker runtime checks remain pending because the local engine was unavailable.

### 2026-07-09

- Replaced the old risk-gate decision layer with the Adaptive Decision Engine:
  - `adaptive_policy.py` is now the only production selection authority after ranking
  - low sample size, missing fields, high uncertainty, and ordinary risk flags lower confidence / recommendation strength instead of automatically producing no-trade
  - risk is modeled as an adaptive score penalty, not a hard gate, unless an explicit hard block is present
  - LLM decision payloads are retained for contract shape but marked `not_used_for_selection`
  - decision snapshots now include adaptive policy input/output, policy state version, calibration output, and adaptive validator result
  - historical replay exposes adaptive score, calibrated probability, recommendation strength, and optional post-outcome policy-state updates
- Consolidated slot and daily freshness runtime state:
  - added `runtime.slot_state` as the single normalization layer for clock phase, daily data state, current artifact stage/freshness, and tradeability
  - `/api/health` now derives `daily_data_state`, `artifact_stage`, `artifact_freshness`, `artifact_status`, `book_freshness`, and `tradeability_state` from that layer
  - `artifact_status` no longer mirrors clock `close_pending`; clock data status is exposed separately as `clock_data_status`
  - post-close ready is represented as `market_phase=POSTCLOSE_PENDING`, `daily_data_state=ready`, `artifact_stage=daily_plan`, `artifact_freshness=current`, and `book_freshness=postclose_ready`
  - `gp-worker` uses the same daily data state classification before publishing or blocking runtime artifacts
  - Workspace ops UI no longer suggests manual postclose archive when the daily artifact is already current
  - added `python -m gp_assistant.cli diagnose-slot-state` for read-only inspection of pointer, artifact meta, daily freshness, EOD probe, and cache-only daily last dates

### 2026-07-08

- Added the Decision Intelligence layer on top of Market Memory:
  - every market-facing judgment now receives `DecisionContextModel` fields for market, security, signal/thesis, user, position, objective, and constraints
  - every decision carries `ThesisLifecycle` with `thesis_strengthened`, `thesis_unchanged`, `thesis_weakening`, or `thesis_invalidated`
  - Decision Synthesizer outputs only `HOLD / ADD / REDUCE / EXIT / WAIT / NO_TRADE`
  - recommend, no-trade, pick detail, single-stock, live-entry, compare, candidate-compare, intraday, exit, and run-change workflows attach the same decision fields instead of using keyword-specific answer handlers
  - response payloads and the right-side decision snapshot expose `decision_context_model`, `thesis_lifecycle`, `decision_action`, and `decision_synthesis`
  - added unit coverage for strengthened thesis, invalidated holding, no-trade, and weak-probability rejection behavior
- Completed the production-path migration from the old score stack to the Market-Memory Agent:
  - production `build_day_selection()` now calls the new decision pipeline
  - new decisions are built from signal events, normalized feature-vector similarity, probability evidence, risk ranking, Adaptive Decision Engine selection, and `DecisionContextSnapshot`
  - the old `selection_engine` remains available only as migration reference and low-level data support, not as the recommendation ranking authority
- Added Market Memory persistence:
  - `market_events` with raw features, normalized feature vector, market context, and known outcomes
  - `decision_snapshots` with complete market context, candidates, rejected candidates, historical cases, probability/risk/ranking outputs, LLM decision input/output, validator result, narrator input, and final response
  - optional `GP_MARKET_MEMORY_DIR` for isolated replay stores
- Added probability and risk evidence:
  - nearest historical cases by normalized feature-vector distance
  - similarity-weighted statistics
  - Bayesian shrinkage toward broader priors
  - evidence block with sample size, effective sample size, similarity, success/failure distribution, major failure modes, uncertainty, and confidence
- Added Historical Replay / AB validation:
  - cache-only replay runner for historical trading days
  - no future outcome leakage in Market Memory retrieval
  - selected, rejected, alternative, and no-trade outcome tracking
  - calibration curve and Brier score
  - prediction-error attribution and recommendation regret analysis
- Latest local replay is documented in [historical_validation.md](./historical_validation.md). The result supports better selectivity and risk reduction on the tested sample, but also shows probability overconfidence and limited trade coverage.

### 2026-07-07

- Reworked the worker/runtime market path into one configurable runtime chain:
  - daily freshness and daybook resolution always run first
  - when `GP_INTRADAY_RUNTIME_ENABLED=1`, intraday phases refresh the latest closed 5-minute slot, including the 11:30 lunch slot
  - when `GP_INTRADAY_RUNTIME_ENABLED=0`, the same chain skips minute refresh and publishes a daily-plan artifact
  - `gp-worker` now runs `runtime-loop`; `daily-loop` remains only as a compatibility alias
  - `/api/health` reports intraday runtime from real config and current artifact state instead of a hard-coded disabled value

### 2026-05-05

- Removed the standalone 5-minute execution path from the production runtime:
  - `pulse-loop`, replay-today, slot replay, and separate 5-minute UI affordances are no longer production entrypoints
  - minute refresh now belongs inside the unified runtime chain when enabled
- Removed theme/concept/industry ranking interfaces from the retired score-stack path:
  - `theme_concept.py`, `theme_pool.py`, and `theme_pool_impl.py` are retained as commented archives
  - `agent.py` no longer imports or calls `build_themes` or `last_concept_status`
  - output keeps `themes: []` only for API compatibility
- Rebuilt the then-current mainline calculation to use only local market/candidate data:
  - this was part of the retired score-stack implementation; it no longer defines the production recommendation ranking authority
  - historical candidate industry aggregation used `candidate_score`, `industry_strength_score`, and `peer_consensus_score`
  - snapshot fallback derives full-market strong-line clues from leaders and turnover
  - `mainline.source` is now `derived:daily_universe`, `derived:market_snapshot`, or `derived:unavailable`
- Updated Workspace and ops UI copy to remove 5-minute, slot replay, execution degradation, and observation wording from normal user-facing paths.
- Updated Docker/CLI operational entrypoints so the worker runs one runtime loop; manual ops now expose rebuild-daybook and postclose-archive only.
- Hardened the intent path so `/api/chat` now depends on the LLM router for market-facing requests instead of silently falling back to local semantic heuristics.
- Added explicit API error mapping for intent failures:
  - `503` when the intent LLM is unavailable
  - `502` when the LLM returns invalid or semantically inconsistent TurnFrame output after one repair attempt
- Added `src/gp_assistant/kernel/` as the public service facade for recommendation v2 artifacts, compare, pick detail, validation summary, portfolio state, execution intent preview, paper execution, and workbench aggregation.
- Added active API routes for `recommend_v2`, `compare`, `pick`, `validation/summary`, and `workbench`.
- Improved follow-up explanation grounding so short user questions can explain recent structured business facts instead of repeating prior prose or fabricating prices.
- Added semantic consistency validation for LLM intent frames so obvious mismatches are repaired by the LLM or surfaced as 502 instead of being silently accepted.
- Converted missing subject/rank follow-ups into explicit no-trade business replies instead of 500 errors.
- Replaced deprecated `datetime.utcnow()` usage in paper-trade validation with timezone-aware UTC timestamps.
- Fixed the current README and ops runbook UTF-8 Chinese text, and added `.gitattributes` to align repository text files with the LF line-ending policy already declared in `.editorconfig`.
- Hardened trading-calendar handling so missing, stale, or out-of-range exchange calendars fail closed instead of falling back to weekday assumptions. AkShare calendar refresh now writes a full natural-day range with `is_open=0` for holidays, and `/api/health` exposes calendar status/range/next trading day.

### 2026-04-29

- Completed the dialogue-assistant pass that was previously left in a half-cleaned state.
- Rewrote the user-facing fallback and assistant-context layer so replies sound like an assistant instead of an ops console.
- Added `src/gp_assistant/runtime/dialogue_text.py` as the shared text-cleaning and state-labeling layer.
- Kept the existing architecture shape; changes stay inside the current `parser -> judgment -> narrator -> frontend workspace` chain.
- Finished the runtime-toggle alignment:
  - when `GP_INTRADAY_RUNTIME_ENABLED=0`, live-entry requests do not assume `latest_5m`
  - when enabled, minute freshness is part of the same runtime artifact chain
  - user-facing answers and cards reflect whether the minute stage is enabled
- Stopped leaking internal markers such as `generated 10 picks`, `intraday_runtime_disabled`, and raw gate/debug strings into user replies.
- Fixed term-explain follow-ups so questions like `什么是收盘有效跌破支撑带` and `为什么仅观察` are answered as explanations instead of being misrouted to single-pick detail.
- Reworked the Workspace UI copy and presentation so it feels like a chat assistant rather than an internal control panel.
- Refreshed desktop and mobile responsive behavior, including a real mobile overflow/layout fix discovered during screenshot verification.

### 2026-04-22

- Fixed stale backend CI references and synced the fix to GitHub.
- Removed the old `gp_assistant.chat` and `gp_assistant.recommend` compatibility surface.
- Deleted legacy tests that only existed to support retired service paths.
- Reduced the repository back to the current service architecture.
- Reorganized `docs/` so active docs stay at the top level and historical material is archived.

## Current State

- Main flow remains aligned around `gateway -> runtime -> judgment -> reply -> workspace`.
- Production decisions now flow through `Market Data -> Signal Engine -> Market Memory -> Probability Engine -> Risk Engine -> Ranking -> Adaptive Decision Engine -> Decision Intelligence -> Thesis Lifecycle -> DecisionContextSnapshot`.
- Intent parsing is now a hard LLM dependency for `/api/chat`; unavailable or malformed intent responses are surfaced as explicit API errors instead of hidden fallback behavior.
- `kernel.facade` is the current cross-cutting service boundary for recommendation artifacts, validation, portfolio, execution preview, and workbench aggregation.
- The production decision path is one runtime chain. It always resolves daily freshness/daybook first, builds Market-Memory daily plans, runs Decision Intelligence for user-facing actions, optionally runs 5-minute pulse evaluation when enabled, and does not call AkShare theme/concept/industry ranking APIs.
- Runtime state is normalized by `runtime.slot_state`. Clock phase, daily data state, artifact freshness, and tradeability are separate fields; post-close readiness is not encoded as `market_phase=POSTCLOSE_READY`.
- Mainline is derived from the full-market snapshot and daily candidate universe rather than external theme interfaces.
- The decision layer is constrained by the Adaptive Decision Engine, `DecisionContextModel`, thesis lifecycle, and a validator. The Adaptive Decision Engine owns symbol selection; the Decision Synthesizer can output only `HOLD / ADD / REDUCE / EXIT / WAIT / NO_TRADE` and cannot select/promote/demote candidates or invent market facts.
- Probability outputs are not scores. They include evidence and calibration must be monitored.
- Missing data is an explicit adaptive feature. Risk flags are score penalties unless they represent hard blocks.
- The Workspace page now presents:
  - a conversation-first left pane
  - a persistent decision snapshot on the right
  - cleaned Chinese copy for assistant, recommendation, no-trade, run-change, compare, and detail cards
- Desktop and mobile visual checks were run locally after the UI rewrite.
- The current machine did not have CodeRabbit CLI installed, so external CodeRabbit review was not completed in this pass.

## Verification Snapshot

The following checks passed locally during the 2026-04-29 pass:

- `pytest tests/test_dialogue_assistant_behavior.py tests/test_term_explain_flow.py tests/test_freshness_policy.py tests/unit/test_interpret_request_types.py tests/unit/test_dispatch_new_handlers.py -q`
- `frontend: npm run typecheck`
- `frontend: npm run test`
- `frontend: npm run lint`
- `frontend: npm run build`

Manual browser verification completed locally with screenshots for:

- desktop Workspace
- mobile Workspace

The following backend checks passed locally during the 2026-05-05 cleanup pass:

- `pytest tests\unit\test_interpret_request_types.py tests\test_term_explain_flow.py tests\server\test_chat_endpoint_smoke.py tests\kernel\test_kernel_facade_smoke.py -q`
- `python -m compileall -q src`
- `pytest -q`

The default test suite passed without the previous `datetime.utcnow()` deprecation warnings.

The following checks passed locally during the daily-mainline shutdown pass:

- `pytest`
- `frontend: npm run lint`
- `frontend: npm run typecheck`
- `frontend: npm test`
- `frontend: npm run build`
- static scans for theme ranking calls and retired user-visible degradation wording

Real LLM-connected `/api/chat` acceptance was run from PowerShell after loading `.env`. The checked sequence covered recommendation, rank follow-up, term explanation, comparison, and sell-decision follow-up. All five turns returned HTTP 200; because local data freshness blocked publication, recommendation and subject-dependent follow-ups correctly returned user-facing `no_trade` replies.

The following Market-Memory checks were run locally during the 2026-07-08 validation pass before the Adaptive Decision Engine replacement:

- `python -m gp_assistant.evaluation_engine.historical_replay --days 20260105 ... 20260127 --topk 3 --max-symbols 12 --output-name historical_replay_ab_202601_top3`
- replay result: 16 days, 4 recommend decisions, 12 observe decisions under the retired gate behavior
- new vs legacy baseline: better Top1 T+1/T+3 average return, Top3 T+3 average return, worst drawdown, max consecutive losses, and average regret; worse Top1 T+5 average return and lower trade coverage
- calibration result: Brier score `0.2465254294485468`; probability buckets were materially overconfident on the tested sample. Current adaptive replay should also inspect adaptive score buckets and recommendation-strength groups.

## Current Documentation Anchors

Use these files first when resuming work on this area:

- `src/gp_assistant/worker.py`
  Market-time resolution, completed-bar freshness, immutable daybook reuse, and snapshot publication.
- `src/gp_assistant/chat_agent.py`
  Snapshot-grounded chat rendering and current/historical no-trade behavior.
- `src/gp_assistant/agent_store.py`
  Immutable snapshots, atomic session binding, transcript persistence, and readonly health reads.
- `src/gp_assistant/kernel/facade.py`
  Public service facade for recommendation v2, compare, pick detail, validation, portfolio, execution preview, and workbench aggregation.
- `src/gp_assistant/decision_engine/pipeline.py`
  Production Market-Memory recommendation pipeline.
- `src/gp_assistant/market_memory/`
  Market Memory event store, vector retrieval, and decision snapshot storage.
- `src/gp_assistant/probability_engine/`
  Evidence-backed probability inference and shrinkage.
- `src/gp_assistant/evaluation_engine/historical_replay.py`
  Time-travel-safe historical replay and AB validation.
- `src/gp_assistant/runtime/freshness_policy.py`
  Daily-plan freshness and active-run reuse behavior.
- `frontend/src/features/workspace/`
  Active Workspace UI surface.
- `frontend/src/features/workspace/presentation.ts`
  Shared frontend state wording / presentation mapping.

## Next Cleanup Candidates

- Continue normalizing any remaining older Chinese templates or source files that still carry historical encoding damage outside README, ops runbook, and the actively used Workspace path.
- Decide whether to keep `dialogue_text.py` as the single long-term text policy layer and move any remaining duplicated label logic into it.
- Install and wire CodeRabbit CLI on the working machine if external review is expected to be part of the routine workflow.
- Re-run a real LLM-connected acceptance pass after environment setup confirms `llm_ready=true`, focusing on multi-turn Chinese follow-ups, term explanation, compare, and sell-decision quality.
## 2026-07-11 runtime recovery checkpoint

- Added configurable SQLite history filename and journal mode for Docker Desktop bind mounts.
- Recovered cached-market-data reads using `history-clean.db` with `DELETE` journaling while retaining the original database.
- Rebuilt and verified API, worker, web, health, cache probes, and daybook generation.

## 2026-07-14 Serenity-native ranking and real-LLM recovery complete

- Replaced the fixed `/api/chat` renderer with real LLM intent routing and
  grounded narration while preserving deterministic engine authority over
  candidates, ordering, actions, prices, probabilities and Serenity facts.
- Integrated Serenity into the one Adaptive v2 score as the causally gated
  ninth signed expert. Missing/incomplete exact-target coverage cannot publish
  the eight-expert baseline.
- Added atomic cross-store evidence publication, immutable Serenity/reference
  identities, safe Decision Context Snapshot files, and exact runtime evidence
  bindings before advancing the sole current pointer.
- Split live poll freshness from `SerenitySemanticRevision.v1`. Equivalent
  complete polls renew the worker/coverage certificate without invalidating an
  unchanged snapshot or an in-flight LLM turn; real fact/policy/target changes
  still force rebuild, and partial/expired/dead-worker states fail closed.
- All 253 collected backend tests and compilation passed. The previously run
  frontend lint, typecheck, five Vitest tests and production build remain green;
  Compose validation and whitespace checks passed.
- Rebuilt and recreated only `api`, `worker` and `serenity`. They share image
  `sha256:cd8fcf2ee0ac716dfed3b660ebb36bc8602ba7426292e20c5a9277ef1e4bde30`;
  `web`, Docker Desktop, production databases and volumes were not replaced.
- Natural resident poll renewal changed run/readiness/freshness but retained
  semantic revision `e15a9c6e...`, stable binding and current snapshot
  `daily_c3af00389213`. Health remained `product_ready=true`.
- Real two-turn DeepSeek acceptance and the browser Workspace passed on the
  same immutable snapshot. The first answer returned 600519/600036/601318 as
  non-executable next-window plans; the follow-up explained 600519 with neutral
  shadow Serenity contribution. The persisted conversation contains four roles
  all bound to `daily_c3af00389213`.
