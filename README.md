## 项目简介

对话式策略荐股助手（DeepSeek + 真实数据全链路）。支持多轮会话、意图识别、触发荐股与结构化结果落盘；候选池/主线/环境/公告/事件全部来源真实数据；当数据缺失时只返回 `missing/error` 提示，不回退规则化或合成内容。

---

## 快速开始

1) 安装 Docker 与 Docker Compose（Docker Desktop 即可）。
2) 配置环境变量：
   - 复制模板并填写密钥：`cp .env.example .env`
   - `.env` 关键项：
     - `LLM_BASE_URL=https://api.deepseek.com/v1`
     - `LLM_API_KEY=你的真实密钥`
     - `CHAT_MODEL=deepseek-chat`
     - `DATA_PROVIDER=akshare`（强制使用 AkShare）
     - 已默认开启严格真实/主线约束等参数，见下文“参数说明”。
3) 构建并启动服务：
   - 构建镜像：`docker compose build`
   - 启动服务：`docker compose up -d`
   - 健康检查：`curl http://127.0.0.1:8000/health`

---

## 使用方式

- 交互聊天（REPL）：
  - `docker compose run --rm -it gp python -m gp_assistant chat`
  - 示例：
    - you> 给我推荐3只主板低吸
    - agent> （DeepSeek 生成的自然语言建议；若 LLM 未就绪，将提示 narrative_unavailable）
- HTTP 调用：
  - POST `/chat`：`{"message":"给我推荐3只主板低吸"}`
  - POST `/recommend`：`{"universe":"symbols","symbols":["600519","000333"],"topk":3}`（不传 symbols 则走全市场动态候选池）
- 结果落盘：
  - `store/recommend/<YYYY-MM-DD>.json`：包含 picks、trade_plan、stats、rel_strength、announcement_risk、event_risk、debug 等。

---

## 数据与引擎说明（真实链路）

- 候选池：AkShare 全市场快照 → 剔除 ST/*ST/退、新股≤60天、价格区间[2,500] → 按成交额取前 N（`GP_DYNAMIC_POOL_SIZE`） → 拉日线/指标/筹码 → 硬过滤（5日均额<阈值剔除）→ 观察/禁买标记。
- 主线约束：默认仅从 TopN 行业/概念（真实来源）中选股；快照含“行业”优先，否则使用概念榜 TopN 并取成分股交集。
- 市场环境：基于全市场快照的均值涨跌幅与上涨占比分层（A/B/C/D）。
- 市场统计：快照聚合成交额与涨跌停数量；盘口口径缺失项返回 None 并记录 missing。
- 公告：CNINFO 检索近30日公告列表并提取风险关键词；失败仅返回 `risk_level=None` 与 `error`。
- 未来事件：AkShare gbbq（分红派息/登记等）+ 限售解禁（未来15日窗口）；缺失用 `event_risk=None` + missing 标注。
- 打分：环境/主题/趋势/波动/筹码/统计/风险/相对强度（RS5/RS20），总分 0–100。
- 分散度：同一行业/主题最多 N 只（默认2）。

---

## 参数说明（.env）

- 必填 LLM：`LLM_BASE_URL`、`LLM_API_KEY`、`CHAT_MODEL`
- 数据源：`DATA_PROVIDER=akshare`（强制选择 AkShare，避免 Local 抢占）
- 严格真实：`STRICT_REAL_DATA=1`（禁用一切合成/降级）
- 候选与主线：
  - `GP_MIN_AVG_AMOUNT=5e8`（5日均额下限）
  - `GP_NEW_STOCK_DAYS=60`
  - `GP_PRICE_MIN=2`、`GP_PRICE_MAX=500`
  - `GP_DYNAMIC_POOL_SIZE=200`
  - `GP_RESTRICT_MAINLINE=1`、`GP_MAINLINE_TOP_N=2`、`GP_MAINLINE_MODE=auto`
  - `GP_MAX_PER_INDUSTRY=2`

---

## 诊断与排错

- 查看当前 Provider：
  - `docker compose exec gp python -c "from gp_assistant.providers.factory import provider_health; print(provider_health())"`
- 遇到 `[data_unavailable] spot snapshot not supported`：
  - 确认 `DATA_PROVIDER=akshare`；不要挂载带有 `data/bars/daily` 的本地数据目录（会触发 Local）。
- 遇到 `[narrative_unavailable]`：
  - 检查 DeepSeek 变量是否正确、网络是否可达。

---

## License

MIT License，详见 `LICENSE`。
