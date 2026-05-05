# GP

GP 是一个面向 **A 股主板短线（1-3 个交易日）** 的 chat-first Web 股票推荐 AI 助手。

产品主线只有一个单页 Workspace：

- 左侧是连续对话，用户直接用自然语言提问
- 右侧是同源 `DecisionSnapshot`
- 后端统一从同一个 active run / canonical artifact 输出推荐、盘中判断、空仓解释、单票详情、比较、卖出建议和榜单变化

它不是自动交易系统，也不接券商。系统只输出交易级决策建议，用户自行下单。

## 核心能力

- 今天给我 3 只：返回 Top N 推荐，或明确空仓
- 盘中判断：回答“现在还能买吗”“第二个还能冲吗”
- 收盘后 / 非交易时段：返回下一交易窗口计划，不会直接报“只读不可用”
- 单票详情：返回 `entry / stop / take / thesis / why_selected / execution_state`
- 比较与榜单变化：支持“第一只和第二只比呢”“之前那只怎么没了”
- 卖出建议：返回 `HOLD / REDUCE / SELL / WATCH`

## 当前运行结构

推荐的容器拓扑如下：

- `gp`：FastAPI API 服务
- `gp-worker`：常驻 worker，负责 daybook 初始化、盘中 slot 更新和 post-close 状态刷新
- `web`：前端单页 Workspace
- `gp-rebuild-daybook`：按需手工重建 daybook
- `gp-replay-today`：按需回放当天已收盘 slot
- `gp-postclose-archive`：按需执行收盘后归档

说明：

- `gp` 和 `gp-worker` 是常驻服务
- `gp-rebuild-daybook`、`gp-replay-today`、`gp-postclose-archive` 放在 Compose `ops` profile 下，按需手工运行
- 当前仓库没有引入额外 scheduler / cron / 队列系统

## 环境要求

### Docker 方式

- Docker Desktop / Docker Engine
- Docker Compose v2

### 本地开发方式

- Python 3.11+
- Node.js 18+

## 配置

先复制环境文件：

```powershell
Copy-Item .env.example .env
```

最重要的变量：

- `LLM_API_KEY`：必需。当前 `/api/chat` 的意图解析依赖 LLM；缺失时 API 会明确返回 503，而不是伪装成普通闲聊
- `LLM_BASE_URL`：必需。`.env.example` 使用 DeepSeek 兼容接口
- `CHAT_MODEL`：默认 `deepseek-chat`
- `DATA_PROVIDER`：默认 `akshare`
- `STRICT_REAL_DATA=1`：默认优先真实数据
- `TZ=Asia/Shanghai`

如果本机没有代理，记得把 `.env` 里的这些代理项清空或删除：

- `HTTP_PROXY`
- `HTTPS_PROXY`
- `ALL_PROXY`

## 最快启动方式

### 1. 启动 API、worker 和前端

```powershell
docker compose up -d gp gp-worker web
```

默认入口：

- Workspace: `http://127.0.0.1:8080`
- API: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/health`

### 2. 查看 worker 是否持续更新

```powershell
docker compose logs -f gp-worker
```

### 3. 打开 Workspace

进入 `http://127.0.0.1:8080` 后，直接在聊天区提问，例如：

- `今天给我 3 只`
- `第二个还能冲吗`
- `这只现在还能买吗`
- `002371 的止盈止损点`
- `为什么这次和上次不一样`
- `收盘了也给我三只`

## 手工运维工具

这些命令不会常驻运行，适合按需手工触发。

### 重建当日 daybook

```powershell
docker compose --profile ops run --rm gp-rebuild-daybook
```

用途：

- 重新生成当天 daybook
- 重建 preopen 初始 artifact

### 回放今天已收盘的 slot

```powershell
docker compose --profile ops run --rm gp-replay-today
```

用途：

- 把今天已经结束的 slot replay 到当前时点
- 当你怀疑 `current book` 落后时可手工纠正

### 执行收盘后归档

```powershell
docker compose --profile ops run --rm gp-postclose-archive
```

用途：

- 将当日收盘后的 current artifact 状态归档

## 数据和更新机制

GP 的数据链不是“每次请求都整仓重抓”，而是分层更新。

### 日线

- 默认优先真实数据 provider
- 先读本地 `store/cache`
- 本地没有、数据过时或长度不足时，再在线抓取
- 抓到后写回本地，后续优先复用

### 盘中数据

- `gp-worker` 按 slot 持续更新
- bars、benchmark、breadth snapshot 会进入当前 artifact / current book
- provider snapshot 缺失但 bars 足够时，会走派生逻辑，而不是直接整体 unavailable

### 推荐与盘中判断

- `daybook`：日线交易计划
- `slot artifact`：盘中执行态
- 聊天推荐、右侧 `DecisionSnapshot`、单票详情、盘中入场判断全部读取同一个 canonical run / artifact

### 非交易时段

- 不会返回“只读不可用”
- 会返回“下一交易窗口计划”
- 通常表现为 `WATCH` + `WAIT_NEXT_SESSION`

## 如何使用

### 典型用法

1. 先问 `今天给我 3 只`
2. 再追问 `第二个还能冲吗`
3. 再问 `这只止盈止损点`
4. 最后问 `为什么这次和上次不一样`

### 你会看到的主要卡片

- Recommendation：推荐列表，含 `entry / stop / take / thesis / why_selected`
- Live Entry Check：当前是否还能进
- No Trade：今天为什么空仓，以及恢复条件
- Pick Detail：单票细节
- Compare：排序差异、执行态、风险、分数
- Exit Decision：`HOLD / REDUCE / SELL / WATCH`
- Run Change：本轮与上一轮推荐变化

### 右侧状态面板怎么看

右侧 `DecisionSnapshot` 会显示：

- 当前 `run_id / artifact_id`
- `run_action`
- `market_phase`
- top symbols
- 数据质量 / provenance
- 运行与工具状态

其中“运行与工具”卡会显示：

- 当前数据 provider
- `book_freshness`
- `slot_status`
- 最新 slot 时间
- `gp-worker`
- 可手工运行的 `ops` 工具

## 健康检查与排查

### 看 API 是否正常

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 8
```

`/api/health` 除了 `status / trading_day / llm_ready / storage`，还会返回 `runtime`：

- `market_phase`
- `data_provider`
- `auto_update_service`
- `auto_update_expected`
- `worker_poll_interval_sec`
- `book_freshness`
- `book_updated_at`
- `artifact_id`
- `pulse_trade_day`
- `pulse_slot_at`
- `last_closed_5m`
- `slot_status`
- `publish_allowed`
- `services`

### 看当前 book

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/book/current | ConvertTo-Json -Depth 8
```

### 看当前推荐 run

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/run/<run_id> | ConvertTo-Json -Depth 8
```

### 如果怀疑数据没动

按这个顺序查：

1. `docker compose logs -f gp-worker`
2. `GET /api/health` 看 `runtime.book_freshness`
3. Workspace 右侧“运行与工具”卡
4. 必要时手工执行 `gp-replay-today` 或 `gp-rebuild-daybook`

## 本地开发

### 后端

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m gp_assistant serve --host 127.0.0.1 --port 8000
```

单次命令行对话：

```powershell
$env:PYTHONPATH = "src"
python -m gp_assistant chat "今天给我 3 只"
```

手工运行 worker：

```powershell
$env:PYTHONPATH = "src"
python -m gp_assistant pulse-loop
```

### 前端

```powershell
cd frontend
npm ci
npm run dev
```

本地前端默认地址：

- `http://127.0.0.1:5173`

## API 入口

主要接口如下：

- `POST /api/chat`
- `GET /api/health`
- `GET /api/book/current`
- `GET /api/book/slot/{artifact_id}`
- `GET /api/run/{run_id}`
- `GET /api/recommend_v2`
- `POST /api/compare`
- `GET /api/pick`
- `GET /api/validation/summary`
- `GET /api/workbench`
- `GET /api/session/{session_id}`
- `GET /api/sessions`
- `GET /api/side-results`

## 仓库结构

```text
src/gp_assistant/
  gateway/          FastAPI API 入口和路由
  runtime/          turn loop、上下文、canonical artifact
  memory/           session、transcript、focus 和记忆
  book/             daybook、board、slot artifact、repo
  judgment/         recommend / detail / compare / exit / run_change
  evidence/         行情、验证、组合、股票池服务
  kernel/           跨推荐、验证、组合、执行预览的服务门面
  selection_engine/ 底层选股与打分
  strategy/         策略与 score 逻辑

frontend/src/features/workspace/
  WorkspacePage.tsx       单页主入口
  useAdvisorWorkspace.ts  会话与数据请求
  components/             聊天卡片、Snapshot、Header 等
```

## 验证命令

### 后端

```powershell
python -m compileall -q src
pytest -q
```

### 前端

```powershell
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
```

## 已知限制

- 当前没有 cron / scheduler，`ops` 工具需要手工触发
- `/api/chat` 的意图解析依赖外部 LLM；LLM 不可用时会明确返回 503，LLM 返回非法 JSON 且修复失败时返回 502
- 默认依赖外部 LLM 和行情 provider；如果网络、代理或密钥异常，自然语言理解和实时数据会受影响
- 前端运行状态卡能显示“应由 `gp-worker` 自动更新”，但不是 Docker 进程级探针

## 相关文档

- [docs/README.md](./docs/README.md)
- [docs/PROGRESS.md](./docs/PROGRESS.md)
- [docs/ops_runbook.md](./docs/ops_runbook.md)
- [docs/data_freshness_policy.md](./docs/data_freshness_policy.md)
- [docs/service_contract.md](./docs/service_contract.md)

## 说明

- `store/`、`cache/`、`results/` 下的文件是运行产物，不是核心源码
- 历史 archive 文档中存在旧设计和个别编码损坏，它们只保留作追溯记录，不代表当前实现
