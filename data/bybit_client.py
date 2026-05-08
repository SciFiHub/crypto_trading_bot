# ============================================================
# data/bybit_client.py
# Bybit connection manager
# Works on both local machine and Railway cloud
# Handles old and new pybit versions automatically
# ============================================================

import os
import time
import sys
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from pybit.unified_trading import HTTP


class BybitClient:
    """
    Bybit API client for Futures trading.

    Connection modes:
    - DEMO : api-demo.bybit.com (demo=True)
    - LIVE : api.bybit.com

    Automatically tries multiple methods
    to handle different pybit versions.
    """

    DEMO_ENDPOINT = "https://api-demo.bybit.com"
    LIVE_ENDPOINT = "https://api.bybit.com"

    def __init__(
        self,
        demo   : bool = True,
        testnet: bool = False
    ):
        self.api_key    = os.getenv("BYBIT_API_KEY", "")
        self.api_secret = os.getenv(
            "BYBIT_API_SECRET", ""
        )
        self.demo          = demo
        self.testnet       = testnet
        self.client        = None
        self.mode          = "DEMO" if demo else "LIVE"
        self.connected_via = None

        if not self.api_key or not self.api_secret:
            logger.error(
                "Bybit API keys not found!\n"
                "Add BYBIT_API_KEY and "
                "BYBIT_API_SECRET to environment."
            )
            raise ValueError(
                "Missing Bybit API keys."
            )

        logger.info(f"Bybit client mode: {self.mode}")
        logger.info(
            f"API key: {self.api_key[:6]}..."
            f"{self.api_key[-4:]}"
        )

    def connect(self, max_retries: int = 3) -> bool:
        """
        Connect to Bybit.
        Tries multiple methods automatically.
        Returns True if connected successfully.
        """
        # First test basic connectivity
        self._test_connectivity()

        for attempt in range(1, max_retries + 1):
            logger.info(
                f"Connecting to Bybit [{self.mode}]"
                f" ... attempt {attempt}/{max_retries}"
            )

            methods = self._get_connection_methods()

            for method_name, method_fn in methods:
                try:
                    logger.info(
                        f"   Trying {method_name}..."
                    )
                    client = method_fn()

                    if client is None:
                        continue

                    logger.info(
                        f"   Endpoint: {client.endpoint}"
                    )

                    # Test public endpoint first
                    server = client.get_server_time()
                    if server.get("retCode") != 0:
                        logger.warning(
                            f"   Server time failed: "
                            f"{server.get('retMsg')}"
                        )
                        continue

                    logger.info(
                        "   Server time OK"
                    )

                    # Test authenticated endpoint
                    balance = client.get_wallet_balance(
                        accountType="UNIFIED"
                    )
                    ret_code = balance.get("retCode", -1)

                    if ret_code == 0:
                        self.client        = client
                        self.connected_via = method_name
                        logger.info(
                            f"Connected to Bybit "
                            f"[{self.mode}] via "
                            f"'{method_name}'!"
                        )
                        return True

                    elif ret_code in [10003, 10004]:
                        logger.error(
                            f"   Auth failed "
                            f"(code {ret_code}): "
                            f"{balance.get('retMsg')}\n"
                            f"   Check your API keys!"
                        )

                    else:
                        logger.warning(
                            f"   Balance check: "
                            f"code={ret_code} "
                            f"msg={balance.get('retMsg')}"
                        )

                except TypeError as e:
                    if "demo" in str(e).lower():
                        logger.info(
                            f"   {method_name}: "
                            f"demo param not supported "
                            f"(old pybit) - skipping"
                        )
                    else:
                        logger.warning(
                            f"   {method_name} "
                            f"TypeError: {e}"
                        )

                except Exception as e:
                    logger.warning(
                        f"   {method_name} "
                        f"error: {e}"
                    )

            if attempt < max_retries:
                logger.info(
                    "Retrying in 5 seconds..."
                )
                time.sleep(5)

        logger.error(
            f"Failed to connect to Bybit "
            f"[{self.mode}] after "
            f"{max_retries} attempts.\n"
            f"Check your API keys and permissions."
        )
        return False

    def _test_connectivity(self):
        """
        Test basic internet connectivity to Bybit.
        Helps diagnose Railway network issues.
        """
        import requests as req

        endpoints = [
            (
                "Bybit Demo",
                f"{self.DEMO_ENDPOINT}/v5/market/time"
            ),
            (
                "Bybit Live",
                f"{self.LIVE_ENDPOINT}/v5/market/time"
            ),
        ]

        logger.info("Testing Bybit connectivity...")

        for name, url in endpoints:
            try:
                resp = req.get(url, timeout=8)
                if resp.status_code == 200:
                    logger.info(
                        f"   {name}: "
                        f"REACHABLE (200)"
                    )
                else:
                    logger.warning(
                        f"   {name}: "
                        f"HTTP {resp.status_code}"
                    )
            except req.exceptions.ConnectionError:
                logger.warning(
                    f"   {name}: "
                    f"CONNECTION REFUSED"
                )
            except req.exceptions.Timeout:
                logger.warning(
                    f"   {name}: TIMEOUT"
                )
            except Exception as e:
                logger.warning(
                    f"   {name}: {e}"
                )

    def _get_connection_methods(self) -> list:
        """
        Returns list of (name, function) tuples
        to try in order.
        """
        methods = []

        if self.demo:
            # Method 1: demo=True (pybit >= 5.4)
            def demo_param():
                return HTTP(
                    demo       = True,
                    api_key    = self.api_key,
                    api_secret = self.api_secret,
                )
            methods.append(
                ("demo=True", demo_param)
            )

            # Method 2: Endpoint override
            def demo_override():
                c = HTTP(
                    api_key    = self.api_key,
                    api_secret = self.api_secret,
                )
                c.endpoint = self.DEMO_ENDPOINT
                return c
            methods.append(
                ("demo endpoint override",
                 demo_override)
            )

            # Method 3: Live endpoint
            # (some demo keys work on live)
            def live_fallback():
                return HTTP(
                    api_key    = self.api_key,
                    api_secret = self.api_secret,
                )
            methods.append(
                ("live endpoint fallback",
                 live_fallback)
            )

        else:
            # Live mode
            def live():
                return HTTP(
                    api_key    = self.api_key,
                    api_secret = self.api_secret,
                )
            methods.append(("live", live))

        return methods

    def get_account_info(self) -> dict:
        """Get account balance."""
        if not self.client:
            return None

        try:
            result = self.client.get_wallet_balance(
                accountType="UNIFIED"
            )

            if result.get("retCode") != 0:
                logger.error(
                    f"Account error: "
                    f"{result.get('retMsg')}"
                )
                return None

            data = result["result"]["list"]
            if not data:
                return None

            account      = data[0]
            coins        = account.get("coin", [])
            usdt_balance = 0.0
            total_equity = float(
                account.get("totalEquity", 0)
            )

            logger.info("Bybit Account Balance:")

            for coin in coins:
                symbol = coin.get("coin", "")
                equity = float(
                    coin.get("equity", 0)
                )
                if equity > 0:
                    logger.info(
                        f"   {symbol}: "
                        f"${equity:,.4f}"
                    )
                if symbol == "USDT":
                    usdt_balance = equity

            if usdt_balance == 0 and total_equity > 0:
                usdt_balance = total_equity

            logger.info(
                f"USDT Balance: ${usdt_balance:,.2f}"
            )

            return {
                "usdt"       : usdt_balance,
                "accountType": "UNIFIED",
                "totalEquity": total_equity,
                "balances"   : [
                    {
                        "asset" : c.get("coin"),
                        "free"  : float(
                            c.get("equity", 0)
                        ),
                        "locked": 0.0,
                    }
                    for c in coins
                    if float(c.get("equity", 0)) > 0
                ]
            }

        except Exception as e:
            logger.error(
                f"Account fetch error: {e}"
            )
            return None

    def get_klines(
        self,
        symbol  : str,
        interval: str,
        limit   : int = 300
    ) -> list:
        """Fetch futures candle data."""
        if not self.client:
            return []

        try:
            result = self.client.get_kline(
                category = "linear",
                symbol   = symbol,
                interval = interval,
                limit    = limit
            )

            if result.get("retCode") != 0:
                logger.error(
                    f"Kline error for {symbol}: "
                    f"{result.get('retMsg')}"
                )
                return []

            candles = result["result"]["list"]
            if not candles:
                return []

            candles.reverse()
            return candles

        except Exception as e:
            logger.error(
                f"Kline error for {symbol}: {e}"
            )
            return []

    def get_current_price(
        self,
        symbol: str
    ) -> float:
        """Get current futures price."""
        if not self.client:
            return 0.0

        try:
            result = self.client.get_tickers(
                category = "linear",
                symbol   = symbol
            )

            if result.get("retCode") == 0:
                items = result["result"]["list"]
                if items:
                    return float(
                        items[0].get("lastPrice", 0)
                    )
            return 0.0

        except Exception as e:
            logger.debug(
                f"Price error for {symbol}: {e}"
            )
            return 0.0

    def set_leverage(
        self,
        symbol  : str,
        leverage: int
    ) -> bool:
        """Set leverage for a symbol."""
        if not self.client:
            return False

        try:
            result = self.client.set_leverage(
                category     = "linear",
                symbol       = symbol,
                buyLeverage  = str(leverage),
                sellLeverage = str(leverage)
            )

            code = result.get("retCode", -1)

            if code == 0:
                logger.info(
                    f"Leverage: {symbol} → {leverage}x"
                )
                return True

            if code == 110043:
                logger.debug(
                    f"Leverage already "
                    f"{leverage}x for {symbol}"
                )
                return True

            logger.error(
                f"Set leverage failed: "
                f"{result.get('retMsg')}"
            )
            return False

        except Exception as e:
            logger.error(
                f"Set leverage error: {e}"
            )
            return False

    def place_order(
        self,
        symbol      : str,
        side        : str,
        qty         : float,
        order_type  : str   = "Market",
        price       : float = None,
        stop_loss   : float = None,
        take_profit : float = None,
        reduce_only : bool  = False
    ) -> dict:
        """Place a futures order."""
        if not self.client:
            return {
                "success": False,
                "error"  : "Not connected"
            }

        try:
            params = {
                "category"   : "linear",
                "symbol"     : symbol,
                "side"       : side,
                "orderType"  : order_type,
                "qty"        : str(qty),
                "reduceOnly" : reduce_only,
                "timeInForce": "GTC",
            }

            if price and order_type == "Limit":
                params["price"] = str(
                    round(price, 4)
                )

            if stop_loss:
                params["stopLoss"] = str(
                    round(stop_loss, 4)
                )

            if take_profit:
                params["takeProfit"] = str(
                    round(take_profit, 4)
                )

            result = self.client.place_order(**params)
            code   = result.get("retCode", -1)

            if code == 0:
                order_id = result["result"]["orderId"]
                logger.info(
                    f"Order placed! "
                    f"{symbol} {side} {qty} "
                    f"| ID: {order_id}"
                )
                return {
                    "success"  : True,
                    "order_id" : order_id,
                    "symbol"   : symbol,
                    "side"     : side,
                    "qty"      : qty,
                }

            error = result.get(
                "retMsg", "Unknown error"
            )
            logger.error(f"Order failed: {error}")
            return {
                "success": False,
                "error"  : error
            }

        except Exception as e:
            logger.error(
                f"Place order error: {e}"
            )
            return {
                "success": False,
                "error"  : str(e)
            }

    def get_positions(self, symbol: str = None) -> list:
        """Get all open futures positions (optional symbol filter)."""
        if not self.client:
            return []

        try:
            result = self.client.get_positions(
                category="linear",
                settleCoin="USDT"
            )

            if result.get("retCode") != 0:
                logger.debug(
                    f"Positions error: {result.get('retMsg')}"
                )
                return []

            positions = [
                p for p in result["result"]["list"]
                if float(p.get("size", 0)) > 0
            ]

        # ✅ NEW: filter by symbol
            if symbol:
                positions = [
                    p for p in positions
                    if p.get("symbol") == symbol
                ]

            return positions

        except Exception as e:
            logger.debug(f"Get positions error: {e}")
            return []
        
    def get_closed_pnl(self, limit: int = 20) -> list:
        """Get recently closed trades / pnl."""

        if not self.client:
            return []

        try:
            result = self.client.get_closed_pnl(
                category="linear",
                limit=limit
            )

            if result.get("retCode") != 0:
                logger.error(
                    f"Closed PnL error: "
                    f"{result.get('retMsg')}"
                )
                return []

            return result["result"]["list"]

        except Exception as e:
            logger.error(
                f"Get closed pnl error: {e}"
            )
            return []    

    def close_position(self, symbol: str) -> bool:
        """Close open position for a symbol."""
        if not self.client:
            return False

        try:
            positions = self.get_positions()

            for pos in positions:
                if pos.get("symbol") != symbol:
                    continue

                size = float(pos.get("size", 0))
                side = pos.get("side", "")

                if size <= 0:
                    continue

                close_side = (
                    "Sell" if side == "Buy"
                    else "Buy"
                )

                result = self.place_order(
                    symbol      = symbol,
                    side        = close_side,
                    qty         = size,
                    order_type  = "Market",
                    reduce_only = True
                )

                if result.get("success"):
                    logger.info(
                        f"Position closed: {symbol}"
                    )
                    return True

            return False

        except Exception as e:
            logger.error(
                f"Close position error: {e}"
            )
            return False

    def get_symbol_info(self, symbol: str) -> dict:
        """Get symbol trading rules."""
        if not self.client:
            return {}

        try:
            result = self.client.get_instruments_info(
                category = "linear",
                symbol   = symbol
            )

            if result.get("retCode") != 0:
                return {}

            items = result["result"]["list"]
            if not items:
                return {}

            info         = items[0]
            lot          = info.get(
                "lotSizeFilter", {}
            )
            price_filter = info.get(
                "priceFilter", {}
            )
            lev_filter   = info.get(
                "leverageFilter", {}
            )

            return {
                "symbol"   : symbol,
                "min_qty"  : float(
                    lot.get("minOrderQty", 0.001)
                ),
                "qty_step" : float(
                    lot.get("qtyStep", 0.001)
                ),
                "tick_size": float(
                    price_filter.get("tickSize", 0.01)
                ),
                "max_lever": int(
                    float(
                        lev_filter.get(
                            "maxLeverage", 10
                        )
                    )
                ),
            }

        except Exception as e:
            logger.error(
                f"Symbol info error for {symbol}: {e}"
            )
            return {}

    def cancel_all_orders(
        self,
        symbol: str = None
    ) -> bool:
        """Cancel all open orders."""
        if not self.client:
            return False

        try:
            params = {"category": "linear"}
            if symbol:
                params["symbol"] = symbol

            result = self.client.cancel_all_orders(
                **params
            )

            if result.get("retCode") == 0:
                logger.info("All orders cancelled")
                return True
            return False

        except Exception as e:
            logger.error(
                f"Cancel orders error: {e}"
            )
            return False

    def ping(self) -> bool:
        """Quick health check."""
        if not self.client:
            return False
        try:
            result = self.client.get_server_time()
            return result.get("retCode") == 0
        except Exception:
            return False

    def is_connected(self) -> bool:
        """Check active connection."""
        return (
            self.client is not None and self.ping()
        )

    def get_demo_balance(self) -> float:
        """Quick USDT balance check."""
        info = self.get_account_info()
        if info:
            return info.get("usdt", 0.0)
        return 0.0