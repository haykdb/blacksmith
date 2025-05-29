import asyncio, html, logging, time, requests

log = logging.getLogger("Notifier")


def _escape_markdown(msg: str) -> str:
    """
    Escape characters per Telegram MarkdownV2 rules.
    """
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in msg)


def send_telegram_message(message: str, cfg, max_retries: int = 3) -> None:
    if not getattr(cfg, "TELEGRAM_ENABLED", False):
        return

    token, chat = cfg.TELEGRAM_TOKEN, cfg.TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": _escape_markdown(message),
        "parse_mode": "MarkdownV2",
    }

    backoff = 1
    for attempt in range(max_retries):
        try:
            r = requests.post(url, data=payload, timeout=5)
            if r.ok:
                return
            log.error(f"[Telegram] HTTP {r.status_code}: {r.text}")
        except Exception as e:
            log.error(f"[Telegram] Err: {e}")
        time.sleep(backoff)
        backoff = min(backoff * 2, 10)  # 1s → 2s → 4s


async def async_send_telegram_message(message: str, cfg) -> None:
    await asyncio.get_event_loop().run_in_executor(
        None, lambda: send_telegram_message(message, cfg)
    )


### USAGE
# sync context
# send_telegram_message("✅ Trade closed: +12.4 USDT", config)

# async context
# await async_send_telegram_message("🔔 New position opened", config)
