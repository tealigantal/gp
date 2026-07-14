# ADR 0005 — Serenity Native Alpha and Real-LLM Chat

- **Status:** Accepted
- **Date:** 2026-07-14
- **Supersedes:** ADR 0001 scoring shape and ADR 0004 reference-only authority

## Context

Before this decision, the resident Serenity service collected official evidence
but was only a post-selection add-on. Its targets came from an already-published
recommendation and could fall back to old cursor symbols. Separately, the then-current
`/api/chat` path rendered fixed templates even though the configured real LLM
client and grounded narration modules remained available. This produced an
operationally online system that does not execute the intended user journey.

The user explicitly chose formal Serenity Alpha integration and real LLM
recommendation conversation. The deterministic engine must still own stock
selection and numbers.

## Considered Options

1. Restore the old post-hoc Serenity add-on and old multi-store chat runtime.
2. Keep Serenity reference-only and only replace the chat templates.
3. Make Serenity a native ninth signed Adaptive expert, freeze it into the one
   recommendation snapshot, and let a two-stage LLM route/explain that snapshot.

## Decision

Choose option 3.

The production flow is:

```text
real market data
-> deterministic candidate target set
-> resident Serenity coverage and as-of Alpha freeze for that exact set
-> Adaptive Decision Engine v2 single scoring pass (eight existing experts + Serenity)
-> one immutable RecommendationSnapshot.v1
-> LLM intent routing and grounded Chinese narration
```

Complete coverage with no relevant evidence is a valid neutral Serenity input.
Incomplete, stale, failed or unparsed coverage is pending/no-trade. It may not
fall back to baseline-only scoring, an old target set, an old signal or a
template response. No announcement network call runs in decision rendering or
chat. Backfill remains non-binding. The LLM cannot select/promote/demote symbols
or modify scores, prices, probabilities, facts or actions.

Publication is sidecar-first and pointer-last. `RuntimeEvidenceBinding.v1`
durably binds the Decision Context Snapshot, candidate target, Serenity
reference/pending records, readiness revision and checksums. Only after that
binding is readable does one final `agent.db` transaction write the daybook,
`RecommendationSnapshot.v1` and current pointer under additive schema v3.

Poll freshness and decision semantics have separate identities. A freshness
certificate records the latest complete run, coverage, expiry and live worker
lease and is checked at request start and before commit. A content-addressed
`SerenitySemanticRevision.v1` covers the target/activation/formula/effective
policy plus ordered frozen facts and lineage. Equivalent complete polls renew
freshness without rebuilding the same recommendation or aborting a long LLM
turn. Partial/failed/expired coverage still fails closed; a changed fact,
correction, target, formula or effective policy changes the semantic revision
and forces a new snapshot.

LLM chat has two required logical stages, not a fixed request count. Intent
routing may make one JSON repair request. Narration receives a compact
certificate with at most two Serenity facts per candidate and opaque
candidate+field+value tokens that local code expands into labeled capsules. If
the first narration violates authority validation, one additional real
`tool_evidence_repair` call may regenerate it; rejected drafts are never shown
or stored.

## Rationale

One scoring pass makes ranking ownership auditable. Candidate-first collection
removes the published-snapshot circularity. Immutable as-of lineage prevents
future coverage or corrected documents from rewriting past decisions. Real LLM
routing/narration restores the intended conversational product while grounding
keeps numerical and stock-selection authority deterministic.

## Consequences

- Serenity source availability is now a formal input-readiness condition for a
  candidate set. A failure can delay/no-trade a new snapshot but cannot produce
  a baseline result that silently omits the ninth expert.
- The existing causal policy still gates the Serenity weight; a real known-empty
  signal or shadow state contributes exactly zero.
- Recommendation snapshots grow to include Serenity Alpha feature, contribution
  and evidence lineage.
- `/api/chat` depends on configured LLM availability. LLM failure is observable
  and no assistant turn is committed.
- Exact health/session reads use the real database with a bounded wait, release
  read locks before large JSON decode and return structured 503 rather than a
  cached readiness substitute.
- ADR 0004 remains historical evidence for the resident topology, but its
  reference-only ranking prohibition is superseded.

## Migration

Add immutable candidate-target and Alpha lineage storage plus the additive
`agent.db` schema v3 evidence binding without rewriting existing evidence.
Preserve readable historical reference snapshots and never rewrite an existing
binding sidecar. Change
the normal Serenity mode from `reference` to `native`; reject retired `auto` /
`reference` as non-production selection modes rather than treating them as a
quiet compatibility fallback. Existing policy state is retained, and only its
causally allowed weight may contribute.

## Rollback

A code/image rollback must be explicit and operator-approved. It may stop new
publication, but it must not reinterpret an incomplete native target as a valid
baseline recommendation and must not delete or rewrite evidence, snapshots or
chat history.
