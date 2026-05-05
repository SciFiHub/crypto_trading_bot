# ============================================================
# data/binance_client.py
# Handles ALL communication with Binance
# Tries multiple endpoints automatically
# Works on local machine AND Railway cloud
# ============================================================

import os
import time
from binance.client import Client
from binance.exceptions import BinanceAPIException
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class BinanceClient:
    """
    Manages connection to Binance API.

    Automatically tries multiple Binance endpoints:
    1. api.binance.com  (global)
    2. api.binance.us   (US endpoint)
    3. api1.binance.com (backup)
    4. api2.binance.com (backup)

    This handles geographic restrictions on cloud servers.
    """

    def __init__(self, testnet: bool = False):
        """
        Initialize with API keys from environment variables.
        Works with both .env file (local) and
        Railway environment variables (cloud).
        """
        self.api_key    = os.getenv("BINANCE_API_KEY", "")
        self.api_secret = os.getenv("BINANCE_API_SECRET", "")
        self.testnet    = testnet
        self.client     = None
        self.connected_tld = None  # Which endpoint worked

        # ── VALIDATE API KEYS ─────────────────────────────
        if not self.api_key or not self.api_secret:
            logger.error(
                "API keys not found! "
                "Add BINANCE_API_KEY and "
                "BINANCE_API_SECRET to your "
                "environment variables."
            )
            raise ValueError("Missing Binance API keys.")

        # Check for placeholder text
        placeholder_words = [
            "your_api_key",
            "your_key",
            "paste_here",
            "xxx",
            "your_actual",
        ]
        for word in placeholder_words:
            if word in self.api_key.lower():
                logger.error(
                    "API key looks like a placeholder! "
                    "Replace with your real key."
                )
                raise ValueError(
                    "Placeholder API key detected."
                )

        logger.debug(
            f"API key loaded: "
            f"{self.api_key[:6]}..."
            f"{self.api_key[-4:]}"
        )

    def connect(self, max_retries: int = 3) -> bool:
        """
        Connect to Binance trying multiple endpoints.

        Tries each endpoint up to max_retries times.
        Automatically moves to next endpoint if blocked.

        Returns True if connected, False if all failed.
        """

        # List of endpoints to try in order
        endpoints = [
            {"tld": "com",  "name": "Global (binance.com)"},
            {"tld": "us",   "name": "US (binance.us)"},
        ]

        for endpoint in endpoints:
            tld  = endpoint["tld"]
            name = endpoint["name"]

            logger.info(f"Trying {name}...")

            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(
                        f"   Attempt {attempt}/{max_retries}"
                    )

                    # Create client for this endpoint
                    self.client = Client(
                        api_key    = self.api_key,
                        api_secret = self.api_secret,
                        tld        = tld,
                        requests_params={"timeout": 30}
                    )

                    # Test 1: Simple ping (no auth needed)
                    self.client.ping()
                    logger.debug("   Ping OK")

                    # Test 2: Server time (no auth needed)
                    server_time = self.client.get_server_time()
                    logger.debug("   Server time OK")

                    # Success!
                    self.connected_tld = tld
                    logger.info(
                        f"Successfully connected "
                        f"via {name}!"
                    )
                    logger.info(
                        f"Server time: "
                        f"{server_time['serverTime']}"
                    )
                    return True

                except BinanceAPIException as e:
                    logger.warning(
                        f"   Binance API error: "
                        f"{e.status_code} - {e.message}"
                    )

                    # Auth error — wrong key, don't retry
                    if e.status_code in [-2015, -2014]:
                        logger.error(
                            "Invalid API key or secret!"
                            "\nCheck your Binance settings:"
                            "\n1. Enable Reading permission"
                            "\n2. Set IP to Unrestricted"
                        )
                        return False

                    # Rate limit — wait longer
                    if e.status_code == 429:
                        logger.warning(
                            "Rate limited. Waiting 30s..."
                        )
                        time.sleep(30)
                        continue

                    if attempt < max_retries:
                        logger.info(
                            "   Retrying in 5 seconds..."
                        )
                        time.sleep(5)

                except Exception as e:
                    error_str = str(e).lower()

                    # Geographic block
                    if any(code in str(e)
                           for code in ["451", "403"]):
                        logger.warning(
                            f"   {name} is blocked "
                            f"in this region."
                        )
                        break  # Skip to next endpoint

                    # Connection refused
                    if "connection" in error_str:
                        logger.warning(
                            f"   Connection failed: {e}"
                        )
                        if attempt < max_retries:
                            logger.info(
                                "   Retrying in 5 seconds..."
                            )
                            time.sleep(5)
                        continue

                    # Timeout
                    if "timeout" in error_str:
                        logger.warning(
                            f"   Timeout on attempt "
                            f"{attempt}"
                        )
                        if attempt < max_retries:
                            time.sleep(5)
                        continue

                    # Unknown error
                    logger.warning(
                        f"   Unknown error: {e}"
                    )
                    if attempt < max_retries:
                        time.sleep(5)

        # All endpoints failed
        logger.error(
            "All Binance endpoints failed!"
            "\nPossible fixes:"
            "\n1. Change Railway region to Singapore"
            "\n2. Check API key permissions on Binance"
            "\n3. Check internet connectivity"
        )
        return False

    def get_account_info(self) -> dict:
        """
        Fetch account information.
        Returns account dict or None if failed.
        """
        if not self.client:
            logger.error(
                "Not connected to Binance. "
                "Call connect() first."
            )
            return None

        try:
            account = self.client.get_account()

            # Get non-zero balances only
            non_zero = [
                asset
                for asset in account["balances"]
                if float(asset["free"]) > 0
                or float(asset["locked"]) > 0
            ]

            logger.info(
                f"Account type: {account['accountType']}"
            )

            if non_zero:
                logger.info("Assets with balance:")
                for asset in non_zero:
                    free   = float(asset["free"])
                    locked = float(asset["locked"])
                    logger.info(
                        f"   {asset['asset']}: "
                        f"Free={free:.8f}, "
                        f"Locked={locked:.8f}"
                    )
            else:
                logger.info(
                    "No assets with balance found."
                )

            return account

        except BinanceAPIException as e:
            logger.error(
                f"Error fetching account: "
                f"{e.status_code} - {e.message}"
            )
            return None

        except Exception as e:
            logger.error(
                f"Unexpected error fetching account: {e}"
            )
            return None

    def get_symbol_info(self, symbol: str) -> dict:
        """
        Get trading rules for a symbol.
        Example: minimum order size, price precision.
        """
        if not self.client:
            return None

        try:
            info = self.client.get_symbol_info(symbol)

            if info is None:
                logger.error(
                    f"Symbol {symbol} not found on Binance."
                )
                return None

            filters = {
                f["filterType"]: f
                for f in info["filters"]
            }

            rules = {
                "symbol"      : symbol,
                "base_asset"  : info["baseAsset"],
                "quote_asset" : info["quoteAsset"],
                "min_qty"     : float(
                    filters["LOT_SIZE"]["minQty"]
                ),
                "step_size"   : float(
                    filters["LOT_SIZE"]["stepSize"]
                ),
                "min_notional": float(
                    filters.get(
                        "MIN_NOTIONAL", {}
                    ).get("minNotional", 10)
                ),
                "tick_size"   : float(
                    filters["PRICE_FILTER"]["tickSize"]
                ),
            }

            logger.info(
                f"Trading rules for {symbol}:"
            )
            logger.info(
                f"   Min qty   : {rules['min_qty']}"
            )
            logger.info(
                f"   Step size : {rules['step_size']}"
            )
            logger.info(
                f"   Min order : "
                f"${rules['min_notional']} USDT"
            )
            logger.info(
                f"   Tick size : {rules['tick_size']}"
            )

            return rules

        except BinanceAPIException as e:
            logger.error(
                f"Error fetching symbol info: {e}"
            )
            return None

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None

    def get_current_price(self, symbol: str) -> float:
        """
        Get current market price for a symbol.
        Returns 0.0 if failed.
        """
        if not self.client:
            return 0.0

        try:
            ticker = self.client.get_symbol_ticker(
                symbol=symbol
            )
            return float(ticker["price"])

        except Exception as e:
            logger.error(
                f"Error getting price for {symbol}: {e}"
            )
            return 0.0

    def ping(self) -> bool:
        """
        Quick check if connection is still alive.
        Returns True if connected, False if not.
        """
        if not self.client:
            return False
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    def is_connected(self) -> bool:
        """Check if we have an active connection."""
        return self.client is not None and self.ping()

    def reconnect(self) -> bool:
        """
        Try to reconnect if connection was lost.
        Useful for long-running bots.
        """
        logger.info("Attempting to reconnect...")
        self.client = None
        return self.connect()

    @staticmethod
    def test_binance_reachable() -> bool:
        """
        Test if Binance is reachable from this machine.
        Does NOT need API keys.
        Tests multiple endpoints.
        """
        try:
            import requests

            endpoints = [
                "https://api.binance.com/api/v3/ping",
                "https://api.binance.us/api/v3/ping",
                "https://api1.binance.com/api/v3/ping",
                "https://api2.binance.com/api/v3/ping",
            ]

            for url in endpoints:
                try:
                    response = requests.get(
                        url, timeout=10
                    )
                    if response.status_code == 200:
                        logger.info(
                            f"Binance reachable: {url}"
                        )
                        return True
                    else:
                        logger.warning(
                            f"{url} returned: "
                            f"{response.status_code}"
                        )
                except Exception as e:
                    logger.warning(
                        f"{url} failed: {e}"
                    )
                    continue

            logger.error(
                "All Binance endpoints are blocked!"
            )
            return False

        except Exception as e:
            logger.error(
                f"Connectivity test error: {e}"
            )
            return False