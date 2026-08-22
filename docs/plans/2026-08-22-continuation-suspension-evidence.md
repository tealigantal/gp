# 2026-08-22 连续停牌官方证据修复 ExecPlan

## Purpose / Big Picture

修复日 K 恢复对“已由交易所/上市公司公告确认、且在目标交易日前持续停牌”的误判。目标是让 2026-08-20 的 `002084`、`002445`、`002906`、`600984` 在通过身份、交易所、公告时间、PDF 文本和无复牌冲突校验后，被记录为 `excluded / official_suspension`，从失败重试队列中闭合，使下一交易日计划能够继续按精确覆盖规则生成。

本次不放宽为“无日 K 即停牌”，不改变公共 API，不改变选股或 Serenity 权重，不删除任何运行数据。

## Progress

- 2026-08-22：容器真实探测确认 4 只股票均能找到 CNINFO 记录、交易所复核通过、PDF 可解析，但 `_halt_excerpt` 对目标日返回空；当前逻辑只接受公告正文直接写目标日期开市/开盘停牌。
- 2026-08-22：互联网核验确认 4 只股票在 2026-08-20 均处于停牌状态；当前工作区与运行容器均已有官方停牌采集器。
- 2026-08-22：待实现连续停牌证据类型、回归测试、文档同步、容器重构和真实恢复验收。

## Surprises & Discoveries

- 失败不是公告发现、交易所复核或 PDF 解析失败，而是最后的目标日期文本门禁拒绝了“起始日期 + 继续停牌”表达。
- worker 使用的官方采集器已在运行镜像中，但其证据策略不支持跨多个交易日的明确连续停牌公告。

## Decision Log

- 保留精确目标日证据作为最高优先级。
- 新增连续停牌证据：要求公告在目标日开市前发布、身份与交易所复核通过、明确表达继续/仍在停牌，且没有目标日前复牌冲突；只对当前精确目标日生效。
- 仅有“预计不超过 N 个交易日”不得单独形成证据；交易所目标日停复牌状态可作为独立最高可信来源。
- 连续停牌证据必须保留起始日、目标日、来源记录、复核结果、公告摘要和证据类型，便于审计。

## Outcomes & Retrospective

完成后记录实际覆盖数、4 只股票的证据类型/来源、当前计划发布状态、真实聊天响应和容器镜像/源码一致性。若官方事实仍无法通过，保留 retry，不用降级排除兜底。

## Context and Orientation

- 采集器：`src/gp_assistant/application/official_suspension.py`
- 日 K 调度与证据消费：`src/gp_assistant/application/market_orchestrator.py`
- 运行账本：`src/gp_assistant/application/market_runs.py`、`store/market_runs.db`
- 现有决策：`docs/adr/0015-official-suspension-evidence-for-market-runs.md`
- 现有覆盖测试：`tests/contracts/test_daily_refresh_exact_coverage.py`

## Plan of Work

1. 扩展 PDF 停牌摘要匹配，支持目标日前公告明确写“继续停牌/仍停牌”且起始日不晚于目标日的表达；保留复牌冲突和公告时间门禁。
2. 增加证据类型与连续天数边界，确保“预计最长停牌”不单独被当作目标日事实。
3. 补充单元/合同测试，覆盖四类连续停牌、复牌冲突、过期公告、模糊预计停牌和现有一日停牌。
4. 更新 ADR、研究记录、验证账本和进度文档。
5. 执行后端测试、编译、Compose 校验与真实容器恢复；确认运行账本达到精确覆盖并发布下一计划。

## Concrete Steps

- `python -m pytest -q tests/contracts/test_daily_refresh_exact_coverage.py`
- `python -m pytest -q`
- `python -m compileall -q src tests`
- `docker compose config --quiet`
- `docker compose build gp gp-worker web`
- `docker compose up -d --no-deps gp gp-worker web`
- 读取 `/api/health`、`/api/recommendation/current`，检查 4 只证据和恢复账本；执行一次临时 `/api/chat` 并删除会话。

## Validation and Acceptance

- 自动化：现有全套后端测试通过，连续停牌测试通过，Compose 配置通过。
- 运行时：worker 不再把 4 只股票留在 `failed`；`2026-08-20` 的 expected coverage 完成；健康接口进入可发布/已发布状态。
- 用户链路：聊天只解释新的完整计划或明确不可用状态，不把旧计划伪装成当前可执行计划。
- 失败闭合：公告时间、身份、交易所、PDF、目标日或复牌冲突任一不满足时继续 retry。

## Idempotence and Recovery

证据写入沿用追加式 `evidence_json` 与目标日排除状态，不删除原始 universe 或历史日 K。重复 worker 运行只复用已记录状态。若部署后验证失败，保留旧镜像并只回退后端/worker 镜像，不删除数据卷；本次不使用 `--remove-orphans`。

## Artifacts and Notes

- 运行时文件 `store/llm_runtime_status.json` 与 `.agent.db.lunch-rebalance.lock` 属于既有本地变更，不纳入提交。
- 外部核验来源：2026-08-20 停复牌日历及 4 家上市公司/交易所公告；详见本次 `docs/RESEARCH_LOG.md` 记录。

## Interfaces and Dependencies

不新增依赖、不改变 HTTP/SQLite 公共 schema。继续使用现有 CNINFO 传输、交易所复核、PDF 解析和 `market_runs.db` 账本；官方事实只由 `gp-worker` 采集和写入，推荐与聊天只读完成发布。
