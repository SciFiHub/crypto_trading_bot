# ============================================================
# data/bybit_candle_manager.py
# Fetches OHLCV candle data from Bybit Futures
# ============================================================

import pandas as pd
from loguru import logger
from data.bybit_client import BybitClient


class BybitCandleManager:
    """
    Fetches and manages candle data from Bybit.
    Returns clean pandas DataFrame.
    """

    def __init__(self, client: BybitClient):
        self.client = client

        # Bybit interval format
        self.interval_map = {
            "1m" : "1",
            "3m" : "3",
            "5m" : "5",
            "15m": "15",
            "30m": "30",
            "1h" : "60",
            "2h" : "120",
            "4h" : "240",
            "1d" : "D",
        }

    def fetch_candles(
        self,
        symbol  : str,
        interval: str,
        limit   : int = 300
    ) -> pd.DataFrame:
        """
        Fetch candles from Bybit.
        Returns clean OHLCV DataFrame.
        """

        if interval not in self.interval_map:
            logger.error(
                f"Invalid interval: {interval}"
            )
            return pd.DataFrame()

        bybit_interval = self.interval_map[interval]

        logger.info(
            f"Fetching {limit} candles "
            f"for {symbol} [{interval}]..."
        )

        try:
            raw = self.client.get_klines(
                symbol   = symbol,
                interval = bybit_interval,
                limit    = limit
            )

            if not raw:
                logger.warning(
                    f"No data for {symbol}"
                )
                return pd.DataFrame()

            # Bybit format:
            # [startTime, open, high, low,
            #  close, volume, turnover]
            df = pd.DataFrame(raw, columns=[
                "time", "open", "high",
                "low", "close", "volume", "turnover"
            ])

            # Convert types
            for col in ["open","high","low",
                        "close","volume"]:
                df[col] = df[col].astype(float)

            # Timestamp in milliseconds
            df["time"] = pd.to_datetime(
                df["time"].astype(float),
                unit="ms"
            )

            df = df[[
                "time","open","high",
                "low","close","volume"
            ]]
            df = df.reset_index(drop=True)

            # Validate
            zero_vol = (df["volume"] == 0).sum()
            if zero_vol > 0:
                logger.debug(
                    f"{zero_vol} zero-volume candles"
                )

            logger.info(
                f"Fetched {len(df)} candles!"
            )
            logger.info(
                f"   From: {df['time'].iloc[0]}"
            )
            logger.info(
                f"   To  : {df['time'].iloc[-1]}"
            )
            logger.info(
                f"   Last: "
                f"${df['close'].iloc[-1]:,.4f}"
            )

            return df

        except Exception as e:
            logger.error(
                f"Candle fetch error for {symbol}: {e}"
            )
            return pd.DataFrame()