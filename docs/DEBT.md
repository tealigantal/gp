# Deliberate Technical Debt

## Free announcement interfaces have no SLA

- **Description:** Serenity v1 depends on public CNINFO/SSE/SZSE web interfaces.
- **Reason accepted:** The user requires free data for a local experiment.
- **Affected behavior:** The experiment may become stale or suspended while base GP continues normally.
- **Risk:** Schema changes, throttling, access challenges, and license changes.
- **Scope:** Serenity collection only.
- **Removal condition:** Replace or supplement with a licensed documented feed.
- **Intended milestone:** Post-forward-validation production review.
- **Status:** Accepted experimental debt.

## Historical announcement first-seen is unavailable

- **Description:** Backfilled documents cannot prove their original market-availability time.
- **Reason accepted:** Public metadata/CDN timestamps are insufficient.
- **Affected behavior:** Serenity learning is forward-only. Backfill can appear in narration and a separately labeled reference counterfactual, but its binding contribution and promotion eligibility are exactly zero.
- **Risk:** Promotion takes longer and historical sample coverage is limited.
- **Scope:** Serenity evaluation and learning.
- **Removal condition:** Obtain a point-in-time source with contractual timestamp semantics.
- **Intended milestone:** Data-source upgrade review.
- **Status:** Accepted.

## Cross-document correction relation is conservative, not fully semantic

- **Description:** Same-ID PDF replacement is versioned automatically. Separate earnings corrections can link by exact fact ID or normalized report period. Other live corrections without a trustworthy target set that symbol's Serenity availability to zero instead of guessing a relation; backfill relations never bind.
- **Reason accepted:** Free public metadata does not consistently expose a stable correction target ID, and a false link would contaminate both ranking and forward evaluation.
- **Affected behavior:** An unresolved correction can temporarily suppress all Serenity contribution for one symbol, while baseline Adaptive remains unchanged.
- **Risk:** Reduced experimental coverage and delayed reactivation after benign corrections; no stale corrected fact is allowed to keep a binding add-on.
- **Scope:** Serenity evidence resolution only.
- **Removal condition:** Add a reviewed relation extractor with measured precision or adopt a point-in-time licensed feed.
- **Intended milestone:** After forward corpus review.
- **Status:** Accepted conservative debt.

## PDF parser has a wall-clock but not an RSS limit

- **Description:** PDFs are capped at download size and parsed in a disposable child process with a 20-second timeout, but the child has no portable per-process RSS ceiling.
- **Reason accepted:** The experiment is local, source documents are official filings, and adding a platform-specific sandbox would broaden the first production dependency/runtime surface.
- **Affected behavior:** An abnormal highly compressed PDF may cause a temporary memory spike before timeout/termination.
- **Risk:** Local worker or container memory pressure; API and base ranking remain isolated from the collector.
- **Scope:** Serenity PDF extraction only.
- **Removal condition:** Add a container memory limit and measured parser-worker RSS guard before broader or commercial ingestion.
- **Intended milestone:** Container runtime hardening after forward shadow validation.
- **Status:** Accepted experimental debt.

## Narration claim validation is conservative text grounding

- **Description:** Serenity selection-effect language is checked against structured binding fields and a conservative Chinese/English phrase policy; the LLM does not yet return a formal per-sentence claim graph.
- **Reason accepted:** The current narrator API is text-first and changing it to a structured generation protocol would affect every response type.
- **Affected behavior:** Unknown/missing evidence and non-binding selection-effect synonyms are rejected; future novel phrasing may require extending the local guard.
- **Risk:** Explanation wording risk only; LLM output cannot change candidates, scores, actions, prices, policy state, or stored outcomes.
- **Scope:** User-facing Serenity narration.
- **Removal condition:** Introduce typed `used_fact_ids` and `affected_symbols` in a versioned narrator response contract.
- **Intended milestone:** Narrator contract v2.
- **Status:** Accepted bounded debt.

## Scanned PDF OCR omitted

- **Description:** v1 extracts text-layer PDFs with `pypdf`; scanned filings are marked unparsed.
- **Reason accepted:** Avoid a large OCR dependency and false extraction confidence in the first vertical slice.
- **Affected behavior:** Some announcements remain reference-only or unavailable for scoring.
- **Risk:** Coverage bias toward machine-readable issuers/documents.
- **Scope:** Serenity hypothesis extraction.
- **Removal condition:** Measured unparsed rate justifies a reviewed OCR pipeline.
- **Intended milestone:** After 20 trading days of collection telemetry.
- **Status:** Accepted.
