# Tool-Calling Finance Agent Refactor

This refactor replaces the legacy chat orchestration (intent router + scattered cards) with a single, stateful, tool-calling finance agent. The end-user now interacts with one coherent `/api/chat` entrypoint that always grounds financial answers in tool results and persists one canonical `assistant_bundle` per turn.

## Removed legacy lines

- Intent-classifier dominated mainline (`detect_intent`, `classify_intent_llm`) from the runtime.
- Keyword fallbacks, `latest.json` fallback in chat.
- Legacy per-card and status message emissions into the thread.
- Frontend pages and UI paths for compare/sim/workbench.

## New agent loop

1. Hydrate context: read session state and recent bundle summaries.
2. Mandatory tool: `get_session_context(session_id)`.
3. Agent tool loop (deterministic plan in this phase):
   - `ensure_recommendation(session_id)`
   - `resolve_reference(session_id, raw_reference=<user input>)`
   - Optionally `get_pick_detail`, `explain_selection_set`, `get_exit_decision` based on resolution.
4. Validate outputs with strict validators.
5. Persist a single `assistant_bundle` to the event store and return a minimal `ChatResp`.

## Tools

- `get_session_context(session_id)`
- `ensure_recommendation(session_id, topk?, refresh)`
- `resolve_reference(session_id, raw_reference)`
- `explain_selection_set(session_id)`
- `get_pick_detail(session_id, symbol)`
- `compare_symbols(session_id, symbols)`
- `get_exit_decision(session_id, symbol)`
- `get_run_change(session_id)`
- `set_focus_symbol(session_id, symbol)`

## Assistant bundle schema

```
{
  "kind": "assistant_bundle",
  "text": "...",
  "cards": [...],
  "right_panel": {...},
  "tool_calls": [...],
  "tool_results": [...],
  "grounding": {
    "source": "tool_calling_agent",
    "active_run_id": "...",
    "previous_run_id": "...",
    "focus_symbol": "...",
    "active_symbols": ["..."],
    "used_symbols": ["..."],
    "tradeable": false,
    "run_gating": {...},
    "tools_used": ["..."]
  }
}
```

## Validators

- SymbolConsistencyValidator: ensure symbols in text/cards are within current tool outputs or user explicit symbols.
- TradeabilityConsistencyValidator: disallow BUY semantics when `tradeable=false` or `run_gating.decision!=allow`.
- GroundingRequiredValidator: forbid financial answers without any tool results.

## Thread archiving/cleanup

- A one-off script `src/gp_assistant/chat/archive_legacy_threads.py` exports legacy assistant events (non-`assistant_bundle`) to `store/assistant_legacy_archive/`.
- Read-model `/threads/{cid}/items` now returns only two kinds: `text` (user) and `assistant_bundle` (assistant). All legacy fragments are hidden from the UI.

## Why text/cards/panel cannot diverge now

All user-facing surfaces (`text`, `cards`, `right_panel`) are composed in a single `assistant_bundle` from the same set of tool results, then validated as a whole and persisted atomically. The frontend renders only this bundle per assistant turn.

