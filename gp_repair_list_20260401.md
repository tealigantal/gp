# GP 修复单（面向 Codex）

## 目标

本轮不是补丁修复，而是在**不新建主链、不做兼容、不加兜底**的前提下，把现有 Chat-first 主链修完整：

```text
gateway/routes.py
  -> runtime/turn_loop.py
     -> runtime/concern_parser.py
     -> runtime/evidence_planner.py
     -> judgment/engine.py
     -> runtime/narrator.py
     -> memory/service.py
```

## 已确认的现状（当前代码）

1. `judgment/engine.py` 当前只完整支持 `chat / recommend / compare`。`explain / live_check / run_change / exit` 只在 `evidence.subject_entry is not None` 时才成立，否则直接抛 `ValueError`。
2. `runtime/turn_loop.py::_resolve_subject_entry()` 当前只弱解析 `references.symbol / references.rank / session.focus_subject`，而且 symbol 优先从 `book.board` 找，不是从 `active_run.picks` 找。
3. `runtime/evidence_planner.py` 已接入，但 `run_change` 只要求 `active_run + previous_run`，`judgment/engine.py` 却还把它塞进 `judge_followup()` 逻辑，语义不成立。
4. `book/daybook.py::_map_pick()` 当前把 `item['explain']` 直接映射到 `AdvicePick.thesis` 和 `AdvicePick.why_selected`。
5. `selection_engine/agent.py` 仍在把内部评分串（如 `champ=...`）作为 explain 源输出，导致用户可见层泄漏 debug 文本。
6. 前端右侧快照仍然直接读 `book.board`，而不是优先读 `latestResponse.right_panel.top3` 或 transcript 里的 canonical message。
7. 前端主结论卡 `MainConclusionCard.tsx` 还是硬编码文案，不是数据驱动。

## 现网错误证据

日志里已经明确出现两类 500：

- `request=explain` 导致 `/api/chat` 500
- `request=exit` 导致 `/api/chat` 500

根因都是 `make_judgment()` 抛出：`Unhandled request or missing evidence`。

---

## 改造原则（必须遵守）

1. **不新建第二条主链**。
2. **不做 fallback recommend**。
3. **不做 legacy 兼容输出**。
4. **不允许用户可见层读取 debug explain**。
5. **所有 request 都必须有明确 handler 或明确的 evidence 约束**。
6. **所有 symbol/rank/focus 解析统一走一个 resolver**，不准分散写。
7. **前端只以 canonical message / right_panel 为准**，不再自行拼接另一套结论。

---

# 一、后端修复（P0）

## 1. `src/gp_assistant/judgment/engine.py`

### 目标
把当前半截 dispatcher 改成**完整 dispatcher**。

### 必做

- 保留 `chat / recommend / compare / exit` 现有入口，但重构为总分发。
- 新增并接入以下 handler：
  - `judgment/explain.py`
  - `judgment/live_check.py`
  - `judgment/run_change.py`
- 删除最后的裸 `raise ValueError(...)` 作为正常业务路径。
- 对于每个 request，只允许两种结果：
  1. 命中合法 handler 并返回 `Judgment`
  2. 由于 parser 或 evidence 契约被破坏，抛出**明确的开发期错误**（不是业务 fallback）

### 目标分发规则

- `chat` -> `judge_chat()`
- `recommend` -> `make_recommendation()`
- `compare` -> `compare_entries()`
- `explain` -> `judge_explain()`
- `live_check` -> `judge_live_check()`
- `exit` -> `judge_exit()`
- `run_change` -> `judge_run_change()`

### 关键要求

- `run_change` 绝不能再走 `judge_followup()`。
- `market explain` 绝不能依赖 `subject_entry`。
- `exit` 不能因为缺 `subject_entry` 就直接 500；必须通过 resolver 层把 evidence 做对。

---

## 2. 新增 `src/gp_assistant/judgment/explain.py`

### 职责
处理两类 explain：

1. `subject in {market, run}`：
   - 为什么今天空仓
   - 为什么今天不做
   - 为什么先观察
   - 为什么第一只是它 / 为什么不是第一

2. `subject in {symbol, pick}`：
   - 这只为什么推荐
   - 第二只为什么不是第一只
   - 某只股票的结构、entry/stop/take、execution_state、invalidated

### 输入约束

- `market/run explain`：依赖 `book`、可选 `active_run`
- `symbol/pick explain`：依赖 `subject_entry`，优先来自 `active_run`

### 输出
`Judgment(kind='explain', ...)`

### 禁止
- 不准直接拼 raw debug explain
- 不准调用 recommend 重跑

---

## 3. 新增 `src/gp_assistant/judgment/live_check.py`

### 职责
回答“现在还能买吗 / 现在还能做吗 / 盘中怎么看”。

### 依赖
- 必须有 `subject_entry`
- 优先读取 `entry.pulse`
- 没有 `pulse` 时，可退回 `entry.execution_state/can_open/invalidated`

### 输出
`Judgment(kind='live_check', ...)`

### 禁止
- 不准重跑推荐
- 不准走 followup 泛化文案

---

## 4. 新增 `src/gp_assistant/judgment/run_change.py`

### 职责
回答：
- 为什么这次和上次不一样
- 为什么之前有这次没有
- 为什么榜单变了

### 依赖
- `active_run`
- `previous_run`

### 实现要求
至少比较：
- symbol 集合差异：新增 / 移除 / 共存
- rank 变化：up/down/same
- run.tradeable / run.reason 差异

### 输出
`Judgment(kind='run_change', ...)`

### 禁止
- 不准依赖 `subject_entry`
- 不准重跑 recommend

---

## 5. `src/gp_assistant/runtime/evidence_planner.py`

### 目标
把 evidence 需求与 request 语义完全对齐。

### 修改要求

- `chat`：全部 false
- `recommend`：`publish_run=True`, `need_validation=True`
- `explain`：
  - `subject in {market, run}` -> `need_active_run=True`
  - `subject in {symbol, pick}` -> `need_active_run=True`, `need_subject_entry=True`
- `live_check`：`need_active_run=True`, `need_subject_entry=True`
- `compare`：`need_active_run=True`, `need_compare_entries=True`
- `exit`：`need_active_run=True`, `need_subject_entry=True`, `need_portfolio=True`
- `run_change`：`need_active_run=True`, `need_previous_run=True`

### 禁止
- 不准让 `market explain` 默认去找 `subject_entry`

---

## 6. `src/gp_assistant/runtime/turn_loop.py`

### 目标
把 subject / compare 对象解析做成**统一强解析**。

### 必做改造

#### 6.1 抽出 resolver
新增文件：
- `src/gp_assistant/runtime/reference_resolver.py`

将 `_entry_by_symbol` / `_entry_by_rank` / `_resolve_subject_entry` 移过去，统一管理。

#### 6.2 resolver 解析优先级
对 symbol/pick/exit/live_check/explain：

1. `references.focus_symbol`
2. `references.symbol`
3. `references.compare_symbols`
4. `references.symbols`
5. `references.rank`
6. `session.focus_subject`

#### 6.3 symbol 查找顺序
优先：
- `active_run.picks`
再 fallback：
- `book.board`

#### 6.4 rank 查找顺序
优先：
- `active_run.picks`（当前会话语义）
再 fallback：
- `book.board`

#### 6.5 compare set 解析
支持：
- `references.compare_symbols`
- `references.symbols`
- `session.compare_set`

#### 6.6 `build_evidence_pack()`
- 按 `plan` 调用 resolver
- `run_change` 不解析 subject_entry
- `market explain` 不强行解析 subject_entry

### 验收条件

- “第二只现在还能买吗” 能锚定 `active_run` 第 2 只
- “看 002371 卖出判断” 能 resolve 到 002371
- “为什么这次和上次不一样” 不要求 symbol

---

## 7. `src/gp_assistant/book/daybook.py`

### 目标
彻底切断 debug explain 到用户字段的传播。

### 必改

#### 当前错误

```python
thesis = item.get('thesis') or item.get('explain')
why_selected = item.get('explain')
```

#### 改成

优先读取：
- `item['user_thesis']`
- `item['why_selected_text']`

如果没有，再允许：
- `item['thesis']`

**禁止**继续读 `item['explain']` 作为用户字段。

### 建议
新增 helper：
- `_pick_user_thesis(item)`
- `_pick_user_reason(item)`

---

## 8. `src/gp_assistant/selection_engine/agent.py`

### 目标
内部 debug 与用户文案分层。

### 必改
当前所有 pick 输出，分成三层：

- `debug_explain`: 内部调试串
- `reason_codes`: 结构化原因码数组
- `user_thesis`: 给用户看的中文短句

### 要求

- 原先类似 `champ=..., cand=..., rr=...; off_mainline_downrank` 只允许出现在 `debug_explain`
- `user_thesis` 必须是中文产品文案，例如：
  - “结构候选靠前，但当前执行状态仍偏观察，等待盘中确认。”
  - “相对同组候选更接近计划买点，但主线权重不足，暂列观察。”

### 禁止
- 不准再把 debug 串赋给 `explain`
- 不准让下游只能读 `explain`

---

## 9. `src/gp_assistant/runtime/narrator.py`

### 目标
canonical message 只读用户字段，不复活 debug。

### 必改

#### `_canonical_pick()`
- `thesis` 取 `pick.thesis`
- `why_selected_text` 取 `pick.why_selected`
- 不要拼任何 raw score/debug info

#### `_build_canonical_message()`
新增支持：
- `message_kind='explain'`
- `message_kind='live_check'`
- `message_kind='run_change'`

不要都落成 `'followup'`。

#### `build_reply()`
- `right_panel.top3` 优先级保留：`judgment.run -> evidence.active_run -> book.board`
- `planner_trace` 保留 `frame` 即可，不要把 debug explain 混进 message

---

## 10. `src/gp_assistant/memory/service.py`

### 目标
状态更新严格收口。

### 必改

- `chat`：不更新 run/focus/compare_set（现状基本对）
- `run_change`：不更新 `focus_subject`
- `explain/live_check/exit`：如果存在 `subject_entry`，更新 `focus_subject` 为 symbol
- `compare`：更新 `compare_set`
- `recommend`：更新 `active_run_id / previous_run_id`

### 禁止
- 不准把 `run_change` 当成新的 run

---

# 二、前端修复（P1）

## 11. `frontend/src/shared/contracts.ts`

### 目标
前端 canonical message 类型补齐。

### 必改

现在只有：
- `recommend`
- `followup/compare/exit/no_trade`

改成明确联合类型：
- `recommend`
- `explain`
- `live_check`
- `compare`
- `exit`
- `no_trade`
- `run_change`
- `chat`

### 禁止
- 不准再用 `followup` 一把兜所有后续类型

---

## 12. `frontend/src/features/workspace/components/ChatThread.tsx`

### 目标
按 `message_kind` 精确渲染。

### 必改

- `recommend` -> `RecommendationMessageCard`
- `explain` -> `FollowupTextMessage`
- `live_check` -> 新组件 `LiveCheckMessageCard`
- `compare` -> `FollowupTextMessage` 或独立 compare card
- `exit` -> `ExitDecisionMessage`
- `run_change` -> 新组件 `RunChangeMessageCard`
- `chat` -> `FollowupTextMessage` + suggestions

### 关键修复
当前 pending assistant turn 只写了：
- `run_id`
- `symbols`

没有把 `message` 带进去，导致发送后直到 session 刷新前，UI 可能渲染不全。

必须补上：
- `message`
- `right_panel`

---

## 13. `frontend/src/features/workspace/components/RecommendationPickCard.tsx`

### 目标
只显示用户文案。

### 必改

- 保留 `thesis / why_selected_text`
- 但前提是后端不再注入 debug
- 将下面四个 Tag 改成真正可点击 follow-up 事件，透传给 `onPrompt`

### 禁止
- 不准渲染任何含 `champ=` / `cand=` / `rr=` / `off_mainline_` 的文本

---

## 14. `frontend/src/features/workspace/components/DecisionSnapshot.tsx`

### 目标
右侧快照和主消息同源。

### 必改

当前直接读：
- `book.board.slice(0, 3)`

改成优先：
1. `latestResponse.right_panel.top3`
2. transcript 最近一条 assistant.meta.right_panel.top3
3. 最后才 fallback `book.board`

### 原因
这样右侧不会和本轮聊天消息错位。

---

## 15. `frontend/src/features/workspace/components/MainConclusionCard.tsx`

### 目标
取消硬编码结论。

### 必改

当前写死：
- “环境 A 级，主线强度仍在。”
- “只做当前可买，不追已经拉伸的票。”

改成从：
- `book.daybook.tradeable`
- `book.daybook.reason`
- `book.last_closed_5m`
- `book.updated_at`

动态生成。

### 禁止
- 不准继续显示硬编码市场结论

---

## 16. `frontend/src/features/workspace/useAdvisorWorkspace.ts`

### 目标
同步 pending turn 的 canonical message。

### 必改
在 `pendingTurn.assistant` 注入到 `turns` 时，assistant meta 里增加：
- `message`
- `right_panel`
- `planner_trace`

否则发送后短时间内 UI 看到的是半成品。

---

# 三、测试（必须补）

## 17. 新增后端测试

目录建议：
- `tests/runtime/test_reference_resolver.py`
- `tests/judgment/test_dispatcher.py`
- `tests/runtime/test_turn_loop_intents.py`
- `tests/book/test_daybook_mapping.py`

### 必测用例

1. `你好` -> `chat` -> 200
2. `今天给我3只` -> `recommend` -> 200
3. `为什么今天空仓` -> `explain(subject=market)` -> 200
4. `看002371卖出判断` -> `exit` -> 200
5. `第二只现在还能买吗` -> `live_check` -> 200
6. `为什么这次和上次不一样` -> `run_change` -> 200
7. `book/daybook._map_pick()` 不再把 `item['explain']` 映射到 `thesis/why_selected`

### 关键断言

- `make_judgment()` 对合法 request 不再抛 `Unhandled request or missing evidence`
- `Recommendation message` 中不再出现 `champ=` / `cand=` / `rr=`

---

## 18. 新增前端测试

目录建议：
- `frontend/src/features/workspace/components/__tests__/ChatThread.test.tsx`
- `frontend/src/features/workspace/components/__tests__/DecisionSnapshot.test.tsx`

### 必测

- `message_kind='recommend'` 正常渲染结构化卡片
- `message_kind='exit'` 正常渲染卖出卡
- `message_kind='run_change'` 正常渲染差异卡
- pending assistant turn 也能渲染 `message`
- right panel 优先吃 `right_panel.top3`

---

# 四、实施顺序（必须按顺序）

## PR-1：后端 dispatcher 与 evidence 收口
改：
- `judgment/engine.py`
- `judgment/explain.py`（new）
- `judgment/live_check.py`（new）
- `judgment/run_change.py`（new）
- `runtime/evidence_planner.py`
- `runtime/turn_loop.py`
- `runtime/reference_resolver.py`（new）

## PR-2：用户字段与 debug 分层
改：
- `selection_engine/agent.py`
- `book/daybook.py`
- `runtime/narrator.py`

## PR-3：前端 canonical message 收口
改：
- `frontend/src/shared/contracts.ts`
- `frontend/src/features/workspace/components/ChatThread.tsx`
- `frontend/src/features/workspace/components/RecommendationPickCard.tsx`
- `frontend/src/features/workspace/components/DecisionSnapshot.tsx`
- `frontend/src/features/workspace/components/MainConclusionCard.tsx`
- `frontend/src/features/workspace/useAdvisorWorkspace.ts`

## PR-4：测试与回归
改：
- 后端 tests
- 前端 tests

---

# 五、完成标准（必须满足）

1. `/api/chat` 对 `explain` 不再 500。
2. `/api/chat` 对 `exit` 不再 500。
3. `run_change` 不再依赖 `subject_entry`。
4. 推荐卡片不再出现任何 `champ=` / `cand=` / `rr=` / `off_mainline_...`。
5. 右侧快照与聊天主消息在同一轮对话中展示同一组 top3。
6. `MainConclusionCard` 不再显示硬编码市场总结。
7. 所有 request 都有明确 handler，engine 内不存在业务 fallback recommend。

