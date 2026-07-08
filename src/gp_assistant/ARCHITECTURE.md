# GP Assistant Architecture

GP is a market-memory investment decision agent for A-share short-term daily plans.
The production recommendation path is no longer a rule score stack. It is:

```text
Market Data
  -> Signal Engine
  -> Market Memory
  -> Probability Engine
  -> Risk Engine
  -> Ranking
  -> LLM Risk Committee
  -> Validator
  -> Narrator
  -> DecisionContextSnapshot
```

## Core Boundaries

- `signal_engine/`: converts daily OHLCV history into structural signal events and normalized numeric feature vectors. Signals describe market structure; they are not buy rules.
- `market_memory/`: stores market-memory events and decision snapshots. Similarity retrieval is based on normalized feature-vector distance. Labels such as signal type or regime may adjust weights, but cannot replace vector distance.
- `probability_engine/`: infers probability from nearest historical cases using similarity-weighted statistics and Bayesian shrinkage. Every output carries an evidence block with sample size, effective sample size, similarity, success/failure distribution, uncertainty, and failure modes.
- `risk_engine/`: computes execution quality, stop/take levels, drawdown risk, and mathematical ranking. The ranking engine owns expected return, win probability, risk adjustment, and confidence.
- `decision_engine/`: runs the complete decision pipeline. The LLM is a risk committee: it can downgrade, observe, or reject, but it cannot promote candidates outside the mathematical ranking or invent market facts.
- `evaluation_engine/`: runs historical replay, AB validation, calibration reports, outcome tracking, counterfactual analysis, regret analysis, and prediction-error attribution.

## Runtime Spine

- `gateway/`: FastAPI entry and HTTP routes.
- `runtime/`: conversation turn loop, reference resolution, canonical artifact assembly, and user-safe reply assembly.
- `book/`: daybook, market board, and optional intraday pulse artifacts.
- `judgment/`: user-facing workflows for recommend, detail, compare, exit, no-trade, and run-change answers.
- `evidence/`: service-facing bridge into market facts, current recommendation, validation, portfolio, and universe state.
- `kernel/`: facade for API-facing service calls.

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
- `llm_decision_input`
- `llm_decision_json`
- `validator_result`
- `narrator_input`
- `final_response`

## LLM Permission Boundary

The LLM is not the portfolio manager and not the ranking authority.

It may:

- return `recommend`, `observe`, or `no_trade`
- downgrade or reject a mathematically ranked candidate
- point out evidence gaps, risk flags, low confidence, and abnormal context

It must not:

- promote a lower-ranked candidate above the math ranking
- modify prices, probabilities, returns, samples, or risk facts
- create historical cases or market facts
- combine decision and final explanation in one step

The flow is:

```text
Decision JSON -> Validator -> Narrator
```

## Historical Validation

Historical replay simulates the full agent, not a single strategy. For each replay day, the runner freezes data available at that date, builds signals, retrieves market memory cases with `event.as_of < T`, estimates probabilities, ranks candidates, runs the risk committee, records the decision artifact, and then verifies T+1/T+3/T+5 outcomes.

See `docs/historical_validation.md` for commands and the latest local AB result.
