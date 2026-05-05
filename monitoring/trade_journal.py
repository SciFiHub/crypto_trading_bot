# ============================================================
# monitoring/trade_journal.py
# Saves all trades to a JSON file for review and analysis
# ============================================================

import json
import os
from datetime import datetime
from loguru import logger


class TradeJournal:
    """
    Saves every trade to a JSON file so we can:
    - Review performance after the bot runs
    - Analyze which setups work best
    - Debug issues
    - Build performance reports

    JSON = a simple text format for storing data
    """

    def __init__(self, filepath: str = "logs/trade_journal.json"):
        self.filepath = filepath

        # Create logs directory if it doesn't exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # Load existing journal if file exists
        self.trades = self._load()
        logger.info(
            f"📔 Trade Journal loaded: "
            f"{len(self.trades)} existing trades"
        )

    def log_trade(self, trade: dict):
        """
        Save a completed trade to the journal.
        trade = the trade dict from PaperTrader
        """

        # Add logging timestamp
        entry = trade.copy()
        entry["logged_at"] = datetime.utcnow().isoformat()

        self.trades.append(entry)
        self._save()

        logger.debug(
            f"📔 Trade #{trade.get('trade_id', '?')} "
            f"saved to journal"
        )

    def log_signal(self, signal_data: dict):
        """
        Save a signal (even if no trade was taken).
        Useful for reviewing what the strategy saw.
        """
        entry = {
            "type"      : "SIGNAL",
            "logged_at" : datetime.utcnow().isoformat(),
            **signal_data
        }
        self.trades.append(entry)
        self._save()

    def get_performance_summary(self) -> dict:
        """
        Calculate performance statistics from all saved trades.
        """
        closed = [
            t for t in self.trades
            if t.get("status") == "CLOSED"
            and "total_pnl" in t
        ]

        if not closed:
            return {"message": "No closed trades yet"}

        wins   = [t for t in closed if t["total_pnl"] > 0]
        losses = [t for t in closed if t["total_pnl"] <= 0]

        total_pnl  = sum(t["total_pnl"] for t in closed)
        gross_win  = sum(t["total_pnl"] for t in wins)
        gross_loss = abs(sum(t["total_pnl"] for t in losses))

        return {
            "total_trades"   : len(closed),
            "wins"           : len(wins),
            "losses"         : len(losses),
            "win_rate_pct"   : round(len(wins)/len(closed)*100, 1),
            "total_pnl"      : round(total_pnl, 2),
            "gross_win"      : round(gross_win, 2),
            "gross_loss"     : round(gross_loss, 2),
            "profit_factor"  : round(gross_win/gross_loss, 2)
                               if gross_loss > 0 else 0,
            "avg_win"        : round(gross_win/len(wins), 2)
                               if wins else 0,
            "avg_loss"       : round(-gross_loss/len(losses), 2)
                               if losses else 0,
        }

    def print_performance(self):
        """Print a formatted performance report."""
        summary = self.get_performance_summary()

        if "message" in summary:
            logger.info(f"📔 Journal: {summary['message']}")
            return

        pf = summary["profit_factor"]
        pf_emoji = "✅" if pf > 1.3 else "⚠️" if pf > 1.0 else "❌"

        logger.info(f"\n{'='*55}")
        logger.info(f"  📔 TRADE JOURNAL PERFORMANCE")
        logger.info(f"{'='*55}")
        logger.info(
            f"  Total Trades   : {summary['total_trades']}"
        )
        logger.info(
            f"  Win Rate       : {summary['win_rate_pct']}%"
        )
        logger.info(
            f"  Total P&L      : ${summary['total_pnl']:+,.2f}"
        )
        logger.info(
            f"  Profit Factor  : {pf} {pf_emoji}"
        )
        logger.info(
            f"  Avg Win        : ${summary['avg_win']:+,.2f}"
        )
        logger.info(
            f"  Avg Loss       : ${summary['avg_loss']:+,.2f}"
        )
        logger.info(f"{'='*55}")

    def _save(self):
        """Save all trades to JSON file."""
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.trades, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"❌ Failed to save journal: {e}")

    def _load(self) -> list:
        """Load existing trades from JSON file."""
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r") as f:
                return json.load(f)
        except Exception:
            return []