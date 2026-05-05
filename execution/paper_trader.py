# ============================================================
# execution/paper_trader.py
# Simulates trade execution without real money
# Tracks positions, checks SL/TP on each candle
# ============================================================

import json
import os
from datetime import datetime
from typing import Optional, List
from loguru import logger
from strategy.signal import Signal


class PaperTrader:
    """
    Simulates a trading account with fake money.

    Tracks:
    - Open positions (trades currently active)
    - Closed positions (trades that finished)
    - Running P&L
    - Balance changes over time

    On each new candle, checks if any open positions
    should be closed (stop loss hit or take profit reached).
    """

    def __init__(self, starting_balance: float = 1000.0):
        """
        starting_balance = how much fake USDT we start with
        """
        self.starting_balance  = starting_balance
        self.current_balance   = starting_balance
        self.open_positions    = []   # List of active trades
        self.closed_positions  = []   # List of finished trades
        self.trade_counter     = 0    # Unique ID for each trade

        # Commission simulation (0.1% per trade = Binance standard)
        self.commission_rate   = 0.001

        logger.info(f"📄 Paper Trader initialized")
        logger.info(
            f"   Starting balance: ${starting_balance:,.2f} USDT"
        )

    def open_trade(
        self,
        signal: Signal,
        position_size: float
    ) -> dict:
        """
        Opens a new paper trade based on a signal.

        signal        = the Signal object from strategy
        position_size = how many BTC to buy/sell (from risk manager)

        Returns the trade dict that was created.
        """

        self.trade_counter += 1

        # Calculate commission on entry
        entry_notional = position_size * signal.entry_price
        entry_commission = entry_notional * self.commission_rate

        # Deduct commission from balance
        self.current_balance -= entry_commission

        trade = {
            # Identity
            "trade_id"          : self.trade_counter,
            "pair"              : signal.pair,
            "strategy_id"       : signal.strategy_id,

            # Direction
            "direction"         : signal.direction,

            # Entry details
            "entry_price"       : signal.entry_price,
            "entry_time"        : datetime.utcnow().isoformat(),
            "entry_commission"  : round(entry_commission, 4),

            # Position
            "position_size"     : position_size,
            "remaining_size"    : position_size,  # Reduces as we scale out
            "notional_value"    : round(entry_notional, 2),

            # Risk levels
            "stop_loss"         : signal.stop_loss,
            "take_profits"      : signal.take_profits,
            "original_sl"       : signal.stop_loss,

            # Tracking
            "scale_outs_done"   : 0,     # How many TPs hit so far
            "realized_pnl"      : 0.0,   # P&L from partial closes
            "status"            : "OPEN",
            "bars_open"         : 0,
            "max_price"         : signal.entry_price,  # For tracking
            "min_price"         : signal.entry_price,
            "notes"             : signal.notes,
        }

        self.open_positions.append(trade)

        logger.info(f"{'='*50}")
        logger.info(
            f"📄 [PAPER] TRADE OPENED #{self.trade_counter}"
        )
        logger.info(
            f"   {signal.direction} {signal.pair} "
            f"× {position_size} BTC"
        )
        logger.info(f"   Entry    : ${signal.entry_price:,.2f}")
        logger.info(f"   Stop     : ${signal.stop_loss:,.2f}")
        logger.info(
            f"   TP1/2/3  : "
            f"${signal.take_profits[0]:,.2f} / "
            f"${signal.take_profits[1]:,.2f} / "
            f"${signal.take_profits[2]:,.2f}"
        )
        logger.info(
            f"   Notional : ${entry_notional:,.2f}"
        )
        logger.info(
            f"   Commission: ${entry_commission:.4f}"
        )
        logger.info(f"{'='*50}")

        return trade

    def update(self, candle: dict) -> List[dict]:
        """
        Called on every new candle close.
        Checks if any open positions should be closed.

        candle = dict with keys: high, low, close, time

        Returns list of events that happened
        (stop hit, TP hit, etc.)
        """
        events = []

        for trade in self.open_positions[:]:  # Copy list for safe removal

            trade["bars_open"] += 1
            high  = candle["high"]
            low   = candle["low"]
            close = candle["close"]

            # Track extreme prices
            trade["max_price"] = max(trade["max_price"], high)
            trade["min_price"] = min(trade["min_price"], low)

            if trade["direction"] == "LONG":
                events += self._update_long(trade, high, low, close, candle)
            else:
                events += self._update_short(trade, high, low, close, candle)

        return events

    def _update_long(
        self,
        trade: dict,
        high: float,
        low: float,
        close: float,
        candle: dict
    ) -> list:
        """Check stop loss and take profits for a LONG trade."""
        events = []

        # ── CHECK STOP LOSS (price went below our stop) ──────────
        if low <= trade["stop_loss"]:
            pnl = self._close_trade(
                trade,
                exit_price=trade["stop_loss"],
                reason="STOP_LOSS",
                candle=candle
            )
            events.append({
                "type"     : "STOP_LOSS",
                "trade_id" : trade["trade_id"],
                "pnl"      : pnl
            })
            return events  # Trade is done

        # ── CHECK TAKE PROFITS ────────────────────────────────────
        # Scale out plan: TP1=40%, TP2=30%, TP3=30%
        scale_out_pcts = [0.40, 0.30, 0.30]

        for i, tp in enumerate(trade["take_profits"]):
            # Only check TPs we haven't hit yet
            if trade["scale_outs_done"] <= i and high >= tp:

                close_pct  = scale_out_pcts[i]
                close_size = trade["remaining_size"] * close_pct

                # Calculate P&L for this partial close
                partial_pnl = self._partial_close(
                    trade, tp, close_size, i
                )

                events.append({
                    "type"      : f"TP{i+1}_HIT",
                    "trade_id"  : trade["trade_id"],
                    "tp_level"  : tp,
                    "pnl"       : partial_pnl,
                    "remaining" : trade["remaining_size"]
                })

                # Move stop loss after TP1
                if i == 0:
                    # Move SL to breakeven after TP1
                    trade["stop_loss"] = trade["entry_price"]
                    logger.info(
                        f"   🔒 SL moved to breakeven: "
                        f"${trade['entry_price']:,.2f}"
                    )
                elif i == 1:
                    # Move SL to TP1 after TP2
                    trade["stop_loss"] = trade["take_profits"][0]
                    logger.info(
                        f"   🔒 SL moved to TP1: "
                        f"${trade['take_profits'][0]:,.2f}"
                    )

                # If all TPs hit → close trade
                if trade["remaining_size"] <= 0.000001:
                    trade["status"] = "CLOSED"
                    self.open_positions.remove(trade)
                    self.closed_positions.append(trade)
                    logger.info(
                        f"✅ Trade #{trade['trade_id']} "
                        f"fully closed at TP{i+1}"
                    )

                break  # Only process one TP per candle

        # ── TIME EXIT (trade open too long without hitting TP1) ──
        if (trade["bars_open"] > 20 and
                trade["scale_outs_done"] == 0 and
                trade["status"] == "OPEN"):
            pnl = self._close_trade(
                trade,
                exit_price=close,
                reason="TIME_EXIT",
                candle=candle
            )
            events.append({
                "type"     : "TIME_EXIT",
                "trade_id" : trade["trade_id"],
                "pnl"      : pnl
            })

        return events

    def _update_short(
        self,
        trade: dict,
        high: float,
        low: float,
        close: float,
        candle: dict
    ) -> list:
        """Check stop loss and take profits for a SHORT trade."""
        events = []

        # ── CHECK STOP LOSS ───────────────────────────────────────
        if high >= trade["stop_loss"]:
            pnl = self._close_trade(
                trade,
                exit_price=trade["stop_loss"],
                reason="STOP_LOSS",
                candle=candle
            )
            events.append({
                "type"     : "STOP_LOSS",
                "trade_id" : trade["trade_id"],
                "pnl"      : pnl
            })
            return events

        # ── CHECK TAKE PROFITS ────────────────────────────────────
        scale_out_pcts = [0.40, 0.30, 0.30]

        for i, tp in enumerate(trade["take_profits"]):
            if trade["scale_outs_done"] <= i and low <= tp:

                close_pct  = scale_out_pcts[i]
                close_size = trade["remaining_size"] * close_pct

                partial_pnl = self._partial_close(
                    trade, tp, close_size, i
                )

                events.append({
                    "type"      : f"TP{i+1}_HIT",
                    "trade_id"  : trade["trade_id"],
                    "tp_level"  : tp,
                    "pnl"       : partial_pnl,
                    "remaining" : trade["remaining_size"]
                })

                if i == 0:
                    trade["stop_loss"] = trade["entry_price"]
                elif i == 1:
                    trade["stop_loss"] = trade["take_profits"][0]

                if trade["remaining_size"] <= 0.000001:
                    trade["status"] = "CLOSED"
                    self.open_positions.remove(trade)
                    self.closed_positions.append(trade)

                break

        # ── TIME EXIT ─────────────────────────────────────────────
        if (trade["bars_open"] > 20 and
                trade["scale_outs_done"] == 0 and
                trade["status"] == "OPEN"):
            pnl = self._close_trade(
                trade,
                exit_price=close,
                reason="TIME_EXIT",
                candle=candle
            )
            events.append({
                "type"     : "TIME_EXIT",
                "trade_id" : trade["trade_id"],
                "pnl"      : pnl
            })

        return events

    def _partial_close(
        self,
        trade: dict,
        exit_price: float,
        close_size: float,
        tp_index: int
    ) -> float:
        """
        Close part of a position at a take profit level.
        Returns the P&L from this partial close.
        """

        if trade["direction"] == "LONG":
            gross_pnl = (exit_price - trade["entry_price"]) * close_size
        else:
            gross_pnl = (trade["entry_price"] - exit_price) * close_size

        commission    = close_size * exit_price * self.commission_rate
        net_pnl       = gross_pnl - commission

        trade["realized_pnl"]   += net_pnl
        trade["remaining_size"] -= close_size
        trade["scale_outs_done"] = tp_index + 1

        self.current_balance += net_pnl

        logger.info(
            f"   💰 TP{tp_index+1} HIT — Trade #{trade['trade_id']} | "
            f"Closed {close_size:.5f} BTC @ ${exit_price:,.2f} | "
            f"PnL: ${net_pnl:+,.2f}"
        )

        return round(net_pnl, 2)

    def _close_trade(
        self,
        trade: dict,
        exit_price: float,
        reason: str,
        candle: dict
    ) -> float:
        """
        Fully close a trade at a given price.
        Returns the total net P&L.
        """

        size = trade["remaining_size"]

        if trade["direction"] == "LONG":
            gross_pnl = (exit_price - trade["entry_price"]) * size
        else:
            gross_pnl = (trade["entry_price"] - exit_price) * size

        commission = size * exit_price * self.commission_rate
        net_pnl    = gross_pnl - commission

        # Add any P&L already realized from partial closes
        total_pnl  = net_pnl + trade["realized_pnl"]

        trade["status"]         = "CLOSED"
        trade["exit_price"]     = exit_price
        trade["exit_reason"]    = reason
        trade["exit_time"]      = candle.get("time", datetime.utcnow())
        trade["total_pnl"]      = round(total_pnl, 2)
        trade["remaining_size"] = 0

        self.current_balance   += net_pnl
        self.open_positions.remove(trade)
        self.closed_positions.append(trade)

        # Calculate R multiple
        risk = abs(trade["entry_price"] - trade["original_sl"])
        r_multiple = total_pnl / (risk * (trade["position_size"])) if risk > 0 else 0

        emoji = "✅" if total_pnl > 0 else "❌"

        logger.info(f"{'='*50}")
        logger.info(
            f"{emoji} [PAPER] TRADE CLOSED #{trade['trade_id']}"
        )
        logger.info(f"   Reason   : {reason}")
        logger.info(
            f"   Entry    : ${trade['entry_price']:,.2f}"
        )
        logger.info(f"   Exit     : ${exit_price:,.2f}")
        logger.info(
            f"   Total PnL: ${total_pnl:+,.2f}"
        )
        logger.info(
            f"   R Multiple: {r_multiple:+.2f}R"
        )
        logger.info(
            f"   Balance  : ${self.current_balance:,.2f}"
        )
        logger.info(f"{'='*50}")

        return round(total_pnl, 2)

    def get_unrealized_pnl(self, current_price: float) -> float:
        """
        Calculate total unrealized P&L for all open positions.
        Uses the current market price.
        """
        total = 0.0
        for trade in self.open_positions:
            size = trade["remaining_size"]
            if trade["direction"] == "LONG":
                pnl = (current_price - trade["entry_price"]) * size
            else:
                pnl = (trade["entry_price"] - current_price) * size
            total += pnl
        return round(total, 2)

    def print_summary(self, current_price: float = 0):
        """Print a complete account summary."""

        total_pnl    = self.current_balance - self.starting_balance
        total_pnl_pct = total_pnl / self.starting_balance * 100
        unrealized   = self.get_unrealized_pnl(current_price) \
                       if current_price > 0 else 0

        closed = self.closed_positions
        if closed:
            wins     = [t for t in closed if t.get("total_pnl", 0) > 0]
            losses   = [t for t in closed if t.get("total_pnl", 0) <= 0]
            win_rate = len(wins) / len(closed) * 100
            avg_win  = (
                sum(t["total_pnl"] for t in wins) / len(wins)
                if wins else 0
            )
            avg_loss = (
                sum(t["total_pnl"] for t in losses) / len(losses)
                if losses else 0
            )
        else:
            win_rate = avg_win = avg_loss = 0

        logger.info(f"\n{'='*55}")
        logger.info(f"  📄 PAPER TRADING ACCOUNT SUMMARY")
        logger.info(f"{'='*55}")
        logger.info(
            f"  💰 Starting Balance : ${self.starting_balance:>10,.2f}"
        )
        logger.info(
            f"  💰 Current Balance  : ${self.current_balance:>10,.2f}"
        )
        logger.info(
            f"  📊 Total P&L        : ${total_pnl:>+10,.2f} "
            f"({total_pnl_pct:+.2f}%)"
        )
        if current_price > 0:
            logger.info(
                f"  📈 Unrealized P&L   : ${unrealized:>+10,.2f}"
            )
        logger.info(f"{'─'*55}")
        logger.info(
            f"  📋 Open Trades      : {len(self.open_positions):>10d}"
        )
        logger.info(
            f"  📋 Closed Trades    : {len(self.closed_positions):>10d}"
        )
        logger.info(
            f"  🏆 Win Rate         : {win_rate:>10.1f}%"
        )
        logger.info(
            f"  ✅ Avg Win          : ${avg_win:>+10,.2f}"
        )
        logger.info(
            f"  ❌ Avg Loss         : ${avg_loss:>+10,.2f}"
        )
        logger.info(f"{'='*55}")