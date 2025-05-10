import asyncio
import json
import websockets
from typing import Optional, Union
import random
from loguru import logger


class PriceCache:
    def __init__(self, symbol):
        self.symbol = symbol.lower()
        self.spot = {"bid": Optional[float], "ask": Optional[float]}
        self.futures = {"bid": Optional[float], "ask": Optional[float]}
        self.updated_event = asyncio.Event()

    async def start(self):
        await asyncio.sleep(random.uniform(0.2, 4.0))
        await asyncio.gather(self._listen_spot(), self._listen_futures())

    def get_mid(self, market: str) -> Union[float, None]:
        data = self.spot if market == "spot" else self.futures
        if isinstance(data["bid"], str) and isinstance(data["ask"], str):
            return (float(data["bid"]) + float(data["ask"])) / 2
        return None

    def get_spot_ask(self) -> Union[float, None]:
        return float(self.spot["ask"]) if isinstance(self.spot["ask"], str) else None

    def get_futures_bid(self) -> Union[float, None]:
        return float(self.futures["bid"]) if isinstance(self.spot["bid"], str) else None

    async def _listen_spot(self):
        url = f"wss://stream.binance.com:9443/ws/{self.symbol}@bookTicker"
        while True:
            try:
                async with websockets.connect(url) as ws:
                    async for msg in ws:
                        data = json.loads(msg)
                        self.spot["bid"] = data["b"]
                        self.spot["ask"] = data["a"]
                        self.updated_event.set()
            except Exception as e:
                logger.error(f"[{self.symbol}] Spot WS error: {e}")
                await asyncio.sleep(0.1)

    async def _listen_futures(self):
        url = f"wss://fstream.binance.com/ws/{self.symbol}@bookTicker"
        while True:
            try:
                async with websockets.connect(url) as ws:
                    async for msg in ws:
                        data = json.loads(msg)
                        self.futures["bid"] = data["b"]
                        self.futures["ask"] = data["a"]
                        self.updated_event.set()
            except Exception as e:
                logger.error(f"[{self.symbol}] Futures WS error: {e}")
                await asyncio.sleep(0.1)
