# Product

GP is a chat-first A-share main-board decision assistant for short 1–3 trading-day plans. It presents either a publication grounded in complete evidence or an explicit unavailable/no-recommendation result. Runtime quality can make execution unavailable without changing the daily plan.

## Chat workspace

The primary local product surface is a responsive three-pane workspace at port 8080. Conversation history and canonical turns remain the main journey. The decision brief shows the current plan date, evidence date, execution availability, and the selected candidates in engine-provided order. It does not turn internal diagnostics into user-facing recommendations and does not hide unavailable or non-trading states.

On smaller screens, the same information becomes a single reading flow: chat first, decision brief second. Sending supports Enter, while Shift+Enter inserts a new line. Failed narration is shown in Chinese and the unsent question remains available for retry.

The current decision brief and a conversation's bound publication are separate browser states. When a trusted response proves both publications belong to the same immutable plan, runtime-only updates keep the current candidates visible with an explicit execution-state notice. A confirmed different plan remains isolated, while an unknown historical lineage is labeled as unknown rather than falsely asserted to be a different decision.

Every saved-conversation card has a separate delete control. Deletion requires an explicit irreversible-action confirmation that identifies the conversation time and publication. Deleting the active conversation returns the workspace to a new chat; deleting another conversation leaves the current chat intact. A deleted session and all of its messages disappear permanently, while recommendation publications and plans remain unchanged.

# Time-aware narration

The LLM receives the publication's market-time context directly in its prompt: current Shanghai time, plan session date, daily evidence date, publication time, and the latest runtime phase/observed/slot-close facts. It must use those facts to explain pre-open, morning, lunch, afternoon, closing auction, and post-close behavior in Chinese without changing recommendation authority.

## Serenity official-announcement evidence

Serenity is an auxiliary official-announcement dimension, not a second selector. The base engine first freezes its Top-30. If every finalist has a complete, current, verified source result for that exact batch, Serenity uses a fixed 3% signed weight; positive or negative evidence can change the score by at most 0.03. A complete result with no relevant announcement is neutral. If any finalist is missing, a source or PDF fails, or the batch is stale or mismatched, the whole batch contributes zero and the base recommendation remains unchanged. The chat may explain only the actual bound weight, contribution, and product-level reason; it never exposes internal interfaces or identifiers.

Relevant official scanning announcements may be read only when their identity, event family and numerical evidence are consistently recognizable within fixed safety limits. Unrelated generic revisions are ignored before retrieval. An uncertain or unreadable relevant announcement never becomes partial evidence: the exact Top-30 batch remains at 0%.

## Lunch five-minute rerank

After the 11:30 close, GP may publish a new order within the morning plan's frozen Top-30. It requires exact, complete five-minute data for all 30 candidates and CSI300. The lunch score reflects relative morning strength, location versus a volume-weighted price proxy, location within the morning range, and last-hour momentum; the already bound Serenity contribution remains limited to ±0.03. The daily plan and all non-ranking facts remain immutable.

If any input is incomplete, GP keeps the morning publication instead of showing an empty lunch result. A successful lunch publication is still non-tradeable during the break. Existing conversations continue to explain the publication they originally used; a new conversation sees the latest lunch publication.
