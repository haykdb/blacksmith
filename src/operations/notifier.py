import requests
from loguru import logger


def send_telegram_message(message: str, config):
    if not config.TELEGRAM_ENABLED:
        return

    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        logger.error(f"[NOTIFY] Telegram error: {e}")
