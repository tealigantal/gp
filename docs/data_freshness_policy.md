GP 数据刷新与会话复用规则
1. 目标

GP 必须把下面三层东西彻底分开管理：

日 K / daybook 层
决定市场门控、候选池、排序、canonical run 的基线。
5 分钟线 / pulse 层
决定 execution_state、can_open、entry_distance、盘中还能不能买、止盈止损是否触发。
会话上下文层
只负责“这只、第二只、上一次那轮”这类引用关系，不负责复用旧市场事实。

系统必须遵守下面的铁律：

会话记忆可以复用引用关系，不能绕过 freshness 校验复用旧市场结论。
跨收盘边界以后，旧 run 默认失效，不能继续当成“当前最新结论”。
5 分钟线只能使用“最近一个已收完的 bar”，不能读未收完 bar。
如果跨边界后新数据尚未落地，只能进入 degraded/pending 状态，不能假装旧数据还是新的。
2. 交易时段边界（按当前 A 股主板规则）

按上交所、深交所公开投资者教育规则：

开盘集合竞价：09:15 - 09:25
连续竞价：09:30 - 11:30、13:00 - 14:57
收盘集合竞价：14:57 - 15:00

并且：

深交所主板没有 15:05 - 15:30 的盘后定价交易
该盘后阶段保留在创业板等非当前主板主线范围
上交所的 15:05 - 15:30 盘后固定价格交易属于科创板规则，不应拿来定义 GP 主板项目的日 K 完成边界

因此，GP 的日 K 完成边界应定义为：15:00 收盘后立即进入“可切换到当日 completed daily bar”的状态；若数据源落地有延迟，进入 close_pending 降级状态，而不是继续把旧日 K 当成最新。

3. 核心定义
3.1 daybook_effective_day

用于构建 daybook 的“已完成日线交易日”。

规则：

收盘前：daybook_effective_day = 上一个已完成交易日
收盘后且当日日线已确认可取：daybook_effective_day = 当日
非交易日：daybook_effective_day = 最近一个已完成交易日
3.2 pulse_trade_day

5 分钟线所属的交易日。

规则：

盘中只允许取当日
非交易日不刷新当日 pulse
不允许跨天沿用昨天 pulse 冒充今天 pulse
3.3 pulse_slot_at

最近一个已闭合的 5 分钟 bar 时间。

示例：

09:32：没有当日 closed 5m bar
09:36：最近 closed slot 是 09:35
11:58：最近 closed slot 是 11:30
13:02：最近 closed slot 仍是 11:30
14:48：最近 closed slot 是 14:45
15:01：最近 closed slot 是尾盘最后一个已确认 slot（供应商可能表现为 14:55 或 15:00，实现层必须做供应商归一化）
3.4 market_phase

统一用一个枚举描述市场时段：

NON_TRADING
PREOPEN
OPEN_NO_FIRST_BAR
INTRADAY_AM
LUNCH_BREAK
INTRADAY_PM
POSTCLOSE_PENDING
POSTCLOSE_READY
3.5 active_run_validity

旧 run 是否还能当“当前默认结论”复用，必须同时满足：

active_run.daybook_effective_day == target_daybook_effective_day
若请求需要盘中状态，active_run.pulse_trade_day == target_pulse_trade_day
若请求需要盘中状态，active_run.pulse_slot_at >= target_pulse_slot_at
当前请求没有显式要求 rebuild_daybook
用户没有跨到新的 completed daily boundary
用户没有说“我要看最新一轮/重新给我”

只要有一条不满足，旧 run 就不能默认当最新结论。

4. 刷新层级

定义四种刷新级别：

L0 no_refresh

只复用已有 book/run，不拉新数据。
仅适用于：

纯闲聊
历史 run 对比
与行情无关的说明
L1 pulse_only

只刷新 5 分钟线，不重建 daybook。
适用于：

盘中 live_check
盘中 exit
盘中 现在还能买吗
同一 completed day 下的 intraday recommend / explain
L2 rebuild_daybook

只重建 daybook，不做 5m 刷新。
适用于：

收盘后日 K 已确认
用户显式要求“重算日线/重新跑推荐”
非交易日读取最近 completed day 的静态结果
L3 rebuild_daybook_and_pulse

先重建 daybook，再刷新 5m。
适用于：

新交易日首次进入盘中且需要完整视图
当天首次 recommend 且当前 book 不存在
某些强一致性场景下需要把 board 和 pulse 一并对齐
5. 刷新作用域

为了“正常使用 + 快”，刷新不能每次都打全量。

定义 scope：

none
subject_only
active_run
watchset

规则：

exit/live_check/单票 explain：默认 subject_only 或 active_run
compare：compare_symbols + active_run 最小集
recommend：watchset
纯历史 run_change：none

禁止在单票盘中查询时，仍然无脑刷新整个 watchset。

6. 具体业务规则
6.1 收盘前数据库、收盘后提问
规则

如果数据库中的 daybook_effective_day 仍是上一交易日，而用户提问时已经跨过主板收盘边界：

旧 active_run 立即失效为“非当前最新”
不允许直接用上一次聊天的推荐结果回答“今天给我 3 只/今天为什么空仓/这次第一只是啥”
必须尝试重建 daybook
如果数据源还没落地，返回 POSTCLOSE_PENDING / DEGRADED，明确说“收盘后日线确认中”，而不是继续把旧 run 当最新
结论

你举的这个例子必须刷新，不允许沿用旧对话数据。

6.2 开盘前数据库、开盘后提问
规则

如果数据库时间是开盘前，用户在 10:00 提问：

不重建 daybook
daybook_effective_day 仍是上一个 completed trading day
只刷新当日 5 分钟线
若当日第一根 closed 5m 还没出来，则返回 OPEN_NO_FIRST_BAR，不能把昨天最后一根 5m 当成今天最新
结论

你举的这个例子应该只刷新 5 分钟线，不重建日 K。

6.3 盘中普通 follow-up

示例：

第二只现在还能买吗
601899 止损怎么看
这只现在该不该卖

规则：

默认最少做 L1 pulse_only
不重建 daybook
如果 pulse_slot_at 已经推进，则生成新鲜判断
若用户说的是“上一次那轮第二只”，进入历史模式，但必须提示“这是历史 run 视角，不代表当前最新盘中状态”
6.4 午间休市

11:30 - 13:00：

不存在新的 closed 5m slot
pulse_slot_at 固定在上午最后一根
可复用上午最后 closed slot
不得伪造“最新”成 12:xx 的 5m 状态
6.5 非交易日

周末或节假日：

不刷新当日 5m
daybook_effective_day = 最近一个已完成交易日
推荐结果默认是“最近 completed day 的静态结论 + 当前市场关闭提示”
如果用户问“现在还能买吗”，应明确返回市场关闭态，而不是沿用上一个交易日盘中 pulse
6.6 历史对话复用规则
可以复用
“这只/第二只/上一轮/前一次”这类引用关系
previous_run_id
compare_set
focus_symbol
用户偏好（topk、风险风格等）
不可以复用
旧 run 的 BUY/WATCH/SELL 结论作为“当前最新”
旧 5 分钟 execution_state
旧 last_closed_5m
旧 market gate 作为今天收盘后的最新 gate
特殊规则

只有用户显式说：

上一次
前一次
上一轮
历史那轮

系统才允许把旧 run 当查询对象。
否则默认都按当前最新可用市场视角来答。

7. 实现算法

建议改成两阶段：

第一阶段：轻量 pre-parse

在真正 ensure_book() 前，先做一个不依赖新 book 的轻量 freshness 预判。

输入：

user_message
session metadata
current book metadata
now

输出：

request_hint
freshness_hint
history_mode
target_scope

这一步优先用确定性规则 + 少量 LLM 辅助，而不是先完整跑旧 book。

第二阶段：refresh planner

生成：

RefreshPlan {
  level,
  scope,
  target_daybook_effective_day,
  target_pulse_trade_day,
  target_pulse_slot_at,
  invalidate_active_run,
  history_mode,
  reason_codes[]
}
第三阶段：执行刷新
若 L0：直接用现有 book
若 L1：刷新 pulse，仅限 scope
若 L2：重建 daybook
若 L3：重建 daybook + pulse
第四阶段：完整 parse / evidence / judgment / reply

此时再用新鲜 book 跑完整的 concern parser、evidence planner、judgment engine、narrator。

8. 数据模型建议
8.1 MarketBook 新增字段
daybook_effective_day: str
pulse_trade_day: Optional[str]
pulse_slot_at: Optional[str]
market_phase: str
data_status: str
calendar_source: str
8.2 AdviceRun 新增字段
daybook_effective_day: str
pulse_trade_day: Optional[str]
pulse_slot_at: Optional[str]
market_phase: str
data_status: str
8.3 SymbolPulse 新增字段
trade_day: Optional[str]
slot_at: Optional[str]
is_stale: bool
stale_reason: Optional[str]
8.4 SessionState 新增字段
active_run_daybook_effective_day: Optional[str]
active_run_pulse_trade_day: Optional[str]
active_run_pulse_slot_at: Optional[str]
last_focus_rank: Optional[int]
last_focus_symbol: Optional[str]
9. 必须满足的验收标准
跨收盘边界后，旧 run 不能再作为当前默认结论。
盘中单票问题只刷新必要的 5 分钟线，不重跑整套日 K。
早盘第一根 5 分钟线未闭合前，不允许把昨天 pulse 当今天最新。
周末/节假日不会刷新伪“今天 5 分钟线”。
用户说“上一次那轮”时，系统能查历史，但会明确标注历史视角。
所有用户可见结论都能追溯到：
run_id
book_version
daybook_effective_day
pulse_slot_at
market_phase
10. 推荐的测试样例
09:20 -> 10:00：只刷新 pulse，不重建 daybook
14:20 -> 14:45：只刷新 pulse
14:58 -> 15:01：旧 run 失效；若 close data 未 ready，返回 POSTCLOSE_PENDING
15:06 且 close data ready：重建 daybook 为当日
周五收盘 -> 周六提问：不刷新 pulse，返回市场关闭视图
昨天第二只今天还能买吗：默认按最新市场视角回答；只有显式“上一轮”才走历史
09:32：禁止沿用昨天 pulse 冒充今天盘中状态