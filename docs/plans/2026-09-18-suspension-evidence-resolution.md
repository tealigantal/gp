# Suspension evidence resolution (2026-09-18)

## Purpose / Big Picture

Fix missed official suspension exclusions without treating provider-empty as proof. Keep the frozen full-market universe and exact-date coverage contract, production database schema, immutable plans, scoring and Serenity unchanged.

## Progress

- [x] Read contracts, inspected clean main and reproduced both failures with official documents.
- [x] Separate typed status facts, calendar validity and batch conflict resolution; adapt the worker and existing ledger JSON diagnostics.
- [x] Run offline production-function regression, live official-document replay, required checks and authorized deployment verification.
- [x] 170 backend tests and compile/manifest/retirement/selection/Compose checks passed; frontend typecheck and 14 tests passed. Frozen official PDF text reproduces all four 2026-08-20 cases. Both current symbols were recognized in the initial live pass; later intermittent exchange failures correctly prevented unverified exclusions.

## Surprises & Discoveries

600825's declared ten trading sessions were counted as calendar days. 601995's valid two-page notice was vetoed by three same-day ancillary reports exceeding the PDF page limit. Discovery also used calendar days; rejected evidence reasons were discarded before ledger persistence.

## Decision Log

Reuse the versioned local CnATradingCalendar, count sessions inclusively, and derive discovery from the same calendar (ten preceding sessions). Preserve maximum ten sessions and default five sessions for explicit undated-end continuation. No weekday fallback or larger PDF cap. Parse all readable documents for status facts. Only positively identified ancillary reports have non-blocking read failures; unknown/status/correction documents still block. Evaluate dated resumption against the halt's effective start. Save policy/calendar/fact provenance and per-document reasons in existing evidence_json, without schema migration or manual production repairs.

Ancillary document families are financial/periodic/audit/valuation/transaction reports and articles of association; status/progress/correction/revision wording takes precedence over that classification. Parsed facts always participate regardless of title. Subject and affirmative-assertion checks apply to both initial and continuing halts. Balanced stock-name/code annotations do not split clauses. The reused exchange verifier accepts opt-in strict errors so this collector can retain transport causes while Serenity keeps its existing boolean contract.

## Context and Orientation / Interfaces

`suspension_facts.py` is deterministic text-to-fact and validity logic. `official_suspension.py` owns read-only official collection and returns SuspensionResolution (evidence plus diagnostics). `market_orchestrator.py` consumes that single result after normal daily routes. `market_runs.py` alone persists coverage exclusions and failed-check diagnostics. The LLM and chat never collect or adjudicate evidence.

## Plan of Work / Concrete Steps

Implement these boundaries, update actual callers/tests and current contract; run `python -m pytest -q`, compileall, contract/retirement/selection checks and Compose validation. Replay real official evidence before rebuilding only backend API/worker. Observe native worker recovery and read actual current recommendation/chat. Commit/push only task files after validation under the user's existing authorization.

## Validation and Acceptance

Require tenth/eleventh session and holiday boundaries, date errors, incomplete discovery, late/foreign/unverified disclosures, resumption conflicts, unrelated versus relevant unreadable reports, persisted failures, and unchanged completed records. Live success means audited exact-date exclusions and complete native coverage, not merely HTTP 200. Record actual outcomes below; no predictive-return claim.

## Idempotence and Recovery

Collection is read-only. Diagnostics replace only the latest unresolved operational check; verified exclusions and completed runs are untouched. Deployment retains volumes and existing plans. Verification databases must set both GP_STORE_DIR and GP_CONTRACT_DB explicitly and use an isolated directory.

## Outcomes & Retrospective / Artifacts and Notes

Local and new-image isolated suites both passed 170 tests. The first isolated image invocation omitted the read-only `/app/docs` contract mount and failed that one environment-dependent check; after supplying the required documents, the complete suite passed without code/assertion changes. Both runtime database variables pointed into the disposable container and its network was disabled. Frontend typecheck/14 tests and all required backend gates passed. Independent read-only review found no remaining blockers in the listed counterexamples.

Read-only replay of the captured, exchange-verified 2026-08-20 disclosure batches selected the same four official notices: 002084/1225479880 (2 sessions), 002445/1225476184 (4), 002906/1225481393 (1), 600984/1225477636 (8). This is retrospective official-document validation, not a contemporaneous trading/return backtest.

Pre-deployment current publication was `publication_ad248c594b200026d5f7ef3d`, plan `plan_6456cfcd2e311a3c2af184e1` (session 2026-09-18, evidence 2026-09-17). Real `/api/chat` correctly described its expired status and pending next-session evidence; its disposable conversation was deleted with 204. Immutable payload SHA-256 baselines: plan `2d72cfda1823e0d1480b0828662b2051bb1bedca0313ba40a9defe13614740a7`, publication `8c3f8b6066e11f2898817fc165a2d613dc711d7a1c1abba663786cb6d9647c73`. Native deployment recovery remains in progress.

Deployment outcome: backend image `sha256:b4db10770752346a74bbca76b795ab0874a5fc1f514e5a5980e929788db7d079` was rebuilt; only `gp` and `gp-worker` were recreated. Both containers matched the checkout hashes for all five changed source modules. On the first native due retry, normal daily routes exhausted the two suspended symbols and the official collector accepted 600825/1225559328 (10 sessions) and 601995/1225552493 (4 sessions), recording calendar revision `4c3e16de4e7d9900`. The 2026-09-18 run completed at `18:26:17+08:00`: frozen raw=3052, fetched/expected=3044/3044, excluded=8, all exclusions official and approximation=false. No ledger row was manually repaired. Original plan/publication payload hashes remained identical.

At the initial post-recovery publication check, the unchanged producer correctly waited on `mature_memory_pending`; the separate maintenance child started processing the newly completed date. The older 2026-08-04/603221 recovery gap remained outside this repair and was explicitly diagnosed as an unreadable official document, not mislabeled suspension. These independent gates were not bypassed or redesigned.
