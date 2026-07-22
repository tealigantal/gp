# Single-Protocol Service Contract

The product API has one immutable chat/write protocol and a small Workspace
read model. The read model is derived from the same `AgentStore` snapshot and
turn records; it does not restore the retired book/run JSON authority.

## Contract Ownership

Each runtime-facing contract category has exactly one authoritative source:

- HTTP models and committed assistant-turn presentation:
  `src/gp_assistant/contracts/api.py`.
- LLM semantic routing labels: `src/gp_assistant/contracts/intents.py`.
- Resident worker operations: `src/gp_assistant/contracts/runtime.py`.
- Market-time identity and snapshot comparison:
  `src/gp_assistant/runtime/market_time.py`.
- Daily-freshness report projection:
  `src/gp_assistant/evidence/daily_freshness.py`.
- Full-market candidate-universe contract and immutable storage:
  `src/gp_assistant/evidence/market_universe.py`.
- Persisted product/domain objects: `src/gp_assistant/contracts/objects.py`.
- Produced-artifact identity: `src/gp_assistant/runtime/producer.py`.

No layer may silently translate retired labels. Intent routing accepts only the
current request and freshness literals; a provider response using an obsolete
value receives the existing real-LLM repair attempt and otherwise fails closed.
The worker accepts only `auto`, `rebuild_daybook`, and
`postclose_archive`; its only resident command is `runtime-loop`.
Market-time serialization contains canonical named fields only. The
daily-freshness module is the explicit boundary that projects those fields
into the durable report keys such as `target_day`.

## POST /api/chat

```json
{"session_id":"optional","client_turn_id":"required-idempotency-key","message":"给我当前候选"}
```

`message` and `client_turn_id` are required. A new session binds to the current valid `RecommendationSnapshot.v1`; every later turn in that session uses the same immutable snapshot. Retrying the same `client_turn_id` returns the already committed assistant turn without another write. Each successful new turn has two required logical provider stages: routing must contain a valid `intent_routing` result (optionally after `intent_routing_repair`), and narration must contain `tool_evidence`. The temporary post-generation narration validation and `tool_evidence_repair` stage are disabled; the immutable snapshot remains the source of the structured decision and trading fields. Every provider call required by the committed turn must have a 2xx status, request/response model and provider response ID.

```json
{"session_id":"session_x","client_turn_id":"turn_x","snapshot_id":"snapshot_x","decision":"recommend|no_trade","reply":"...","message":{"message_kind":"...","narrative_text":"..."},"symbols":[]}
```

`src/gp_assistant/contracts/api.py::ChatResponse` is the sole assistant-turn
presentation contract. On every committed response,
`message.narrative_text` is required and exactly equals the validated `reply`;
it is not independently generated prose. The same contract is applied before
write, to idempotent replay, and to persisted-turn reads. Old non-empty rows
are projected at read time from their committed `content` without a database
migration. A new empty assistant body is rejected before commit, and a corrupt
historical empty body is an explicit UI warning rather than a blank answer.

If no current snapshot exists, the service returns HTTP `503` with `current_snapshot_unavailable`. Invalid/incomplete current snapshots return grounded `no_trade`; a valid next-session plan may return `decision=recommend` with `message.tradeable=false`. A recommendation snapshot binds a `MarketUniverseSnapshot.v1` summary and universe ID. A legacy snapshot without that contract is `legacy_coverage_unverified`: it remains readable as historical audit data but cannot be current/tradeable. The service never reads legacy book/run JSON, V1/V2 artifacts, a fallback snapshot, or live Serenity evidence during chat.

Snapshot metadata includes `decision_trade_day`, `daybook_effective_day`, `pulse_trade_day`, `pulse_slot_closed_at`, `observed_at`, `market_phase`, `target_mode`, and `pending_eod_day`; `as_of` remains a deprecated read-only alias. Historical explanatory replies include `perspective="historical"`, `is_current=false`, and `tradeable=false`. An existing-session explanation whose live Serenity semantic revision has advanced uses `snapshot_explanation_only` with the same non-tradeable semantics while retaining its bound candidate evidence. A freshness-only poll renewal does not make the snapshot historical. Current/execution requests against an older session snapshot return `no_trade` with `historical_snapshot_not_tradeable`.

If the short 1200 ms SQLite write budget is exhausted, chat returns HTTP `503` with `error.detail.reason="storage_busy"` and `retry_after_ms`. Health and other exact reads wait for the real database for at most 2000 ms, release the read transaction before decoding large JSON, and return the same structured 503 rather than a cached value when the budget is exhausted.

Routing/provider unavailability is `503`; invalid routing after one repair is `502`. Narration no longer has a post-generation validation or repair failure path while that temporary layer is disabled. Reusing one `client_turn_id` with different content is `409`. None of these failures commits an assistant turn or binds a new empty session.

## GET /api/chat/{session_id}

Returns the unified persisted turn records for that session only, using the
same assistant-turn presentation contract as `POST /api/chat`. A missing
session is `404`.

## GET /api/health

Reports `product_ready`, exact `readiness_reasons`, the `agent.db` counters/current pointer, full-market `candidate_universe` counts/coverage/blockers, sole Market Memory history database path/state, current market-time contract, Serenity target/coverage/worker lease and effective weight, and real-LLM verification. `status=ok` requires a complete, date-matched, non-fallback universe plus a valid immutable snapshot, market-time binding, gate and verified real LLM. Serenity unavailability is valid when its batch effective weight is zero; a stale binding can block only a snapshot that actually applied a non-zero add-on. Health never substitutes a cached or older snapshot. HTTP 200 by itself is only API liveness.

## GET /api/lunch/current

Returns `LunchResponse` (`lunch_snapshot.v1`), a dedicated morning-session read model. It never represents daily completion and always returns `daily.today_complete=false`. During `LUNCH_BREAK`, `state=READY` means the exact morning target slot (normally 11:30) is present, belongs to the target trade day, and has `slot_status=OK`; the only permitted completion wording is for the morning session. Outside the lunch break it returns HTTP 200 with `state=NOT_APPLICABLE`, so polling does not turn an ordinary market phase into an error. `/api/book/current` remains the unchanged daily-plan/full-snapshot interface.

For the Workspace, this response also contains `llm_ready`, `llm_retryable`,
`storage`, and `runtime`. They are UI projections of the exact health,
snapshot, and session state above. `llm_ready` is true only after a shared,
recent, fully validated real-provider product chat commits. `llm_retryable` is
true when the real provider is configured and the user may submit the next
normal chat request. A rejected narration leaves `llm_ready=false` because no
answer committed, but keeps `llm_retryable=true`; the rejected text is neither
shown nor persisted, no hidden probe is sent, and the next request still uses
the real LLM. A missing provider configuration makes both fields false.

## Workspace read endpoints

- `GET /api/book/current`: returns the `MarketBook` embedded in the current
  immutable recommendation snapshot, including independent
  `candidate_universe` / `universe_quality` summaries, or an empty `book` when
  no snapshot exists.
- `GET /api/session/{session_id}`: returns persisted turns from `AgentStore`
  using the same assistant-turn presentation contract as write/replay.
  An unseen client-generated session ID is represented as an empty, unpersisted
  session; reading it never creates a database row.
- `GET /api/session/{session_id}/diagnostics`: returns a bounded, redacted
  summary derived from those same turns.
- `GET /api/sessions?limit=20`: returns persisted session titles and previews.

These endpoints are read-only. They do not select symbols, construct a fallback
plan, or invoke a provider.
