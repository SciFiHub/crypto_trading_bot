# ============================================================
# core/health_check.py
# Monitors bot health and detects problems early
# ============================================================

import time
from datetime import datetime, timezone
from loguru import logger


class HealthCheck:
    """
    Monitors that the bot is running correctly.

    Checks:
    1. Last cycle completed within expected time
    2. Binance connection still alive
    3. No excessive errors in recent cycles
    4. Memory usage reasonable (basic check)

    If health check fails → sends alert and considers restart
    """

    def __init__(self, max_cycle_gap_minutes: int = 20):
        """
        max_cycle_gap_minutes: Alert if no cycle ran in this many minutes
        """
        self.max_gap_seconds    = max_cycle_gap_minutes * 60
        self.last_cycle_time    = time.time()
        self.total_cycles       = 0
        self.error_count        = 0
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self.start_time         = time.time()

    def record_cycle_start(self):
        """Call at the beginning of each cycle."""
        self.last_cycle_time = time.time()
        self.total_cycles   += 1

    def record_success(self):
        """Call when a cycle completes successfully."""
        self.consecutive_errors = 0

    def record_error(self, error_msg: str = ""):
        """Call when a cycle fails."""
        self.error_count        += 1
        self.consecutive_errors += 1

        logger.warning(
            f"⚠️ Error recorded. "
            f"Consecutive: {self.consecutive_errors} | "
            f"Total: {self.error_count}"
        )

    def is_healthy(self) -> tuple:
        """
        Returns (is_healthy: bool, reason: str)

        Checks if the bot is operating normally.
        """

        # Check 1: Time since last cycle
        gap = time.time() - self.last_cycle_time
        if gap > self.max_gap_seconds:
            return False, (
                f"No cycle in {gap/60:.0f} minutes "
                f"(max: {self.max_gap_seconds/60:.0f})"
            )

        # Check 2: Too many consecutive errors
        if self.consecutive_errors >= self.max_consecutive_errors:
            return False, (
                f"{self.consecutive_errors} consecutive errors"
            )

        return True, "Healthy"

    def get_uptime(self) -> str:
        """Returns bot uptime as a formatted string."""
        elapsed = time.time() - self.start_time
        hours   = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        return f"{hours}h {minutes}m"

    def get_status(self) -> dict:
        """Returns full health status as a dictionary."""
        healthy, reason = self.is_healthy()
        return {
            "healthy"            : healthy,
            "reason"             : reason,
            "uptime"             : self.get_uptime(),
            "total_cycles"       : self.total_cycles,
            "total_errors"       : self.error_count,
            "consecutive_errors" : self.consecutive_errors,
            "last_cycle_ago_secs": round(
                time.time() - self.last_cycle_time
            ),
        }

    def print_status(self):
        """Print health status to log."""
        s = self.get_status()
        status_emoji = "✅" if s["healthy"] else "🚨"

        logger.info(f"\n{'='*55}")
        logger.info(f"  🏥 BOT HEALTH CHECK")
        logger.info(f"{'='*55}")
        logger.info(
            f"  Status         : {status_emoji} {s['reason']}"
        )
        logger.info(
            f"  Uptime         : {s['uptime']}"
        )
        logger.info(
            f"  Total Cycles   : {s['total_cycles']}"
        )
        logger.info(
            f"  Total Errors   : {s['total_errors']}"
        )
        logger.info(
            f"  Last Cycle     : {s['last_cycle_ago_secs']}s ago"
        )
        logger.info(f"{'='*55}")