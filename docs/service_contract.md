# Service Contract

The public product routes and their response shapes remain unchanged by lunch reranking.

- `GET /api/recommendation/current` returns the canonical `RecommendationPublication` fields: publication ID, plan ID, optional runtime ID, publication time, decision, candidates and lineage.
- `GET /api/lunch/current` returns market session date, plan/runtime/publication IDs, morning slot close, morning session state, current tradeability and reason codes.
- `GET /api/health` returns current publication lineage, session/evidence/slot dates, historical runtime market/data/tradeability states, product-level Serenity status, read-only `market_recovery`, `market_now`, and `next_plan_target`. `market_now` is the server-clock authority for the current publication's observation time, market phase, plan relation and execution permission. `next_plan_target` independently returns the target session, required daily-evidence date, coverage/retry state and whether that target has been published. Its `ready_to_publish` state means the evidence is complete while no new publication exists; consumers must identify any currently displayed candidates as the prior complete plan. The worker may create that next-session plan after 15:20 through the target session's 09:30, including after an overnight recovery. Public consumers must not treat historical runtime fields as “now” or infer tomorrow's plan from an expired current publication.
- `POST /api/chat` binds a new session to the current publication or keeps an existing session on its original publication.
- Conversation list, detail and delete routes retain their existing canonical contracts.

Lunch reranking adds no route and no field. A successful 11:30 batch changes which already-valid publication is current. An incomplete batch leaves the prior publication current. A lunch publication is not tradeable because its runtime market gate is deny even when its five-minute data quality is ready.

All writes flow through `PlanService`, `RuntimeService` and `PublicationService`. Public handlers do not collect five-minute network data and do not write SQLite directly.
