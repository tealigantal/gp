# GP Assistant Architecture

GP is a market-memory investment decision agent for A-share short-term daily plans.
The production path is no longer centered on "which stock looks good". It is centered on whether a concrete user decision is reasonable under the current market, security, thesis, user, position, objective, and constraint context.

```text
Market Data
  -> Signal Engine
  -> Market Memory
  -> Probability Engine
  -> Risk Engine
  -> immutable candidate target
  -> candidate-bound Serenity as-of Alpha
  -> Adaptive single nine-expert score
  -> DecisionContextSnapshot
  -> RecommendationSnapshot.v1
  -> real-LLM TurnFrame routing and grounded narration
```

## Core Boundaries

- `signal_engine/`: converts daily OHLCV history into structural signal events and normalized numeric feature vectors. Signals describe market structure; they are not buy rules.
- `market_memory/`: stores market-memory events and decision snapshots. Similarity retrieval is based on normalized feature-vector distance. Labels such as signal type or regime may adjust weights, but cannot replace vector distance.
- `probability_engine/`: infers probability from nearest historical cases using similarity-weighted statistics and Bayesian shrinkage. Every output carries an evidence block with sample size, effective sample size, similarity, success/failure distribution, uncertainty, and failure modes.
- `risk_engine/`: computes execution quality, stop/take levels, drawdown risk, and mathematical ranking. Risk facts are penalties for adaptive scoring, not automatic rejection gates.
- `decision_engine/`: publishes the immutable candidate target, loads exact as-of Serenity signals, and runs Adaptive once with nine experts. Local code fixes selection, action, prices and risk; the LLM has no decision JSON authority.
- `evaluation_engine/`: runs historical replay, AB validation, calibration reports, outcome tracking, counterfactual analysis, regret analysis, and prediction-error attribution.

## Runtime Spine

- `gateway/`: FastAPI entry and HTTP routes.
- `runtime/`: market-time resolution, worker publication, reference resolution, canonical artifact assembly, and user-safe reply assembly.
- `book/`: daybook, market board, and optional intraday pulse artifacts.
- `judgment/`: user-facing workflows for recommend, detail, compare, exit, no-trade, and run-change answers.
- `evidence/`: service-facing bridge into market facts, current recommendation, validation, portfolio, and universe state.
- `kernel/`: facade for API-facing service calls.
- `serenity/`: resident official-evidence collection, verification, append-only persistence, candidate-set coverage, and frozen Alpha features. Serenity is the ninth bounded signed input to the one Adaptive score; it has no independent post-hoc ranker and no authority over prices, probabilities, or actions.

## DecisionContextModel

Every market-facing turn is converted into one structured decision context instead of a keyword-specific answer path.

The model contains:

- `market_context`
- `security_context`
- `signal_thesis_context`
- `user_context`
- `position_context`
- `objective`
- `constraints`

The same model is used for "can I buy", "I already bought", "what if it drops", "what if it is profitable", "why not another one", and "was the previous system judgment wrong".

## Thesis Lifecycle

Each recommendation or follow-up decision carries:

```text
Initial Thesis -> Current Thesis State -> Decision
```

Allowed thesis states:

- `thesis_strengthened`
- `thesis_unchanged`
- `thesis_weakening`
- `thesis_invalidated`

The action is derived from the thesis state plus user objective, position context, and adaptive action. Low samples, missing fields, high uncertainty, and ordinary risk flags lower confidence or action intensity; they do not by themselves create `NO_TRADE`. An invalidated thesis maps to `EXIT` for an existing position and to `NO_TRADE` for a new-entry question.

## DecisionContextSnapshot

Every decision persists a complete snapshot under Market Memory storage. The snapshot is the source of truth for future questions such as why a stock was recommended months ago.

Required snapshot fields include:

- `market_context`
- `candidate_list`
- `rejected_candidates`
- `historical_cases`
- `probability_output`
- `risk_output`
- `ranking_output`
- `adaptive_policy_input`
- `adaptive_policy_output`
- `adaptive_policy_state_version`
- `calibration_output`
- `llm_decision_input`
- `llm_decision_json`
- `validator_result`
- `narrator_input`
- `final_response`

The retained `llm_decision_*` fields are compatibility/audit placeholders. They
do not grant the chat LLM selection, numerical or action authority in the
current single-protocol runtime.

## LLM Permission Boundary

The LLM is not a stock picker, not the ranking authority, and not allowed to invent explanation facts. It does not select, promote, demote, or replace recommended symbols.

Selection is owned by the Adaptive Decision Engine. It consumes ranked candidates, missing-aware features, calibrated probability, risk penalties, setup quality, market regime, exploration pressure, and a candidate-bound as-of Serenity Alpha feature. Complete known-empty Serenity coverage is neutral; incomplete coverage blocks publication and cannot switch to an eight-expert fallback. Risk flags reduce adaptive score or recommendation strength unless an explicit hard block is present.

For chat work, the LLM has two mandatory logical stages. The first emits only a `TurnFrame` intent and may use one real repair request for invalid JSON. Local code derives the request scope, current/historical state, decision and action from the bound snapshot. The second emits Chinese narration over bounded `tool_evidence_context`; if the first draft violates authority validation, one real `tool_evidence_repair` request may regenerate it. Every actual call required by the committed turn must carry real 2xx/provider model/response-ID evidence, and the final narration must pass symbol, candidate+field numeric, action and grounding checks. Rejected drafts are not displayed or persisted.

Narration sees a compact certificate, not the full snapshot. Each selected
candidate contributes at most two Serenity facts. Numeric display values are
opaque GPVAL candidate+field+value tokens at the provider boundary and are
expanded only by local code into labeled capsules. Raw provider-written
numbers, cross-candidate reuse, cross-field reuse and unauthorized actions fail
closed.

It may:

- classify the user's semantic request without inventing symbols or refresh scope
- explain the locally fixed recommendation/no-trade result and its risk boundary
- point out evidence gaps, risk flags, low confidence, and abnormal context

It must not:

- select, promote, demote, or replace candidates
- modify prices, probabilities, returns, samples, or risk facts
- create historical cases or market facts
- emit or change a trading action
- combine routing and final explanation in one call

The flow is:

```text
LLM TurnFrame -> local snapshot judgment -> LLM narration -> authority/grounding validation -> atomic turn commit
```

## Atomic Runtime Publication and Health Reads

The public snapshot contract remains `RecommendationSnapshot.v1`; the product
database uses additive schema v3. The worker writes an immutable
`RuntimeEvidenceBinding.v1` sidecar first, then commits the daybook, snapshot and
current pointer in one final `agent.db` transaction. A session never changes its
bound snapshot. Existing-session explanations may keep reading that immutable
evidence after live Serenity advances, but are marked
`snapshot_explanation_only`, non-tradeable and action `WAIT`.

Read paths use real `mode=ro`/`query_only` connections. Health waits at most
2000 ms, fetches the raw current row and counters, ends the transaction, and
only then decodes the large JSON payload. Persistent contention returns
structured `storage_busy` 503; no cache or older snapshot substitutes for the
real state.

## Historical Validation

Historical replay simulates the full agent, not a single strategy. For each replay day, the runner freezes data available at that date, builds signals, retrieves market memory cases with `event.as_of < T`, estimates probabilities, ranks candidates, synthesizes a validated decision, records the decision artifact, and then verifies T+1/T+3/T+5 outcomes.

Replay can optionally update adaptive policy state after a day's payload has been generated and its outcomes have been evaluated. Default replay mode is evaluation-only and does not mutate the production policy state.

See `docs/historical_validation.md` for commands and the latest local AB result.
