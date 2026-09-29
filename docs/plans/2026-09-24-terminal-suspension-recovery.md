# Terminal suspension recovery

## Purpose / Big Picture
Restore native current recommendation generation when an issuer has explicitly stopped trading until delisting. Preserve the full frozen raw universe, immutable plans, strict coverage and ordinary suspension bounds. User authorized repair and local container rebuild on 2026-09-24; no commit or push is authorized.

## Progress
- 2026-09-24: read-only diagnosis confirmed 601059/601198 evidence is parsed but expires after five sessions. September 21 succeeds; September 22/23 fail with session_limit_exceeded. Latest publication is September 22. Implementation and deployment pending at initial diagnosis.

- 2026-09-24 08:56: final local default suite passed 224 tests. Compile, selection self-check, manifest, retired checks and Compose validation passed. Final image resolves both real September 23 terminal notices; isolated real LLM API answered correctly on the old expired plan. Deployment pending independent review and final image fixture checks.

- 2026-09-24 08:58: deployed final image to gp/gp-worker after real-PDF and isolated real-LLM acceptance; 199 Python source hashes match both containers and workspace. Independent review blocker closed. Image suite: 221 passed initially, three missing-fixture failures resolved by mounting docs/reports and running their 22-test modules (all passed). Existing web remains healthy. Native scheduled retry/publication pending.

- 2026-09-24 09:01:56: native daily worker completed September 23: raw=3052, expected/fetched=3046, five official suspensions plus one trusted-no-trade, no provider-failure exclusions. Both repaired symbols bind v4 terminal facts. Source is reconstructed_current_universe:akshare:sina, approximate=true, fallback=false, stale=false. At 09:04 memory maintenance reached 600/3052; publication still properly gated on completion.

- 2026-09-24 09:12:32: mature memory atomically completed all 3052 symbols. At 09:13:27 native worker published plan_dc0aa356cf5ed5f421824276 / publication_244cd88cd011afd5690a358d for September 24 using September 23 evidence. Scored=199, selected=3 (002046/002913/605058). Nginx real chat returned 200 with correct dates, candidates and preopen non-execution; UI agreed. Disposable session cleanup returned 204. All 87 prior plans, 5033 publications and 4951 runtime payload hashes were preserved.

## Surprises & Discoveries
- Both API and worker match workspace source. This is a policy modelling defect, not an old image.
- An attempted pytest verbosity override removed the repository basetemp setting and failed before tests with Windows temporary-directory PermissionError. Restored the repository command; no code or assertion was weakened. The first isolated image suite passed 221 tests and failed three due to unmounted docs/reports fixtures; those fixture-dependent modules are being checked with read-only mounts.
- Independent review found title-only withdrawal checks insufficient; body cancellation/delisting regressions were added and passed.
- A new indefinite fact alone is insufficient: the ten-session discovery window would later lose its source notice.
- Existing reports/fixed-score-scale-20260919/README.md modification belongs to the user and is outside scope.

## Decision Log
- Represent an affirmative issuer-bound dated halt until delisting separately. Ordinary five/ten-session and conditional-resumption bounds remain unchanged.
- Previous verified terminal evidence may extend discovery to its source publication. It is only a discovery anchor: fetch the complete interval and reverify documents and conflicts for each target. No direct reuse of historical exclusions.
- Keep existing HTTP temporal projection semantics and scheduling windows. Do not broaden this repair to a public API change or general retry-system redesign.

## Outcomes & Retrospective
Completed implementation, tests, final-image real-source acceptance, local deployment and native user-flow recovery. Current plan remains observe-only and preopen unavailable; Serenity is correctly atomic zero in the verified publication because its matching batch was unavailable. No claim of intraday execution or return performance. Historical August 21/002155 backlog remains outside this repair; cold-start discovery outside the default window without an anchor remains fail-closed. No commit or push.

## Context and Orientation
application/suspension_facts.py parses facts; official_suspension.py resolves verified pre-open disclosures; market_runs.py owns operational evidence; market_orchestrator.py collects in the isolated child. No collection enters chat or selection. Active runtime uses the external Linux volume; host store remains untouched.

## Plan of Work
1. Add terminal semantics, persisted discovery anchors and focused positive/negative regressions.
2. Update current policy documentation, execute backend and contract gates, preserve old plan/publication hashes.
3. Build a separate backend image; verify isolated real-PDF resolution and real narration before replacing shared-image services.
4. Deploy API/worker, observe native completion and publication, verify nginx/current/health/chat, update evidence.

## Concrete Steps
Run python -m pytest -q, compileall, selection self-check, contract manifest --check and retired-symbol checks with isolated storage. Validate Compose with config --quiet. Build with a separate GP_BACKEND_TAG, retain the old image, and recreate only gp/gp-worker after acceptance.

## Validation and Acceptance
Test sessions 5/6/7 and beyond ten sessions, issuer/conditional/negated text, later resume and unreadable correction, incomplete discovery and as-of anchors. Live acceptance must record raw/expected/fetched/excluded counts, evidence provenance, approximation, plan dates, selected/scored counts, actual LLM response and immutable old artifact hashes. Health alone is not success. No trading-window bypass if work finishes after 09:30.

## Idempotence and Recovery
Use existing operational JSON and no schema migration. Every target revalidates source and conflicts. Historical completed runs/plans are unchanged. Retain old image for code rollback; do not restore an old database over new user data. Provider/discovery failures remain explicit retries. Cold-start terminal evidence outside discovery without a verified anchor stays unavailable.

## Artifacts and Notes
Diagnostics and verification artifacts are under results/terminal-suspension-20260924, never staged. Preserve runtime and unrelated data.

## Interfaces and Dependencies
Only the existing collector/ledger interface gains a discovery-anchor argument. No dependency, selection/scoring, LLM, frontend, public API or deployment-topology change.
