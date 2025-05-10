# === Live API Settings ===
API_KEY = "V0R9ksbzKn29PwwgvZf6e11kcxCnkdB4fXsBTLyzsdEaUrkRc2cPbpYgEK2MPI5j"
API_SECRET = "KuTI2KncBqcj4azaS76oQyQxKZwsh1TVG6DLHGn7JH2muNuQ1Ojts2wn0yTfl04S"

# === Spot Testnet API Settings ===
SPOT_API_KEY = "iVbyH2SVnWUAd1wyYPzW6CuX6OcYtZKH0m2u4yac8G9FA45OtdmJqohrtz9ZgT8x"
SPOT_API_SECRET = "1t9kHnXsj3fS8VadntJIdu8JqGqg5CFvfE6Q5x5pOac46rzk8XnBaDwKGoNaYTaI"

# === Futures Testnet API Settings ===
FUTURES_API_KEY = "76b91893df17578be29428909d8907eeabae12b26966c508844e5a2b29b69a5e"
FUTURES_API_SECRET = "755d61406a815b5ef7030b1bdbdf14c2f676e8ae28dfbe487fb73991bbb39fd3"

# Symbol and Trading
SYMBOLS = [
    "FLMUSDT",
    "BIOUSDT",
    "ATAUSDT",
    "ALPACAUSDT",
    "DOGEUSDT",
    "WIFUSDT",
    "TRUMPUSDT",
    "ARBUSDT",
    "BNBUSDT",
    "ACTUSDT"
]
CAPITAL_PER_TRADE = 15  # USD
USE_TESTNET = False
ALLOW_SHORT_SPREAD = False
LEVERAGE = 1

# Strategy parameters
STRATEGY_LOOKBACK = 120  # in minutes
STRATEGY_Z_ENTRY = 1.5
STRATEGY_Z_EXIT = 0.5
TRADE_SLEEP = 0.2
SPREAD_MODEL_SLEEP = 30
TC = 0.0008
USE_WEBSOCKET = True
USE_MID_PRICE = False

# Logging
TRADE_LOG_PATH = (
    "/Users/admin/Documents/BinanceBots/trades_history/{symbol}_{t:%Y-%m-%d}_trades.csv"
)

# Telegram Notifications
TELEGRAM_ENABLED = True
TELEGRAM_TOKEN = "8164459721:AAF_VmLBCalUOHhWQ5F-tsHeHWIJZjll96U"
TELEGRAM_CHAT_ID = 1721711870

# Exit Timeout
USE_BOOK_BASED_EXIT = True
EXIT_TIMEOUT_SECONDS = 900  # 10 minutes fallback
