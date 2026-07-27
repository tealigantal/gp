# Worker daily-refresh gate repair

## Goal

Stop a valid base plan from starting a full-market daily-K refresh merely because no lunch rerank was published, while preserving exact target-date recovery after close.

## Scope

- Bind the worker gate to the current plan target (market session plus required daily evidence date), not to lunch-plan identity.
- Do not start full-market daily refresh in afternoon or closing auction.
- Remove the AkShare request wrapper's network-wide lock so configured batch concurrency is real.
- Modify the existing daily-refresh contract test; add no test files or test cases.

## Evidence and acceptance

- 2026-07-27 logs show afternoon retries and the 15:02 full scan followed the lunch-plan gate, not database corruption or Serenity.
- The adjusted existing test must prove afternoon skip, post-close target refresh, and no repeat once the next-session target is bound.
- Rebuild only `gp` and `gp-worker`; verify their health and that their image contains the repaired worker code.
