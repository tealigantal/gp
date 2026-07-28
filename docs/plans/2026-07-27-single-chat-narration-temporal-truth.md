# 单一聊天叙述链路与时间事实切除

## Purpose / Big Picture

将用户实际使用的 `POST /api/chat` 固化为唯一的 LLM 叙述入口。删除未接入的旧叙述模块和已断开的旧工具路由；聊天必须明确区分回答时刻、计划交易日、日线证据截止日与最后盘中观察，不能把旧运行态说成当前市场状态或下一交易日计划。

## Context and Orientation

- 当前生产入口为 `gateway/routes.py → ConversationService._narrate() → LLMClient.chat(..., contract_narration)`。
- `src/gp_assistant/llm/narrate.py` 使用已退休的 `tool_evidence_context` 输入和 `tool_evidence` 阶段；静态检索未发现任何调用、导入或动态入口。
- `tools/legacy/` 不在 `src` 打包范围内，未被当前 CLI、Compose、测试或文档引用，且依赖已不存在的旧 agent/tool 接口。
- 2026-07-27 真实容器聊天在 22:04 把 14:59 的历史 RuntimeObservation 描述为当前时刻，证明只靠 prompt 不能维护时间契约。

## Progress

- [x] 2026-07-27：用容器会话、发布、计划和运行态记录复现时间错述。
- [x] 2026-07-27：证明此前 `c519730` 只修改未接入的旧模块，容器运行的是当前源码而不是旧镜像。
- [x] 将当前聊天时间事实、回答权限和用户可见提示改为同一份确定性上下文。
- [x] 删除旧叙述模块、旧工具路由和仅服务于旧叙述的无消费者代码。
- [x] 只修改既有测试并完成真实容器聊天验证。

## Plan of Work

1. 在 `ConversationService` 中形成唯一的时间事实：回答时刻、当前阶段、当前是否可执行、计划交易日、日线日期、计划生成时刻、发布时刻、最后运行观察及其历史性质、恢复状态。
2. 将仍适用的用户叙述规则迁入该唯一生产 prompt：不编造、候选数值绑定、非当前计划不可称为可执行或下一交易日计划、日线日期与计划日期必须分开说明。
3. 在持久化前对关键时间/时态断言进行确定性校验；违反时由同一生产链路重生成，不能把错误文本写入会话。
4. 物理删除已证实无入口的 `src/gp_assistant/llm/narrate.py` 和 `tools/legacy/`；仅移除专属于这些死路径的无消费者代码，不删除仍被当前 LLMClient、语义分类、评分或 Serenity 使用的模块。
5. 修改现有聊天合约测试，覆盖收盘后旧计划、恢复中的最后完整发布和错误时间叙述被拒绝；不新增测试文件或测试数量。

## Concrete Steps

1. 用 `rg` 与包/入口配置证明删除目标无引用，再执行物理删除。
2. 运行 `python -m compileall -q src tests` 与 `python -m pytest -q`。
3. 运行 `docker compose config --quiet`，仅重建实际受影响的 `gp` 与 `gp-worker`；不改写数据卷或会话。
4. 在容器中发起一个可丢弃的真实聊天，验证实际回答时刻、计划交易日、日线日期和恢复状态不再混淆；删除该验证会话。

## Validation and Acceptance

验收要求：仓库不再存在旧叙述或旧工具路由入口；`/api/chat` 是唯一 LLM 叙述调用点；收盘后回复不能把 RuntimeObservation 时间说成回答时刻，不能把已结束的计划说成下一交易日计划，且错误回复不被持久化。评分、发布、聊天会话绑定和 Serenity 3% 事实保持不变。

## Idempotence and Recovery

删除仅针对无入口源码，不触碰 `store/`、计划、发布、会话或证据数据库。回退可通过前一 Git 提交恢复源码；本次不引入兼容分支或双叙述路径。

## Surprises & Discoveries

- 名为“收盘后叙述修复”的 `c519730` 提交只改了旧 `llm/narrate.py`，而实际 `/api/chat` 从未导入它。
- 现行 `ConversationService` 同时提供回答时刻和历史运行态，但没有定义它们的关系，且只过滤工程术语，不验证叙述时间真伪。

## Decision Log

- 采用物理删除，不保留旧叙述/旧工具兼容入口。
- 保留 `llm/semantics.py`、`LLMClient` 传输能力、评分和 Serenity 逻辑，因为它们仍有实在调用者；不得因目录名称或历史用途误删。
- 动态市场可执行性是回答时刻的投影，不改写不可变 `RecommendationPublication` 的历史运行事实。
- 聊天和健康查询使用运行账本的只读连接；缺失账本返回未启动/不可用状态，不能由一次读取创建 `market_runs.db`。

## Interfaces and Dependencies

HTTP 路由与会话数据模型保持兼容。聊天文字会获得正确的时间语义；健康和前端将只在确有必要时读取同一动态市场状态，不把历史 RuntimeObservation 重新定义为当前事实。

## Outcomes & Retrospective

已完成。物理删除 `src/gp_assistant/llm/narrate.py`、`tools/legacy/` 五个旧路由源码、只服务于旧 narrator 的 `LLMClient` 双阶段追踪接口及其旧测试，并移除无消费者的旧预算常量。保留仍有生产调用的 `LLMClient.chat`、通用运行遥测、`llm/semantics.py`、评分和 Serenity 路径。

2026-07-27 验证：`python -m compileall -q src tests`、`python -m pytest -q`（52 通过）、`docker compose config --quiet`、退役契约检查与 `git diff --check` 均通过。重建并重启了 `gp` 与 `gp-worker`，未触碰 `web` 和任何数据卷。通过真实 `POST /api/chat` 的可丢弃会话验证，22:39 的回答首段准确声明市场已收盘、2026-07-27 计划已经结束且仅供回顾、恢复为 3042/3044；正文中首段只出现一次，不含历史 `14:59`、错误的“收盘后发布”或“供明日开盘”表述。验证会话随后删除，返回 204。
