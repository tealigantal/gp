# 午盘 Top-30 五分钟重排 ExecPlan

## Purpose / Big Picture

在交易日 11:30 收盘后，用完整闭合的上午 5 分钟行情对早盘计划冻结的 Top-30 重新排序。早盘 `RecommendationPlan` 永久保留，午盘结果是新的不可变计划版本；数据库表结构、Pydantic 合同字段和 HTTP 响应形状全部不变。任一股票、沪深300或任一闭合时点缺失时，不创建午盘计划、不切换 current publication，也不清空早盘结果。

## Progress

- [x] 2026-07-24：验证当前免费主数据源可为现行 Top-30 连续返回 09:35–11:30 的 24 根 5 分钟线；东财 fallback 当前不可视为可靠备源。
- [x] 2026-07-24：确认现有 `contract_kernel.v1` 可用追加式新 plan/runtime/publication 表达午盘版本，无需迁移或字段扩展。
- [x] 2026-07-24：确定旧会话保持首次 publication，新会话读取午盘 current 的既有会话语义。
- [x] 2026-07-24：实现完整批次规范化、摘要、确定性午盘重排和固定3% Serenity穿透。
- [x] 2026-07-24：实现11:32稳定延迟、独立采集子进程总预算、worker单次触发、失败保持早盘结果和午盘不可交易 runtime。
- [x] 2026-07-24：实现采集起点CAS、跨进程写锁、current防倒退、内容身份与持久化血缘校验。
- [x] 2026-07-24：完成合同、数据库、调度、来源窗口、真实隔离采集和午后解释链路验证；默认40项测试、分钟来源3项测试及真实来源1项集成测试通过。

## Surprises & Discoveries

- 当前午休路径直接生成空的 `RuntimeObservation`，所以即使 11:30 数据存在，午休 publication 也会表现为 unavailable。
- `current_publication` 当前是无版本比较的 last-writer-wins；迟到的日线任务可以把午盘结果覆盖回去。
- 现有会话会永久绑定首次 publication。这是血缘保护，不应通过批量更新 session 来绕过。
- 免费 5 分钟主源当前可用，但 fallback 实测失败；第一版必须把完整性作为原子闸门，而不能承诺双源可用性。
- `src/gp_assistant/intraday/__init__.py` 仍 eager import 已删除的 `strategies` 模块，使任何现行子模块导入都失败；当前无调用方依赖这些失效导出，已移除 eager import 而未恢复旧策略权威。

## Decision Log

- 2026-07-24：采用“早盘计划 + 午盘新增计划版本”，禁止 UPDATE、删除或复用早盘 plan ID。
- 2026-07-24：午盘仅重排早盘冻结 Top-30，保留计划中的完整 evaluated-candidate 范围；不声称重新执行全市场筛选。
- 2026-07-24：午盘排序以新鲜 5 分钟信号为主要权威；Serenity 仍保留固定 3% 边界，日线负责冻结候选范围和原有交易事实。
- 2026-07-24：午盘严格继承基础计划已经绑定的 Serenity 0%/3% 结果；11:32 不读取晚到批次，后续公告证据从下一份日线基础计划生效。实现与验证见 `docs/plans/2026-07-24-daily-refresh-and-serenity-ocr-recovery.md`。
- 2026-07-24：Top-30 与沪深300必须全部具有 09:35–11:30 精确24根闭合数据，任何缺失整批失败。
- 2026-07-24：午盘 publication 必须同时绑定新 plan 和 11:30 runtime；不发布 runtime=None 的中间状态。
- 2026-07-24：旧会话不自动换绑。用户明确创建新会话或重新发起推荐时才读取最新午盘 publication。

## Outcomes & Retrospective

实现和本地验证已完成，等待草稿 PR 的人工审核。临时数据库测试证明早盘记录继续可读、当前 v1 数据库不会被迁移命令替换、伪造身份/血缘/交易状态被拒绝、跨进程写锁和采集起点 CAS 生效。真实隔离采集验证了当前免费主源可以一次性返回 Top-30 与沪深300完整上午窗口。该分支没有替换运行容器、修改公开合同或合并主分支。

## Context and Orientation

日线计划由 `src/gp_assistant/application/real_producer.py` 生成；唯一 worker 入口是 `src/gp_assistant/cli.py`；5 分钟来源位于 `src/gp_assistant/providers/akshare_provider.py`；计划、runtime 和 publication 分别通过三个 application service 写入 `src/gp_assistant/store.py`。现行 SQLite schema 是 `contract_kernel.v1`，本任务不得修改 schema 或现有 ContractModel 字段。

## Plan of Work

1. 新建纯计算午盘模块，规范化完整批次并计算可解释、确定性的上午信号。
2. 新建午盘编排器，在网络采集完成后追加新 plan、新 runtime，最后一次性切 current publication。
3. 把 worker 午休路径改为一次性午盘编排；失败或数据不完整时保留早盘 publication，下午继续在午盘 plan 上生成正常 runtime。
4. 加固 store/publication 的身份、血缘、乱序和 current CAS 防护，不改变数据库结构。
5. 补齐旧计划可读、同批次幂等、完整失败、调度重启、会话绑定和数据库完整性测试。
6. 更新产品、架构、数据新鲜度、服务合同、验证与进度文档。

## Concrete Steps

- 只通过 application service 写 plan/runtime/publication，禁止直接写业务 SQLite。
- 使用临时 SQLite 文件测试，不接触 `store/agent.db`。
- 执行 `python -m pytest -q`、显式分钟来源测试、`python -m compileall -q src tests`、合同清单、退役符号、Compose config 和 `git diff --check`。
- 对真实 5 分钟源只做只读探针；不因测试重建或替换当前容器。

## Validation and Acceptance

- 11:30只确认上午收盘，不立即接受；11:32稳定延迟后同交易日同批次只产生一个午盘 plan。
- 30只股票加沪深300均为同日 24 根、最后时点11:30；缺一只、缺一根、重复、乱序、空值或未闭合均失败并保持早盘 current。
- 早盘 plan/runtime/publication 仍可完整读取，schema metadata 保持 `contract_kernel.v1`，无 UPDATE/DELETE/migration。
- 新午盘 plan 保留全部 evaluated candidates，仅冻结 Top-30 有入选资格；午盘排序确实可以变化。
- 午盘 runtime 的 slot 为11:30、质量 ready、市场门禁 deny、tradeable false。
- 迟到任务不能把 current 指针倒退；并发 writer 只有一个能切换 current。
- 旧会话继续读取早盘 publication，新会话读取午盘 publication。
- `/api/recommendation/current`、`/api/lunch/current` 与 `/api/health` 字段集合和类型不变。

## Idempotence and Recovery

分钟批次摘要由基础 plan ID、来源、标的和规范化 OHLCV 内容确定。相同输入复用同一 plan/runtime/publication；失败不切 current。允许留下已提交但未发布的不可见 plan/runtime，重试可通过内容身份复用。回滚只需停止午盘触发并恢复旧代码，已追加记录继续可读且无需数据库降级。

## Artifacts and Notes

- 决策：`docs/adr/0011-lunch-top30-five-minute-rerank.md`
- 合同语义：`docs/contracts/CURRENT_CONTRACTS.md`
- 运行数据 `store/`、`cache/`、`results/` 永不纳入提交。

## Interfaces and Dependencies

- 输入：早盘 plan 的冻结 Top-30、沪深300以及闭合至11:30的 5 分钟 OHLCV。
- 输出：复用现有 `RecommendationPlan`、`RuntimeObservation`、`RecommendationPublication`。
- 依赖：现有 AkShare provider、pandas、标准库并发和当前三个 application service；不新增依赖、公开端点、合同字段或数据库表。
