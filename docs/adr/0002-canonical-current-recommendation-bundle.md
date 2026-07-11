# ADR 0002: Canonical current recommendation bundle

## Status

Accepted on 2026-07-11.

## Decision

All Python Compose services use one tagged backend image. Runtime writers attach revision, source digest, artifact schema, and Adaptive policy metadata. A validated immutable MarketBook is written before the current pointer, which is the final atomic commit point. Readers resolve current state from that versioned book rather than recomposing it from a mutable daybook.

Parameterless recommendation APIs use the canonical current book. Explicit run/date parameters retain historical artifact lookup. Non-trading current plans keep their picks while immediate execution remains disabled.

## Consequences

Legacy or mismatched artifacts are retained but cannot become current. Rebuilding the backend invalidates prior current producer identity and causes the current worker to rebuild safely. Ops commands require the running API producer contract.
