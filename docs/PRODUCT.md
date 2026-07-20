# GP Product

## Product Summary

GP is a single-workspace A-share main-board decision assistant for short 1–3 trading-day plans. The left pane is a continuous conversation and the right pane presents the same canonical decision snapshot.

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

All market-facing answers use the same active run and structured judgment. The LLM translates facts into Chinese but cannot change selection or numbers. DeepSeek tool routing uses the provider's strict Beta interface; unavailable provider calls fail explicitly rather than silently using a different router. Obsolete routing labels are not silently reinterpreted as a different user request: the normal real-LLM repair runs once, then the turn fails closed if it remains invalid. A rejected LLM narration is fail-closed for that one answer: it is neither displayed nor saved, while a configured real provider remains available for the user's next direct question. Once an answer commits, its exact validated body remains visible in the immediate response, idempotent retry, and later Workspace history; a malformed historical record is shown as an explicit recovery warning, never as a blank reply. The conversation transcript renders that validated narration as plain text for every assistant intent; it does not render candidate, comparison, execution, or risk-detail cards. The right-side decision snapshot remains the single structured operational view. Serenity is visible immediately as real evidence and shadow/counterfactual impact; it affects production ranking only after automatic causal validation.

During the lunch break, the runtime status card shows whether the 11:30 intraday data artifact has updated. This is a data-completion signal only; it does not imply a trading recommendation.

## Failure and Recovery Experience

Critical market-data failures produce explicit blocked/no-trade behavior. Serenity collection failures degrade only the experiment: the base recommendation remains available, the answer must not claim that no announcement exists, and health exposes the reason and recovery state. If a real LLM answer fails evidence validation, the Workspace says it may be retried and keeps the composer available; only an unconfigured provider disables new natural-language requests.

## Product Constraints

- Real, attributable data only.
- No automated trading.
- No future leakage in replay or learning.
- No silent fallback that fabricates a conclusion.
- Public chat response compatibility remains stable.

## Non-goals

Broad-media news coverage, OCR of scanned filings, commercial redistribution of free public data, and guaranteed performance are outside Serenity v1.

## Current Gaps

Adaptive full-history acceptance is incomplete; existing probability samples show overconfidence; Docker validation depends on the local engine; free announcement sources lack an SLA; Serenity has no forward performance sample yet.
## Non-trading daily plans

When the latest completed trading day has valid Adaptive candidates, weekends and other non-trading periods continue to show the ranked daily plan, entry zone, stop and take-profit levels. The UI labels it as a recent-trading-day plan for next-session review; `publish_allowed=false` prevents it from being presented as immediately executable.
