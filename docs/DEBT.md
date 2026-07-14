# Deliberate Technical Debt

## Free announcement interfaces have no SLA

- **Description:** Serenity v1 depends on public CNINFO/SSE/SZSE web interfaces.
- **Reason accepted:** The user requires free data for a local resident native-Alpha service.
- **Affected behavior:** Evidence may become stale or unavailable; exact-target publication then remains pending/no-trade instead of continuing on the eight-expert baseline.
- **Risk:** Schema changes, throttling, access challenges, and license changes.
- **Scope:** Serenity collection and current recommendation readiness.
- **Removal condition:** Replace or supplement with a licensed documented feed.
- **Intended milestone:** Data-source reliability review.
- **Status:** Accepted operational debt.

## Historical announcement first-seen is unavailable

- **Description:** Backfilled documents cannot prove their original market-availability time.
- **Reason accepted:** Public metadata/CDN timestamps are insufficient.
- **Affected behavior:** Backfill may be retained for audit/reference evaluation, but never enters a current binding Alpha or user-facing selection claim.
- **Risk:** Promotion takes longer and historical sample coverage is limited.
- **Scope:** Serenity evaluation and learning.
- **Removal condition:** Obtain a point-in-time source with contractual timestamp semantics.
- **Intended milestone:** Data-source upgrade review.
- **Status:** Accepted.

## Cross-document correction relation is conservative, not fully semantic

- **Description:** Same-ID PDF replacement is versioned automatically. Separate earnings corrections can link by exact fact ID or normalized report period. Other live corrections without a trustworthy target set that symbol's Serenity availability to zero instead of guessing a relation; backfill relations never bind.
- **Reason accepted:** Free public metadata does not consistently expose a stable correction target ID, and a false link would contaminate both ranking and forward evaluation.
- **Affected behavior:** An unresolved correction makes that symbol's exact-target signal unavailable and blocks publication of the whole current candidate set until resolved; no baseline-only result is exposed.
- **Risk:** Reduced experimental coverage and delayed reactivation after benign corrections; no stale corrected fact is allowed to keep a native Serenity contribution.
- **Scope:** Serenity evidence resolution only.
- **Removal condition:** Add a reviewed relation extractor with measured precision or adopt a point-in-time licensed feed.
- **Intended milestone:** After forward corpus review.
- **Status:** Accepted conservative debt.

## PDF parser has a wall-clock but not an RSS limit

- **Description:** PDFs are capped at download size and parsed in a disposable child process with a 20-second timeout, but the child has no portable per-process RSS ceiling.
- **Reason accepted:** The service is local, source documents are official filings, and adding a platform-specific sandbox would broaden the runtime surface.
- **Affected behavior:** An abnormal highly compressed PDF may cause a temporary memory spike before timeout/termination.
- **Risk:** Local worker or container memory pressure; API and the deterministic engine process remain isolated from the collector. Incomplete collection still blocks native publication rather than exposing a baseline-only rank.
- **Scope:** Serenity PDF extraction only.
- **Removal condition:** Add a container memory limit and measured parser-worker RSS guard before broader or commercial ingestion.
- **Intended milestone:** Container runtime hardening after collection telemetry review.
- **Status:** Accepted operational debt.

## Narration claim validation is conservative text grounding

- **Description:** Serenity selection-effect language is checked against structured binding fields and a conservative Chinese/English phrase policy; the LLM does not yet return a formal per-sentence claim graph. The current provider certificate is compact, exposes at most two Serenity facts, and replaces all quantitative values with opaque candidate+field+value tokens expanded locally into labeled capsules. One real LLM repair may regenerate a rejected draft under the same validator.
- **Reason accepted:** The current narrator API is text-first and changing it to a structured generation protocol would affect every response type.
- **Affected behavior:** Unknown/missing evidence, raw provider-written numbers, cross-candidate/field token use, unauthorized actions and non-binding selection-effect synonyms are rejected. Future novel but valid phrasing may require extending the local guard; a rejected first draft is never shown or stored.
- **Risk:** Explanation wording risk only; LLM output cannot change candidates, scores, actions, prices, policy state, or stored outcomes.
- **Scope:** User-facing Serenity narration.
- **Removal condition:** Introduce typed `used_fact_ids` and `affected_symbols` in a versioned narrator response contract.
- **Intended milestone:** Narrator contract v2.
- **Status:** Accepted bounded debt.

## Scanned PDF OCR omitted

- **Description:** v1 extracts text-layer PDFs with `pypdf`; scanned filings are marked unparsed.
- **Reason accepted:** Avoid a large OCR dependency and false extraction confidence in the first vertical slice.
- **Affected behavior:** A target containing an unparsed or truncated relevant document remains incomplete and cannot publish a recommendation until a later complete parse succeeds.
- **Risk:** Coverage bias toward machine-readable issuers/documents.
- **Scope:** Serenity hypothesis extraction.
- **Removal condition:** Measured unparsed rate justifies a reviewed OCR pipeline.
- **Intended milestone:** After 20 trading days of collection telemetry.
- **Status:** Accepted.
## Resolved historical note — single-protocol container cutover

No compatibility layer or deferred data migration is retained. The earlier
outstanding normal rebuild and worker-publication step has been completed on
2026-07-14 through the ordinary Compose stack and natural resident collection;
it is no longer current debt. No production database or volume was deleted.
