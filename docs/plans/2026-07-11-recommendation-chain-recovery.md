# Recommendation Chain Recovery ExecPlan

## Purpose / Big Picture

Restore one trustworthy recommendation chain: every backend service runs the same revision, only compatible Adaptive artifacts may become current, and current recommendation APIs/UI show the same picks. Non-trading periods retain the latest completed daily plan while disabling immediate execution.

## Progress

- [x] 2026-07-11: Confirmed a stale `gp-rebuild-daybook` image wrote a legacy risk-committee empty artifact over the Adaptive current state.
- [x] Make every Python Compose service use one tagged backend image and expose producer revision/schema/policy metadata.
- [x] Validate and atomically publish daybook, slot artifact, and current pointer; reject incompatible producers.
- [x] Serve parameterless `recommend_v2` from the current canonical book while preserving explicit historical lookup.
- [x] Preserve valid daily picks during non-trading and label them as next-session review plans.
- [x] Rebuild all profiles, repair current state, and verify API/Web/chat.

## Surprises & Discoveries

- Compose assigned distinct images to services sharing the same build block; rebuilding API/worker did not rebuild ops.
- Parameterless `recommend_v2` reads a separate stale `latest_v2.json` rather than current book.
- A display fallback could mask a corrupt current pointer; canonical routes now fail unavailable until repair instead of presenting fallback data as current.
- Serenity absence grounding initially confused general risk language with announcement claims; the check now activates only when Serenity/news/announcement evidence is explicitly mentioned.

## Decision Log

- Use one shared backend image for all Python services.
- Treat current canonical book/run as the default recommendation source; retain explicit historical lookup.
- Preserve original non-trading behavior: plans remain visible while execution remains disabled.

## Outcomes & Retrospective

The current book and default recommendation API now expose the same 10 Adaptive candidates for 2026-07-10. Non-trading plans remain visible with execution disabled. All Python services use one image digest, guarded ops repair succeeds, complete backend/frontend tests pass, and the two-turn chat flow is restored. Serenity remains non-binding at 0%; its existing suspension was preserved rather than bypassed.

## Context and Orientation

Compose service images are defined in `docker-compose.yml`. Daybook and pointer persistence lives in `book/repo.py` and `worker.py`. Current HTTP recommendation views live in `gateway/routes.py` and `kernel/facade.py`.

## Plan of Work

1. Share one backend image and add build identity.
2. Add producer metadata, validation, atomic JSON writes, and current-pointer compatibility checks.
3. Adapt current canonical book to the V2 response for unparameterized requests.
4. Restore current state with the new image and verify non-trading presentation.

## Concrete Steps

- Update Compose/build metadata and CLI preflight.
- Extend artifact contracts without breaking existing readers.
- Guard all current publication paths and startup reads.
- Add backend/frontend regression tests and operational documentation.

## Validation and Acceptance

- Compileall, complete pytest, frontend lint/typecheck/tests/build.
- Compose config across default, ops, experiments, and bootstrap profiles.
- Identical image IDs for all Python services.
- Health, current book, current/historical recommendation, repair, Web Top symbols, and two-turn chat checks.
- Current 2026-07-10 plan is non-empty; non-trading disables immediate execution without removing picks.

## Idempotence and Recovery

Writes remain versioned and current pointer changes only after validation. Failed repair leaves the prior pointer intact and reports unavailable/degraded. Rollback uses the prior Git commit and one shared-image rebuild; runtime data is never deleted.

## Artifacts and Notes

Do not stage `store/`, `cache/`, `results/`, databases, daybooks, slots, or current pointers.

## Interfaces and Dependencies

No new production dependency. Successful HTTP response compatibility is retained; producer/freshness fields are additive.
