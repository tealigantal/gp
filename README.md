# gp 仓库（单入口 Agent + Provider 可插拔 + AkShare 回退）

本仓库已重构为“单入口、最小可用”的形态：只保留一个对外 CLI 入口，Agent 作为唯一编排层，所有功能都以工具（tools）形式接入；数据源支持可插拔 Provider，默认使用 AkShare，在没有官方凭证时自动回退且不影响运行。

重要：Docker 与 docker-compose 的运行方式得到保留，仅将启动命令切换为新的单入口。

## 项目总览
- 唯一入口：`python -m gp_assistant`
- Agent 职责：解析 → 路由 → 执行工具 → 组织输出（Agent 不直接 import 业务细节）
- Provider：
  - `akshare`（默认可用、无凭证）
  - `official`（占位实现；可从环境读取凭证，缺失时不影响运行）

## 目录结构（核心）
```
src/gp_assistant/
  __main__.py            # 支持 python -m gp_assistant
  cli.py                 # 唯一 CLI 入口
  agent/
    agent.py             # 编排：解析 → 路由 → 执行 → 输出
    state.py             # 会话/运行态（尽量小）
    router.py            # 规则路由（识别 data/pick/backtest/help）
  tools/
    registry.py          # 工具注册表
    market_data.py       # 行情/基础数据（内部调用 provider）
    universe.py          # 选股池构建
    signals.py           # 指标/信号（占位）
    rank.py              # 排序/打分（占位）
    backtest.py          # 回测（占位）
    explain.py           # 解释（可选占位）
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
```

保留根目录：`Dockerfile`、`docker-compose.yml`、`configs/`、`store/`、`cache/`、`data/`、`results/`、`universe/`、`pyproject.toml`、`requirements.txt` 等。

## 安装与运行
1) 安装依赖：
```
pip install -r requirements.txt
```

2) 本地运行（两种方式二选一）
- 方式 A（推荐）：安装包（开发模式）
```
pip install -e .
python -m gp_assistant pick
```
- 方式 B：不安装，临时设置模块路径
  - PowerShell（Windows）：
    ```
    $env:PYTHONPATH='src'
    python -m gp_assistant pick
    ```
  - Bash（Linux/macOS）：
    ```
    PYTHONPATH=src python -m gp_assistant pick
    ```

## CLI 用法
- 顶层：`python -m gp_assistant <子命令>`
- 子命令：
  - `chat`：文本路由模式（示例：`data 000001 start=2024-01-01`）
  - `data --symbol 000001 [--start YYYY-MM-DD --end YYYY-MM-DD]`：拉取行情
  - `pick`：生成候选（即使为空也结构化输出）
  - `backtest --strategy NAME`：回测占位

示例：
```
python -m gp_assistant data --symbol 000001
python -m gp_assistant pick
python -m gp_assistant chat "data 000001 start=2024-01-01 end=2024-02-01"
```

## Provider 配置与回退
- 环境变量：
  - `DATA_PROVIDER`：`akshare`（默认）或 `official`
  - `OFFICIAL_API_KEY`：官方数据源凭证（占位字段）

选择/降级规则仅存在于 `providers/factory.py`：
- 选择 `official` 但缺少凭证：不会崩溃，自动降级到 `akshare`，并输出明确提示。
- 健康检查：`provider_health()` 返回 `{selected, name, ok, reason}`（不触网，仅验证导入/配置）。

检查示例：
```
python -c "from src.gp_assistant.providers.factory import provider_health; import json; print(json.dumps(provider_health(), ensure_ascii=False, indent=2))"
```

## Docker/Compose
- Dockerfile 已更新为单入口：
  - `CMD ["python","-m","gp_assistant","chat"]`
- docker-compose：
  - 服务 `gp` 使用命令 `python -m gp_assistant chat`
  - 数据卷映射保持：`data/`、`results/`、`universe/`、`store/`、`cache/`、`configs/`

运行示例：
```
docker compose build gp
docker compose run --rm gp python -m gp_assistant data --symbol 000001
docker compose run --rm gp python -m gp_assistant pick
```

## 快速验证（Smoke Tests）
以下三条命令应返回可读结果（或可读错误），不应出现堆栈信息轰炸：
1) Provider 状态：
```
python -c "from src.gp_assistant.providers.factory import provider_health; import json; print(json.dumps(provider_health(), ensure_ascii=False, indent=2))"
```
2) 数据命令：
```
python -m gp_assistant data --symbol 000001
```
3) 选股命令：
```
python -m gp_assistant pick
```
或直接：
```
python tools/smoke_test.py
```

## 设计约束（必须遵守）
- 仅保留单入口；旧入口脚本已删除。
- Provider 选择/降级仅在 `providers/factory.py`，业务工具通过 `get_provider()` 获取数据。
- 路径统一在 `core/paths.py` 管理，禁止硬编码相对路径拼接。
- 默认参数/模板/策略等统一在 `core/config.py` 集中管理。
- 工具模块禁止直接读取环境变量/YAML，统一由 `config` 或 `factory` 注入。
- 所有异常必须可读，并提示下一步（如“未配置官方凭证，已自动使用 akshare”）。

## 迁移与兼容性
- 下列旧入口脚本已删除：`assistant.py`、`gp.py`、`run.py`、`serve.py`、`backtest.py`、`update.py`、`gpbt.py`
- 统一改用：`python -m gp_assistant ...`
- Docker 运行方式保持，命令已指向新入口。

## 开发提示
- 编译检查：`python -m compileall src`（应返回 0）
- 日志级别：`GP_LOG_LEVEL`（默认 `INFO`）
- 数据/缓存/结果/存储目录：`core/paths.py` 会自动创建（`cache/`、`store/`、`data/`、`results/`、`universe/`、`configs/`）

