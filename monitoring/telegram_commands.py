# ============================================================
# monitoring/telegram_commands.py
# Handles Telegram commands for live bot monitoring
# Includes start/stop/pause control
# ============================================================

import os
import threading
import requests
import time
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class TelegramCommands:
    """
    Listens for Telegram commands and replies
    with live bot status information.
    """

    def __init__(
        self,
        paper_trader,
        risk_manager,
        performance,
        health,
        bot_ref=None
    ):
        self.token        = os.getenv(
            "TELEGRAM_BOT_TOKEN", ""
        )
        self.chat_id      = os.getenv(
            "TELEGRAM_CHAT_ID", ""
        )
        self.enabled      = bool(
            self.token and self.chat_id
        )
        self.base_url     = (
            f"https://api.telegram.org/bot{self.token}"
        )
        self.offset       = 0
        self.running      = False
        self.thread       = None

        # Bot module references
        self.paper_trader = paper_trader
        self.risk_manager = risk_manager
        self.performance  = performance
        self.health       = health
        self.bot_ref      = bot_ref

        # Control flag
        self.is_paused    = False

        if self.enabled:
            logger.info("Telegram commands: ENABLED")
        else:
            logger.warning("Telegram commands: DISABLED")

    def set_bot_ref(self, bot):
        """Set reference to main TradingBot."""
        self.bot_ref = bot

    def start(self):
        """Start listening in background thread."""
        if not self.enabled:
            return

        self.running = True
        self.thread  = threading.Thread(
            target=self._listen_loop,
            daemon=True
        )
        self.thread.start()
        logger.info("Telegram command listener started")

    def stop(self):
        """Stop the listener."""
        self.running = False
        logger.info("Telegram command listener stopped")

    def _listen_loop(self):
        """Background loop checking for messages."""
        while self.running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception as e:
                logger.debug(f"Telegram poll error: {e}")
            time.sleep(5)

    def _get_updates(self) -> list:
        """Fetch new messages."""
        try:
            response = requests.get(
                f"{self.base_url}/getUpdates",
                params={
                    "offset" : self.offset,
                    "timeout": 4,
                    "limit"  : 10
                },
                timeout=8
            )
            data    = response.json()
            updates = data.get("result", [])

            if updates:
                self.offset = updates[-1]["update_id"] + 1

            return updates if data.get("ok") else []
        except Exception:
            return []

    def _handle_update(self, update: dict):
        """Process one incoming message."""
        message = update.get("message", {})
        text    = message.get("text", "").strip().lower()
        from_id = str(
            message.get("chat", {}).get("id", "")
        )
        
        # ✅ DUPLICATE UPDATE FIX
        update_id = update.get("update_id")
        if hasattr(self, "last_update_id") and self.last_update_id == update_id:
            return
        self.last_update_id = update_id 
        
        # Security check
        if from_id != self.chat_id:
            return

        if not text:
            return

        logger.info(f"Telegram command: {text}")

        # Route commands
        if text == "/help":
            self._cmd_help()
        elif text == "/status":
            self._cmd_status()
        elif text == "/positions":
            self._cmd_positions()
        elif text == "/balance":
            self._cmd_balance()
        elif text == "/trades":
            self._cmd_trades()
        elif text == "/health":
            self._cmd_health()
        elif text == "/pause":
            self._cmd_pause()
        elif text == "/resume":
            self._cmd_resume()
        elif text == "/stop":
            self._cmd_stop()
        elif text == "/kill":
            self._cmd_kill()
        else:
            self._send(
                f"Unknown command: {text}\n"
                "Send /help for commands"
            )

    # ── MONITORING COMMANDS ───────────────────────────────────

    def _cmd_help(self):
        """Show all commands."""
        pause_status = (
            "PAUSED" if self.is_paused
            else "Running"
        )
        self._send(
            "<b>BOT COMMANDS</b>\n"
            "========================\n"
            f"Status: {pause_status}\n"
            "========================\n"
            "<b>MONITORING:</b>\n"
            "/status     - Full overview\n"
            "/positions  - Open trades\n"
            "/balance    - Account info\n"
            "/trades     - Trade history\n"
            "/health     - Bot health\n"
            "========================\n"
            "<b>CONTROL:</b>\n"
            "/pause      - Pause signals\n"
            "/resume     - Resume signals\n"
            "/stop       - Stop bot\n"
            "/kill       - Emergency stop\n"
            "========================\n"
            f"Time: "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )

    def _cmd_status(self):
        """Full status."""
        balance  = self.paper_trader.current_balance
        open_pos = self.paper_trader.open_positions
        metrics  = self.performance.get_metrics(balance)
        status   = self.risk_manager.get_status(balance)

        if open_pos:
            pos_lines = []
            for p in open_pos:
                tps_done = p.get("scale_outs_done", 0)
                pos_lines.append(
                    f"  {p['direction']} "
                    f"{p['pair']} @ "
                    f"${p['entry_price']:,.4f} "
                    f"[TP{tps_done}/3]"
                )
            pos_str = "\n" + "\n".join(pos_lines)
        else:
            pos_str = " None"

        pause_str = (
            "PAUSED" if self.is_paused
            else "Active"
        )

        self._send(
            f"<b>BOT STATUS</b>\n"
            f"========================\n"
            f"Mode       : {pause_str}\n"
            f"Balance    : ${balance:,.2f}\n"
            f"Daily P&L  : "
            f"${status['daily_pnl']:+,.2f}\n"
            f"Drawdown   : "
            f"{status['drawdown_pct']:.2f}%\n"
            f"========================\n"
            f"Open trades: {len(open_pos)}\n"
            f"Total trades: "
            f"{metrics['total_trades']}\n"
            f"Win rate   : {metrics['win_rate']}%\n"
            f"Total return: "
            f"{metrics['total_return']:+.2f}%\n"
            f"========================\n"
            f"<b>Positions:</b>{pos_str}\n"
            f"========================\n"
            f"Uptime: {self.health.get_uptime()}\n"
            f"Time: "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )

    def _cmd_positions(self):
        """Live positions from Bybit"""

        if not self.bot_ref or not hasattr(self.bot_ref, "exchange"):
            self._send("❌ Bybit client not available")
            return

        client = self.bot_ref.exchange

        positions = [
            p for p in client.get_positions()
            if float(p.get("size", 0)) > 0
        ]

        if not positions:
            self._send("<b>No open position</b>")
            return

        msg = "<b>LIVE POSITIONS</b>\n"

        for pos in positions:

            side = pos.get("side", "")
            size = float(pos.get("size", 0))
            entry = float(pos.get("avgPrice", 0))
            mark = float(pos.get("markPrice", 0))
            liq = float(pos.get("liqPrice", 0))
            pnl = float(pos.get("unrealisedPnl", 0))
            leverage = pos.get("leverage", "N/A")

            symbol = pos.get("symbol", "UNKNOWN")

            sl = pos.get("stopLoss", "Not Set")
            tp = pos.get("takeProfit", "Not Set")

            msg += (
                "\n========================\n"
                f"Pair      : {symbol}\n"
                f"Side      : {side}\n"
                f"Size      : {size}\n"
                f"Entry     : ${entry:,.4f}\n"
                f"Mark      : ${mark:,.4f}\n"
                f"SL        : {sl}\n"
                f"TP        : {tp}\n"
                f"Liq Price : ${liq:,.4f}\n"
                f"PnL       : ${pnl:+,.2f}\n"
                f"Leverage  : {leverage}x\n"
            )

        self._send(msg)

    def _cmd_balance(self):
        """Account balance."""
        balance = self.paper_trader.current_balance
        start   = self.paper_trader.starting_balance
        pnl     = balance - start
        pnl_pct = pnl / start * 100
        status  = self.risk_manager.get_status(balance)

        dd = status['drawdown_pct']

        self._send(
            "<b>ACCOUNT BALANCE</b>\n"
            "========================\n"
            f"Current  : ${balance:,.2f}\n"
            f"Starting : ${start:,.2f}\n"
            f"Total P&L: ${pnl:+,.2f} "
            f"({pnl_pct:+.2f}%)\n"
            f"========================\n"
            f"Today P&L: "
            f"${status['daily_pnl']:+,.2f}\n"
            f"Drawdown : {dd:.2f}%\n"
            f"Peak     : "
            f"${status['peak_balance']:,.2f}\n"
            f"========================\n"
            f"Open pos : "
            f"{len(self.paper_trader.open_positions)}\n"
            f"Consec L : "
            f"{status['consecutive_losses']}\n"
            f"Win rate : "
            f"{status['win_rate_pct']}%\n"
            f"Time: "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )

    def _cmd_trades(self):
        """Last 5 closed trades."""
        if not self.bot_ref or not hasattr(self.bot_ref, "exchange"):
            self._send("❌ Exchange not available")
            return

        closed = self.bot_ref.exchange.get_closed_pnl()

        if not closed:
            self._send(
                "<b>No closed trades yet</b>\n"
                "Trades appear here after closing."
            )
            return

        recent = list(reversed(closed[-5:]))

        total_pnl = sum(
            float(t.get("closedPnl", 0))
            for t in closed
        )

        wins = len(
            [
                t for t in closed
                if float(t.get("closedPnl", 0)) > 0
            ]
        )

        msg = (
            f"<b>LAST {len(recent)} TRADES</b> "
            f"(of {len(closed)} total)\n"
        )

        for trade in recent:
            pnl = float(trade.get("closedPnl", 0))
            entry = float(trade.get("avgEntryPrice", 0))
            exit_p = float(trade.get("avgExitPrice", 0))
            pair = trade.get("symbol", "?")
            direct = trade.get("side", "?")
            reason = trade.get("execType", "Closed")

            result = "WIN" if pnl > 0 else "LOSS"

            msg += (
                f"\n========================\n"
                f"{result}: {direct} {pair}\n"
                f"  Entry  : ${entry:,.4f}\n"
                f"  Exit   : ${exit_p:,.4f}\n"
                f"  P&L    : ${pnl:+,.2f}\n"
                f"  Reason : {reason}"
            )

        msg += (
            f"\n========================\n"
            f"Total: {len(closed)} trades | "
            f"{wins}W/{len(closed)-wins}L\n"
            f"Net P&L: ${total_pnl:+,.2f}"
        )

        self._send(msg)

    def _cmd_health(self):
        """Bot health check."""
        s = self.health.get_status()

        kill_status = (
            f"ACTIVE - {self.risk_manager.kill_reason}"
            if self.risk_manager.is_killed
            else "Inactive"
        )

        pause_str = (
            "PAUSED" if self.is_paused
            else "Running"
        )

        self._send(
            "<b>BOT HEALTH</b>\n"
            "========================\n"
            f"Status   : {s['reason']}\n"
            f"Trading  : {pause_str}\n"
            f"========================\n"
            f"Uptime   : {s['uptime']}\n"
            f"Cycles   : {s['total_cycles']}\n"
            f"Errors   : {s['total_errors']}\n"
            f"Last cycle: "
            f"{s['last_cycle_ago_secs']}s ago\n"
            f"========================\n"
            f"Kill SW  : {kill_status}\n"
            f"Time: "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )

    # ── CONTROL COMMANDS ──────────────────────────────────────

    def _cmd_pause(self):
        """Pause new signals."""
        if self.is_paused:
            self._send(
                "Bot is already paused.\n"
                "Send /resume to resume."
            )
            return

        self.is_paused = True
        if self.bot_ref:
            self.bot_ref.is_paused = True

        logger.warning("Bot PAUSED via Telegram")

        self._send(
            "<b>BOT PAUSED</b>\n"
            "========================\n"
            "No new trades will open.\n"
            "Existing trades still managed.\n"
            "Market monitoring continues.\n"
            "========================\n"
            "Send /resume to resume.\n"
            "Send /stop to stop completely.\n"
            f"Time: "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )

    def _cmd_resume(self):
        """Resume signals."""
        if not self.is_paused:
            self._send(
                "Bot is already running.\n"
                "Send /status for details."
            )
            return

        self.is_paused = False
        if self.bot_ref:
            self.bot_ref.is_paused = False

        logger.info("Bot RESUMED via Telegram")

        self._send(
            "<b>BOT RESUMED</b>\n"
            "========================\n"
            "Signal generation active.\n"
            "All pairs being scanned.\n"
            "========================\n"
            "Send /status for overview.\n"
            f"Time: "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )

    def _cmd_stop(self):
        """Stop bot safely."""
        open_count = len(
            self.paper_trader.open_positions
        )

        self._send(
            "<b>STOPPING BOT...</b>\n"
            "========================\n"
            f"Open positions: {open_count}\n"
            "Bot will stop after this.\n"
            "========================\n"
            "Send /start to restart later.\n"
            f"Time: "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )

        logger.warning("STOP via Telegram")

        if self.bot_ref:
            self.bot_ref.is_running = False

    def _cmd_kill(self):
        """Emergency stop."""
        self._send(
            "<b>EMERGENCY KILL</b>\n"
            "========================\n"
            "Stopping everything!\n"
            "Check positions manually!\n"
            f"Time: "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )

        logger.critical("KILL via Telegram!")

        if self.bot_ref:
            self.bot_ref.is_running = False
            self.risk_manager._activate_kill_switch(
                "Manual kill via Telegram"
            )

    # ── SEND ──────────────────────────────────────────────────

    def _send(self, message: str) -> bool:
        """Send reply to Telegram."""
        if not self.enabled:
            return False
        try:
            requests.post(
                f"{self.base_url}/sendMessage",
                data={
                    "chat_id"   : self.chat_id,
                    "text"      : message,
                    "parse_mode": "HTML",
                },
                timeout=10
            )
            return True
        except Exception as e:
            logger.debug(f"Telegram send error: {e}")
            return False