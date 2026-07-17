# Serenity Alpha Automatic Promotion ExecPlan

## Purpose / Big Picture

Deliver a real free-data official-announcement experiment that is useful on its first enabled answer, remains non-binding in shadow, and can automatically enter ranking with at most an 8% add-on only after forward causal validation.

## Progress

- [x] 2026-07-11: Audited current architecture, free sources, local data, licensing limits, and runtime boundaries.
- [x] 2026-07-11: Chose CNINFO primary, SSE/SZSE verification, append-only evidence storage, and a separate worker.
- [x] 2026-07-11: Defined shadow/probation/active/suspended gates and 0%–8% counterfactual arms.
- [x] 2026-07-11: Implemented the evidence store, source adapters, conservative parser, elapsed scheduler, per-symbol coverage, resumable pagination, persistent breaker, and bootstrap-only readiness gate.
- [x] 2026-07-11: Integrated frozen signals, binding and reference-only counterfactual arms, policy state, checksummed sidecar snapshots, T+6 evaluation, and atomic policy ledger.
- [x] 2026-07-11: Integrated target-only narration, grounding guards, health, CLI, and separate worker/bootstrap Compose profiles.
- [x] 2026-07-11: Executed a real 30-day CNINFO bootstrap for `000001`: 4 HTTP requests, 2 PDF-backed records, complete per-symbol coverage, bootstrap marker `serboot_9006363b1b6de1090d027602`, and zero qualifying facts without fabrication.
- [x] 2026-07-11: Executed a second isolated real bootstrap for `000977`: 2 PDF-backed records and one verified 0.92-confidence positive fact; the backfill remained reference-only and applied weight stayed 0%.
- [x] 2026-07-11: Passed the final 119-test targeted checkpoint, all 311 tests in the isolated default suite, changed-file Ruff, compileall, diff check, and both Compose profile renders.
- [x] 2026-07-17: Rebuilt the shared backend and Web images locally, recreated the API, market worker, Serenity worker, and Web containers without deleting mounted runtime directories, and verified API health plus backend source provenance.
- [x] 2026-07-17: Replaced the legacy announcement envelope with the observed CNINFO v2 contract. A successful no-result query is `announcements: null` with zero counts, `hasMore: false`, and `totalpages: 0`; it now completes as zero records rather than opening a schema breaker.
- [x] 2026-07-17: Cleared only the obsolete pre-repair CNINFO breaker and ran the renewed worker. Its first live poll covered `002594` and `600000` successfully: 3 requests, 0 records, complete metadata/hydration coverage, no errors, and a 0% Serenity weight.

## Surprises & Discoveries

- Existing `history.db` overwrites item payloads and cannot preserve first-seen/version evidence.
- Existing Adaptive expert projection enforces a 3% minimum per expert, so Serenity must be a separate add-on to represent a true 0% shadow state.
- Current replay pending objects may contain full future outcomes before maturity; Serenity pending state must contain opaque references only.
- Current book JSON writes are not atomic; collector target discovery needs validated double reads.
- A plain two-day live poll is not a bootstrap and must never unlock shadow; a persisted bootstrap marker with complete target coverage is required.
- Historical replay originally inherited the live Serenity store; replay/backtest entry points now force Serenity off and prohibit Serenity persistence.
- Backfilled facts need immediate reference visibility but must never bind or enter promotion statistics. Separate reference arms preserve that distinction.
- Same-ID PDFs can change remotely; successful documents are revalidated at a bounded six-hour interval and stored as immutable versions.
- Poll completion is split from per-symbol coverage: source-level failures drive breaker/suspension, while local target/hydration gaps remain isolated and retry only their own window.
- Scanned or bounded-truncated PDFs are terminal non-scoring evidence in v1; transient download/timeout failures retry without poisoning the immutable content-version row.

## Decision Log

- Use official announcements only in v1; exclude broad free media news.
- Store raw evidence separately from Market Memory and transcript data.
- Keep `adaptive_score` as the eight-expert baseline and add `decision_score` for the optional Serenity adjustment.
- Preserve nine deterministic counterfactual arms for every frozen decision.
- Set automatic-learning hard cap to 8%; promotion begins at 1% probation and active learning begins at 2%.
- LLM receives bounded verified facts after routing and may only explain computed results.
- Treat the current CNINFO web-query response as one strict versioned contract: no `id` fallback, no empty-list compatibility for an official null empty page, and no pagination inference from `totalpages`.
- A binding decision is fail-closed if its Serenity reference snapshot or pending evaluation cannot be persisted.
- T+5 outcomes are evaluated no earlier than the next actual trading day and only with a complete finite five-bar window.

## Outcomes & Retrospective

The vertical slice is implemented, has both zero-result and positive-fact real-source proof, and passes the complete local default test suite. It remains in `shadow` at 0% because no forward outcomes have matured; the positive `000977` fact is historical backfill and therefore cannot train or bind. This is the intended first-day visible effect without fabricated production influence. Automatic promotion cannot occur until the documented forward sample and performance gates are met. Container build/smoke remains an environmental follow-up because Docker Desktop was not running.

## Context and Orientation

The base selection is implemented in `src/gp_assistant/decision_engine/adaptive_policy.py` and orchestrated by `decision_engine/pipeline.py`. Decision snapshots live in Market Memory. Chat routing and tool evidence are in `runtime/turn_loop.py` and `runtime/context_engine.py`; narration is in `llm/narrate.py`. Runtime state is exposed by `gateway/routes.py` and `contracts/api.py`.

## Plan of Work

1. Build `gp_assistant/serenity/` with typed models, append-only SQLite, CNINFO/SSE/SZSE adapters, PDF extraction, high-confidence hypothesis parsing, target discovery, and elapsed-time scheduling.
2. Build the independent policy module that freezes signals, computes 0%–8% arms, applies only the allowed weight, stores checksums, and advances/suspends state from mature immutable evaluations.
3. Insert the add-on after baseline Adaptive scoring but before final pick selection, keeping hard blocks and baseline fields unchanged.
4. Add target-only narration references, grounding validation, health status, CLI commands, Compose experiment profile, and documentation.
5. Validate causal timing, baseline invariance, append-only recovery, live bootstrap, payload budgets, full tests, and Docker concurrency/restart behavior.

## Concrete Steps

- Add `pypdf` and ignore `store/serenity/` runtime files.
- Implement one-writer WAL storage with heartbeat lease, read-only API connections, immutable versions, cursors, poll runs, hypotheses, snapshots, evaluations, update ledger, and policy CAS.
- Implement `serenity-loop`, `serenity-once`, `serenity-bootstrap`, and `serenity-status`.
- Add the worker under `experiments` and bootstrap under the distinct `serenity-bootstrap` profile so they cannot contend for the same lease.
- Add tests named in this plan to the repository's default-test allowlist.

## Validation and Acceptance

- `python -m compileall -q src tests`
- Targeted Serenity, Adaptive, context-budget, health, CLI, worker, and replay tests.
- `python -m pytest -q` with no unexpected skips/failures under the default suite.
- Opt-in live bootstrap obtains real source IDs, URLs, hashes, and first-seen values; fixtures cannot mark ready.
- Same inputs in shadow produce bit-for-bit base selection/action/price outputs.
- T+4 and unfinalized T+5 never update; T+6 applies each update exactly once.
- Docker worker failure leaves API/base recommendations healthy and exposes experimental degradation.

## Idempotence and Recovery

All source records, versions, evaluations, and policy updates use stable IDs and unique ledgers. Partial polls do not advance the complete cursor; a separate per-symbol page checkpoint resumes backlog safely. Evaluation insertion and pending completion share one transaction; policy CAS and its ledger share another, and the next worker pass reconciles a crash between those transactions. Crashes may leave removable raw-file orphans but never committed DB references to missing files. Any integrity violation sets the applied weight to zero and requires a new shadow epoch.

## Artifacts and Notes

- Runtime store: `store/serenity/` (ignored by Git).
- Governance: `docs/RESEARCH_LOG.md`, `docs/VALIDATION.md`, `docs/PROGRESS.md`, `docs/DEBT.md`.
- Architecture decision: `docs/adr/0001-serenity-alpha-experimental-addon.md`.

## Interfaces and Dependencies

Public `ChatResponse` remains compatible. Health receives an additive Serenity status. Internal types include facts, hypotheses, frozen references, counterfactual arms, evaluations, and policy state. `pypdf` is the only new runtime dependency; no OCR, queue, scheduler, or paid data dependency is introduced.
