# gp_assistant 对话助手（保留说明）

本仓库保留 `gp_assistant` 作为可选服务（docker-compose 仍可运行），但主文档已迁移为“短线回测实验系统”。

快速启动（Docker）：
- 构建并启动：`docker compose up -d --build`
- 仅后端：`docker compose up -d gp`

主要端口：
- Web 前端：http://localhost:8080
- 后端健康检查：`curl http://127.0.0.1:8000/api/health`
- 推荐接口：`POST http://127.0.0.1:8000/api/recommend`

受控动作（REPL 内）：
- 仅允许 `python gpbt.py` 的白名单子命令（见 `configs/assistant.yaml`）
- 禁止任意 shell 执行

会话回放：日志落盘到 `store/assistant/sessions/session_*.jsonl`，对疑似密钥脱敏。

