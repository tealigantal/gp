# Serenity 固定 3% 与统一 Worker 接入 ExecPlan

## Purpose / Big Picture

让 Serenity 重新参与股票推荐，但只作为 Adaptive Decision Engine 的确定性附加专家：对基础 Top-30 候选读取一个已完整提交、日期和候选集合完全匹配的公告批次；整批可用时固定权重为 3%，否则整批权重为 0%。采集在 `gp-worker` 内独立运行，任何数据源、解析或存储故障不得阻塞基础行情采集、计划生成或聊天。LLM 只解释已提交结果，并在系统提示词中理解 Serenity 的作用和归零规则。

## Progress

- [x] 2026-07-24：确认现行 Compose 已移除 Serenity 服务，但统一 worker 没有接管 Serenity 采集；生产计划固定写入零权重绑定。
- [x] 2026-07-24：确认 `PlanLookupKey` 未绑定 Serenity 批次身份，若不修正则异步完成的 3% 批次无法生成新计划。
- [x] 2026-07-24：定义固定 3% 的原子批次、快照读取和计划身份合同。
- [x] 2026-07-24：将 Serenity 采集以独立子进程故障域接入 `gp-worker`。
- [x] 2026-07-24：在 Adaptive 最终选择前应用整批 0%/3% 的加法贡献。
- [x] 2026-07-24：更新 LLM 系统提示词和产品/架构/运维文档。
- [x] 2026-07-24：执行合同、回归、容器及真实链路验证。
- [x] 2026-07-24：以同一最新镜像重建 `gp` 与 `gp-worker`，精确移除旧 `gp-gp-serenity-worker-1` 容器。

## Surprises & Discoveries

- 2026-07-24：2026-07-23 的合同内核切换同时删除了独立 Serenity 容器和采集实现；文档声称统一 worker 已接管，但当前 `worker` 命令只运行行情/计划/盘中刷新。
- 2026-07-24：仅恢复采集不会生效，因为现行计划缓存身份不随 Serenity 完整快照变化。
- 2026-07-24：旧 Serenity 运行库仍在 `store/serenity/evidence.db`，迁移必须保持追加语义，不能删除或改写既有证据。

## Decision Log

- 2026-07-24：采用用户指定的固定权重：完整兼容批次为 `0.03`，不完整、过期、目标不匹配或数据源失败统一为 `0.00`。
- 2026-07-24：按批次原子门控，不按个股分别降级，防止数据可得性对部分股票产生偏袒。
- 2026-07-24：Serenity 的有符号 alpha 限制在 `[-1, 1]`，最终贡献为 `0.03 * alpha`；完整但无相关证据时 alpha 为 0。
- 2026-07-24：采集网络调用只在统一 worker 的隔离执行单元中发生；计划生成只读取已提交快照且不等待网络。
- 2026-07-24：不可用状态使用稳定零权重身份，只有新的完整批次身份才使计划键变化，避免错误轮询制造计划抖动。

## Outcomes & Retrospective

实现和本地部署完成。当前生产计划使用 `adaptive_kernel_v3_serenity`，冻结 30 个基础候选。真实公告轮询在 `000100` 遇到无法解析的 PDF 后按合同将整个批次归零；计划仍正常发布，盘中状态继续刷新，没有发生部分候选加权。真实 LLM 回答用自然中文解释了 Top-30、固定 3%、最大正负 0.03、完整空结果中性以及数据失败整批归零，没有复述字段名、原因代码或工程接口。

最终 `gp` 与 `gp-worker` 均运行镜像 `sha256:c10be816d0671792fcdb27d94ad7e8720af4cf8737750ad4c5471e4509f3aa41`；Serenity 服务文件和提示词文件的容器摘要分别与本地一致。旧单独容器数量为 0，旧 `store/serenity/evidence.db` 保留未删，新合同写入独立的 `current.db`。当前真实状态为 degraded/0%，这是数据不完整时的正确生产结果，不是接入失败。

## Context and Orientation

当前推荐入口位于 `src/gp_assistant/application/real_producer.py`、`plan_service.py` 和 `decision_engine.py`；合同位于 `src/gp_assistant/contracts/`；统一 worker 入口位于 `src/gp_assistant/cli.py`。Serenity 当前只剩 `src/gp_assistant/serenity/policy.py`，而 Compose 已只保留 `gp`、`gp-worker`、`web`。运行证据目录是共享卷 `store/`，不得纳入 Git 或做破坏性迁移。

## Plan of Work

1. 建立小型现行 Serenity 合同与追加存储，保留官方公告采集/解析能力，不恢复已退役 RecommendationSnapshot 或旧决策权威。
2. 由计划生产器发布精确 Top-30 目标；Serenity worker 异步采集并原子提交目标批次。
3. 计划生成在 base 排序后读取匹配批次，应用固定 3% 有符号贡献，再交给 Adaptive Decision Engine 做最终选择。
4. 把合格批次身份或稳定零权重哨兵放入计划查找键，保证异步批次完成后能生成新计划。
5. 将采集循环以独立子进程和异常边界接入 `gp-worker`，并在健康状态暴露最新成功、最新错误和批次可用性。
6. 更新系统提示词、合同注册表、架构、产品、进度和验证台账。
7. 验证后重建同一最新镜像下的 `gp` 与 `gp-worker`，再按确切名称删除旧停止容器。

## Concrete Steps

- 使用 `rg`、Git 历史和现行合同审计恢复边界。
- 仅通过 `apply_patch` 修改源码、测试和文档。
- 执行 `python -m compileall -q src tests` 和 `python -m pytest -q`，并执行 Serenity 定向合同测试。
- 执行 `docker compose build gp`，分别强制重建 `gp` 和 `gp-worker`，不得使用 `--remove-orphans`。
- 验证两个容器镜像 ID、源代码摘要、健康状态和真实 `/api/chat` 说明链路。
- 再次核对容器名后执行 `docker rm gp-gp-serenity-worker-1`；共享 `store` 数据保留。

## Validation and Acceptance

- 完整、目标匹配的 Serenity 批次使所有 finalist 使用统一 `0.03` 权重；有证据的候选贡献受限于 `[-0.03, 0.03]`。
- 不完整、过期、目标不匹配、解析错误或来源失败时，所有候选的分数、排序、档位相对 base 逐项不变，绑定权重为 0。
- 完整但无相关公告的候选 alpha 和贡献为 0，不因“没有信息”受到奖励或惩罚。
- 新完整批次改变计划身份；连续失败/不完整轮询不制造新计划。
- Serenity 采集异常不终止或延迟基础 worker 循环，`/api/chat` 内无网络采集。
- LLM 系统提示词明确 Serenity 的来源、固定 3%、整批归零和非选股权威边界。
- `gp` 与 `gp-worker` 使用同一最新镜像；旧单独 Serenity 容器不存在；用户运行数据未删除。

### Executed evidence

- `python -m compileall -q src tests`：通过。
- `python -m pytest -q`：18 项通过；其中包含完整 evaluated-candidate 范围保留、未覆盖候选不得因 Top-30 内候选受到负贡献而进入 selected、公告证据首次真实观测时间保持，以及公开健康状态不泄漏底层采集错误的回归验证。
- `python -m gp_assistant.contracts.check_retired`：通过。
- `docker compose config --quiet` 与 `git diff --check`：通过。
- 定向测试覆盖完整正向/负向/中性、缺一只整批归零、来源失败、语义计划身份和 LLM 产品级上下文。
- 真实 worker：Serenity 子进程建立目标后报告 PDF 无法解析；健康状态为 degraded、批次不可用，现行计划及全部候选实际权重均为 0。
- 真实核心 worker：Serenity 失败后仍发布新计划与新 runtime，证明失败域未阻断核心循环。
- 真实 `/api/chat`：解释固定 3% 和整批归零，未输出字段名、原因代码、内部标识或接口；验证会话随后被精确删除并返回 404。
- 容器：API 健康，worker 运行；两者镜像 ID 一致；两个关键源码 SHA-256 与本地一致；旧容器已精确删除。

## Idempotence and Recovery

数据库迁移只创建新表或追加版本，不删除旧表和证据。worker 目标、批次和文档写入使用稳定身份，重复执行不会重复制造语义相同记录。若 Serenity 失败，回退状态自然是整批 0%，基础推荐继续；代码回滚不得恢复静态小名单、退役合同或独立 Serenity 容器。

## Artifacts and Notes

- 现行决策：`docs/adr/0010-serenity-fixed-three-percent-unified-worker.md`
- 被细化的旧决策：`docs/adr/0008-full-market-universe-and-additive-serenity.md`
- 历史实现仅用于提取官方数据源和解析逻辑，不恢复退役接口。

## Interfaces and Dependencies

- 输入接口：由计划侧提交日期、候选集合和稳定目标摘要，Serenity worker 读取后采集官方公告。
- 输出接口：不可变批次包含目标摘要、内容摘要、完整性状态和每个候选的有符号 alpha；推荐侧只读取完整兼容批次。
- 外部依赖沿用 `requests` 与 `pypdf`，不增加付费数据、密钥或公开 HTTP API。
