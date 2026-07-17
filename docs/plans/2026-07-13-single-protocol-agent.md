# Single-Protocol Recommendation Chat Agent ExecPlan

## Purpose / Big Picture

Reduce GP to one chat-first recommendation product: the worker publishes immutable `RecommendationSnapshot.v1` records into `agent.db`; chat turns bind exactly one snapshot and commit atomically; no old recommendation, execution, or operations interface survives.

## Progress

- [x] 2026-07-13: Audited real stores and found divergent current-book, V1/V2 recommendation artifacts, split history databases, and non-atomic conversation writes.
- [x] Define `agent.db` schema, snapshot projection, and transactional chat store.
- [x] Move worker publication and chat retrieval to the new store.
- [x] Remove public legacy HTTP/UI/CLI/product paths and old runtime stores after new-path validation.
- [x] Refactor Compose to the three-service protocol and audit core-engine database inputs/output fields.

## Surprises & Discoveries

- Current source revision guards reject the persisted current book despite an unchanged runtime schema; source digests cannot remain a read-compatibility condition.
- Docker reads `history-clean.db` while freshness audit hard-coded `history.db`.

## Decision Log

- The user authorized destructive removal of old conversations and legacy runtime data after integrity-gated cutover.
- No V1/V2 conversion, compatibility adapter, or runtime fallback will be retained.
- `history-clean.db` becomes the single history database after integrity validation.

## Context and Orientation

The current product writes conversations through `memory/`, recommendation artifacts through Book/Run JSON plus legacy V2 files, and exposes many routes from `gateway/routes.py`. The new core replaces the product-facing portions with `agent.db`; Market Memory remains internal selection evidence.

## Plan of Work

1. Add strict migrations, immutable snapshots, a single current pointer, and transactional turn commits.
2. Publish the worker's validated selection as `RecommendationSnapshot.v1`; make chat consume only that store.
3. Retain only chat, chat-history, and health routes/UI calls.
4. Verify integrity, then delete legacy data and dead product code. Completed 2026-07-13: legacy Docker services stopped; `history-clean.db` integrity-gated and promoted to `history.db`; `gateway.db`, book/run/recommend/portfolio/validation/cache artifacts and old frontend surfaces were physically removed. The new production `agent.db` was initialized at schema version 1 and intentionally has no snapshot until the rebuilt worker completes a validated publication.

## Validation and Acceptance

- Migration/version mismatch, snapshot hash, foreign-key, immutability, idempotent turn, concurrent same-session, and no-trade tests pass.
- Worker publication, chat recommendation, follow-up, comparison, exit question, and history restore use only `agent.db`.
- No production import or route accesses V1/V2 artifact, Book/Run HTTP, Workbench, portfolio, or ops paths.
- One history resolver is used by runtime, freshness audit, and replay.

## Idempotence and Recovery

Schema initialization and worker publication are repeatable. A duplicate client turn returns its committed response. Any invalid snapshot or migration state stops chat recommendation with an explicit error/no-trade result; no old source is read. Legacy deletion runs only after all integrity checks and is scoped to the explicitly named runtime paths.

## Artifacts and Notes

The existing user-modified `store/book/current_slot.json` was removed only during the verified deletion phase, as required by the approved cutover. Do not stage runtime data.

## Interfaces and Dependencies

Public product routes become `POST /api/chat`, `GET /api/chat/{session_id}`, and `GET /api/health`. `client_turn_id` is required for a mutation-safe chat request.
