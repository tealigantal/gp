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
- [ ] Execute full `/api/chat` after the worker publishes a current book; the current request is blocked locally by `current book unavailable`, before LLM routing.

## Surprises & Discoveries

- The earlier July 9 failure was prompt overflow. The current live request is compact, so reapplying prompt compression cannot repair it.
- The former strict schemas marked fields optional. DeepSeek Beta validates strict schemas server-side and requires every property in every object to be required.
- The provider's exact response identified the immediate rejection: thinking mode does not allow `tool_choice`. Beta accepts the same request when thinking is explicitly disabled.
- CNINFO's observed no-result response has `announcements: null`, not an array. The former strict array check misclassified this successful official response as a source-schema failure.

## Decision Log

- Use DeepSeek Beta directly for all GP LLM calls; do not retain a `/v1` compatibility fallback.
- Preserve strict tools. Unknown optional business inputs are required fields with a `null` value, not omitted fields.

## Validation and Acceptance

- Targeted agent routing and chat endpoint tests pass.
- `python -m compileall -q src tests` passes.
- `docker compose config --quiet` resolves the Beta URL for every Python service.
- A real `/api/chat` request returns a business response rather than an upstream HTTP 400, and `/api/health` remains healthy.

## Idempotence and Recovery

Recreating Compose services does not alter mounted `store/`, `data/`, `cache/`, or `results/` data. If the rebuilt route fails, retain the captured provider response and recover by rebuilding the previously tagged image; do not delete runtime state.
