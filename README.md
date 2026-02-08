# gp assistant — 前端对话LLM + 后端荐股Agent

两层架构：
- /chat = 多轮对话入口（必要时自动触发荐股，LLM 不可用也能降级回复）
- /recommend = 严格荐股流水线（结构化 JSON 输出，确定性渲染由前端使用）

启动（Docker Compose，一键运行）：

```
docker-compose up --build
```

服务启动后：

```
curl -s http://127.0.0.1:8000/health | jq

curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好"}' | jq

curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"sess-001","message":"给我推荐3只主板低吸"}' | jq

curl -s -X POST http://127.0.0.1:8000/recommend \
  -H 'Content-Type: application/json' \
  -d '{"universe":"symbols","symbols":["000001","000333","600519"],"topk":3}' | jq
```

环境变量（可选）：
- TZ=Asia/Shanghai（默认）
- LLM_BASE_URL、LLM_API_KEY、CHAT_MODEL（LLM 不可用时 /chat 自动降级）
- DATA_PROVIDER=akshare（或默认自动）

注意：当 env.grade == D 时系统输出空仓倾向，并在 recovery_conditions 给出恢复条件。

附：旧 CLI/路由已移至 `tools/legacy/`，默认不再支持或文档化，以免误导使用；统一通过 HTTP 服务对接前端。
