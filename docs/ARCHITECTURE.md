# GP System Architecture Index

## System Context

GP combines external market/announcement data, deterministic selection, one immutable snapshot store, a FastAPI chat service, and a chat-only Workspace.

## Current Runtime Entry Points

- `gp`: FastAPI through `gp_assistant.gateway.app`.
- `gp-worker`: unified market runtime through `gp_assistant.cli runtime-loop`.
- `web`: Workspace frontend.
- `serenity`: resident official-announcement collector/validator started by ordinary Compose.

Detailed backend decision ownership is canonical in `src/gp_assistant/ARCHITECTURE.md`; frontend structure is documented in `frontend/ARCHITECTURE.md`; HTTP/domain contracts are canonical in `docs/service_contract.md`.

## Major Components and Flow

```text
market providers -> Market Memory -> Adaptive Decision Engine
  -> immutable candidate target -> resident Serenity as-of Alpha freeze
  -> Adaptive v2 single nine-expert score
  -> RecommendationSnapshot.v1 in agent.db -> real-LLM /api/chat -> Workspace
```

Serenity is a native input lane:

```text
free official announcement sources -> serenity
  -> append-only evidence.db -> candidate-set-bound frozen Alpha feature
  -> ninth signed Adaptive expert and immutable snapshot lineage
```

## Data Ownership and Persistence

- `store/agent.db` is the only product-facing state: immutable snapshots, producer-compatible immutable daybooks, one current pointer, sessions, turns and claims. Additive database schema v3 stores explicit market-time fields alongside the retained `as_of` compatibility alias; the public snapshot contract remains `RecommendationSnapshot.v1`.
- `store/search/history.db` is the single Market Memory history database.
- Market Memory owns normalized events, decision snapshots, and prediction outcomes.
- Serenity owns immutable candidate targets, bootstrap markers, source cursors and resumable page/hydration checkpoints, per-symbol as-of coverage, persisted breakers, poll runs, append-only document metadata/content versions, Alpha feature lineage, evaluations, and policy transitions in `store/serenity/`.
- The decision path reads only candidate-bound local Serenity features and freezes them into the recommendation snapshot. Chat reads that snapshot and never re-reads a live Serenity sidecar. Only the Serenity worker performs external announcement I/O.
- `RuntimeEvidenceBinding.v1` sidecars bind each published snapshot to the exact Decision Context Snapshot, candidate target, Serenity reference/pending identifiers, freshness/readiness certificate, semantic revision and checksums. The sidecar is durable before `agent.db` advances the current pointer.

## External Integrations

Market providers currently default to AkShare. Chat routing and narration use an OpenAI-compatible LLM endpoint. Serenity uses free CNINFO discovery/PDF data with SSE/SZSE metadata for verification; these sources have no contractual SLA, so incomplete coverage blocks the native candidate set instead of silently omitting Alpha.

## Dependency Directions

Source adapters depend on HTTP and storage contracts. Decision policy depends only on frozen local Serenity signals. Runtime narration consumes bounded references after routing/judgment. External collectors must never import or invoke chat orchestration.

## Security and Trust Boundaries

Credentials remain environment-only. PDF bodies never enter routing or LLM payloads. PDFs are size-bounded and parsed in a disposable process with a 20-second wall-clock limit. Serenity may retain up to three compact verified facts internally, while the LLM narration certificate exposes at most two for each selected target. Numeric values cross the provider boundary only as opaque candidate+field+value tokens and are expanded locally into labeled capsules. Evidence IDs, timestamps, hashes, source state, target coverage, and target symbols are validated before narration. Public source failures never weaken core market-data hard blocks.

## Current Architectural Constraints

Shared Docker bind mounts use DELETE journaling. Read paths open `mode=ro`/`query_only` connections and never execute DDL, journal-mode changes, or `BEGIN IMMEDIATE`; only short write transactions use the bounded single-writer lane. Exact health/session reads wait for the real database for at most 2000 ms, release the read transaction before decoding large snapshot JSON, and return structured `storage_busy` 503 instead of a cached or stale substitute. Market Memory event versions are append-only and retrieval requires both pre-decision signal availability and a matured outcome availability day. Source-level completion is separate from candidate coverage: successful symbols advance independently, local gaps retain their own retry checkpoint, and source-level incomplete polls drive breaker/suspension metrics.

Serenity keeps two identities for different jobs. The freshness certificate contains the current poll run, checked/finished/expiry times, exact target coverage and worker lease; partial/failed polls, expiry or a dead worker fail closed immediately. `SerenitySemanticRevision.v1` hashes only the target/activation/formula/policy plus the ordered frozen facts, fact lineage, status and Alpha inputs that can change ranking or narration. An equivalent complete poll renews freshness without invalidating an immutable snapshot or an in-flight LLM turn; any real fact, correction, target, formula or effective-policy change produces a new semantic revision and requires a new snapshot.

## Known Legacy or Transitional Paths

`selection_engine/` remains for migration reference and low-level helpers. Historical archive docs are not current contracts. Historical replay/backtest cannot read or write the production Serenity store and must use explicitly frozen as-of Alpha fixtures when validating the native formula. Backfilled announcement facts remain non-binding. Retained version history separates decision trade day, daybook effective day, observed time and generation time.

## Target Direction

Keep collection network I/O isolated from selection and chat, bind complete as-of Serenity coverage to the deterministic candidate set, score once, and expose the resulting immutable evidence and contribution through real-LLM grounded conversation.

## Canonical current publication

All Python Compose services run `gp-backend:<tag>`. The API publishes a producer contract containing revision, source digest, artifact schema, and selection policy. Operational jobs must match it before writing.

The worker validates a daybook/slot bundle, durably writes its evidence binding, then publishes an immutable `RecommendationSnapshot.v1`, daybook and current pointer in one final `agent.db` transaction. The only public consumers are `POST /api/chat`, `GET /api/chat/{session_id}`, and `GET /api/health`; no recommendation, compare, pick, run or Workbench endpoint forms a second product surface. A session remains bound to its immutable snapshot, and any non-current snapshot is historical for execution purposes. Existing-session explanations may continue to read that immutable evidence after the live Serenity semantic revision advances, but the reply is `snapshot_explanation_only`, non-tradeable and never an execution authorization.

Each successful chat has two required logical LLM stages: intent routing and evidence narration. Routing may repair invalid JSON, and narration may make one additional real `tool_evidence_repair` call when the first draft violates the same authority validator. Rejected drafts are neither shown nor persisted; every provider call needed by the committed turn carries a successful status, request/response model and response ID.
