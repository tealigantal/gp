# Assistant 使用说明

- 索引：`python assistant.py index`（README/configs/src 等，不包含 results）
- 对话：`python assistant.py chat`（REPL，基于仓库事实回答）
- 快览：`python assistant.py inspect`（最近一次 `run_*` 的 compare_strategies 摘要）

受控动作：仅允许 `python gpbt.py` 与 `python gp.py` 的白名单子命令（见 `configs/assistant.yaml`）。禁止任意 shell。

会话回放：每次对话日志落盘至 `store/assistant/sessions/session_*.jsonl`，记录用户输入、模型输出、工具调用参数和返回摘要、耗时。

注意：助手不会改变既有 gpbt 产物目录结构（`results/run_*/compare_strategies.csv`、`doctor_report.json` 等保持不变）。

