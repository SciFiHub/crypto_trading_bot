# ============================================================
# bot_runner.py
# Bybit Futures Trading Bot
# Auto-scans and selects top pairs every hour
# Dynamic leverage support (1x-10x)
# Demo account trades visible on Bybit
# ============================================================

import io
import time
import sys
import numpy as np
from datetime import datetime, timezone
from loguru import logger
from dotenv import load_dotenv

from config.settings import (
    TRADING_PAIRS, TRADING_PAIR, TIMEFRAME, MODE,
    WARMUP_CANDLES, EMA_FAST, EMA_MEDIUM, EMA_SLOW,
    ATR_PERIOD, RISK_PER_TRADE, MAX_DAILY_LOSS,
    MAX_CONCURRENT_TRADES, MAX_DRAWDOWN, MIN_CONFIDENCE,
    MAX_POSITION_PCT, MIN_NOTIONAL, DEMO_MODE,
    BASE_LEVERAGE, MAX_LEVERAGE, MIN_LEVERAGE
)
from data.bybit_client import BybitClient
from data.bybit_candle_manager import BybitCandleManager
from data.pair_scanner import PairScanner
from features.indicators import IndicatorEngine
from strategy.regime import RegimeDetector
from strategy.trend_pullback import TrendPullbackStrategy
from strategy.signal import Signal
from risk.risk_manager import RiskManager
from risk.leverage_calculator import LeverageCalculator
from execution.bybit_executor import BybitExecutor
from monitoring.trade_journal import TradeJournal
from monitoring.telegram_alert import TelegramAlert
from monitoring.telegram_commands import TelegramCommands
from monitoring.performance import PerformanceTracker
from core.timer import CandleTimer
from core.health_check import HealthCheck

load_dotenv()

# ── LOGGING ───────────────────────────────────────────────
logger.remove()

logger.add(
    io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
        line_buffering=True
    ),
    level="INFO",
    format="{time:HH:mm:ss} | {level:<8} | {message}",
    colorize=False
)

logger.add(
    "logs/bot_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="14 days",
    level="DEBUG",
    encoding="utf-8",
    format=(
        "{time:YYYY-MM-DD HH:mm:ss} | "
        "{level:<8} | {name}:{line} | {message}"
    )
)

logger.add(
    "logs/errors.log",
    rotation="1 week",
    retention="1 month",
    level="ERROR",
    encoding="utf-8",
)


def build_config() -> dict:
    return {
        "EMA_FAST"             : EMA_FAST,
        "EMA_MEDIUM"           : EMA_MEDIUM,
        "EMA_SLOW"             : EMA_SLOW,
        "ATR_PERIOD"           : ATR_PERIOD,
        "RISK_PER_TRADE"       : RISK_PER_TRADE,
        "MAX_DAILY_LOSS"       : MAX_DAILY_LOSS,
        "MAX_CONCURRENT_TRADES": MAX_CONCURRENT_TRADES,
        "MAX_DRAWDOWN"         : MAX_DRAWDOWN,
        "MIN_CONFIDENCE"       : MIN_CONFIDENCE,
        "MAX_POSITION_PCT"     : MAX_POSITION_PCT,
        "MAX_LEVERAGE"         : MAX_LEVERAGE,
        "MIN_NOTIONAL"         : MIN_NOTIONAL,
        "BASE_LEVERAGE"        : BASE_LEVERAGE,
        "MIN_LEVERAGE"         : MIN_LEVERAGE,
    }


class TradingBot:
    """
    Bybit Futures Trading Bot.
    Auto-scans top pairs by volume and volatility.
    Trades with dynamic leverage on Demo account.
    """

    def __init__(self):
        self.config      = build_config()
        self.is_running  = False
        self.is_paused   = False
        self.cycle_count = 0
        self.pairs       = TRADING_PAIRS

        # All modules
        self.exchange         = None
        self.candle_mgr       = None
        self.pair_scanner     = None
        self.indicator_engine = None
        self.regime_detector  = None
        self.strategy         = None
        self.risk_manager     = None
        self.lev_calc         = None
        self.executor         = None
        self.journal          = None
        self.telegram         = None
        self.cmd_handler      = None
        self.performance      = None
        self.timer            = None
        self.health           = None
        self.usdt_balance     = 10000.0

        # Track trades
        self.open_trades   = []
        self.closed_trades = []

    # ──────────────────────────────────────────────────────
    # SETUP
    # ──────────────────────────────────────────────────────

    def setup(self) -> bool:
        """Initialize all modules."""
        logger.info("Setting up Bybit Futures Bot...")
        logger.info(
            f"Mode: {'DEMO' if DEMO_MODE else 'LIVE'}"
        )

        try:
            # Telegram
            self.telegram = TelegramAlert()

            # Bybit connection
            self.exchange = BybitClient(
                demo=DEMO_MODE
            )
            if not self.exchange.connect():
                logger.error("Cannot connect to Bybit!")
                return False

            # Get balance
            account = self.exchange.get_account_info()
            if account:
                usdt = account.get("usdt", 0)
                if usdt > 0:
                    self.usdt_balance = usdt

            logger.info(
                f"Demo balance: "
                f"${self.usdt_balance:,.2f} USDT"
            )

            # Parse timeframe
            if TIMEFRAME.endswith("m"):
                interval_mins = int(TIMEFRAME[:-1])
            elif TIMEFRAME.endswith("h"):
                interval_mins = int(TIMEFRAME[:-1]) * 60
            else:
                interval_mins = 15

            # Initialize modules
            self.candle_mgr = BybitCandleManager(
                self.exchange
            )

            self.pair_scanner = PairScanner(
                client     = self.exchange,
                top_n      = 10,
                min_price  = 0.01,
                min_volume = 100_000,
            )

            self.indicator_engine = IndicatorEngine(
                self.config
            )
            self.regime_detector = RegimeDetector(
                self.config
            )
            self.strategy = TrendPullbackStrategy(
                self.config
            )
            self.risk_manager = RiskManager(
                self.config
            )
            self.lev_calc = LeverageCalculator(
                self.config
            )
            self.executor = BybitExecutor(
                client   = self.exchange,
                config   = self.config,
                lev_calc = self.lev_calc
            )
            self.journal = TradeJournal(
                "logs/trade_journal.json"
            )
            self.performance = PerformanceTracker(
                self.usdt_balance
            )
            self.timer = CandleTimer(
                interval_minutes=interval_mins
            )
            self.health = HealthCheck(
                max_cycle_gap_minutes=interval_mins + 5
            )

            self.risk_manager.set_starting_balance(
                self.usdt_balance
            )

            # Telegram commands
            self.cmd_handler = TelegramCommands(
                paper_trader = self,
                risk_manager = self.risk_manager,
                performance  = self.performance,
                health       = self.health,
                bot_ref      = self
            )
            self.cmd_handler.start()

            # Initial pair scan
            logger.info("Running initial pair scan...")
            scanned = self.pair_scanner.get_active_pairs(
                force_rescan=True
            )
            if scanned:
                self.pairs = scanned

            logger.info("All modules initialized!")
            return True

        except Exception as e:
            logger.error(
                f"Setup failed: {e}", exc_info=True
            )
            return False

    # ──────────────────────────────────────────────────────
    # PROPERTIES for TelegramCommands compatibility
    # ──────────────────────────────────────────────────────

    @property
    def current_balance(self) -> float:
        try:
            account = self.exchange.get_account_info()
            if account:
                return account.get(
                    "usdt", self.usdt_balance
                )
        except Exception:
            pass
        return self.usdt_balance

    @property
    def starting_balance(self) -> float:
        return self.usdt_balance

    @property
    def open_positions(self) -> list:
        try:
            positions = self.exchange.get_positions()
            result = []
            for p in positions:
                entry = float(p.get("avgPrice", 0))
                size  = float(p.get("size", 0))
                sl    = float(p.get("stopLoss", 0))
                tp    = float(p.get("takeProfit", 0))
                side  = p.get("side", "Buy")
                sym   = p.get("symbol", "")
                pnl   = float(
                    p.get("unrealisedPnl", 0)
                )
                lev   = int(p.get("leverage", 1))

                result.append({
                    "pair"           : sym,
                    "direction"      : (
                        "LONG" if side == "Buy"
                        else "SHORT"
                    ),
                    "entry_price"    : entry,
                    "stop_loss"      : sl,
                    "take_profits"   : [tp],
                    "position_size"  : size,
                    "remaining_size" : size,
                    "scale_outs_done": 0,
                    "bars_open"      : 0,
                    "unrealized_pnl" : pnl,
                    "leverage"       : lev,
                })
            return result
        except Exception:
            return []

    @property
    def closed_positions(self) -> list:
        return self.closed_trades

    # ──────────────────────────────────────────────────────
    # MAIN CYCLE
    # ──────────────────────────────────────────────────────

    def run_cycle(self) -> bool:
        """Scan all pairs and execute signals."""
        self.cycle_count += 1
        self.health.record_cycle_start()

        # Auto-update pairs every hour
        if self.pair_scanner:
            updated = self.pair_scanner.get_active_pairs()
            if updated:
                self.pairs = updated

        now = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        logger.info(f"{'='*55}")
        logger.info(
            f"CYCLE #{self.cycle_count} | {now} UTC"
        )
        logger.info(
            f"Scanning {len(self.pairs)} pairs"
            + (" [PAUSED]" if self.is_paused else "")
        )
        logger.info(f"{'='*55}")

        try:
            signals_found  = 0
            trending_pairs = []
            ranging_pairs  = []

            for pair in self.pairs:
                logger.info(f"")
                logger.info(f"--- {pair} ---")

                result = self._analyze_pair(pair)

                if result == "SIGNAL":
                    signals_found += 1
                elif result == "TRENDING":
                    trending_pairs.append(pair)
                elif result == "RANGING":
                    ranging_pairs.append(pair)

            # Get live positions
            live_positions = self.exchange.get_positions()

            logger.info(f"{'─'*55}")
            logger.info(
                f"Cycle #{self.cycle_count} complete"
            )
            logger.info(
                f"Signals  : {signals_found}"
            )
            logger.info(
                f"Trending : {len(trending_pairs)}"
                + (f" ({','.join(trending_pairs)})"
                   if trending_pairs else "")
            )
            logger.info(
                f"Ranging  : {len(ranging_pairs)}"
            )
            logger.info(
                f"Live pos : {len(live_positions)}"
            )
            logger.info(f"{'─'*55}")

            # Periodic reports
            self._periodic_reports()

            # Kill switch
            if self.risk_manager.is_killed:
                logger.critical("KILL SWITCH!")
                self.telegram.kill_switch_alert(
                    self.risk_manager.kill_reason,
                    self.current_balance
                )
                self.is_running = False
                return False

            self.health.record_success()
            return True

        except Exception as e:
            logger.error(
                f"Cycle error: {e}", exc_info=True
            )
            self.health.record_error(str(e))
            self.telegram.error_alert(str(e))
            return False

    # ──────────────────────────────────────────────────────
    # ANALYZE ONE PAIR
    # ──────────────────────────────────────────────────────

    def _analyze_pair(self, pair: str) -> str:
        """Full analysis for one pair."""
        try:
            df = self.candle_mgr.fetch_candles(
                symbol   = pair,
                interval = TIMEFRAME,
                limit    = WARMUP_CANDLES
            )

            if df.empty:
                logger.warning(f"No data for {pair}")
                return "ERROR"

            current_price = df["close"].iloc[-1]
            logger.info(
                f"Price: ${current_price:,.4f}"
            )

            df = self.indicator_engine.calculate(df)
            if df.empty:
                return "ERROR"

            regime = self.regime_detector.detect(df)
            logger.info(f"Regime: [{regime}]")

            signal = self.strategy.evaluate(df, regime)

            if signal:
                signal.pair   = pair
                signal.regime = regime
                self._process_signal(signal, df, regime)
                return "SIGNAL"
            else:
                self._log_market_status(
                    pair, df, regime, current_price
                )
                if regime in [
                    "TRENDING_UP", "TRENDING_DOWN"
                ]:
                    return "TRENDING"
                return "RANGING"

        except Exception as e:
            logger.error(f"Error on {pair}: {e}")
            return "ERROR"

    # ──────────────────────────────────────────────────────
    # MARKET STATUS
    # ──────────────────────────────────────────────────────

    def _log_market_status(
        self,
        pair         : str,
        df,
        regime       : str,
        current_price: float
    ):
        """Show distance to signal zone."""

        if regime == "TRENDING_UP":
            latest    = df.iloc[-1]
            ema_21    = latest[f"ema_{EMA_FAST}"]
            ema_50    = latest[f"ema_{EMA_MEDIUM}"]
            rsi       = latest["rsi_14"]
            vol_ratio = latest["volume_ratio"]
            zone_top  = ema_21
            zone_bot  = ema_50 * 0.997

            if current_price > zone_top:
                dist = (
                    (current_price - zone_top)
                    / current_price * 100
                )
                logger.info(
                    f"TRENDING UP | "
                    f"Need pullback to "
                    f"${zone_bot:,.4f}-"
                    f"${zone_top:,.4f} | "
                    f"{dist:.2f}% above"
                )
            elif zone_bot <= current_price <= zone_top:
                logger.info(
                    f"*** IN ZONE! *** | "
                    f"RSI:{rsi:.1f} "
                    f"Vol:{vol_ratio:.2f}x | "
                    f"Waiting confirmation..."
                )
            else:
                logger.info(
                    f"Below zone | "
                    f"${current_price:,.4f}"
                )

        elif regime == "TRENDING_DOWN":
            latest   = df.iloc[-1]
            ema_21   = latest[f"ema_{EMA_FAST}"]
            ema_50   = latest[f"ema_{EMA_MEDIUM}"]
            zone_bot = ema_21
            zone_top = ema_50 * 1.003

            if current_price < zone_bot:
                dist = (
                    (zone_bot - current_price)
                    / current_price * 100
                )
                logger.info(
                    f"TRENDING DOWN | "
                    f"Need pullback UP to "
                    f"${zone_bot:,.4f}-"
                    f"${zone_top:,.4f} | "
                    f"{dist:.2f}% below"
                )
            elif zone_bot <= current_price <= zone_top:
                logger.info(
                    f"*** IN SHORT ZONE! *** | "
                    f"Waiting bearish confirmation..."
                )
            else:
                logger.info(
                    f"Above zone | "
                    f"${current_price:,.4f}"
                )

        elif regime == "NO_TRADE":
            logger.info("NO TRADE | Too volatile")

        else:
            rsi = df.iloc[-1].get("rsi_14", 50)
            logger.info(
                f"RANGING | RSI:{rsi:.1f} | "
                f"Waiting for trend"
            )

    # ──────────────────────────────────────────────────────
    # SIGNAL PROCESSING
    # ──────────────────────────────────────────────────────

    def _process_signal(
        self,
        signal: Signal,
        df,
        regime: str
    ):
        """Execute signal on Bybit Futures."""

        if self.is_paused:
            logger.info(
                f"Bot paused - skipped: "
                f"{signal.direction} {signal.pair}"
            )
            return

        # Check concurrent trades
        live_pos = self.exchange.get_positions()
        if len(live_pos) >= MAX_CONCURRENT_TRADES:
            logger.warning(
                f"Max trades reached "
                f"({MAX_CONCURRENT_TRADES}). "
                f"Skipping."
            )
            return

        # Check duplicate position
        pair_pos = [
            p for p in live_pos
            if p.get("symbol") == signal.pair
        ]
        if pair_pos:
            logger.info(
                f"Already in {signal.pair}. Skipping."
            )
            return

        # ATR percentile for leverage
        atr_col     = f"atr_{ATR_PERIOD}"
        atr_current = df[atr_col].iloc[-1]
        atr_history = df[atr_col].iloc[-100:].values
        atr_pct = float(
            np.sum(atr_history < atr_current)
            / len(atr_history) * 100
        )

        cons_losses = self.risk_manager.consecutive_losses

        # Risk check
        balance  = self.current_balance
        decision = self.risk_manager.evaluate(
            signal, balance
        )

        if not decision["approved"]:
            logger.warning(
                f"Signal rejected: "
                f"{decision['reason']}"
            )
            return

        logger.info(
            f"SIGNAL APPROVED: "
            f"{signal.direction} {signal.pair}"
        )

        # Execute on Bybit
        trade = self.executor.execute(
            signal             = signal,
            account_balance    = balance,
            atr_percentile     = atr_pct,
            consecutive_losses = cons_losses
        )

        if trade.get("success"):
            leverage  = trade.get("leverage", 1)
            contracts = trade.get("contracts", 0)
            notional  = trade.get("notional", 0)
            risk_usd  = trade.get("risk_usd", 0)

            # Telegram alert
            self.telegram.send(
                f"<b>BYBIT FUTURES TRADE</b>\n"
                f"========================\n"
                f"Pair     : {signal.pair}\n"
                f"Direction: {signal.direction}\n"
                f"Entry    : "
                f"${signal.entry_price:,.4f}\n"
                f"Stop Loss: "
                f"${signal.stop_loss:,.4f}\n"
                f"TP1      : "
                f"${signal.take_profits[0]:,.4f}\n"
                f"TP2      : "
                f"${signal.take_profits[1]:,.4f}\n"
                f"========================\n"
                f"Contracts: {contracts}\n"
                f"Leverage : {leverage}x\n"
                f"Notional : ${notional:,.2f}\n"
                f"Risk     : ${risk_usd:,.2f}\n"
                f"Confidence: "
                f"{signal.confidence:.0%}\n"
                f"========================\n"
                f"Check Bybit Demo!\n"
                f"Time: "
                f"{datetime.utcnow().strftime('%H:%M')}"
                f" UTC"
            )

            self.risk_manager.record_trade_opened(
                signal, contracts
            )

            self.journal.log_signal({
                "type"      : "BYBIT_TRADE",
                "direction" : signal.direction,
                "pair"      : signal.pair,
                "entry"     : signal.entry_price,
                "stop"      : signal.stop_loss,
                "tp"        : signal.take_profits,
                "contracts" : contracts,
                "leverage"  : leverage,
                "notional"  : notional,
                "risk_usd"  : risk_usd,
                "confidence": signal.confidence,
                "regime"    : regime,
                "order_id"  : trade.get("order_id"),
            })

            logger.info(
                "Trade visible in Bybit Demo!"
            )

        else:
            logger.error(
                f"Trade failed: "
                f"{trade.get('error')}"
            )

    # ──────────────────────────────────────────────────────
    # PERIODIC REPORTS
    # ──────────────────────────────────────────────────────

    def _periodic_reports(self):
        """Hourly and daily reports."""

        balance = self.current_balance

        # Every 4 cycles = 1 hour
        if self.cycle_count % 4 == 0:

            # Force rescan pairs
            if self.pair_scanner:
                new_pairs = (
                    self.pair_scanner.get_active_pairs(
                        force_rescan=True
                    )
                )
                if new_pairs:
                    self.pairs = new_pairs
                    logger.info(
                        f"Pairs rescanned: "
                        f"{', '.join(self.pairs)}"
                    )

            self.health.print_status()

            live_pos = self.exchange.get_positions()
            metrics  = self.performance.get_metrics(
                balance
            )

            # Build positions string
            if live_pos:
                pos_lines = []
                for p in live_pos:
                    sym  = p.get("symbol", "?")
                    side = p.get("side", "?")
                    size = float(p.get("size", 0))
                    pnl  = float(
                        p.get("unrealisedPnl", 0)
                    )
                    lev  = int(p.get("leverage", 1))
                    pos_lines.append(
                        f"  {side} {sym} "
                        f"x{size} [{lev}x] "
                        f"PnL:${pnl:+.2f}"
                    )
                pos_str = "\n" + "\n".join(pos_lines)
            else:
                pos_str = " None"

            # Build pairs string
            pairs_str = (
                self.pair_scanner.get_pairs_summary()
                if self.pair_scanner
                else ", ".join(self.pairs)
            )

            self.telegram.send(
                f"<b>HOURLY UPDATE</b> "
                f"Cycle #{self.cycle_count}\n"
                f"========================\n"
                f"Balance    : ${balance:,.2f}\n"
                f"Open trades: {len(live_pos)}\n"
                f"Total trades: "
                f"{metrics['total_trades']}\n"
                f"Win rate   : "
                f"{metrics['win_rate']}%\n"
                f"========================\n"
                f"<b>Positions:</b>{pos_str}\n"
                f"========================\n"
                f"<b>Active Pairs "
                f"({len(self.pairs)}):</b>\n"
                f"{pairs_str}\n"
                f"========================\n"
                f"Uptime: {self.health.get_uptime()}"
            )

        # Every 96 cycles = 24 hours
        if (self.cycle_count % 96 == 0
                and self.cycle_count > 0):

            status  = self.risk_manager.get_status(
                balance
            )
            metrics = self.performance.get_metrics(
                balance
            )
            self.telegram.daily_summary(
                balance      = balance,
                daily_pnl    = status["daily_pnl"],
                total_trades = metrics["total_trades"],
                win_rate     = metrics["win_rate"],
                open_trades  = len(
                    self.exchange.get_positions()
                )
            )

    # ──────────────────────────────────────────────────────
    # SHUTDOWN
    # ──────────────────────────────────────────────────────

    def shutdown(self):
        """Clean shutdown."""
        if self.cmd_handler:
            self.cmd_handler.stop()

        live_pos = self.exchange.get_positions()
        balance  = self.current_balance

        logger.info("=" * 55)
        logger.info("BOT SHUTTING DOWN")
        logger.info(f"Balance  : ${balance:,.2f}")
        logger.info(f"Open pos : {len(live_pos)}")
        logger.info("=" * 55)

        self.telegram.send(
            "<b>BOT STOPPED</b>\n"
            "========================\n"
            f"Uptime  : {self.health.get_uptime()}\n"
            f"Cycles  : {self.cycle_count}\n"
            f"Balance : ${balance:,.2f}\n"
            f"Open pos: {len(live_pos)}\n"
            "Positions remain active on Bybit.\n"
            "Send /start to restart."
        )

        logger.info("Shutdown complete.")

    # ──────────────────────────────────────────────────────
    # MAIN LOOP
    # ──────────────────────────────────────────────────────

    def run(self):
        """Main production loop."""

        logger.info("=" * 55)
        logger.info("BYBIT FUTURES TRADING BOT")
        logger.info(
            f"Mode   : "
            f"{'DEMO' if DEMO_MODE else 'LIVE'}"
        )
        logger.info(f"TF     : {TIMEFRAME}")
        logger.info(
            f"Lever  : {MIN_LEVERAGE}x-{MAX_LEVERAGE}x"
            f" (base {BASE_LEVERAGE}x)"
        )
        logger.info(
            "Auto-scanning top pairs by volume"
        )
        logger.info("=" * 55)

        if not self.setup():
            logger.error("Setup failed!")
            return

        self.telegram.bot_started(
            f"Bybit Futures | "
            f"{'Demo' if DEMO_MODE else 'Live'} | "
            f"Auto-scan top {len(self.pairs)} pairs",
            self.usdt_balance
        )

        self.is_running = True
        first_cycle     = True

        logger.info("Bot LIVE on Bybit Futures!")
        logger.info(
            f"Trading {len(self.pairs)} pairs "
            f"(auto-updated hourly)"
        )
        logger.info("=" * 55)

        while self.is_running:
            try:
                if not first_cycle:
                    self.timer.wait_for_next_candle()

                success     = self.run_cycle()
                first_cycle = False

                if not success:
                    if self.health.consecutive_errors >= 5:
                        logger.critical(
                            "Too many errors. Stopping."
                        )
                        break
                    logger.info(
                        "Retrying next candle..."
                    )

            except KeyboardInterrupt:
                logger.info("Stopped by user.")
                self.is_running = False
                break

            except Exception as e:
                logger.error(
                    f"Error: {e}", exc_info=True
                )
                self.health.record_error(str(e))
                self.telegram.error_alert(str(e))
                time.sleep(60)

        self.shutdown()


if __name__ == "__main__":
    bot = TradingBot()
    bot.run()