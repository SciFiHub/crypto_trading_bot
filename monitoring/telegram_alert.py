# ============================================================
# monitoring/telegram_alert.py
# Sends real-time alerts to your Telegram phone app
# ============================================================

import os
import requests
from loguru import logger
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


class TelegramAlert:
    """
    Sends messages to your Telegram phone.

    Uses Telegram's free Bot API.
    No paid services needed.

    Message types we send:
    - 🟢 Bot started
    - 🔵 Trade opened
    - ✅ Trade closed (profit)
    - ❌ Trade closed (loss)
    - 🎯 Take profit hit
    - 🛑 Stop loss hit
    - 🚨 Kill switch activated
    - 📊 Daily summary
    - ⚠️  Error alerts
    """

    def __init__(self):
        self.token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)

        # Base URL for Telegram API
        self.base_url = (
            f"https://api.telegram.org/bot{self.token}"
        )

        if self.enabled:
            logger.info("📱 Telegram alerts: ENABLED")
        else:
            logger.warning(
                "📱 Telegram alerts: DISABLED "
                "(no token/chat_id in .env)"
            )

    def send(self, message: str) -> bool:
        """
        Send any text message to your Telegram.

        Returns True if sent successfully, False if failed.
        """
        if not self.enabled:
            # Just log it locally if Telegram not configured
            logger.info(f"[TELEGRAM-DISABLED] {message}")
            return False

        try:
            url  = f"{self.base_url}/sendMessage"
            data = {
                "chat_id"    : self.chat_id,
                "text"       : message,
                "parse_mode" : "HTML",  # Allows bold, italic text
            }

            response = requests.post(url, data=data, timeout=10)

            if response.status_code == 200:
                logger.debug("📱 Telegram message sent")
                return True
            else:
                logger.warning(
                    f"📱 Telegram failed: "
                    f"{response.status_code} — {response.text}"
                )
                return False

        except requests.exceptions.Timeout:
            logger.warning("📱 Telegram timeout — skipping alert")
            return False

        except Exception as e:
            logger.warning(f"📱 Telegram error: {e}")
            return False

    # ── PRE-BUILT MESSAGE TEMPLATES ───────────────────────────

    def bot_started(self, pair: str, balance: float):
        """Send when bot starts up."""
        msg = (
            f"🟢 <b>BOT STARTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Pair     : {pair}\n"
            f"💰 Balance  : ${balance:,.2f} USDT\n"
            f"🕐 Time     : "
            f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Paper trading mode active ✅"
        )
        return self.send(msg)

    def trade_opened(
        self,
        direction: str,
        pair: str,
        entry: float,
        stop: float,
        tp1: float,
        tp2: float,
        size: float,
        risk_usd: float,
        strategy: str
    ):
        """Send when a new trade is opened."""
        emoji = "📈" if direction == "LONG" else "📉"
        risk_pct = (risk_usd / (size * entry) * 100) if size > 0 else 0

        msg = (
            f"{emoji} <b>TRADE OPENED [{direction}]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💱 Pair     : {pair}\n"
            f"🎯 Entry    : ${entry:,.2f}\n"
            f"🛑 Stop     : ${stop:,.2f}\n"
            f"✅ TP1      : ${tp1:,.2f}\n"
            f"✅ TP2      : ${tp2:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Size     : {size:.5f} BTC\n"
            f"⚠️  Risk     : ${risk_usd:.2f}\n"
            f"🧠 Strategy : {strategy}\n"
            f"🕐 Time     : "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )
        return self.send(msg)

    def trade_closed(
        self,
        direction: str,
        pair: str,
        entry: float,
        exit_price: float,
        pnl: float,
        reason: str,
        r_multiple: float = 0
    ):
        """Send when a trade closes."""
        emoji    = "✅" if pnl > 0 else "❌"
        pnl_sign = "+" if pnl > 0 else ""

        msg = (
            f"{emoji} <b>TRADE CLOSED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💱 Pair     : {pair} [{direction}]\n"
            f"🎯 Entry    : ${entry:,.2f}\n"
            f"🚪 Exit     : ${exit_price:,.2f}\n"
            f"💰 P&L      : {pnl_sign}${pnl:.2f}\n"
            f"📊 R-Multiple: {r_multiple:+.1f}R\n"
            f"📋 Reason   : {reason}\n"
            f"🕐 Time     : "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )
        return self.send(msg)

    def tp_hit(
        self,
        tp_number: int,
        pair: str,
        price: float,
        partial_pnl: float
    ):
        """Send when a take profit level is hit."""
        msg = (
            f"🎯 <b>TP{tp_number} HIT!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💱 Pair     : {pair}\n"
            f"💵 Price    : ${price:,.2f}\n"
            f"💰 Partial PnL: +${partial_pnl:.2f}\n"
            f"🔒 Stop moved to safer level\n"
            f"🕐 Time     : "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )
        return self.send(msg)

    def stop_loss_hit(
        self,
        pair: str,
        price: float,
        pnl: float
    ):
        """Send when stop loss is triggered."""
        msg = (
            f"🛑 <b>STOP LOSS HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💱 Pair     : {pair}\n"
            f"💵 Price    : ${price:,.2f}\n"
            f"💸 Loss     : ${pnl:.2f}\n"
            f"✅ Risk was managed. Moving on.\n"
            f"🕐 Time     : "
            f"{datetime.utcnow().strftime('%H:%M')} UTC"
        )
        return self.send(msg)

    def kill_switch_alert(self, reason: str, balance: float):
        """Send emergency kill switch alert."""
        msg = (
            f"🚨 <b>KILL SWITCH ACTIVATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️  Reason   : {reason}\n"
            f"💰 Balance  : ${balance:,.2f}\n"
            f"🛑 ALL TRADING HALTED\n"
            f"👤 Manual restart required\n"
            f"🕐 Time     : "
            f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        )
        return self.send(msg)

    def no_signal(self, regime: str, cycle: int):
        """
        Silent — we do NOT send Telegram for no-signal cycles.
        Too many messages. Just log locally.
        """
        logger.debug(
            f"[Cycle {cycle}] No signal. Regime: {regime}"
        )

    def daily_summary(
        self,
        balance: float,
        daily_pnl: float,
        total_trades: int,
        win_rate: float,
        open_trades: int
    ):
        """Send daily performance summary."""
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        pnl_sign  = "+" if daily_pnl >= 0 else ""

        msg = (
            f"📊 <b>DAILY SUMMARY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance   : ${balance:,.2f}\n"
            f"{pnl_emoji} Daily P&L  : "
            f"{pnl_sign}${daily_pnl:.2f}\n"
            f"📋 Trades    : {total_trades}\n"
            f"🏆 Win Rate  : {win_rate:.1f}%\n"
            f"🔢 Open Now  : {open_trades}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 "
            f"{datetime.utcnow().strftime('%Y-%m-%d')} UTC"
        )
        return self.send(msg)

    def error_alert(self, error_msg: str):
        """Send when a serious error occurs."""
        msg = (
            f"⚠️ <b>BOT ERROR</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"❌ {error_msg[:200]}\n"
            f"🕐 "
            f"{datetime.utcnow().strftime('%H:%M')} UTC\n"
            f"Bot is attempting to recover..."
        )
        return self.send(msg)