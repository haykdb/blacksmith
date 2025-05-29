# price_cache.py
import asyncio, json, random, websockets
from typing import Optional, Tuple

### USAGE
# /
# cache = PriceCache("btcusdt")
# asyncio.create_task(cache.start())
#
# await cache.updated_event.wait()
# cache.updated_event.clear()
# spot_mid, fut_mid = cache.get_mid_prices()
#


class PriceCache:
    """
    Keeps latest bid/ask for spot & futures via Binance bookTicker websockets.
    One instance per symbol. Provides an asyncio.Event to notify updates.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self.spot_bid: Optional[float] = None
        self.spot_ask: Optional[float] = None
        self.fut_bid: Optional[float] = None
        self.fut_ask: Optional[float] = None
        self.updated_event = asyncio.Event()

    # ---------------------------------------------------------------- public
    def get_mid_prices(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Returns (spot_mid, futures_mid) or (None, None) if not ready.
        """
        if all(
            v is not None
            for v in (self.spot_bid, self.spot_ask, self.fut_bid, self.fut_ask)
        ):
            spot_mid = (self.spot_bid + self.spot_ask) / 2
            fut_mid = (self.fut_bid + self.fut_ask) / 2
            return spot_mid, fut_mid
        return None, None

    async def start(self):
        # stagger connections to avoid handshake storms
        await asyncio.sleep(random.uniform(0.2, 4.0))
        await asyncio.gather(self._listen("spot"), self._listen("futures"))

    # ---------------------------------------------------------------- intern
    async def _listen(self, market: str):
        base = (
            "wss://stream.binance.com:9443/ws"
            if market == "spot"
            else "wss://fstream.binance.com/ws"
        )
        url = f"{base}/{self.symbol}@bookTicker"
        backoff = 1

        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    async for msg in ws:
                        data = json.loads(msg)
                        if market == "spot":
                            nb, na = float(data["b"]), float(data["a"])
                            changed = (nb != self.spot_bid) or (na != self.spot_ask)
                            self.spot_bid, self.spot_ask = nb, na
                        else:
                            nb, na = float(data["b"]), float(data["a"])
                            changed = (nb != self.fut_bid) or (na != self.fut_ask)
                            self.fut_bid, self.fut_ask = nb, na

                        if changed:
                            self.updated_event.set()
                    # normal close → reset backoff
                    backoff = 1
            except asyncio.CancelledError:
                return  # task cancelled -> exit
            except Exception as e:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 32)  # exponential back-off
