# ============================================================
# data/candle_manager.py
# Fetches and manages candle (OHLCV) data from Binance
# Think of this as our "data warehouse"
# ============================================================

import pandas as pd                    # For data tables
from loguru import logger
from binance.client import Client
from binance.exceptions import BinanceAPIException
from datetime import datetime


class CandleManager:
    """
    Fetches candle data from Binance and returns it
    as a clean pandas DataFrame (a table with rows and columns).

    One row = one candle = one 15-minute period
    Columns = time, open, high, low, close, volume
    """

    def __init__(self, client: Client):
        """
        client = the Binance connection we already created
        We pass it in so we don't create a new connection every time
        """
        self.client = client

        # Map our simple interval names to Binance's format
        self.interval_map = {
            "1m":  Client.KLINE_INTERVAL_1MINUTE,
            "5m":  Client.KLINE_INTERVAL_5MINUTE,
            "15m": Client.KLINE_INTERVAL_15MINUTE,
            "1h":  Client.KLINE_INTERVAL_1HOUR,
            "4h":  Client.KLINE_INTERVAL_4HOUR,
            "1d":  Client.KLINE_INTERVAL_1DAY,
        }

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        limit: int = 300
    ) -> pd.DataFrame:
        """
        Fetch the most recent candles from Binance.

        symbol   = trading pair, e.g. "BTCUSDT"
        interval = timeframe, e.g. "15m"
        limit    = how many candles to fetch (max 1000)

        Returns: a pandas DataFrame (table) with clean candle data
        """

        # Check that the interval is one we support
        if interval not in self.interval_map:
            logger.error(
                f"❌ Invalid interval: {interval}. "
                f"Choose from: {list(self.interval_map.keys())}"
            )
            return pd.DataFrame()  # Return empty table

        logger.info(
            f"📥 Fetching {limit} candles for "
            f"{symbol} [{interval}]..."
        )

        try:
            # Ask Binance for candle data
            # Binance calls candles "klines"
            raw_candles = self.client.get_klines(
                symbol=symbol,
                interval=self.interval_map[interval],
                limit=limit
            )

            # raw_candles is a list of lists
            # Each inner list has 12 items — we only need the first 7
            # [0]=open_time, [1]=open, [2]=high, [3]=low,
            # [4]=close, [5]=volume, [6]=close_time, ...

            # Convert to a clean DataFrame (table)
            df = pd.DataFrame(raw_candles, columns=[
                "open_time",    # When the candle started (timestamp)
                "open",         # Opening price
                "high",         # Highest price
                "low",          # Lowest price
                "close",        # Closing price
                "volume",       # Volume traded
                "close_time",   # When the candle ended
                "quote_volume", # Volume in USDT
                "trades",       # Number of trades
                "taker_buy_base",
                "taker_buy_quote",
                "ignore"        # Binance sends this but we don't use it
            ])

            # === CLEAN THE DATA ===

            # Convert prices from text to numbers
            # (Binance sends everything as strings)
            numeric_columns = ["open", "high", "low", "close", "volume"]
            df[numeric_columns] = df[numeric_columns].astype(float)

            # Convert timestamps to readable datetime format
            # Binance sends time in milliseconds
            df["open_time"] = pd.to_datetime(
                df["open_time"], unit="ms"
            )
            df["close_time"] = pd.to_datetime(
                df["close_time"], unit="ms"
            )

            # Keep only the columns we need
            df = df[[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]]

            # Rename open_time to just "time" for simplicity
            df = df.rename(columns={"open_time": "time"})

            # Reset index (make rows numbered 0, 1, 2, 3...)
            df = df.reset_index(drop=True)

            # === VALIDATE THE DATA ===
            issues = self._validate(df)
            if issues > 0:
                logger.warning(
                    f"⚠️ Found {issues} data issues. "
                    f"Continuing anyway."
                )

            logger.info(
                f"✅ Fetched {len(df)} candles successfully!"
            )
            logger.info(
                f"   📅 From: {df['time'].iloc[0]}"
            )
            logger.info(
                f"   📅 To  : {df['time'].iloc[-1]}"
            )
            logger.info(
                f"   💰 Latest close price: "
                f"${df['close'].iloc[-1]:,.2f}"
            )

            return df

        except BinanceAPIException as e:
            logger.error(f"❌ Binance error fetching candles: {e}")
            return pd.DataFrame()

        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            return pd.DataFrame()

    def _validate(self, df: pd.DataFrame) -> int:
        """
        Basic data quality checks.
        Returns the number of issues found.
        """
        issues = 0

        # Check for missing values
        missing = df.isnull().sum().sum()
        if missing > 0:
            logger.warning(f"⚠️ Found {missing} missing values")
            issues += missing

        # Check for impossible OHLC values
        # High must always be >= Open, Close, Low
        bad_high = (df["high"] < df["low"]).sum()
        if bad_high > 0:
            logger.warning(
                f"⚠️ Found {bad_high} candles where high < low"
            )
            issues += bad_high

        # Check for zero or negative prices
        bad_price = (df["close"] <= 0).sum()
        if bad_price > 0:
            logger.warning(
                f"⚠️ Found {bad_price} candles with zero/negative price"
            )
            issues += bad_price

        # Check for zero volume
        zero_vol = (df["volume"] == 0).sum()
        if zero_vol > 0:
            logger.warning(
                f"⚠️ Found {zero_vol} candles with zero volume"
            )
            issues += zero_vol

        if issues == 0:
            logger.info("✅ Data validation passed — clean data!")

        return issues

    def print_sample(self, df: pd.DataFrame, rows: int = 5):
        """
        Print a sample of the candle data in a readable format.
        Useful for verifying the data looks correct.
        """
        if df.empty:
            logger.warning("⚠️ DataFrame is empty — nothing to show")
            return

        logger.info(f"\n{'='*65}")
        logger.info(f"📊 CANDLE DATA SAMPLE (last {rows} candles)")
        logger.info(f"{'='*65}")

        # Get last N rows
        sample = df.tail(rows)

        for _, row in sample.iterrows():
            logger.info(
                f"  🕯️  {row['time'].strftime('%Y-%m-%d %H:%M')} | "
                f"O: ${row['open']:>10,.2f} | "
                f"H: ${row['high']:>10,.2f} | "
                f"L: ${row['low']:>10,.2f} | "
                f"C: ${row['close']:>10,.2f} | "
                f"V: {row['volume']:>12,.3f}"
            )

        logger.info(f"{'='*65}")
        logger.info(f"Total candles in memory: {len(df)}")