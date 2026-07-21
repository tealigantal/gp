# DeepSeek Beta Strict Tool Routing ExecPlan

## Purpose / Big Picture

Restore the real `/api/chat` journey for the configured `deepseek-v4-flash` provider by making its strict tool-routing request conform to the official DeepSeek Beta contract. The LLM continues to route only; deterministic local code remains responsible for selection and numerical decisions.

## Progress

- [x] 2026-07-17: Proved the live 400 occurs before business tools, with a 7,492-byte routing payload; it is not the prior context-overflow failure.
- [x] 2026-07-17: Switched Compose defaults and local runtime configuration to `https://api.deepseek.com/beta`.
- [x] 2026-07-17: Made every strict tool object require all declared properties and represent unknown routing values as JSON `null`.
- [x] 2026-07-17: Passed targeted chat-route tests, compileall, and Compose configuration validation.
- [x] 2026-07-17: Rebuilt the shared backend image and recreated the API, runtime worker, and Serenity worker.
- [x] 2026-07-17: Verified the actual Beta provider returns HTTP 200 and an `answer_chat` tool call for the complete GP tool schema with `tool_choice=required` and thinking disabled.
- [x] 2026-07-17: Rebuilt all local GP services from the current workspace after the Serenity CNINFO v2 source-contract repair; backend source provenance matches the rebuilt image and Web was refreshed from local frontend source.
- [x] 2026-07-17: Confirmed the rebuilt Serenity worker completes a real official no-result poll rather than emitting `cninfo_announcement_schema_changed`.
- [x] 2026-07-17: Restored the seven deleted `gp_assistant.memory` files exactly from `af90e6a`'s first parent `fb41d91`, then rebuilt every local service from the current workspace.
- [x] 2026-07-18: Ran a real current `/api/chat` request after publication. It committed a native two-candidate plan for `002415` and `601318`; intent routing, narration, and narration repair each returned provider HTTP 200 with response IDs.
- [x] 2026-07-18: Made product-chat verification shared across the two Uvicorn processes, so `/api/health` reports the committed real chat instead of a process-local false `unverified` state.
- [x] 2026-07-18: Promoted `gp-serenity-worker` to a default resident Compose service. A plain `docker compose up -d --build` started the API, market worker, Serenity worker, and Web service; real chat subsequently restored LLM readiness.
- [x] 2026-07-18: Repaired the Workspace integration contract after the single-protocol cutover: Nginx now targets the Compose `gp` service, Workspace reads project the current `AgentStore` snapshot/turns, and each frontend chat turn carries a generated idempotency key. Browser acceptance completed a real two-candidate Serenity question with HTTP 200; the market worker emitted a publish followed by safe no-op cycles.
- [x] 2026-07-18: Repaired the narration field-label precedence that misread `第一目标盈亏比 0.73` as a target price. Rejected answers now remain fail-closed per turn while a configured real provider stays directly retryable; the Workspace distinguishes `已验证`, `可重试`, and `未配置` without adding a probe, template, or fallback.
- [x] 2026-07-18: Closed the end-to-end assistant-response presentation contract in `src/gp_assistant/contracts/api.py`. Every committed non-empty reply now carries the same narrative through POST, idempotent replay, persisted-session projection, and Workspace rendering; legacy persisted turns are projected without a database rewrite, and malformed/empty metadata is visibly degraded rather than rendered as a blank reply.
- [x] 2026-07-18: Retired the remaining runtime-affecting compatibility contracts. Worker operations now have one strict source in `contracts/runtime.py`; routing intents and market time reject obsolete aliases; daily-freshness report fields are explicitly projected in their owning module. The default worker and daily-freshness tests now exercise `AgentStore + MarketTimeContext + runtime-loop` rather than removed file-store/portfolio seams.
- [x] 2026-07-18: Completed final live Top-N and same-session follow-up acceptance after rebuilding every Compose service from the same source digest. Explicit candidate-list wording now wins over generic exit-keyword normalization; mainland security identifiers are checked by the symbol boundary rather than misclassified as price numbers; and natural negative action explanations such as “盘后不宜直接开仓” remain allowed while affirmative execution instructions stay fail-closed.
- [x] 2026-07-18: Retired structured assistant-output cards from the Workspace transcript. Every canonical intent now renders only its validated committed narration plus optional LLM-provided follow-up prompts; the right-side decision snapshot remains the single structured operational surface, and no selector, numerical, or Serenity boundary changed.
- [x] 2026-07-21: Separated immutable daily decision rank from intraday board display rank. Native snapshots now require the same selected symbol set and preserved pick-level decision rank, while allowing the lunch/continuous board to reorder by live execution readiness. Relaxed narration from mandatory GPVAL-only output to exact candidate-and-field-bound natural numeric output.
- [x] 2026-07-21: Disabled the complete post-generation narration validation and repair layer at user direction. LLM prose no longer receives symbol, numeric, action, sizing, or Serenity post-validation; immutable snapshot fields remain the authoritative structured API result.
- [x] 2026-07-21: Added `GET /api/lunch/current` (`lunch_snapshot.v1`) without changing `/api/book/current`. The lunch response has its own morning-session completion contract and an unconditional `daily.today_complete=false`; Workspace now renders lunch completion only from that endpoint and no longer calls a generic `slot_status=OK` “日线就绪”.
- [x] 2026-07-21: Added a narration-system requirement that every candidate included in `candidate_details` explicitly reports its own `final_score` as the comprehensive score; secondary candidates may not omit it or substitute probability/confidence.
- [x] 2026-07-21: Rebuilt `gp`, `gp-worker`, and `gp-serenity-worker` from the local workspace. After the worker published compatible `daily_417a5311b334`, a real Top-3 `/api/chat` response named the three candidate comprehensive scores: 52.75, 52.09, and 50.62.
- [x] 2026-07-21: Removed local hard-field reconstruction from `/api/chat` routing at user direction. Candidate quantity, scope, references, and refresh intent now remain the strict LLM router's frame; local code only validates and resolves it against the current immutable snapshot.
- [x] 2026-07-21: Rebuilt the shared backend services and verified a real same-session Top-10 → “预期收益大一点” conversation. The LLM selected `topk=10`, all ten candidate certificates stayed in scope, and the reply reordered them by supplied expected return instead of collapsing to the first symbol.

## Surprises & Discoveries

- The earlier July 9 failure was prompt overflow. The current live request is compact, so reapplying prompt compression cannot repair it.
- The former strict schemas marked fields optional. DeepSeek Beta validates strict schemas server-side and requires every property in every object to be required.
- The provider's exact response identified the immediate rejection: thinking mode does not allow `tool_choice`. Beta accepts the same request when thinking is explicitly disabled.
- CNINFO's observed no-result response has `announcements: null`, not an array. The former strict array check misclassified this successful official response as a source-schema failure.
- A clean Git source-status check does not prove the merged source is runnable. Here, `af90e6a` created a tracked inconsistency: it preserved a `turn_loop` import while deleting its package. Compilation alone does not detect this missing import target; chat-related pytest collection does.
- A late write from a pre-native `SerenityAddon.v1` runtime artifact was evaluated as a native sample after the first formula cutover. That correctly failed integrity checks, but incorrectly left the current policy suspended. Formula epochs must isolate such immutable legacy evidence before evaluation.
- Chat commit uses an optimistic current-snapshot check. A worker publication during a provider round-trip produces an explicit 503 rather than committing a stale answer; a subsequent request on a stable snapshot commits normally.
- `第一目标` is a prefix of the distinct `第一目标盈亏比` field. Generic label matching therefore bound the latter's display value as `take1` before the correct risk/reward field, rejecting an otherwise grounded repair. Specific numeric labels must take precedence over their prefixes.
- Commit `268b43c` restored Workspace reads by exposing the persisted `AgentStore` payload verbatim. The single-protocol chat payload keeps the real LLM answer in `reply`/turn `content`, while the old `ChatThread` assumed `meta.message.narrative_text`; ordinary `chat` turns therefore rendered an empty body despite a committed provider response. The failure is a read-model/presentation-contract gap, not a provider-call failure.
- Producer compatibility covers the complete backend source digest. Recreating only `gp` after a backend edit correctly makes the running worker's old snapshot incompatible; a source change therefore requires a single rebuild of `gp`, `gp-worker`, and `gp-serenity-worker` before live-chat acceptance.
- A user asking for a Top-N plan can mention plan fields such as `止损`. Generic concern parsing must not convert that concrete list request into an exit decision after local candidate scope is derived. Similarly, negative action phrases need their own grammar so they do not become false execution recommendations.
- The 2026-07-21 score-follow-up incident showed that the immutable snapshot had all ten scores, while the selected narration target was only the first focused symbol. Prompt-level score disclosure therefore applies to every supplied candidate certificate and must not describe a missing narration target as missing snapshot data.

## Decision Log

- Use DeepSeek Beta directly for all GP LLM calls; do not retain a `/v1` compatibility fallback.
- Preserve strict tools. Unknown optional business inputs are required fields with a `null` value, not omitted fields.
- Keep Serenity at shadow/0% after a formula-epoch recovery. Its own causal controller may move it to 1% probation only after the documented 40 mature-day, 300-result and performance gates; no manual weight override is permitted.
- Preserve a committed-chat signal separately from retry eligibility: only a committed validated turn makes `llm_ready=true`, while an already configured provider exposes `llm_retryable=true` after a rejected turn. Recovery happens only through the user's next real question.

## Validation and Acceptance

- Targeted agent routing and chat endpoint tests pass.
- `python -m compileall -q src tests` passes.
- `docker compose config --quiet` resolves the Beta URL for every Python service.
- A real `/api/chat` request commits a snapshot-bound business response with a complete, real two-stage LLM trace (including any validator-directed repair), and `/api/health` reports `product_ready=true`.
- The `第一目标盈亏比` display value passes its own field validation while the same value presented as `第一目标` still fails. A failed narration yields `llm_ready=false` and `llm_retryable=true`; missing configuration yields both false; a subsequent real committed turn immediately restores `llm_ready=true` in Workspace.

## Idempotence and Recovery

Recreating Compose services does not alter mounted `store/`, `data/`, `cache/`, or `results/` data. If the rebuilt route fails, retain the captured provider response and recover by rebuilding the previously tagged image; do not delete runtime state.
