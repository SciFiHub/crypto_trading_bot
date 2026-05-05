# ============================================================
# data/pair_scanner.py
# Automatically scans and selects top trading pairs
# Runs every hour to update the active pair list
# ============================================================

import time
from loguru import logger
from data.bybit_client import BybitClient


class PairScanner:
    """
    Scans all Bybit USDT Perpetual pairs.
    Ranks them by volume, volatility, and activity.
    Returns top N pairs for the bot to trade.

    Scoring formula:
    Score = (volume_rank * 0.5) +
            (range_rank * 0.3) +
            (trades_rank * 0.2)

    Higher score = better pair for trading
    """

    def __init__(
        self,
        client      : BybitClient,
        top_n       : int   = 10,
        min_price   : float = 0.01,
        min_volume  : float = 100_000,
    ):
        """
        client     : Bybit client connection
        top_n      : How many pairs to select
        min_price  : Minimum price filter
        min_volume : Minimum 24h volume in USDT
        """
        self.client       = client
        self.top_n        = top_n
        self.min_price    = min_price
        self.min_volume   = min_volume
        self.current_pairs = []
        self.last_scan     = 0
        self.scan_interval = 3600  # Rescan every 1 hour

        # Pairs to always skip
        self.skip_bases = [
            "USDC", "BUSD", "TUSD", "USDP",
            "USDD", "FDUSD", "DAI", "PAXG",
            "GUSD", "PYUSD"
        ]

        # Keywords to skip (leveraged tokens etc)
        self.skip_keywords = [
            "UP", "DOWN", "BULL", "BEAR",
            "3L", "3S", "2L", "2S",
            "1000000"
        ]

    def should_rescan(self) -> bool:
        """Check if it's time to rescan pairs."""
        now = time.time()
        elapsed = now - self.last_scan
        return elapsed >= self.scan_interval

    def get_active_pairs(
        self,
        force_rescan: bool = False
    ) -> list:
        """
        Get current active trading pairs.

        If cached pairs exist and not expired → return cache
        If expired or force_rescan → scan fresh

        Returns list of symbol strings.
        """

        if (self.current_pairs
                and not force_rescan
                and not self.should_rescan()):
            return self.current_pairs

        logger.info("Scanning all Bybit pairs...")
        new_pairs = self.scan()

        if new_pairs:
            self.current_pairs = new_pairs
            self.last_scan     = time.time()
            logger.info(
                f"Active pairs updated: "
                f"{len(new_pairs)} pairs"
            )
        else:
            logger.warning(
                "Scan returned no pairs! "
                "Keeping previous list."
            )

        return self.current_pairs

    def scan(self) -> list:
        """
        Full scan of all USDT Perpetual pairs.
        Returns top N pairs ranked by score.
        """
        if not self.client.client:
            logger.error(
                "Not connected to Bybit!"
            )
            return []

        try:
            # Fetch all tickers
            result = self.client.client.get_tickers(
                category="linear"
            )

            if result.get("retCode") != 0:
                logger.error(
                    f"Ticker fetch error: "
                    f"{result.get('retMsg')}"
                )
                return []

            tickers = result["result"]["list"]
            logger.info(
                f"Total tickers found: {len(tickers)}"
            )

            # Filter and collect valid pairs
            valid_pairs = []

            for ticker in tickers:
                symbol = ticker.get("symbol", "")

                # Only USDT pairs
                if not symbol.endswith("USDT"):
                    continue

                # Get base asset name
                base = symbol.replace("USDT", "")

                # Skip stablecoins
                if base in self.skip_bases:
                    continue

                # Skip leveraged tokens
                if any(kw in base
                       for kw in self.skip_keywords):
                    continue

                # Parse data safely
                try:
                    price    = float(
                        ticker.get("lastPrice", 0)
                    )
                    volume   = float(
                        ticker.get("turnover24h", 0)
                    )
                    high     = float(
                        ticker.get("highPrice24h", 0)
                    )
                    low      = float(
                        ticker.get("lowPrice24h", 0)
                    )
                    change   = float(
                        ticker.get(
                            "price24hPcnt", 0
                        )
                    ) * 100
                    vol_coin = float(
                        ticker.get("volume24h", 0)
                    )
                except (ValueError, TypeError):
                    continue

                # Apply filters
                if price < self.min_price:
                    continue
                if volume < self.min_volume:
                    continue

                # Calculate daily range %
                daily_range = 0.0
                if low > 0 and high > low:
                    daily_range = (
                        (high - low) / low * 100
                    )

                # Skip dead pairs (no movement)
                if daily_range < 0.1:
                    continue

                valid_pairs.append({
                    "symbol"     : symbol,
                    "base"       : base,
                    "price"      : price,
                    "volume"     : volume,
                    "vol_coin"   : vol_coin,
                    "daily_range": daily_range,
                    "change"     : change,
                })

            if not valid_pairs:
                logger.warning("No valid pairs found!")
                return []

            # ── RANK PAIRS ────────────────────────────────

            # Sort by volume to get volume rank
            valid_pairs.sort(
                key=lambda x: x["volume"],
                reverse=True
            )
            for i, p in enumerate(valid_pairs):
                p["volume_rank"] = i + 1

            # Sort by range to get volatility rank
            valid_pairs.sort(
                key=lambda x: x["daily_range"],
                reverse=True
            )
            for i, p in enumerate(valid_pairs):
                p["range_rank"] = i + 1

            # Calculate composite score
            total_pairs = len(valid_pairs)
            for p in valid_pairs:
                # Normalize ranks to 0-1
                # Lower rank number = better
                vol_score   = 1 - (
                    p["volume_rank"] / total_pairs
                )
                range_score = 1 - (
                    p["range_rank"] / total_pairs
                )

                # Weighted score
                p["score"] = (
                    vol_score   * 0.6 +
                    range_score * 0.4
                )

            # Sort by score (highest first)
            valid_pairs.sort(
                key=lambda x: x["score"],
                reverse=True
            )

            # Take top N
            top_pairs = valid_pairs[:self.top_n]

            # Log results
            logger.info(
                f"\n{'='*65}\n"
                f"TOP {len(top_pairs)} PAIRS "
                f"(from {len(valid_pairs)} valid)\n"
                f"{'='*65}"
            )
            logger.info(
                f"{'#':<4}"
                f"{'Symbol':<12}"
                f"{'Price':>12}"
                f"{'Volume':>16}"
                f"{'Range%':>8}"
                f"{'Score':>8}"
            )
            logger.info(f"{'─'*65}")

            for i, p in enumerate(top_pairs, 1):
                logger.info(
                    f"{i:<4}"
                    f"{p['symbol']:<12}"
                    f"${p['price']:>11,.4f}"
                    f"${p['volume']:>15,.0f}"
                    f"{p['daily_range']:>7.2f}%"
                    f"{p['score']:>8.3f}"
                )

            logger.info(f"{'='*65}")

            symbols = [p["symbol"] for p in top_pairs]

            return symbols

        except Exception as e:
            logger.error(f"Pair scan error: {e}")
            return []

    def print_current_pairs(self):
        """Print currently active pairs."""
        if not self.current_pairs:
            logger.info("No active pairs selected.")
            return

        logger.info(
            f"Active trading pairs "
            f"({len(self.current_pairs)}):"
        )
        for i, sym in enumerate(self.current_pairs, 1):
            logger.info(f"  {i}. {sym}")

    def get_pairs_summary(self) -> str:
        """
        Get pairs summary for Telegram.
        Returns formatted string.
        """
        if not self.current_pairs:
            return "No pairs selected"

        lines = []
        for i, sym in enumerate(self.current_pairs, 1):
            lines.append(f"  {i}. {sym}")

        return "\n".join(lines)