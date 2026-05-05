# ============================================================
# risk/leverage_calculator.py
# Automatically calculates optimal leverage per trade
# Based on signal confidence + market volatility
# ============================================================

from loguru import logger
import numpy as np


class LeverageCalculator:
    """
    Calculates the optimal leverage for each trade.

    Logic:
    - Start with base leverage (3x)
    - Increase if signal is confident
    - Decrease if market is volatile (high ATR)
    - Always stay within safe limits

    Scale:
      1x  = very uncertain / very volatile
      3x  = normal conditions (default)
      5x  = good signal + normal volatility
      8x  = strong signal + low volatility
      10x = maximum (never exceeded)
    """

    def __init__(self, config: dict):
        self.base_leverage    = config.get(
            "BASE_LEVERAGE", 3
        )
        self.max_leverage     = config.get(
            "MAX_LEVERAGE", 10
        )
        self.min_leverage     = config.get(
            "MIN_LEVERAGE", 1
        )

    def calculate(
        self,
        confidence    : float,
        atr_percentile: float,
        regime        : str,
        consecutive_losses: int = 0
    ) -> int:
        """
        Calculate leverage for a trade.

        confidence     : Signal confidence 0.0-1.0
        atr_percentile : Current ATR vs history 0-100
        regime         : Market regime string
        consecutive_losses: How many losses in a row

        Returns: Integer leverage (1-10)
        """

        leverage = float(self.base_leverage)

        # ── CONFIDENCE ADJUSTMENT ─────────────────────
        # More confident signal = more leverage
        # confidence 0.55 → +0x bonus
        # confidence 0.75 → +2x bonus
        # confidence 0.90 → +4x bonus
        if confidence >= 0.90:
            leverage += 4.0
        elif confidence >= 0.80:
            leverage += 3.0
        elif confidence >= 0.70:
            leverage += 2.0
        elif confidence >= 0.60:
            leverage += 1.0
        # Below 0.60 → no bonus

        # ── VOLATILITY ADJUSTMENT ─────────────────────
        # High ATR = market is wild = reduce leverage
        # atr_percentile 0-30  = calm   → no penalty
        # atr_percentile 30-60 = normal → -1x
        # atr_percentile 60-80 = high   → -2x
        # atr_percentile 80+   = extreme → -3x
        if atr_percentile >= 80:
            leverage -= 3.0
        elif atr_percentile >= 60:
            leverage -= 2.0
        elif atr_percentile >= 30:
            leverage -= 1.0
        # Below 30 = very calm → no penalty

        # ── REGIME ADJUSTMENT ────────────────────────
        # Strong trend = slightly more leverage
        # Ranging = reduce leverage
        if "TRENDING" in regime:
            leverage += 1.0  # Trend is your friend
        elif regime == "RANGING":
            leverage -= 1.0  # Less certain in ranges

        # ── CONSECUTIVE LOSSES PENALTY ───────────────
        # After losses, be more conservative
        if consecutive_losses >= 3:
            leverage -= 2.0
        elif consecutive_losses == 2:
            leverage -= 1.0

        # ── APPLY LIMITS ─────────────────────────────
        leverage = max(
            self.min_leverage,
            min(self.max_leverage, leverage)
        )
        leverage = int(round(leverage))

        logger.info(
            f"Leverage calculated: {leverage}x "
            f"(conf={confidence:.0%}, "
            f"atr%ile={atr_percentile:.0f}, "
            f"regime={regime})"
        )

        return leverage

    def get_position_size(
        self,
        account_balance: float,
        entry_price    : float,
        stop_loss      : float,
        leverage       : int,
        risk_pct       : float = 0.01
    ) -> float:
        """
        Calculate position size in contracts
        given leverage and risk %.

        Formula:
          Risk amount = balance × risk_pct
          Stop distance = |entry - stop| / entry
          Position USDT = Risk / stop_distance
          Contracts = Position USDT × leverage / entry

        Example:
          Balance  = $1,000
          Risk     = 1% = $10
          Entry    = $77,000
          Stop     = $76,000
          Distance = 1.3%
          Leverage = 5x
          Position = $10 / 0.013 = $769 USDT
          Contracts= $769 × 5 / $77,000 = 0.05 BTC
        """
        if entry_price <= 0 or stop_loss <= 0:
            return 0.0

        stop_distance = (
            abs(entry_price - stop_loss) / entry_price
        )

        if stop_distance <= 0:
            return 0.0

        risk_amount    = account_balance * risk_pct
        position_usdt  = risk_amount / stop_distance
        contracts      = (
            position_usdt * leverage / entry_price
        )

        # Round to 3 decimal places
        contracts = round(contracts, 3)

        logger.info(
            f"Position size: {contracts} contracts "
            f"(${position_usdt:,.2f} USDT notional, "
            f"{leverage}x leverage)"
        )

        return contracts