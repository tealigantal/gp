# Research Log

2026-07-23: Repository inspection established that timing, persistence, and conversation identity were distributed through retired structures. The contract kernel now makes plan reuse depend only on semantic decision inputs and makes runtime freshness independent from plan identity.

2026-07-24: A live CNINFO-targeted run for the current frozen Top-30 reached a `000100` PDF that `pypdf` could not extract. This confirmed the need for whole-batch atomic gating in production: the observable result was Serenity degraded at 0% while the base plan and runtime continued. No inference was made from the unreadable document.

2026-07-24: The lunch five-minute implementation was checked against the current 2026-07-24 frozen Top-30 and CSI300 using the primary AkShare Sina minute route only. All 30 stocks and the benchmark returned exactly 24 normalized rows ending at 11:30; the batch digest prefix was `b71cc68bb392`. Earlier fallback probes disconnected, so the first production revision intentionally fails the whole lunch batch instead of mixing a fallback route per symbol. The free route has no SLA and still requires forward soak monitoring.
