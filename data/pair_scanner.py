# ============================================================
# data/pair_scanner.py
# Auto-scans Bybit Futures for top liquid trading pairs
# Filters out junk tokens and pump/dump coins
# Updates pairs list every hour automatically
# ============================================================

import time
from loguru import logger
from data.bybit_client import BybitClient


class PairScanner:
    """
    Scans Bybit USDT Perpetual Futures for best pairs.

    Selection criteria:
    1. High 24h turnover (liquid = easy to enter/exit)
    2. Reasonable daily range (volatile enough for signals)
    3. Good price (not dust/penny tokens)
    4. Established coins (not pump/dump tokens)

    Updates automatically every hour.
    Fallback to default pairs if scan fails.
    """

    def __init__(
        self,
        client    : BybitClient,
        top_n     : int   = 10,
        min_price : float = 0.005,
        min_volume: float = 5_000_000,
    ):
        self.client     = client
        self.top_n      = top_n
        self.min_price  = min_price
        self.min_volume = min_volume

        # Cache settings
        self.cached_pairs   = []
        self.last_scan_time = 0
        self.scan_interval  = 3600  # 1 hour

        # ── FILTER LISTS ──────────────────────────────────

        # Stablecoins to skip
        self.skip_bases = {
            "USDC", "BUSD", "TUSD", "USDP",
            "USDD", "FDUSD", "DAI", "PAXG",
            "GUSD", "PYUSD", "FRAX", "LUSD",
        }

        # Leveraged token keywords to skip
        self.skip_keywords = [
            "UP", "DOWN", "BULL", "BEAR",
            "3L", "3S", "2L", "2S", "5L", "5S",
            "10L", "10S",
        ]

        # Low quality / unknown tokens to skip
        self.skip_tokens = {
            "BSB", "ZBT", "PRL", "ORCA",
            "CHIP", "PENGU", "TRUMP", "MAGA",
            "PEPE2", "WOJAK", "LADYS",
        }

        # Quality filter thresholds
        self.min_daily_range = 0.3   # Min 0.3% daily range
        self.max_daily_range = 25.0  # Max 25% range (too wild)
        self.min_turnover    = 5_000_000  # Min $5M daily USDT volume

        # Preferred quality pairs
        # These get a score bonus if found
        self.quality_pairs = {
            "BTCUSDT", "ETHUSDT", "SOLUSDT",
            "XRPUSDT", "BNBUSDT", "DOGEUSDT",
            "ADAUSDT", "AVAXUSDT", "LINKUSDT",
            "DOTUSDT", "MATICUSDT", "NEARUSDT",
            "ATOMUSDT", "APTUSDT", "ARBUSDT",
            "OPUSDT",  "SUIUSDT",  "SEIUSDT",
            "INJUSDT", "TIAUSDT",  "ORDIUSDT",
        }

        # Fallback if scan completely fails
        self.fallback_pairs = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "XRPUSDT",
            "BNBUSDT",
            "DOGEUSDT",
            "ADAUSDT",
            "AVAXUSDT",
            "LINKUSDT",
            "DOTUSDT",
        ]

    def scan(self) -> list:
        """
        Scan Bybit for top USDT Perpetual pairs.

        Returns list of symbol strings sorted by quality score.
        """
        logger.info("Scanning Bybit pairs...")

        if not self.client or not self.client.client:
            logger.warning(
                "Not connected. Using fallback pairs."
            )
            return self.fallback_pairs

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
                return self.fallback_pairs

            tickers = result["result"]["list"]
            logger.info(
                f"Total tickers: {len(tickers)}"
            )

            pairs      = []
            skipped    = 0
            rejected   = 0

            for t in tickers:
                sym = t.get("symbol", "")

                # Only USDT perpetual
                if not sym.endswith("USDT"):
                    skipped += 1
                    continue

                base = sym.replace("USDT", "")

                # Skip stablecoins
                if base in self.skip_bases:
                    skipped += 1
                    continue

                # Skip leveraged tokens
                if any(
                    kw in base
                    for kw in self.skip_keywords
                ):
                    skipped += 1
                    continue

                # Skip known junk tokens
                if base in self.skip_tokens:
                    skipped += 1
                    continue

                # Parse values safely
                try:
                    price    = float(
                        t.get("lastPrice", 0) or 0
                    )
                    turnover = float(
                        t.get("turnover24h", 0) or 0
                    )
                    volume   = float(
                        t.get("volume24h", 0) or 0
                    )
                    high     = float(
                        t.get("highPrice24h", 0) or 0
                    )
                    low      = float(
                        t.get("lowPrice24h", 0) or 0
                    )
                except (ValueError, TypeError):
                    rejected += 1
                    continue

                # ── HARD FILTERS ──────────────────────────

                # Price filter
                if price < self.min_price:
                    rejected += 1
                    continue

                # Volume filter
                if turnover < self.min_turnover:
                    rejected += 1
                    continue

                # Very low price filter
                if price < 0.001:
                    rejected += 1
                    continue

                # ── CALCULATE METRICS ─────────────────────

                daily_range = 0.0
                if low > 0 and high > low:
                    daily_range = (
                        (high - low) / low * 100
                    )

                # Skip extreme volatility
                if daily_range > self.max_daily_range:
                    rejected += 1
                    continue

                # Skip too flat
                if daily_range < self.min_daily_range:
                    rejected += 1
                    continue

                # ── CALCULATE SCORE ───────────────────────
                # Score from 0.0 to 1.0
                # Higher = better for trading

                # Volume score (0.0 to 0.6)
                # $5B+ volume = max score
                vol_score = min(
                    turnover / 5_000_000_000, 1.0
                ) * 0.6

                # Range score (0.0 to 0.3)
                # 2-8% daily range is ideal
                if 2.0 <= daily_range <= 8.0:
                    range_score = 0.3
                elif daily_range < 2.0:
                    range_score = (
                        daily_range / 2.0 * 0.3
                    )
                else:
                    range_score = max(
                        0,
                        0.3 - (daily_range - 8) * 0.02
                    )

                # Quality bonus (0.0 to 0.1)
                quality_score = (
                    0.1 if sym in self.quality_pairs
                    else 0.0
                )

                total_score = (
                    vol_score
                    + range_score
                    + quality_score
                )

                pairs.append({
                    "symbol"     : sym,
                    "base"       : base,
                    "price"      : price,
                    "volume"     : volume,
                    "turnover"   : turnover,
                    "daily_range": daily_range,
                    "score"      : total_score,
                    "quality"    : (
                        sym in self.quality_pairs
                    ),
                })

            # Sort by score descending
            pairs.sort(
                key=lambda x: x["score"],
                reverse=True
            )

            total_valid = len(pairs)

            # Take top N
            top_pairs = pairs[:self.top_n]

            if not top_pairs:
                logger.warning(
                    "No pairs after filtering! "
                    "Using fallback."
                )
                return self.fallback_pairs

            # ── DISPLAY RESULTS ───────────────────────────
            logger.info(f"\n{'='*68}")
            logger.info(
                f"TOP {len(top_pairs)} PAIRS "
                f"(from {total_valid} valid "
                f"| {skipped} skipped "
                f"| {rejected} rejected)"
            )
            logger.info(f"{'='*68}")
            logger.info(
                f"{'#':<4}"
                f"{'Symbol':<14}"
                f"{'Price':>12}"
                f"{'Turnover':>18}"
                f"{'Range%':>8}"
                f"{'Score':>8}"
                f"{'Q':>4}"
            )
            logger.info(f"{'─'*68}")

            for i, p in enumerate(top_pairs, 1):
                quality_mark = "★" if p["quality"] else ""
                logger.info(
                    f"{i:<4}"
                    f"{p['symbol']:<14}"
                    f"${p['price']:>11,.4f}"
                    f"${p['turnover']:>17,.0f}"
                    f"{p['daily_range']:>7.2f}%"
                    f"{p['score']:>8.3f}"
                    f"{quality_mark:>4}"
                )

            logger.info(f"{'='*68}")
            logger.info(
                "★ = Established quality pair"
            )

            symbols = [p["symbol"] for p in top_pairs]

            logger.info(
                f"\nActive pairs: "
                f"{', '.join(symbols)}"
            )

            return symbols

        except Exception as e:
            logger.error(
                f"Scan error: {e}", exc_info=True
            )
            return self.fallback_pairs

    def get_active_pairs(
        self,
        force_rescan: bool = False
    ) -> list:
        """
        Get current active pairs.

        Uses cached result if scan was within 1 hour.
        Set force_rescan=True to scan immediately.

        Returns list of symbol strings.
        """
        now          = time.time()
        time_elapsed = now - self.last_scan_time
        cache_valid  = (
            bool(self.cached_pairs)
            and time_elapsed < self.scan_interval
        )

        if force_rescan or not cache_valid:

            reason = (
                "forced" if force_rescan
                else "cache expired"
                if self.cached_pairs
                else "first scan"
            )

            logger.info(
                f"Rescanning pairs ({reason})..."
            )

            new_pairs = self.scan()

            if new_pairs:
                old_pairs      = self.cached_pairs
                self.cached_pairs   = new_pairs
                self.last_scan_time = now

                # Log if pairs changed
                if old_pairs and old_pairs != new_pairs:
                    added   = [
                        p for p in new_pairs
                        if p not in old_pairs
                    ]
                    removed = [
                        p for p in old_pairs
                        if p not in new_pairs
                    ]
                    if added:
                        logger.info(
                            f"New pairs added: "
                            f"{', '.join(added)}"
                        )
                    if removed:
                        logger.info(
                            f"Pairs removed: "
                            f"{', '.join(removed)}"
                        )
            else:
                logger.warning(
                    "Scan returned empty. "
                    "Keeping previous pairs."
                )

        else:
            mins_left = int(
                (self.scan_interval - time_elapsed)
                / 60
            )
            logger.debug(
                f"Using cached pairs "
                f"(rescan in {mins_left}min)"
            )

        return (
            self.cached_pairs
            or self.fallback_pairs
        )

    def get_pairs_summary(self) -> str:
        """
        Get formatted summary for Telegram messages.
        """
        if not self.cached_pairs:
            return "  No pairs scanned yet"

        lines = []
        for i, sym in enumerate(
            self.cached_pairs, 1
        ):
            star = "★ " if sym in self.quality_pairs else "  "
            lines.append(f"{star}{i:>2}. {sym}")

        return "\n".join(lines)

    def add_quality_pair(self, symbol: str):
        """
        Manually add a pair to quality list.
        """
        self.quality_pairs.add(symbol)
        logger.info(
            f"Added {symbol} to quality pairs"
        )

    def add_skip_token(self, base: str):
        """
        Manually add a token to skip list.
        Forces rescan on next get_active_pairs call.
        """
        self.skip_tokens.add(base)
        self.last_scan_time = 0  # Force rescan
        logger.info(
            f"Added {base} to skip list. "
            f"Will rescan next cycle."
        )

    def set_filters(
        self,
        min_price       : float = None,
        min_volume      : float = None,
        min_daily_range : float = None,
        max_daily_range : float = None,
        top_n           : int   = None,
    ):
        """
        Update filter settings dynamically.
        Forces rescan on next call.
        """
        if min_price is not None:
            self.min_price = min_price
        if min_volume is not None:
            self.min_turnover = min_volume
        if min_daily_range is not None:
            self.min_daily_range = min_daily_range
        if max_daily_range is not None:
            self.max_daily_range = max_daily_range
        if top_n is not None:
            self.top_n = top_n

        self.last_scan_time = 0
        logger.info(
            f"Filters updated. "
            f"min_price=${self.min_price}, "
            f"min_vol=${self.min_turnover:,.0f}, "
            f"range={self.min_daily_range}"
            f"-{self.max_daily_range}%, "
            f"top_n={self.top_n}"
        )

    def get_scan_status(self) -> dict:
        """
        Get current scanner status.
        """
        now          = time.time()
        time_elapsed = now - self.last_scan_time
        next_scan    = max(
            0,
            self.scan_interval - time_elapsed
        )

        return {
            "cached_pairs"  : self.cached_pairs,
            "pair_count"    : len(self.cached_pairs),
            "last_scan_ago" : int(time_elapsed),
            "next_scan_in"  : int(next_scan),
            "top_n"         : self.top_n,
            "min_volume"    : self.min_turnover,
            "min_price"     : self.min_price,
        }