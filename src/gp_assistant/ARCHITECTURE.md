# GP Assistant Architecture

GP is a market-memory investment decision agent for A-share short-term daily plans.
The production path is no longer centered on "which stock looks good". It is centered on whether a concrete user decision is reasonable under the current market, security, thesis, user, position, objective, and constraint context.

```text
Market Data
  -> Signal Engine
  -> Market Memory
  -> Probability Engine
  -> Risk Engine
  -> Ranking
  -> Adaptive Decision Engine
  -> Decision Intelligence
  -> Thesis Lifecycle
  -> Decision Synthesizer
  -> Validator
  -> DecisionContextSnapshot
  -> Response
```

## Core Boundaries

- `signal_engine/`: converts daily OHLCV history into structural signal events and normalized numeric feature vectors. Signals describe market structure; they are not buy rules.
- `market_memory/`: stores market-memory events and decision snapshots. Similarity retrieval is based on normalized feature-vector distance. Labels such as signal type or regime may adjust weights, but cannot replace vector distance.
- `probability_engine/`: infers probability from nearest historical cases using similarity-weighted statistics and Bayesian shrinkage. Every output carries an evidence block with sample size, effective sample size, similarity, success/failure distribution, uncertainty, and failure modes.
- `risk_engine/`: computes execution quality, stop/take levels, drawdown risk, and mathematical ranking. Risk facts are penalties for adaptive scoring, not automatic rejection gates.
- `decision_engine/`: runs the Adaptive Decision Engine as the only production selection authority, then builds `DecisionContextModel`, evaluates thesis lifecycle, synthesizes the user-facing action, validates action boundaries, and attaches decision fields to all judgment artifacts. The synthesizer may output only `HOLD`, `ADD`, `REDUCE`, `EXIT`, `WAIT`, or `NO_TRADE`.
- `evaluation_engine/`: runs historical replay, AB validation, calibration reports, outcome tracking, counterfactual analysis, regret analysis, and prediction-error attribution.

## Runtime Spine

- `gateway/`: FastAPI entry and HTTP routes.
- `runtime/`: conversation turn loop, reference resolution, canonical artifact assembly, and user-safe reply assembly.
- `book/`: daybook, market board, and optional intraday pulse artifacts.
- `judgment/`: user-facing workflows for recommend, detail, compare, exit, no-trade, and run-change answers.
- `evidence/`: service-facing bridge into market facts, current recommendation, validation, portfolio, and universe state.
- `kernel/`: facade for API-facing service calls.

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

## LLM Permission Boundary

The LLM is not a stock picker, not the ranking authority, and not allowed to invent explanation facts. It does not select, promote, demote, or replace recommended symbols.

Selection is owned by the Adaptive Decision Engine. It consumes ranked candidates, missing-aware features, calibrated probability, risk penalties, setup quality, market regime, and exploration pressure. Missing data is recorded as a feature, not silently filled as evidence. Risk flags reduce adaptive score or recommendation strength unless an explicit hard block is present.

For decision work, the LLM role is Decision Synthesizer. It consumes the structured `DecisionContextModel` and `ThesisLifecycle`, then emits a bounded action JSON that the validator checks.

It may:

- return `HOLD`, `ADD`, `REDUCE`, `EXIT`, `WAIT`, or `NO_TRADE`
- lower action intensity when evidence, user state, position state, or thesis lifecycle does not support the stronger action
- point out evidence gaps, risk flags, low confidence, and abnormal context

It must not:

- select, promote, demote, or replace candidates
- modify prices, probabilities, returns, samples, or risk facts
- create historical cases or market facts
- combine decision and final explanation in one step

The flow is:

```text
DecisionContextModel -> ThesisLifecycle -> Decision JSON -> Validator -> Response Renderer
```

## Historical Validation

Historical replay simulates the full agent, not a single strategy. For each replay day, the runner freezes data available at that date, builds signals, retrieves market memory cases with `event.as_of < T`, estimates probabilities, ranks candidates, synthesizes a validated decision, records the decision artifact, and then verifies T+1/T+3/T+5 outcomes.

Replay can optionally update adaptive policy state after a day's payload has been generated and its outcomes have been evaluated. Default replay mode is evaluation-only and does not mutate the production policy state.

See `docs/historical_validation.md` for commands and the latest local AB result.
