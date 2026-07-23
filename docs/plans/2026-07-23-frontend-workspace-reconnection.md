# Frontend Workspace Reconnection

## Purpose / Big Picture

Restore the former chat-first GP workspace after the Contract Kernel hard cutover replaced it with a minimal publication page. Keep the new immutable `RecommendationPublication`, `RuntimeObservation`, and conversation contracts; do not restore retired Book, Daybook, or diagnostic APIs.

## Progress

- 2026-07-23: Confirmed the old workspace source remains recoverable from local `HEAD`, while its former HTTP dependencies were removed by the hard cutover.
- 2026-07-23: Confirmed the Contract Kernel persists canonical conversation sessions and turns but lacks a current read API for the frontend to reload them.
- 2026-07-23: Added canonical conversation list/detail reads and restored the header, session switcher, full thread, composer, status panel, candidate snapshot, and refresh controls against the current contracts.
- 2026-07-23: Passed `python -m pytest -q tests/contracts` (6 passed), `python -m compileall -q src tests`, manifest, retirement, and diff checks; frontend typecheck, lint, test (1 passed), and production build also passed.
- 2026-07-23: Rebuilt `gp`, `gp-worker`, and `web` from this source. Browser verification confirmed the restored workspace loads without console errors, sends a real LLM-backed chat request, switches to a saved session, and reloads the persisted ordered turns.
- 2026-07-23: Found a stale history lock left by a replaced container. Added conservative expired-lock reclamation and passed the expanded contract suite (7 tests). The rebuilt worker reclaimed and released the real stale lock; no subsequent timeout was logged.

## Surprises & Discoveries

- Reinstating the old files unchanged would make the browser request the retired Book product endpoint, which the Contract Kernel correctly does not expose.

## Decision Log

- Restore the prior workspace interaction and visual structure, but bind each view directly to current publication, health, lunch, and conversation contracts.
- Add narrowly scoped canonical conversation read routes rather than restoring any retired route or compatibility adapter.

## Context and Orientation

- Workspace source: `frontend/src/features/workspace/`.
- Current product routes: `src/gp_assistant/gateway/routes.py`.
- Canonical conversation persistence: `src/gp_assistant/store.py`.

## Plan of Work

1. Expose read-only current conversation session and turn records.
2. Restore the chat-first workspace, session switching, full thread, status header, and decision snapshot against new contracts.
3. Test the frontend and new routes, then rebuild the existing Compose services and verify a real chat flow.

## Concrete Steps

- Do not recreate the retired Book, diagnostics, or operations routes.
- Preserve existing user runtime data; schema additions are not required for the read routes.

## Validation and Acceptance

Executed: backend route tests, frontend lint/typecheck/test/build, contract enforcement, Compose rebuild of `gp`, `gp-worker`, and `web`, HTTP checks, and browser verification. The browser rendered the restored workspace and all key controls, produced an actual LLM answer grounded in the current 2026-07-22 daily evidence, and preserved that conversation across reload.

## Idempotence and Recovery

- The workspace only reads canonical records and sends the existing idempotent client turn identifier.
- Rollback is restoring the current minimal `frontend/src/app/App.tsx`; canonical persisted conversation records are unchanged.

## Artifacts and Notes

- This corrective plan supersedes only the hard-cutover frontend replacement, not the Contract Kernel data model.

## Interfaces and Dependencies

- `GET /api/recommendation/current`, `GET /api/health`, `GET /api/lunch/current`, and `POST /api/chat` remain authoritative.
- New conversation reads must return `ConversationSession` and ordered `ConversationTurn` records only.

## Outcomes & Retrospective

Completed. The former functional workspace is reconnected to current Contract Kernel contracts rather than retired API names. The intentionally unavailable retired diagnostic projection was not restored; its former API has no canonical equivalent and is not part of the user-facing recommendation journey.
