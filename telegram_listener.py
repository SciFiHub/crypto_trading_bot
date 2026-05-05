# ============================================================
# telegram_listener.py
# Always-on Telegram listener
# Controls the trading bot from your phone
# Run once: python telegram_listener.py
# Then use /start /stop /help from Telegram
# ============================================================

import os
import sys
import time
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── INSTALL CHECK ─────────────────────────────────────────────
try:
    import requests
except ImportError:
    print("Installing requests...")
    import subprocess
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "requests"],
        check=True
    )
    import requests

# ── CONFIG ────────────────────────────────────────────────────
TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

# ── PATHS ─────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# On Railway: no venv, use system python
# On local Windows: use venv python
if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"):
    # Running on Railway cloud
    VENV_PYTHON = sys.executable
    MAIN_SCRIPT = os.path.join(ROOT_DIR, "main_cloud.py")
    IS_RAILWAY  = True
elif sys.platform == "win32":
    # Local Windows
    VENV_PYTHON = os.path.join(
        ROOT_DIR, "venv", "Scripts", "python.exe"
    )
    MAIN_SCRIPT = os.path.join(ROOT_DIR, "main.py")
    IS_RAILWAY  = False
else:
    # Local Linux/Mac
    VENV_PYTHON = os.path.join(
        ROOT_DIR, "venv", "bin", "python"
    )
    MAIN_SCRIPT = os.path.join(ROOT_DIR, "main.py")
    IS_RAILWAY  = False

# ── GLOBAL STATE ──────────────────────────────────────────────
bot_process  = None
bot_lock     = threading.Lock()


# ── HELPERS ───────────────────────────────────────────────────

def log(msg: str):
    """Timestamped console print."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def send(message: str) -> bool:
    """
    Send a message to your Telegram chat.
    Returns True if successful.
    """
    if not TOKEN or not CHAT_ID:
        log(f"[NO TELEGRAM] {message[:50]}")
        return False

    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            data={
                "chat_id"   : CHAT_ID,
                "text"      : message,
                "parse_mode": "HTML",
            },
            timeout=10
        )
        return response.status_code == 200

    except KeyboardInterrupt:
        return False
    except requests.exceptions.ConnectionError:
        log("Telegram: No internet connection")
        return False
    except requests.exceptions.Timeout:
        log("Telegram: Request timed out")
        return False
    except Exception as e:
        log(f"Telegram send error: {e}")
        return False


def get_updates(offset: int) -> list:
    """Fetch new messages from Telegram."""
    try:
        response = requests.get(
            f"{BASE_URL}/getUpdates",
            params={
                "offset" : offset,
                "timeout": 4,
                "limit"  : 10
            },
            timeout=8
        )
        data = response.json()
        return (
            data.get("result", [])
            if data.get("ok") else []
        )
    except KeyboardInterrupt:
        return []
    except Exception:
        return []


def is_bot_running() -> bool:
    """Check if trading bot process is alive."""
    global bot_process
    if bot_process is None:
        return False
    return bot_process.poll() is None


def read_bot_output():
    """
    Read bot output in background thread.
    Prints to console so you can monitor.
    """
    global bot_process
    try:
        for line in bot_process.stdout:
            line = line.rstrip()
            if line:
                print(f"  [BOT] {line}", flush=True)
    except Exception:
        pass
    log("Bot process ended.")


# ── BOT CONTROL ───────────────────────────────────────────────

def start_bot():
    """Launch the trading bot as subprocess."""
    global bot_process

    with bot_lock:
        if is_bot_running():
            send(
                "Bot is already running!\n"
                "Send /status to check it."
            )
            return

        log("Starting trading bot...")

        if not os.path.exists(VENV_PYTHON):
            # On Railway, use system python
            python_cmd = sys.executable
        else:
            python_cmd = VENV_PYTHON

        if not os.path.exists(MAIN_SCRIPT):
            log(f"ERROR: main.py not found")
            send("ERROR: main.py not found!")
            return

        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"]       = "1"

            bot_process = subprocess.Popen(
                [python_cmd, MAIN_SCRIPT],
                cwd      = ROOT_DIR,
                stdout   = subprocess.PIPE,
                stderr   = subprocess.STDOUT,
                encoding = "utf-8",
                errors   = "replace",
                bufsize  = 1,
                env      = env
            )

            t = threading.Thread(
                target=read_bot_output,
                daemon=True
            )
            t.start()

            time.sleep(3)

            if is_bot_running():
                log(
                    f"Bot started! PID: {bot_process.pid}"
                )
                send(
                    "<b>BOT STARTED!</b>\n"
                    "========================\n"
                    "Trading bot is running.\n"
                    "Scanning all pairs...\n"
                    "========================\n"
                    "/positions - Open trades\n"
                    "/balance   - Account info\n"
                    "/pause     - Pause trading\n"
                    "/stop      - Stop bot\n"
                    f"Time: "
                    f"{datetime.now().strftime('%H:%M')}"
                )
            else:
                send("Bot failed to start!")

        except Exception as e:
            log(f"Start error: {e}")
            send(f"Failed to start: {e}")


def stop_bot():
    """Stop the trading bot process."""
    global bot_process

    with bot_lock:
        if not is_bot_running():
            send(
                "Bot is not running.\n"
                "Send /start to start it."
            )
            return

        log("Stopping trading bot...")

        try:
            import subprocess

            bot_process.terminate()

            try:
                bot_process.wait(timeout=10)
                log("Bot stopped cleanly.")
            except subprocess.TimeoutExpired:
                bot_process.kill()
                log("Bot force-killed.")

            send(
                "<b>BOT STOPPED</b>\n"
                "------------------------\n"
                "Trading bot has stopped.\n"
                "Note: Open trades on exchange\n"
                "may still be active.\n"
                "------------------------\n"
                "Send /start to restart.\n"
                f"Time: "
                f"{datetime.now().strftime('%H:%M')}"
            )

        except Exception as e:
            log(f"Stop error: {e}")
            send(f"Error stopping bot: {e}")


def restart_bot():
    """Restart the trading bot."""
    log("Restarting bot...")
    send("Restarting bot...")

    if is_bot_running():
        stop_bot()
        time.sleep(3)

    start_bot()


# ── COMMAND HANDLER ───────────────────────────────────────────

def handle_command(text: str):
    """Route Telegram command to correct function."""
    text = text.strip().lower()
    log(f"Command: {text}")

    if text == "/start":
        if is_bot_running():
            send(
                "Bot is already running!\n"
                "Send /status to check.\n"
                "Send /stop to stop first."
            )
        else:
            send("Starting bot, please wait...")
            t = threading.Thread(
                target=start_bot,
                daemon=True
            )
            t.start()

    elif text == "/stop":
        if is_bot_running():
            send("Stopping bot...")
            t = threading.Thread(
                target=stop_bot,
                daemon=True
            )
            t.start()
        else:
            send(
                "Bot is not running.\n"
                "Send /start to start it."
            )

    elif text == "/restart":
        t = threading.Thread(
            target=restart_bot,
            daemon=True
        )
        t.start()

    elif text == "/status":
        if is_bot_running():
            pid = bot_process.pid
            send(
                "<b>BOT IS RUNNING</b>\n"
                "------------------------\n"
                f"Process ID: {pid}\n"
                "Bot is actively trading.\n"
                "------------------------\n"
                "The bot also responds to:\n"
                "/positions /balance /trades\n"
                "/health /pause /resume\n"
                "------------------------\n"
                "Send /stop to stop it.\n"
                f"Time: "
                f"{datetime.now().strftime('%H:%M')}"
            )
        else:
            send(
                "<b>BOT IS STOPPED</b>\n"
                "------------------------\n"
                "No trading happening.\n"
                "Send /start to start.\n"
                f"Time: "
                f"{datetime.now().strftime('%H:%M')}"
            )

    elif text == "/help":
        running = (
            "Running" if is_bot_running()
            else "Stopped"
        )
        send(
            "<b>BOT COMMANDS</b>\n"
            "========================\n"
            f"Current: {running}\n"
            "========================\n"
            "<b>LAUNCHER CONTROL:</b>\n"
            "/start    - Start bot\n"
            "/stop     - Stop bot\n"
            "/restart  - Restart bot\n"
            "/status   - Running check\n"
            "/help     - This message\n"
            "========================\n"
            "<b>WHEN BOT IS RUNNING:</b>\n"
            "/positions - Open trades\n"
            "/balance   - Account info\n"
            "/trades    - Trade history\n"
            "/health    - Bot health\n"
            "/pause     - Pause signals\n"
            "/resume    - Resume signals\n"
            "/kill      - Emergency stop"
        )

    else:
        if is_bot_running():
            # Bot is running, maybe it can handle this command
            send(
                f"Launcher got: {text}\n"
                "The trading bot handles:\n"
                "/positions /balance /trades\n"
                "/health /pause /resume /kill\n"
                "Send /help for all commands."
            )
        else:
            send(
                f"Unknown command: {text}\n"
                "Bot is stopped.\n"
                "Send /start to start it.\n"
                "Send /help for commands."
            )


# ── MAIN LOOP ─────────────────────────────────────────────────

def main():
    """Main listener loop."""

    # Validate config
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not found in .env")
        print("Please add it to your .env file")
        return

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID not found in .env")
        print("Please add it to your .env file")
        return

    # Print startup info
    print("=" * 50)
    print("TELEGRAM BOT LAUNCHER")
    print("=" * 50)
    print(f"Chat ID    : {CHAT_ID}")
    print(f"Bot Python : {VENV_PYTHON}")
    print(f"Script     : {MAIN_SCRIPT}")
    print("=" * 50)
    print("COMMANDS:")
    print("  /start   - Start trading bot")
    print("  /stop    - Stop trading bot")
    print("  /restart - Restart bot")
    print("  /status  - Check if running")
    print("  /help    - All commands")
    print("=" * 50)
    print("Listening for Telegram messages...")
    print("Press Ctrl+C to quit launcher")
    print("=" * 50, flush=True)

    # Send startup message (non-blocking)
    log("Sending startup message to Telegram...")
    result = send(
        "<b>LAUNCHER READY</b>\n"
        "------------------------\n"
        "Telegram listener is active.\n"
        "Send /start to start trading.\n"
        "Send /help for all commands.\n"
        f"Time: {datetime.now().strftime('%H:%M')}"
    )

    if result:
        log("Startup message sent successfully!")
    else:
        log("Could not send startup message.")
        log("Check your Telegram token and chat ID.")
        log("Continuing to listen anyway...")

    # Main polling loop
    offset = 0

    while True:
        try:
            # Get new messages
            updates = get_updates(offset)

            for update in updates:
                # Move offset forward
                offset = update["update_id"] + 1

                # Extract message
                message = update.get("message", {})
                text    = message.get("text", "")
                from_id = str(
                    message.get(
                        "chat", {}
                    ).get("id", "")
                )

                # Security: only respond to YOUR chat
                if from_id != CHAT_ID:
                    log(
                        f"Blocked message from "
                        f"unknown chat: {from_id}"
                    )
                    continue

                if text:
                    handle_command(text)

            # Check if bot crashed unexpectedly
            global bot_process
            if bot_process is not None:
                if not is_bot_running():
                    code = bot_process.poll()
                    if code is not None and code != 0:
                        log(
                            f"Bot crashed! "
                            f"Exit code: {code}"
                        )
                        send(
                            "<b>BOT CRASHED!</b>\n"
                            "------------------------\n"
                            f"Exit code: {code}\n"
                            "Bot stopped unexpectedly.\n"
                            "Send /start to restart.\n"
                            f"Time: "
                            f"{datetime.now().strftime('%H:%M')}"
                        )
                        # Reset so we don't spam
                        bot_process = None

            # Poll every 2 seconds
            time.sleep(2)

        except KeyboardInterrupt:
            print("\n", flush=True)
            log("Launcher stopped by user (Ctrl+C)")

            if is_bot_running():
                log("Stopping trading bot...")
                stop_bot()

            send(
                "Launcher stopped manually.\n"
                "Bot has been stopped too.\n"
                "Restart launcher to resume."
            )
            break

        except Exception as e:
            log(f"Listener error: {e}")
            time.sleep(5)  # Wait before retrying


if __name__ == "__main__":
    main()