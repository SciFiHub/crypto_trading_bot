# ============================================================
# main_cloud.py
# Cloud entry point - works on ALL platforms:
# - Hugging Face Spaces
# - Render.com
# - Railway.app
# - Any cloud with Docker support
# ============================================================

import os
import sys
import time
import threading

# Force UTF-8 encoding
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"]       = "1"

# Add project root to path
sys.path.insert(
    0,
    os.path.dirname(os.path.abspath(__file__))
)

# Load .env file if exists (local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ── FAKE WEB SERVER ───────────────────────────────────────
# Keeps cloud platforms happy that expect a web service
# Runs silently in background on port 7860 (HuggingFace)
# or whatever PORT is set

def start_web_server():
    """
    Starts a tiny web server in background.
    Required by some cloud platforms (HuggingFace, Koyeb).
    Shows bot status at the root URL.
    Does NOT affect trading functionality.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class StatusHandler(BaseHTTPRequestHandler):

        def do_GET(self):
            """Return simple status page."""
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            html = """
            <html>
            <head>
                <title>Bybit Trading Bot</title>
                <meta http-equiv="refresh" content="30">
                <style>
                    body {
                        font-family: monospace;
                        background: #0a0a0a;
                        color: #00ff00;
                        padding: 20px;
                    }
                    h1 { color: #00ff00; }
                    .status { color: #ffff00; }
                    .info { color: #00ffff; }
                </style>
            </head>
            <body>
                <h1>🤖 Bybit Futures Trading Bot</h1>
                <p class="status">
                    Status: <b>RUNNING</b>
                </p>
                <p class="info">
                    Mode: Bybit Demo Trading
                </p>
                <p class="info">
                    Strategy: Trend Pullback Futures
                </p>
                <p class="info">
                    Leverage: Dynamic 1x-10x
                </p>
                <p>
                    Bot is running 24/7.
                    Control via Telegram.
                </p>
                <p style="color:#666">
                    Page auto-refreshes every 30s
                </p>
            </body>
            </html>
            """
            self.wfile.write(html.encode())

        def log_message(self, format, *args):
            # Suppress web server logs (too noisy)
            pass

    def run_server():
        port = int(os.getenv("PORT", 7860))
        try:
            server = HTTPServer(
                ("0.0.0.0", port),
                StatusHandler
            )
            print(
                f"Web server started on port {port}"
            )
            server.serve_forever()
        except Exception as e:
            print(f"Web server error: {e}")

    # Run in background daemon thread
    t = threading.Thread(
        target=run_server,
        daemon=True
    )
    t.start()


# ── ENVIRONMENT CHECK ─────────────────────────────────────

def check_environment() -> bool:
    """Verify all required environment variables."""

    required = {
        "BYBIT_API_KEY"     : os.getenv(
            "BYBIT_API_KEY", ""
        ),
        "BYBIT_API_SECRET"  : os.getenv(
            "BYBIT_API_SECRET", ""
        ),
        "TELEGRAM_BOT_TOKEN": os.getenv(
            "TELEGRAM_BOT_TOKEN", ""
        ),
        "TELEGRAM_CHAT_ID"  : os.getenv(
            "TELEGRAM_CHAT_ID", ""
        ),
    }

    print("=" * 50)
    print("ENVIRONMENT VARIABLES CHECK")
    print("=" * 50)

    all_ok = True
    for name, value in required.items():
        if value and len(value) > 5:
            print(
                f"OK  : {name} = "
                f"{value[:6]}..."
            )
        else:
            print(
                f"MISS: {name} = NOT FOUND"
            )
            all_ok = False

    print("=" * 50)

    if all_ok:
        print("All environment variables OK!")
    else:
        print(
            "MISSING variables!\n"
            "Add them to your cloud platform secrets."
        )

    return all_ok


# ── CONNECTIVITY TEST ─────────────────────────────────────

def test_bybit_connectivity() -> bool:
    """Test if Bybit is reachable from this server."""
    import requests

    print("=" * 50)
    print("BYBIT CONNECTIVITY TEST")
    print("=" * 50)

    endpoints = [
        (
            "Bybit Demo",
            "https://api-demo.bybit.com/v5/market/time"
        ),
        (
            "Bybit Live",
            "https://api.bybit.com/v5/market/time"
        ),
    ]

    reachable = False

    for name, url in endpoints:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                print(f"REACH: {name}")
                reachable = True
            else:
                print(
                    f"FAIL : {name} "
                    f"HTTP {resp.status_code}"
                )
        except requests.exceptions.ConnectionError:
            print(
                f"BLOCK: {name} "
                f"Connection refused"
            )
        except requests.exceptions.Timeout:
            print(f"TIME : {name} Timeout")
        except Exception as e:
            print(f"ERR  : {name} {e}")

    print("=" * 50)

    if not reachable:
        print(
            "WARNING: Bybit may be blocked here!\n"
            "Bot will attempt connection anyway..."
        )

    return reachable


# ── MAIN ENTRY POINT ──────────────────────────────────────

def main():
    """
    Main entry point for cloud deployment.

    Flow:
    1. Start fake web server (keeps platform happy)
    2. Check environment variables
    3. Test Bybit connectivity
    4. Start trading bot with auto-restart
    """

    print("=" * 50)
    print("BYBIT FUTURES TRADING BOT")
    print("Cloud Mode: Starting...")
    print("=" * 50)

    # Step 1: Start web server in background
    # This keeps cloud platforms happy
    start_web_server()

    # Step 2: Check environment
    if not check_environment():
        print(
            "\nCannot start: missing variables.\n"
            "Add them to your cloud secrets."
        )
        # Keep web server alive so platform doesn't crash
        while True:
            time.sleep(60)

    # Step 3: Test connectivity
    test_bybit_connectivity()

    # Step 4: Run bot with auto-restart
    print("\nStarting trading bot...")
    restart_count = 0

    while True:
        try:
            restart_count += 1
            print(
                f"\n{'='*50}\n"
                f"Bot attempt #{restart_count}\n"
                f"{'='*50}"
            )

            # Import here to avoid circular imports
            from bot_runner import TradingBot

            bot = TradingBot()
            bot.run()

            # Bot exited cleanly
            print(
                "Bot stopped cleanly. "
                "Restarting in 15 seconds..."
            )
            time.sleep(15)

        except KeyboardInterrupt:
            print("\nBot stopped by user.")
            break

        except ImportError as e:
            print(f"Import error: {e}")
            print("Check your requirements.txt")
            time.sleep(60)

        except Exception as e:
            print(
                f"Bot error (#{restart_count}): {e}"
            )
            import traceback
            traceback.print_exc()
            print("Restarting in 30 seconds...")
            time.sleep(30)


if __name__ == "__main__":
    main()