from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BaselineDailyParams:
    buy_top_k: int = 1
    per_stock_cash: float = 0.25


class BaselineDaily:
    """纯日线策略：
    - 每日开盘按候选池 TopK 买入（额度按 per_stock_cash）
    - 次日开盘卖出（T+1）
    - 周五收盘强平
    """

    requires_minutes = False

    def __init__(self, params: BaselineDailyParams | None = None):
        self.params = params or BaselineDailyParams()

