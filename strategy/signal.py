# ============================================================
# strategy/signal.py
# Defines the Signal object — the output of our strategy
# A Signal is like a "trade proposal" with all details
# ============================================================

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class Signal:
    """
    A Signal represents a potential trade our strategy wants to make.

    dataclass = a simple Python class that holds data
    Think of it like a form with fields to fill in.

    Example filled signal:
        direction    = "LONG"
        entry_price  = 77500.00
        stop_loss    = 77000.00
        take_profits = [78000.00, 78500.00]
        confidence   = 0.70
        strategy_id  = "TREND_PULLBACK_LONG"
    """

    # === REQUIRED FIELDS ===
    direction: str          # "LONG" or "SHORT"
    entry_price: float      # Price to enter the trade
    stop_loss: float        # Price where we exit if wrong (loss limit)
    take_profits: List[float]  # List of prices to take profit
    strategy_id: str        # Which strategy generated this signal
    confidence: float       # How confident we are (0.0 to 1.0)

    # === OPTIONAL FIELDS (have default values) ===
    pair: str = "BTCUSDT"
    timeframe: str = "15m"
    regime: str = "UNKNOWN"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    invalidation_price: Optional[float] = None
    notes: str = ""

    def __post_init__(self):
        """
        Runs automatically after the signal is created.
        Validates that all values make sense.
        """
        # Direction must be LONG or SHORT
        if self.direction not in ["LONG", "SHORT"]:
            raise ValueError(
                f"direction must be 'LONG' or 'SHORT', "
                f"got '{self.direction}'"
            )

        # Confidence must be between 0 and 1
        if not 0 <= self.confidence <= 1:
            raise ValueError(
                f"confidence must be between 0 and 1, "
                f"got {self.confidence}"
            )

        # For LONG: stop must be BELOW entry
        if self.direction == "LONG":
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"LONG signal: stop_loss ({self.stop_loss}) "
                    f"must be BELOW entry ({self.entry_price})"
                )

        # For SHORT: stop must be ABOVE entry
        if self.direction == "SHORT":
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"SHORT signal: stop_loss ({self.stop_loss}) "
                    f"must be ABOVE entry ({self.entry_price})"
                )

    @property
    def risk_amount(self) -> float:
        """
        How many dollars of price movement from entry to stop.
        Used by risk manager to calculate position size.

        Example: Entry=77500, Stop=77000 → risk = $500 per BTC
        """
        return abs(self.entry_price - self.stop_loss)

    @property
    def risk_reward_ratio(self) -> float:
        """
        Ratio of potential reward to risk.
        Uses the FIRST take profit target.

        Example:
            Entry=77500, Stop=77000, TP1=78500
            Risk   = 77500 - 77000 = 500
            Reward = 78500 - 77500 = 1000
            R:R    = 1000 / 500    = 2.0
        """
        if not self.take_profits or self.risk_amount == 0:
            return 0.0

        first_tp = self.take_profits[0]
        reward = abs(first_tp - self.entry_price)
        return round(reward / self.risk_amount, 2)

    def summary(self) -> str:
        """
        Returns a clean one-line summary of the signal.
        Used for logging and Telegram alerts.
        """
        tp_str = " | ".join([f"${tp:,.2f}" for tp in self.take_profits])

        return (
            f"[{self.strategy_id}] "
            f"{self.direction} {self.pair} @ ${self.entry_price:,.2f} | "
            f"SL: ${self.stop_loss:,.2f} | "
            f"TPs: {tp_str} | "
            f"R:R={self.risk_reward_ratio} | "
            f"Conf={self.confidence:.0%}"
        )