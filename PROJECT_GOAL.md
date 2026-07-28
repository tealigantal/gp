<!-- codex-important-project -->

# GP Durable Project Goal

## Objective

Build a dependable A-share main-board recommendation chat agent. Every recommendation and follow-up must bind to one immutable RecommendationPublication projected only from one RecommendationPlan and an optional RuntimeObservation; answer-time market status is a separate deterministic projection and may never be replaced by a historical runtime snapshot. No retired recommendation, narration, execution, or operational API may provide an alternative answer.

## User and Problem

The primary user is an individual A-share researcher/trader who needs a coherent answer to what is worth monitoring, why, at what risk boundary, and how a prior thesis changed. The problem is not merely discovering symbols; it is preserving causal, current, and explainable decision context across recommendation and conversation.

## Observable Stopping Condition

The product reaches its durable objective when current-data recommendation and follow-up journeys are reliable through the single chat protocol, publications and turns commit atomically, retired stores and APIs are removed, historical replay proves no future leakage, probability and adaptive outputs meet documented holdout thresholds, operational failures fail closed, and all displayed claims are traceable to immutable evidence.

## Critical User Journeys

- Ask for current Top-N candidates and receive a valid plan or explicit no-trade result.
- Ask why a candidate was selected or rejected and receive source-grounded evidence.
- Compare candidates and explain an existing position from the same bound publication.
- Review how a conclusion changed without rewriting the original evidence.
- Use resident official-announcement evidence as an atomic fixed-3% Alpha expert without mistaking it for certainty or allowing partial source coverage to bias candidates.
- Refresh the frozen Top-30 at lunch from one complete 11:30 five-minute batch while preserving the morning plan, daily evidence and historical conversation lineage.

## Non-goals

- Automated order placement or brokerage integration.
- LLM-based stock picking or fabricated market/news facts.
- Guaranteed investment returns.
- Production dependence on undocumented free web interfaces without explicit licensing and reliability controls.

## Constraints

- Real data only; missing or stale critical market data fails closed.
- Selection and numerical conclusions remain deterministic and auditable.
- Historical logic uses only information available at the decision time.
- The only public product interface is the versioned chat contract plus health and chat-history reads.
- Legacy runtime recommendation and conversation data is deleted rather than converted after the integrity-gated cutover authorized by the user.

## Current Lifecycle Stage

Contract-kernel hard cutover: one typed plan, runtime observation, publication, and conversation lineage.

## Approval Gates

- Full Adaptive holdout acceptance before mainline production promotion.
- Serenity ranking influence at a fixed 3% for an exact complete batch was explicitly authorized on 2026-07-24; incomplete, failed, stale, or mismatched batches must be zero for every finalist.
- Explicit approval for deployment, paid dependencies/data, commercial data use, secrets, destructive migrations, or public API breaks.

## Assumptions

- Serenity is a local resident native Alpha input using free official announcements; its effective weight is exactly 0% or 3%, and the deterministic engine remains the sole ranking authority.
- Current data and chat services continue to use the existing Docker topology and shared `store` volume.
- The user accepts the bounded Serenity v2 OCR lane: `pypdf` remains the text fast path, while structurally valid zero-text PDFs may use fixed-version PDFium, Tesseract `chi_sim+eng`, and Pillow dependencies inside the isolated worker child process.

## Unknowns

- Free official endpoints have no contractual SLA and may change schema or access policy.
- Public historical announcement timestamps do not consistently prove first market availability.
- Serenity's predictive value is unknown until enough forward-only outcomes mature.
