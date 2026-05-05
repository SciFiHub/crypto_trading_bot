# ============================================================
# features/indicators.py (UPGRADED WITH ADX)
# ============================================================

import pandas as pd
import numpy as np
from loguru import logger


class IndicatorEngine:

    def __init__(self, config: dict):
        self.ema_fast   = config.get("EMA_FAST", 21)
        self.ema_medium = config.get("EMA_MEDIUM", 50)
        self.ema_slow   = config.get("EMA_SLOW", 200)
        self.atr_period = config.get("ATR_PERIOD", 14)
        self.rsi_period = 14
        self.vol_sma    = 20
        self.adx_period = 14   # ✅ NEW

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:

        if df.empty:
            logger.error("❌ Cannot calculate indicators on empty DataFrame")
            return df

        df = df.copy()
        logger.info("⚙️  Calculating indicators...")

        df = self._add_ema(df)
        df = self._add_atr(df)
        df = self._add_rsi(df)
        df = self._add_volume_sma(df)
        df = self._add_adx(df)   # ✅ NEW
        df = self._add_candle_features(df)

        df = df.dropna(subset=[f"ema_{self.ema_slow}"])
        df = df.reset_index(drop=True)

        logger.info(
            f"✅ Indicators calculated! "
            f"{len(df)} candles with full data."
        )

        return df

    def _add_ema(self, df: pd.DataFrame) -> pd.DataFrame:

        df[f"ema_{self.ema_fast}"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df[f"ema_{self.ema_medium}"] = df["close"].ewm(span=self.ema_medium, adjust=False).mean()
        df[f"ema_{self.ema_slow}"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()

        return df

    def _add_atr(self, df: pd.DataFrame) -> pd.DataFrame:

        prev_close = df["close"].shift(1)

        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"]  - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        df[f"atr_{self.atr_period}"] = true_range.ewm(span=self.atr_period, adjust=False).mean()

        return df

    def _add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:

        delta  = df["close"].diff()
        gains  = delta.clip(lower=0)
        losses = (-delta).clip(lower=0)

        avg_gain = gains.ewm(span=self.rsi_period, adjust=False).mean()
        avg_loss = losses.ewm(span=self.rsi_period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)

        df[f"rsi_{self.rsi_period}"] = 100 - (100 / (1 + rs))
        df[f"rsi_{self.rsi_period}"] = df[f"rsi_{self.rsi_period}"].fillna(50)

        return df

    def _add_volume_sma(self, df: pd.DataFrame) -> pd.DataFrame:

        df[f"volume_sma_{self.vol_sma}"] = df["volume"].rolling(window=self.vol_sma).mean()

        df["volume_ratio"] = (
            df["volume"] /
            df[f"volume_sma_{self.vol_sma}"].replace(0, np.nan)
        )

        return df

    # =======================
    # ✅ NEW: ADX FUNCTION
    # =======================
    def _add_adx(self, df: pd.DataFrame) -> pd.DataFrame:

        high = df["high"]
        low  = df["low"]
        close = df["close"]

        plus_dm  = high.diff()
        minus_dm = low.diff().abs()

        plus_dm  = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)

        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low  - close.shift()).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.rolling(self.adx_period).mean()

        plus_di  = 100 * (pd.Series(plus_dm).rolling(self.adx_period).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm).rolling(self.adx_period).mean() / atr)

        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100

        df["ADX"] = dx.rolling(self.adx_period).mean()

        return df

    def _add_candle_features(self, df: pd.DataFrame) -> pd.DataFrame:

        df["candle_color"] = np.where(
            df["close"] >= df["open"],
            "bullish",
            "bearish"
        )

        df["body_pct"] = (
            (df["close"] - df["open"]).abs() / df["open"] * 100
        )

        body_top    = df[["close", "open"]].max(axis=1)
        body_bottom = df[["close", "open"]].min(axis=1)

        df["upper_wick"] = df["high"] - body_top
        df["lower_wick"] = body_bottom - df["low"]

        return df