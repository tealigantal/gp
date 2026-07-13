# Research Log

## 2026-07-11 — Free official data for Serenity Alpha

- **Question:** Can GP obtain free, stable enough data for a real official-announcement Alpha experiment?
- **Checked date:** 2026-07-11.
- **Applicable version:** GP branch `codex/merge-adaptive-decision-engine`; AkShare 1.18.24; public CNINFO/SSE/SZSE interfaces observed on the checked date.
- **Official sources:** CNINFO public disclosure and Data Service, SSE/SZSE disclosure pages and legal notices, RQData PIT documentation, Tushare agreement, AkShare usage statement.
- **Open-source implementations compared:** AkShare, Tushare, BaoStock, FinGPT, TradingAgents, and AI Hedge Fund at the architectural level.
- **Maintenance and release status:** Public exchange/CNINFO web schemas are not contractual APIs. Local AkShare trails the observed documentation release and its news wrapper is a small latest-page view.
- **License:** Free public sources are treated as local non-commercial research inputs. Commercial or redistributed use requires a separate license review.
- **Relevant pattern:** Official metadata discovery, immutable first-seen/version storage, local PDF extraction, deterministic high-confidence hypotheses, local-only decision reads, and dual-source verification.
- **Limitations:** Recent announcement times may be date-only; historical CDN timestamps are not first-seen evidence; old public coverage is incomplete; scanned PDFs need OCR that v1 omits.
- **Applicability:** Suitable for a forward-only experiment and target-specific narration. Not sufficient for a production SLA or broad-media news claims.
- **Decision:** Use CNINFO as the primary free discovery/PDF source, SSE/SZSE as verification, isolate collection in `gp-serenity-worker`, and permit automatic ranking influence only after the recorded causal gates pass.
- **Implemented observation:** A real 30-day `000001` bootstrap on 2026-07-11 completed four requests and two PDF records in 3.64 seconds. Neither record matched a high-confidence scoring category, so the system stored provenance and reported zero facts instead of fabricating Alpha.
- **Positive real-data observation:** An isolated `000977` bootstrap returned two official PDF records. One 2026-07-08 earnings-guidance filing was confirmed through the exchange verifier and deterministically produced `direction=+1`, `confidence=0.92`, and `source_quality=1`. It was visible as reference evidence immediately but remained `backfill_only=true`, `learning_eligible=false`, and applied weight 0%.
- **Operational observation:** The observed 3.64-second run produced a closed-session 1,800-second delay. Later intervals remain a function of last cost, EWMA, p90, phase bounds, backlog, `Retry-After`, and failure state.
- **Verification rule:** CNINFO PDF evidence is retained, but a fact is not `verified` or scoring-eligible unless the corresponding SSE/SZSE metadata check succeeds. Verification failure is unknown, not weak confirmation.
- **Correction rule:** Backfill relations never affect scoring. A live correction freezes only an exact fact ID or matching earnings-report-period key; an unresolved live relation with no trustworthy target zeros only that symbol's Serenity contribution until resolved, leaving baseline Adaptive untouched.
# 2026-07-13 — recommendation-engine database input audit

Evidence inspected locally, without external research:

- The selection pipeline takes current OHLCV through `MarketDataHub`, writes historical signal events to `market_memory.db`, and retrieves only events with `as_of < decision_as_of` and `outcome.complete=true`.
- Each retrievable event supplies normalized feature vectors, raw features, market-regime context, realized outcomes, and data provenance. Retrieval is normalized feature-vector distance; matching signal/regime labels are small adjustments only.
- Probability consumes retrieved outcomes and priors; risk consumes the candidate signal/probability; adaptive policy owns final selection. The LLM has no selection authority.
- The product-facing snapshot is a projection of the daybook, not a second decision source. It carries rank, entry/stop/take-profit plans, probability/evidence, risk flags, scoring, and evidence references.

Conclusion: the evidence architecture is appropriate for a professional decision-support agent, but the observed production data is not currently fresh enough to issue a professional recommendation. The correct current response is `no_trade` until the worker refreshes and validates the next trading-day data.
