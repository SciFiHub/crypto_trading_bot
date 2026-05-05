# ============================================================
# execution/bybit_executor.py (FINAL - CLEAN, NO STATE)
# ============================================================

import time
from loguru import logger
from data.bybit_client import BybitClient
from strategy.signal import Signal
from risk.leverage_calculator import LeverageCalculator


class BybitExecutor:

    def __init__(
        self,
        client    : BybitClient,
        config    : dict,
        lev_calc  : LeverageCalculator
    ):
        self.client   = client
        self.config   = config
        self.lev_calc = lev_calc

        self.risk_pct   = config.get("RISK_PER_TRADE", 0.01)
        self.commission = 0.001

    # =========================
    # CHECK OPEN POSITION
    # =========================
    def _has_open_position(self, symbol: str) -> bool:
        try:
            positions = self.client.get_positions(symbol)

            for pos in positions:
                size = float(pos.get("size", 0))
                if size > 0:
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking positions: {e}")
            return True

    def execute(
        self,
        signal         : Signal,
        account_balance: float,
        atr_percentile : float = 50,
        consecutive_losses: int = 0
    ) -> dict:

        logger.info(
            f"Executing {signal.direction} "
            f"{signal.pair}..."
        )

        # =========================
        # EXCHANGE CHECK ONLY
        # =========================
        if self._has_open_position(signal.pair):
            logger.warning(
                f"⚠️ Already in position for {signal.pair} → skipping"
            )
            return {
                "success": False,
                "error": "Position already open"
            }

        # ── STEP 1: Leverage ──
        leverage = self.lev_calc.calculate(
            confidence         = signal.confidence,
            atr_percentile     = atr_percentile,
            regime             = signal.regime,
            consecutive_losses = consecutive_losses
        )

        self.client.set_leverage(
            symbol   = signal.pair,
            leverage = leverage
        )

        # ── STEP 2: Position size ──
        contracts = self.lev_calc.get_position_size(
            account_balance = account_balance,
            entry_price     = signal.entry_price,
            stop_loss       = signal.stop_loss,
            leverage        = leverage,
            risk_pct        = self.risk_pct
        )

        if contracts <= 0:
            return {"success": False, "error": "Invalid size"}

        symbol_info = self.client.get_symbol_info(signal.pair)
        min_qty  = symbol_info.get("min_qty", 0.001)
        qty_step = symbol_info.get("qty_step", 0.001)

        contracts = max(
            min_qty,
            round(contracts - (contracts % qty_step), 3)
        )

        side = "Buy" if signal.direction == "LONG" else "Sell"

        # ── STEP 3: Place order ──
        result = self.client.place_order(
            symbol      = signal.pair,
            side        = side,
            qty         = contracts,
            order_type  = "Market",
            stop_loss   = signal.stop_loss,
            take_profit = signal.take_profits[0],
        )

        if not result.get("success"):
            return {"success": False, "error": result.get("error")}

        # ── STEP 4: Trade record ──
        notional = contracts * signal.entry_price

        return {
            "success"   : True,
            "order_id"  : result.get("order_id"),
            "pair"      : signal.pair,
            "direction" : signal.direction,
            "contracts" : contracts,
            "leverage"  : leverage,
            "notional"  : round(notional, 2),
        }