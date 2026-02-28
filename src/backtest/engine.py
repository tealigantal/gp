from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import math
import json
import pandas as pd

from ..strategies.base import Strategy, OrderIntent


@dataclass
class CostModel:
    commission_rate: float = 0.0003  # 0.03%
    transfer_fee: float = 0.00002  # Shanghai only typically
    stamp_duty: float = 0.001  # sell only
    slippage_bps: float = 1.0  # 1 bps
    min_commission: float = 5.0

    def calc(self, side: str, amount: float, exchange: str = "SH") -> Tuple[float, float]:
        # returns (total_fee, price_slip_multiplier)
        commission = max(self.min_commission, amount * self.commission_rate)
        transfer = amount * self.transfer_fee if exchange == "SH" else 0.0
        stamp = amount * self.stamp_duty if side == "SELL" else 0.0
        slip = self.slippage_bps / 10000.0
        px_mult = (1 + slip) if side == "BUY" else (1 - slip)
        return commission + transfer + stamp, px_mult


@dataclass
class Position:
    ts_code: str
    shares: int = 0
    cost: float = 0.0  # cost per share
    last_buy_date: Optional[str] = None


@dataclass
class Order:
    ts_code: str
    side: str  # BUY/SELL
    shares: int
    signal_time: str
    next_exec_time: Optional[str] = None
    status: str = "pending"  # pending/filled/cancelled
    pending_bars: int = 0  # for limit-up/down suspension counting
    reason: str = ""


def round_to_lot(shares: int, lot: int = 100) -> int:
    return max(0, (shares // lot) * lot)


def limit_prices(prev_close: float, is_st: bool = False) -> Tuple[float, float]:
    # mainboard 10% limit, ST 5%
    limit = 0.05 if is_st else 0.10
    up = round_price(prev_close * (1 + limit))
    dn = round_price(prev_close * (1 - limit))
    return up, dn


def round_price(px: float) -> float:
    return float(round(px + 1e-8, 2))


class BacktestEngine:
    def __init__(
        self,
        strategies: List[Strategy],
        initial_cash: float,
        cost_model: CostModel,
        results_dir: Path,
        basics: pd.DataFrame,
        daily_prev_close: Dict[str, float],
    ) -> None:
        self.strategies = strategies
        self.cash = initial_cash
        self.cost_model = cost_model
        self.results_dir = Path(results_dir)
        self.positions: Dict[str, Position] = {}
        self.trades: List[Dict] = []
        self.daily_equity_rows: List[Dict] = []
        self.daily_prev_close = daily_prev_close
        self.is_st_map = {r.ts_code: bool(r.is_st) for r in basics.itertuples()}
        self.exchange_map = {r.ts_code: str(r.exchange) for r in basics.itertuples()}
        # carry-over orders to next trading day (e.g., T+1 sells or forced flat)
        self.carry_orders: List[Order] = []
        # capacity/participation settings (optional; set via attribute)
        self.max_participation_rate: Optional[float] = None  # e.g., 0.05; if None -> disabled
        # fill tracking
        self._buy_intent_shares: int = 0
        self._buy_filled_shares: int = 0
        self._partial_fill_count: int = 0
        self._unfilled_shares_eod: int = 0

    def _position(self, ts: str) -> Position:
        if ts not in self.positions:
            self.positions[ts] = Position(ts_code=ts)
        return self.positions[ts]

    def _one_word_limit(self, ts: str, bar: Dict, prev_close: float, up: bool) -> bool:
        up_px, dn_px = limit_prices(prev_close, is_st=False)  # ST excluded by default
        lim = up_px if up else dn_px
        return (
            abs(bar["open"] - lim) < 1e-8
            and abs(bar["high"] - lim) < 1e-8
            and abs(bar["low"] - lim) < 1e-8
            and abs(bar["close"] - lim) < 1e-8
            and (bar.get("vol", 0) <= 1)
        )

    def _exec_order(self, order: Order, bar_open: float, trade_time: str, *, bar_vol: Optional[float] = None) -> bool:
        # return True if filled
        pos = self._position(order.ts_code)
        exch = self.exchange_map.get(order.ts_code, "SH")
        amount = bar_open * order.shares
        fee, slip_mult = self.cost_model.calc(order.side, amount, exchange=exch)
        px = round_price(bar_open * slip_mult)

        if order.side == "BUY":
            # capacity constraint: cap shares by participation of bar volume
            if self.max_participation_rate is not None and bar_vol is not None:
                cap_shares = int(math.floor(float(bar_vol) * float(self.max_participation_rate)))
                cap_shares = round_to_lot(cap_shares)
                ask_shares = round_to_lot(order.shares)
                self._buy_intent_shares += ask_shares
                if cap_shares <= 0:
                    return False
                if ask_shares > cap_shares:
                    # partial fill amount
                    fill_shares = cap_shares
                    leftover = max(0, ask_shares - fill_shares)
                    # update order to leftover for retry later in day
                    order.shares = leftover
                    order.next_exec_time = None
                    self._partial_fill_count += 1
                else:
                    fill_shares = ask_shares
                    leftover = 0
                if fill_shares <= 0:
                    return False
                # recompute fees on actual amount
                amount2 = px * fill_shares
                fee, _ = self.cost_model.calc(order.side, amount2, exchange=exch)
                total = px * fill_shares + fee
                if total > self.cash + 1e-6:
                    return False
                # fill
                new_shares = pos.shares + fill_shares
                pos.cost = (pos.cost * pos.shares + px * fill_shares) / new_shares if new_shares else 0.0
                pos.shares = new_shares
                pos.last_buy_date = trade_time[:8]
                self.cash -= total
                self.trades.append(
                    {
                        "time": trade_time,
                        "ts_code": order.ts_code,
                        "side": order.side,
                        "price": px,
                        "shares": fill_shares,
                        "fee": fee,
                        "reason": order.reason,
                    }
                )
                self._buy_filled_shares += fill_shares
                # if leftover remains, keep order pending
                return leftover == 0
            total = px * order.shares + fee
            if total > self.cash + 1e-6:
                return False
            # fill
            new_shares = pos.shares + order.shares
            pos.cost = (pos.cost * pos.shares + px * order.shares) / new_shares if new_shares else 0.0
            pos.shares = new_shares
            pos.last_buy_date = trade_time[:8]
            self.cash -= total
            self.trades.append(
                {
                    "time": trade_time,
                    "ts_code": order.ts_code,
                    "side": order.side,
                    "price": px,
                    "shares": order.shares,
                    "fee": fee,
                    "reason": order.reason,
                }
            )
            self._buy_filled_shares += order.shares
            return True
        else:
            if pos.shares <= 0:
                return False
            # T+1: cannot sell today if bought today
            if pos.last_buy_date == trade_time[:8]:
                return False
            sell_shares = min(order.shares or pos.shares, pos.shares)
            sell_shares = round_to_lot(sell_shares)
            if sell_shares <= 0:
                return False
            proceeds = px * sell_shares - fee
            pos.shares -= sell_shares
            self.cash += proceeds
            self.trades.append(
                {
                    "time": trade_time,
                    "ts_code": order.ts_code,
                    "side": order.side,
                    "price": px,
                    "shares": sell_shares,
                    "fee": fee,
                    "reason": order.reason,
                }
            )
            return True

    def _mark_to_market(self, trade_date: str, last_bar_prices: Dict[str, float]) -> None:
        equity = self.cash
        for ts, pos in self.positions.items():
            if pos.shares <= 0:
                continue
            px = last_bar_prices.get(ts, self.daily_prev_close.get(ts, pos.cost))
            equity += px * pos.shares
        self.daily_equity_rows.append({"trade_date": trade_date, "equity": round(equity, 2), "cash": round(self.cash, 2)})

    def run_day(self, trade_date: str, min5_bars: Dict[str, List[Dict]], universe: List[str], *, is_week_last: bool = False) -> Dict:
        # Build a combined chronological set of bar times
        # min5_bars: {ts_code: [{trade_time, open, high, low, close, vol, amount}, ...]}
        times = sorted({b["trade_time"] for bars in min5_bars.values() for b in bars})
        history: Dict[str, List[Dict]] = {ts: [] for ts in min5_bars.keys()}
        if not times:
            # no bars available; still mark MTM using prev close
            self._mark_to_market(trade_date, {})
            return {"pending": [], "buy_fail": 0, "sell_fail": 0, "pending_bar_count": 0, "reject_buy": 0, "reject_sell": 0}

        scheduled: List[Order] = []
        # preload carryover orders to first bar open
        for o in self.carry_orders:
            o.next_exec_time = times[0]
            scheduled.append(o)
        self.carry_orders = []

        pending_counts = {"buy_fail": 0, "sell_fail": 0}
        pending_bar_count = 0
        reject_counts = {"reject_buy": 0, "reject_sell": 0}

        last_px: Dict[str, float] = {}

        for i, t in enumerate(times):
            # update history to this close
            for ts, bars in min5_bars.items():
                while history[ts] and history[ts][-1]["trade_time"] == t:
                    break
                # append bar for this time if exists
                for b in bars:
                    if b["trade_time"] == t:
                        history[ts].append(b)
                        last_px[ts] = b["close"]
                        break

            # strategies generate intents at bar close t
            bar_slice = {"history": {ts: history[ts][:] for ts in history}, "universe": list(universe)}
            intents: List[OrderIntent] = []
            for s in self.strategies:
                intents.extend(s.on_bar(t, bar_slice))

            # schedule execution at next bar open
            next_time = times[i + 1] if i + 1 < len(times) else None
            for intent in intents:
                if intent.ts_code == "__ALL__" and intent.side == "SELL":
                    # mark all positions for next-day close via engine policy; we record as a day-end plan
                    continue
                if intent.side == "BUY" and is_week_last:
                    # Friday no new positions: reject and log
                    self.trades.append(
                        {
                            "time": t,
                            "ts_code": intent.ts_code,
                            "side": "REJECT_BUY",
                            "price": 0.0,
                            "shares": 0,
                            "fee": 0.0,
                            "reason": "friday_no_new_position",
                        }
                    )
                    reject_counts["reject_buy"] += 1
                    continue
                order = Order(ts_code=intent.ts_code, side=intent.side, shares=round_to_lot(intent.shares), signal_time=t, next_exec_time=next_time, reason=intent.reason)
                scheduled.append(order)

            # Try to execute scheduled whose time is now
            still_pending: List[Order] = []
            for order in scheduled:
                # allow re-try on every subsequent bar if next_exec_time is None (pending)
                if order.next_exec_time not in (None, t):
                    still_pending.append(order)
                    continue
                # determine open price at t for that symbol
                bars = min5_bars.get(order.ts_code, [])
                next_bar = next((b for b in bars if b["trade_time"] == t), None)
                if not next_bar:
                    still_pending.append(order)
                    continue
                prev_close = self.daily_prev_close.get(order.ts_code, last_px.get(order.ts_code, next_bar["open"]))
                # locked limit check
                if order.side == "BUY" and self._one_word_limit(order.ts_code, next_bar, prev_close, up=True):
                    order.pending_bars += 1
                    pending_counts["buy_fail"] += 1
                    pending_bar_count += 1
                    order.next_exec_time = None  # keep pending, retry on future bars in the same day
                    still_pending.append(order)
                    continue
                if order.side == "SELL" and self._one_word_limit(order.ts_code, next_bar, prev_close, up=False):
                    order.pending_bars += 1
                    pending_counts["sell_fail"] += 1
                    pending_bar_count += 1
                    order.next_exec_time = None  # keep pending, retry on future bars in the same day
                    still_pending.append(order)
                    continue
                # attempt fill
                filled = self._exec_order(order, next_bar["open"], t, bar_vol=next_bar.get("vol"))
                if not filled:
                    # keep as pending to try later bars the same day
                    order.next_exec_time = None
                    still_pending.append(order)
            scheduled = still_pending

        # Day end MTM
        self._mark_to_market(trade_date, last_px)

        # Create forced flat on week last bar: schedule SELL for all positions to next day
        if is_week_last:
            for ts, pos in list(self.positions.items()):
                if pos.shares > 0:
                    self.carry_orders.append(
                        Order(
                            ts_code=ts,
                            side="SELL",
                            shares=pos.shares,
                            signal_time=f"{trade_date} {times[-1].split(' ')[1]}",
                            next_exec_time=None,
                            reason="force_flat_friday_close",
                        )
                    )

        # Cancel leftover BUY at day end; carry over SELL if T+1 (same-day signal)
        still_pending_carry: List[Order] = []
        for order in scheduled:
            sig_day = order.signal_time[:8]
            if order.side == "SELL" and sig_day == trade_date:
                # carry to next day due to T+1
                self.carry_orders.append(order)
                reject_counts["reject_sell"] += 1
                continue
            # otherwise cancel and record in trades log as CANCEL
            if order.side == "BUY":
                # count remaining shares as unfilled
                self._unfilled_shares_eod += int(order.shares)
            self.trades.append(
                {
                    "time": f"{trade_date} {times[-1].split(' ')[1]}",
                    "ts_code": order.ts_code,
                    "side": ("CANCEL_BUY" if order.side == "BUY" else "CANCEL_SELL"),
                    "price": 0.0,
                    "shares": 0,
                    "fee": 0.0,
                    "reason": ("limit_locked" if order.pending_bars > 0 else "not_filled"),
                }
            )

        return {
            "pending": self.carry_orders[:],
            "buy_fail": pending_counts["buy_fail"],
            "sell_fail": pending_counts["sell_fail"],
            "pending_bar_count": pending_bar_count,
            "reject_buy": reject_counts["reject_buy"],
            "reject_sell": reject_counts["reject_sell"],
            "partial_fill_count": self._partial_fill_count,
            "unfilled_shares_end_of_day": self._unfilled_shares_eod,
        }

    def finalize(self) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        trades_df = pd.DataFrame(self.trades)
        daily_eq = pd.DataFrame(self.daily_equity_rows)
        trades_df.to_csv(self.results_dir / "trades.csv", index=False)
        daily_eq.to_csv(self.results_dir / "daily_equity.csv", index=False)
