# Single-Protocol Service Contract

Only three public endpoints exist.

## POST /api/chat

```json
{"session_id":"optional","client_turn_id":"required-idempotency-key","message":"给我当前候选"}
```

`message` and `client_turn_id` are required. A new session binds to the current valid `RecommendationSnapshot.v1`; every later turn in that session uses the same immutable snapshot. Retrying the same `client_turn_id` returns the already committed assistant turn without another write.

```json
{"session_id":"session_x","client_turn_id":"turn_x","snapshot_id":"snapshot_x","decision":"recommend|no_trade","reply":"...","message":{},"symbols":[]}
```

If no valid current snapshot exists, the response is structured `no_trade`. The service never reads legacy book/run JSON, V1/V2 artifacts, historical sessions, or a fallback snapshot.

## GET /api/chat/{session_id}

Returns the unified persisted turn records for that session only. A missing session is `404`.

## GET /api/health

Reports the `agent.db` counters/current pointer, the sole Market Memory history database path/state, and the worker publisher name. It exposes no operational repair, execution, validation, Workbench or legacy artifact information.
