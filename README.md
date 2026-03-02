## A股主板短线回测实验系统（候选池20 + 5min执行 + 周度对比）

### 快速启动（本地）
- 环境：Python 3.11+（推荐 3.12），无需数据库。
- 安装依赖：
  1) `python -m venv .venv && source .venv/bin/activate`（Windows: `.venv\\Scripts\\activate`）
  2) `pip install -r requirements.txt`
- 一键自检（含单测/服务链路/实验）：
  - `python gpbt.py gate --level ALL`（看到 ALL PASS 即可）
- 启动后端 API（FastAPI）：
  - `python -m uvicorn src.gp_assistant.server.app:app --host 0.0.0.0 --port 8000`
  - 健康检查：`curl http://localhost:8000/api/health`（会返回 `service` 状态）
  - 获取最新推荐：`curl http://localhost:8000/api/reco/latest`
  - 按卡片模式获取：`curl -X POST http://localhost:8000/api/recommend -d '{"mode":"service","detail":"compact"}' -H 'Content-Type: application/json'`
- 可选前端（本地开发）：
  - `cd frontend && npm ci && npm run dev`，浏览器访问 http://localhost:5173（聊天输入“最新推荐”会读取 latest.json）

#### 加入 API Key（本地）
- LLM（用于聊天功能；荐股不依赖）：
  - macOS/Linux（bash/zsh）：
    - `export LLM_API_KEY=你的密钥`
    - `export LLM_BASE_URL=https://api.deepseek.com/v1`（如用 DeepSeek）
  - Windows（PowerShell）：
    - `$env:LLM_API_KEY = "你的密钥"`
    - `$env:LLM_BASE_URL = "https://api.deepseek.com/v1"`
  - 然后启动：`python -m uvicorn src.gp_assistant.server.app:app --host 0.0.0.0 --port 8000`

### 使用 Docker（后端与前端）
- 准备：复制 `.env.example` 为 `.env`，按需改环境变量（默认数据源 AkShare，无需 Token）。
- 启动后端（FastAPI）与 LLM 代理（可选）：
  - `docker compose up -d gp llm-proxy`
  - 后端健康：`curl http://localhost:8000/api/health`
- 启动前端（可选）：
  - `docker compose up -d web`，打开 http://localhost:8080
- 在容器里跑荐股链路：
  - 盘前：`docker compose exec gp python gpbt.py service preopen --date 20250106`
  - 全天循环（后台）：`docker compose exec -d gp python gpbt.py service run --date today --every 300 --until 15:00`
  - 收盘与发布：`docker compose exec gp python gpbt.py service close --date 20250106 && docker compose exec gp python gpbt.py service publish --date 20250106`
- 数据持久化：`docker-compose.yml` 已将宿主机目录挂载到容器 `/app/{data,results,universe,store,configs}`，产物和缓存重启不丢。
- 切换数据源：在 `.env` 中设置 `DATA_PROVIDER=akshare|tushare|local`（默认 akshare）。

#### 加入 API Key（Docker）
- 复制 `.env.example` 为 `.env`，在其中设置：
  - `LLM_API_KEY=你的密钥`（可选：`LLM_BASE_URL`）
  - 如走代理服务：`UPSTREAM_API_KEY`（`services/llm_proxy` 使用）
- 重新启动：`docker compose up -d`

### 查看运行日志（可直接复制）
- 本地（uvicorn 后端）：
  - 前台日志：
    - `python -m uvicorn src.gp_assistant.server.app:app --host 0.0.0.0 --port 8000 --log-level info`
    - 调试级别：把 `--log-level info` 改为 `--log-level debug`
- 本地（服务循环 gpbt）：
  - 注意：`--until` 必须为 `HH:MM`（例如 `15:00`）；重定向需与命令在同一行。
  - 直接写到当前目录一个 txt 文件：
    - Windows PowerShell：`python gpbt.py service run --date today --every 300 --until 15:00 2>&1 | Tee-Object -FilePath .\\service.txt -Append`
    - Linux/macOS：`python gpbt.py service run --date today --every 300 --until 15:00 2>&1 | tee -a service.txt`
  - 先创建日志目录：
    - Linux/macOS：`mkdir -p logs`
    - Windows PowerShell：`New-Item -ItemType Directory -Force .\logs`
  - 前台运行并写入同一个日志文件：
    - Linux/macOS：
      - `python gpbt.py service run --date today --every 300 --until 15:00 2>&1 | tee -a logs/service.log`
    - Windows PowerShell：
      - `python gpbt.py service run --date today --every 300 --until 15:00 2>&1 | Tee-Object -FilePath .\logs\service.log -Append`
    - 使用虚拟环境 python（可选）：
      - Windows：`.\.venv\Scripts\python.exe gpbt.py service run --date today --every 300 --until 15:00 2>&1 | Tee-Object -FilePath .\logs\service.log -Append`
  - 后台运行并分别写出/错日志（Windows PowerShell）：
    - `Start-Process -FilePath python -ArgumentList 'gpbt.py','service','run','--date','today','--every','300','--until','15:00' -NoNewWindow -RedirectStandardOutput .\logs\service.out.log -RedirectStandardError .\logs\service.err.log`
  - 实时查看日志尾部：
    - Linux/macOS：`tail -f logs/service.log`
    - Windows PowerShell：`Get-Content .\logs\service.log -Wait`
- Docker：
  - 后端容器日志：`docker compose logs -f gp --tail=200`
  - 前端/代理：`docker compose logs -f web`、`docker compose logs -f llm-proxy`
  - 进入容器：`docker compose exec gp bash`

### 荐股流程（说人话）
- 盘前（preopen）
  - 干什么：从全市场筛出 Top20 候选，结合风控，生成当日初始推荐。
  - 产物：`store/recommend/YYYYMMDD.json` 和 `store/recommend/latest.json`（stage=preopen）。
  - 命令：`python gpbt.py service preopen --date 20250106`（或让 run 自动补齐）。
- 盘中（intraday）
  - 干什么：每 5 分钟读取新 bar，计算/回测影子持仓，产出 shadow 指标，并刷新 latest.json。
  - 产物：`results/live_shadow/YYYYMMDD/{order_log.csv,equity.csv,metrics.json}`；`latest.json` 会随轮次更新（stage=intraday）。
  - 命令（全天循环）：`python gpbt.py service run --date today --every 300 --until 15:00`
- 收盘（close）
  - 干什么：收盘收尾，定格当日推荐和 shadow 指标。
  - 产物：`YYYYMMDD.json` 与 `latest.json`（stage=close）。
- 给谁看：前端/对话卡片统一读取 `store/recommend/latest.json`，里面总有这 3 个关键字段：
  - `as_of`: `YYYYMMDD`
  - `as_of_ts`: `YYYYMMDD HH:MM:SS`
  - `stage`: `preopen|intraday|close`
- 默认数据源：AkShare（无需 token）。


### 完整荐股策略（说人话）
- 总体目标：给“仅沪深主板”的可交易清单，附带买点/止损/止盈线，盘前产出，盘中滚动刷新；任何外部接口故障都不影响用户“至少看到真实或近期真实的线索”。

- 基础数据与“主板”严格限制
  - 数据源：默认 AkShare；不需要 Tushare。
  - 代码归一：统一到 `XXXXXX.SH|SZ`，内部计算一律用 `ts_code`。
  - 主板仅这几段：沪 600/601/603/605；深 000/001/002/003。科创板 688、创业板 300/301、B 股 200/900 等全部剔除（候选池构建与动态候选都按这个规则过滤）。

- 盘前（preopen）怎么挑票
  1) 快照与环境：优先拉一次全市场快照（失败也不致命）；根据广度/涨跌幅等做“环境分层”打标签（A/B/C/D）。
  2) 主题（themes）：
     - 首选东财行业/概念榜；若断连自动尝试 THS；成功就写入磁盘缓存（真实历史）。
     - 若接口全挂，回退到“快照强势线索”（按涨跌幅/成交额挑 top movers）——保证不是空白。
  3) 主线（mainline）：
     - 若快照里有“行业”，先做按行业的成交额/涨跌聚合；否则走资金流榜；成功即写磁盘缓存。
     - 接口失败时在 TTL 内直接用缓存，超 TTL 但在可容忍时限内也用“stale cache”兜底（都是过去真实数据）。
  4) 候选池：
     - 动态候选优先用快照里成交额排序做截断（默认 200）；如无快照，则读 `universe/` 文件；都只保主板。
     - 拉日线做基本特征：`ma20/slope20/atr_pct/gap_pct` 等。
     - 筛掉硬性不合格：流动性太差/历史太短；并打“仅观察/禁止”的标记（如 ATR 过大、贴近 90% 筹码高位等）。
  5) 生成 picks：
     - 对每只票评估所有已注册策略（detect_setups/event study），选出“当下冠军（champion）”。
     - 关键带（S1/S2/R1/R2）优先来自策略；不行则用筹码带；再不行用近期窗口分位点（并记录诊断）。
     - 由关键带推导出“买点/止损/止盈”（entry/stop/take）写在 `trade_plan` 里，前端可直接展示。

- 盘中（intraday）怎么滚动
  - 每 5 分钟拉一次分钟线（动态候选 + 持仓涉及的票），按回测引擎跑“影子执行”，生成订单/权益/简单指标到 `results/live_shadow/`。
  - 同步刷新 `latest.json` 的时间戳与阶段；若 picks 为空且 tradeable=true，会自动打 `EMPTY_PICKS` 的 degraded 提示，避免“好像可以交易但没票”的坏状态。

- 降级与告警（不吓人，也不装）
  - 真正问题才降级：会写 `debug.degraded=true` + `degrade_reasons=[...]`，前端红色提示。
  - 轻微/可容忍问题只告警：写到 `debug.warnings`，不影响 `tradeable`（如 `UNIVERSE_DIRTY_INPUT`）。
  - data_status 里标注来源（source）与是否用到了 TTL cache 或 stale cache，方便诊断。

- 最终“能不能交易”的判定
  - 必须：无降级 + 快照干净 + 候选池/可交易数量达标（阈值可配置）+（可选）主线存在。
  - 不满足则 `tradeable=false`，message 前缀会列出关键原因代码。

#### 常用开关（环境变量，按需）
- `GP_DYNAMIC_POOL_SIZE`（默认 200）：动态候选截断规模（避免全市场都算）。
- `GP_THEME_CONCEPT_MAX_STALE_SEC`（默认 86400）：主题缓存可用的最长“过期”时间。
- `GP_MAINLINE_TTL_SEC`（默认 300）：主线资金流的磁盘缓存 TTL。
- `GP_MAINLINE_MAX_STALE_SEC`（默认 86400）：主线资金流在失败时允许使用的最长“过期”时间。
- `GP_TRADEABLE_MIN_UNIVERSE` / `GP_TRADEABLE_MIN_CANDIDATES`：可交易判定的数量阈值。

#### 输出长什么样（v1 契约）
- `store/recommend/latest.json` 与 `YYYYMMDD.json`：
  - `picks: [...]`
  - `meta: { tradeable, as_of, as_of_ts, stage, disclaimer, debug{ degraded, degrade_reasons|warnings, mode }, ... }`
  - 买点/止损/止盈在每个 pick 的 `trade_plan.entry/stop/take`，关键带在 `trade_plan.bands`。


本项目按《项目计划.txt》进行方向纠偏式重构，将原有 gp_assistant 主文档改为以回测实验系统为主。旧助手说明见 `docs/assistant.md`（docker-compose 仍可运行）。

核心约束（默认）
- 仅沪深主板；默认剔除 ST/*ST；默认剔除上市不足 `min_list_days` 的新股；
- 每天盘前生成候选池 Top20；盘中以 5 分钟K 执行；统一成交口径：信号在某根 5min bar 收盘确认后，下一根 bar 开盘成交（+滑点）；
- 严格 T+1；周一开始，周五收盘强制清仓；
- 输出每策略：胜率/单笔期望/盈亏比/最大回撤/交易次数/不可成交次数（涨停买不到/跌停卖不出）。

从 0 到跑通（命令，默认 AkShare）
- `python -m scripts.fetch_basics --provider akshare --start 20180101 --end 20251231`
- `python -m scripts.fetch_daily --provider akshare --start 20180101 --end 20251231`
- `python -m scripts.build_candidate_pool --date 20250106 --pool_size 20`
- `python -m scripts.fetch_min5_for_pool --provider akshare --date 20250106`
- `python -m backtest.runner_weekly --config configs/config.yaml --strategies configs/strategies/*.yaml --start 20200101 --end 20251231 --run_id demo_001`
- `python gpbt.py doctor --date 20250106`

数据源切换（可选）：
- 默认 AkShare（开箱即用）。
- 如需 Tushare：设置环境变量 `TUSHARE_TOKEN`，将命令加 `--provider tushare`，或在 `.env` 里设 `DATA_PROVIDER=tushare`。

项目结构（关键新增）
- `src/providers/`: 数据提供接口（Tushare/AkShare）与本地 Parquet 存储
- `src/scripts/`: 数据抓取与候选池脚本（支持 `python -m scripts.xxx`）
- `src/selector/selector_v1.py`: 可解释 V1 打分（趋势/动量/流动性/波动惩罚/公告关键词）
- `src/strategies/`: 策略插件体系（baseline/breakout/pullback/openrange）
- `src/backtest/`: 回测引擎、周度运行器、指标汇总
- `results/run_{run_id}/`: `trades.csv`, `daily_equity.csv`, `weekly_summary.csv`, `metrics.json`

配置（见 `configs/config.yaml`）
- `market=mainboard`、`pool_size=20`、`min_list_days=60`、`exclude_st=true`
- `initial_cash=1_000_000`、`max_positions`、费用参数、`force_flat_on_friday_close=true`

可选 CLI（便捷封装）
- 初始化: `python gpbt.py init`
- 一次性抓取: `python gpbt.py fetch --provider akshare --start 20180101 --end 20251231`
- 生成候选池: `python gpbt.py build-candidates --date 20250106`
- 拉分钟数据: `python gpbt.py fetch-min5-for-pool --provider akshare --date 20250106`
- 回测: `python gpbt.py backtest --config configs/config.yaml --strategies configs/strategies/*.yaml --start 20200101 --end 20251231 --run_id demo_001`

测试与断言（离线 fixtures）
- 新增单元测试（见 `tests/`）：
  1) 无未来函数：候选池生成只用 ≤ 前一交易日数据；策略只能访问当前 bar 及以前
  2) T+1 强制：买入当日出现卖出 intent 不得成交
  3) 一字板不可成交挂起：构造涨停/跌停 bar 序列验证挂起逻辑与计数
  4) 费用一致性：对一笔已知交易手算费用与程序一致

提示
- 仓库根目录已包含 `sitecustomize.py`，可确保 `src/` 布局下使用 `python -m scripts.xxx` 直接运行。
- 若需安装包方式使用，也可 `pip install -e .`。

自检
- 一键自检（含单测/服务链路/实验）：`python gpbt.py gate --level ALL`
