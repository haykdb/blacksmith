# price_cache.py

import asyncio
import json
import websockets
from typing import Optional

class PriceCache:
    def __init__(self, symbol):
        self.symbol = symbol.lower()
        self.spot = {"bid": Optional[float], "ask": Optional[float]}
        self.futures = {"bid": Optional[float], "ask": Optional[float]}

    async def start(self):
        await asyncio.gather(
            self._listen_spot(),
            self._listen_futures()
        )

    def get_mid(self, market):
        data = self.spot if market == "spot" else self.futures
        if data["bid"] and data["ask"]:
            return (float(data["bid"]) + float(data["ask"])) / 2
        return None

    async def _listen_spot(self):
        url = f"wss://stream.binance.com:9443/ws/{self.symbol}@bookTicker"
        while True:
            try:
                async with websockets.connect(url) as ws:
                    async for msg in ws:
                        data = json.loads(msg)
                        self.spot["bid"] = data["b"]
                        self.spot["ask"] = data["a"]
            except Exception as e:
                print(f"[{self.symbol}] Spot WS error: {e}")
                await asyncio.sleep(5)

    async def _listen_futures(self):
        url = f"wss://fstream.binance.com/ws/{self.symbol}@bookTicker"
        while True:
            try:
                async with websockets.connect(url) as ws:
                    async for msg in ws:
                        data = json.loads(msg)
                        self.futures["bid"] = data["b"]
                        self.futures["ask"] = data["a"]
            except Exception as e:
                print(f"[{self.symbol}] Futures WS error: {e}")
                await asyncio.sleep(5)
