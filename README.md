# 架构与使用（gp_core Pipeline）

本仓库后端已重构为三模块 + 一个编排主干：
- 模块① MarketInfo：真实网络搜索 + 抓正文 + LLM 结构化两周市场信息（含 sources 证据链）。
- 模块② StrategyEngine：LLM 选择策略集合 → 逐策略模拟/解释（结合 gpbt 数据） → 产出每策略结果。
- 模块③ AnswerComposer：综合用户提问 + 用户偏好 + A/B/回测结论 → LLM 生成最终建议。
- 编排器 Pipeline：按 Step1~Step5 串行执行，上下文与 LLM 提示/原始响应全部落盘。

重要：生产逻辑不包含任何 mock/fallback。缺少 LLM Key 或 Search Key 会直接报错（fail-fast）。

## 目录结构（后端）
- `src/gp_core/`：核心模块（schemas/io/llm/search/market_info/strategies/judge/qa/pipeline）
- `src/gp/cli.py`：新增 `gp recommend` 命令
- `src/gp/serve.py`：新增 Pipeline API（见下）
- `configs/`：`llm.yaml`、`search.yaml`、`strategies.yaml`、`pipeline.yaml`
- `store/pipeline_runs/`：每次运行的产物与审计材料

## 快速开始
1) 安装依赖：`pip install -r requirements.txt`
2) 配置环境：`cp .env.example .env` 并设置：
   - `DEEPSEEK_API_KEY`（或你的真实 LLM provider 的 key 与 base_url/model）
   - `TAVILY_API_KEY`（或 `BING_API_KEY`/`SERPAPI_API_KEY`）
3) 准备数据（示例）：`python gpbt.py init`，并根据需要更新数据/候选池。

### CLI（Pipeline）
运行：
```
python gp.py recommend --date 2026-02-09 --question "偏好短线，一周内机会？" --topk 3 --profile profile.json
```
输出 run_id 与最终建议文本，同时将产物写入 `store/pipeline_runs/{run_id}/`：
- `01_market_context.json`
- `01_sources.jsonl`
- `02_selected_strategies.json`
- `03_strategy_runs/{strategy_id}.json`
- `04_champion.json`
- `05_final_response.json`
- `05_final_response.txt`
- `prompts/{step}_{name}.json`（请求消息）
- `llm_raw/{step}_{name}.json`（原始响应）

### Assistant 对话
```
python assistant.py chat --once "2026-02-09 荐股，我的账户可用资金26722.07，..."
```
首轮“荐股”触发完整 Pipeline，并把 run_id 存入会话；后续如“第2只为什么推荐？”仅读取该 run 的产物进行解释（不重跑）。

## API（FastAPI）
- `POST /api/recommend` → 直接跑 Pipeline，返回 `{run_id, response}`
- `GET  /api/runs/{run_id}` → 返回该 run 的 `index.json`
- `GET  /api/runs/{run_id}/artifacts/{name}` → 下载/查看单个产物（json/jsonl/txt）

## 配置说明
- `configs/llm.yaml`：必须为真实 provider；缺 key 将直接报错。
- `configs/search.yaml`：必须为真实搜索 provider（tavily/bing/serpapi）与对应 env。
- `configs/strategies.yaml`：策略注册表（id/name/tags/风险偏好/默认参数）。
- `configs/pipeline.yaml`：默认 lookback/topk/queries（代码当前也内置了等价默认值）。

## 编码与字符门禁
- 仅允许 UTF-8 源码，禁止混入私用区/不可打印字符。
- 本仓库提供 `tools/check_nonprintable.py` 与测试 `tests/test_nonprintable.py`；任何违规会直接失败。
- 建议使用纯文本编辑器/终端粘贴中文，不要从富文本拷贝。
- 若遇异常，可运行 `python tools/sanitize_nonprintable.py` 一键清理并查看 `store/nonprintable_cleanup_report.json`。

## 复现与审计
每次运行均生成 `index.json` 与完整 prompts/raw 响应，可根据 run_id 完整复现与审计。
