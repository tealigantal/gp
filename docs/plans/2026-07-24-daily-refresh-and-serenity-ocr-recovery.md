# 日线刷新与 Serenity OCR 恢复 ExecPlan

## Purpose / Big Picture

修复日线来源返回旧日期时被误算为刷新成功的问题，并为真正相关、结构正常但没有文本层的官方公告提供资源受限的中文 OCR。推荐只有在目标日应有日 K 的主板全集达到 100% 精确日期覆盖时才可用；Serenity 仍只有完整批次 3% 和其他状态 0% 两种结果。公开 HTTP、ContractModel 和 `contract_kernel.v1` 数据库结构不变，当前运行容器不在本计划内替换。

## Progress

- [x] 2026-07-24：确认 live 故障同时包含目标日覆盖误判、同一失败股票反复全量刷新，以及扫描 PDF 无文本层。
- [x] 2026-07-24：确定同日新鲜 spot 零交易值是唯一允许排除“目标日不应有 bar”股票的证据，旧日/陈旧/缺字段证据全部 fail closed。
- [x] 2026-07-24：确定采用 Tesseract `chi_sim+eng`、PDFium 渲染和现有 `pypdf` 快路径，所有 OCR 仍在 Serenity 子进程内运行。
- [x] 2026-07-24：实现日线覆盖、停牌排除和 worker 完成后计时。
- [x] 2026-07-24：实现标题预筛选、受限 OCR、解析审计元数据和 Serenity v2 身份。
- [x] 2026-07-24：完成单元/合同测试、完整默认回归、镜像构建、真实合成扫描件探针和独立审查。
- [x] 2026-07-24：提交并推送实现，更新草稿 PR #10，继续等待人工审核且不部署。
- [x] 2026-07-24：经用户追加授权，从提交 `48e7cb3` 重建并精确替换 `gp`/`gp-worker`，保留旧镜像回滚标签且未重建 `web`。
- [x] 修复部署后暴露的停牌识别缓存来源缺口：旧 pickle 缺 sidecar 时强制实时重拉，缓存新鲜度只认可信采集时间，失败回退不进入新鲜内存缓存。
- [ ] 从新提交重建并确认 `002036` 由同日可信零交易快照排除，精确覆盖恢复为完整且新计划可发布。

## Surprises & Discoveries

- `DailyEvidenceRefresher` 当前只要 DataFrame 非空就增加 `received`，不检查是否包含所需目标日。
- `RealRecommendationProducer` 当前以最常见历史日期作为覆盖日并允许 `0.999`，刷新后递归获取第二份 spot 快照。
- Worker 用扫描开始前的时间记录 `last_plan_at`，扫描耗时达到间隔时会立即重跑。
- 当前阻塞的扫描 PDF 由宽泛的“修订”标题匹配进入，但其法律意见标题不能生成方向性 Serenity 事实。
- Docker 官方 Debian/PyPI 路径在验证时分别发生 502 和大文件中断；系统与 Python 安装层已拆分、增加重试，并用可配置镜像参数完成一次性镜像验证，不改变运行服务。
- 真实 Tesseract 探针会在中文词组内插入空格；主题和数字签名因此在匹配前统一规范化空白，并增加回归测试。二次识别确实会拒绝不一致数字，清晰单百分比扫描件可稳定通过。
- 部署后真实全市场刷新只请求缺失的 `002036`，三条来源均未返回目标日，最终精确覆盖为 `3043/3044`，正确保持 pending；但不可用计划因证据日期回退被 publication CAS 拒绝，旧错误语义下生成的 current recommendation 没有自动失效。
- 首轮 Serenity v2 收集提交 30 只、11 份文本层公告的完整批次；下一轮 CNINFO 504 时 worker 仅降级而未重启。运行容器内合成扫描 PDF 以 Tesseract 5.3.0、93 中位置信度通过。
- `ak_spot_snapshot.pkl` 是旧版本遗留文件且缺少配套 sidecar；单看文件 mtime 既不能证明交易日，也可能被复制或 touch 刷新。可信缓存因此绑定内容摘要、受支持来源、带时区采集时间和会话日期，并按采集时间计算 TTL。
- 磁盘读取原先会刷新进程内缓存时间：失败回退可能被洗白，接近 TTL 的可信快照也可能被延寿。现在任何磁盘结果都不进入内存缓存，每次均按 sidecar 的原始采集时间重新判断。

## Decision Log

- 2026-07-24：原始主板全集计数不因停牌缩小；完整性分母只排除与目标日一致的新鲜 spot 明确证明无交易的股票。
- 2026-07-24：`complete` 要求目标可交易全集 100% 存在精确目标日，不用非空返回或多数日期代替。
- 2026-07-24：OCR 只处理结构有效且 `pypdf` 零有效文本的相关文档；损坏、加密、截断和超限文档直接整批 0%。
- 2026-07-24：午盘继续继承基础计划已经绑定的 Serenity 0%/3%，不吸收午盘前晚到的公告批次。
- 2026-07-24：停牌证据缓存采用 fail-closed 来源证明；缺失、摘要不符、未知来源、无时区、日期不符、未来或超 TTL 的 sidecar 均不得走新鲜缓存快路径。

## Outcomes & Retrospective

主体实现已部署到本地 `gp`/`gp-worker`，镜像提交标签和 OCR 运行依赖已核对。真实 LLM 推荐说明、Serenity v2 批次、运行容器 OCR、数据库只读完整性和 worker 不连续重扫均通过。部署暴露的最后缺口不是数据库或 publication 契约，而是旧 spot pickle 缺少可信采集日期，导致真实停牌未进入排除集；最小缓存来源修复已通过 52 项默认测试，等待新镜像真实验证后完成本计划。

## Context and Orientation

日线生产位于 `src/gp_assistant/application/real_producer.py`，增量写入位于 `src/gp_assistant/application/daily_refresh.py`，worker 调度位于 `src/gp_assistant/cli.py`。Serenity 标题、采集和批次提交位于 `src/gp_assistant/serenity/service.py`，PDF 解析位于 `src/gp_assistant/serenity/parser.py`。两个 Compose 后端服务共享同一 Dockerfile 和镜像。

## Plan of Work

1. 建立目标日、同日 spot 会话和明确零交易行的纯计算边界；只刷新缺少精确目标日的应交易股票。
2. 将刷新统计拆为非空返回和目标日命中，刷新后从存储重读并以 100% 精确覆盖判定。
3. 改为从刷新完成后的 monotonic 时间计算下一次计划刷新。
4. 收紧 Serenity 标题事件族，加入有页数、像素、DPI、字符和超时上限的 OCR 子进程。
5. 提升 Serenity 语义版本，记录解析审计元数据并保持整批 0%/3% 原子门禁。

## Concrete Steps

- 只使用 `apply_patch` 修改跟踪文件，不暂存 `store/`、`cache/` 或 `results/`。
- 新增单元测试覆盖旧日期非空响应、同日停牌证据、恢复交易、陈旧快照、100% 覆盖和调度节流。
- 新增合成扫描 PDF 测试和标题分类测试，不把第三方 PDF 加入仓库。
- 构建后端镜像并在一次性容器检查 Tesseract、`chi_sim`、`eng`；不重建运行服务。

## Validation and Acceptance

- `python -m pytest -q`、`python -m compileall -q src tests`、合同/退役检查、`docker compose config --quiet` 和 `git diff --check` 全部通过。
- 非空旧日期响应保持 pending；同日明确停牌不阻塞；任何应交易股票缺目标日仍 fail closed。
- 一个相关 PDF 的 OCR、身份、主题、置信度或二次数字校验失败时，Top-30 全部权重为 0%。
- SQLite schema metadata、公开模型和 HTTP 字段集合没有变化，午盘记录仍追加且继承基础 Serenity 绑定。

## Idempotence and Recovery

刷新只追加/更新按日期标识的历史行，相同目标日重试幂等。Serenity 文档版本和批次继续按内容摘要追加，v1 记录只读保留。回滚代码即可恢复旧行为，不需要数据库降级；OCR 不可用时自然回到整批 0%。

## Artifacts and Notes

- 架构决策：`docs/adr/0012-daily-coverage-and-serenity-ocr.md`
- 午盘计划：`docs/plans/2026-07-24-lunch-five-minute-rerank.md`
- 当前分支：`agent/lunch-five-minute-rerank`，草稿 PR #10。

## Interfaces and Dependencies

- 公开接口和 SQL schema 不变；只增加内部刷新统计、spot 审计元数据和 Serenity 文档 JSON 元数据。
- Python 依赖固定为 `pypdfium2==5.12.1`、`pytesseract==0.3.13`、`Pillow==12.3.0`；镜像安装 Tesseract 5 及简体中文/英文语言包。
