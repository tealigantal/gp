# 0008 — Full-market universe ownership and additive Serenity

- **Status:** Accepted
- **Date:** 2026-07-22

## Context

The production daily path disabled the market snapshot and silently fell back to a ten-symbol file. Freshness then validated only those ten symbols, allowing a reduced input scope to appear complete. Serenity also had both scoring authority and a veto over base recommendation availability.

## Considered Options

1. Re-enable the former liquidity snapshot switch without a new contract.
2. Keep the static file but label it degraded.
3. Introduce an immutable full-market universe contract, fail closed when its coverage is unproven, and make Serenity an additive batch only.

## Decision

Choose option 3. The worker owns a dated `MarketUniverseSnapshot.v1` built from official exchange security lists and completed daily market data. Production selection consumes only an accepted snapshot, filters the complete main-board input, and scores at most 200 symbols. Static files are never a production fallback.

Serenity operates on the base Top-30 finalist pool. A complete batch may contribute the causally gated 0%-8% weight. An incomplete or stale batch contributes zero for every finalist, preserves the base ordering, and is reported as degraded without blocking the base recommendation.

## Rationale

The product promise is full-market discovery, not stable output from an arbitrary watchlist. Scope and freshness therefore need one auditable, publish-blocking contract. Atomic zero contribution prevents partial Serenity coverage from introducing asymmetric ranking bias while retaining its approved bounded influence when evidence is complete.

## Consequences

- Full-market collection can delay availability; the correct response is explicit no-trade rather than narrowed recommendations.
- Health and Workspace expose universe counts independently from the selected/tracked set.
- Historical snapshots without the contract remain readable for audit but cannot be current or tradeable.
- The worker gains resumable universe collection responsibility; chat remains network-free.

## Migration

Deploy the new producer and integrity checks together. The source revision invalidates the old current artifact. Build and publish the first accepted target-day universe, then publish a new recommendation snapshot. Do not rewrite or delete old snapshots.

## Rollback

Do not reactivate a backend image that can publish the static ten-symbol universe as healthy. If collection or scoring fails, retain the new fail-closed runtime and fix/roll forward. The Web may be rolled back independently if its additive presentation fails.
