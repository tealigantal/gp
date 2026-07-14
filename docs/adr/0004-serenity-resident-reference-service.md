# ADR 0004 — Serenity resident reference service

- **Status:** Superseded by ADR 0005 for ranking authority; retained for the resident-service topology
- **Date:** 2026-07-13

## Context

Serenity Alpha was introduced as a profile-gated forward experiment. That made
official-evidence collection optional and operationally easy to forget, while
its historical automatic-promotion design made the word `auto` unsafe as a
normal deployment default.

## Decision

Run Serenity as a normal `serenity` service in the default Docker Compose
topology. Its default mode is `reference`: it collects, verifies, versions, and
persists official evidence and exposes its health, but contributes zero to the
recommendation decision engine. `off` remains a deliberate operator kill
switch. The legacy `auto` setting is accepted only as a compatibility alias for
`reference`.

No automatic promotion from evidence collection to ranking authority is
permitted by this service. Any future ranking integration requires a new
explicit product decision, an architecture update, and fresh causal validation.

## Consequences

- `docker compose up -d` includes API, worker, web, and Serenity.
- Serenity failures are isolated from the core recommendation chain.
- Historical shadow/probation/active policy records remain readable evidence
  but cannot raise the applied decision weight under the default configuration.
- Operators can disable only Serenity with `GP_SERENITY_MODE=off`.

## Rollback

Set `GP_SERENITY_MODE=off` to stop useful collection behavior while retaining
the service topology, or explicitly stop/remove the `serenity` service during
an operator-approved rollback. Neither action changes stored recommendation
snapshots.
