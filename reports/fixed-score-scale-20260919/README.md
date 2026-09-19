# GP 固定评价刻度修改验收

交付状态：**已正式应用到 `codex/newline1` 分支实际源码，尚未部署**。本次应用前工作区干净，基线为 `34079723e394e99846225fa442e614a36153b614`。对仓库原 patch 执行 `git apply --check` 成功后应用，并完成统一评分文案及契约文字修正。`fixed-score-scale.unapplied.patch` 作为原始补丁存档保留，文件名不代表当前源码状态。

本次已按明确授权同步 `docs/contracts/CURRENT_CONTRACTS.md` 的 v7 公式、固定评价刻度含义和日线/午盘版本引用，原数学条款冲突已消除。数据结构、schema manifest、API、数据库结构及发布关系未变；未新增兼容层或旧公式回退。未提交、推送、部署、重启服务或生成生产计划。

## 已应用和修改的文件

| 文件 | 必要改动 |
|---|---|
| src/gp_assistant/decision_engine/scoring.py | 指定 z 与 score 两行计算；评分身份 v7 |
| configs/daily_scoring.json | 仅 revision，与评分身份一致，已有 digest 随之变化 |
| src/gp_assistant/application/real_producer.py | 日线 producer revision 5→6 |
| src/gp_assistant/application/lunch_rebalance_producer.py | 午盘 producer revision 3→4，阻止旧午盘直接复用 |
| src/gp_assistant/intraday/lunch_rebalance.py | 已用午盘算法身份 v3→v4，观察逻辑不变 |
| src/gp_assistant/application/conversation_service.py | 新旧计划使用统一相对评价说明，移除 core_score 存在性判断，仅引用各自记录分数 |
| tests/contracts/test_fixed_score_scale.py | 新刻度、排序、融合和身份验收；新增 v6/v7 原分叙述与两份完整计划各198项回归 |
| tests/contracts/test_smoothed_scoring.py | 原数学夹具转换验证、v6 历史读取与版本缓存验收 |
| tests/contracts/test_lunch_rebalance.py | 明确使用旧 v6 基础计划验证拒绝复用 |
| frontend/src/App.test.tsx | 展示只乘 100，覆盖新刻度及公告后的分数 |
| docs/contracts/CURRENT_CONTRACTS.md | 仅同步评分公式、含义、版本与公告最终名次边界 |
| reports/fixed-score-scale-20260919/README.md | 记录本次实际源码应用和验收结果 |

## 刻度与只读对照

使用指定 `z=n*(g-l)/denominator` 和 `score=0.5+0.54*z/(0.08+abs(z))`。保留缩放、参数检查、净收益及风险事实；z 不持久化。A0=0.03997941946323374、n0=20、成本及全部参考池元数据不变，未重新冻结。

原 v6 的 40、45、50、55、60 分分别映射为约 11.428571、20、50、80、88.571429 分。统一叙述为：“总分为本计划生成时记录的相对评价，不是上涨概率或收益保证；不同评分政策的分数不能直接跨版本比较。”

本机两份完整 G/L/N/A0/n0 计划，各 198 个候选，均为 2026-09-18 证据；这是同一天的两份计划，不是 396 个独立样本。本次直接读取原 `readonly-comparison.json`，使用当前仓库 `src/gp_assistant/decision_engine/scoring.py` 的真实目标函数逐项重算；原 v6 参照只在 tests 中。基础排序及同分按代码排序全部一致，Top-30、零公告 Top-3 不变。

| 百分制 | 最低 | P10 | P25 | 中位数 | P75 | P90 | 最高 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 原 v6 | 33.41 | 40.41 | 42.73 | 45.91 | 49.65 | 52.83 | 55.62 |
| 新刻度 | 6.49 | 11.90 | 15.16 | 22.71 | 45.71 | 72.38 | 81.55 |

基础前三：000993 55.620819→81.548689；002428 55.347964→80.893365；002851 55.176754→80.462265。完整逐项 G/L/N/A0/n0 和对照值见 `readonly-comparison.json`。未推导缺失案例，也未重写历史记录。

## 本次实际源码验收

以下命令均在当前 GP 仓库运行，未引用上次隔离副本结果代替本次验收。

- 目标测试：`test_smoothed_scoring.py`、`test_fixed_score_scale.py`、`test_lunch_rebalance.py`、`test_serenity_fixed_weight.py` 共 **102 passed**。
- 完整后端回归：`python -m pytest -q -rA` 全部通过，现有 pytest.ini 默认范围共 **202 项**；网络/LLM integration 不属于本次运行范围。
- `python -m compileall -q src tests` 通过。
- `PYTHONPATH=src` 下的 `python -m gp_assistant.selection_engine.self_check_contract`、`python -m gp_assistant.contracts.manifest --check`、`python -m gp_assistant.contracts.check_retired` 全部通过。
- 前端重新 `npm ci` 后，`npm run lint`、`npm run typecheck`、`npm test -- --run`（**24 passed**）和 `npm run build` 全部通过。
- Serenity 精确完整批次、仅一次叠加及截断、午盘保分和零技术评分贡献、前端仅乘100均通过；非零公告仍按新刻度最多±3分，最终名次可能变化的测试通过。
- 新政策、producer revision、digest 防止旧计划复用，旧午盘身份拒绝复用；历史读取无重算或回写的测试通过。v6 的55分与 v7 的80分分别被原样引用，均有 core_score；统一文案无版本推断，测试中禁止调用评分函数验证读取和叙述没有重算。
- 两份完整计划各198项测试通过：全量基础排序及代码同分处理、Top-30与零公告Top-3保持一致；原始对照JSON和原patch均未修改。配置与应用前相比仅 revision 不同，A0、n0、成本、冻结时间和全部参考元数据保持原值。
- `git diff --check` 通过；实际源码和文档修改可见于 git diff。`src/gp_assistant/contracts/`、前端契约定义及 registry 未改动。

首轮目标测试为101通过、1失败：新增 v6 叙述测试将已舍入的55.0与二进制 `0.55*100` 严格比较，产生浮点尾差。改用明确的1e-12绝对容差，同时保留对既有四位小数展示结果的精确断言后，目标与全量回归通过；没有改公式或原始预期数据。辅助文件核验曾因 Windows CRLF 与 Git LF 的字节差异误报，按 Git 换行归一化复核一致，原文件未改写。

这些是实现与固定刻度验收，不是收益或胜率提升证据。两份计划来自同一证据日，不视为独立历史回测；本次未部署、未生成生产计划，也未执行真实网络/LLM端到端验证。
