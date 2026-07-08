运行态产物目录（不纳入源码版本）。

当前生产推荐由 Market-Memory Agent 生成。`store/recommend/` 中的 JSON 是前端/API 可见的发布产物或兼容样例，不是推荐排序权威；解释“为什么推荐/为什么不推荐”时应读取对应 `DecisionContextSnapshot`，其中包含 market context、候选、被拒候选、历史相似案例、概率 evidence、风险、ranking、LLM risk committee 决策和最终叙述。

- 后端服务在 preopen/intraday/close/publish 阶段写入本目录：
  - latest.json：当前对前端/接口可见的最新推荐（契约样式）
  - YYYYMMDD.json：按交易日分片的历史产物（可重建）
- Market Memory 运行数据默认在 `store/events/`，其中数据库和 snapshot 文件属于运行产物，不应入库。
- 调试附加：*_debug.json / *_sources.json 为一次性诊断输出，不应入库。

仓库策略：
- `.gitignore` / `.dockerignore` 默认忽略本目录所有文件，仅放行 `latest.json` 与一个最小样例（当前为 2026-03-11.json）。
- 历史请以运行态持久化或外部备份方式保存；如需清理，参见 `python -m scripts.retention`。

