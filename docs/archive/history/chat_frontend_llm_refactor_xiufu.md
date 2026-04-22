# Chat/Frontend/LLM Refactor on `xiufu`

This document summarizes the refactor work to converge to a Chat‑first stock recommendation assistant with an LLM planner, deterministic executor, and unified UI protocol.

## Changed Files

Backend
- src/gp_assistant/chat/intent_schema.py (add PlannerPlan schema)
- src/gp_assistant/chat/intent_classifier.py (upgrade to planner `plan_message` while keeping legacy classifier)
- src/gp_assistant/chat/orchestrator.py (add tri‑phase `handle_message_v2` and make it default)
- src/gp_assistant/chat/session_store.py (fix active_run_id priority; add previous_* and planner output fields)
- src/gp_assistant/chat/run_reuse.py (new; run reuse/stale/refresh decision)
- src/gp_assistant/chat/run_diff_service.py (new; run difference explanation)
- src/gp_assistant/server/models.py (extend ChatResp with ui_items/right_panel/planner_trace)
- src/gp_assistant/server/app.py (pass through new fields; extend thread mapping and previews for new cards; fix fallback_used semantics; unread count covers new kinds)

Frontend
- frontend/src/api/types.ts (extend ChatResp)
- frontend/src/api/contracts.ts (extend ThreadItem kinds and conversation preview kinds)
- frontend/src/pages/Chat.tsx (render new cards; add RightContextPanel; persist last right panel from chat response)
- frontend/src/pages/Conversations.tsx (delete current conversation switches to latest/new)
- frontend/src/features/chat/RightContextPanel.tsx (new; shows run/context state)
- frontend/src/features/chat/cards/*.tsx (new minimal cards for no_trade/pick_detail/compare/exit_decision/run_change)

Docs
- docs/chat_frontend_llm_refactor_xiufu.md (this document)
- docs/manual_acceptance_chat_frontend_llm.md (manual acceptance steps)

## Planner Contract

The planner produces strict JSON (no narration):

Fields (minimum): intent, symbol, symbols, ordinal, topk, force_refresh, reuse_active_run, response_card_kind, focus_symbol, compare_symbols, explanation_target, confidence, reason

Intent values: recommend_topn | explain_no_trade | analyze_symbol | analyze_nth_pick | compare_symbols | exit_decision | explain_ranking | explain_run_change | risk_points | clarify_tradeability | refresh_recommend | general_explain | unknown

Rules:
- LLM planner first if available; fallback to rules on unavailable/invalid/low confidence
- LLM does not invent numbers (stop/take/entry/RR/execution_state/tradeable)
- Binds ambiguous pronouns to active run/focus

## Orchestrator (Tri‑phase)

1) Planner: reads session state + recent context; outputs plan
2) Deterministic executor: executes one of paths without LLM fabrication
   - recommend_topn / refresh_recommend -> canonical artifact (PickArtifactV2 gated)
   - explain_no_trade -> based on run_gating/reason
   - analyze_symbol / analyze_nth_pick -> kernel.pick_detail
   - compare_symbols -> kernel.compare_symbols
   - exit_decision -> heuristic from pick detail execution_state/gating
   - explain_run_change -> run_diff_service
   - general_explain -> LLM for text only
3) Renderer: returns natural text reply and ui_items; appends card events into thread

## Unified UI Message Protocol

ChatResp adds:
- ui_items: Array<{ type, data, focus_symbol?, run_id? }>
- right_panel: { active_run_id, previous_run_id, focus_symbol, active_symbols, planner_intent, executor_path, reused_run, stale, cache_level, refresh_reason, top_symbols, ... }
- planner_trace: the raw planner output
- fallback_used: true only when planner path degraded to rules

Thread mapping supports kinds: text | recommendation | no_trade | pick_detail | compare | exit_decision | run_change | status

Preview rules:
- recommendation -> “推荐清单 N”
- no_trade -> “空仓原因”
- pick_detail -> “研究 SYMBOL”
- compare -> “对比 A vs B”
- exit_decision -> “卖出判断 SYMBOL”
- run_change -> “推荐变化说明”
- status -> message
- text -> first line

## Run Reuse / Stale / Refresh Strategy

- Default reuse active run for follow‑ups (no re‑compute)
- Recommend reuses when active run is fresh; refresh when stale; create when none
- Stale heuristic: active run_id date older than today -> stale
- right_panel exposes reused_run / stale / cache_level / refresh_reason

## ChatShell Structure

- Left: Conversations (delete switches to latest/new; create new)
- Center: Chat thread; ui_items embed cards
- Right: RightContextPanel (active run, previous run, focus, top symbols, reuse/stale, intent/executor)
- Compare/Sim routes remain but are no longer primary from Chat

## Session State & Run Context

- Fix: active_run_id prefers run_id over as_of
- Add previous_run_id / previous_active_symbols / last_planner_output
- On recommend/refresh success: migrate previous_* and set new active_* fields

## Compatibility Notes

- Legacy orchestrator is preserved in file; new handle_message_v2 overrides module export for server
- Existing event_store and thread APIs remain; extended with new card kinds

