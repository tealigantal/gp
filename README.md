# gp assistant · 对话 LLM + 策略荐股 Agent（FastAPI）

gp assistant 是一个最小可用的“对话 + 策略荐股”后端：
- /chat：多轮对话入口，支持意图识别（推荐/追问/闲聊），未配置 LLM 时优雅降级。
- /recommend：直接返回结构化 JSON 的荐股结果，便于前端/系统接入。

特性
- 多轮会话：记录历史与最近一次推荐，支持“为什么/买卖点/止损”等追问。
- 策略引擎：主题池、市场环境分层、候选生成、指标/事件统计、打分与冠军选择。
- 数据源选择：本地 Parquet/官方/akshare 自动回退；可用离线夹带数据进行无网演示。
- 降级容错：LLM 未配置时不阻断对话；行情不足时用合成数据标注为“insufficient”。

目录结构（要点）
- src/gp_assistant/server：HTTP 服务入口（FastAPI）
- src/gp_assistant/chat：意图识别、编排、渲染、会话存储
- src/gp_assistant/recommend：荐股引擎与数据枢纽
- src/gp_assistant/strategy：指标/事件研究/CV/打分/策略库
- src/gp_assistant/providers：数据源适配与选择工厂
- data | results | store | cache | universe | configs：挂载与产出目录

快速开始（Docker）
1) 复制环境文件并填写必要变量
   cp .env.example .env
   - TZ=Asia/Shanghai（默认）
   - LLM_BASE_URL=https://api.deepseek.com/v1（或你的代理地址）
   - LLM_API_KEY=你的密钥（留空则 /chat 闲聊降级，不影响 /recommend）
   - CHAT_MODEL=deepseek-chat（或自定义）
   - DATA_PROVIDER=akshare | local | official（默认 akshare）
   - GP_REQUEST_TIMEOUT_SEC=60（建议，降低超时概率）

2) 构建并启动
```
docker compose up -d --build
```

3) 健康检查
```
curl -s http://127.0.0.1:8000/health | jq
```

4) 调用示例
- 对话（新会话）：
```
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好"}' | jq
```
- 同一会话触发推荐：
```
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"sess-001","message":"请推荐3只股票"}' | jq
```
- 直接拿结构化结果：
```
curl -s -X POST http://127.0.0.1:8000/recommend \
  -H 'Content-Type: application/json' \
  -d '{"universe":"symbols","symbols":["000001","000333","600519"],"topk":3}' | jq
```

本地运行（无需 Docker）
- Python 3.11+
- 安装依赖与包：
```
pip install -r requirements.txt
pip install -e .
```
- 启动服务：
```
uvicorn gp_assistant.server.app:app --host 0.0.0.0 --port 8000
```

API 约定
- GET /health
  - 返回：{status, llm_ready, data_provider, time}
- POST /chat
  - 请求：{session_id?, message}
  - 响应：{session_id, reply(文本), tool_trace{triggered_recommend, recommend_result?}}
  - 说明：意图为“推荐”时，内部调用同一引擎并将结构化结果渲染为文本；
          非推荐/追问走 LLM；未配置 LLM 时降级为回显提示。
- POST /recommend
  - 请求：{date?, topk?, universe?(auto|symbols), symbols?, risk_profile?}
  - 响应：结构化 JSON（env/themes/picks/execution_checklist/debug 等）；
          同步落盘至 store/recommend/{as_of}.json 与 _debug/_sources。

配置说明（环境变量）
- TZ：时区，默认 Asia/Shanghai
- LLM_BASE_URL / LLM_API_KEY / CHAT_MODEL：对话 LLM 配置
- GP_REQUEST_TIMEOUT_SEC：HTTP 请求超时（秒），建议 30–60
- DATA_PROVIDER：akshare | local | official（结合 providers/factory 自动回退）
- OFFICIAL_API_KEY：官方数据源凭证（选配）
- GP_PREFER_LOCAL=1：偏好本地数据（仅在 prefer=None/auto 时生效）

数据与产物
- 会话库：store/sessions/session.db（多轮对话历史与最近推荐）
- 推荐结果：store/recommend/{as_of}.json / *_debug.json / *_sources.json
- 缓存：store/cache/**（公告/市场等）

常见问题
- PowerShell 中文显示为乱码：接口是 UTF-8，建议用浏览器/Postman/curl 或调整控制台编码。
- 未配置 LLM：/chat 闲聊会降级，/recommend 不受影响。
- 无行情数据：将用合成序列补齐并在 meta 标注 insufficient，不用于真实交易。

架构索引（主要文件）
- 服务入口：src/gp_assistant/server/app.py
- 对话编排：src/gp_assistant/chat/orchestrator.py
- 荐股引擎：src/gp_assistant/recommend/agent.py
- 数据枢纽：src/gp_assistant/recommend/datahub.py
- 指标/统计：src/gp_assistant/strategy/*
- 数据源选择：src/gp_assistant/providers/factory.py
- 配置中心：src/gp_assistant/core/config.py

开发与测试
- 运行测试：
```
pytest -q
```
- 代码风格与类型：项目内以简洁为主，必要位置含类型标注；可按需使用编辑器格式化。

安全与合规
- 请勿将真实密钥写入仓库；将 .env 添加到 .gitignore（已默认）。
- 本项目仅用于研究与教育示例，不构成任何投资建议或收益承诺。市场有风险，决策需独立承担。

