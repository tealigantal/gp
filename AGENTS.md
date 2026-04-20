GP Engineering Standard
0. 产品目标

GP 不是 demo，不是泛行情看板，也不是自动交易系统。
GP 是：

面向 A 股主板短线（1–3 个交易日）的 AI 选股决策助手。

所有代码修改都必须服务于下面四件事：

用户能拿到当前可信结论
结果能追溯到统一 canonical artifact
盘中 follow-up 足够快
任何时候都不能静默使用旧数据冒充最新
1. 最高优先级原则
1.1 正确性高于对话连续性

如果旧会话结论已经过时：

保留引用关系可以
复用旧市场事实不可以
1.2 freshness 必须是独立能力，不得散落

所有和下面内容相关的逻辑，必须统一收口到同一个 freshness policy：

交易日判断
收盘边界
5 分钟 bar 闭合判断
old run 是否可复用
是否只刷 pulse 还是重建 daybook

禁止在多个文件里各写一套 datetime.now() 判断。

1.3 LLM 不能替代系统状态机

LLM 负责：

理解用户意图
组织解释语言
理解“这只/第二只/上一轮”

LLM 不负责：

决定数据是否够新
推断今天日 K 是否已完成
在没有 refresh plan 的情况下替代系统做 freshness 决策
2. 架构边界
2.1 selection_engine/*

职责：

候选生成
策略评分
日线级结构分析

禁止：

处理会话记忆
处理 active_run 复用
处理 UI 层 follow-up
2.2 book/*

职责：

materialized market view
daybook
pulse
board

禁止：

直接决定用户意图
直接做历史 run 选择
2.3 runtime/*

职责：

freshness policy
orchestration
evidence planning
reference resolution

这是唯一允许决定“要不要刷新”“刷到什么粒度”“旧 run 能不能复用”的层。

2.4 memory/*

职责：

会话上下文
active_run / previous_run
focus symbol / compare set / user preferences

禁止：

存储未经 freshness 校验的“当前市场事实”作为默认真相
2.5 llm/*

职责：

parse
narrate

禁止：

编造数值
绕过 canonical artifact
绕过 freshness policy
3. Source of Truth 规则
3.1 canonical artifact

用户可见的市场结论必须能追溯到统一的：

run_id
book_version
daybook_effective_day
pulse_slot_at
market_phase
3.2 会话上下文不是 source of truth

会话里存的：

active_run_id
focus_symbol
compare_set

只是索引和引用工具，不是当前市场真相。

3.3 历史 run 必须显式进入

只有用户明确说：

上一次
前一次
上一轮
历史那轮

系统才进入历史 run 模式。
否则默认都回答“当前最新可用结论”。

4. 数据新鲜度规则
4.1 completed daily boundary

对于当前 GP 主线（A 股主板）：

收盘前：daybook 只能基于上一个 completed trading day
收盘后：必须切换到当日 completed daily day，或返回 close_pending_degraded
禁止静默使用旧 daybook 冒充收盘后最新
4.2 intraday pulse boundary

5 分钟判断只能基于：

当日
最近一个已闭合 bar

禁止：

使用未闭合 bar
使用昨天 pulse 伪装成今天盘中状态
4.3 refresh scope 最小化
单票问题：只刷单票或 active_run
recommend：刷 watchset
纯历史说明：不刷新
5. 代码修改流程
5.1 先设计，再改代码

以下改动必须先写设计文档或 RFC：

跨模块状态流改动
freshness policy 改动
canonical artifact 字段改动
active_run / previous_run 语义改动
API 合约改动

文档目录建议：

docs/rfcs/
docs/architecture/
5.2 一次 PR 只做一件主事

禁止把下面内容混成一个大杂烩提交：

freshness 重构
策略公式改动
UI 大改
prompt 大改

推荐拆法：

freshness policy
reference resolver
narrator / UI contract
tests
cleanup
5.3 保持兼容，分阶段迁移

如果字段要升级：

先新增字段
再保留旧字段兼容一轮
最后再删旧字段

禁止直接大面积 rename，导致 API/前端/历史 run 全挂。

6. 编码规则
6.1 所有时间敏感逻辑必须可测试

要求：

freshness 相关函数必须支持传入 now
不要在核心逻辑里写死 datetime.now()
不要把时区换算散落到多个文件
6.2 日历必须单点维护

要求：

交易日历读取、市场 phase 判断、slot 计算放同一处
不允许 calendar.py、datahub.py、routes.py 各写一套
6.3 命名必须表达真实语义

示例：

不要继续让 current_trading_day 同时表示“今天”和“已完成日线日”
应区分：
market_trade_day
daybook_effective_day
pulse_trade_day
6.4 prompt 和规则分层
规则判断写 Python
LLM 只做解释和柔性理解
不要把 freshness 这种硬状态机交给 prompt 猜
7. 测试规则

任何涉及下面内容的改动，都必须补测试：

收盘前 / 收盘后边界
开盘前 / 第一根 5m 未闭合
午间休市
周末 / 节假日
历史 run 显式访问
这只/第二只/上一轮 指代解析
topk 渲染一致性

最低要求：

unit tests
boundary tests
regression tests
8. 观测与日志

每次 market-facing 请求都应该能在日志中看到：

session_id
request
freshness_hint
market_phase
refresh_level
refresh_scope
daybook_effective_day
pulse_slot_at
invalidate_active_run
data_status

如果回答错了，必须能靠日志回放出：

当时系统认定的 phase
当时为什么没有/有刷新
用的是哪个 run / 哪个 slot
9. 前端与 API 合约

用户可见层必须始终显示关键 freshness 元信息：

run_id
as_of / daybook_effective_day
pulse_slot_at
market_phase
data_status
tradeable

禁止只给“结论文本”，不暴露 freshness 元信息。

10. 仓库卫生

以下内容禁止提交到仓库：

__pycache__/
*.pyc
本地 parquet/cache/store 产物
临时 notebook 输出
未使用的 prompt 实验文件

.gitignore 必须覆盖这些内容。

11. 提交与评审要求

推荐 commit 前缀：

feat(runtime): ...
fix(book): ...
refactor(memory): ...
test(freshness): ...
docs(architecture): ...

PR 描述必须回答：

这次改的是哪一层
为什么要改
哪些边界条件被覆盖
会不会影响 canonical artifact
新增了哪些测试
12. Codex 工作准则

Codex 每次改代码前必须先做：

阅读相关模块
明确 source of truth
列出影响面
优先最小可回滚改动
先补测试，再改逻辑，或至少同时提交测试

Codex 不得：

跨多个层随意塞逻辑
为了“看起来能跑”而静默降级成旧数据
在没有解释的情况下删字段、删接口、删历史兼容
13. 最后的非协商规则

宁可明确返回 degraded / pending，也不要把旧数据包装成最新数据。

这是 GP 的底线。