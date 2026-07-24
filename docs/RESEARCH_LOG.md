# Research Log

2026-07-23: Repository inspection established that timing, persistence, and conversation identity were distributed through retired structures. The contract kernel now makes plan reuse depend only on semantic decision inputs and makes runtime freshness independent from plan identity.

2026-07-24: A live CNINFO-targeted run for the current frozen Top-30 reached a `000100` PDF that `pypdf` could not extract. This confirmed the need for whole-batch atomic gating in production: the observable result was Serenity degraded at 0% while the base plan and runtime continued. No inference was made from the unreadable document.
