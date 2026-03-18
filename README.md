## gp — 简洁版 AI 选股系统（Chat 入口 + gated V2）

本项目提供一个面向 A 股的简洁 AI 选股系统。以 Chat 为入口，由 orchestrator 调用推荐引擎，统一到 gated PickArtifactV2，写入会话上下文（run_id/active_symbols）。流程推荐单采用同一信源，后续追问（第二名/为什么推荐它/为什么空仓/重新计算）绑定同一 run_id 运行环境。

### 快速开始（本地）
- 依赖：Python 3.11+（推荐 3.12），Node.js 18+（前端）
- 安装后端依赖：
  1) `python -m venv .venv && source .venv/bin/activate`（Windows: `.venv\Scripts\activate`）
  2) `pip install -r requirements.txt`
- 启动后端（FastAPI）：
  - `python -m uvicorn gp_assistant.server.app:app --host 0.0.0.0 --port 8000`
  - 健康检查：`curl http://localhost:8000/api/health`
- 启动前端（可选）：
  - `cd frontend && npm ci && npm run dev`
- 浏览器访问：`http://localhost:5173`（默认进入 `/chat`）

### 使用 Docker（后端 + 前端 + LLM 代理）
- 可选创建 `.env`（供 docker-compose 使用的环境变量）：
  - 常用：`LLM_API_KEY`、`LLM_BASE_URL`（或 `UPSTREAM_BASE_URL`/`UPSTREAM_API_KEY` 供 llm-proxy）、`GP_CORS_ORIGINS`、`DATA_PROVIDER`（默认 akshare）
- 启动服务：
  - 后端与 LLM 代理：`docker compose up -d gp llm-proxy`
  - 前端（可选）：`docker compose up -d web`
- 访问：
  - 后端健康检查：`http://localhost:8000/api/health`
  - Web 前端：`http://localhost:8080`（默认进入 `/chat`）
- 查看日志：
  - 后端：`docker compose logs -f gp --tail=200`
  - 前端：`docker compose logs -f web --tail=200`
- 数据与产出（已挂载到宿主机）：`./data ./results ./universe ./store ./cache ./configs`

### Chat 主链路与关键节点
- Chat：`POST /api/chat { session_id?, message }`
  - 支持 follow-up：第二名 / 为什么推荐它 / 为什么空仓 / 重新计算
- 推荐卡（只读）：`GET /api/recommend_v2/gated?run_id=...`（gated PickArtifactV2）
- 历史卡片：`GET /api/artifacts/recommendations/{artifact_id}`
  - 若提供 v2 `run_id`，则读取 gated v2 并做安全字段遮蔽（不泄露内部实现）
  - 比较与细节：
    - `POST /api/compare { run_id, symbols }`
    - `GET /api/pick?run_id=...&symbol=...`

### 推荐产出与 run_id
- 每次推荐生成唯一 run_id（贯穿 as_of），以 `{run_id}_v2.json` 持久化到 `store/recommend/`，并同步 `latest_v2.json`。
- 前端卡片统一读取 `artifact_version=v2` + `run_id`，展示决策链（tradeable/market_regime/run_gating/themes/strategy/thesis/entry_zone/stop/take_profit/RR/state/actionable/scores/risk_flags/invalidation/gating_decision）。
- 空仓（no-trade）不是错误：推荐卡会显示 run_gating / market_regime / 主要原因。

### 端到端验收（后端）
- 后端最小验证：
  - `pytest -q tests/api/test_recommend_v2_endpoint.py tests/api/test_compare_and_pick_endpoints.py tests/test_chat_agent_flow.py tests/test_chat_followup_run_context.py tests/test_chat_recommendation_e2e.py`
- 前端：
  - `cd frontend && npm run typecheck && npm run build && npm run test`

### 维护脚本
- v2 文件命名规则：`python scripts/report_legacy_v2_naming.py`
  - 输出 run_id 命名 vs 日期命名的数量与样例，协助迁移到 run_id 命名

### Workbench（可选）
- 面向 operator 的轻量界面，入口与快速入门见 `docs/WORKBENCH_QUICKSTART.md`

### 开发与约束
- 不再维护 `/api/recommend` V1 的兼容；前端不暴露 score/actionable/gating 的原始异常/调试信息
- 不重复造轮子，不引入复杂外部依赖，不做自动交易
- follow-up 上下文：会提示“请先生成推荐”，不做越权操作

