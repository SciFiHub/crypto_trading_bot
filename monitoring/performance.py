# ============================================================
# monitoring/performance.py
# Calculates and displays performance metrics
# ============================================================

from loguru import logger
from typing import List


class PerformanceTracker:
    """
    Tracks and calculates all performance metrics in real-time.

    Metrics we track:
    - Win rate
    - Profit factor
    - Average R-multiple
    - Max drawdown
    - Consecutive losses
    - Daily/weekly P&L
    """

    def __init__(self, starting_balance: float):
        self.starting_balance = starting_balance
        self.peak_balance     = starting_balance
        self.trade_results    = []  # List of P&L values

    def record(self, pnl: float, balance: float):
        """Record a completed trade result."""
        self.trade_results.append(pnl)
        self.peak_balance = max(self.peak_balance, balance)

    def get_metrics(self, current_balance: float) -> dict:
        """Calculate all performance metrics."""

        if not self.trade_results:
            return {
                "total_trades"   : 0,
                "win_rate"       : 0.0,
                "profit_factor"  : 0.0,
                "total_return"   : 0.0,
                "max_drawdown"   : 0.0,
                "expectancy"     : 0.0,
            }

        wins   = [p for p in self.trade_results if p > 0]
        losses = [p for p in self.trade_results if p <= 0]

        win_rate      = len(wins) / len(self.trade_results) * 100
        gross_profit  = sum(wins) if wins else 0
        gross_loss    = abs(sum(losses)) if losses else 0
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0 else 0
        )

        total_return = (
            (current_balance - self.starting_balance)
            / self.starting_balance * 100
        )

        max_dd = (
            (self.peak_balance - current_balance)
            / self.peak_balance * 100
            if self.peak_balance > 0 else 0
        )

        expectancy = (
            sum(self.trade_results) / len(self.trade_results)
        )

        return {
            "total_trades"  : len(self.trade_results),
            "wins"          : len(wins),
            "losses"        : len(losses),
            "win_rate"      : round(win_rate, 1),
            "profit_factor" : round(profit_factor, 2),
            "total_return"  : round(total_return, 2),
            "max_drawdown"  : round(max_dd, 2),
            "expectancy"    : round(expectancy, 2),
            "gross_profit"  : round(gross_profit, 2),
            "gross_loss"    : round(gross_loss, 2),
        }

    def print_metrics(self, current_balance: float):
        """Print formatted performance metrics."""
        m = self.get_metrics(current_balance)

        if m["total_trades"] == 0:
            logger.info("📊 No completed trades yet.")
            return

        pf_emoji = (
            "✅" if m["profit_factor"] > 1.3
            else "⚠️" if m["profit_factor"] > 1.0
            else "❌"
        )

        logger.info(f"\n{'='*55}")
        logger.info(f"  📊 PERFORMANCE METRICS")
        logger.info(f"{'='*55}")
        logger.info(
            f"  Total Trades   : {m['total_trades']}"
            f" ({m['wins']}W / {m['losses']}L)"
        )
        logger.info(
            f"  Win Rate       : {m['win_rate']}%"
        )
        logger.info(
            f"  Profit Factor  : {m['profit_factor']} {pf_emoji}"
        )
        logger.info(
            f"  Total Return   : {m['total_return']:+.2f}%"
        )
        logger.info(
            f"  Max Drawdown   : {m['max_drawdown']:.2f}%"
        )
        logger.info(
            f"  Avg Per Trade  : ${m['expectancy']:+.2f}"
        )
        logger.info(f"{'='*55}")