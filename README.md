## 项目概览
对话式 A 股策略与推荐助手（DeepSeek + 真实数据链路）。支持多轮会话、意图识别、荐股与结构化结果，强调“真实数据优先，不做合成降级”。

核心能力：
- 数据提供层：AkShare 多线路回退（TX→Sina→EastMoney），本地 Parquet（可选）。
- 市场环境：基于全市场快照的分层（A/B/C/D）与基础统计。
- 候选与主线：动态候选池、行业/概念主线约束、风险与分散度控制。
- 工具与接口：命令行工具、交互式聊天，FastAPI HTTP 服务。

---

## 快速开始
方式一：Docker（推荐）
- 构建镜像：`docker compose build --no-cache`
- 启动服务：`docker compose up -d`
- 健康检查：`curl http://127.0.0.1:8000/health`
- 如国内网络构建较慢，可在 `.env` 中设置 `PIP_INDEX_URL`（如清华/阿里镜像）。修改镜像源后建议使用 `docker compose build --no-cache` 确保生效。

方式二：本地运行
- 要求：Python 3.10+（推荐 3.11）
- 安装依赖：`pip install -r requirements.txt`
- 让源码包可导入（两选一）：
  - `pip install -e .`（基于 `pyproject.toml`）
  - 或设置 `PYTHONPATH` 指向 `src`（本仓含 `sitecustomize.py` 自动加入 `src`）

---

## 使用方式
交互聊天（REPL）
- 本地：`python -m gp_assistant chat`
- Docker：`docker compose run --rm -it gp python -m gp_assistant chat`
- 单次输出 JSON：`python -m gp_assistant chat --once "给我推荐3只低位放量"`

HTTP API（FastAPI）
- POST `/chat`：`{"message":"给我推荐3只主板低位"}`
- POST `/recommend`：`{"universe":"symbols","symbols":["600519","000333"],"topk":3}`
- GET `/health`：查看服务与 Provider 状态

工具/脚本（Windows PowerShell 示例）
- 在线日线（严格真实数据）
  - `$env:PYTHONPATH=(Join-Path (Get-Location) 'src')`
  - `$env:STRICT_REAL_DATA='1'`
  - `$env:AK_DAILY_PRIORITY='tx,sina,em'`
  - `python -c "from gp_assistant.tools.market_data import run_data; import json; r=run_data({'symbol':'600519','start':'2024-01-02','end':'2024-02-01'}, None); print(json.dumps({'ok':r.ok,'msg':r.message},ensure_ascii=False))"`

- 在线快照（用于 market_env）
  - `$env:AK_SPOT_PRIORITY='sina,em'`
  - `python -c "from gp_assistant.providers.factory import get_provider; p=get_provider('akshare'); df,meta=p.spot_snapshot(); print(len(df), meta.get('source'))"`

- 离线 fixtures 回退（仅 DataHub，保持原逻辑）
  - `$env:STRICT_REAL_DATA='0'`
  - `python -c "from gp_assistant.recommend.datahub import MarketDataHub; import json; hub=MarketDataHub(); df,meta=hub.daily_ohlcv('600519'); print(len(df)); print(json.dumps(meta,ensure_ascii=False))"`

---

## 数据与引擎（真实链路）
- 候选池：基于全市场快照，剔除 ST/*ST/退、新股≤`GP_NEW_STOCK_DAYS`、价格区间 `[GP_PRICE_MIN, GP_PRICE_MAX]`，按成交额取前 `GP_DYNAMIC_POOL_SIZE`。拉取日线指标/筹码，做硬过滤与禁买标记。
- 主线约束：默认仅在 TopN 行业/概念（真实来源）中选股，优先有行业字段的快照；否则用概念 TopN，取交集。
- 市场环境：按全市场均值涨跌幅与上涨占比打分（A/B/C/D），返回原因与恢复条件。
- 市场统计：聚合成交额、涨跌停数量；盘口口径缺失项返回 None 并标记 missing。
- 公告与事件：近 30 日公告风险关键词、分红派息登记等事件与限售解禁（若缺失以 missing 说明）。
- 打分与分散：多维度打分（环境/主题/趋势/波动/筹码/统计/风险/RS），并限制同一行业/主题的数量。

---

## AkShare 多线路回退
为解决东财 push2 在部分网络下连接中断，新增可配置优先级并串行回退（默认采用更稳组合）：

日线优先级（默认 `sina,em,tx`）
- tx（`stock_zh_a_hist_tx`）：返回 `date,open,close,high,low,amount(手)`；内部转换：`volume=amount*100`；`amount(成交额)`近似为 `close*volume`（在 `attrs.amount_is_estimated=True` 标注）。
- sina（`stock_zh_a_daily`）：包含 `volume(股)` 与 `amount(元)`，直接映射。
- em（`stock_zh_a_hist`）：若缺 `amount`，以 `close*volume` 近似。
- 标准化输出：`date, open, high, low, close, volume, amount`（日期升序，数值列为数值类型）。

快照优先级（默认 `em,sina`）
- sina（`stock_zh_a_spot`）优先，减少解析失败；
- em：先直连 push2，再回退 `stock_zh_a_spot_em`；
- 内存 TTL 缓存：30 秒。

环境变量（env-first）
- `AK_DAILY_PRIORITY`：默认 `sina,em,tx`
- `AK_SPOT_PRIORITY`：默认 `em,sina`

来源标注
- DataHub 在严格真实模式下会把来源写入 meta：`akshare:tx | akshare:sina | akshare:em`；离线 fixtures 则为 `fixtures`。

---

## 配置（环境变量）
基础
- `DATA_PROVIDER=akshare`（强制 AkShare）
- `STRICT_REAL_DATA=1`（默认开启，禁用合成降级；DataHub 不命中时直接报错）
- `LLM_BASE_URL`、`LLM_API_KEY`、`CHAT_MODEL`（用于对话与讲解，可选）

AkShare 回退
- `AK_DAILY_PRIORITY`、`AK_SPOT_PRIORITY`（见上文）

候选与主线
- `GP_MIN_AVG_AMOUNT`（默认 `5e8`）
- `GP_NEW_STOCK_DAYS`（默认 `60`）
- `GP_PRICE_MIN`、`GP_PRICE_MAX`（默认 `2/500`）
- `GP_DYNAMIC_POOL_SIZE`（默认 `200`）
- `GP_RESTRICT_MAINLINE`（默认 `1`）、`GP_MAINLINE_TOP_N`（默认 `2`）、`GP_MAINLINE_MODE=auto`
- `GP_MAX_PER_INDUSTRY=2`

其它
- `GP_REQUEST_TIMEOUT_SEC`、`TZ`、`GP_DEFAULT_VOLUME_UNIT`

---

## 目录结构（摘）
- 代码：`src/gp_assistant`（core/providers/tools/recommend/strategy/...）
- 服务器：`src/gp_assistant/server/app.py`（FastAPI）
- 数据：`store/`（fixtures、cache、snapshots）、`data/`（运行时）、`results/`、`universe/`
- 配置：`configs/`
- 脚本：`scripts/`
- 构建：`requirements.txt`、`pyproject.toml`、`Dockerfile`、`docker-compose.yml`

---

## 诊断与排障
- 查看 Provider 健康：
  - `python -c "from gp_assistant.providers.factory import provider_health; print(provider_health())"`
- EastMoney 连接中断：
  - 使用默认优先级（Sina 优先）；必要时设置 `AK_SPOT_PRIORITY='sina,em'`、`AK_DAILY_PRIORITY='tx,sina,em'`
- LLM 不可用：
  - 不影响真实数据链路；仅在对话与讲解部分返回 `narrative_unavailable` 标注。
- 编译校验：`python -m compileall src`（本仓通过）

---

## License
MIT，详见 `LICENSE`。
