# ============================================================
# main.py
# Simple launcher — runs the production bot
# ============================================================

from bot_runner import TradingBot

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()