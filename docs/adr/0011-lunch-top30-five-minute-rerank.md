# ADR 0011 — 午盘 Top-30 五分钟重排

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

现行日线计划在交易日前一日闭合数据上冻结候选，但午休已有当日上午 24 根闭合 5 分钟线。旧 runtime 只能记录执行状态且午休会生成空状态，不能满足用户要求的午盘重排。用户要求避免数据库失效和接口错位，因此不得迁移 schema、修改合同字段或覆盖旧计划。

## Considered Options

1. 只更新 `RuntimeObservation`：数据库最保守，但不能改变排序。
2. 前端临时排序：会形成第二推荐权威并破坏 publication 血缘。
3. 覆盖早盘 plan：违反不可变性并可能让旧会话和摘要失效。
4. 新增不可变午盘 plan：复用现有合同与追加存储，可真实重排并保留历史。

## Decision

选择方案4。早盘完整计划负责全市场筛选并冻结 Top-30。11:32 稳定延迟后，只有在 Top-30 与沪深300都具有精确、完整、闭合的上午 5 分钟批次时，才创建新的午盘 `RecommendationPlan`。采集在有总预算的独立子进程中运行。午盘使用5分钟信号直接形成新的排序分，Serenity 继续保持固定3%边界；完整 evaluated-candidate 范围和日线交易事实继续保留。随后为新 plan 创建午休 runtime，并在最后一步发布 plan+runtime。

所有旧记录不可变。相同批次通过稳定内容摘要幂等复用。数据不完整、来源失败、并发冲突或陈旧任务均不得切换 current publication。

## Rationale

新 plan 明确表达新的选择证据，不滥用 runtime，也不把排序藏到前端。追加式版本使旧计划、旧 publication 和旧会话继续可读；现有 HTTP 和 SQLite schema 无需变化。完整批次原子失败避免按数据可得性偏袒个别股票。

## Consequences

- 午盘只能称为“早盘 Top-30 内重排”，不能声称重新全市场筛选。
- 午休结果更新排序但市场门禁仍为 deny，不会产生午休可交易状态。
- 旧会话保持早盘血缘，新会话读取午盘 current。
- 免费来源失败时午盘计划不可用，但早盘结果保持，不会被清空。
- worker 和 publication store 必须拒绝并发或迟到写入造成的 current 倒退。

## Migration

无数据库迁移、无合同字段迁移、无 HTTP 迁移。部署新代码后由 worker 自然追加午盘记录。

## Rollback

停止午盘触发并回滚代码即可。已追加午盘 plan/runtime/publication 与旧 schema 完全兼容，可保留审计，不需删除。
