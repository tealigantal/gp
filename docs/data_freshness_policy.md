# Data Freshness Policy

Daily base plans bind one completed `daily_evidence_date` and one complete full-market candidate-universe digest. They fail closed when the required daily date or full-market coverage is unavailable.

Once that exact daily run is complete, its next-session base plan is eligible from 15:20 on the evidence date until 09:30 of the target open session. The overnight portion is intentional: a self-healing run that completes after midnight must still create the target-session plan before the market opens. The worker never backfills a new base plan during the target session's continuous trading period.

The worker checks the next-session base-plan deadline both before and after full-market computation. If calculation crosses 09:30, the result is retained only as an unpinned immutable audit artifact and cannot become the public plan during continuous trading.

Once a daily source is ready, the worker finishes every unattempted persisted batch before it schedules a retry. Network requests remain bounded by their source timeout and route policy; a total wall-clock budget may not cut a healthy full-market scan into an artificial wait period. Each batch rereads exact target-date rows through a half-open date range on the indexed `(query_id,item_time)` pair and records only that batch's status transition; this is an implementation of the same exact-coverage contract, not a looser cache shortcut.

The required daily date must appear exactly for every expected-tradable symbol; a nonempty older response is not refresh success. The raw main-board count never shrinks for suspension. A symbol may leave only the target-date coverage denominator through one of two auditable facts: (1) a reused spot snapshot that is fresh, belongs to that exact session, contains every required field, has positive previous close, and reports zero price, OHLC, volume and amount; or (2) after normal daily-data sources have tried a bounded remaining set, an official CNINFO disclosure published no later than the target session open whose PDF explicitly says that the exact target date opens suspended and whose listing is independently verified at the relevant exchange. The latter is stored per symbol with source record ID, URL, publication time, document digest, verification basis and excerpt. Missing rows, stale fallback, cross-day snapshots, incomplete fields, a late announcement, an unreadable PDF, or ambiguous wording cannot prove suspension. Readiness requires 100% exact-date coverage after storage is reread.

Runtime observations bind one immutable plan and one observed market phase. Their `slot_closed_at` may never be later than `observed_at`, and a publication for the same market session may not move either closed-slot time or observation time backwards.

## Lunch five-minute batch

A lunch-derived plan is eligible only from 11:32 Asia/Shanghai on its own open market session. The two-minute finality delay prevents accepting the 11:30 row at the instant its label first appears. Its batch must contain the frozen Top-30 plus CSI300, with exactly 24 ordered, unique, finite OHLCV rows per object at five-minute closes from 09:35 through 11:30. Prices must be positive, OHLC relationships valid, and aggregate volume positive.

The first production revision uses the AkShare Sina five-minute route without per-symbol fallback mixing. Collection runs in a bounded child process and is terminated when the configured total budget expires, so a weak source cannot stall the core worker. Normalized content, the base plan ID and the lunch policy revision form the new producer identity. Any source error, missing object, missing or duplicate slot, mixed date, unclosed row, null/non-finite value or invalid OHLCV rejects the whole batch. Rejection writes no lunch plan and does not change `current_publication`.

The successful lunch runtime is observed during lunch, closes at 11:30, reports the complete frozen scope, and has a deny market gate. Afternoon runtime observations may advance from that plan; an older daily or runtime task may not replace it for the same session.
