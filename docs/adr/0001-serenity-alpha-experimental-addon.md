# ADR 0001 — Serenity Alpha Experimental Add-on

- **Status:** Accepted for implementation
- **Date:** 2026-07-11

## Context

GP needs a real official-announcement dimension using free data. It must be visible immediately but must not silently become a hard rule or contaminate the existing eight-expert Adaptive weights. Public endpoints have weak availability/time guarantees and historical first-seen data is unreliable.

## Considered Options

1. Add Serenity as a ninth Adaptive expert immediately.
2. Provide narration-only announcement facts forever.
3. Use a separate zero-able add-on with shadow counterfactuals and gated automatic promotion.

## Decision

Choose option 3. Collection runs in an independent worker and append-only store. Baseline `adaptive_score` remains unchanged. A separate `decision_score` may include `w × availability × direction × confidence × source_quality`, with `w` between 0% and 8%. Binding availability additionally requires a live, double-source-verified, unexpired fact. Backfill uses separate reference arms that can never bind or train the policy. State advances through shadow, probation, active, and suspended using only forward outcomes finalized on the trading day after T+5.

## Rationale

This provides immediate real evidence and measurable counterfactual value, represents a true zero-weight state, preserves the original experts, and supports automatic rollback when source or performance quality deteriorates.

## Consequences

The deployment gains separate bootstrap/worker profiles, a SQLite store, process-isolated PDF parser, health surface, and atomic policy/evaluation ledger. Promotion cannot be demonstrated by historical backfill and therefore takes forward time. LLM narration must distinguish backfill reference, shadow evidence, and active computed contribution. A binding decision fails closed if its v2 reference snapshot (including explicit trading day and frozen risk plans) cannot be atomically frozen with its pending evaluation.

## Migration

Old policy state loads with Serenity shadow/0% defaults. Chat responses remain compatible. ReferenceSnapshot v2 is intentionally fail-closed; no v1 pending/reference records existed at migration time. The experiment profile bootstraps real evidence before exposing ready state.

## Rollback

Set Serenity mode off or suspend the policy, atomically applying 0% weight. Stop the experimental worker. Base Adaptive selection and existing stores continue unchanged.
