# Historical Replay and AB Validation

Last updated: 2026-07-11

This document records the current validation method for the Market-Memory Agent.
The goal is to evaluate the full decision system, including no-trade and rejected-candidate behavior, not only whether an endpoint returns symbols.

## Replay Flow

For each historical trading day `T`, the replay runner executes:

```text
freeze T-visible daily data
  -> signal detection
  -> normalized feature-vector fingerprint
  -> Market Memory nearest-case retrieval
  -> probability inference
  -> risk assessment
  -> ranking
  -> Adaptive Decision Engine
  -> DecisionContextModel
  -> Thesis Lifecycle
  -> Decision Synthesizer
  -> validator
  -> decision artifact
  -> T+1/T+3/T+5 verification
```

Time-travel controls:

- daily bars for signal generation use `as_of=T`
- Market Memory retrieval only uses events with `event.as_of < T`
- historical signal outcomes are inserted only when their forward window would already be knowable by `T`
- future T+1/T+3/T+5 outcomes are loaded only after the recommendation artifact is generated
- replay can set `GP_MARKET_MEMORY_DIR` to isolate event memory and snapshots from production runtime state
- default replay does not update adaptive policy state
- with `--update-policy-state` or `--mode causal-adaptive`, policy updates remain queued until the replay clock reaches the outcome's T+5 `matured_at` date

## Command

```powershell
$env:GP_MARKET_MEMORY_DIR = "$env:TEMP\gp_market_memory_replay_events"
$env:PYTHONPATH = "src"
python -m gp_assistant.evaluation_engine.historical_replay `
  --days 20260105 20260106 20260107 20260108 20260109 20260112 20260113 20260114 20260115 20260116 20260119 20260120 20260121 20260122 20260123 20260127 `
  --topk 3 `
  --max-symbols 12 `
  --output-name historical_replay_ab_202601_top3
```

Optional adaptive policy update mode:

```powershell
python -m gp_assistant.evaluation_engine.historical_replay `
  --days 20260105 20260106 `
  --topk 3 `
  --max-symbols 12 `
  --update-policy-state
```

Generated JSON is written under `results/market_memory_validation/` and is treated as a local runtime artifact.

### Full local-history replay

The full runner reads `store/search/history.db` through SQLite read-only mode, reconstructs the eligible main-board universe and market breadth at each historical date, never calls a provider, and writes all mutable state below an isolated checkpoint directory.

## Coverage trust boundary after 2026-07-09

Production candidate snapshots from 2026-07-09 through the first successfully validated `MarketUniverseSnapshot.v1` are coverage-unverified. They may be retained and read for audit, but must not be labelled full-market, promoted back to current, or used as tradeable recommendations. No synthetic universe is backfilled for that interval.

```powershell
$env:PYTHONPATH = "src"
python -m gp_assistant.evaluation_engine.historical_replay `
  --history-db store/search/history.db `
  --start 2020-01-01 `
  --end 2026-06-30 `
  --topk 3 `
  --full-max-symbols 200 `
  --min-history 120 `
  --min-universe 100 `
  --friction-bps 30 `
  --mode static `
  --offline `
  --checkpoint-dir results/market_memory_validation/full_static_checkpoint `
  --output-name full_static_replay
```

Use `--resume` after interruption. Run `--mode causal-adaptive` into a different checkpoint directory; that mode is evaluation-only and does not enable production policy updates.

Every eligible main-board symbol contributes to the historical breadth and liquidity ranking. The default then evaluates the top 200 causal liquidity candidates, matching the production dynamic-pool scale; use `--full-max-symbols 0` only for the substantially more expensive exhaustive scoring pass.

The report splits valid dates chronologically into 60% development, 20% validation, and 20% holdout. Acceptance requires at least 250 holdout days and 500 filled picks, positive Top1/Top3 net T+3 returns after 30 bps friction, non-inferiority to the deterministic current-main baseline, bounded drawdown, Brier score at or below 0.25, and reasonable strength/data-quality cohort ordering.

## Latest Local Result

### 2026-07-11 integration preflight

- The real read-only history DB path completed an offline full-market smoke: 3,038 symbols were eligible on the checked day, breadth used all 3,038, and the causal liquidity prefilter sent 12 symbols to scoring.
- Checkpoint resume completed without duplicate rows.
- A 17-day engineering preflight did not satisfy the release metrics, but its holdout contained only four days and is not treated as a performance conclusion.
- The Adaptive branch remains blocked from `main` until the full holdout reaches at least 250 valid days and every acceptance check passes.
- Docker image validation was not run because the local Docker Desktop Linux engine was unavailable; no running production container was changed.

### Pre-adaptive reference result

The following result predates the Adaptive Decision Engine replacement and reflects the retired gate behavior. New replay reports should additionally inspect adaptive score buckets, recommendation-strength groups, exploratory picks, and cautious picks.

Dataset:

- 16 historical trading days from January 2026
- Top 3 comparison
- maximum 12 replay universe symbols per day
- daily bars loaded from local cache in cache-only mode
- legacy baseline used local historical candidate-pool ordering

The old selection engine was not rerun by default because it can request provider/network data and attempted external fetches during validation. The report therefore compares the new decision system against the local historical legacy candidate-pool baseline without fabricating old `candidate_score`, champion, or `final_score` values.

| Metric | Legacy candidate-pool baseline | Market-Memory Agent |
| --- | ---: | ---: |
| decision counts | 16 recommend | 4 recommend, 12 observe under retired gate behavior |
| recommendation coverage | 100.00% | 25.00% |
| evaluated recommended picks | 48 | 4 |
| Top1 T+1 average return | -0.9527% | 0.1197% |
| Top1 T+3 average return | -2.0411% | -1.3529% |
| Top1 T+5 average return | -2.1419% | -2.4026% |
| Top3 T+3 average return | -1.4377% | -1.3529% |
| worst max drawdown | -9.5533% | -6.1074% |
| max consecutive Top1 T+3 losses | 13 | 2 |
| recommended-pick win rate | 20.83% | 25.00% |
| average regret T+3 | 1.5988% | 1.1325% |
| rejected candidate T+3 average return | -0.8438% | -1.1850% |
| alternative candidate T+3 average return | -0.8531% | -1.3006% |
| no-trade / observe days | 0 | 12 under retired gate behavior |
| no-trade avoided-loss days | 0 | 5 |
| no-trade missed-opportunity days | 0 | 7 |
| no-trade best alternative T+3 average | n/a | 0.2875% |

Interpretation:

- The new system traded less often and avoided many weak days.
- On this small sample, it improved Top1 T+1/T+3 return, Top3 T+3 return, worst drawdown, consecutive losses, win rate, and regret.
- It underperformed on Top1 T+5 average return and missed opportunities on 7 observe days under the retired gate behavior.
- This is not enough to claim universal superiority. It is evidence from the pre-adaptive system that selectivity affected risk and missed opportunities; the current system should be judged by adaptive score and recommendation-strength performance as well as calibration.

## Calibration

Market-Memory Agent probability evaluation:

- calibration sample size: 192 candidate/outcome pairs
- Brier score: `0.2465254294485468`
- 0.3-0.4 bucket: mean predicted 39.20%, realized win rate 0.00%, count 3
- 0.4-0.5 bucket: mean predicted 45.84%, realized win rate 20.69%, count 87
- 0.5-0.6 bucket: mean predicted 52.67%, realized win rate 24.51%, count 102

Current conclusion:

- probabilities are evidence-backed but overconfident on this sample
- all evaluated candidates fell into the 30-80 effective-sample bucket
- calibration quality must be monitored before treating predicted probability as a standalone trading edge
- adaptive reports should compare calibrated probability, adaptive score buckets, exploratory picks, and cautious picks against realized outcomes

## Failure Attribution

Failure attribution is recorded per evaluated recommendation, rejected candidate, and alternative candidate.

Observed failure distribution in the latest replay sample:

- `market_regime_change`: 58
- `risk_estimation_failure`: 21

Example evidence block fields available per candidate:

- `sample_size`
- `effective_sample_size`
- `mean_similarity`
- `success_distribution`
- `major_failure_modes`

The system must use these fields when explaining adaptive recommendation strength, rejected candidates, legacy observe payloads, or true no-trade hard blocks.

## Limitations

- This run is a local historical replay, not live trading proof.
- The sample is small and concentrated in January 2026.
- The legacy comparison is a local candidate-pool baseline because rerunning old selection logic can pull current/provider data.
- Pre-adaptive low trade coverage should not be projected onto the current system; current reports should read return metrics alongside adaptive-strength buckets and true no-trade hard-block counts.
- Calibration is currently imperfect and should remain visible in every probability-backed decision.
