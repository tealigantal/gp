# 0006 — Single assistant-turn presentation contract

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

The single-protocol chat writer persisted a real LLM reply in turn `content` and
payload `reply`, while Workspace rendering expected a separate
`message.narrative_text`. The restored Workspace read endpoint passed the raw
payload through, so an otherwise successful ordinary chat could render a blank
assistant body. This was a cross-layer protocol mismatch, not a provider or
selection failure.

## Considered Options

1. Patch `ChatThread` alone to read `turn.content`.
2. Migrate or rewrite every stored session row.
3. Define one server-side assistant-turn presentation contract and make all
   writer/replay/read paths use it; let the UI render its guaranteed text and
   make corrupt legacy data explicit.

## Decision

`src/gp_assistant/contracts/api.py::ChatResponse` is the single canonical
assistant-turn presentation contract. Its `project_persisted` method binds the
already validated, committed `reply` to `message.narrative_text`, preserving
structured metadata and persistence-only trace fields without creating any new
prose.

`AgentStore.commit_turn`, idempotent replay, and `AgentStore.session_turns`
all call this contract. `POST /api/chat`, `GET /api/chat/{session_id}`, and
`GET /api/session/{session_id}` therefore expose the same renderable assistant
turn. The frontend treats the persisted `content` as a defensive rendering
fallback only; malformed structured metadata is shown as its real text, and a
truly empty corrupt record is an explicit warning rather than a blank answer.

## Rationale

The LLM must have one authoritative user-visible body after validation and
commit. Duplicating that body across unrelated assembler, storage, route, and
component conventions permits silent loss. A projection avoids a destructive
database rewrite while retaining old conversation visibility.

## Consequences

- New turns persist `message.narrative_text` exactly equal to `reply`.
- Existing non-empty turns gain that field at read time without changing the
  database schema or historical content.
- Empty assistant content is rejected before a new turn commits; legacy corrupt
  content is observable as an error state.
- LLM routing, narration, numeric authority validation, selection, and Serenity
  shadow/weight policy are unchanged.

## Migration

No migration is needed. Read-time projection provides compatibility, and new
writes converge naturally to the canonical shape.

## Rollback

Reverting the contract code restores the former raw payload behavior, but may
reintroduce blank Workspace replies for ordinary chat turns. Runtime stores are
not modified by this decision.
