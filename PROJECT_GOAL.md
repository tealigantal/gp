<!-- codex-important-project -->

# GP Durable Project Goal

## Objective

Build a dependable A-share main-board decision assistant that combines real market data, Market Memory, calibrated probability, execution risk, Adaptive selection, and auditable evidence into consistent 1–3 trading-day plans and follow-up decisions.

## User and Problem

The primary user is an individual A-share researcher/trader who needs a coherent answer to what is worth monitoring, why, at what risk boundary, and how a prior thesis changed. The problem is not merely discovering symbols; it is preserving causal, current, and explainable decision context across recommendation and conversation.

## Observable Stopping Condition

The product reaches its durable objective when current-data recommendation and follow-up journeys are reliable, historical replay proves no future leakage, probability and adaptive outputs meet documented holdout thresholds, operational failures fail closed, and all displayed claims are traceable to immutable evidence.

## Critical User Journeys

- Ask for current Top-N candidates and receive a valid plan or explicit no-trade result.
- Ask why a candidate was selected or rejected and receive source-grounded evidence.
- Compare candidates and manage an existing position from the same run.
- Review how a conclusion changed without rewriting the original evidence.
- Use experimental official-announcement evidence without mistaking unvalidated signals for a hard rule.

## Non-goals

- Automated order placement or brokerage integration.
- LLM-based stock picking or fabricated market/news facts.
- Guaranteed investment returns.
- Production dependence on undocumented free web interfaces without explicit licensing and reliability controls.

## Constraints

- Real data only; missing or stale critical market data fails closed.
- Selection and numerical conclusions remain deterministic and auditable.
- Historical logic uses only information available at the decision time.
- Existing public ChatResponse compatibility is preserved unless separately approved.
- Runtime stores and the user's local data are non-destructive boundaries.

## Current Lifecycle Stage

Adaptive Decision Engine integration, full-history validation, and forward-only Serenity Alpha experimentation.

## Approval Gates

- Full Adaptive holdout acceptance before mainline production promotion.
- Serenity automatic ranking influence only after its forward causal gates pass.
- Explicit approval for deployment, paid dependencies/data, commercial data use, secrets, destructive migrations, or public API breaks.

## Assumptions

- Serenity is currently a local research experiment using free official announcements.
- Current data and chat services continue to use the existing Docker topology and shared `store` volume.
- The user accepts one additional open-source PDF dependency, `pypdf`, and no OCR in v1.

## Unknowns

- Free official endpoints have no contractual SLA and may change schema or access policy.
- Public historical announcement timestamps do not consistently prove first market availability.
- Serenity's predictive value is unknown until enough forward-only outcomes mature.
