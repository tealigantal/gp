# 2026-09-28 尾盘链路容器部署与缺陷复核

用户明确授权重构容器和分析潜在错误。北京时间01:45完成 `gp`、`gp-worker`、`web` 重建替换，保留数据卷和用户已有改动，未提交或推送。API和worker使用同一新镜像，未操作其他容器、Docker Desktop或BuildKit历史。

## 已修复的真实缺陷

1. **首轮指代可能绑定错误计划。** 页面展示P1、后台切换P2后，旧请求没有携带可见发布物，首次“第一只”会绑定P2。当前POST `/api/chat`明确携带publication_id（没有展示计划则显式null）；新会话绑定该真实版本，已存在会话保持原绑定，网络重试保留原ID。前后端、服务契约和回归同步更新。
2. **正式建议可被自由文本覆盖。** 工具结果引用正确时，模型仍能在answer.text追加相反建议。入场respond现限定text为空，并校验拒绝非空；结论、理由、变化及带时间的历史记录来自正式评估。未增加中文禁词或备用回答。
3. **新确认停牌不能及时撤销缓存买入状态。** 旧代码只在重新采集时检查停牌，缓存有效期内页面和聊天可能继续显示可以买。读取正式结果时现在检查当日已验证停牌事实，立即标记当前不可用，保留旧评估作为历史，不重新下载或让模型猜停牌。

另删除已无生产调用方的盘中开关、冷却/重试配置及runtime/dialogue_text.py，避免配置看似生效却不控制新链路。保留午盘实际使用的GP_INTRADAY_FETCH_BUDGET_SEC及用户.env文件。

## 验证与部署

- 主机后端255 passed，7 integration deselected；镜像内相同255项通过。
- 前端lint、typecheck、26项测试与build通过；Python编译、契约manifest、retired检查、Compose配置及diff检查通过。
- 新增首轮P1/P2绑定、非法补充建议拒绝、新停牌使缓存失效回归；前端断网重试测试断言publication_id。
- 首次容器测试有2项失败，原因是测试依赖的既有reports样本未挂载；补充只读挂载后通过，未修改断言。新增绑定测试的初始夹具被计划ID完整性检查拒绝，改为通过PlanService生成真实规范测试计划后通过。最终镜像测试仅有Starlette测试客户端依赖弃用提示，不影响生产HTTP或断言。
- 使用新镜像隔离数据库执行7轮真实模型问题，全部成功，见 [final-image-probe.json](final-image-probe.json)。继续使用当前DeepSeek模型与凭据，无模型切换。两只股票003006/603268和指数000300各实际取得240根新浪分钟行情，耗时约214/187/200毫秒，最新证据仍是9月24日15:00；没有把凌晨请求时间冒充行情时间。
- 执行 `docker compose build gp web`，随后 `docker compose up -d --no-build --force-recreate gp gp-worker web`。API及web健康，worker正常运行，详情见 [containers.json](containers.json)。旧镜像留存标签gp-backend:before-tail-20260928和gp-web:before-tail-20260928，仅作为部署恢复工件，不构成生产数据/模型回退路径。
- API与worker各203个Python文件逐一SHA-256比对，均与工作区一致，无遗漏文件。backend镜像为 `sha256:2712c47e6789cbe1eca374e69771ed459684657aa5cf8e15d1c50cda7dd38833`；web镜像为 `sha256:941a7f2d284cdfbc923c913a259c4ddbc35fa6de49f83bd2bdebbbd66ba092d9`。

## 真实生产验收

替换前的真实聊天仍返回人工看图清单；替换后经8080 nginx调用真实聊天，第一只003006、第二只603268及已有持仓追问正确绑定。开盘前明确返回未完成当前入场确认，变化追问明确没有此前正式评估，未伪造走弱或买入许可。页面实际发送“第一只现在能买吗？”得到同样结果；截图见 [page.png](page.png)，浏览器console/errors为空。

当前计划仍为plan_a175a3d68bb867852994fe2a，交易日9月28日，日K证据9月24日，目标覆盖3052/3052，进入评分199、入选3。部署前后91份计划、5262份发布物和5176份RuntimeObservation的逐条payload哈希全部未变，数据卷未替换或清空。两轮worker心跳正常，无database is locked/readonly database错误；原有成熟记忆和Serenity状态仍正常。证据见 [before.json](before.json)、[after.json](after.json)、[worker.log](worker.log)。

## 尚未证明的事项

- 当前为凌晨，仍没有14:40／14:50现场发布、未闭合线更新行为、新鲜度与端到端延迟记录。现有一根五分钟发布时间差是实现边界，不是已验证的供应商SLA。
- 原有8月21日历史回补仍为3045/3046，缺一只；不是本次部署新增故障，也没有影响当前9月28日计划的完整覆盖。未扩大本任务去重做历史修复。
- 本次证明代码、镜像、实际会话与页面接通，不能据此宣称盈利提高或盘中现场验收已完成。
