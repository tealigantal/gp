# GP System Architecture Index

## System Context

GP combines external market/announcement data, local immutable/runtime stores, deterministic decision engines, an LLM routing/narration boundary, a FastAPI service, and a single-page Workspace.

## Current Runtime Entry Points

- `gp`: FastAPI through `gp_assistant.gateway.app`.
- `gp-worker`: unified market runtime through `gp_assistant.cli runtime-loop`.
- `web`: Workspace frontend.
- Ops profiles: daybook rebuild and post-close archive.
- `gp-serenity-worker`: experimental collector/evaluator under the Compose `experiments` profile.
- `gp-serenity-bootstrap`: one-shot real 30-day bootstrap under the separate `serenity-bootstrap` profile, so enabling the worker cannot race the bootstrap.

Detailed backend decision ownership is canonical in `src/gp_assistant/ARCHITECTURE.md`; frontend structure is documented in `frontend/ARCHITECTURE.md`; HTTP/domain contracts are canonical in `docs/service_contract.md`.

## Major Components and Flow

```text
market providers -> local cache -> signal/memory/probability/risk
  -> Adaptive Decision Engine -> Decision Intelligence -> snapshot
  -> judgment -> bounded LLM narration -> API/Workspace
```

Serenity adds a separate path:

```text
free official announcement sources -> gp-serenity-worker
  -> append-only evidence.db -> frozen Serenity signal
  -> shadow/counterfactual add-on -> gated ranking influence
  -> target-only narration evidence
```

## Data Ownership and Persistence

- Existing market cache and books remain under `store/` and `cache/`.
- Market Memory owns normalized events, decision snapshots, and prediction outcomes.
- Serenity owns bootstrap markers, source cursors and resumable page/hydration checkpoints, per-symbol coverage, persisted breakers, poll runs, append-only document metadata/content versions, hypotheses, v2 reference snapshots, evaluations, and policy transitions in `store/serenity/`.
- Decision and chat paths read Serenity locally; only the Serenity worker performs external announcement I/O.

## External Integrations

Market providers currently default to AkShare. LLM calls use an OpenAI-compatible endpoint. Serenity v1 uses free CNINFO discovery/PDF data with SSE/SZSE metadata for verification; these sources are experimental and have no contractual SLA.

## Dependency Directions

Source adapters depend on HTTP and storage contracts. Decision policy depends only on frozen local Serenity signals. Runtime narration consumes bounded references after routing/judgment. External collectors must never import or invoke chat orchestration.

## Security and Trust Boundaries

Credentials remain environment-only. PDF bodies never enter routing or LLM payloads. PDFs are size-bounded and parsed in a disposable process with a 20-second wall-clock limit. Only the selected target's maximum three compact verified facts may enter narration. Evidence IDs, timestamps, hashes, source state, target coverage, and target symbols are validated before narration. Public source failures never weaken core market-data hard blocks.

## Current Architectural Constraints

Shared Docker bind mounts require one Serenity writer, a renewable owner lease, and short SQLite WAL transactions. Existing `history.db` overwrites records and therefore cannot store evidence versions. Current book JSON writes are not atomic, so Serenity target discovery uses validated double reads plus a bounded last-stable-target fallback. Source-level completion is separate from candidate coverage: successful symbols advance independently, local gaps retain their own retry checkpoint, and source-level incomplete polls drive breaker/suspension metrics.

## Known Legacy or Transitional Paths

`selection_engine/` remains for migration reference and low-level helpers. Historical archive docs are not current contracts. Historical replay/backtest explicitly disables Serenity and cannot read or write its production store. Backfilled announcement facts may appear in narration and a clearly non-binding reference counterfactual, but binding arms and promotion statistics require a live forward fact. Every learning reference freezes the pipeline trading day separately from its generation timestamp, preventing UTC/calendar rebuilds from creating duplicate samples.

## Target Direction

Keep evidence collection isolated, preserve a permanent 0% baseline, and allow the Serenity add-on to move from shadow to bounded automatic weight only through immutable causal evaluations and automatic rollback.
