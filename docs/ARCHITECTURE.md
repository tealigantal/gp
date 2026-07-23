# Architecture

The decision pipeline normalizes provider data at explicit adapters, applies Signal, Market Memory, Probability, Risk, Adaptive, and Serenity evidence, and emits a typed plan commit command. `PlanService`, `RuntimeService`, and `PublicationService` own the only application write path. The storage boundary verifies schema identity before any normal operation.

The browser is a read-and-converse projection served by Nginx. It consumes only current publication, health, canonical conversation list/detail, and chat routes. Browser state may optimistically display the user's pending turn, but the ordered persisted `ConversationTurn` records replace it after the response. Candidate filtering is limited to displaying `disposition=selected` entries in their existing engine order; no selection, ranking, scoring, or execution decision exists in frontend code.

The browser atomically accepts health and current-publication reads only when their publication IDs match, with one bounded retry for pointer rollover. Chat responses never overwrite the current-publication state. Their bound publication supplies an in-memory, trusted publication-to-plan lineage hint for the active session; browser storage is not a source of truth. Unknown or different-plan sessions remain isolated from the current candidate panel.

Conversation deletion is a narrow lifecycle operation. The store deletes one `sessions` row by primary key; foreign keys cascade only to that session's `turns` and `claims`. A `deleted_sessions` tombstone prevents delayed or retried chat requests from recreating the same session ID. The browser invalidates stale list reads after deletion and filters tombstoned IDs from concurrent responses, while the current publication state remains independent.

Compose contains the core `gp`, `gp-worker`, and `web` services. API and web health checks make startup readiness observable, and worker/web startup waits for API health. Nginx proxies `/api/` to `gp:8000` and serves the single-page application for all other paths.
