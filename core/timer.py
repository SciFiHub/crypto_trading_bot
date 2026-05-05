# ============================================================
# core/timer.py
# Smart candle timer — waits until EXACTLY the next candle
# close before running the strategy cycle
# ============================================================

import time
from datetime import datetime, timezone
from loguru import logger


class CandleTimer:
    """
    Synchronizes the bot with Binance candle closes.

    Instead of sleeping a fixed 900 seconds (which drifts),
    we calculate exactly how many seconds until the NEXT
    15-minute candle closes and wait that long.

    Example:
        Current time : 16:32:47
        Next 15m mark: 16:45:00
        Wait time    : 12 minutes and 13 seconds exactly
    """

    def __init__(self, interval_minutes: int = 15):
        """
        interval_minutes = candle timeframe in minutes
        15 for 15m candles, 60 for 1h candles, etc.
        """
        self.interval_minutes  = interval_minutes
        self.interval_seconds  = interval_minutes * 60

        # Small buffer AFTER candle close
        # Wait 3 extra seconds to ensure Binance has finalized the candle
        self.close_buffer_secs = 3

    def seconds_until_next_candle(self) -> float:
        """
        Calculates how many seconds until the next candle closes.

        How it works:
        1. Get current UTC time in seconds
        2. Find the next multiple of 15 minutes
        3. Return the difference

        Example:
            Now      = 16:32:47 = 59567 seconds since midnight
            Interval = 900 seconds (15 minutes)
            Last mark= 59567 // 900 * 900 = 59400 = 16:30:00
            Next mark= 59400 + 900 = 60300 = 16:45:00
            Wait     = 60300 - 59567 = 733 seconds = 12m 13s
        """
        now = datetime.now(timezone.utc)

        # Seconds since midnight UTC
        seconds_since_midnight = (
            now.hour   * 3600 +
            now.minute * 60   +
            now.second
        )

        # How far into the current interval are we?
        seconds_into_interval = (
            seconds_since_midnight % self.interval_seconds
        )

        # How long until the NEXT interval?
        seconds_to_next = (
            self.interval_seconds - seconds_into_interval
        )

        # Add buffer to ensure candle is fully closed
        seconds_to_next += self.close_buffer_secs

        return seconds_to_next

    def wait_for_next_candle(self):
        """
        Blocks (waits) until the next candle close.
        Prints a countdown so you can see it's working.

        This is the key function — call this between cycles.
        """
        wait_seconds = self.seconds_until_next_candle()
        next_time    = self._get_next_candle_time()

        logger.info(
            f"⏳ Next candle close: "
            f"{next_time.strftime('%H:%M:%S')} UTC | "
            f"Waiting {wait_seconds:.0f} seconds "
            f"({wait_seconds/60:.1f} minutes)"
        )

        # Sleep in chunks so we can show progress
        # Every 60 seconds, print a status update
        remaining = wait_seconds

        while remaining > 0:
            if remaining > 60:
                # Show update every minute
                time.sleep(60)
                remaining -= 60
                logger.info(
                    f"   ⏳ {remaining:.0f}s until next candle..."
                )
            else:
                # Final countdown
                time.sleep(remaining)
                remaining = 0

        logger.info("🕯️  Candle closed! Running cycle...")

    def _get_next_candle_time(self) -> datetime:
        """Returns the datetime of the next candle close."""
        wait = self.seconds_until_next_candle()
        now  = datetime.now(timezone.utc)
        return datetime.fromtimestamp(
            now.timestamp() + wait,
            tz=timezone.utc
        )

    def run_immediately_then_wait(self) -> bool:
        """
        Returns True for the first cycle (run immediately),
        False for all subsequent cycles (wait for candle).

        Usage:
            first_run = True
            while True:
                if not first_run:
                    timer.wait_for_next_candle()
                run_cycle()
                first_run = False
        """
        return False  # Simplified — always wait after first run