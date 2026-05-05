# ============================================================
# risk/risk_manager.py
# The gatekeeper — approves or rejects every trade signal
# Has ABSOLUTE authority over all trading decisions
# ============================================================

from loguru import logger
from datetime import datetime, date
from typing import List, Optional
from strategy.signal import Signal
from risk.position_sizer import PositionSizer


class RiskManager:
    """
    Enforces ALL risk rules before any trade is placed.

    Think of this as a strict compliance officer.
    No trade goes through without passing every check.

    CHECKS (in order):
    1. Kill switch (emergency stop)
    2. Drawdown limit
    3. Daily loss limit
    4. Max concurrent trades
    5. Signal confidence minimum
    6. Position sizing
    7. Final approval
    """

    def __init__(self, config: dict):

        # Risk settings
        self.risk_per_trade      = config.get("RISK_PER_TRADE", 0.01)
        self.max_daily_loss_pct  = config.get("MAX_DAILY_LOSS", 0.03)
        self.max_drawdown_pct    = config.get("MAX_DRAWDOWN", 0.10)
        self.max_concurrent      = config.get("MAX_CONCURRENT_TRADES", 3)
        self.min_confidence      = config.get("MIN_CONFIDENCE", 0.55)

        # State tracking
        self.starting_balance    = 0.0
        self.peak_balance        = 0.0
        self.daily_pnl           = 0.0
        self.daily_reset_date    = date.today()
        self.consecutive_losses  = 0
        self.total_trades        = 0
        self.winning_trades      = 0
        self.open_positions      = []   # List of active trade dicts
        self.trade_history       = []   # List of all closed trades
        self.is_killed           = False
        self.kill_reason         = ""

        # Sub-module
        self.sizer = PositionSizer(config)

        logger.info("🛡️  Risk Manager initialized")
        logger.info(
            f"   Risk/trade  : {self.risk_per_trade*100:.1f}%"
        )
        logger.info(
            f"   Daily limit : {self.max_daily_loss_pct*100:.1f}%"
        )
        logger.info(
            f"   Max drawdown: {self.max_drawdown_pct*100:.1f}%"
        )
        logger.info(
            f"   Max trades  : {self.max_concurrent}"
        )

    def set_starting_balance(self, balance: float):
        """
        Call this once at bot startup with the current account balance.
        Used to track drawdown from the starting point.
        """
        self.starting_balance = balance
        self.peak_balance     = balance
        logger.info(
            f"💰 Starting balance set: ${balance:,.2f}"
        )

    def evaluate(
        self,
        signal: Signal,
        account_balance: float
    ) -> dict:
        """
        THE MAIN FUNCTION.
        Evaluates a signal and returns approval decision.

        Returns a dict:
        {
            "approved"      : True/False,
            "position_size" : 0.021 (BTC amount),
            "risk_amount"   : 10.00 (USD at risk),
            "reason"        : "APPROVED" or "WHY_REJECTED"
        }
        """

        logger.info(f"🔍 Risk check for: {signal.summary()}")

        # Reset daily tracking if new day
        self._check_daily_reset(account_balance)

        # Update peak balance
        self.peak_balance = max(self.peak_balance, account_balance)

        # === CHECK 1: Kill Switch ===
        if self.is_killed:
            return self._reject(f"KILL_SWITCH: {self.kill_reason}")

        # === CHECK 2: Drawdown Limit ===
        if self.peak_balance > 0:
            drawdown = (
                (self.peak_balance - account_balance)
                / self.peak_balance
            )
            if drawdown >= self.max_drawdown_pct:
                self._activate_kill_switch(
                    f"Drawdown {drawdown*100:.1f}% "
                    f"≥ limit {self.max_drawdown_pct*100:.1f}%"
                )
                return self._reject(f"DRAWDOWN_KILL: {drawdown*100:.1f}%")

        # === CHECK 3: Daily Loss Limit ===
        daily_loss_limit = account_balance * self.max_daily_loss_pct
        if self.daily_pnl <= -daily_loss_limit:
            return self._reject(
                f"DAILY_LOSS_LIMIT: Lost ${abs(self.daily_pnl):.2f} today "
                f"(limit: ${daily_loss_limit:.2f})"
            )

        # === CHECK 4: Max Concurrent Trades ===
        open_count = len(self.open_positions)
        if open_count >= self.max_concurrent:
            return self._reject(
                f"MAX_CONCURRENT: {open_count}/{self.max_concurrent} "
                f"trades already open"
            )

        # === CHECK 5: Signal Confidence ===
        if signal.confidence < self.min_confidence:
            return self._reject(
                f"LOW_CONFIDENCE: {signal.confidence:.0%} "
                f"< {self.min_confidence:.0%} minimum"
            )

        # === CHECK 6: Duplicate Direction ===
        # Don't open same direction trade on same pair
        for pos in self.open_positions:
            if (pos["pair"] == signal.pair and
                    pos["direction"] == signal.direction):
                return self._reject(
                    f"DUPLICATE: Already have {signal.direction} "
                    f"on {signal.pair}"
                )

        # === CHECK 7: Position Sizing ===
        sizing = self.sizer.calculate(
            account_balance    = account_balance,
            entry_price        = signal.entry_price,
            stop_loss          = signal.stop_loss,
            confidence         = signal.confidence,
            consecutive_losses = self.consecutive_losses
        )

        if not sizing["approved"]:
            return self._reject(
                f"SIZING_FAILED: {sizing['rejection_reason']}"
            )

        # === ALL CHECKS PASSED ===
        logger.info("✅ Risk check PASSED!")
        logger.info(
            f"   Position size : {sizing['position_size']} BTC"
        )
        logger.info(
            f"   Risk amount   : ${sizing['risk_amount']:,.2f} "
            f"({sizing['risk_pct']:.2f}% of account)"
        )
        logger.info(
            f"   Notional value: ${sizing['notional_value']:,.2f}"
        )
        logger.info(
            f"   Leverage      : {sizing['effective_leverage']:.2f}x"
        )

        return {
            "approved"          : True,
            "position_size"     : sizing["position_size"],
            "risk_amount"       : sizing["risk_amount"],
            "risk_pct"          : sizing["risk_pct"],
            "notional_value"    : sizing["notional_value"],
            "effective_leverage": sizing["effective_leverage"],
            "reason"            : "APPROVED",
        }

    def record_trade_opened(self, signal: Signal, position_size: float):
        """
        Call this when a trade is actually opened.
        Adds it to our list of open positions.
        """
        trade = {
            "pair"        : signal.pair,
            "direction"   : signal.direction,
            "entry_price" : signal.entry_price,
            "stop_loss"   : signal.stop_loss,
            "take_profits": signal.take_profits,
            "position_size": position_size,
            "strategy_id" : signal.strategy_id,
            "opened_at"   : datetime.utcnow(),
            "trade_id"    : len(self.trade_history) + 1,
        }
        self.open_positions.append(trade)
        self.total_trades += 1
        logger.info(
            f"📝 Trade recorded as open: "
            f"{signal.direction} {signal.pair} "
            f"× {position_size} BTC"
        )

    def record_trade_closed(
        self,
        pair: str,
        direction: str,
        exit_price: float,
        pnl: float
    ):
        """
        Call this when a trade closes.
        Updates daily P&L and consecutive loss tracking.
        """

        # Find and remove from open positions
        self.open_positions = [
            p for p in self.open_positions
            if not (p["pair"] == pair and p["direction"] == direction)
        ]

        # Update P&L tracking
        self.daily_pnl += pnl

        # Track consecutive losses
        if pnl > 0:
            self.winning_trades    += 1
            self.consecutive_losses = 0
            result_emoji            = "✅"
        else:
            self.consecutive_losses += 1
            result_emoji             = "❌"

        # Add to history
        self.trade_history.append({
            "pair"      : pair,
            "direction" : direction,
            "exit_price": exit_price,
            "pnl"       : pnl,
            "closed_at" : datetime.utcnow(),
        })

        logger.info(
            f"{result_emoji} Trade closed: "
            f"{direction} {pair} | "
            f"PnL: ${pnl:+,.2f} | "
            f"Daily PnL: ${self.daily_pnl:+,.2f}"
        )

        if self.consecutive_losses >= 2:
            logger.warning(
                f"⚠️ {self.consecutive_losses} consecutive losses. "
                f"Position sizes will be reduced."
            )

    def get_status(self, account_balance: float) -> dict:
        """
        Returns a summary of current risk status.
        Useful for monitoring and daily reports.
        """
        drawdown = 0.0
        if self.peak_balance > 0:
            drawdown = (
                (self.peak_balance - account_balance)
                / self.peak_balance * 100
            )

        win_rate = 0.0
        if self.total_trades > 0:
            win_rate = self.winning_trades / self.total_trades * 100

        return {
            "is_killed"          : self.is_killed,
            "kill_reason"        : self.kill_reason,
            "account_balance"    : account_balance,
            "peak_balance"       : self.peak_balance,
            "drawdown_pct"       : round(drawdown, 2),
            "daily_pnl"          : round(self.daily_pnl, 2),
            "open_positions"     : len(self.open_positions),
            "total_trades"       : self.total_trades,
            "win_rate_pct"       : round(win_rate, 1),
            "consecutive_losses" : self.consecutive_losses,
        }

    def print_status(self, account_balance: float):
        """Prints a formatted risk status report."""
        s = self.get_status(account_balance)

        logger.info(f"\n{'='*55}")
        logger.info(f"  🛡️  RISK MANAGER STATUS")
        logger.info(f"{'='*55}")
        logger.info(
            f"  💰 Balance      : ${s['account_balance']:>10,.2f}"
        )
        logger.info(
            f"  📈 Peak Balance : ${s['peak_balance']:>10,.2f}"
        )
        logger.info(
            f"  📉 Drawdown     :  {s['drawdown_pct']:>9.2f}%"
        )
        logger.info(
            f"  📊 Daily PnL    : ${s['daily_pnl']:>+10,.2f}"
        )
        logger.info(
            f"  🔢 Open Trades  :  {s['open_positions']:>9d}"
        )
        logger.info(
            f"  🏆 Win Rate     :  {s['win_rate_pct']:>9.1f}%"
        )
        logger.info(
            f"  ❌ Consec Loss  :  {s['consecutive_losses']:>9d}"
        )

        if s["is_killed"]:
            logger.error(
                f"  🚨 KILL SWITCH  : ACTIVE — {s['kill_reason']}"
            )
        else:
            logger.info(f"  ✅ Kill Switch  : Inactive")

        logger.info(f"{'='*55}")

    # ── PRIVATE HELPERS ──────────────────────────────────────

    def _check_daily_reset(self, account_balance: float):
        """Resets daily P&L tracker at midnight UTC."""
        today = date.today()
        if today != self.daily_reset_date:
            logger.info(
                f"📅 New day — resetting daily PnL "
                f"(was ${self.daily_pnl:+,.2f})"
            )
            self.daily_pnl       = 0.0
            self.daily_reset_date = today

    def _activate_kill_switch(self, reason: str):
        """Activates the kill switch — stops all trading."""
        self.is_killed   = True
        self.kill_reason = reason
        logger.critical(
            f"🚨 KILL SWITCH ACTIVATED: {reason}"
        )
        logger.critical(
            "🚨 All trading HALTED. Manual restart required."
        )

    def _reject(self, reason: str) -> dict:
        """Returns a standardized rejection response."""
        logger.warning(f"⛔ Signal REJECTED: {reason}")
        return {
            "approved"          : False,
            "position_size"     : 0,
            "risk_amount"       : 0,
            "risk_pct"          : 0,
            "notional_value"    : 0,
            "effective_leverage": 0,
            "reason"            : reason,
        }