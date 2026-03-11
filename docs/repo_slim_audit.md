# 仓库瘦身审计（xiufu 分支）

本审计以“运行态剥离、源码收口、保留主链”为原则，结合调用链、测试、服务入口与文档引用逐项给出结论：

## 目录与文件结论

- store/encoding_normalize_report.json：delete
  - 一次性报告，未在代码/测试/文档被引用。
- store/gp.duckdb：move-out
  - 运行态数据库，代码未直接引用，可按需重建；不应纳入源码版本。
- store/refactor_plan.md：keep
  - 设计记录，便于理解历史重构意图。
- store/assistant/picks/*.json：move-out
  - 运行产物，无调用链依赖，也非测试夹具。
- store/assistant/sessions/*.jsonl：move-out
  - 运行态会话记录，不参与测试；应从仓库剥离。
- store/backtest/*.json：move-out
  - 回测输出，运行态产物；不应长期入库。
- store/cache/**：move-out
  - 磁盘缓存（主题/公告/主线），运行态；代码可自动再生成。
- store/fixtures/bars/*.csv：keep
  - 最小夹具，支持离线/单测（测试中使用 fixture 数据模式）。
- store/recommend/*.json：move-out（部分留样）
  - 运行产物，被服务端/前端读取但可重建；保留 `latest.json` 与一个最近样例 `2026-03-11.json` 作为 contract/夹具，清理其余历史与 *_debug/_sources 文件。
- store/registry/champion.json：keep
  - 推荐系统静态注册数据，文档/后端说明引用。
- store/search/history.db：move-out
  - 搜索历史 SQLite，`src/gp_assistant/search/history_store.py` 会自动建表；无需版本化。
- store/sessions/session.db：move-out
  - 会话 SQLite，`src/gp_assistant/chat/session_store.py` 自动初始化；无需版本化。
- store/snapshots/spot_latest.json：move-out
  - 运行态快照；不需版本化。
- store/universe/universe_symbols.txt：keep
  - `src/gp_assistant/providers/universe_provider.py` 读取，作为最小静态资产保留。

- cache/**（根目录）：move-out
  - 本地 pkl 缓存；运行态，不应入库。

- _tmp_gp/**：delete
  - 临时目录，含重复 registry；无调用链引用。

- EMQuantAPI_Python/**：move-out
  - 第三方安装包与二进制/文档；代码路径无引用，仅在脚本扫描排除列表出现；迁移为外部依赖说明。

- backtest/（根目录）：delete
  - 与 `src/backtest` 重复。测试与 README 通过 `sitecustomize.py` 解析到 `src/backtest`；根目录同名包会造成遮蔽与歧义。

- tests/**：keep
  - 真实被 pytest 使用的测试与 fixtures，应完整保留。

- docs/**：keep（将补充运行态与清理策略说明）

- scripts/**：keep
  - 实用脚本链路（selfcheck/quick_daily_pipeline/scan_secrets 等）。`__pycache__` 清理。

- frontend/**：keep（源码与配置）
  - 删除 `node_modules/` 与 `dist/`（构建产物），保留 `src` 与配置。

- 根目录临时/备份/错误文件：delete
  - tmp_*.txt、*_patch*、*.bak、error.txt、docker-compose.yml.bak、一次性辅助脚本（_patch_agent.py/_dump_compact.py/_run_self_check.py/_search.ps1）。无调用链引用。

- src/gp.egg-info：delete
  - 构建产物，不应入库。

## 理由与影响

- 运行态数据（会话/历史/推荐产物/缓存/快照/本地db）全部降级为运行目录，通过 `.gitignore` 与 `.dockerignore` 排除；必要时保留最小样例与目录初始化逻辑（由 `core.paths` 自动创建）。
- 多重状态目录去重（删除 `_tmp_gp`，唯一真源为 `store/` + `cache/` 运行态约定与 `store/registry` 静态资产）。
- vendored 大包移除（EMQuantAPI_Python），在 README/ops_runbook 说明为外部依赖。
- 前端构建产物与依赖移出仓库，镜像/本地通过安装构建。

以上结论与代码、测试实际引用相符，不影响 API、推荐逻辑或 champion 选择。

