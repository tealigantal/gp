# Current Progress

Last updated: 2026-05-05

## Snapshot

The repository is currently centered on one active product surface:

- `gateway/` exposes the FastAPI API
- `runtime/` owns concern parsing, turn orchestration, and user-safe reply assembly
- `memory/` stores session, transcript, and follow-up context
- `book/` builds the daybook and actionable board
- `judgment/` produces recommendation, follow-up, compare, and exit decisions
- `frontend/` renders the chat-first Workspace with a right-side decision snapshot

The current product direction is:

- one Workspace page
- one continuous assistant conversation
- one shared decision source for recommendation, follow-up, comparison, exit, and run-change answers

## Recent Changes

### 2026-05-05

- Removed the 5-minute execution path from the production runtime:
  - `pulse5m.py` is retained only as a commented historical archive
  - `pulse-loop`, replay-today, slot replay, minute fetch, and 5-minute UI affordances are no longer production entrypoints
  - canonical picks now use daily-plan states such as `PLAN_READY`, `WAIT_PULLBACK`, `RISK_HIGH`, `INVALIDATED`, and `WATCH_ONLY`
- Removed theme/concept/industry ranking interfaces from the production recommendation path:
  - `theme_concept.py`, `theme_pool.py`, and `theme_pool_impl.py` are retained as commented archives
  - `agent.py` no longer imports or calls `build_themes` or `last_concept_status`
  - output keeps `themes: []` only for API compatibility
- Rebuilt mainline calculation to use only local market/candidate data:
  - candidate industry aggregation uses `candidate_score`, `industry_strength_score`, and `peer_consensus_score`
  - snapshot fallback derives full-market strong-line clues from leaders and turnover
  - `mainline.source` is now `derived:daily_universe`, `derived:market_snapshot`, or `derived:unavailable`
- Updated Workspace and ops UI copy to remove 5-minute, slot replay, execution degradation, and observation wording from normal user-facing paths.
- Updated Docker/CLI operational entrypoints so the worker runs `daily-loop`; manual ops now expose rebuild-daybook and postclose-archive only.
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
- Finished the 5-minute shutdown alignment:
  - when `GP_INTRADAY_RUNTIME_ENABLED=0`, live-entry requests no longer assume `latest_5m`
  - freshness planning degrades to day-level / active-run-safe behavior
  - user-facing answers and cards no longer pretend 5-minute execution data exists
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
- Intent parsing is now a hard LLM dependency for `/api/chat`; unavailable or malformed intent responses are surfaced as explicit API errors instead of hidden fallback behavior.
- `kernel.facade` is the current cross-cutting service boundary for recommendation artifacts, validation, portfolio, execution preview, and workbench aggregation.
- The production recommendation path is daily-plan only. It does not run 5-minute pulse evaluation and does not call AkShare theme/concept/industry ranking APIs.
- Mainline is derived from the full-market snapshot and daily candidate universe rather than external theme interfaces.
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
- static scans for production `pulse5m`, theme ranking calls, and retired user-visible 5-minute/observation wording

Real LLM-connected `/api/chat` acceptance was run from PowerShell after loading `.env`. The checked sequence covered recommendation, rank follow-up, term explanation, comparison, and sell-decision follow-up. All five turns returned HTTP 200; because local data freshness blocked publication, recommendation and subject-dependent follow-ups correctly returned user-facing `no_trade` replies.

## Current Documentation Anchors

Use these files first when resuming work on this area:

- `src/gp_assistant/runtime/turn_loop.py`
  Turn orchestration, tool-facing assistant context, decision-basis explanation.
- `src/gp_assistant/runtime/narrator.py`
  User-facing fallback text and canonical reply assembly.
- `src/gp_assistant/runtime/dialogue_text.py`
  Shared text cleaning, observation explanation, and state labeling.
- `src/gp_assistant/runtime/concern_parser.py`
  LLM-backed request parsing and normalization behavior.
- `src/gp_assistant/llm/interpret.py`
  Strict JSON intent router prompt, one-shot repair, and parse error reporting.
- `src/gp_assistant/kernel/facade.py`
  Public service facade for recommendation v2, compare, pick detail, validation, portfolio, execution preview, and workbench aggregation.
- `src/gp_assistant/runtime/freshness_policy.py`
  Daily-plan freshness and active-run reuse behavior.
- `src/gp_assistant/selection_engine/mainline.py`
  Derived mainline calculation from daily candidate universe and market snapshot.
- `frontend/src/features/workspace/`
  Active Workspace UI surface.
- `frontend/src/features/workspace/presentation.ts`
  Shared frontend state wording / presentation mapping.

## Next Cleanup Candidates

- Continue normalizing any remaining older Chinese templates or source files that still carry historical encoding damage outside README, ops runbook, and the actively used Workspace path.
- Decide whether to keep `dialogue_text.py` as the single long-term text policy layer and move any remaining duplicated label logic into it.
- Install and wire CodeRabbit CLI on the working machine if external review is expected to be part of the routine workflow.
- Re-run a real LLM-connected acceptance pass after environment setup confirms `llm_ready=true`, focusing on multi-turn Chinese follow-ups, term explanation, compare, and sell-decision quality.
