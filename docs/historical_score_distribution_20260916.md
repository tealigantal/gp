# 历史推荐评分集中度分析（2026-09-16）

## 结论与范围
入选股票集中在60–65分是实际数据现象，主要来自加权公式、近似常数的置信度及Top-N上尾筛选；不是前端固定分数。综合分不是胜率。此次只分析，不修改任何分数、选股公式或历史计划，也没有执行收益回测。

## 数据口径
只读查询运行容器 /app/store/agent.db：74个唯一计划、4572个发布快照。65个非空日线计划覆盖2026-07-23至2026-09-14。每个交易日保留最后一个日线计划，避免同日Serenity版本和分钟发布重复计数，得到32个计划、6198个实际评分候选、96次入选。另3个午盘计划公式不同，最高入选分82.08，单独排除；6个计划无候选。

实际评分池每次先按成交金额取前200；6198不是全市场全部标的评分。最新计划的合格全集3046，实际评分200。

| 样本 | 最低 | 最高 | 均值 | 中位数 |
|---|---:|---:|---:|---:|
| 实际评分候选6198条 | 25.60 | 65.85 | 50.03 | 50.89 |
| 入选96条 | 58.83 | 65.85 | 62.45 | 62.36 |

入选标准差1.43；88/96（91.7%）在60–65。每日第一、第二名差距中位数0.7823分，18/32天不足1分；第一至第三名差距中位数1.4006分。

## 公式为什么产生62分
src/gp_assistant/application/real_producer.py 的日线公式（换算百分制）：

`50×上涨概率 + 30×执行质量 + 20×置信度 − 20×回撤概率 + Serenity贡献`

96次入选的平均分量：

| 分量 | 平均贡献（分） |
|---|---:|
| 上涨概率 | +27.8604 |
| 执行质量 | +22.0390 |
| 置信度 | +18.5612 |
| 回撤惩罚 | −6.1049 |
| Serenity | +0.0938 |
| 总计 | 62.4495 |

执行质量未单独持久化；这一项按当前公式从保存的综合分、概率、风险和Serenity分量反推，并非读取到的独立原始指标。

probability_engine/engine.py 固定先验强度20；检索通常取80个邻居。入选有效样本量79.303–79.964、均值79.825。置信度公式为 `0.65×有效样本量/80 + 0.35×平均相似度`，实际均值0.9281（范围0.8595–0.9716），因此形成近似固定加分。概率也被先验收缩。

risk_engine/engine.py 的执行质量又包含20%置信度；展开综合分后，置信度总权重为26分。重复计入是代码事实，但去掉是否改善实际收益需样本外验证。

另外：按成交额Top-200→基础Top-30→入选Top-3压缩了可见分差；96次入选只有3次Serenity非零。日线生成固定市场状态C、行业强度默认0.5进一步减少可用特征差异，但没有消融实验，不能量化其因果贡献。

## 排序语义问题
risk_engine/engine.py 算出的收益相关ranking_score并非最终排序权威。decision_engine/adaptive.py只按adaptive_score排序并以0.5为入选门槛，没有消费ranking_score或rankable。历史96次入选有2次ranking_score为0：2026-07-27的000858（61.2427分、上涨估计44.7156%），2026-09-01的600030（61.7033分、上涨估计48.0847%）。

最新9月14日日线计划plan_d2e9e8735796f32122a1a691：

| 股票 | 综合分 | 上涨概率估计 | ranking_score |
|---|---:|---:|---:|
| 600519 | 61.8355 | 48.1299% | 0.0007872 |
| 601138 | 61.3477 | 50.5889% | 0.0011719 |
| 601168 | 61.2996 | 53.1794% | 0.0018617 |

这三只的综合排序与概率/收益排序值方向相反，说明综合分不应解释成胜率或预期收益。frontend/src/App.tsx只是toFixed(3)，没有把分数写成0.6。

## 后续决策依据
应先做严格as-of、T+5成熟、样本外按分桶收益/胜率/回撤与交易成本验证，比较Top1–Top3差异、去重置信度的消融、收益风险门槛及真实市场/行业特征。然后确定唯一排序权威。不能仅用min-max把分数拉成0–100来声称区分能力提升，也不能由本次分布诊断推断模型一定无效或修改后一定更盈利。

## 复现

运行 `python scripts/analyze_score_distribution.py store/agent.db`，只读事务内采样。此次结果保存在未跟踪运行产物 `results/storage-recovery-20260916/score-distribution.json`，包含计划ID和载荷哈希。独立复算确认32天、96次入选、均分62.449451、88次落在60–65、第一第二名中位差0.782284。

## 进一步核实：案例池未持续更新

只读查询当前 `store/events/market_memory.db`：36190条事件，最新信号日2026-07-14，最新结果可用日2026-07-21，最后创建时间2026-07-22。按生产SQL分别以2026-07-22和2026-09-11为as-of取最近4000条成熟事件，两次事件ID集合SHA256均为 `05da23f9a2caefff01128546d26fbd8cd7dd6b231c7ebb346385aab27ddd1629`，覆盖203只股票、信号日2026-06-15至07-14，全部market_regime=C。

因此当前库在两个日期得到完全相同的检索池，实际没有吸收7月下旬以来的新成熟案例。这是学习样本更新缺口，与9月14日history.db故障发生时间不同；恢复日线库不会自动解决它。固定案例池、固定市场状态和相近检索置信度共同限制了模型适应性，但其对分差和收益的量化影响仍需消融回测。生产日线函数使用max_history=0，未在生成计划时写入历史事件，不能把注释所说的离线维护当作已经正常运行的证据。

复核命令增加 `--memory-database store/events/market_memory.db` 可输出上述日期与事件池哈希。

## 2026-09-17 corrective ablation

The pre-deployment backup adds one session:33 daily sessions,6400 evaluated candidates and99 selections. `scripts/compare_score_policy.py` holds the old probability/confidence/downside estimates fixed, algebraically recovers execution quality and positive expected return, removes duplicated confidence, and applies the shared positive-net-edge gate. Because finalist membership may change, Serenity is zero for the comparison. Selected mean62.5710→61.0039, standard deviation1.4230→1.6018; eight old selections fail the modeled30bps cost gate. This deliberately does not stretch scores. Concentration near60 can remain because the probability estimator and bounded weighted formula are unchanged. This is a scoring ablation, not a reconstructed new-memory backtest, calibration study or profitability claim. Saved report:results/causal-repair-20260917/frozen-score-comparison.json.
