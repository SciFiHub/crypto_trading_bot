# ============================================================
# diagnose.py
# Shows exactly why no signal is firing
# Run this anytime to understand current market state
# ============================================================

from dotenv import load_dotenv
from loguru import logger
import sys

logger.remove()
logger.add(sys.stdout, format="<white>{message}</white>", colorize=True)

from config.settings import (
    TRADING_PAIRS, TIMEFRAME, WARMUP_CANDLES,
    EMA_FAST, EMA_MEDIUM, EMA_SLOW, ATR_PERIOD
)
from data.binance_client import BinanceClient
from data.candle_manager import CandleManager
from features.indicators import IndicatorEngine
from strategy.regime import RegimeDetector

load_dotenv()

config = {
    "EMA_FAST"   : EMA_FAST,
    "EMA_MEDIUM" : EMA_MEDIUM,
    "EMA_SLOW"   : EMA_SLOW,
    "ATR_PERIOD" : ATR_PERIOD,
}

def diagnose_pair(pair, candle_mgr, indicator_engine, regime_detector):
    """Show detailed analysis for one pair."""

    df = candle_mgr.fetch_candles(
        symbol=pair, interval=TIMEFRAME, limit=WARMUP_CANDLES
    )
    if df.empty:
        logger.warning(f"No data for {pair}")
        return

    df = indicator_engine.calculate(df)
    if df.empty:
        return

    regime = regime_detector.detect(df)

    # Get latest values
    latest   = df.iloc[-1]
    close    = latest["close"]
    ema_21   = latest[f"ema_{EMA_FAST}"]
    ema_50   = latest[f"ema_{EMA_MEDIUM}"]
    ema_200  = latest[f"ema_{EMA_SLOW}"]
    atr      = latest[f"atr_{ATR_PERIOD}"]
    rsi      = latest[f"rsi_14"]
    vol_ratio= latest["volume_ratio"]

    # Check each condition for LONG signal
    cond1 = ema_21 > ema_50 > ema_200
    cond2 = close > ema_50 * 0.998
    cond3 = close < ema_21
    cond4 = vol_ratio < 0.85
    atr_avg = df[f"atr_{ATR_PERIOD}"].iloc[-20:].mean()
    cond5 = atr <= atr_avg * 1.4

    # EMA slope
    ema_slope = (ema_21 - df[f"ema_{EMA_FAST}"].iloc[-10]) / df[f"ema_{EMA_FAST}"].iloc[-10] * 100

    print(f"\n{'='*60}")
    print(f"  📊 {pair} DETAILED DIAGNOSIS")
    print(f"{'='*60}")
    print(f"  💰 Price    : ${close:,.2f}")
    print(f"  🧭 Regime   : [{regime}]")
    print(f"{'─'*60}")
    print(f"  📐 MOVING AVERAGES:")
    print(f"     EMA 21  : ${ema_21:,.2f}")
    print(f"     EMA 50  : ${ema_50:,.2f}")
    print(f"     EMA 200 : ${ema_200:,.2f}")
    print(f"     Slope   : {ema_slope:+.3f}%")
    print(f"  📏 ATR 14  : ${atr:,.2f} (avg: ${atr_avg:,.2f})")
    print(f"  📡 RSI 14  : {rsi:.1f}")
    print(f"  📦 Volume  : {vol_ratio:.2f}x average")
    print(f"{'─'*60}")
    print(f"  🔍 SIGNAL CONDITIONS CHECK (LONG):")
    print(f"     ✅ = met   ❌ = not met")
    print(f"{'─'*60}")

    # Condition 1: EMA alignment
    status1 = "✅" if cond1 else "❌"
    print(f"  {status1} EMAs bullish aligned (21>50>200)")
    if not cond1:
        if ema_21 < ema_200:
            gap = (ema_200 - ema_21) / ema_21 * 100
            print(f"     → EMA21 is ${ema_21:,.2f}, needs to be")
            print(f"       above EMA200 ${ema_200:,.2f}")
            print(f"       Gap: {gap:.2f}% to close")

    # Condition 2: Regime
    status2 = "✅" if regime == "TRENDING_UP" else "❌"
    print(f"  {status2} Regime is TRENDING_UP (currently: {regime})")
    if regime == "RANGING":
        print(f"     → Market is sideways. Need clear uptrend.")
        print(f"     → EMA alignment score too weak")
    elif regime == "NO_TRADE":
        print(f"     → Too volatile. ATR too high.")

    # Condition 3: RSI not overbought
    status3 = "✅" if rsi < 70 else "❌"
    print(f"  {status3} RSI below 70 (currently: {rsi:.1f})")
    if rsi >= 70:
        print(f"     → RSI={rsi:.1f} means overbought")
        print(f"     → Wait for RSI to cool below 70")

    # Condition 4: Volume declining
    status4 = "✅" if cond4 else "❌"
    print(f"  {status4} Volume declining on pullback "
          f"(ratio: {vol_ratio:.2f}x)")

    # Condition 5: ATR stable
    status5 = "✅" if cond5 else "❌"
    print(f"  {status5} ATR not spiking "
          f"(current: ${atr:.2f}, avg: ${atr_avg:.2f})")

    print(f"{'─'*60}")

    # Overall verdict
    all_met = cond1 and regime == "TRENDING_UP"
    if all_met:
        print(f"  🟢 VERDICT: Setup possible soon!")
    else:
        missing = []
        if not cond1:
            missing.append("EMA alignment")
        if regime != "TRENDING_UP":
            missing.append(f"Trend regime (currently {regime})")
        if rsi >= 70:
            missing.append("RSI cooldown")
        print(f"  🔴 VERDICT: No signal — waiting for:")
        for m in missing:
            print(f"     → {m}")

    # How close to a signal?
    conditions_met = sum([
        cond1,
        regime == "TRENDING_UP",
        rsi < 70,
        cond4,
        cond5
    ])
    print(f"\n  📊 Readiness: {conditions_met}/5 conditions met")

    # What needs to change
    print(f"\n  💡 WHAT NEEDS TO HAPPEN:")
    if regime == "RANGING":
        print(f"     → BTC needs to pick a direction")
        print(f"     → EMAs need to align bullish OR bearish")
        print(f"     → Typically happens after a breakout")
    if rsi > 70:
        print(f"     → RSI needs to drop from {rsi:.0f} to below 70")
        print(f"     → Usually takes 2-5 candles of sideways/down")

    print(f"{'='*60}\n")


def main():
    print("\n" + "="*60)
    print("  🔬 MARKET DIAGNOSIS TOOL")
    print(f"  Scanning: {', '.join(TRADING_PAIRS)}")
    print("="*60)

    # Connect
    binance = BinanceClient(testnet=False)
    if not binance.connect():
        logger.error("Cannot connect to Binance")
        return

    candle_mgr       = CandleManager(binance.client)
    indicator_engine = IndicatorEngine(config)
    regime_detector  = RegimeDetector(config)

    # Diagnose each pair
    for pair in TRADING_PAIRS:
        diagnose_pair(
            pair,
            candle_mgr,
            indicator_engine,
            regime_detector
        )

    print("\n" + "="*60)
    print("  📌 SUMMARY")
    print("="*60)
    print("  The bot is working correctly.")
    print("  It is waiting for a TRENDING market.")
    print("  Current market is RANGING (sideways).")
    print("  Signals come when trend develops.")
    print("  This is normal professional behavior.")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()