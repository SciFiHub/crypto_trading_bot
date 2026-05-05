# ============================================================
# strategy/trend_pullback.py (UPGRADED VERSION)
# Added:
# ✅ ADX sideways filter
# ✅ Better confirmation
# ============================================================

import pandas as pd
from loguru import logger
from typing import Optional
from strategy.signal import Signal


class TrendPullbackStrategy:

    def __init__(self, config: dict):
        self.ema_fast   = config.get("EMA_FAST", 21)
        self.ema_medium = config.get("EMA_MEDIUM", 50)
        self.ema_slow   = config.get("EMA_SLOW", 200)
        self.atr_period = config.get("ATR_PERIOD", 14)

        self.zone_buffer_pct = 0.003
        self.pullback_vol_threshold = 0.85
        self.atr_spike_threshold = 1.4

        # ✅ NEW: ADX threshold
        self.adx_threshold = 20

    def evaluate(self, df: pd.DataFrame, regime: str) -> Optional[Signal]:

        # ❌ SIDEWAYS FILTER (NEW)
        if "ADX" in df.columns:
            if df.iloc[-1]["ADX"] < self.adx_threshold:
                logger.debug("❌ ADX low → sideways market → skip")
                return None

        if regime == "TRENDING_UP":
            return self._check_long(df)

        elif regime == "TRENDING_DOWN":
            return self._check_short(df)

        return None

    def _check_long(self, df: pd.DataFrame) -> Optional[Signal]:

        ema_fast_col   = f"ema_{self.ema_fast}"
        ema_medium_col = f"ema_{self.ema_medium}"
        ema_slow_col   = f"ema_{self.ema_slow}"
        atr_col        = f"atr_{self.atr_period}"

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        close = curr["close"]
        low   = curr["low"]
        high  = curr["high"]
        open_ = curr["open"]

        ema_21  = curr[ema_fast_col]
        ema_50  = curr[ema_medium_col]
        ema_200 = curr[ema_slow_col]

        atr       = curr[atr_col]
        vol_ratio = curr["volume_ratio"]

        # EMA alignment
        if not (ema_21 > ema_50 > ema_200):
            return None

        # Pullback zone
        zone_top    = ema_21
        zone_bottom = ema_50 * (1 - self.zone_buffer_pct)

        if not (low <= zone_top and low >= zone_bottom):
            return None

        # ✅ IMPROVED CONFIRMATION (NEW)
        candle_range = high - low
        close_pos = (close - low) / candle_range if candle_range > 0 else 0.5

        is_bullish = close > open_
        strong_close = close_pos > 0.6

        # NEW: extra confirmation → price higher than previous close
        continuation = close > prev["close"]

        confirmation = (is_bullish and strong_close and continuation)

        if not confirmation:
            return None

        # Volume filter
        if vol_ratio > self.pullback_vol_threshold:
            return None

        # ATR filter
        recent_atr_avg = df[atr_col].iloc[-20:].mean()
        if atr > recent_atr_avg * self.atr_spike_threshold:
            return None

        # Build signal
        entry_price = close
        stop_loss = min(low, ema_50) - (atr * 0.5)
        risk = entry_price - stop_loss

        tp1 = entry_price + (risk * 1.5)
        tp2 = entry_price + (risk * 2.5)
        tp3 = entry_price + (risk * 4.0)

        confidence = 0.6
        if close_pos > 0.75:
            confidence += 0.05
        if vol_ratio < 0.7:
            confidence += 0.05

        return Signal(
            direction="LONG",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profits=[tp1, tp2, tp3],
            strategy_id="TREND_PULLBACK_LONG",
            confidence=min(confidence, 0.9),
            regime="TRENDING_UP"
        )

    def _check_short(self, df: pd.DataFrame) -> Optional[Signal]:

        ema_fast_col   = f"ema_{self.ema_fast}"
        ema_medium_col = f"ema_{self.ema_medium}"
        ema_slow_col   = f"ema_{self.ema_slow}"
        atr_col        = f"atr_{self.atr_period}"

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        close = curr["close"]
        low   = curr["low"]
        high  = curr["high"]
        open_ = curr["open"]

        ema_21  = curr[ema_fast_col]
        ema_50  = curr[ema_medium_col]
        ema_200 = curr[ema_slow_col]

        atr       = curr[atr_col]
        vol_ratio = curr["volume_ratio"]

        if not (ema_21 < ema_50 < ema_200):
            return None

        zone_bottom = ema_21
        zone_top    = ema_50 * (1 + self.zone_buffer_pct)

        if not (high >= zone_bottom and high <= zone_top):
            return None

        # ✅ IMPROVED CONFIRMATION (NEW)
        candle_range = high - low
        close_pos = (close - low) / candle_range if candle_range > 0 else 0.5

        is_bearish = close < open_
        weak_close = close_pos < 0.4

        continuation = close < prev["close"]

        confirmation = (is_bearish and weak_close and continuation)

        if not confirmation:
            return None

        if vol_ratio > self.pullback_vol_threshold:
            return None

        recent_atr_avg = df[atr_col].iloc[-20:].mean()
        if atr > recent_atr_avg * self.atr_spike_threshold:
            return None

        entry_price = close
        stop_loss = max(high, ema_50) + (atr * 0.5)
        risk = stop_loss - entry_price

        tp1 = entry_price - (risk * 1.5)
        tp2 = entry_price - (risk * 2.5)
        tp3 = entry_price - (risk * 4.0)

        confidence = 0.6
        if close_pos < 0.25:
            confidence += 0.05
        if vol_ratio < 0.7:
            confidence += 0.05

        return Signal(
            direction="SHORT",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profits=[tp1, tp2, tp3],
            strategy_id="TREND_PULLBACK_SHORT",
            confidence=min(confidence, 0.9),
            regime="TRENDING_DOWN"
        )