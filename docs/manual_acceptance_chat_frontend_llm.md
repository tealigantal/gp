# Manual Acceptance: Chat‑first + LLM Planner

1) 新建会话
- 打开 /chat，左侧“新建对话”。应进入空会话，右栏空。

2) 删除单个会话
- 在左侧列表，删除非当前会话。列表刷新。

3) 删除当前会话
- 删除当前会话后应自动切换到最近更新的一个；若没有则自动创建新会话并进入。

4) 今天给我3只
- 输入“今天给我3只”。中间出现一条 AI 文本“已生成推荐清单…”，并有“推荐清单”卡。右栏出现 run_id、top symbols、reused_run/cache/stale 等字段。

5) 给我5只
- 同上，topk=5 生效，卡片总数/预览反映变更。

6) 为什么今天空仓
- 返回 no_trade 卡，包含 run_gating.decision/reasons。

7) 第二只为什么
- 复用 active run；插入 pick_detail 卡，右栏 focus_symbol 更新。

8) 第一只为什么排第一
- 返回 pick_detail 卡；右栏不刷新 run，仅更新 focus（如需要）。

9) 601899止损怎么看
- 复用 active run；返回 pick_detail 卡中止损字段。

10) 601600的止盈止损点
- 同上；不触发新 recommend run。

11) 这只还能买吗
- 复用 active run + focus_symbol；返回 exit_decision 卡（HOLD/REDUCE/WATCH 等）。

12) 这只现在该不该卖
- 同 11。

13) 为什么上次有这次没有
- 返回 run_change 卡，列出变化摘要。

14) 为什么这次榜单变了
- 同 13。

15) 右栏是否显示 reused_run / stale / cache_level / refresh_reason
- 在 recommend/解释类请求后，右栏显示这些字段。

16) follow-up 是否复用 active run
- 连发 7-12 步，观察未重新计算推荐，右栏 active_run_id 不变。

17) recommendation / no_trade / pick_detail / compare / exit / run_change 是否都出现在消息流里
- 逐个请求；中间以卡片形式展示。

18) `/compare` `/sim` 是否不再是 Chat 主流程按钮
- 右栏不再展示 compare/sim 主入口。

