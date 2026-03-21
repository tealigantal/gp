## gp · 简洁版 AI 选股系统（Chat 入口 + gated V2）

本项目提供一个面向 A 股的简洁 AI 选股系统。以 Chat 为入口，orchestrator 调用推荐引擎，统一至 gated PickArtifactV2，写入会话上下文（run_id/active_symbols）。

### 快速开始（本地）
- 依赖：Python 3.11+（推荐 3.12），Node.js 18+（前端）
- 安装后端依赖：
  1) `python -m venv .venv && ./.venv/Scripts/activate`（Linux/macOS: `source .venv/bin/activate`）
  2) `pip install -r requirements.txt`
- 启动后端（FastAPI）：
  - `python -m uvicorn gp_assistant.server.app:app --host 0.0.0.0 --port 8000`
  - 健康检查：`curl http://localhost:8000/api/health`
- 启动前端（可选）：
  - `cd frontend && npm ci && npm run dev`
  - 浏览器访问：`http://localhost:5173`（默认进入 `/chat`）

### 使用 Docker（后端 + 前端）
- 可选创建 `.env`（供 docker compose 使用）。常用：`LLM_API_KEY`、`LLM_BASE_URL`、`GP_CORS_ORIGINS`、`DATA_PROVIDER`（默认 akshare）。
- 启动服务：
  - 后端：`docker compose up -d gp`
  - 前端（可选）：`docker compose up -d web`
  - 或一次性：`docker compose up -d`
- 访问与日志：
  - 后端健康检查：`http://localhost:8000/api/health`
  - Web 前端：`http://localhost:8080`（默认进入 `/chat`）
  - 查看日志：`docker compose logs -f gp --tail=200`、`docker compose logs -f web --tail=200`
- 数据与产出（已挂载到宿主机）：`./data ./results ./universe ./store ./cache ./configs`

说明：
- `LLM_BASE_URL` 默认指向 `https://api.deepseek.com/beta`（严格工具）。
- `LLM_API_KEY` 为上游 DeepSeek/OpenAI 兼容接口的 API Key（直接使用，不再经过本地代理）。

### Chat 主链路与关键节点（概览）
- Chat：`POST /api/chat { session_id?, message }`（支持 follow-up）
- 推荐卡：`GET /api/recommend_v2/gated?run_id=...`（gated PickArtifactV2）
- 历史卡：`GET /api/artifacts/recommendations/{artifact_id}`
- 对比/细节：`POST /api/compare`、`GET /api/pick`

### 端到端验收（后端）
- 最小验证示例：
  - `pytest -q tests/api/test_recommend_v2_endpoint.py tests/api/test_compare_and_pick_endpoints.py`

### 开发与约束
- 不再引入第 3 个服务；不再维护本地 LLM 代理。
- 不重复造轮子，不引入复杂外部依赖；严格工具模式保持开启。

