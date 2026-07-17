# Single-Protocol Service Contract

The product API has one immutable chat/write protocol and a small Workspace
read model. The read model is derived from the same `AgentStore` snapshot and
turn records; it does not restore the retired book/run JSON authority.

## POST /api/chat

```json
{"session_id":"optional","client_turn_id":"required-idempotency-key","message":"给我当前候选"}
```

`message` and `client_turn_id` are required. A new session binds to the current valid `RecommendationSnapshot.v1`; every later turn in that session uses the same immutable snapshot. Retrying the same `client_turn_id` returns the already committed assistant turn without another write. Each successful new turn has two required logical provider stages: routing must contain a valid `intent_routing` result (optionally after `intent_routing_repair`), and narration must contain `tool_evidence` (optionally followed by one `tool_evidence_repair` when the first draft fails authority validation). Every provider call required by the committed turn must have a 2xx status, request/response model and provider response ID.

```json
{"session_id":"session_x","client_turn_id":"turn_x","snapshot_id":"snapshot_x","decision":"recommend|no_trade","reply":"...","message":{},"symbols":[]}
```

If no current snapshot exists, the service returns HTTP `503` with `current_snapshot_unavailable`. Invalid/incomplete current snapshots return grounded `no_trade`; a valid next-session plan may return `decision=recommend` with `message.tradeable=false`. The service never reads legacy book/run JSON, V1/V2 artifacts, a fallback snapshot, or live Serenity evidence during chat.

Snapshot metadata includes `decision_trade_day`, `daybook_effective_day`, `pulse_trade_day`, `pulse_slot_closed_at`, `observed_at`, `market_phase`, `target_mode`, and `pending_eod_day`; `as_of` remains a deprecated read-only alias. Historical explanatory replies include `perspective="historical"`, `is_current=false`, and `tradeable=false`. An existing-session explanation whose live Serenity semantic revision has advanced uses `snapshot_explanation_only` with the same non-tradeable semantics while retaining its bound candidate evidence. A freshness-only poll renewal does not make the snapshot historical. Current/execution requests against an older session snapshot return `no_trade` with `historical_snapshot_not_tradeable`.

If the short 1200 ms SQLite write budget is exhausted, chat returns HTTP `503` with `error.detail.reason="storage_busy"` and `retry_after_ms`. Health and other exact reads wait for the real database for at most 2000 ms, release the read transaction before decoding large JSON, and return the same structured 503 rather than a cached value when the budget is exhausted.

Routing/provider unavailability is `503`; invalid routing after one repair is `502`. A narration draft that fails validation may receive one real-LLM repair attempt; if the repair also fails, or trace integrity fails, the result is `502`. Reusing one `client_turn_id` with different content is `409`. None of these failures commits an assistant turn or binds a new empty session.

## GET /api/chat/{session_id}

Returns the unified persisted turn records for that session only. A missing session is `404`.

## GET /api/health

Reports `product_ready`, exact `readiness_reasons`, the `agent.db` counters/current pointer, sole Market Memory history database path/state, current market-time contract, Serenity target/coverage/worker lease, snapshot/active readiness revisions, snapshot/active semantic revisions, and real-LLM verification. `status=ok` means the immutable snapshot passes native-Alpha integrity, matches the current market-time target, the exact active Serenity target is complete/fresh with a live worker lease, its semantic revision still matches the snapshot, and a two-logical-stage chat was committed within the verification TTL. Health never substitutes a cached or older snapshot. HTTP 200 by itself is only API liveness.

For the Workspace, this response also contains `llm_ready`, `storage`, and
`runtime`. They are UI projections of the exact health, snapshot, and session
state above; `llm_ready` is true only when the shared real-provider verification
is ready.

## Workspace read endpoints

- `GET /api/book/current`: returns the `MarketBook` embedded in the current
  immutable recommendation snapshot, or an empty `book` when no snapshot exists.
- `GET /api/session/{session_id}`: returns persisted turns from `AgentStore`.
  An unseen client-generated session ID is represented as an empty, unpersisted
  session; reading it never creates a database row.
- `GET /api/session/{session_id}/diagnostics`: returns a bounded, redacted
  summary derived from those same turns.
- `GET /api/sessions?limit=20`: returns persisted session titles and previews.

These endpoints are read-only. They do not select symbols, construct a fallback
plan, or invoke a provider.
