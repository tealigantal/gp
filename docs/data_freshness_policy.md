# Data Freshness Policy

Daily base plans bind one completed `daily_evidence_date` and one complete full-market candidate-universe digest. They fail closed when the required daily date or full-market coverage is unavailable.

Runtime observations bind one immutable plan and one observed market phase. Their `slot_closed_at` may never be later than `observed_at`, and a publication for the same market session may not move either closed-slot time or observation time backwards.

## Lunch five-minute batch

A lunch-derived plan is eligible only from 11:32 Asia/Shanghai on its own open market session. The two-minute finality delay prevents accepting the 11:30 row at the instant its label first appears. Its batch must contain the frozen Top-30 plus CSI300, with exactly 24 ordered, unique, finite OHLCV rows per object at five-minute closes from 09:35 through 11:30. Prices must be positive, OHLC relationships valid, and aggregate volume positive.

The first production revision uses the AkShare Sina five-minute route without per-symbol fallback mixing. Collection runs in a bounded child process and is terminated when the configured total budget expires, so a weak source cannot stall the core worker. Normalized content, the base plan ID and the lunch policy revision form the new producer identity. Any source error, missing object, missing or duplicate slot, mixed date, unclosed row, null/non-finite value or invalid OHLCV rejects the whole batch. Rejection writes no lunch plan and does not change `current_publication`.

The successful lunch runtime is observed during lunch, closes at 11:30, reports the complete frozen scope, and has a deny market gate. Afternoon runtime observations may advance from that plan; an older daily or runtime task may not replace it for the same session.
