# Storage recovery and historical score analysis

## Purpose / Big Picture
Restore the interrupted history database and make worker recovery failures observable and retryable. Explain historical score concentration without changing selection or scores.

## Context and Orientation
On 2026-09-14 16:56:16 Shanghai time, worker commit and /app/store access failed with I/O errors. history.db retained a hot rollback journal. Read-only coverage scans then failed with SQLITE_READONLY_ROLLBACK. User authorized repair on 2026-09-16; existing conversation_service.py and contract test edits must be preserved.

## Progress
- [x] Diagnosed original commit I/O failure and recurring read-only recovery failure.
- [x] Stopped only gp-worker; copied history database plus journal; verified equal SHA256 values before recovering the copy.
- [x] Isolated copy recovered and PRAGMA integrity_check returned ok.
- [x] Validate worker-owned preflight, error persistence, child supervision and Linux fork signal reset; 64 contract tests pass. Docker stop validation follows.
- [x] Recover live history, deploy affected GP services, verify resumed daily recovery and real chat; strict coverage limitations recorded below.
- [x] Record historical score analysis in docs/historical_score_distribution_20260916.md; no formula changes.

## Surprises & Discoveries
The earliest failure also prevented ledger error persistence. Existing worker supervision did not reconcile nonzero daily-child exits. Docker UI closed 13 seconds earlier, but this does not prove an engine shutdown caused the failure.

## Decision Log
Keep the existing volume topology during this repair; a database volume migration is a separate deployment decision. Let SQLite perform rollback; never remove journal files manually. Preserve the production candidate scope, scores and publication time gates. Public readers remain read-only.

## Plan of Work
Add worker-only storage preflight, preserve original errors through cleanup, record child failures with retry state, release leases on completion, and handle termination. Verify a real interrupted transaction fixture before deploying. Analyse canonical plans with daily deduplication.

## Concrete Steps
Run python -m pytest -q; python -m compileall -q src tests; docker compose config --quiet; git diff --check. Verify affected source in built containers and read /api/health, current recommendation, and real /api/chat.

## Validation and Acceptance
A crash fixture must roll back uncommitted changes without losing committed rows. Storage failure must persist retry metadata or preserve its original cause when the ledger is inaccessible. Child death must be observed. Live exact-date coverage must advance; lack of current publication must remain explicit, not bypass time or data gates.

## Idempotence and Recovery
Backup directory results/storage-recovery-20260916 contains the isolated recovered copy; original hashes were recorded in tool output. The isolated copy was recovered first. During validation, an existing test without GP_STORE_DIR isolation invoked the new preflight on the default live history; its journal was consequently consumed by SQLite before the second backup attempt. This unintended test access was caught; an autouse isolated runtime-store fixture now prevents it for the entire contract suite. The live database subsequently passed full integrity_check. The second copy original-history.db is a post-recovery copy, not an untouched original transaction pair; do not describe it as a forensic backup. Recovery can repeat safely through SQLite mode=rw without creating missing files. Do not stage runtime data. Keep current image available for rollback.

## Artifacts and Notes
Initial database SHA256: 20B2869D78326A0725A50046731158B3348534F1310D704F3B0870183EC31172.
Initial journal SHA256: 56D6CF79AA45DF29F0E37FB6D8BCC28B717C497745F469F6F9DA5549D92A2F6F.

## Interfaces and Dependencies
No public schema, ranking formula or new dependency. Existing market ledger retry state and token-scoped leases are reused.

## Outcomes & Retrospective
Storage repair is deployed and exercised. Historical score audit is complete. No score formula changed; strict full-market acceptance remains limited by existing degraded exclusions and historical universe provenance.

2026-09-16 checkpoint: live database integrity_check=ok; two backend services rebuilt with matching source hashes. Real daily recovery advanced from zero to at least 1200/3051 for September 15. Linux fork child terminated with exit code -15 after resetting inherited handlers. Added worker stop_grace_period=60s to match cleanup budget.

Checkpoint: actual docker stop --timeout 60 returned worker ExitCode=0. Recreated worker preserved completed data and continued both dates. September 14 complete state contains 2 degraded_provider_failure exclusions under pre-existing policy; do not equate ledger completion with strict full-market acceptance. September 15 continues. Historical score analysis additionally proves the same 4000-event pool for July 22 and September 11 as-of queries, with latest event outcome July 21. These independent selection/evidence-policy findings are recorded, not silently changed as part of the storage repair.

Final 2026-09-16 12:57 Shanghai checkpoint: both September 14 and 15 runs reached ledger complete, without recurring SQLite error. September 14 has 3045 fetched / 3 official suspensions / 1 trusted-no-trade / 2 degraded-provider exclusions (601238,605303). September 15 has 3042 fetched / 8 official suspensions / 1 degraded-provider exclusion (605303). These inherited exclusions are not verified no-trade evidence and are not strict full-market acceptance. Health says recovery ready and next target ready_to_publish, while the current September 14 plan remains expired and tradeable_now=false; the base publication window has passed. Real post-deployment chat refused execution of that expired plan. It was sampled during final catch-up and included an overly broad future-publication statement; this is not proof of publication or a complete narration audit. Both diagnostic chat sessions were deleted with HTTP 204. No Git commit/push; existing user edits preserved.
