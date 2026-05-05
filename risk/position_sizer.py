# ============================================================
# risk/position_sizer.py
# Calculates exactly how much BTC to buy/sell per trade
# Based on fixed fractional position sizing
# ============================================================

from loguru import logger


class PositionSizer:
    """
    Calculates position size so that if our stop loss is hit,
    we lose EXACTLY our defined risk amount — no more.

    This is the core of professional risk management.
    """

    def __init__(self, config: dict):
        # Risk per trade as a decimal (0.01 = 1%)
        self.risk_per_trade   = config.get("RISK_PER_TRADE", 0.01)

        # Maximum position as % of account (prevents over-concentration)
        self.max_position_pct = config.get("MAX_POSITION_PCT", 0.20)

        # Maximum effective leverage allowed
        self.max_leverage     = config.get("MAX_LEVERAGE", 3.0)

        # Minimum order value in USDT (Binance rule)
        self.min_notional     = config.get("MIN_NOTIONAL", 10.0)

    def calculate(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        confidence: float = 1.0,
        consecutive_losses: int = 0
    ) -> dict:
        """
        Calculate the position size for a trade.

        Parameters:
            account_balance   : Current USDT balance
            entry_price       : Price we plan to enter at
            stop_loss         : Price where we exit if wrong
            confidence        : Signal confidence (0.0 to 1.0)
            consecutive_losses: How many losses in a row

        Returns a dict with:
            position_size  : Amount of BTC to buy/sell
            risk_amount    : Dollar amount we are risking
            notional_value : Total value of the position
            effective_leverage: How much leverage we're using
            approved       : True if size is valid, False if too small
        """

        # === BASE RISK CALCULATION ===
        base_risk_pct = self.risk_per_trade

        # === DYNAMIC RISK ADJUSTMENT ===
        # Reduce risk after consecutive losses (anti-martingale)
        if consecutive_losses >= 3:
            adjusted_risk_pct = base_risk_pct * 0.50
            logger.warning(
                f"⚠️ {consecutive_losses} consecutive losses. "
                f"Risk reduced to 50%: "
                f"{adjusted_risk_pct*100:.2f}%"
            )
        elif consecutive_losses == 2:
            adjusted_risk_pct = base_risk_pct * 0.75
            logger.warning(
                f"⚠️ {consecutive_losses} consecutive losses. "
                f"Risk reduced to 75%: "
                f"{adjusted_risk_pct*100:.2f}%"
            )
        else:
            adjusted_risk_pct = base_risk_pct

        # Scale by confidence
        # Minimum multiplier = 0.5 (never less than half normal size)
        confidence_multiplier = max(0.5, min(confidence, 1.0))
        final_risk_pct = adjusted_risk_pct * confidence_multiplier

        # === CORE FORMULA ===
        risk_amount    = account_balance * final_risk_pct
        stop_distance  = abs(entry_price - stop_loss)

        if stop_distance == 0:
            logger.error("❌ Stop distance is zero — invalid signal")
            return self._rejected("Stop distance is zero")

        # How many units of base currency to trade
        position_size  = risk_amount / stop_distance
        notional_value = position_size * entry_price
        leverage       = notional_value / account_balance

        # === SAFETY CAPS ===

        # Cap 1: Max position size as % of account
        max_notional = account_balance * self.max_position_pct
        if notional_value > max_notional:
            logger.debug(
                f"   Position capped at {self.max_position_pct*100:.0f}% "
                f"of account (${max_notional:,.2f})"
            )
            position_size  = max_notional / entry_price
            notional_value = max_notional
            leverage       = notional_value / account_balance

        # Cap 2: Maximum leverage
        if leverage > self.max_leverage:
            logger.debug(
                f"   Position capped at {self.max_leverage}x leverage"
            )
            notional_value = account_balance * self.max_leverage
            position_size  = notional_value / entry_price
            leverage       = self.max_leverage

        # Cap 3: Minimum order size (Binance rule)
        if notional_value < self.min_notional:
            return self._rejected(
                f"Position too small: "
                f"${notional_value:.2f} < ${self.min_notional} minimum"
            )

        # Round position size to 5 decimal places (BTC precision)
        position_size = round(position_size, 5)

        # Recalculate after rounding
        notional_value    = position_size * entry_price
        actual_risk       = position_size * stop_distance
        actual_risk_pct   = actual_risk / account_balance * 100

        result = {
            "approved"          : True,
            "position_size"     : position_size,
            "risk_amount"       : round(actual_risk, 2),
            "risk_pct"          : round(actual_risk_pct, 3),
            "notional_value"    : round(notional_value, 2),
            "effective_leverage": round(leverage, 2),
            "stop_distance"     : round(stop_distance, 2),
            "confidence_used"   : round(confidence_multiplier, 2),
            "rejection_reason"  : None,
        }

        return result

    def _rejected(self, reason: str) -> dict:
        """Returns a rejected result with explanation."""
        return {
            "approved"          : False,
            "position_size"     : 0,
            "risk_amount"       : 0,
            "risk_pct"          : 0,
            "notional_value"    : 0,
            "effective_leverage": 0,
            "stop_distance"     : 0,
            "confidence_used"   : 0,
            "rejection_reason"  : reason,
        }