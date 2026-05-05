# ============================================================
# scan_pairs.py
# Scans Binance.US for highest liquidity trading pairs
# Adjusted filters for lower Binance.US liquidity
# ============================================================

import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    from binance.client import Client
except ImportError:
    print("Installing python-binance...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip",
                   "install", "python-binance"], check=True)
    from binance.client import Client


def connect_binance():
    """Connect to Binance.US or Global."""
    api_key    = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")

    endpoints = [
        {"tld": "us",  "name": "Binance.US"},
        {"tld": "com", "name": "Binance Global"},
    ]

    for ep in endpoints:
        try:
            print(f"Trying to connect to {ep['name']}...")
            client = Client(
                api_key    = api_key,
                api_secret = api_secret,
                tld        = ep["tld"],
                requests_params={"timeout": 30}
            )
            client.ping()
            print(f"Connected to {ep['name']}!")
            return client, ep["name"]
        except Exception as e:
            print(f"  Failed to connect to {ep['name']}: {e}")
            continue

    print("Cannot connect to any Binance endpoint!")
    return None, None


def get_recommended_pairs(
    min_volume: float = 1_000_000, # Lowered from 5M to 1M
    min_price: float = 0.05,     # Increased from 0.01
    min_daily_range: float = 0.5, # Lowered from 1%
    top_n: int = 10              # Get top 10 recommended
):
    """
    Fetch and filter trading pairs recommended for our strategy.
    Adjusted for Binance.US lower liquidity.
    """

    client, endpoint_name = connect_binance()

    if not client:
        return []

    print(f"\nFetching 24h ticker data from {endpoint_name}...")

    try:
        tickers = client.get_ticker()
    except Exception as e:
        print(f"Error fetching tickers: {e}")
        return []

    recommended = []

    skip_bases = [
        "USDC", "BUSD", "TUSD", "USDP", "USDD", "FDUSD",
        "PYUSD", "DAI", "PAXG", "GUSD"
    ]
    skip_keywords = [
        "UP", "DOWN", "BULL", "BEAR", "3L", "3S", "2L", "2S"
    ]

    for ticker in tickers:
        symbol = ticker["symbol"]

        if not symbol.endswith("USDT"):
            continue

        base = symbol.replace("USDT", "")

        # --- FILTERS ---
        if base in skip_bases:
            continue
        if any(kw in base for kw in skip_keywords):
            continue

        # Convert to float (handle missing keys gracefully)
        try:
            volume = float(ticker.get("quoteVolume", 0))
            price  = float(ticker.get("lastPrice", 0))
            change = float(ticker.get("priceChangePercent", 0))
            high   = float(ticker.get("highPrice", 0))
            low    = float(ticker.get("lowPrice", 0))
        except (ValueError, TypeError):
            continue # Skip if data is bad

        if volume < min_volume:
            continue
        if price < min_price:
            continue
        if abs(change) < 0.2: # Minimum 0.2% change to indicate activity
            continue

        daily_range = 0
        if low > 0 and high > low:
            daily_range = (high - low) / low * 100

        if daily_range < min_daily_range:
            continue

        recommended.append({
            "symbol"      : symbol,
            "base"        : base,
            "volume"      : volume,
            "price"       : price,
            "change"      : change,
            "daily_range" : daily_range,
        })

    # Sort by volume (highest first)
    recommended.sort(
        key=lambda x: x["volume"],
        reverse=True
    )

    # Take top N
    final_recommended = recommended[:top_n]

    print(f"\n{'='*70}")
    print(f"RECOMMENDED PAIRS FOR TRADING ({len(final_recommended)} pairs)")
    print(f"({endpoint_name} - Min Volume: ${min_volume:,.0f}, Min Range: {min_daily_range:.1f}%)")
    print(f"{'='*70}")
    print(
        f"{'#':<4} "
        f"{'Symbol':<12} "
        f"{'Price':<12} "
        f"{'Volume':>14} "
        f"{'Range%':>8}"
    )
    print(f"{'─'*70}")

    for i, pair in enumerate(final_recommended, 1):
        print(
            f"{i:<4} "
            f"{pair['symbol']:<12} "
            f"${pair['price']:<11,.4f} "
            f"${pair['volume']:>13,.0f} "
            f"{pair['daily_range']:>7.2f}%"
        )

    print(f"{'='*70}")

    symbols = [p["symbol"] for p in final_recommended]

    print(f"\n{'='*70}")
    print("COPY THIS INTO config/settings.py:")
    print(f"{'='*70}")
    print("TRADING_PAIRS = [")
    for sym in symbols:
        print(f'    "{sym}",')
    print("]")
    print(f"{'='*70}")

    return symbols


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("BINANCE PAIR SCANNER")
    print("=" * 60)
    print("Scanning for best liquid pairs...")
    print("=" * 60)
    get_recommended_pairs()