# Current Contract Kernel

GP has one recommendation lifecycle.

1. `RecommendationPlan` is the immutable daily decision from the Adaptive Decision Engine. Its identity binds the session, completed daily evidence, complete candidate universe, policy state, and producer revision.
2. `RuntimeObservation` is immutable intraday execution evidence for exactly one plan. It may only report symbols already evaluated by that plan.
3. `RecommendationPublication` is the only product projection. `PublicationService` alone constructs and commits it from a plan plus an optional runtime observation.

`PlanService` resolves the target before selection. A session before or during trading uses the current session and the latest completed daily evidence. After close, a pending daily bar yields an explicit pending state; a completed daily bar targets the next open session. Market phase and polling time never affect plan identity.

The database owns `recommendation_plans`, `runtime_observations`, `recommendation_publications`, `current_publication`, `sessions`, `turns`, and `claims`. Conversation sessions and turns bind `publication_id`.

Public reads are `GET /api/recommendation/current`, `GET /api/conversations`, and `GET /api/conversations/{session_id}`. `DELETE /api/conversations/{session_id}` removes exactly one conversation plus its cascaded turns and claims; it never deletes the bound publication, plan, runtime, or another session. Deleted session IDs are tombstoned so a delayed chat request cannot recreate them. The conversation reads expose canonical `ConversationSession` and ordered `ConversationTurn` records; they do not recreate old Book, diagnostic, or run projections. Health reports publication lineage and each canonical time field. The LLM may route and narrate only publication-bound evidence; it cannot select, rerank, or change values.
