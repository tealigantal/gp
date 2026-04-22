Codex 执行指令：freshness 重构第一阶段

你是本仓库的 staff engineer。
你的任务不是改策略收益逻辑，而是完成 数据 freshness / 会话复用 / 盘中快速刷新 的基础重构。

目标

在不改变选股策略数学逻辑的前提下，实现下面目标：

收盘前数据 + 收盘后提问时，不再复用旧 run
开盘前数据 + 开盘后提问时，只刷新 5 分钟线，不重建 daybook
盘中单票 follow-up 只刷新必要 symbol，不无脑刷整个 watchset
旧 pulse 不能跨天冒充今天最新
active_run 的复用必须同时校验 daybook 和 pulse freshness
用户显式说“上一轮/前一次”时，才能进入历史 run 视角
必读文件

先完整阅读以下文件，再开始改：

gp_assistant/runtime/turn_loop.py
gp_assistant/runtime/concern_parser.py
gp_assistant/runtime/reference_resolver.py
gp_assistant/llm/interpret.py
gp_assistant/book/engine.py
gp_assistant/book/pulse5m.py
gp_assistant/evidence/market_service.py
gp_assistant/selection_engine/calendar.py
gp_assistant/selection_engine/datahub.py
gp_assistant/contracts/objects.py
gp_assistant/memory/service.py
gp_assistant/runtime/narrator.py
gp_assistant/gateway/routes.py
P0：必须实现
1. 新建统一 freshness policy

新增文件：

gp_assistant/runtime/market_clock.py
gp_assistant/runtime/freshness_policy.py

要求：

统一输出 market_phase
统一计算：
target_daybook_effective_day
target_pulse_trade_day
target_pulse_slot_at
支持：
NON_TRADING
PREOPEN
OPEN_NO_FIRST_BAR
INTRADAY_AM
LUNCH_BREAK
INTRADAY_PM
POSTCLOSE_PENDING
POSTCLOSE_READY
优先使用官方交易日历缓存；没有时才降级为 weekday，并打 warning / degraded 标记
2. 重构 turn loop 顺序

当前问题是：先 ensure_book()，后 parse。
必须改成：

读取 session/book metadata
做轻量 freshness pre-parse
生成 RefreshPlan
依据 RefreshPlan 刷新 book
再跑完整 parse_concern
再跑 evidence / judgment / narrator

要求：

不允许继续保留“先旧 book，后 freshness 解释”的顺序
轻量 pre-parse 可以先用规则法；不要一开始把问题做成重 LLM 依赖
3. 改造 ensure_book()

把：

ensure_book(force_rebuild: bool = False)

改成支持 refresh plan，例如：

ensure_book(refresh_plan: RefreshPlan) -> MarketBook

要求：

能区分 L0 / L1 / L2 / L3
能区分 pulse refresh scope：
none
subject_only
active_run
watchset
4. 改造 pulse 逻辑，禁止跨日脏状态

修改：

gp_assistant/book/pulse5m.py
gp_assistant/contracts/objects.py

要求：

SymbolPulse 增加：
trade_day
slot_at
is_stale
stale_reason
当 target_pulse_trade_day != existing_pulse.trade_day 时，必须清空或标 stale
不能在今天 09:32 没有 closed 5m bar 时继续沿用昨天 pulse
不能在周末/节假日把上个交易日 pulse 当最新盘中状态
5. 给 AdviceRun 和 SessionState 补 freshness metadata

要求新增字段：

daybook_effective_day
pulse_trade_day
pulse_slot_at
market_phase
data_status

要求：

active_run 的复用不能只看 book_version
book_version 继续保留用于 daybook 版本
但 run 是否足够新，还要看 pulse freshness
6. 收盘边界禁止静默沿用旧 run

要求：

一旦跨过主板收盘完成边界，旧 run 默认不能再作为当前最新
若当日日线数据还没落地，返回 POSTCLOSE_PENDING / DEGRADED
绝不能继续拿旧 run 假装是“当前最新推荐”
P1：顺手一起修
7. 修 compare_symbols / symbols 键不一致

修改：

gp_assistant/runtime/reference_resolver.py
必要时同步 concern_parser.py

要求：

symbols 和 compare_symbols 统一归一
compare follow-up 稳定可用
8. 增加 rank / 指代解析

要求至少支持：

第二只
第一只
这只
这个票
上一轮第二只

实现建议：

规则 parser 优先处理中文序数
SessionState 里增加 last_focus_rank 和 last_focus_symbol
9. narrator.py 尊重真实 topk

要求：

用户请求多少只，就渲染多少只
不再把 recommend message 和 right panel 强行写死 [:3]
10. 单票请求的 pulse 刷新改成最小作用域

要求：

exit/live_check/symbol explain 默认只刷新 subject 或 active_run symbols
不再每次单票问答都刷新完整 watchset
明确禁止
禁止顺手改策略分数、阈值、选股公式
禁止把 freshness 问题混进 prompt 工程里“靠模型自己理解”
禁止把交易时段边界散落到多个文件
禁止继续用 yesterday pulse 冒充 today pulse
禁止为了省事把 POSTCLOSE_PENDING 再回退成旧 run
建议新增测试

新增测试文件，至少覆盖：

test_preopen_uses_previous_completed_daybook
test_open_no_first_bar_does_not_reuse_yesterday_pulse
test_intraday_only_refreshes_pulse
test_postclose_invalidates_old_run
test_postclose_pending_returns_degraded_not_old_run
test_weekend_no_fake_today_pulse
test_compare_symbols_reference_resolution
test_rank_reference_second_pick
test_recommend_respects_requested_topk

所有 freshness 相关函数必须支持注入 now，不要把 datetime.now() 写死在逻辑中心。

输出要求

完成后请给出：

改了哪些文件
每个文件改动目的
哪些旧字段保留为兼容层
哪些测试新增
还有哪些后续可做但本轮没做