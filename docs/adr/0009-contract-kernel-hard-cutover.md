# ADR 0009: Contract Kernel Hard Cutover

## Decision

Use the three immutable canonical aggregates and a destructive database replacement. The publication is the sole product-facing projection.

## Consequences

No compatibility adapters, aliases, dual reads, dual writes, or retired schema support may be added. A failed required-evidence check produces a fail-closed state.
