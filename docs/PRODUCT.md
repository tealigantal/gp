# GP Product

## Product Summary

GP is a chat-only A-share main-board decision assistant for short 1–3 trading-day plans. Every reply is bound to one immutable `RecommendationSnapshot.v1`.

## Target Users

Individual researchers and traders who want evidence-backed candidate plans and consistent follow-up decisions. GP is not an execution venue and does not place orders.

## User Problems

- Candidate lists without an auditable reason or risk boundary.
- Follow-up answers that drift from the original recommendation.
- Current and historical data being mixed across time.
- Probabilities or news being treated as certainty.

## Critical User Journeys

- Request current candidates or an explicit no-trade result.
- Inspect a candidate's entry, stop, take-profit, probability, uncertainty, and evidence.
- Compare ranked candidates and understand why an alternative lost.
- Manage a holding as the thesis strengthens, weakens, or invalidates.
- Read official-announcement evidence as a bounded experimental factor.

## Expected User-visible Behavior

All market-facing answers use the session-bound immutable snapshot. The chat layer cannot change selection, numbers, candidates or evidence. A missing, invalid, stale or non-tradeable snapshot returns structured `no_trade`; it never reads an older run, JSON artifact or historical chat record.

## Failure and Recovery Experience

Critical market-data failures produce explicit blocked/no-trade behavior. Serenity collection failures degrade only the experiment: the base recommendation remains available, the answer must not claim that no announcement exists, and health exposes the reason and recovery state.

## Product Constraints

- Real, attributable data only.
- No automated trading.
- No future leakage in replay or learning.
- No silent fallback that fabricates a conclusion.
- No V1/V2 or legacy API compatibility is retained.

## Non-goals

Broad-media news coverage, OCR of scanned filings, commercial redistribution of free public data, and guaranteed performance are outside Serenity v1.

## Current Gaps

Adaptive full-history acceptance is incomplete; existing probability samples show overconfidence; Docker validation depends on the local engine; free announcement sources lack an SLA; Serenity has no forward performance sample yet.
## Non-trading daily plans

When the latest completed trading day has valid Adaptive candidates, weekends and other non-trading periods continue to show the ranked daily plan, entry zone, stop and take-profit levels. The UI labels it as a recent-trading-day plan for next-session review; `publish_allowed=false` prevents it from being presented as immediately executable.
