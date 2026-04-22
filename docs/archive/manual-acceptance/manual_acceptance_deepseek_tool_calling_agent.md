# Manual Acceptance for DeepSeek Tool-Calling Finance Agent

1) 用户问：“3月20日应该选择哪些股票呢”
- 生成 canonical assistant_bundle；如 NO-TRADE，不出现 BUY 语义。

2) 用户问：“为什么选这三支呀”
- 模型先调用 tools（get_session_context + explain/ensure），最终文本只解释当前 run 的 symbols，不包含 run 外 symbols。

3) 用户问：“为什么空仓”
- grounded 到当前 run 的 tradeable 与 run_gating/reason。

4) 用户点击第二只，再问：“这只还能买吗”
- 先 POST /api/chat/focus 更新 focus_symbol；下一轮 agent 从 get_session_context 读到 focus；
- 文本/卡片 grounded 到该 symbol 的 pick_detail。

5) 用户问：“这只现在该不该卖”
- grounded 到 get_exit_decision 的工具结果。

6) 用户问：“为什么上次有这次没有”
- grounded 到 get_run_change 的工具结果。

7) 刷新页面再打开线程
- 时间线只显示 user 与 assistant_bundle；右侧状态从最后一个 bundle 恢复；卡片不缩水。

8) 普通用户界面
- 不再看到 compare/sim/workbench 主入口。仅保留 /chat 与 /health。

