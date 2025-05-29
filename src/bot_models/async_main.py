# main.py   –  run with:  poetry run python -m main

import asyncio, multiprocessing as mp
from datetime import date
from loguru import logger
from binance.client import Client

import configs.config as config
from bot_models.async_bot import Bot  # <- direct import
from operations.price_cache import PriceCache  # used only if websocket

LOGFILE = f"/Users/admin/Documents/BinanceBots/Logs/{date.today()}.log"
logger.add(LOGFILE, rotation="10 MB")


# ---------------------------------------------------------------- helpers
def build_clients() -> tuple[Client, Client]:
    """
    Returns (spot_client, futures_client) based on LIVE or TEST mode.
    Always create NEW client objects inside each subprocess.
    """
    if config.USE_TESTNET:
        spot = Client(config.SPOT_API_KEY, config.SPOT_API_SECRET, testnet=True)
        fut = Client(config.FUTURES_API_KEY, config.FUTURES_API_SECRET, testnet=True)
        spot.API_URL = "https://testnet.binance.vision"
        fut.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
    else:
        # live keys may be the same or separate – adjust as needed
        spot = Client(config.API_KEY, config.API_SECRET)
        fut = spot
    return spot, fut


# ---------------------------------------------------------------- bot runner
def run_bot(symbol: str):
    import nest_asyncio

    nest_asyncio.apply()  # for macOS spawn quirk
    spot_client, fut_client = build_clients()

    if config.USE_WEBSOCKET:
        price_cache = PriceCache(symbol)
        bot = Bot(spot_client, fut_client, symbol, price_cache=price_cache)

        async def launch():
            await asyncio.gather(price_cache.start(), bot.start())

        asyncio.run(launch())
    else:
        bot = Bot(spot_client, fut_client, symbol)
        asyncio.run(bot.start())


# ---------------------------------------------------------------- system runner
def run_system():
    mp.set_start_method("spawn", force=True)
    # OPTIONAL: limit concurrency e.g. sem = mp.Semaphore(10)
    procs: list[mp.Process] = []

    for sym in config.SYMBOLS:
        p = mp.Process(target=run_bot, args=(sym,), name=f"Bot-{sym}")
        p.start()
        procs.append(p)
        logger.info(f"Started bot for {sym}")

    try:
        for p in procs:
            p.join()
    except KeyboardInterrupt:
        logger.warning("CTRL-C received – terminating all bots.")
        for p in procs:
            p.terminate()


# ---------------------------------------------------------------- entry point
if __name__ == "__main__":
    run_system()
