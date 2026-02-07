# gp（单入口 Agent + Provider 可插拔 + AkShare 回退）

本仓库已重构为“单入口、最小可用”的形态：只保留一个对外 CLI 入口，Agent 作为唯一编排层，所有功能以工具（tools）形式接入；数据源支持可插拔 Provider，默认使用 AkShare，在没有官方凭证时自动回退且不影响运行。

重要：Docker 与 docker-compose 的运行方式保持不变，仅将启动命令切换为新的单入口。

## 项目总览
- 唯一接口：`chat`（LLM 路由，多轮对话）
- 仅支持 Docker 方式部署与测试（不再提供本地 CLI 使用说明）
- Provider：`akshare`（默认）、`official`（占位）

## 目录结构（核心）
```
src/gp_assistant/
  __main__.py            # 支持 python -m gp_assistant
  cli.py                 # 唯一 CLI 入口
  agent/
    agent.py             # 编排：解析 → 路由 → 执行 → 输出
    state.py             # 会话/运行态（最小）
    router_llm.py        # LLM 路由器（真实调用，JSON 输出）
    router_factory.py    # 路由工厂（统一走 LLM；无密钥时给 help）
  tools/
    registry.py          # 工具注册表
    market_data.py       # 行情/基础数据（内部调用 provider）
    universe.py          # 选股池构建
    signals.py           # 指标/信号（占位）
    rank.py              # 排序/打分（占位）
    strategy_score.py    # 多策略打分（占位）
    market_info.py       # 市场信息抓取（无 key 爬虫）
    recommend.py         # LLM 合成推荐（无模板；无 key 时 narrative=None）
    backtest.py          # 回测（占位）
    explain.py           # 解释（占位）
  providers/
    base.py              # MarketDataProvider 抽象接口
    akshare_provider.py  # AkShare 实现（默认）
    official_provider.py # 官方数据源占位（缺凭证时报可读错误）
    factory.py           # Provider 选择/降级唯一决策点
  core/
    config.py            # 配置入口（env 为主，默认集中）
    paths.py             # 路径统一管理（cache/store/data 等）
    logging.py           # 日志
    errors.py            # 可读异常
    types.py             # 通用类型
  llm_client.py          # OpenAI 兼容 LLM 客户端（用于路由/合成）
```

已清理旧管线与冗余模块：`src/gp_core/`、`src/gp/`、`src/gpbt/`、`src/gp_research/` 与旧工具脚本等均已移除，仅保留单一管线。

## 部署与运行（Docker 专用）
1) 准备环境变量（DeepSeek）
```
export DEEPSEEK_API_KEY=你的DeepSeekKey   # Windows 请用 setx 或 $env:DEEPSEEK_API_KEY
```
2) 构建镜像
```
docker compose build gp
```
3) 启动交互式对话（仅 chat 接口）
```
docker compose run --rm gp
```
容器内会直接进入多轮 REPL（因为默认命令是 `python -m gp_assistant chat --repl`）。
示例输入：
```
recommend topk=3 date=2026-02-09
data 000001 start=2026-02-01 end=2026-02-09
```

（不再提供本地 CLI 子命令用法，项目只暴露 Docker + chat 接口。）

### 多轮对话说明
- 交互命令：`python -m gp_assistant chat --repl`
- 上下文范围：同一进程内保留“最近 10 次路由结果”（工具名与参数），作为路由提示上下文，提升自然语言连续性；当前未做跨进程持久化。
- 提示：若需要跨会话持久化（例如写入 `store/`），我可以按你的偏好加一个 `--session` 开关做轻量持久化。

## LLM 路由与推荐合成（DeepSeek 专用）
- 配置文件：`configs/llm.yaml`
  ```yaml
  provider: deepseek
  base_url: "https://api.deepseek.com/v1"
  model: "deepseek-chat"
  api_key_env: "DEEPSEEK_API_KEY"
  temperature: 0.2
  max_tokens: 1200
  timeout_sec: 60
  retries: 2
  json_mode: true
  ```
- 环境变量：设置 `DEEPSEEK_API_KEY`
- 无密钥：`chat` 返回结构化 help；`recommend` 仍会跑评分与资讯抓取，但 `narrative=None`

## 推荐逻辑（流水线说明）
- 入口与路由：容器进入 REPL 后，所有自然语言输入都交由 DeepSeek 路由，产出严格 JSON `{tool, args}`。当 `tool=recommend` 时进入推荐流水线。
- 流水线步骤：
  - `universe`：加载默认候选池（`core/config.py` 中 `default_universe`，当前为 `['000001','000002','000333','600519']`），不触网，可按需求扩展。
  - `strategy_score`：对候选池进行“确定性占位打分”（规则：将证券代码中的数字求和，`sum(digits) % 10 / 10.0`，数值越大排名越前），支持 `topk` 与 `offset` 分页，仅用于骨架演示，后续可替换为真实因子/回测策略。
  - `market_info`：无 key 的公开网页抓取（优先东方财富，失败回退新浪财经），提取标题列表与少量正文摘要（优先 `readability-lxml`，缺失则使用 `BeautifulSoup` 提取正文文本），合成 `summary` 与 `sources[{title,url}]`。
  - `recommend`（合成）：将 `candidates`（前 `topk` 项）与 `market_context`（`summary/sources`）交给 DeepSeek 生成结构化 JSON，字段包含：
    - `narrative`：简明理由（无模板）；
    - `reasoning`（可选）：当路由设置 `explain=true` 时输出更具体的原因；
    - `trade_points`（可选）：当路由设置 `need_trade_points=true` 时输出每只票的买卖点（如买入区间/卖出区间/止损/入场时机/备注）。
    - 若无 DeepSeek Key，则这些字段返回 `null`，但 `picks` 与 `market_context` 仍可用。
- 多轮对话约定（由 LLM 路由决定，不在代码中写 if/else）：
  - 未明确工具但与上一轮相关：默认延续上一轮 `tool`，继承必要参数（如 `date/topk/offset`）。
  - “更多/其他/换/继续”等追问且上一轮为 `recommend`：自动设置 `args.offset = last.offset + last.topk`（分页继续），保留 `last.topk/last.date`。
  - “为什么/理由/原因”：设置 `args.explain = true`（触发 `reasoning` 输出）。
  - “买卖点/支撑位/阻力位/止损/入手时机/需要发给我”：设置 `args.need_trade_points = true`（触发 `trade_points` 输出）。
  - 不确定时：返回 `help` 并在 `args.question` 提示所需澄清的信息。
- 预算与仓位（说明）：当前打分逻辑未使用“预算/仓位”等约束；它们可作为后续扩展（例如在 `strategy_score` 或新增回测/仓位分配工具中引入），DeepSeek 侧会把这些信息用于 `narrative/trade_points` 的表述，但不改变打分排序本身。
- 失败与降级：
  - LLM 路由失败 → 返回 `help`（结构化，非堆栈）；
  - LLM 合成失败 → `narrative/reasoning/trade_points` 为 `null`；
  - 资讯抓取异常 → `summary` 尽力生成且 `sources` 可能为空；
  - 整体不影响 chat 会话与结构化输出。

## Provider 配置与回退
- 环境变量：
  - `DATA_PROVIDER`：`akshare`（默认）或 `official`
  - `OFFICIAL_API_KEY`：官方数据源凭证（占位字段）
- 选择/降级规则仅存在于 `providers/factory.py`：
  - 选择 `official` 但缺少凭证：不会崩溃，自动降级到 `akshare`，并输出明确提示。
- 健康检查：
```
python -c "from src.gp_assistant.providers.factory import provider_health; import json; print(json.dumps(provider_health(), ensure_ascii=False, indent=2))"
```

## 市场信息（无 key 爬虫）
- `tools/market_info.py` 抓取公开新闻站点标题（具备容错与备用源），返回 `{summary, sources:[{title,url}]}`
- 可随后替换为带 key 的搜索/摘要服务（接入 llm-proxy 或厂商 API）

## Docker/Compose
- Dockerfile：`CMD ["python","-m","gp_assistant","chat","--repl"]`
- docker-compose：服务 `gp` 默认进入交互式 chat（REPL）
- 数据卷映射：`data/`、`results/`、`universe/`、`store/`、`cache/`、`configs/`

运行示例：
```
docker compose build gp
docker compose run --rm gp python -m gp_assistant data --symbol 000001
docker compose run --rm gp python -m gp_assistant recommend --topk 2 --date 2026-02-09
```

## 快速验证（Smoke Tests）
以下命令应返回可读结果（或可读错误），不应出现堆栈信息：
```
python -c "from src.gp_assistant.providers.factory import provider_health; import json; print(json.dumps(provider_health(), ensure_ascii=False, indent=2))"
python -m gp_assistant data --symbol 000001
python -m gp_assistant pick
python tools/smoke_test.py
```

## 设计约束
- 仅保留单入口；旧入口脚本与旧管线已删除。
- Provider 选择/降级仅在 `providers/factory.py`，业务工具通过 `get_provider()` 获取。
- 路径统一在 `core/paths.py` 管理，禁止硬编码相对路径。
- 默认参数/模板/策略等统一在 `core/config.py` 管理。
- 工具模块不直接读环境/YAML（通过 config 或 factory 注入）。
- 错误信息可读并指示下一步（如“未配置官方凭证，已自动使用 akshare”）。

## 开发提示
- 编译检查：`python -m compileall src`（应返回 0）
- 日志级别：`GP_LOG_LEVEL`（默认 `INFO`）
- 数据/缓存/结果/存储目录：`core/paths.py` 自动创建（`cache/`、`store/`、`data/`、`results/`、`universe/`、`configs/`）
