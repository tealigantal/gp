# Service Contract

This document describes the current public-facing service contract at a high level.

## API Surface

The current HTTP API is exposed by `src/gp_assistant/gateway/routes.py`.

Primary endpoints:

- `POST /api/chat`
- `GET /api/health`
- `GET /api/book/current`
- `GET /api/book/slot/{artifact_id}`
- `GET /api/run/{run_id}`
- `GET /api/recommend_v2`
- `POST /api/compare`
- `GET /api/pick`
- `GET /api/validation/summary`
- `GET /api/workbench`
- `GET /api/session/{session_id}`
- `GET /api/sessions`
- `GET /api/side-results`

## Chat Request

`POST /api/chat`

Request shape:

```json
{
  "session_id": "optional-session-id",
  "message": "user input"
}
```

Notes:

- `session_id` is optional on the first turn.
- `message` is required.

## Chat Response

The response model is defined in `src/gp_assistant/contracts/api.py` as `ChatResponse`.

Current top-level fields:

```json
{
  "session_id": "string",
  "reply": "string",
  "message": {},
  "run_id": "string or null",
  "symbols": [],
  "right_panel": {},
  "ui_items": [],
  "planner_trace": {},
  "evidence_refs": []
}
```

Field intent:

- `session_id`: stable conversation handle
- `reply`: primary assistant text
- `message`: structured narrative payload for the current turn
- `run_id`: current published run when the turn produces or binds one
- `symbols`: symbols relevant to the turn
- `right_panel`: compact operational summary for clients
- `ui_items`: future-facing structured UI payloads
- `planner_trace`: parse / planning trace for debugging
- `evidence_refs`: provenance references for the answer

## Health Response

`GET /api/health`

Current fields:

```json
{
  "status": "ok",
  "trading_day": "optional-string",
  "book_version": "optional-string",
  "llm_ready": true,
  "storage": {
    "session_count": 0,
    "transcript_count": 0,
    "claim_count": 0,
    "latest_session_at": null
  }
}
```

## Session Response

`GET /api/session/{session_id}`

Current shape:

```json
{
  "session": {},
  "recent_turns": [],
  "recent_claims": []
}
```

## Book Response

`GET /api/book/current`

Current shape:

```json
{
  "book": {}
}
```

The concrete `book` object is derived from `MarketBook` in `src/gp_assistant/contracts/objects.py`.

## Run Response

`GET /api/run/{run_id}`

Current shape:

```json
{
  "run": {}
}
```

The concrete `run` object is derived from `AdviceRun` in `src/gp_assistant/contracts/objects.py`.

## DecisionContextSnapshot

`DecisionContextSnapshot` is the core artifact for Market-Memory decisions. It is persisted by `src/gp_assistant/market_memory/store.py` and produced by the Market-Memory decision pipeline. Runtime judgments additionally attach `DecisionContextModel`, `ThesisLifecycle`, and `DecisionSynthesis` from `src/gp_assistant/decision_engine/intelligence.py`.

The snapshot must be treated as the source of truth for later questions such as why a stock was recommended, why another candidate was rejected, whether a user should hold/add/reduce/exit, or why the system chose wait/no-trade.

Required fields:

```json
{
  "market_context": {},
  "candidate_list": [],
  "rejected_candidates": [],
  "historical_cases": {},
  "probability_output": {},
  "risk_output": {},
  "ranking_output": [],
  "adaptive_policy_input": {},
  "adaptive_policy_output": {},
  "adaptive_policy_state_version": 1,
  "calibration_output": {},
  "llm_decision_input": {},
  "llm_decision_json": {},
  "validator_result": {},
  "narrator_input": {},
  "final_response": "string",
  "decision_context_model": {
    "market_context": {},
    "security_context": {},
    "signal_thesis_context": {},
    "user_context": {},
    "position_context": {},
    "objective": "string",
    "constraints": {}
  },
  "thesis_lifecycle": {
    "initial_thesis": "string",
    "current_thesis_state": "thesis_strengthened|thesis_unchanged|thesis_weakening|thesis_invalidated",
    "current_thesis": "string",
    "evidence_delta": [],
    "invalidation_triggers": [],
    "risk_flags": []
  },
  "decision_action": "HOLD|ADD|REDUCE|EXIT|WAIT|NO_TRADE",
  "decision_synthesis": {
    "action": "HOLD|ADD|REDUCE|EXIT|WAIT|NO_TRADE",
    "confidence": 0.0,
    "rationale": "string",
    "thesis_state": "string",
    "risk_controls": [],
    "validator_result": {}
  }
}
```

Contract rules:

- probability fields must include evidence, not only a scalar probability
- Market Memory historical cases must be retrieved by normalized feature-vector distance
- Adaptive Decision Engine is the only production selection authority after ranking
- low sample size, missing fields, high uncertainty, and ordinary risk flags must lower confidence, uncertainty, recommendation strength, or adaptive score rather than automatically causing no-trade
- risk is a score penalty unless an explicit hard block is present
- invalid symbols, fewer than 120 as-of daily bars, a missing target-day bar, stale/failed cache state, missing entry or stop plans, and non-finite ranking scores are explicit hard blocks
- backtests must use read-only as-of market data; adaptive outcomes may update policy state only after their T+5 maturity date is visible to the replay clock
- `llm_decision_input` and `llm_decision_json` may be retained for shape compatibility but must be marked `not_used_for_selection`
- the Decision Synthesizer can lower action intensity but cannot select, promote, demote, replace candidates, or invent facts
- response text must be based on validated facts from the snapshot and decision synthesis
- rejected candidates and no-trade/legacy observe decisions must remain available for counterfactual outcome tracking

## Stability Rules

- Treat `src/gp_assistant/contracts/api.py` as the source of truth for HTTP response envelopes.
- Treat `src/gp_assistant/contracts/objects.py` as the source of truth for internal structured domain models.
- Treat `DecisionContextSnapshot` plus attached decision intelligence fields as the source of truth for recommendation evidence, user-state decisions, and post-hoc explanation.
- Add new fields conservatively.
- Do not reintroduce retired `chat` or `recommend` compatibility contracts.
- Do not reintroduce old score-stack fields as ranking authority. `candidate_score`, champion, or `final_score` may appear only in legacy artifacts or migration references.
- If a client needs stronger guarantees, document the exact field-level promise near the corresponding response model rather than in a historical compatibility shim.
