# ============================================================
# config/settings.py
# Complete configuration for Bybit Futures Trading Bot
# ============================================================

# ── EXCHANGE SETTINGS ─────────────────────────────────────
EXCHANGE  = "bybit"
DEMO_MODE = True    # True = Demo account, False = Live

# ── TRADING MODE ──────────────────────────────────────────
MODE = "demo"       # "demo" or "live"

# ── TIMEFRAME ─────────────────────────────────────────────
TIMEFRAME = "15m"   # 15 minute candles

# ── CANDLE HISTORY ────────────────────────────────────────
WARMUP_CANDLES = 300  # Candles to load at startup

# ── DEFAULT PAIRS ─────────────────────────────────────────
# These are used as fallback if auto-scanner fails
# Bot automatically replaces with top 10 scanned pairs
TRADING_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
]

# Backward compatibility
TRADING_PAIR = "BTCUSDT"

# ── AUTO PAIR SCANNER SETTINGS ────────────────────────────
AUTO_SCAN_PAIRS  = True      # Auto-select top pairs
SCAN_TOP_N       = 10        # How many pairs to trade
SCAN_MIN_VOLUME  = 100_000   # Min $100K daily volume
SCAN_MIN_PRICE   = 0.01      # Min price filter
SCAN_INTERVAL    = 3600      # Rescan every 1 hour (seconds)

# ── RISK SETTINGS ─────────────────────────────────────────
RISK_PER_TRADE        = 0.01   # 1% risk = approx $5 max loss
MAX_DAILY_LOSS        = 0.05   # 5% daily stop
MAX_CONCURRENT_TRADES = 3
MAX_DRAWDOWN          = 0.15
MIN_CONFIDENCE        = 0.55
MAX_POSITION_PCT      = 0.10   # Use only 10% of balance
MIN_NOTIONAL          = 5.0

BOT_RESET_DATE = "2026-05-07" #bot_Reset_Day

# ── LEVERAGE SETTINGS ─────────────────────────────────────
BASE_LEVERAGE = 3    # Starting leverage
MAX_LEVERAGE  = 10   # Maximum allowed leverage
MIN_LEVERAGE  = 1    # Minimum leverage

# ── INDICATOR SETTINGS ────────────────────────────────────
EMA_FAST   = 21     # Fast EMA period
EMA_MEDIUM = 50     # Medium EMA period
EMA_SLOW   = 200    # Slow EMA period
ATR_PERIOD = 14     # ATR period

# ── EXECUTION SETTINGS ────────────────────────────────────
COMMISSION_RATE = 0.001    # 0.1% per trade (Bybit taker)
SLIPPAGE_RATE   = 0.0005   # 0.05% estimated slippage