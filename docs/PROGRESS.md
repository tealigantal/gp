# Current Progress

Last updated: 2026-04-29

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
- The 5-minute runtime is currently treated as an optional capability. When disabled, the product now consistently falls back to day-level planning and observation wording.
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

## Current Documentation Anchors

Use these files first when resuming work on this area:

- `src/gp_assistant/runtime/turn_loop.py`
  Turn orchestration, tool-facing assistant context, decision-basis explanation.
- `src/gp_assistant/runtime/narrator.py`
  User-facing fallback text and canonical reply assembly.
- `src/gp_assistant/runtime/dialogue_text.py`
  Shared text cleaning, observation explanation, and state labeling.
- `src/gp_assistant/runtime/concern_parser.py`
  Request parsing and `term_explain` / intraday-disabled routing behavior.
- `src/gp_assistant/runtime/freshness_policy.py`
  Freshness downgrades when intraday execution is disabled.
- `frontend/src/features/workspace/`
  Active Workspace UI surface.
- `frontend/src/features/workspace/presentation.ts`
  Shared frontend state wording / presentation mapping.

## Next Cleanup Candidates

- Continue normalizing any remaining older Chinese templates or source files that still carry historical encoding damage outside the actively used Workspace path.
- Decide whether to keep `dialogue_text.py` as the single long-term text policy layer and move any remaining duplicated label logic into it.
- Install and wire CodeRabbit CLI on the working machine if external review is expected to be part of the routine workflow.
- Re-run a real LLM-connected acceptance pass after environment setup confirms `llm_ready=true`, because the visual verification in this pass focused on structure and layout, not final model prose quality.
