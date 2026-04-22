# Manual Acceptance for Tool-Calling Finance Agent

Scenarios to verify:

1) 用户问：“3月20日应该选择哪些股票呢”
- Agent produces a canonical recommendation bundle.
- If NO-TRADE, no BUY semantics appear in tags or text.

2) 用户问：“为什么选这三支呀”
- Agent grounds to current selection set via tools and explains only current run symbols.
- No symbols outside the current run appear in text/cards.

3) 用户问：“为什么空仓”
- Reply grounds to current run `tradeable=false` and/or `run_gating` reasons.

4) 用户点击第二只，再问：“这只还能买吗”
- After POST /api/chat/focus, next turn reads `focus_symbol` in session context.
- Reply grounds pick detail for the focused symbol.

5) 用户问：“这只现在该不该卖”
- Reply is grounded by `get_exit_decision` tool result for the resolved symbol.

6) 用户问：“为什么上次有这次没有”
- Reply uses `get_run_change` tool result to describe added/removed symbols.

7) 刷新页面再打开线程
- Timeline shows only user messages and assistant bundles.
- Right panel recovers from the latest bundle.

8) 普通用户界面
- No compare/sim/workbench entry points or pages.

