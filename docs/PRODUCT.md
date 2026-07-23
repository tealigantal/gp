# Product

GP is a chat-first A-share main-board decision assistant for short 1–3 trading-day plans. It presents either a publication grounded in complete evidence or an explicit unavailable/no-recommendation result. Runtime quality can make execution unavailable without changing the daily plan.

## Chat workspace

The primary local product surface is a responsive three-pane workspace at port 8080. Conversation history and canonical turns remain the main journey. The decision brief shows the current plan date, evidence date, execution availability, and the selected candidates in engine-provided order. It does not turn internal diagnostics into user-facing recommendations and does not hide unavailable or non-trading states.

On smaller screens, the same information becomes a single reading flow: chat first, decision brief second. Sending supports Enter, while Shift+Enter inserts a new line. Failed narration is shown in Chinese and the unsent question remains available for retry.

The current decision brief and a conversation's bound publication are separate browser states. When a trusted response proves both publications belong to the same immutable plan, runtime-only updates keep the current candidates visible with an explicit execution-state notice. A confirmed different plan remains isolated, while an unknown historical lineage is labeled as unknown rather than falsely asserted to be a different decision.

Every saved-conversation card has a separate delete control. Deletion requires an explicit irreversible-action confirmation that identifies the conversation time and publication. Deleting the active conversation returns the workspace to a new chat; deleting another conversation leaves the current chat intact. A deleted session and all of its messages disappear permanently, while recommendation publications and plans remain unchanged.

# Time-aware narration

The LLM receives the publication's market-time context directly in its prompt: current Shanghai time, plan session date, daily evidence date, publication time, and the latest runtime phase/observed/slot-close facts. It must use those facts to explain pre-open, morning, lunch, afternoon, closing auction, and post-close behavior in Chinese without changing recommendation authority.
