## gp_assistant 本地启动与使用指南

这份文档聚焦两件事：
- 本地一键启动/更新 (Docker)
- 服务/数据位置与常见问题（说人话）

---

### 快速启动 (Docker)
- 一键启动或更新：`docker compose up -d --build`
- 只启动后端：`docker compose up -d gp`

打开页面/接口：
- 前端：`http://localhost:8080`
- 健康检查：`curl http://127.0.0.1:8000/api/health`
- 推荐接口：`POST http://127.0.0.1:8000/api/recommend`

---

### 服务与端口
- gp（后端）：`http://localhost:8000`
- web（前端）：`http://localhost:8080`
- llm-proxy（可选）：宿主 `18080` -> 容器 `8080`
  - 后端默认 `LLM_BASE_URL=http://llm-proxy:8080/v1`；如需直连厂商，请在 `.env` 覆盖 `LLM_BASE_URL` 与 `LLM_API_KEY`。

---

### 镜像与网络（官方镜像）
- 基础镜像：`python:3.11-slim`、`node:18-alpine`、`nginx:1.25-alpine`
- 可在 `.env` 覆盖：`BASE_PY_IMAGE` / `BASE_NODE_IMAGE` / `BASE_NGINX_IMAGE`
- 构建拉取失败（EOF）排查：
  - 确认 Docker Desktop 代理走你的 VPN（Settings -> Proxies 使用系统代理）
  - 执行 `docker login` 降低限流
  - 先手动 `docker pull node:18-alpine nginx:1.25-alpine python:3.11-slim` 再构建

---

### 数据挂载与 Universe
- 挂载目录（容器内 -> 宿主机）：
  - `/app/store` -> `./store`
  - `/app/cache` -> `./cache`
  - `/app/configs` -> `./configs`
- 会话数据库：`store/sessions/session.db`
- Universe 文件：`store/universe/universe_symbols.(txt|json)`
- 默认可交易阈值（可在 `.env` 覆盖）：
  - `GP_TRADEABLE_MIN_UNIVERSE=50`
  - `GP_TRADEABLE_MIN_CANDIDATES=20`

---

### 荐股逻辑（说人话）
目标：在“当下市场环境允许出手”的前提下，从“流动性好、风险可控”的股票里，挑出少量更有胜算的机会，并给出买点和风控要点。

1) 数据来源
- 行情来自 AkShare，多路来源（Sina/东方财富/腾讯）按优先级回退，只用真实数据；
- 以日线为主（K 线、成交量、成交额），必要时看当日快照判断是否可交易。

2) 先看“大环境”能不能做（环境评估）
- 看四件事：
  - 热度/扩散：涨跌对比、行业/概念扩散度；
  - 量能：成交额是否回到常态；
  - 波动/噪声：情绪过山车时会降权；
  - 主线：是否有 1–2 条明确的主线行业/概念；
- 给出“可以做/轻仓/观望”提示，避免硬推荐。

3) 过滤明显不合格（候选池）
- 流动性与成交额达标（`amount_5d_avg` ≥ 门槛）；
- 非新股、非 ST；
- 价格在合理区间；
- 优先围绕当日“主线行业/概念”；
- 得到“动态候选池”（几百只以内）。

4) 用看得懂的信号打分（为什么选它）
- 突破/回踩：MA20 回踩企稳、前高突破回踩不破；
- 收缩后释放：NR7/Squeeze 等“长时间收窄后放量突破”；
- 动量极值：RSI2 强势回落后的二次上攻；
- 缺口处理：回补缺口后的方向选择；
- 筹码/支撑：靠近密集成交区或均线带的低风险入场位；
- 假突破反转：类似 Turtle Soup 的快速反包；
- 多信号综合打分：考虑强度、量价配合、与支撑/阻力距离。

5) 风险与主题的修正（更稳更贴合）
- 风险扣分：剧烈波动、连续一字炸板、异常缺口等；
- 主题加分：更贴近“当日主线”的行业/概念；
- 去重与分散：
  - 同行业最多 N 只，避免“一篮子鸡蛋”；
  - 多信号命中的候选保留评分最高的一只；
  - 去掉高度相似/相关性过高的票。

6) 最终产出（少而精 + 可执行）
- TopK（默认 3 只）+ 行业分散约束；
- 每只股票包含：命中信号、参考买点区间、止损/止盈、行业/概念标签、可选自然语言说明（有 LLM 时更顺滑）。

7) 边界与声明
- 基于公开行情的筛选与提醒，不是投资建议；
- 以日线与简单规则为主；极端行情/停牌/延迟会降低可用性；
- 当天条件不足时会明确提示“观望或降权”。

---

### 常用操作
- 仅更新前端：`docker compose build web && docker compose up -d web`
- 仅更新后端：`docker compose build gp && docker compose up -d gp`

---

### 自检与回归（可选）
```
python -m compileall src
python -m pytest -q \
  tests/test_regress_theme_and_bands.py \
  tests/test_contract_event_and_history.py \
  tests/test_theme_concept_fallback_no_snapshot.py \
  tests/test_theme_pool_snapshot_paths.py \
  tests/test_theme_pool_impl_nan_and_scale.py \
  tests/test_strict_no_pseudo_output.py
PYTHONPATH=src python -m gp_assistant.recommend.self_check_contract
```

---

### 严格输出与数据契约（摘要）
- 严格模式（`GP_STRICT_OUTPUT=1`）：缺失数字字段输出 `null`，不以 `0.0` 兜底；不伪造主线线索。
- 推荐卡片 `meta` 包含：
  - `schema_version: 1`
  - `data_status`: `{ snapshot: { ok, source, rows, elapsed_sec, cache, as_of_ts, error }, themes: { ok, source, attempted, error, as_of_ts }, daily: { ok, symbols_ok, symbols_fail, error_summary } }`
  - `mover_hints`: 来自快照的强势线索；`themes` 仅包含行业/概念。

---

如需更多偏好（比如加入日内、更严格过滤、主题识别、回测等），告诉我即可继续打磨。
