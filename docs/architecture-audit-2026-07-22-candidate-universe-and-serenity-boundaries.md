# 2026-07-22 候选宇宙与 Serenity 边界全仓审计

- **状态：** 已完成的只读研究；不是已批准的修复方案。
- **范围：** 生产数据链、容器/存储所有权、跨模块契约、Serenity 接入、历史回放、测试、文档与 Git 演进。
- **检查日期：** 2026-07-22（Asia/Shanghai）。
- **方法：** 读取工作区源码、Git 历史、Compose 配置、当前运行日志和 SQLite 只读表结构；未修改生产代码、数据库、容器或运行时数据。

## 结论

本次“昨日与今日推荐高度重复”的直接原因不是评分未运行、快照复用或数据库拒绝写入，而是生产候选宇宙被固定为十只股票。评分确实在每日重新执行，分数和部分排序也会变化；但它只能在同一组十只股票中排序，无法产生集合外的候选。

更深层的架构问题是：仓库已有聊天、运行时和快照的契约，却没有一个不可绕过的**基础市场输入/候选宇宙契约**。候选来源、全市场输入数、主板合格数、实际评分数、最小覆盖阈值和回退状态未被作为生产发布的强制条件。结果是“十只都新鲜”被错误地表现为“全市场数据完整”。

Serenity 的正确产品定位需要区分两类权限：

- Serenity 应以版本化 Alpha、证据谱系和受控权重参与最终评分；已知完整但无相关公告时，贡献可以为 0。
- Serenity 不应改写基础候选宇宙、基础行情完整性、基础特征/概率/风险，也不应将自身采集状态伪装为基础市场数据缺失。

当前实现只完成了前半部分的一部分：它可以成为第九个评分专家，但覆盖不完整还会把整条基础推荐变为 `no_trade`。因此它目前不仅是评分输入，也拥有基础链路的可用性否决权。

## 已核实的生产链路

```text
gp-worker
  -> worker._load_or_build_daybook
  -> book.build_daybook
  -> evidence.market_service.build_day_selection
  -> decision_engine.pipeline.run_market_memory_selection
  -> AgentStore 发布不可变快照和 current pointer
```

在 `src/gp_assistant/evidence/market_service.py` 中，日线构建调用固定传入 `allow_snapshot=False`。`pipeline.py` 因此记录 `snapshot_disabled_daily_mode`，跳过 `_load_snapshot()` 和 `_snapshot_universe()`，随后回退到 `_file_universe()`。该回退读取 `store/universe/universe_symbols.txt`；检查时文件只有十只股票，且 `topk=10`，所以生产路径只会为这十只获取日线、生成信号并评分。

### Git 演进

- `8cfde8b`（2026-07-09，`fix: separate postclose daily readiness from intraday snapshots`）新增 `allow_snapshot` 参数，并在 `build_day_selection` 中固定设为 `False`。
- 同一提交加入 `test_build_day_selection_disables_snapshot_universe`，使该行为成为通过测试所要求的结果。
- `95e8f59`（2026-07-14，Serenity Native Alpha 接入）保留了这一调用；它不是十只候选的起因。
- 对该改动的提交、ADR、计划和产品文档中，未发现“将全市场候选缩为静态十只”已经获产品授权，或替代范围满足原范围的证明。

## 候选范围与产品范围的差异

禁用前的 `_snapshot_universe()` 会读取市场现货快照，过滤主板代码后按成交额排序，取动态池，默认上限为 200。因此它是“从全市场快照发现候选、在动态池内评分”，并不是对五千余只标的全部逐一计算。

审计同时发现，当前生产 `decision_engine` 的动态池实现只显式执行主板代码过滤和成交额排序：

- `GP_DYNAMIC_POOL_SIZE=200` 在 Compose 默认配置中存在，但日线生产路径被 `allow_snapshot=False` 绕过。
- `GP_MIN_AVG_AMOUNT`、`GP_NEW_STOCK_DAYS`、`GP_PRICE_MIN`、`GP_PRICE_MAX`、`GP_TRADEABLE_MIN_UNIVERSE` 和 `GP_TRADEABLE_MIN_CANDIDATES` 的实际筛选/门槛代码位于 `selection_engine/`。
- `AGENTS.md` 已定义 `selection_engine/` 是 legacy/reference，不是生产排序权威；生产 `decision_engine` 未调用这些门槛。
- 对 `decision_engine`、`evidence`、`providers` 的检查未发现 ST 排除实现。因此“主板、排除 ST、既有阈值”的产品范围不能被当前生产链证明已经执行。

这意味着恢复 `allow_snapshot=True` 本身不足以证明恢复了既定产品范围；它只能恢复 7 月 9 日前的动态快照路径。

## 完整性契约缺口

当前顺序为：先完成选择，再用 `selection_symbols(raw)` 提取 `picks + candidate_pool` 调用 `reconcile_daily_freshness()`。新鲜度报告、`SlotDataQuality` 和 `TrackedUniverse` 均只记录发布后的小范围标的；`TrackedUniverse.total` 甚至由前十推荐和最多两只 reserve 派生。

因此下列关键事实没有共同的、强制校验的结构化契约：

| 需要证明的事实 | 当前状态 |
| --- | --- |
| 候选宇宙来源与快照时间 | 仅作为 pipeline debug/meta 的松散字段，未作为发布门槛 |
| 原始市场输入数 | 动态路径可记录；静态回退只记录文件数；未进入运行时/产品快照契约 |
| 主板、ST、上市天数、流动性等合格数 | 没有生产统一记录 |
| 实际取数、信号成功、评分成功数 | 仅有局部失败/候选信息，未形成发布不变量 |
| 最小覆盖阈值 | 配置存在于 legacy `selection_engine`，生产 `decision_engine` 未强制执行 |
| 回退是否允许以及是否降级范围 | 静态文件回退可静默成功 |

`/api/health` 的日线 ready 在本次运行中确认了十只检查对象都到达目标交易日；这不能证明全市场扫描。Workspace 会话运行态还存在更弱的投影：`gateway/routes.py::_workspace_runtime()` 将 `daily_freshness_ready` 设为 `has_book`，不携带候选宇宙覆盖语义。

## Serenity 的现状与正确边界

### 已有隔离

- `gp-serenity-worker` 是独立常驻进程，只有它执行公告网络 I/O。
- Serenity 使用独立 `store/serenity/evidence.db`、WAL、忙等待和 worker lease；其表包含公告版本、事实、候选目标、覆盖、政策、评估和断路器。
- 证据、事实和策略具有较好的 append-only/first-seen 谱系设计。

### 尚未隔离的权力

- `decision_engine/pipeline.py` 直接调用 `publish_candidate_target()` 和 `load_frozen_signals()`；基础决策管线既生成 Serenity 输入目标，也读取其结果。
- 同一管线将 Serenity 作为第九个专家写入最终 Adaptive 分数，并重排候选。
- `agent_store.py`、`worker.py`、`chat_agent.py` 与 `runtime/native_snapshot.py` 也直接导入 Serenity 的模型或存储函数，说明边界不是独立接口，而是跨包内部调用。
- `GP_SERENITY_MODE=native` 下，`require_serenity=True`。目标覆盖不足、信号未就绪、过期、失败或未解析会造成 `serenity_coverage_incomplete` 和正式 `no_trade`；对应测试明确要求“不得回退基线评分”。

上述最后一点与“Serenity 有评分权重”不同：前者是最终评分中的受控贡献，后者是它对基础推荐是否可发布的否决权。当前 ADR 0005 记录的是后一种语义；ADR 0004 曾记录“Serenity 失败隔离于核心推荐链”，已被 ADR 0005 对排名权威部分取代。README 仍保留 `auto/reference` 的旧配置说明，而代码当前只接受 `native/off`，存在文档漂移。

## 容器和存储并不是权限边界

Compose 中 `gp`、`gp-worker`、`gp-serenity-worker`、bootstrap 和运维任务共享同一 `gp-backend:<tag>` 镜像，并共同挂载 `store/`、`cache/`、`data/` 等目录。测试还明确断言所有 Python 服务共用该镜像。

所以容器只是运行角色划分，不是模块权限隔离：一次后端镜像重建会同时带入核心和 Serenity 源码；服务通过共享 SQLite 文件和指针文件协作，而非版本化的 RPC/消息契约。`agent.db` 和历史缓存库在 Docker bind mount 上默认使用 DELETE journal；Serenity 库使用 WAL。前者是锁竞争和写入协调的独立运营风险，但本次十只候选问题没有证据表明由数据库拒绝更新导致。

## 历史回放与生产脱节

`evaluation_engine/historical_replay.py` 的实现比生产路径更接近所需数据契约：它使用只读历史库、显式 `eligible_count`、最小宇宙阈值、`universe_source` 和 as-of 约束，且在历史回放中明确 `serenity_mode="off"`。

这证明仓库内已有可借鉴的范围完整性概念，但它没有成为生产 `MarketBook`、日线新鲜度、运行时状态或发布门槛的一部分。历史回放的正确性也不能自动证明生产候选范围正确。

## 测试、文档与运行事实

- 测试覆盖了 AgentStore 不可变快照、Serenity 谱系和第九专家分数、Serenity 覆盖不足的 no-trade、共享镜像等；它们没有覆盖“生产全市场候选来源、最小覆盖、ST 排除和静态回退必须阻断发布”。
- `test_build_day_selection_disables_snapshot_universe` 将错误的范围收缩写成了回归保护，因此测试通过不代表产品范围正确。
- CI 仍对 `selection_engine` 的 self-check 做契约验证；该模块不是生产排序权威，不能代替对 `decision_engine` 的生产范围验收。
- 运行时审计确认 2026-07-21 与 2026-07-22 的快照不同、分数不同，且部分名次变化；重复的是十只候选集合。Serenity 当时为 shadow、权重 0，未造成“复用昨日评分”。

## 经确认的根因链

1. 为避免盘后误用不完整/陈旧的现货快照，7 月 9 日在调用点全局禁用了 snapshot universe。
2. 管线将“没有 snapshot”解释为允许静态文件候选回退，而非“生产候选宇宙不可证明，禁止发布”。
3. 新鲜度检查发生在选择之后，只验证该静态小集合。
4. 运行时和前端没有候选范围/来源/覆盖的合同字段，健康状态因此无法揭露范围缩小。
5. Serenity 接入后继续在同一中心 pipeline 内编排基础评分、扩展目标、扩展读取、最终排序和发布准备，扩大了跨模块耦合；它不是原始禁用者，但现有结构使扩展具备影响基础链可用性的能力。

## 本研究不作出的决定

- 未批准或实施恢复动态池、全市场回补、数据库迁移、容器拆分、协议改造或 Serenity 权重规则变更。
- 未将 Serenity 从最终评分中移除；用户已明确其应拥有评分权重。
- 未把静态十股清单认定为可接受的生产降级。

后续若获修复授权，必须先将“基础候选宇宙”和“Serenity 评分扩展”定义为分离、版本化、可验证的权限契约，再决定最小化恢复路径；不能仅通过改回一个开关而声称全市场产品范围已恢复。

## 可复核证据位置

- `src/gp_assistant/evidence/market_service.py`
- `src/gp_assistant/decision_engine/pipeline.py`
- `src/gp_assistant/evidence/daily_freshness.py`
- `src/gp_assistant/contracts/objects.py`
- `src/gp_assistant/runtime/slot_state.py`
- `src/gp_assistant/gateway/routes.py`
- `src/gp_assistant/serenity/store.py`
- `src/gp_assistant/evaluation_engine/historical_replay.py`
- `docker-compose.yml`
- `tests/test_daily_freshness.py`
- `tests/agent/test_serenity_native_engine.py`
- `tests/test_compose_shared_backend.py`
- Git commits `8cfde8b` and `95e8f59`
