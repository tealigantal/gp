# GP Intent Layer Formalization — Codex 实施单

## 0. 目标

本轮不是补丁修复“你好触发推荐”，而是把 **Intent Layer** 正式收口为单一主链内的领域层：

- 不新建主链
- 不做兼容
- 不做 fallback recommend
- 非交易输入成为正式 request 类型
- 所有 request 必须有显式 handler
- chat 不触发推荐、不发布 run、不污染 session 状态

与现有主链保持一致：

```text
gateway/routes.py
  -> runtime/turn_loop.py
     -> runtime/concern_parser.py
     -> runtime/evidence_planner.py
     -> judgment/engine.py
     -> runtime/narrator.py
     -> memory/service.py
```

## 1. 当前已验证的问题（按现代码）

### 1.1 parser 会默认补成 recommend
文件：`src/gp_assistant/llm/interpret.py`

当前存在：

```python
obj.setdefault('subject', 'run')
obj.setdefault('request', 'recommend')
obj.setdefault('freshness', 'current_book')
```

结果：只要 LLM 返回 JSON 不完整，`request` 就会被直接补成 `recommend`。

### 1.2 engine 对未覆盖 request 会掉回 recommend
文件：`src/gp_assistant/judgment/engine.py`

当前存在：

```python
if evidence.subject_entry is not None:
    return judge_followup(...)
# default to recommendation if subject could not be anchored
return make_recommendation(...)
```

结果：即使 `frame.request == "chat"`，只要没有 subject_entry，也会最终推荐。

### 1.3 concern_parser 只是 LLM 透传层
文件：`src/gp_assistant/runtime/concern_parser.py`

当前只有：

```python
context = build_context(memory_ctx, book)
return parse_turn_frame(context, user_message)
```

没有：
- preclassify
- validate
- normalize
- request gating

### 1.4 turn_loop 没接 evidence planner
文件：`src/gp_assistant/runtime/turn_loop.py`

当前虽然 import 了 `plan_evidence`，但没有实际使用。

## 2. 本轮重构目标

### 2.1 request 正式化
`request` 统一为：

- `chat`
- `recommend`
- `explain`
- `live_check`
- `compare`
- `exit`
- `run_change`

### 2.2 业务硬规则

- 非交易输入必须落到 `chat`
- parser 不允许 silent default 到 `recommend`
- engine 不允许 fallback 到 `make_recommendation`
- `chat` 不加载交易证据
- `chat` 不发布 run
- `chat` 不更新 active_run_id / previous_run_id / focus_subject / compare_set

### 2.3 不做兼容

直接删除：
- parser 的 recommend 默认值
- engine 的 recommend fallback
- 任何未显式声明 request 的默认推荐路径

## 3. PR 拆分

### PR-1: Intent Contract

#### 修改文件
- `src/gp_assistant/contracts/objects.py`
- `src/gp_assistant/contracts/api.py`
- 新增 `src/gp_assistant/contracts/intents.py`

#### 任务

1. 新增强类型枚举或 `Literal`：
   - `RequestType`
   - `SubjectType`
   - `FreshnessType`

2. `TurnFrame` 从松散字符串改为受控类型：

```python
class TurnFrame(GPModel):
    frame_id: str
    raw_message: str
    subject: SubjectType
    request: RequestType
    freshness: FreshnessType
    references: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    ambiguity: Dict[str, Any] = Field(default_factory=dict)
```

3. `ChatResponse` 正式声明 `message` 字段，去掉靠 `extra="allow"` 偷带：

```python
class ChatResponse(BaseModel):
    session_id: str
    reply: str
    message: Dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    right_panel: Dict[str, Any] = Field(default_factory=dict)
    ui_items: List[Dict[str, Any]] = Field(default_factory=list)
    planner_trace: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
```

#### 删除
- `ChatResponse.model_config = ConfigDict(extra="allow")`

---

### PR-2: Parser Service Formalization

#### 修改文件
- `src/gp_assistant/runtime/concern_parser.py`
- `src/gp_assistant/llm/interpret.py`
- `src/gp_assistant/runtime/context_engine.py`

#### 任务

1. `llm/interpret.py` 的 SYSTEM prompt 增加正式 request：`chat`

2. 改 prompt 逻辑为两层：
   - 先判断是否属于交易请求
   - 若不是交易请求，直接输出 `request="chat"`
   - 若是交易请求，再细分成其他 6 类

3. 明确 chat 语义：
   - 打招呼
   - 寒暄
   - 简短应答
   - 无明确推荐/研究/比较/卖出意图

4. 删除以下业务默认值：

```python
obj.setdefault('subject', 'run')
obj.setdefault('request', 'recommend')
obj.setdefault('freshness', 'current_book')
```

5. 替换成严格校验：
   - 允许补技术性默认：`references={}`、`constraints={}`、`ambiguity={...}`
   - 不允许补会改变业务走向的默认 request/subject

6. 在 `concern_parser.py` 中把 parser 变成正式 facade：

```python
def parse_concern(memory_ctx, book, user_message) -> TurnFrame:
    context = build_context(memory_ctx, book)
    frame = parse_turn_frame(context, user_message)
    return normalize_turn_frame(frame)
```

7. 新增 `normalize_turn_frame()` 或 `validate_turn_frame()`：
   - 保证 request/subject/freshness 合法
   - 规范 references 结构
   - 不做 recommend fallback

8. `context_engine.py` 保留现结构，但加一个只读字段帮助 parser：
   - `session_has_active_run: bool`
   - `session_focus_symbol: Optional[str]`

#### 删除
- parser 内任何 silent request fallback
- parser 内任何“解析不稳就 recommend”逻辑

---

### PR-3: Dispatcher + Evidence Planning

#### 修改文件
- `src/gp_assistant/judgment/engine.py`
- `src/gp_assistant/judgment/chat.py`（新增）
- `src/gp_assistant/runtime/evidence_planner.py`
- `src/gp_assistant/runtime/turn_loop.py`

#### 任务

1. 新增 `judgment/chat.py`

```python
from __future__ import annotations

from ..contracts.objects import Judgment


def judge_chat() -> Judgment:
    return Judgment(
        kind='chat',
        summary='non_trading_chat',
        evidence_refs=[],
    )
```

2. `judgment/engine.py` 改成 total dispatcher：

```python
from .chat import judge_chat
from .recommend import make_recommendation
from .followup import judge_followup
from .compare import compare_entries
from .exit import judge_exit


def make_judgment(session_id: str, frame: TurnFrame, evidence: EvidencePack) -> Judgment:
    topk = int(frame.constraints.get('topk') or 3)

    if frame.request == 'chat':
        return judge_chat()

    if frame.request == 'recommend':
        return make_recommendation(session_id=session_id, book=evidence.book, topk=topk)

    if frame.request == 'compare':
        entries = evidence.compare_entries or ([evidence.subject_entry] if evidence.subject_entry else [])
        return compare_entries(session_id=session_id, entries=entries)

    if frame.request == 'exit' and evidence.subject_entry is not None:
        return judge_exit(evidence.subject_entry, evidence.portfolio_slice)

    if frame.request in ('explain', 'live_check', 'run_change') and evidence.subject_entry is not None:
        return judge_followup(session_id=session_id, entry=evidence.subject_entry)

    raise ValueError(f"Unhandled request or missing evidence: request={frame.request}")
```

3. 删除 engine 末尾这句：

```python
return make_recommendation(...)
```

4. `runtime/evidence_planner.py` 增加 `chat`：

```python
if frame.request == 'chat':
    return {
        'need_active_run': False,
        'need_previous_run': False,
        'need_subject_entry': False,
        'need_compare_entries': False,
        'need_validation': False,
        'need_portfolio': False,
        'publish_run': False,
    }
```

并且把其他 request 的计划显式写全。

5. `runtime/turn_loop.py` 真接入 `plan_evidence(frame)`：
   - `build_evidence_pack()` 增加 `plan` 参数
   - 按 `plan` 决定是否加载 active_run / previous_run / subject_entry / compare_entries / portfolio / validation

建议签名改为：

```python
def build_evidence_pack(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook, plan: Dict[str, Any]) -> EvidencePack:
```

6. `turn_loop.run_turn_sync()` 改成：

```python
frame = parse_concern(memory_ctx, book, user_message)
plan = plan_evidence(frame)
evidence = build_evidence_pack(frame, memory_ctx, book, plan)
judgment = make_judgment(session_id=session_id, frame=frame, evidence=evidence)
```

#### 删除
- `turn_loop.py` 中无计划加载的全量 evidence 方式
- engine 中任何默认 recommend 路径

---

### PR-4: Narrator + Memory + Response Contract

#### 修改文件
- `src/gp_assistant/runtime/narrator.py`
- `src/gp_assistant/memory/service.py`
- `src/gp_assistant/llm/narrate.py`

#### 任务

1. `runtime/narrator.py` 给 `kind == 'chat'` 单独 message contract：

```python
if kind == 'chat':
    return {
        'message_kind': 'chat',
        'narrative_text': narrative_text,
        'followup_suggestions': [
            '今天给我 3 只',
            '为什么今天空仓',
            '看 600519 卖出判断',
        ],
    }
```

2. `llm/narrate.py` 的 SYSTEM prompt 增加约束：
   - `judgment.kind == chat` 时，不要输出交易结论
   - 只做轻量引导

3. `memory/service.py` 中 `commit_turn()` 增加严格状态规则：

```python
if judgment.kind == 'chat':
    pass
elif judgment.run is not None:
    ...
elif judgment.subject_entry is not None:
    ...
```

4. `chat` 回复不能更新：
   - `active_run_id`
   - `previous_run_id`
   - `focus_subject`
   - `compare_set`

5. `runtime/narrator.py` 中 `right_panel['top3']` 建议调整优先级：
   - 有 `judgment.run` 时用 `judgment.run.picks[:3]`
   - 否则有 `evidence.active_run` 时用 `active_run.picks[:3]`
   - 最后才回退到 `book.board[:3]`

虽然这不是 chat 改造的唯一核心，但这一步能减少主链展示分裂。

---

### PR-5: Tests（必须）

#### 新增目录
- `tests/unit/`
- `tests/integration/`

#### 新增测试文件
- `tests/unit/test_interpret_request_types.py`
- `tests/unit/test_judgment_dispatch.py`
- `tests/integration/test_chat_does_not_publish_run.py`

#### 单元测试用例

##### parser
- `你好` -> `chat`
- `hi` -> `chat`
- `在吗` -> `chat`
- `谢谢` -> `chat`
- `今天给我3只` -> `recommend`
- `为什么今天空仓` -> `explain`
- `第二只为什么不是第一只` -> `compare` 或 `explain`（按你最终定义固定）
- `600519现在该不该卖` -> `exit`
- `为什么这次和上次不一样` -> `run_change`

##### judgment dispatcher
- `request='chat'` -> `Judgment.kind == 'chat'`
- `request='chat'` 时绝不能调用 `make_recommendation`
- 未覆盖 request 必须抛错，不允许隐式 recommend

##### integration
- `chat` 不生成 run_id
- `chat` 后 session.active_run_id 不变化
- `chat` 后 session.focus_subject 不变化
- `recommend` 才生成 run_id

#### 测试要求

1. parser 测试必须 mock LLM 返回，不依赖线上模型
2. judgment 测试直接构造 `TurnFrame` / `EvidencePack`
3. integration 测试允许用临时 `GP_STORE_DIR`

## 4. 删除清单

这轮必须直接删：

1. `src/gp_assistant/llm/interpret.py`
   - `obj.setdefault('subject', 'run')`
   - `obj.setdefault('request', 'recommend')`
   - `obj.setdefault('freshness', 'current_book')`

2. `src/gp_assistant/judgment/engine.py`
   - `return make_recommendation(...)` 这个 fallback

3. 任何 parser / engine / turn_loop 中：
   - 未识别 request -> recommend
   - 未锚定 subject -> recommend

## 5. 验收标准

### 验收 1
输入：`你好`

必须满足：
- `frame.request == 'chat'`
- `judgment.kind == 'chat'`
- 不调用推荐链
- 不生成 run_id
- 不更新 active_run_id

### 验收 2
输入：`今天给我3只`

必须满足：
- `frame.request == 'recommend'`
- 生成 run
- 正常输出推荐 message

### 验收 3
输入：`600519现在该不该卖`

必须满足：
- `frame.request == 'exit'`
- 不重新推荐

### 验收 4
代码中不得再存在任何默认 recommend 路径。

## 6. Codex 执行顺序

1. 先做 PR-1：contract
2. 再做 PR-2：parser
3. 再做 PR-3：dispatcher + evidence
4. 再做 PR-4：narrator + memory
5. 最后做 PR-5：tests
6. 每个 PR 完成后都运行对应测试

## 7. Codex 执行要求

- 不新建第二条主链
- 不保留兼容逻辑
- 不做 fallback recommend
- 不允许 stringly-typed 魔法分支继续扩散
- 改动以现有文件原地重构为主
- 提交前必须保证测试可跑
