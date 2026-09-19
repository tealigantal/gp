# GP 固定评价刻度修改验收

交付状态：**未应用 patch**，在隔离的 HEAD 副本实现、测试。基线 `239616af683f25fd179cac611db2ece306a10995`。当前仓库的受跟踪文件、契约和生产入口保持原状；原 reports/ 内容保留。未提交、推送、部署、重启或发布计划。

唯一明确的契约冲突：`docs/contracts/CURRENT_CONTRACTS.md:25` 仍要求唯一基础分为 `(N*G + 0.5*n0*A0)/(N*(G+L)+n0*A0)`。本 patch 改为指定固定刻度，故按本次指令暂不应用，未修改契约。

## Patch 中的文件

| 文件 | 必要改动 |
|---|---|
| src/gp_assistant/decision_engine/scoring.py | 指定 z 与 score 两行计算；评分身份 v7 |
| configs/daily_scoring.json | 仅 revision，与评分身份一致，已有 digest 随之变化 |
| src/gp_assistant/application/real_producer.py | 日线 producer revision 5→6 |
| src/gp_assistant/application/lunch_rebalance_producer.py | 午盘 producer revision 3→4，阻止旧午盘直接复用 |
| src/gp_assistant/intraday/lunch_rebalance.py | 已用午盘算法身份 v3→v4，观察逻辑不变 |
| src/gp_assistant/application/conversation_service.py | 固定评价刻度说明，只引用记录分数 |
| tests/contracts/test_fixed_score_scale.py | 新刻度锚点、排序、返回语义、融合、读取和身份验收 |
| tests/contracts/test_smoothed_scoring.py | 原数学夹具转换验证、v6 历史读取与版本缓存验收 |
| tests/contracts/test_lunch_rebalance.py | 明确使用旧 v6 基础计划验证拒绝复用 |
| frontend/src/App.test.tsx | 展示只乘 100，覆盖新刻度及公告后的分数 |

## 刻度与只读对照

使用指定 `z=n*(g-l)/denominator` 和 `score=0.5+0.54*z/(0.08+abs(z))`。保留缩放、参数检查、净收益及风险事实；z 不持久化。A0=0.03997941946323374、n0=20、成本及全部参考池元数据不变，未重新冻结。

原 v6 的 40、45、50、55、60 分分别映射为约 11.428571、20、50、80、88.571429 分。总分是固定刻度下的相对评价，不是上涨概率或收益保证。

本机两份完整 G/L/N/A0/n0 计划，各 198 个候选，均为 2026-09-18 证据；这是同一天的两份计划，不是 396 个独立样本。按每份计划所有记录重新调用目标函数；原 v6 参照只在 tests 中。基础排序及同分按代码排序全部一致，Top-30、零公告 Top-3 不变。

| 百分制 | 最低 | P10 | P25 | 中位数 | P75 | P90 | 最高 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 原 v6 | 33.41 | 40.41 | 42.73 | 45.91 | 49.65 | 52.83 | 55.62 |
| 新刻度 | 6.49 | 11.90 | 15.16 | 22.71 | 45.71 | 72.38 | 81.55 |

基础前三：000993 55.6208→81.5487；002428 55.3480→80.8934；002851 55.1768→80.4623。完整逐项 G/L/N/A0/n0 和对照值见 `readonly-comparison.json`。未推导缺失案例，也未重写历史记录。

## 实际验收

- 隔离副本完整后端契约测试：199 passed。首次新增午盘测试使用了不足 30 个测试候选，被现有完整性校验拒绝；补齐真实要求的 30 个测试候选后通过，未改动或弱化生产约束。
- 前端：24 passed；lint、typecheck、build 通过。
- `compileall -q src tests`、`selection_engine.self_check_contract`、`contracts.manifest --check`、`contracts.check_retired` 全部通过。机器契约检查通过不代表上述文档数学冲突已消除。
- Serenity 精确批次规则、仅一次叠加与截断、午盘保分、展示只乘 100、LLM 引用原记录分数均通过。非零公告仍在新刻度最多 ±3 分，测试明确覆盖最终名次可能与旧刻度不同。
- 新政策 revision、producer revision、digest 分别阻止旧计划复用；旧午盘身份拒绝复用。历史读取测试通过；生产 83 份历史计划只读加载成功，任务前后计划 ID 与 payload digest 全部一致。
- `git apply --check` 通过；在另一份干净临时副本实际应用 patch，内容与已测试副本一致（Git 换行符归一化后）。当前工作区受跟踪文件 diff 为空。

这些是实现与固定刻度验收，不是收益或胜率提升证据。
