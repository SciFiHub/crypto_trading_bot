# ============================================================
# strategy/regime.py
# Detects the current market regime
# OUTPUT: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "NO_TRADE"
# ============================================================

import pandas as pd
import numpy as np
from loguru import logger


class RegimeDetector:
    """
    Classifies the current market into one of 4 regimes.

    Uses 3 measurements:
    1. EMA Alignment  → Are EMAs stacked in order?
    2. EMA Slope      → Are EMAs pointing up or down?
    3. ATR Percentile → Is volatility normal or extreme?
    """

    def __init__(self, config: dict):
        self.ema_fast         = config.get("EMA_FAST", 21)
        self.ema_medium       = config.get("EMA_MEDIUM", 50)
        self.ema_slow         = config.get("EMA_SLOW", 200)
        self.atr_period       = config.get("ATR_PERIOD", 14)
        self.slope_lookback   = 10    # Bars to measure EMA slope over
        self.atr_lookback     = 100   # Bars to compare ATR against
        self.slope_threshold  = 0.05  # Minimum slope % for trend
        self.volatile_pct     = 85    # ATR percentile above = volatile

    def detect(self, df: pd.DataFrame) -> str:
        """
        Main function — returns the current market regime.

        df = candle DataFrame with indicators already calculated

        Returns one of:
            "TRENDING_UP"   → Go LONG on pullbacks
            "TRENDING_DOWN" → Go SHORT on pullbacks
            "RANGING"       → Wait (range strategy later)
            "NO_TRADE"      → Stay out completely
        """

        # Need enough data to calculate everything
        min_bars = self.atr_lookback + self.slope_lookback
        if len(df) < min_bars:
            logger.warning(
                f"⚠️ Not enough bars for regime detection. "
                f"Need {min_bars}, have {len(df)}"
            )
            return "NO_TRADE"

        # Column names
        ema_fast_col   = f"ema_{self.ema_fast}"
        ema_medium_col = f"ema_{self.ema_medium}"
        ema_slow_col   = f"ema_{self.ema_slow}"
        atr_col        = f"atr_{self.atr_period}"

        # === MEASUREMENT 1: EMA Alignment ===
        # Check if EMAs are in bullish or bearish order
        alignment_score = self._get_alignment_score(
            df, ema_fast_col, ema_medium_col, ema_slow_col
        )

        # === MEASUREMENT 2: EMA Slope ===
        # Is the fast EMA pointing up or down?
        ema_slope_pct = self._get_ema_slope(
            df, ema_fast_col, self.slope_lookback
        )

        # === MEASUREMENT 3: Volatility Check ===
        # Is ATR at an extreme level right now?
        atr_percentile = self._get_atr_percentile(
            df, atr_col, self.atr_lookback
        )

        # === CLASSIFICATION ===
        regime = self._classify(
            alignment_score,
            ema_slope_pct,
            atr_percentile
        )

        # Log the measurements for transparency
        logger.debug(
            f"   Regime inputs → "
            f"Alignment: {alignment_score:+d} | "
            f"Slope: {ema_slope_pct:+.3f}% | "
            f"ATR%ile: {atr_percentile:.0f}"
        )
        logger.info(f"🧭 Market Regime: [{regime}]")

        return regime

    def _get_alignment_score(
        self,
        df: pd.DataFrame,
        fast_col: str,
        medium_col: str,
        slow_col: str
    ) -> int:
        """
        Score from -3 to +3 measuring EMA alignment.

        +3 = fully bullish (price > EMA21 > EMA50 > EMA200)
        -3 = fully bearish (price < EMA21 < EMA50 < EMA200)
         0 = mixed
        """
        latest = df.iloc[-1]

        price  = latest["close"]
        fast   = latest[fast_col]
        medium = latest[medium_col]
        slow   = latest[slow_col]

        score = 0

        # Each bullish relationship = +1, bearish = -1
        score += 1 if price  > fast   else -1
        score += 1 if fast   > medium else -1
        score += 1 if medium > slow   else -1

        return score

    def _get_ema_slope(
        self,
        df: pd.DataFrame,
        ema_col: str,
        lookback: int
    ) -> float:
        """
        Measures the slope of the EMA as a percentage.

        Slope = (current EMA - EMA N bars ago) / EMA N bars ago * 100

        Positive = EMA pointing UP
        Negative = EMA pointing DOWN
        Near zero = EMA is flat
        """
        current_ema = df[ema_col].iloc[-1]
        past_ema    = df[ema_col].iloc[-lookback]

        if past_ema == 0:
            return 0.0

        slope_pct = (current_ema - past_ema) / past_ema * 100
        return slope_pct

    def _get_atr_percentile(
        self,
        df: pd.DataFrame,
        atr_col: str,
        lookback: int
    ) -> float:
        """
        What percentile is the current ATR vs last N bars?

        100 = current ATR is the highest it's been in N bars (very volatile)
          0 = current ATR is the lowest it's been in N bars (very calm)
         50 = normal volatility
        """
        recent_atrs = df[atr_col].iloc[-lookback:].values
        current_atr = df[atr_col].iloc[-1]

        # Count how many historical ATRs are BELOW current ATR
        below_count = np.sum(recent_atrs < current_atr)
        percentile  = below_count / len(recent_atrs) * 100

        return percentile

    def _classify(
        self,
        alignment_score: int,
        slope_pct: float,
        atr_percentile: float
    ) -> str:
        """
        Combines the 3 measurements into a single regime label.

        Decision tree:
        1. If ATR is extreme → NO_TRADE (too dangerous)
        2. If EMAs fully bullish and slope positive → TRENDING_UP
        3. If EMAs fully bearish and slope negative → TRENDING_DOWN
        4. Everything else → RANGING
        """

        # Rule 1: Extreme volatility — always sit out
        if atr_percentile >= self.volatile_pct:
            return "NO_TRADE"

        # Rule 2: Strong uptrend
        # Need alignment ≥ 2 AND positive slope
        if (alignment_score >= 1 and
                slope_pct > self.slope_threshold):
            return "TRENDING_UP"

        # Rule 3: Strong downtrend
        # Need alignment ≤ -2 AND negative slope
        if (alignment_score <= -1 and
                slope_pct < -self.slope_threshold):
            return "TRENDING_DOWN"

        # Rule 4: Everything else is ranging/unclear
        return "RANGING"