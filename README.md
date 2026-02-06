# 使用说明（gp + gpbt + 对话 Agent）

本仓库已封装一个可对话的 Agent，能够在本地或 Docker 中直接对话，并通过现有 gpbt 能力完成“LLM 荐股→回测”的工作流。以下仅保留“怎么用”的说明。

## 本地快速跑
- 安装依赖并初始化目录：
  - `pip install -r requirements.txt`
  - `python gpbt.py init`
- 启动对话：
  - `python assistant.py chat`
- 单次自测（便于 CI/脚本）：
  - `python assistant.py chat --once "荐股"`

提示：若未配置真实 LLM Key，Agent 仍可用，会使用“可解释的规则排序”作为荐股结果，并在输出中标注 provider=fallback/mock。

## Docker 快速跑（推荐）
1) 复制环境变量模板：
   - `cp .env.example .env`
   - 如需启用 DeepSeek，请在 `.env` 设置 `DEEPSEEK_API_KEY`；或在 `configs/llm.yaml` 设为 `provider: mock` 走离线自测。
2) 构建镜像并启动：
   - `docker compose up --build -d`
3) 进入可交互对话：
   - `docker compose run --rm gp`

预置卷确保数据持久化：`./data ./universe ./results ./store ./cache ./configs`。

## 对话示例
- “荐股”
- “推荐 20260106 top5”
- “/pick --date 20260106 --topk 5 --template momentum_v1 --mode auto”

输出包含：TopK 股票代码、简短理由、使用模板/策略/日期，以及数据就绪情况（候选池/分钟线缺口/日线缺口）。

## 可选：使用 gpbt 原生命令
- 初始化与抓取：
  - `python gpbt.py init`
  - `python gpbt.py fetch --start 20260103 --end 20260110 --no-minutes`
- 构建候选池与诊断：
  - `python gpbt.py build-candidates-range --start 20260106 --end 20260110`
  - `python gpbt.py doctor --start 20260106 --end 20260106`
- LLM 排名（支持 mock/fallback）：
  - `python gpbt.py llm-rank --date 20260106 --template momentum_v1`

说明：无真实 key 时会用 mock/fallback 仍给结果；如需真实 LLM，可填 UPSTREAM_API_KEY（走 llm-proxy）或 DEEPSEEK_API_KEY（直连）。任何 Key 仅从 env/.env 读取；输出/落盘均脱敏。
