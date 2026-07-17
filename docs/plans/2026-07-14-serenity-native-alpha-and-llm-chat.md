# Serenity Native Alpha and Real-LLM Chat ExecPlan

This ExecPlan is a living document. `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be updated as work proceeds.

## Purpose / Big Picture

Restore GP's real user journey without preserving the fixed-template deployment
or the post-hoc Serenity add-on. Market data first produces a deterministic
candidate target set. The resident Serenity service then freezes official
announcement coverage for exactly that set. Adaptive Decision Engine v2 scores
all candidates once, with Serenity as a ninth signed expert. One immutable
`RecommendationSnapshot.v1` contains every selected symbol, number, Alpha
contribution and evidence lineage. `/api/chat` invokes the configured LLM to
route and explain that snapshot, while the LLM remains unable to pick stocks or
alter any numerical conclusion.

The production path has no baseline-scoring fallback, old-target fallback,
stale-signal fallback, fixed-template reply fallback, or synchronous external
data fetch in chat. Incomplete Serenity coverage is a first-class pending /
`no_trade` result until the resident collector completes the same target set.

## Progress

- [x] (2026-07-14 14:00 +08:00) Classified the repository as an initialized
  important project and this task as architecture-changing, real-user and
  financial-data-integrity work.
- [x] (2026-07-14 14:00 +08:00) Audited the live containers, production stores,
  `/api/chat`, the retained LLM modules, Serenity collection/storage and the
  Adaptive scoring boundary without mutating runtime state.
- [x] (2026-07-14 14:00 +08:00) Confirmed the live image matches the current
  fixed-template source, production mode is enabled, the LLM credentials are
  configured, and the official model endpoint is reachable.
- [x] (2026-07-14 15:20 +08:00) Replaced reference-only/post-hoc Serenity with an immutable candidate
  target contract and a native ninth-expert scoring input.
- [x] (2026-07-14 15:20 +08:00) Corrected live CNINFO empty-result handling, full-TTL correction observation, target-bound retry progress and strict parsed-content coverage.
- [x] (2026-07-14 15:20 +08:00) Restored two-stage real LLM routing and narration against only the bound
  recommendation snapshot, with no deterministic response fallback.
- [x] (2026-07-14 15:20 +08:00) Added product-readiness health for LLM and Serenity and passed backend,
  frontend, causal/as-of and regression gates.
- [x] (2026-07-14 15:35 +08:00) Rebuilt the ordinary shared backend image and
  recreated the existing Compose services without deleting databases or
  volumes. The prior Serenity lease expired naturally and the new resident
  process acquired it without an unsafe takeover.
- [x] (2026-07-14 15:35 +08:00) Corrected resident target-pointer observation:
  a Serenity process that starts before the decision worker publishes a target
  now watches the additive pointer at a bounded cadence instead of sleeping for
  the full source scheduler interval. The complete default suite now passes
  166 tests, including the exact real CNINFO null-empty response shape.
- [ ] Wait for the ordinary EOD probe to observe a complete 2026-07-14 daily
  bar, then record the natural Serenity poll, worker publication and real
  multi-turn `/api/chat` acceptance against production data.
- [ ] Record actual evidence and any honest limitation (for example, a real
  known-empty Serenity feature has contribution exactly zero).

## Surprises & Discoveries

- The deployed container is not accidentally in development mode; its source
  matches the working tree and `chat_agent.py` deliberately renders fixed
  Chinese templates without importing an LLM.
- The current Serenity integration calls `select_candidates()` first and then
  applies `SerenityAddon.v1`, so it is not an Adaptive expert and can reorder a
  result after the purported single selection authority has completed.
- Serenity targets come from an already-published recommendation snapshot and
  the worker can fall back to cursor targets. This creates lag, target-selection
  bias and a circular dependency.
- A valid CNINFO query with no announcements returns `announcements=null`,
  `totalpages=0`, and `hasMore=false`. The current parser misclassifies this as
  schema drift.
- The production Serenity store is internally consistent but currently has no
  scoring facts. A successful repair may therefore prove a real native Alpha
  feature with value/contribution zero; it cannot manufacture a non-zero effect.
- Partial poll status had been able to advance a cursor and affect success
  history. Source success now requires complete exact-target coverage; partial
  progress is target/window-bound and never advances the complete cursor.
- A date-only runtime noop could save a newly ready DayBook without publishing
  it. Noop now requires exact DayBook equality, so the natural pending-to-ready
  transition advances the current snapshot.
- A later bootstrap could retroactively make an earlier signal read look ready,
  and legacy evaluation formula fields could spuriously reset an epoch. Both
  are now decision-time/formula-lineage bounded with regression tests.
- Process/container health cannot represent product usability. The public
  health contract therefore distinguishes HTTP liveness from readiness across
  current market time, embedded Alpha integrity, resident worker coverage and
  recent committed real-LLM evidence.
- A resident process can validly start before an immutable candidate target
  exists. Treating `candidate_target_unavailable` as an ordinary one-hour
  source interval delayed target adoption. The process now retains its lease
  and observes only the local additive target pointer every bounded lease retry
  interval; it does not contact CNINFO until a target exists or the normal poll
  becomes due.
- The first real post-rebuild EOD probe at 15:32 returned data for all three
  anchors but their last complete bar remained 2026-07-13. The production
  contract correctly stayed `current_pending`; neither a 2026-07-14 candidate
  set nor a recommendation may be fabricated while that remains true.

## Decision Log

- **2026-07-14 — One native scoring path.** Replace the post-hoc add-on with
  Serenity inside `score_candidate()` / `select_candidates()`. Preserve the
  existing eight Adaptive expert weights and apply the separately causally
  gated Serenity weight as a ninth signed contribution. Sorting uses the one
  final score only.
- **2026-07-14 — Coverage is mandatory, neutral is valid.** Complete coverage
  with no relevant fact yields `alpha_value=0` and continues through the same
  formula. Missing, stale, source-error or unparsed coverage produces pending /
  no-trade; it never reallocates weight or invokes an older scoring path.
- **2026-07-14 — Candidate targets precede evidence.** The decision worker
  publishes an immutable target set carrying `decision_trade_day`,
  `daybook_effective_day`, and `observed_at`. Serenity reads only that target
  set. Existing recommendation snapshots and cursors are not target sources.
- **2026-07-14 — LLM explains, engine decides.** The chat endpoint uses the LLM
  for structured intent routing and final Chinese narration, but candidates,
  ranking, scores, prices, actions and Serenity facts come only from the bound
  immutable snapshot. LLM failure returns a service error and commits no
  assistant turn; a template is not substituted.
- **2026-07-14 — No manual production evidence.** Acceptance uses the ordinary
  Compose services and production stores. No synthetic facts, isolated smoke
  store, policy override, stale snapshot copy or manual database mutation is an
  acceptable production result.

## Context and Orientation

`src/gp_assistant/decision_engine/pipeline.py` owns the production decision
pipeline. `adaptive_policy.py` owns scoring and selection. `serenity/store.py`
owns append-only evidence, coverage and frozen signals; `serenity/worker.py`
is the only process allowed to perform announcement network I/O.
`agent_store.py` publishes immutable recommendation snapshots and atomically
binds sessions/turns. `chat_agent.py` is the sole `/api/chat` orchestration path.
`llm/interpret.py` and `llm/narrate.py` are the retained, real two-stage LLM
interfaces. `runtime/grounding.py` validates that narration cannot escape the
deterministic evidence envelope.

## Plan of Work

First add an append-only candidate-target table and model. The decision pipeline
publishes a content-addressed target set from the deterministic preselection
list. The resident collector consumes only the newest current target set and
freezes coverage/signals for those symbols. Correct as-of reads so coverage,
document versions, first-seen time and effective availability are all bounded
by `observed_at`; backfill stays non-binding.

Next extend Adaptive scoring with Serenity expert scores, contribution and
lineage. A complete neutral feature is allowed; every other incomplete state
returns a single-path no-trade result. Remove the second scoring/reordering pass
from the pipeline. Serialize the exact Alpha feature and contribution into the
canonical recommendation snapshot rather than re-reading a sidecar in chat.

Then replace `_render()` in `chat_agent.py` with two-stage LLM orchestration.
Build compact routing and narration contexts from the bound `MarketBook`, its
snapshot payload and prior session turns. Validate structured routing, validate
the narrated reply, and only then atomically commit the turn. Map LLM
configuration/transport/parse errors to explicit HTTP service errors.

Finally expose LLM readiness and recent-call metadata plus Serenity target /
coverage status from `/api/health`, run all gates, rebuild the shared backend
image, recreate ordinary services without volume deletion, and exercise a real
first-turn and follow-up chat. A valid current no-trade result remains an
acceptable recommendation outcome when the engine's real hard blocks demand it.

## Concrete Steps

Run from `C:\Users\24179\Desktop\gp`:

1. `python -m compileall -q src tests`
2. targeted Serenity, Adaptive, AgentStore, chat and gateway pytest files
3. `python -m pytest -q`
4. from `frontend/`: `npm run lint`, `npm run typecheck`,
   `npm test -- --run`, `npm run build`
5. `docker compose config --quiet` and `git diff --check`
6. `docker compose build api web`
7. `docker compose up -d --force-recreate api worker serenity web`
8. inspect `/api/health`, the latest candidate target/poll/snapshot, and perform
   real `/api/chat` first-turn, follow-up and history reads.

Do not delete or replace `store/agent.db`, Market Memory, Serenity evidence,
Docker volumes, or unrelated runtime artifacts during these steps.

## Validation and Acceptance

- A unit/integration test proves positive, negative and neutral Serenity Alpha
  enter the native expert map and final score, and no post-hoc ranker runs.
- A test proves incomplete coverage cannot fall back to baseline selection,
  prior target symbols or an older frozen signal.
- As-of tests prove later coverage/version changes do not alter a historical
  decision and backfill never contributes.
- Snapshot tests prove candidate order, Serenity value, contribution, fact IDs
  and hashes are published atomically and chat needs no live sidecar read.
- Chat tests prove both LLM stages are called, grounded output is committed once,
  duplicate turns are idempotent, and LLM failure commits no assistant response.
- The final container acceptance uses configured real market/Serenity stores and
  configured real LLM. It records the response model/request metadata, snapshot
  ID, same-session binding, actual engine decision and actual Alpha contribution.

## Idempotence and Recovery

Schema creation uses additive `CREATE TABLE IF NOT EXISTS` statements and
content-addressed immutable rows. Re-running publication of the same target set
is a no-op. Service recreation keeps bind-mounted stores. If a source or LLM
call fails, retain the formal pending/error state and retry through the resident
service's ordinary schedule; do not publish a fabricated success or restore a
legacy path. A code rollback may restore the previous image, but it must not
rewrite existing append-only evidence or snapshots.

## Outcomes & Retrospective

Completed locally on the ordinary production Compose stack on 2026-07-14.

- Serenity is the ninth signed expert inside the single Adaptive score. Complete
  neutral coverage contributes zero; incomplete coverage remains pending/no-trade.
- Candidate target, frozen Alpha, ordered fact lineage, semantic revision,
  Decision Context Snapshot, reference/pending records and the public snapshot
  are integrity-checked and published sidecar-first/pointer-last.
- Freshness certificates are now separate from decision semantics. Natural poll
  `serpoll_51b68620afb445ec8d14c7b05f407ca9` advanced to
  `serpoll_97bde9880f0c4dd9a58d17885f9a215d`: readiness and freshness tokens changed,
  while semantic revision
  `e15a9c6ef06102e5092798b9250cf0548b536ee44ddf042fa0a5c93913bcc175`,
  stable binding and current snapshot `daily_c3af00389213` did not change.
- Real DeepSeek `deepseek-v4-flash` first-turn and same-session follow-up both
  returned HTTP 200. The first produced 600519/600036/601318 as non-executable
  next-window plans; the follow-up retained the same snapshot and explained
  600519 with `snapshot_explanation_only`, Alpha/contribution zero, shadow and
  non-binding semantics. Four persisted roles all reference the same snapshot.
- The browser Workspace completed a real POST/GET conversation against that
  snapshot and rendered the user request, LLM answer and three plan cards. One
  earlier provider draft/repair was correctly rejected with HTTP 502 for an
  unauthorized `开仓` claim and committed no turn; an ordinary retry succeeded.
- `python -m compileall -q src tests`, all 253 collected backend tests, frontend
  lint/typecheck/Vitest/build, Compose configuration and `git diff --check`
  passed. The final shared backend image digest is
  `sha256:cd8fcf2ee0ac716dfed3b660ebb36bc8602ba7426292e20c5a9277ef1e4bde30`.
- No Docker Desktop restart, database/volume deletion, synthetic evidence,
  isolated production substitute, manual signal injection or template fallback
  was used.
