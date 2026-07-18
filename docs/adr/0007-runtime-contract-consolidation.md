# 0007 — Runtime contract consolidation

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

The single-protocol cutover removed worker file-store and portfolio seams, but
the default worker tests still monkeypatched those names. Market time also
exposed retired dictionary aliases that allowed callers to depend on ambiguous
date names. The result was a permanently failing default suite and a risk that
future code could revive old lifecycle paths merely to satisfy stale callers.

## Considered Options

1. Restore the old worker functions and mapping aliases.
2. Keep the stale tests ignored and leave compatibility code in place.
3. Retire the aliases, define one operation contract, and migrate active
   freshness/worker callers and tests to the current runtime model.

## Decision

Adopt option 3.

- contracts/runtime.py is the sole runtime-operation contract. Only auto,
  rebuild_daybook, and postclose_archive are valid.
- runtime/market_time.py owns canonical market-time fields only.
- evidence/daily_freshness.py owns the explicit projection from canonical
  market time to durable daily-freshness report fields.
- contracts/intents.py accepts only current routing literals.
- The resident worker is reached only through runtime-loop; replay, daily,
  pre-open, and old post-close wrapper functions are removed.

## Rationale

Reintroducing obsolete functions would conceal the cutover and give future
callers two incompatible sources of truth. Explicit category ownership makes
an invalid boundary input visible, repairable by the real LLM where applicable,
and otherwise safely fail-closed.

## Consequences

- A stale provider routing label receives the normal one-shot real repair; it
  is not silently converted into a different request.
- Runtime callers receive a deterministic validation error for retired
  operation names before acquiring the worker lane.
- Daily freshness keeps its stable persisted field names without making
  MarketTimeContext impersonate that schema.
- No database schema, user history, selection rule, numeric authority rule,
  or Serenity shadow/weight gate changes.

## Migration

Worker and daily-freshness tests now construct MarketTimeContext and use
AgentStore-based boundaries. Existing persisted freshness reports remain
readable because their durable report schema is unchanged.

## Rollback

Revert the code and test migration together. Do not selectively restore old
worker exports or market-time aliases, because that would recreate the split
contract.
