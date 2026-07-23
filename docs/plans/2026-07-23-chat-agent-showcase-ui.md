# Chat Agent Showcase UI

## Purpose / Big Picture

Deliver a polished, minimal, chat-first frontend for GP and make the core product runnable with one `docker compose up`. The interface must expose the current immutable `RecommendationPublication` and canonical conversation records without restoring any retired product or diagnostic contract.

## Progress

- 2026-07-23: Classified the repository as an initialized important project and this work as a cross-layer, real-user product task.
- 2026-07-23: Confirmed the current worktree is in the Contract Kernel hard cutover: the former frontend is deleted, the canonical conversation read routes exist, and Compose still points at the missing frontend build context.
- 2026-07-23: Selected a three-pane chat workspace: conversation history, primary chat, and a publication-bound decision brief. Mobile layouts collapse into one readable flow.
- 2026-07-23: Implemented the responsive workspace, canonical API client, failure-closed states, focused interaction tests, production Nginx image, and Compose health/dependency ordering.
- 2026-07-23: Frontend checks, current contract checks, production image build, one-command Compose startup, HTTP smoke, and automated browser verification passed. A real chat was persisted and restored after reload with no captured console errors.
- 2026-07-23: Independent review identified five frontend state/interaction blockers. Fixed historical-publication isolation, stale polling failure closure, idempotent retry identity, Chinese IME Enter handling, and mobile history access; expanded the frontend suite from two to six tests and verified the final web image without touching backend services.
- 2026-07-23: Final idempotency recheck tightened new-chat behavior: the browser now creates the session identity before its first request and reuses both session and client-turn identities after an uncertain failure.
- 2026-07-23: Repaired runtime-publication churn handling without changing backend code. The browser now keeps current and conversation-bound publications separate, compares trusted plan lineage instead of raw publication identity, retries crossed health/publication reads, and protects overlapping refresh and conversation requests.
- 2026-07-23: Added confirmed per-conversation deletion. The API deletes one session with cascaded turns/claims, tombstones its ID against late chat resurrection, and preserves recommendation artifacts. The sidebar supports desktop and 44 px mobile delete targets, active-session reset, stale-list suppression, and accessible completion announcements.

## Surprises & Discoveries

- The existing workspace-reconnection plan reports a completed browser validation, but the current working tree contains no `frontend/` files and no running `web` service. Current filesystem and runtime state take precedence over that stale completion note.
- The runtime worker creates a new publication about once per minute even when the immutable daily plan is unchanged. A raw publication-ID comparison therefore marked a fresh session historical. Existing conversation reads do not expose their bound publication payload or plan ID, so an unknown lineage must remain explicitly unknown and fail closed until a trusted chat response supplies it.

## Decision Log

- Build directly on `GET /api/recommendation/current`, `GET /api/health`, `GET /api/conversations`, `GET /api/conversations/{session_id}`, and `POST /api/chat`.
- Keep the UI intentionally informational: browser refresh synchronizes canonical state but does not launch market collection or change recommendation authority.
- Use system fonts and local SVG/CSS decoration only; do not add a new production UI dependency.
- Keep `currentPublication` owned only by the consistent health/current-publication poll. A chat response records trusted `publication_id -> plan_id` lineage for its session but never replaces the current decision panel.
- Treat same-plan runtime changes as a current execution-state update, not a historical decision. Treat unknown or confirmed-different lineage as isolated; browser persistence is not an authority source.
- Make deletion win over delayed chat and list operations: a deleted session ID cannot be recreated, stale list responses cannot reinsert its card, and deleting one session cannot clear a newly selected different session.

## Context and Orientation

- Frontend: `frontend/`.
- Canonical API: `src/gp_assistant/gateway/routes.py`.
- Product contracts: `src/gp_assistant/contracts/` and `docs/contracts/`.
- Container topology: `docker-compose.yml`, root `Dockerfile`, and `frontend/Dockerfile`.

## Plan of Work

1. Recreate the frontend build, API types/client, chat state, publication panel, and responsive styling against current contracts.
2. Add focused component/state tests and restore the production Nginx image.
3. Add Compose health checks and service dependency ordering for the API and web UI.
4. Run frontend, backend, contract, Compose, container, HTTP, and browser validation.
5. Record executed evidence and any remaining operational limitations.

## Concrete Steps

- Preserve all unrelated Contract Kernel changes and runtime data.
- Generate `package-lock.json` from the checked-in `package.json` using npm.
- Rebuild only the project services; do not use `--remove-orphans` or restart Docker Desktop.

## Validation and Acceptance

- `npm run lint`, `npm run typecheck`, `npm test -- --run`, and `npm run build` pass in `frontend/`.
- Backend compile/tests and contract enforcement pass.
- `docker compose config --quiet` passes and plain `docker compose up -d --build` leaves `gp`, `gp-worker`, and `web` running, with API and web healthy.
- The browser loads at `http://127.0.0.1:8080`, has no console errors, renders canonical recommendation facts, sends a real chat turn, and reloads the saved conversation.
- A conversation bound to an older runtime publication of the same plan remains usable after the current publication advances; it shows the latest execution state without displaying the false historical warning or raw backend reason codes.
- Deleting a disposable real conversation removes its card, survives a full page reload, returns 404 on later reads, rejects a late same-ID chat with `conversation_deleted`, and leaves all pre-existing conversations and recommendation artifacts intact.

## Idempotence and Recovery

- Re-running npm build and Compose build/up is safe and does not mutate recommendation records by itself.
- Chat retries use a stable per-submit `client_turn_id`; the backend remains the idempotency authority.
- Rollback is limited to the new frontend and Compose health/dependency changes; canonical storage is unchanged.

## Interfaces and Dependencies

- The Adaptive Decision Engine remains the only stock-selection authority.
- The LLM only narrates publication-bound evidence and may not add, delete, or rerank candidates.
- No new external service, paid source, secret, public API break, or deployment is introduced.

## Outcomes & Retrospective

Completed. GP now has a restrained chat-first product surface and a reproducible core Compose startup. The browser keeps conversation primary while exposing only the selected slice of the immutable publication in engine-provided order. Current state and conversation-bound state remain separate, while trusted plan lineage prevents runtime-only publication churn from masquerading as a historical decision. Windows-to-Alpine lockfile gaps for native build bindings were made explicit after the first container build revealed them.

The browser run also observed an existing narration-quality risk: when a candidate's canonical `name` equals its stock code, the current backend may infer a company name in prose. Per the user's scope boundary, no backend source or test change was retained for this frontend task.
