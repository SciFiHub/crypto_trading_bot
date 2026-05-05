# ============================================================
# test_signal.py
# Tests what signals would fire with adjusted settings
# Run this WITHOUT stopping the main bot
# ============================================================

from dotenv import load_dotenv
from loguru import logger
import sys

logger.remove()
logger.add(
    sys.stdout,
    format="<white>{message}</white>",
    colorize=True
)

from config.settings import (
    TRADING_PAIRS, TIMEFRAME, WARMUP_CANDLES,
    EMA_FAST, EMA_MEDIUM, EMA_SLOW, ATR_PERIOD,
    RISK_PER_TRADE, MAX_DAILY_LOSS,
    MAX_CONCURRENT_TRADES, MAX_DRAWDOWN,
    MIN_CONFIDENCE, MAX_POSITION_PCT,
    MAX_LEVERAGE, MIN_NOTIONAL
)
from data.binance_client import BinanceClient
from data.candle_manager import CandleManager
from features.indicators import IndicatorEngine
from strategy.trend_pullback import TrendPullbackStrategy
from risk.risk_manager import RiskManager

load_dotenv()

config = {
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
}


class RelaxedRegimeDetector:
    """
    Slightly relaxed regime detector for testing.
    Uses alignment >= 1 instead of >= 2
    """

    def __init__(self, config):
        self.ema_fast        = config.get("EMA_FAST", 21)
        self.ema_medium      = config.get("EMA_MEDIUM", 50)
        self.ema_slow        = config.get("EMA_SLOW", 200)
        self.atr_period      = config.get("ATR_PERIOD", 14)
        self.slope_lookback  = 10
        self.atr_lookback    = 100
        self.slope_threshold = 0.05
        self.volatile_pct    = 85

    def detect(self, df):
        import numpy as np

        min_bars = self.atr_lookback + self.slope_lookback
        if len(df) < min_bars:
            return "NO_TRADE"

        ema_fast_col   = f"ema_{self.ema_fast}"
        ema_medium_col = f"ema_{self.ema_medium}"
        ema_slow_col   = f"ema_{self.ema_slow}"
        atr_col        = f"atr_{self.atr_period}"

        latest = df.iloc[-1]
        price  = latest["close"]
        fast   = latest[ema_fast_col]
        medium = latest[ema_medium_col]
        slow   = latest[ema_slow_col]

        # Alignment score
        score = 0
        score += 1 if price  > fast   else -1
        score += 1 if fast   > medium else -1
        score += 1 if medium > slow   else -1

        # Slope
        current_ema = df[ema_fast_col].iloc[-1]
        past_ema    = df[ema_fast_col].iloc[-self.slope_lookback]
        slope_pct   = (current_ema - past_ema) / past_ema * 100

        # ATR percentile
        recent_atrs  = df[atr_col].iloc[-self.atr_lookback:].values
        current_atr  = df[atr_col].iloc[-1]
        below_count  = np.sum(recent_atrs < current_atr)
        atr_pct      = below_count / len(recent_atrs) * 100

        # Classify with relaxed threshold (1 instead of 2)
        if atr_pct >= self.volatile_pct:
            return "NO_TRADE"

        if alignment_score >= 1 and slope_pct > self.slope_threshold:
            return "TRENDING_UP"

        if alignment_score <= -1 and slope_pct < -self.slope_threshold:
            return "TRENDING_DOWN"

        return "RANGING"

    def detect(self, df):
        import numpy as np

        ema_fast_col   = f"ema_{self.ema_fast}"
        ema_medium_col = f"ema_{self.ema_medium}"
        ema_slow_col   = f"ema_{self.ema_slow}"
        atr_col        = f"atr_{self.atr_period}"

        latest = df.iloc[-1]
        price  = latest["close"]
        fast   = latest[ema_fast_col]
        medium = latest[ema_medium_col]
        slow   = latest[ema_slow_col]

        score = 0
        score += 1 if price  > fast   else -1
        score += 1 if fast   > medium else -1
        score += 1 if medium > slow   else -1

        current_ema = df[ema_fast_col].iloc[-1]
        past_ema    = df[ema_fast_col].iloc[-self.slope_lookback]
        slope_pct   = (current_ema - past_ema) / past_ema * 100

        recent_atrs = df[atr_col].iloc[-self.atr_lookback:].values
        current_atr = df[atr_col].iloc[-1]
        below_count = np.sum(recent_atrs < current_atr)
        atr_pct     = below_count / len(recent_atrs) * 100

        if atr_pct >= self.volatile_pct:
            return "NO_TRADE"

        # RELAXED: score >= 1 instead of >= 2
        if score >= 1 and slope_pct > self.slope_threshold:
            return "TRENDING_UP"

        if score <= -1 and slope_pct < -self.slope_threshold:
            return "TRENDING_DOWN"

        return "RANGING"


def main():
    print("\n" + "="*60)
    print("  🧪 SIGNAL TEST WITH RELAXED REGIME")
    print("  Testing alignment >= 1 (currently >= 2)")
    print("="*60)

    binance = BinanceClient(testnet=False)
    if not binance.connect():
        return

    candle_mgr       = CandleManager(binance.client)
    indicator_engine = IndicatorEngine(config)
    regime_detector  = RelaxedRegimeDetector(config)
    strategy         = TrendPullbackStrategy(config)
    risk_manager     = RiskManager(config)
    risk_manager.set_starting_balance(1000.0)

    signals_found = 0

    for pair in TRADING_PAIRS:
        print(f"\n📊 Testing {pair}...")

        df = candle_mgr.fetch_candles(
            symbol=pair,
            interval=TIMEFRAME,
            limit=WARMUP_CANDLES
        )
        if df.empty:
            continue

        df = indicator_engine.calculate(df)
        if df.empty:
            continue

        regime = regime_detector.detect(df)
        print(f"   Regime (relaxed): [{regime}]")

        signal = strategy.evaluate(df, regime)

        if signal:
            signals_found += 1
            decision = risk_manager.evaluate(
                signal, 1000.0
            )

            print(f"\n   🚨 SIGNAL FOUND!")
            print(f"   {'─'*40}")
            print(f"   Direction  : {signal.direction}")
            print(f"   Entry      : ${signal.entry_price:,.2f}")
            print(f"   Stop Loss  : ${signal.stop_loss:,.2f}")
            print(f"   TP1        : ${signal.take_profits[0]:,.2f}")
            print(f"   TP2        : ${signal.take_profits[1]:,.2f}")
            print(f"   Confidence : {signal.confidence:.0%}")
            print(f"   R:R        : {signal.risk_reward_ratio}")
            print(f"   Risk Check : {decision['reason']}")
            if decision['approved']:
                print(
                    f"   Position   : "
                    f"{decision['position_size']} BTC"
                )
                print(
                    f"   Risk $     : "
                    f"${decision['risk_amount']:.2f}"
                )
        else:
            print(f"   💤 No signal even with relaxed regime")

    print(f"\n{'='*60}")
    print(f"  RESULT: {signals_found} signals found")
    if signals_found > 0:
        print(f"  ✅ Relaxed regime WORKS — update regime.py")
    else:
        print(f"  ℹ️  Market not ready even with relaxed regime")
        print(f"  → Wait for market to develop a trend")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()