# Research Log

## 2026-07-22 — 生产候选宇宙与 Serenity 权限边界审计

- **问题：** 为什么每日推荐在数据已刷新时仍局限于同一组股票；Serenity 是否因接入而获得了不应有的基础链路权限？
- **检查日期与来源：** 2026-07-22；本地工作区源码、Git 历史、Docker Compose、运行日志和运行数据库只读检查。没有使用外部资料，也没有修改运行时状态。
- **完整证据：** [候选宇宙与 Serenity 边界全仓审计](./architecture-audit-2026-07-22-candidate-universe-and-serenity-boundaries.md)。
- **观察：** 2026-07-09 的 `8cfde8b` 在生产日线调用点固定 `allow_snapshot=False`；pipeline 因而回退到 `store/universe/universe_symbols.txt`，当前仅十只。每日评分快照和分数会变化，但候选集合不变。新鲜度只在选出候选之后检查，故十只新鲜不能证明全市场完整。
- **边界观察：** Serenity 有独立 worker 和 append-only 证据库，但核心 pipeline 直接创建其目标、读取其信号并把它放进最终九专家评分；native 覆盖不足会产生 `no_trade`。这使它同时拥有评分贡献和基础推荐可用性否决权。
- **产品范围观察：** 生产动态路径原本是全市场现货快照后的成交额动态池，不是全量逐标的评分；当前 production `decision_engine` 未证明执行 ST 排除及 legacy `selection_engine` 中的最小宇宙/价格/上市天数等门槛。
- **决策影响：** 后续修复不能只恢复单个 snapshot 开关。任何获批实现必须先定义并强制验证基础候选宇宙契约（来源、时间、输入/合格/评分数、规则版本和回退状态），再把 Serenity 限定为版本化、受权重约束的评分扩展。是否采用该架构仍待用户明确批准。

## 2026-07-17 — DeepSeek Beta strict tool routing

- **Question:** Why did compact real `/api/chat` routing calls return HTTP 400 from DeepSeek?
- **Checked date:** 2026-07-17.
- **Official source:** DeepSeek Function Calling documentation and Chat Completion reference.
- **Observation:** The live routing payload was 7,492 bytes, so it was below the local 600,000-byte budget and not the prior prompt-overflow incident. A direct Beta request returned the provider error `Thinking mode does not support this tool_choice`; the same complete GP tool schema returned HTTP 200 after thinking was explicitly disabled.
- **Provider constraint:** Strict function mode is a Beta feature and every property of each object must be required with `additionalProperties=false`.
- **Decision impact:** GP uses `https://api.deepseek.com/beta` without a `/v1` fallback, keeps strict tools, encodes unknown routing fields as explicit JSON `null`, and always disables thinking for required-tool routing.

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

## 2026-07-17 — CNINFO announcement-query envelope v2 observation

- **Source and checked date:** Live `POST https://www.cninfo.com.cn/new/hisAnnouncement/query`, checked 2026-07-17. This is the public CNINFO web-query endpoint used by Serenity, not a paid CNINFO Data Service API.
- **Observed request/response:** Exact-stock form queries use `stock={symbol},{orgId}`, `column`, `seDate`, pagination fields and `tabName=fulltext`. The complete top-level response contains `classifiedAnnouncements`, `totalSecurities`, `totalAnnouncement`, `totalRecordNum`, `announcements`, `categoryList`, `hasMore`, and `totalpages`. A genuine no-result response returned HTTP 200 with `announcements:null`, all record counts and `totalpages` equal to 0, and `hasMore:false`.
- **Observed non-empty fields:** Each announcement row includes `announcementId`, `secCode`, `secName`, `orgId`, `announcementTitle`, epoch-millisecond `announcementTime`, `adjunctUrl`, and additional official metadata. `id` was null in observed rows.
- **Maintenance and applicability:** CNINFO's public web interface has no contractual stability guarantee. The collector now follows this observed v2 shape strictly: only `announcementId` is accepted as the record key, only the official nullable empty representation is accepted, and `hasMore` alone controls continuation because exact-stock queries may report `totalpages:0` even when rows exist.
- **Decision impact:** The prior `cninfo_announcement_schema_changed` was a local parser defect, not evidence of a provider field rename. A valid empty poll completes with zero evidence and keeps Serenity at its additive 0% contribution.
