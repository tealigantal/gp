## gp_assistant（对话式 A 股策略与推荐助手）
DeepSeek + 真实数据链路，支持多轮对话、意图识别、荐股与结构化结果；新增同源友好的 `/api` 前缀和轻量前端 SPA。

核心能力
- 数据链路：AkShare 多线路回退（Sina/EM/Tx），严格真实优先；可落盘结果
- 引擎要点：全市场快照→环境分层→主线约束→候选打分→冠军策略与关键带
- 服务形态：命令行、FastAPI HTTP、前端 SPA（React）

目录结构（摘）
- 代码与服务：`src/gp_assistant`
- 前端工程：`frontend/`
- 运行产物：`store/`（含 `store/recommend/*.json`）
- 配置示例：`.env.example`

---

## 一键启动（最小步骤）
本地后端 + 前端开发（推荐，用于联调）
1) 后端（端口 8000）
   - Python 3.10+
   - `pip install -r requirements.txt`
   - `uvicorn gp_assistant.server.app:app --host 0.0.0.0 --port 8000`
   - 健康检查：`curl http://127.0.0.1:8000/api/health`
2) 前端（端口 5173）
   - `cd frontend && npm i && npm run dev`
   - 访问 `http://localhost:5173`（Vite 已代理 `/api -> http://localhost:8000`）

Docker（全栈：前端 + 后端）
- 一键启动：`docker compose up --build -d`
- 首次构建会同时打包前端（Node 构建）与后端（Uvicorn）
- 访问前端：`http://localhost:8080`
- 健康检查（直连后端）：`curl http://127.0.0.1:8000/api/health`

生产构建与部署（同源方案）
- 前端构建：`cd frontend && npm run build`（产物在 `frontend/dist`）
- 同源部署建议：
  - 静态资源托管 `/`（拷贝 `frontend/dist`）
  - `/api` 反代到 FastAPI（端口 8000）
  - Nginx 示例：`location /api { proxy_pass http://backend:8000; }`；`location / { root /usr/share/nginx/html; try_files $uri /index.html; }`

---

## 后端 HTTP API（新旧兼容）
新接口（统一前缀，供前端使用）
- POST `/api/chat`
- POST `/api/recommend`（支持 `detail: compact|full`，默认 `compact`）
- GET  `/api/health`
- 可选增强：
  - GET `/api/ohlcv/{symbol}?start=YYYY-MM-DD&end=YYYY-MM-DD&limit=800` → `{symbol, meta, bars[]}`
  - GET `/api/recommend/{date}` → 读取 `store/recommend/{date}.json`

旧接口（保留且行为一致，默认 `detail=compact`）
- POST `/chat`、POST `/recommend`、GET `/health`

轻量输出（detail=compact）
- 仅保留：as_of, timezone, env, themes, picks, tradeable, message, execution_checklist, disclaimer；
- debug 仅保留：degraded / degrade_reasons / advisories；
- `detail=full` 输出完整 payload。

可选 CORS（默认关闭）
- 设置环境变量 `GP_CORS_ORIGINS=http://localhost:5173,https://your.site` 开启跨域；未设置则不启用。

---

## 前端（React + Vite + AntD + React Query + ECharts）
开发模式（联调）
- `cd frontend && cp .env.example .env && npm i && npm run dev`
- 打开 `http://localhost:5173`，页面：
  - `/recommend`：参数表单（topk/universe/symbols/risk_profile/detail），展示 tradeable 与 env.grade，降级原因 Alert，Picks 表格（symbol/theme/strategy/bands/actions）
  - `/chat`：持久化会话，触发推荐时可跳转 `/recommend`
  - `/health`：Provider/LLM/time

生产构建
- `cd frontend && npm run build` → `frontend/dist`
- 配置同源反代 `/api`，避免跨域与 Cookie/鉴权复杂度。

---

## 常用命令（冒烟）
健康检查
- `curl http://127.0.0.1:8000/api/health`

对话
- `curl -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" -d '{"session_id":null,"message":"荐股 topk=3"}'`

推荐（轻量）
- `curl -X POST http://127.0.0.1:8000/api/recommend -H "Content-Type: application/json" -d '{"topk":3,"universe":"auto","risk_profile":"normal","detail":"compact"}'`

K 线（可选）
- `curl 'http://127.0.0.1:8000/api/ohlcv/600519?start=2024-01-01&limit=120'`

历史推荐（可选）
- `curl 'http://127.0.0.1:8000/api/recommend/2024-02-01'`

---

## 接口参数说明（中文）
POST `/api/recommend` Body
- topk: 返回候选数量（默认 3）。建议 1–10。
- universe: 股票池来源。`auto`（默认，从全市场动态筛）| `symbols`（只在给定列表内评估）。
- symbols: 当 `universe=symbols` 时生效，证券代码数组，如 `["600519","000333"]`。
- risk_profile: 风险偏好。`normal`（默认）| `conservative` | `aggressive`（仅作为说明性参数，不改变核心数据链路）。
- detail: 输出详略。`compact`（默认，轻量字段集）| `full`（完整结果，适合调试或导出）。
- date: 可选，指定交易日（默认使用最新交易日）。

POST `/api/chat` Body
- session_id: 会话 ID，可空。为空时后端自动生成并回传，用于多轮对话。
- message: 用户输入文本，如“给我推荐 3 只低位放量”。

GET `/api/ohlcv/{symbol}` Params（可选增强）
- start: 开始日期（YYYY-MM-DD）。
- end: 结束日期（YYYY-MM-DD）。
- limit: 只返回尾部最近 N 根 K 线（默认 800）。

返回结构要点
- env.grade: 市场环境分层 A/B/C/D。
- picks[].champion.strategy: 每只标的的“冠军策略”。
- picks[].trade_plan.bands: 关键带位 S1/S2/R1/R2（若策略未给出，则回退为筹码带）。
- debug.degraded/degrade_reasons: 数据链路降级标记与原因代码（仅诊断用）。

---

## 关键文件
src/gp_assistant/server/app.py
src/gp_assistant/server/models.py
frontend/vite.config.ts
frontend/.env.example

---

## 引擎简介（概览）
- 候选池：剔除 ST/退/新股≤`GP_NEW_STOCK_DAYS`、价格区间 `[GP_PRICE_MIN, GP_PRICE_MAX]`，基于全市场快照按成交额取前 `GP_DYNAMIC_POOL_SIZE`
- 主线约束：仅在行业/概念 TopN 内选取
- 环境分层：A/B/C/D 并给出恢复条件
- 冠军策略与关键带：为每只标的挑选策略冠军与 S1/S2/R1/R2 执行带

更多细节见代码与注释（策略库与指标、降级与可观测性等）。

---

## License
MIT，详见 `LICENSE`。

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

## 选股逻辑（决策条件）

只列规则，不做叙述：

- 候选入围（基于快照）
  - 非 ST：`not name.upper().str.contains('ST|\*ST|退')`
  - 价格：`GP_PRICE_MIN ≤ close ≤ GP_PRICE_MAX`（默认 2–500）
  - 新股：若有 `list_date`，`days_since_list ≥ GP_NEW_STOCK_DAYS`（默认 60）
  - 规模：按 `amount` 降序取前 `GP_DYNAMIC_POOL_SIZE`（默认 200）
  - 主线（默认开）：若有 `industry`，取 `sum(amount)` 排名前 `GP_MAINLINE_TOP_N`（默认 2）行业内股票

- 单标有效性
  - `len(bars) ≥ 250`（不足仅计数）
  - `amount_5d_avg = rolling_mean(amount, 5)`
  - `atr_pct = ATR14/close`；`gap_pct = (open - prev_close)/prev_close`；`slope20 = (ma20 - ma20.shift(5))/ma20.shift(5)`；`dist_to_90_high_pct`

- 硬否决（剔除）
  - `amount_5d_avg < GP_MIN_AVG_AMOUNT`（默认 5e8）

- 观察标记（保留但标识不可执行）
  - 任一满足：`liq_grade == 'C'` 或 `atr_pct > 0.08` 或 `gap_pct > 0.02` 或 `dist_to_90_high_pct ≤ 0.02`

- 排序（从好到差）
  - `-slope20` → `atr_pct`（小优先） → `liq_grade`（A 优于 B 优于 C）

- 选取
  - 排序后取前 `topk` 作为 `picks`

- 可交易（tradeable == True）
  - 快照干净：非 missing/fallback/cache/stale/报错
  - `universe_after_filter_count ≥ GP_TRADEABLE_MIN_UNIVERSE`（默认 50）
  - `candidates_out_count ≥ GP_TRADEABLE_MIN_CANDIDATES`（默认 20）
  - 无 `degrade_reasons`

- 环境等级（仅影响建议语气，不影响是否产生 picks）
  - `A: mean_chg>1.0 且 up_ratio>0.6`；`B: >0.3 且 >0.55`；`C: >-0.3 且 >0.45`；否则 `D`

## 选股逻辑（通俗解释）

一句话概括：先从全市场抓一批“今天最有交易量的人气股”，再用“更稳的、趋势更好的、离压力区不近”的原则，把它们排个序，取前几只给出执行要点。

- 第一步｜先挑人气股（看得见钱的地方）
  - 用全市场快照把“问题股”先剔掉（ST/退、价格太极端、新股太短）。
  - 剩下的按“成交额”从高到低取前 N（默认 200）。这一步就是把“今天市场的注意力在哪”抓出来。

- 第二步｜只在主线里找（顺风口更省力）
  - 把候选按行业汇总成交额，找出“总成交额最高”的前 2 个主线行业，只在这两个行业里挑。这样能避开杂音，跟着大部队走。

- 第三步｜补历史、算特征（看趋势和稳定度）
  - 给每只候选拉日线，计算：
    - 趋势：20 日均线是否在抬头（slope20 越大越好）。
    - 稳定：ATR% 越小越稳，Gap% 太大说明跳空多、节奏差。
    - 参与度：5 日成交额均值（越大越好）。
    - 位置：筹码 90% 带，离上沿太近说明“上面卖压近”，不宜强推。

- 第四步｜一个硬门槛（流动性不够直接淘汰）
  - 5 日成交额均值 < 5e8 的直接不要。没量，做了也不灵活。

- 第五步｜几个软约束（不强推就标记“观察”）
  - 满足以下任一就“先观察”：
    - 流动性等级 C（5 日成交额均值 < 1e9）；
    - ATR% > 8%（今天太乱）；
    - Gap% > 2%（跳空过多）；
    - 距筹码 90% 上沿 ≤ 2%（头上压力太近）。

- 第六步｜怎么排座次（谁更优先）
  - 先看趋势（slope20 大的靠前），
  - 再看稳定（ATR% 小的靠前），
  - 最后同等条件下，优先流动性 A > B > C。

- 第七步｜给出前几名 + 执行要点
  - 取前 topk 只。每只都会挑一个“最匹配的交易法”（14 个策略里选冠军），配上关键带位（S1/S2/R1/R2）和“何时确认/何时放弃”的要点，方便落地执行。

- 第八步｜遇到弱市时怎么办
  - 如果当天市场整体很弱（上涨占比很低、平均涨跌为负），会提示“轻仓/观察为主”，但只要数据齐、样本足，仍会给出候选；只有数据链路不完整或样本过小，才提示“不具备可交易性”。

- 数据来源怎么保证靠谱
  - 快照先走 EastMoney（EM），不通就走 Sina；日线先走 Sina，再尝试 EM，最后 Tx；严格真实模式下“不瞎补”，缺字段直接换路由。Tx 的“成交量(手)”已经自动换算成“股”。

## 策略库（人话版）

系统内置 14 个“能落地的交易法”，每只标的自动挑一个最合适的作为“冠军”，并给出关键带位与执行要点。下面是每个策略的白话说明：

- S1｜Bias6 上穿：短均线重新压过中均线，趋势有起色。
  - 适合：回踩后转强的票；不追远离均线的大阳。
  - 确认：收盘站回关键带，量能不失控。

- S2｜RSI2 反弹：超跌后的短线弹一下。
  - 适合：区间内来回波动的票；趋势震荡为主。
  - 确认：连阴后出现止跌+小放量；只做 2–5 天的快进快出。

- S3｜Squeeze 收缩→释放：长时间缩在小区间，放量走出方向。
  - 适合：一段时间很安静的票；等“闸门打开”的那一下。
  - 确认：放量突破收缩区，上方空间不近压。

- S4｜Turtle Soup 假突破：先破前高/前低，马上收回去，走反向。
  - 适合：情绪走极端后拐头；反身快、吃波动。
  - 确认：快速回收关键位；不拖泥带水。

- S5｜MA20 回踩：回到 20 日线附近止跌再起。
  - 适合：稳步上行的票；用 20 日线当路边石。
  - 确认：回踩不破、次日企稳；量能正常。

- S6｜突破回踩：先突破，回来晃一圈，守住再上。
  - 适合：平台突破后的二次上攻。
  - 确认：回踩不破突破位或关键带，放量转强。

- S7｜NR7 窄幅：今天很窄，后面容易走出方向。
  - 适合：缩量整理末期；博第二天变盘。
  - 确认：次日放量出区间；别在中间追。

- S8｜量能激增：突然放很大的量，有延续/分歧两种走法。
  - 适合：热点轮动里的人气股；优先顺势跟随，不做逆势硬抗。
  - 确认：放量后不回吐，收盘站稳关键带。

- S9｜筹码支撑：价格回到筹码密集区下沿附近，有承接。
  - 适合：震荡抬升、下方筹码厚的票。
  - 确认：下沿附近缩量止跌→回收；靠近上沿不追。

- S10｜跳空处理：有缺口就看是回补还是被封住。
  - 适合：消息驱动后的次日；要快。
  - 确认：回补途中不破关键位；若被压着走就放弃。

- S11｜RSI2 极端：过热/过冷后的“拉回正态”。
  - 适合：短线幅度过猛的票；只做小波段。
  - 确认：极端读数回到正常区间；止盈止损都要快。

- S12｜AVWAP 锚：围绕事件/阶段成本线的拉扯。
  - 适合：机构抱团或有明确锚点的票。
  - 确认：回踩 AVWAP 不破或收复 AVWAP；线下久拖不碰。

- S13｜收缩后的继续：Squeeze 放量后的一段延续。
  - 适合：刚走出收缩的强势票；吃“第二段”。
  - 确认：缩量回踩不破、再放量拉起。

- S14｜Turtle Soup Plus：更干净的假突破，条件更苛刻、信号更少。
  - 适合：追求胜率、宁缺毋滥。
  - 确认：快速收复+收盘确认；拖泥带水不做。


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
