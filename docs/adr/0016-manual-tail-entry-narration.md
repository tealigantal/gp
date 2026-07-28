# ADR 0016 — Manual tail-entry narration

Status: Accepted, 2026-07-28

## Context

GP's prior-day daily plan already selects candidates, ranks them and supplies an entry range, stop and target for the next 1–3 trading days. Users asked how to monitor the next afternoon and what conditions should make the range actionable. Free live data cannot safely support an automated tail-entry engine, and the product has no brokerage or order-placement goal.

## Decision

Keep selection, ranking and numerical authority in the immutable `RecommendationPlan`. Add a fixed manual tail-entry playbook to the only production `ConversationService` prompt and its publication-bound facts. The playbook tells users to inspect price location, VWAP, strength relative to CSI300, tail volume, recent five-minute shape, no-chase and stop rules between 14:45 and 14:56. It distinguishes `breakout_pullback` and `structure_watch` daily signal labels.

The narrator must call this a user-operated checklist. It must never claim that it has observed those live values, that a condition has passed, that the system will perform a later automatic decision, or that it can initiate an order. No first-entry guidance is given after 14:57.

## Consequences

The chat can answer practical entry questions without an additional data source, scheduler, runtime schema, execution engine or public API. It remains useful to a user who can see a brokerage chart. It cannot give a real-time pass/fail decision until a future product explicitly supplies auditable live facts.

## Rollback

Remove the manual playbook from the one prompt and its in-memory fact payload. No persisted data, recommendation plan, runtime observation, publication, session schema or external side effect requires migration.
