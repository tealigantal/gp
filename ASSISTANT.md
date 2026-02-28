# Assistant 使用说明（简版）

详细说明迁移至 `docs/assistant.md`。

受控动作：仅允许 `python gpbt.py` 的白名单子命令（见 `configs/assistant.yaml`）。禁止任意 shell。

会话回放：每次对话日志落盘至 `store/assistant/sessions/session_*.jsonl`，记录用户输入、模型输出、工具调用摘要与耗时，对疑似密钥进行脱敏。

