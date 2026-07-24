# Service Contract

The public product routes and their response shapes remain unchanged by lunch reranking.

- `GET /api/recommendation/current` returns the canonical `RecommendationPublication` fields: publication ID, plan ID, optional runtime ID, publication time, decision, candidates and lineage.
- `GET /api/lunch/current` returns market session date, plan/runtime/publication IDs, morning slot close, morning session state, current tradeability and reason codes.
- `GET /api/health` returns current publication lineage, session/evidence/slot dates, market and data states, publication/tradeability states, and product-level Serenity status.
- `POST /api/chat` binds a new session to the current publication or keeps an existing session on its original publication.
- Conversation list, detail and delete routes retain their existing canonical contracts.

Lunch reranking adds no route and no field. A successful 11:30 batch changes which already-valid publication is current. An incomplete batch leaves the prior publication current. A lunch publication is not tradeable because its runtime market gate is deny even when its five-minute data quality is ready.

All writes flow through `PlanService`, `RuntimeService` and `PublicationService`. Public handlers do not collect five-minute network data and do not write SQLite directly.
