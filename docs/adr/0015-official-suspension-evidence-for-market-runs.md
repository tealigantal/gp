# ADR 0015：日K运行账本的官方停牌事实

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

2026-07-27 的日K run 仅余 `002036` 与 `002828` 缺失。两者均有开盘前披露、正文明确写明 7 月 27 日开市停牌的官方公告，但原运行账本只承认同日全零现货；该 run 又因停机后重建分母而不能使用现货排除。因此准确的官方停牌事实没有任何生产消费入口，run 保持 3042/3044 pending。

Serenity 已有官方公告传输、交易所复核和 PDF 解析能力，但其任务、Top-30 batch、追加存储及固定 3% 权重属于评分辅助域，不能成为日K覆盖或候选范围的所有者。

## Decision

新增 `application.official_suspension.OfficialSuspensionEvidenceCollector`。它只复用 CNINFO 的严格传输、交易所复核与受限 PDF 文本解析，不读取或写入 Serenity batch/store，也不接触选股、评分或发布。

日K子 worker 先完成普通 `sina → em → tx` 日K尝试和精确重读；仅在仍缺失不超过十只、且本轮均已尝试后，才对这些股票逐只调用官方事实通道。事实必须同时绑定：目标代码、目标日、开盘前公告时间、CNINFO 记录、交易所复核、PDF 中“目标日开市/开盘停牌”的明确文本和文档摘要。任一网络、解析、时间、身份、复核或文本歧义失败都不排除。

`market_runs.db` 的 `daily_run_symbols.evidence_json` 追加保存该事实；账本将对应状态设为 `excluded / official_suspension`，但保留 raw universe，重算 expected denominator。该路径可用于 `reconstructed_current_universe`，因为它不依赖陈旧现货。计划、聊天和 API 仍只读已完成 run。

## Consequences

- 停牌事实与 Serenity 评分重新分属两个明确契约：前者是日K完整性事实，后者仍是 Top-30 的原子 0%/3% 辅助。
- 不能用官方公告大规模代替日K源；全市场失败时仍会 fail closed，不会扫描全部公告。
- 既有 `market_runs.db` 只做一列可加迁移，`history.db`、产品库、公开 HTTP 合同和 Serenity 证据均不迁移。
- 深交所使用公告 ID 复核；上交所当前适配器为代码加规范标题复核，账本会记录其 verification basis，不能表述为公告 ID 精确匹配。

## Rollback

回退代码会忽略 `evidence_json` 和 `official_suspension` 行，既有数据库和产品发布不受破坏；未完成 run 将恢复为普通日K缺失重试。不得通过删除运行账本来回退。
