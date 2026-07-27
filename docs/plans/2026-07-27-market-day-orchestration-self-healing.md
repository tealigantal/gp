# 市场日编排与停机自愈重写

## Purpose / Big Picture

将生产 worker 从“60 秒循环叠加 30 分钟门槛”替换为持久化市场日任务状态机。停机后会按交易日续跑同一日K任务；不完整数据、历史回补或空候选均不得替换最后完整发布。现有 `history.db`、`agent.db`、算法、Serenity 固定 3% 原子批次和聊天接口不迁移。

## Context and Orientation

- `src/gp_assistant/application/market_runs.py` 是新增、独立的 `store/market_runs.db` 账本；它不是推荐或聊天事实库。
- `MarketDayOrchestrator` 是 worker 唯一的网络/计划/发布编排入口；API 与聊天只读。
- `RealRecommendationProducer` 只消费完成的冻结分母和精确目标日日K；它不再抓现货或补日K。
- `PublicationService` 和 `ContractStore` 都验证发布资格，防止任意调用者把 pending 计划推进当前指针。

## Progress

- [x] 2026-07-27：确认事故源于 lunch 分支错误地触发全市场刷新及 AkShare 请求锁串行，不是数据库或 Serenity 损坏。
- [x] 2026-07-27：新增市场日账本、租约、分母冻结、目标日覆盖核验、按缺口续跑与恢复健康摘要。
- [x] 2026-07-27：替换 core worker 条件分支；计划生成、运行时、午盘和 T+5 维护分别受时间窗约束。
- [x] 2026-07-27：在发布服务及存储边界加入完整计划门禁，并禁用 API 手工采集入口。
- [x] 2026-07-27：已修改既有测试（未新增测试文件或测试数量），目标回归与全套默认测试通过。
- [x] 2026-07-27：重建 `gp`/`gp-worker`/`web` 后完成实际恢复观察：旧完整发布保留，精确核验为 3042/3044，两只缺口写入失败与下次重试时间。
- [ ] 继续运行中的外部源恢复尚未补齐两只缺口；完整后才允许下一版本发布。

## Plan of Work

1. 14:57 冻结当天主板分母；15:05 后每五分钟小样本探测，15:20 后才允许按 100 只批次运行当前日日K。
2. 账本对每股票记录待处理、已覆盖、失败和可信停牌排除；每批后从 `history.db` 对目标日期重新核验，仅续跑缺口。
3. 启动时从最近连续完成日（首次从已存日K最大日期推断）向前恢复，缺历史分母时明确记录 `reconstructed_current_universe`，且不生成历史日推荐。
4. 仅完整、READY 的推荐或合法 no-recommend 可推进 `current_publication`；恢复时保留最后完整发布。
5. 基础计划、运行时、午盘、Serenity 和 T+5 分别运行在既定窗口，互不借用触发条件。

## Concrete Steps

1. 运行 `python -m compileall -q src tests`。
2. 运行 `python -m pytest -q`；只维护现有测试函数。
3. 运行 `docker compose config --quiet`，构建并重建 `gp` 与 `gp-worker`，不触碰 `web` 和数据卷。
4. 读取 `/api/health`、worker 日志和当前发布，验证恢复状态与旧完整发布保留。

## Validation and Acceptance

已执行：目标合约测试与 `python -m pytest -q`。它们覆盖旧日期不能冒充目标日、任务中断后仅缺口续跑、可信停牌边界、冻结分母纯读建计划、源未就绪只探测、发布门禁、午盘重启不重复及运行时不自动移动指针。

已执行：容器重建后的真实恢复观察。`/api/health` 连续十次返回 200；`market_recovery` 显示 3042/3044、两只失败、下一次重试时间和近似分母标记；浏览器实际显示“市场数据恢复中”且没有错误覆盖层。当前源未补齐两只缺口，所以完整发布这一最终条件仍由运行中的账本负责，未被伪造为通过。

## Idempotence and Recovery

`daily_runs.trade_date` 和 `daily_run_symbols(trade_date,symbol)` 为幂等键。worker 与单日任务各有过期租约；容器中断后只接管未完成 run。恢复账本可删除并重建，但不会改写任何产品数据库；回退只需恢复旧镜像，`history.db`、`agent.db` 和 Serenity 证据保持原状。

## Surprises & Discoveries

- 现有 `latest_rows()` 只适合当前决策；跨日修复必须按目标日期查询，否则较新日K会遮蔽旧日期缺口。
- 原先的生产发布路径只比较时间与 CAS，未验证计划完整性；因此一次待补日K计划曾覆盖有效当前发布。

## Decision Log

- 采用独立 `market_runs.db`，不为编排状态迁移或改写既有产品库。
- 没有历史冻结分母时允许以当前分母修复历史日K，但标为近似，绝不称为历史精确全市场覆盖。
- 日K抓取在短生命周期子进程中执行，父 worker 继续处理运行时与午盘。

## Interfaces and Dependencies

`/api/health` 新增只读 `market_recovery`；推荐、聊天和会话响应形状不变。前端仅展示中文恢复提示。AkShare 日K仍严格按 `sina → em → tx` 路由优先级；批大小、探测/重试间隔、租约及抓取预算由 `GP_MARKET_RUN_*` 配置。

## Outcomes & Retrospective

实现与容器观察已完成；外部数据源恢复仍在继续，系统保持最后完整发布。没有引入兼容 worker、产品数据库迁移或新的产品数据表。
