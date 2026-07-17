# GP

GP 是一个面向 **A 股主板短线（1–3 个交易日）** 的 Market-Memory 投资决策 Agent。

它基于真实日线数据、历史相似事件、概率校准、风险审查、用户状态和 thesis 生命周期，判断“当前这个决策是否合理”。它不是自动交易系统，也不接券商；系统只输出交易级决策建议，用户自行下单。

## 目录

- [产品与能力](#产品与能力)
- [决策架构](#决策架构)
- [运行与部署](#运行与部署)
- [使用 Workspace](#使用-workspace)
- [数据与运行机制](#数据与运行机制)
- [运维与排障](#运维与排障)
- [本地开发](#本地开发)
- [API 入口](#api-入口)
- [仓库结构](#仓库结构)
- [验证](#验证)
- [已知限制](#已知限制)
- [相关文档](#相关文档)

## 产品与能力

### Workspace

产品主线是单页 Workspace：左侧为连续对话，右侧为同源 `DecisionSnapshot`。后端从同一个 active run / canonical artifact 输出推荐、日线计划判断、空仓解释、单票详情、比较、持仓处理和榜单变化。

### 支持的问题

- 今天给我 3 只：返回 Top N 计划，或明确空仓 / 等待
- 为什么推荐：返回相似历史案例、相似度、概率、不确定性、风险和排序证据
- 为什么不推荐：返回被拒候选的风险、置信度、历史失败模式和机会成本
- A 和 B 哪个更好：按数学排序和风险证据比较，不让 LLM 凭偏好改排名
- 如果跌了怎么办：返回 stop / drawdown / failure mode / 执行条件
- 这个策略历史靠谱吗：返回 Market Memory 样本、校准质量和历史结果
- 用户状态决策：同一条链回答“能买吗”“我已经买了怎么办”“亏了怎么办”“赚了怎么办”
- 日线计划判断：回答“现在还能买吗”“第二个还能冲吗”
- 收盘后 / 非交易时段：返回日线计划，不会直接报“只读不可用”
- 单票详情：返回 `entry / stop / take / thesis / why_selected / execution_state`
- 比较与榜单变化：支持“第一只和第二只比呢”“之前那只怎么没了”
- 持仓处理：返回 `HOLD / ADD / REDUCE / EXIT / WAIT / NO_TRADE`

### 典型使用流程

1. 先问 `今天给我 3 只`
2. 再追问 `第二个还能冲吗`
3. 再问 `这只止盈止损点`
4. 最后问 `为什么这次和上次不一样`

### Workspace 主要卡片

- Recommendation：计划列表，含 `entry / stop / take / thesis / why_selected / decision_action`
- Live Entry Check：当前是否还能进
- No Trade：今天为什么空仓，以及恢复条件
- Pick Detail：单票细节
- Compare：排序差异、执行态、风险、概率和历史相似证据
- Exit Decision：`HOLD / ADD / REDUCE / EXIT / WAIT / NO_TRADE`
- Run Change：本轮与上一轮推荐变化

### 右侧状态面板

`DecisionSnapshot` 会显示当前 `run_id / artifact_id`、`run_action`、`market_phase`、top symbols、数据质量 / provenance，以及运行与工具状态。

“运行与工具”卡会显示当前数据 provider、`book_freshness`、`slot_status`、最新 slot 时间、`gp-worker` 和可手工运行的 `ops` 工具。

## 决策架构

### 生产决策路径

```text
Market Data
  -> Signal Engine
  -> Market Memory
  -> Probability Engine
  -> Risk Engine
  -> Ranking
  -> Decision Intelligence
  -> Thesis Lifecycle
  -> Decision Synthesizer
  -> Validator
  -> DecisionContextSnapshot
  -> Response
```

### 模块边界

- `signal_engine/`：只识别市场结构，不直接决定买入
- `market_memory/`：用归一化 feature vector 距离检索历史相似事件，不允许退化成 `signal_type` 标签查询
- `probability_engine/`：用相似案例加权统计和 Bayesian shrinkage 输出概率，并输出 evidence block
- `risk_engine/` 和 ranking：负责数学排序、风险调整和执行质量
- `decision_engine/`：构建 `DecisionContextModel`，统一包含 market / security / signal-thesis / user / position / objective / constraints
- Thesis Lifecycle：判断 `thesis_strengthened / thesis_unchanged / thesis_weakening / thesis_invalidated`
- Decision Synthesizer：输出 `HOLD / ADD / REDUCE / EXIT / WAIT / NO_TRADE`，不能编造价格、概率、样本或历史事实
- `DecisionContextSnapshot`：保存每次决策的上下文、动作、校验结果和最终解释，供未来复盘

## 运行与部署

### 服务拓扑

- `gp`：FastAPI API 服务
- `gp-worker`：常驻 worker，负责统一运行链（日线 freshness、daybook、盘中分钟线、current artifact）刷新
- `web`：前端单页 Workspace
- `gp-rebuild-daybook`：按需手工重建 daybook
- `gp-postclose-archive`：按需执行收盘后归档
- `gp-serenity-worker`：可选实验 worker，只读取当前 Top10、reserve 与持仓，采集免费官方公告并做前向影子验证
- `gp-serenity-bootstrap`：一次性真实 30 日公告 bootstrap，与常驻实验 worker 使用不同 Compose profile

`gp` 和 `gp-worker` 是常驻服务；`gp-rebuild-daybook` 与 `gp-postclose-archive` 位于 Compose 的 `ops` profile 下，按需手工运行。当前仓库没有额外 scheduler / cron / 队列系统。

Serenity 默认配置为 `auto`，但初始状态固定为 `warming/shadow + 0%`；没有完成真实 bootstrap 与前向门槛时，不会改变正式排序。

### 环境要求

| 方式 | 要求 |
| --- | --- |
| Docker | Docker Desktop / Docker Engine、Docker Compose v2 |
| 本地开发 | Python 3.11+、Node.js 18+ |

### 配置

先复制环境文件：

```powershell
Copy-Item .env.example .env
```

最重要的变量：

- `LLM_API_KEY`：必需。当前 `/api/chat` 的意图解析依赖 LLM；缺失时 API 会明确返回 503，而不是伪装成普通闲聊
- `LLM_BASE_URL`：必需。`.env.example` 使用 DeepSeek Beta 接口
- `CHAT_MODEL`：默认 `deepseek-chat`
- `DATA_PROVIDER`：默认 `akshare`
- `STRICT_REAL_DATA=1`：默认优先真实数据
- `TZ=Asia/Shanghai`
- `GP_SERENITY_MODE=auto`：`off / reference / auto`；只有 `auto` 且状态已自动晋升至 probation/active 时才允许非零权重
- `GP_SERENITY_MAX_WEIGHT=0.08`：独立 add-on 的硬上限，不进入原八专家权重

如果本机没有代理，请清空或删除 `.env` 中的 `HTTP_PROXY`、`HTTPS_PROXY` 和 `ALL_PROXY`。

### 最快启动

启动 API、worker 和前端：

```powershell
docker compose up -d gp gp-worker web
```

默认入口：

- Workspace：`http://127.0.0.1:8080`
- API：`http://127.0.0.1:8000`
- Health：`http://127.0.0.1:8000/api/health`

查看 worker 是否持续更新：

```powershell
docker compose logs -f gp-worker
```

## 使用 Workspace

打开 `http://127.0.0.1:8080` 后，直接在聊天区提问，例如：

- `今天给我 3 只`
- `第二个还能冲吗`
- `这只现在还能买吗`
- `002371 的止盈止损点`
- `为什么这次和上次不一样`
- `收盘了也给我三只`

## 数据与运行机制

### 数据更新

GP 的数据链不是“每次请求都整仓重抓”，而是分层更新：

| 数据类型 | 更新方式 |
| --- | --- |
| 日线 | 默认优先真实数据 provider；先读本地 `store/cache`，本地没有、数据过时或长度不足时再在线抓取；抓取后写回本地复用。 |
| 盘中数据 | `gp-worker` 按 slot 持续更新；bars、benchmark、breadth snapshot 进入当前 artifact / current book。provider snapshot 缺失但 bars 足够时，走派生逻辑。 |
| 决策与盘中判断 | `Market Memory Agent` 处理日线候选、相似历史、概率、风险和数学排序；Decision Intelligence 合成决策上下文；Thesis Lifecycle 判断 thesis 状态；`DecisionContextSnapshot` 记录决策；`daybook` 保存日线计划与 Workspace 当前状态。 |

聊天推荐、右侧 `DecisionSnapshot`、单票详情、盘中入场判断和持仓处理，全部读取同一个 canonical run / artifact 及 Decision Intelligence 输出。

### Serenity Alpha 实验

先运行一次真实 bootstrap；fixture 或普通两日轮询不能令实验 ready：

```powershell
docker compose --profile serenity-bootstrap run --rm gp-serenity-bootstrap
```

确认 bootstrap 成功后，再启动常驻 worker：

```powershell
docker compose --profile experiments up -d gp-serenity-worker
docker compose logs -f gp-serenity-worker
```

查看状态：

```powershell
docker compose exec -T gp python -m gp_assistant.cli serenity-status
```

`shadow` 时官方事实、非绑定参考分数和反事实排名可用于解释，但正式 `adaptive_score`、候选、动作和交易参数不变。只有双源核验、未过期、非 backfill 的前向事实才进入自动学习；缺失、陈旧、源故障或无相关公告的贡献严格为零。

### Slot 与日线状态

运行态状态由 `runtime.slot_state` 统一归一化，不再由 gateway、worker 和前端分别解释。

- `market_phase`：交易时钟，例如 `PREOPEN / INTRADAY_AM / LUNCH_BREAK / CLOSING_AUCTION / POSTCLOSE_PENDING / NON_TRADING`
- `daily_data_state`：日线状态，取值为 `previous_completed / eod_pending / daily_reconciling / freshness_blocked / ready / unavailable`
- `artifact_stage`：当前 artifact 类型，取值为 `daily_plan / intraday_pulse / none / unknown`
- `artifact_freshness`：artifact 是否跟上日线状态，取值为 `current / lagging / unavailable / blocked`
- `tradeability_state`：是否可交易，取值为 `tradeable / no_trade / blocked`，不再和 freshness 混在一起
- `artifact_status`：`artifact_freshness` 的兼容别名，不再使用 clock 的 `close_pending`

收盘后时钟仍是 `POSTCLOSE_PENDING`，日线是否就绪以 `daily_data_state` 为准。完整就绪状态如下：

```text
market_phase=POSTCLOSE_PENDING
daily_data_state=ready
artifact_stage=daily_plan
artifact_freshness=current
artifact_status=current
book_freshness=postclose_ready
```

`publish_allowed=false` 只表示当前决策为 no-trade，不代表日线没有拉取完成。`slot artifact` 表示盘中执行态。

### 非交易时段

系统不会返回“只读不可用”，而会返回“下一交易窗口计划”，通常表现为 `WATCH` + `WAIT_NEXT_SESSION`。

## 运维与排障

### 手工运维工具

这些命令不会常驻运行，适合按需手工触发。

#### 重建当日 daybook

```powershell
docker compose --profile ops run --rm gp-rebuild-daybook
```

用于重新生成当天 daybook，并重建 preopen 初始 artifact。

#### 执行收盘后归档

```powershell
docker compose --profile ops run --rm gp-postclose-archive
```

用于运维诊断或强制补跑收盘后日线链路。正常情况下，`gp-worker` 会自动完成收盘后日线确认和 daily artifact 发布，无需手工触发。

### 健康检查

查看 API 状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 8
```

`/api/health` 除 `status / trading_day / llm_ready / storage` 外，还会返回 `runtime`：

- `market_phase`、`data_provider`、`auto_update_service`、`auto_update_expected`
- `worker_poll_interval_sec`、`daily_data_state`、`clock_data_status`、`book_freshness`
- `artifact_stage`、`artifact_freshness`、`artifact_status`、`tradeability_state`
- `book_updated_at`、`artifact_id`、`pulse_trade_day`、`pulse_slot_at`、`last_closed_5m`
- `slot_status`、`publish_allowed`、`services`

查看当前 book：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/book/current | ConvertTo-Json -Depth 8
```

查看当前推荐 run：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/run/<run_id> | ConvertTo-Json -Depth 8
```

### 数据未更新时

按以下顺序检查：

1. `docker compose logs -f gp-worker`
2. `GET /api/health` 中的 `runtime.daily_data_state / artifact_stage / artifact_freshness / book_freshness`
3. Workspace 右侧“运行与工具”卡
4. 本地运行只读诊断：

   ```powershell
   $env:PYTHONPATH = "src"
   python -m gp_assistant.cli diagnose-slot-state --trade-day 2026-07-09
   ```

5. 仅在 `artifact_freshness=lagging`、`daily_data_state=freshness_blocked` 或 repair 明确 `blocked/failed` 时，再考虑执行 `gp-rebuild-daybook` 或 `gp-postclose-archive`

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
python -m gp_assistant runtime-loop
```

### 前端

```powershell
cd frontend
npm ci
npm run dev
```

本地前端默认地址：`http://127.0.0.1:5173`。

## API 入口

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
  gateway/            FastAPI API 入口和路由
  runtime/            turn loop、上下文、canonical artifact
  memory/             session、transcript、focus 和记忆
  book/               daybook、board、slot artifact、repo
  judgment/           recommend / detail / compare / exit / run_change
  evidence/           行情、验证、组合、股票池服务
  kernel/             跨推荐、验证、组合、执行预览的服务门面
  signal_engine/      日线结构信号与 feature fingerprint
  market_memory/      相似历史事件、决策快照、预测结果存储
  probability_engine/ 相似案例统计、Bayesian shrinkage、evidence block
  risk_engine/        执行风险、回撤风险、数学 ranking
  decision_engine/    Decision Context、Thesis Lifecycle、Decision Synthesizer、validator
  evaluation_engine/  historical replay、AB validation、calibration、counterfactual
  selection_engine/   旧系统参考和低层行情工具；不再是生产推荐排序权威

frontend/src/features/workspace/
  WorkspacePage.tsx       单页主入口
  useAdvisorWorkspace.ts  会话与数据请求
  components/             聊天卡片、Snapshot、Header 等
```

## 验证

### 后端

```powershell
python -m compileall -q src tests
pytest -q
```

### Historical Replay / AB Validation

```powershell
$env:GP_MARKET_MEMORY_DIR = "$env:TEMP\gp_market_memory_replay_events"
$env:PYTHONPATH = "src"
python -m gp_assistant.evaluation_engine.historical_replay `
  --days 20260105 20260106 20260107 20260108 20260109 20260112 20260113 20260114 20260115 20260116 20260119 20260120 20260121 20260122 20260123 20260127 `
  --topk 3 `
  --max-symbols 12 `
  --output-name historical_replay_ab_202601_top3
```

本地最新结果见 [docs/historical_validation.md](./docs/historical_validation.md)。

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
- `/api/chat` 的意图解析依赖外部 LLM；LLM 不可用时明确返回 503，LLM 返回无效 TurnFrame 且修复失败时返回 502
- 默认依赖外部 LLM 和行情 provider；网络、代理或密钥异常会影响自然语言理解和实时数据
- 前端运行状态卡能显示“应由 `gp-worker` 自动更新”，但不是 Docker 进程级探针
- 当前概率系统已有 evidence block 和 calibration 评估，但 2026-01 本地 replay 显示概率偏乐观，不能把概率当黑盒分数使用
- 旧 `selection_engine` 仍保留作迁移参考和低层数据工具；生产决策和推荐排序不再依赖旧 `candidate_score` / champion / `final_score`

## 相关文档

- [文档索引](./docs/README.md)
- [项目进度](./docs/PROGRESS.md)
- [运维手册](./docs/ops_runbook.md)
- [数据新鲜度策略](./docs/data_freshness_policy.md)
- [服务契约](./docs/service_contract.md)
- [历史验证结果](./docs/historical_validation.md)

## 说明

- `store/`、`cache/`、`results/` 下的文件是运行产物，不是核心源码
- 历史 archive 文档中存在旧设计和个别编码损坏；它们只保留作追溯记录，不代表当前实现
