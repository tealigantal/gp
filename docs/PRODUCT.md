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
- See verified official-announcement evidence, its actual native Alpha contribution, and whether that contribution was neutral, shadowed or binding.

## Expected User-visible Behavior

All market-facing answers use the session-bound immutable snapshot and the configured real LLM for routing and grounded Chinese narration. The chat layer cannot change selection, numbers, candidates or evidence. A missing current snapshot is HTTP 503; an incompatible, stale, market-time-mismatched or Serenity-incomplete snapshot is a grounded `no_trade` without candidate leakage. A valid completed-day plan outside an executable window remains `decision=recommend` with `tradeable=false` and is described as a next-session plan. The service never reads legacy run JSON or a live Serenity sidecar during chat. A narration draft that violates the evidence boundary may be repaired once by another real LLM call and the same validator; rejected drafts are never shown or persisted. LLM failure remains explicit and never substitutes a fixed template or commits an assistant turn. Any session-bound snapshot whose ID is no longer the current pointer is historical: explanation remains available, while recommendation or execution requests are non-tradeable. A new complete Serenity poll with the same frozen facts only renews freshness and keeps the snapshot current; a true semantic change forces a new snapshot. When live Serenity semantics advance before the current pointer catches up, an existing-session explanation may still use its bound evidence but is explicitly `snapshot_explanation_only`, `tradeable=false` and not current execution guidance.

## Failure and Recovery Experience

Critical market-data failures produce explicit blocked/no-trade behavior. Before the close data is ready, the system builds a plan from the last completed daily-bar day rather than incorrectly demanding an unfinished same-day bar; post-close EOD probing remains pending without advancing the current recommendation. Serenity collection failure or incomplete candidate coverage keeps that candidate set pending/no-trade; it never exposes a baseline-only recommendation or claims that no announcement exists. Health exposes the exact target, coverage and recovery state. It always reads the real database, waits at most two seconds for a transient lock, and returns retryable 503 rather than displaying a cached readiness value.

## Product Constraints

- Real, attributable data only.
- No automated trading.
- No future leakage in replay or learning.
- No silent fallback that fabricates a conclusion.
- No V1/V2 or legacy API compatibility is retained.

## Non-goals

Broad-media news coverage, OCR of scanned filings, commercial redistribution of free public data, and guaranteed performance are outside Serenity v1.

## Current Gaps

Adaptive full-history acceptance is incomplete; existing probability samples show overconfidence; free announcement sources lack an SLA; Serenity has no forward performance sample yet.

## Non-trading daily plans

When the latest completed trading day has valid Adaptive candidates, weekends and other non-trading periods continue to show the ranked daily plan, entry zone, stop and take-profit levels. The UI labels it as a recent-trading-day plan for next-session review; `publish_allowed=false` prevents it from being presented as immediately executable.
