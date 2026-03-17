# AGENT.md

## 项目定位
你在维护 `gp`。这是一个面向 A 股机会研究与执行的产品，不是聊天 demo。
目标不是“能说得像分析师”，而是让用户在真实使用中更快做出更好的交易决策，并有机会获得利润。

## 最高优先级原则
1. 交易数字必须来自确定性逻辑，不允许 LLM 自由生成。
2. `PickArtifactV2` 是核心对象；聊天、对比、详情、验证都必须围绕它展开。
3. 推荐必须可执行、可解释、可验证、可复盘。
4. 允许 no-trade day，不能为了显得聪明而硬推低质量机会。
5. 任何会影响收益判断的 bug，优先级高于 UI 与文案。

## 当前阶段 gate
默认假设当前阶段尚未自动放行。任何新一轮开发前，先确认当前 gate 是否通过：

### Phase 2.6 必须通过的门槛
- `import gp_assistant.server.app` 成功
- `/api/recommend_v2`、`/api/compare`、`/api/pick` 可正常导入并通过测试
- `execution_score` 对 actionable item 不得全部饱和到 1.0
- `reward_risk` 对 actionable item 排序必须仍有真实影响
- `smoke_v2_hardening` 不允许再出现 `skipped score check`
- Phase 2.6 关键测试必须进入默认 gate 或 CI

如果以上任一项未通过，先做 Phase 2.6 closeout，不得直接进入 Phase 3。

## 代码修改硬约束
- 不写 git 操作，不输出 git 命令，不做提交。
- 不用 LLM 决定：买点、止损、止盈、RR、actionable、execution_state、score。
- 不破坏 `/api/recommend` 的 V1 兼容。
- 不把 raw exception、内部 note、debug 字段直接暴露给用户。
- 不允许前端自己猜 `actionable` 或 score。
- 不允许“这三只”类请求退化成默认第一只。
- 不允许把旧 bands 冒充“重算结果”。

## 当前架构重点
### 后端
- 主代码目录：`src/gp_assistant/`
- V2 契约：`src/gp_assistant/recommend/contracts.py`
- V2 读写与 fallback：`src/gp_assistant/recommend/artifact_store.py`
- 打分：`src/gp_assistant/recommend/calibration.py`
- 校验：`src/gp_assistant/recommend/validators.py`
- compare / pick：`src/gp_assistant/recommend/compare_service.py`
- refresh：`src/gp_assistant/recommend/refresh_service.py`
- API：`src/gp_assistant/server/app.py`

### 前端
- 主目录：`frontend/src/`
- API client：`frontend/src/api/client.ts`
- V2 类型：`frontend/src/api/types.ts`
- 适配器：`frontend/src/api/adapters.ts`

## 开发顺序约束
### Phase 2.6 closeout
先修基座与 gate：
1. API 导入/接口可用性
2. execution score 语义
3. smoke/pytest/CI gate
4. V2 一致性验证

### Phase 3
只做 validation layer：
1. event study
2. walk-forward summary
3. paper trade lifecycle
4. strategy health
5. evidence block 接入 artifact

### Phase 4
再做工作台前端：
1. Dashboard
2. PickDetail
3. Compare
4. Paperfolio
5. 右侧助手

## 每次交付必须包含
1. 修改文件清单
2. 设计理由
3. 测试命令
4. 测试结果
5. 风险与未完成项

## 测试要求
- 优先写 deterministic tests。
- 如果加了新模块，但默认 CI 不会跑，这次工作不算完成。
- smoke harness 不能依赖“刚好本地 store 里有数据”；必须自带稳定 fixture 或临时样本。

## 决策标准
当你在“继续堆功能”和“先修收益相关基础问题”之间犹豫时，永远先修后者。
