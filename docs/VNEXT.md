# vNext 说明（Docker + Proxy + Assistant + 新口径）

- Docker 一键启动：
  - `cp .env.example .env`（填 KEY 或使用代理）
  - `docker compose up --build`
  - 容器内运行：`python assistant.py chat` 或 `python gpbt.py backtest ...`
- LLM Proxy：可选服务 `services/llm_proxy`，OpenAI 兼容 `/v1/chat/completions`，上游 KEY 存于服务器端。

## compare_strategies.csv（vNext）
必含列：
- `strategy,n_trades,win_rate,total_return_net,max_drawdown_net,turnover,no_fill_buy,no_fill_sell,forced_flat_count,status`

## 运行产物（每个 `results/run_*`）
- `manifest.json`：包含 `git_commit`、`configs_hash`、`engine_policy`、`cost_model`、`asof_policy`、`data_coverage_summary`
- `events.jsonl`：逐事件（signal/order/fill/skip/force_flat）记录（最小可用：当前为 fill/force_flat）

## Assistant 命令
- `/help` `/runs` `/run <id>` `/doctor <id>` `/open <path>` `/exec gpbt|gp ...`
- 会话脱敏：日志中会对 `sk-...` 等形式自动遮罩。

