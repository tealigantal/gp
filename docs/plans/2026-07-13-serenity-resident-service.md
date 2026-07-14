# Serenity Resident Reference Service ExecPlan

## Purpose

Make Serenity Alpha a normal, always-started official-evidence service: a plain
`docker compose up -d` starts collection alongside the API, recommendation
worker, and web UI. Serenity remains reference-only; it must never alter
selection, scores, prices, or actions without a separate, explicit product
decision backed by new validation.

## Progress

- [x] Inspect the current Compose topology, runtime entry point, and policy
  modes.
- [x] Make `reference` the default Serenity mode and safely map the legacy
  `auto` setting to it.
- [x] Add the resident `serenity` Compose service with the shared backend image.
- [x] Add regression coverage and validate the rendered Compose configuration.
- [x] Record the operating decision in architecture, product, ADR, progress,
  validation, and debt documentation.
- [x] Diagnose the blocked backend image build as an obsolete hard-coded
  `host.docker.internal:7890` proxy default.
- [x] Refactor Compose so `api` alone builds the shared backend image; worker
  and Serenity only consume it.
- [x] Make a recreated Serenity service wait for an existing persisted worker
  lease instead of entering a restart loop.
- [x] Rebuild the backend image without a proxy fallback and recreate the
  resident Compose services.

## Execution Plan

1. Keep collection, verification, persistence, and health reporting active in
   `reference` mode, but retain the decision engine's zero contribution.
2. Start the service without a Compose profile, after the healthy API, with a
   restart policy suitable for a long-running local service.
3. Preserve `off` as an operator kill switch. Treat legacy `auto` as a
   compatibility alias for `reference`, not an automatic promotion path.
4. Add configuration and Compose regression tests, then run the default Python
   suite, compilation, Compose validation, and whitespace checks.
5. Keep proxy selection an explicit build input; verify the rebuilt service set
   against the real Docker engine.

## Decision Record

- The resident service is an operational evidence collector, not an experiment
  that can silently become ranking authority.
- A source failure degrades Serenity evidence only. The base recommendation
  chain remains independent and fail-closed on its own required market data.
- Existing historical shadow/promotion results remain historical evidence; they
  do not authorize automatic ranking influence in the resident service.

## Validation Record

Passed `python -m compileall -q src tests`, default `python -m pytest -q`,
`docker compose config --quiet`, rendered-service inspection, and
`git diff --check`. The backend rebuilt with empty proxy build arguments and
the four resident services were recreated. Serenity stayed alive through the
previous lease expiry, acquired its own lease, and completed a real polling
attempt. No container is started by this plan outside the user-authorized
rebuild operation.
