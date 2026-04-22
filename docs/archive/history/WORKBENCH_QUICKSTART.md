# Workbench 快速上手（Docker，一条主线 + 可操作）

唯一主线：

artifact_v2 (canonical source)
→ /api/recommend_v2/gated（正式推荐视图）
→ order intent
→ paper/shadow execution
→ portfolio state
→ /api/workbench（唯一 operator 视图）

## 一、启动（Docker Compose）

```bash
docker compose up -d
```

服务启动后：
http://localhost:8080
- 前端（Workbench）：http://localhost:8080/workbench
- 后端健康检查：http://localhost:8000/api/health
- 正式推荐视图（JSON）：http://localhost:8000/api/recommend_v2/gated
- Operator 聚合视图（JSON）：http://localhost:8000/api/workbench

查看日志（可选）：

```bash
docker compose logs -f gp --tail=200    # 后端
docker compose logs -f web               # 前端
```

## 二、在 /workbench 如何操作（最小人工操作闭环）

打开 http://localhost:8080/workbench，页面包含：

- **Recommendations**：每条有 symbol、状态（Allow/Degraded/Blocked）、1–2 条原因、score/confidence/reliability、actionable 标记。
- **Intent Review（预览）**：从推荐派生的意图（不写盘），可对单条执行 **Admit/Reject**。
  - Admit：将意图写入组合 pending_intents，并生成 admitted 事件；页面自动刷新后可在 Portfolio/Pending 与 Recent Events 中看到变化。
  - Reject：仅记录 rejected 事件，不进入 pending。
  - Pending 列表支持 **Cancel**（移出 pending，并记录 cancelled 事件）。
- **Portfolio Summary**：positions/pending/events 摘要与 Pending 列表。
- **Recent Execution Events**：按时间列出 event_type、symbol、timestamp。
- **Validation/Health**：healthy/degraded/killed 数、walkforward 缺失数、live shadow 状态。

> 提示：如推荐/summary 初始为空，系统会优雅降级。你也可以在容器里手动刷新一次验证汇总：

```bash
docker compose exec gp python scripts/run_validation_refresh.py
```

## 三、注意事项

- Workbench 面向操作员，目标是「看懂 + 可操作 + 可回放」。
- 不要直接读存储目录；不要在前端拼业务逻辑。
- 正式推荐视图以 `/api/recommend_v2/gated` 为准；operator 聚合视图以 `/api/workbench` 为准。

