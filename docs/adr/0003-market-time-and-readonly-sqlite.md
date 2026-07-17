# ADR 0003: Explicit market time and read-only SQLite access

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

The runtime treated a plan's trading day as the daily-bar freshness day. On a Monday before close this demanded same-day bars and blocked every candidate. Separately, read getters initialized `agent.db` with `BEGIN IMMEDIATE`, turning routine health/chat reads into writer contention.

## Decision

Use `MarketTimeContext` as the core date contract. Daily selection and `DayBook.trading_day` use `daybook_effective_day`; published runtime artifacts use `decision_trade_day`. Retain `as_of` only as a compatibility alias. Migrate `agent.db` additively to schema v2, bootstrap at process/write boundaries, and use explicit read-only connections for getters. Sessions bind by insert-or-verify and allocate sequence numbers from a counter.

## Consequences

The worker can reuse an immutable producer-compatible daybook until a force rebuild or completed-day change. Reads remain available while a writer holds a RESERVED transaction. A session no longer silently changes factual basis after its first committed turn.

## Rollback

The migration is additive. Rollback is code-level: retain the v2 fields and read the preserved `as_of` alias; no runtime database or legacy artifact is restored.
