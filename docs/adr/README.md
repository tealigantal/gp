# Architecture Decision Records

Create an ADR when work changes module or data ownership, public interfaces,
trust/security boundaries, persistence strategy, deployment topology, major
dependencies, or long-term compatibility. The current contract kernel and
project operating contract take precedence when an older ADR differs.

Each retained ADR records its decision context, consequences, and rollback
boundary. The repository history contains gaps in the original ADR sequence;
only the files listed below are retained records.

## Index

| ADR | Status and scope |
| --- | --- |
| [0001 — Serenity Alpha experimental add-on](0001-serenity-alpha-experimental-addon.md) | Superseded for production topology and weight by ADR 0010; retained as experiment history. |
| [0004 — Serenity resident reference service](0004-serenity-resident-reference-service.md) | Superseded for topology by ADR 0010; retained as resident-service history. |
| [0006 — Single assistant-turn presentation contract](0006-assistant-turn-presentation-contract.md) | Historical presentation contract; current API behavior is governed by the contract kernel. |
| [0008 — Full-market universe ownership and additive Serenity](0008-full-market-universe-and-additive-serenity.md) | Accepted for full-market ownership; its former Serenity weight range is superseded by ADR 0010. |
| [0009 — Contract Kernel Hard Cutover](0009-contract-kernel-hard-cutover.md) | Accepted destructive cutover record; never rerun against the current store. |
| [0010 — Serenity fixed 3% and unified worker isolation](0010-serenity-fixed-three-percent-unified-worker.md) | Current Serenity weight and worker-topology decision. |
| [0011 — Lunch Top-30 five-minute rerank](0011-lunch-top30-five-minute-rerank.md) | Current immutable lunch-plan semantic extension. |
| [0012 — Exact daily coverage and bounded Serenity OCR](0012-daily-coverage-and-serenity-ocr.md) | Current exact coverage and bounded OCR decision. |
| [0013 — Market-day orchestrator and recovery](0013-market-day-orchestrator-and-recovery.md) | Current daily scheduling, recovery, and publication-gate decision. |
| [0014 — Single chat narration and temporal truth](0014-single-chat-narration-temporal-truth.md) | Current single narration authority and answer-time market-state decision. |
| [0015 — Official suspension evidence for market runs](0015-official-suspension-evidence-for-market-runs.md) | Current official no-bar fact boundary for exact daily coverage. |
