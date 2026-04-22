# DeepSeek Tool-Calling Finance Agent Refactor

This document summarizes the refactor to a single, stateful DeepSeek-based tool-calling finance agent.

1) Removed legacy lines
- Removed orchestrator-first, intent-classifier-dominated routing from the main chat path.
- Removed keyword fallbacks, latest.json fallback in chat, and legacy v1 recommendation narrative from the mainline.
- Removed compare/sim/workbench UI and associated adapters/mappers from chat timeline.
- Thread read-model now hides all legacy assistant fragments; only user text and assistant_bundle are returned.

2) DeepSeek tool-calling loop
- The agent uses DeepSeek /chat/completions via an OpenAI-compatible client.
- Step 0: load session_state and recent bundle summaries (not raw legacy text).
- Step 1: expose only get_session_context; the model must call it first.
- Step 2: expose the full high-level tools; allow 1–3 tool rounds.
- Step 3: when the model stops calling tools, it produces the final answer.
- Step 4: validators enforce symbol, tradeability, and grounding constraints; retry once on failure.
- Step 5: persist a single assistant_bundle that unifies text + cards + right_panel + grounding.

3) Tools and schema
- High-level tools only: get_session_context, ensure_recommendation, resolve_reference, explain_selection_set, get_pick_detail, compare_symbols, get_exit_decision, get_run_change, set_focus_symbol.
- Input schemas are JSON object shapes; strict mode can be applied by switching base_url to /beta and setting strict=true per function.

4) assistant_bundle schema
- See src/gp_assistant/chat/assistant_bundle.py for canonical fields: text, cards, right_panel, tool_calls, tool_results, grounding (source=deepseek_tool_calling_finance_agent, run fields, tools_used, used_symbols).

5) Validators
- SymbolConsistencyValidator: symbols in text/cards must come from current tool results, user explicit symbols, or current selection set.
- TradeabilityConsistencyValidator: when tradeable=false or run_gating!=allow, forbid BUY semantics.
- GroundingRequiredValidator: forbid financial answers without current turn tool grounding.

6) Legacy archive strategy
- A one-off script exports legacy assistant items to store/assistant_legacy_archive/.
- /threads/{cid}/items returns only user text + assistant_bundle, hiding legacy fragments from UI.

7) No more “cards vs text” mismatch
- The agent composes a single assistant_bundle per turn from the exact tool results used, and validators gate content—so text, cards, and right panel can’t diverge.

