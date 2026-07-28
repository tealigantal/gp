# Product

GP is a chat-first A-share main-board decision assistant for short 1–3 trading-day plans. It presents either a publication grounded in complete evidence or an explicit unavailable/no-recommendation result. Runtime quality can make execution unavailable without changing the daily plan.

## Chat workspace

The primary local product surface is a responsive three-pane workspace at port 8080. Conversation history and canonical turns remain the main journey. The decision brief shows the current plan date, evidence date, execution availability, and the selected candidates in engine-provided order. Its primary market card reads the server-clock `market_now` projection rather than the publication's historical RuntimeObservation: after close an ended plan is labeled “仅供回顾”, not “today” or executable, and the candidate section is explicitly named “上一份计划入选（仅回顾）”. A separate next-plan card reads `next_plan_target`: it says whether the next session plan is published, is waiting for a named daily-evidence date, or has complete evidence but no new publication yet. It must not call that last state “正在发布” or visually pass the old candidates off as the new plan. An ended current plan is never presented as a prohibition on tomorrow's plan. It does not turn internal diagnostics into user-facing recommendations and does not hide unavailable or non-trading states. 当容器停机后，界面继续展示最后一份完整发布，不把正在补齐的市场数据误显示为新的不可用推荐；下一计划卡会以中文提示目标日期、所需日K、完成/失败数和近似回补标记。

On smaller screens, the same information becomes a single reading flow: chat first, decision brief second. Sending supports Enter, while Shift+Enter inserts a new line. Failed narration is shown in Chinese and the unsent question remains available for retry.

The current decision brief and a conversation's bound publication are separate browser states. When a trusted response proves both publications belong to the same immutable plan, runtime-only updates keep the current candidates visible with an explicit execution-state notice. A confirmed different plan remains isolated, while an unknown historical lineage is labeled as unknown rather than falsely asserted to be a different decision.

Every saved-conversation card has a separate delete control. Deletion requires an explicit irreversible-action confirmation that identifies the conversation time and publication. Deleting the active conversation returns the workspace to a new chat; deleting another conversation leaves the current chat intact. A deleted session and all of its messages disappear permanently, while recommendation publications and plans remain unchanged.

# Time-aware narration

Every new chat starts with a deterministic Chinese market-status statement. It identifies the answer time, whether the displayed plan is active, future, or already ended, and whether it can be executed now. It separately explains the daily-evidence date, the plan trading date, and any recovery progress. The following LLM prose may explain only the publication-bound candidates; it cannot reinterpret the last intraday observation as the current clock, call a runtime publication a new daily plan, or turn an ended plan into a next-session plan. If a new daily plan is still recovering, the last complete plan remains readable only as research, never as a new executable recommendation.

## Serenity official-announcement evidence

Serenity is an auxiliary official-announcement dimension, not a second selector. The base engine first freezes its Top-30. If every finalist has a complete, current, verified source result for that exact batch, Serenity uses a fixed 3% signed weight; positive or negative evidence can change the score by at most 0.03. A complete result with no relevant announcement is neutral. If any finalist is missing, a source or PDF fails, or the batch is stale or mismatched, the whole batch contributes zero and the base recommendation remains unchanged. The chat may explain only the actual bound weight, contribution, and product-level reason; it never exposes internal interfaces or identifiers.

Relevant official scanning announcements may be read only when their identity, event family and numerical evidence are consistently recognizable within fixed safety limits. Unrelated generic revisions are ignored before retrieval. An uncertain or unreadable relevant announcement never becomes partial evidence: the exact Top-30 batch remains at 0%.

## Lunch five-minute rerank

After the 11:30 close, GP may publish a new order within the morning plan's frozen Top-30. It requires exact, complete five-minute data for all 30 candidates and CSI300. The lunch score reflects relative morning strength, location versus a volume-weighted price proxy, location within the morning range, and last-hour momentum; the already bound Serenity contribution remains limited to ±0.03. The daily plan and all non-ranking facts remain immutable.

If any input is incomplete, GP keeps the morning publication instead of showing an empty lunch result. A successful lunch publication is still non-tradeable during the break. Existing conversations continue to explain the publication they originally used; a new conversation sees the latest lunch publication.

## 市场日恢复

每个新架构市场日在 14:57 冻结主板分母与现货证据，15:05 后先做小样本日K源探测，15:20 后才开始按批次补齐当日数据。目标日覆盖未完整时不会发布下一计划。若正常源已尝试完毕且只剩少数股票缺日K，系统可核验对应官方停牌公告；只有公告在开盘前披露、交易所复核通过、PDF 明确写明该目标日开市停牌时才从覆盖分母排除，并保存可审计证据。公告超时、无法读取或表述不清仍保持缺失和重试。停机期间缺失交易日按日期顺序恢复，已完成股票不重抓。若旧日期没有当时冻结的分母，系统仅能用当前分母近似修复日K，并明确标记为近似；它不会把这一近似说成历史完整推荐或发布历史日计划。
