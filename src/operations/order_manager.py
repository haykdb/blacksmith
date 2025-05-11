import asyncio
from loguru import logger
import time
import math
from binance.exceptions import BinanceAPIException  # type: ignore[import-untyped]
from binance.client import Client  # type: ignore[import-untyped]


class OrderManager:
    def __init__(self, spot_client: Client, futures_client: Client):
        self.spot = spot_client
        self.futures = futures_client

    # === Public Spot Methods ===
    def spot_buy(self, symbol: str, quantity: float) -> bool:
        return self._safe_order(symbol, "BUY", quantity, is_futures=False)

    def spot_sell(self, symbol: str, quantity: float) -> bool:
        return self._safe_order(symbol, "SELL", quantity, is_futures=False)

    def spot_order(self, symbol: str, side: str, quantity: float) -> bool:
        assert side in ["BUY", "SELL"]
        return self._safe_order(symbol, side, quantity, is_futures=False)

    # === Public Futures Methods ===
    def futures_buy(
        self, symbol: str, quantity: float, reduce_only: bool = False
    ) -> bool:
        return self._safe_order(
            symbol, "BUY", quantity, is_futures=True, reduce_only=reduce_only
        )

    def futures_sell(
        self, symbol: str, quantity: float, reduce_only: bool = False
    ) -> bool:
        return self._safe_order(
            symbol, "SELL", quantity, is_futures=True, reduce_only=reduce_only
        )

    def futures_order(
        self, symbol: str, side: str, quantity: float, reduce_only: bool = False
    ) -> bool:
        assert side in ["BUY", "SELL"]
        return self._safe_order(
            symbol, side, quantity, is_futures=True, reduce_only=reduce_only
        )

    # === Public Position Closer ===
    def close_position(self, symbol: str, is_futures: bool) -> bool:
        return (
            self.close_futures_position(symbol)
            if is_futures
            else self.close_spot_position(symbol)
        )

    def close_futures_position(self, symbol: str) -> bool:
        try:
            info = self.futures.futures_position_information(symbol=symbol)
            if not info:
                logger.debug(f"[FUTURES] No open futures position for {symbol}.")
                return True
            pos_amt = float(info[0]["positionAmt"])
            if abs(pos_amt) < 1e-6:
                logger.info(f"[FUTURES] No open futures position for {symbol}.")
                return True
            side = "SELL" if pos_amt > 0 else "BUY"
            quantity = abs(pos_amt)
            # logger.info(f"[FUTURES] Closing {side} {quantity} {symbol}")
            return self._safe_order(
                symbol, side, quantity, is_futures=True, reduce_only=True
            )
        except Exception as e:
            logger.error(f"[FUTURES ERROR] Failed to close position: {e}")
            return False

    def close_spot_position(self, symbol: str) -> bool:
        try:
            asset = symbol.replace("USDT", "")
            account = self.spot.get_account()
            minQty = self.get_min_qty(symbol, False)
            minNotional = self.get_min_notional(symbol, False)
            spot_price = round(
                float(self.spot.get_symbol_ticker(symbol=symbol)["price"]), 4
            )
            quantity = 0.0
            for balance in account["balances"]:
                if balance["asset"] == asset:
                    quantity = float(balance["free"]) + float(balance["locked"])
                    break
            if quantity <= minQty or spot_price * quantity <= minNotional:
                logger.debug(f"[SPOT] No spot balance for {asset} to close.")
                return True
            # logger.info(f"[SPOT] Closing spot position: SELL {quantity} {symbol}")
            return self._safe_order(symbol, "SELL", quantity, is_futures=False)

        except Exception as e:
            logger.error(f"[SPOT ERROR] Failed to close spot position: {e}")
            return False

    # === Core Safe Order Method ===
    def _safe_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        is_futures: bool,
        reduce_only=False,
        max_retries=3,
    ) -> bool:
        attempt = 0
        min_qty = self.get_min_qty(symbol, is_futures)
        step_size = self.get_step_size(symbol, is_futures)

        while attempt < max_retries:
            quantity = self.adjust_to_step_size(quantity, step_size)

            try:
                if is_futures:
                    params = {
                        "symbol": symbol,
                        "side": side,
                        "type": "MARKET",
                        "quantity": quantity,
                        "reduceOnly": reduce_only,
                    }
                    self.futures.futures_create_order(**params)
                else:
                    params = {
                        "symbol": symbol,
                        "side": side,
                        "type": "MARKET",
                        "quantity": quantity,
                    }
                    self.spot.create_order(**params)

                logger.success(
                    f"[ORDER SUCCESS] {side} {quantity} {symbol} (futures={is_futures}, reduceOnly={reduce_only})"
                )
                return True

            except BinanceAPIException as e:
                if e.code in (-1013, -4131):
                    logger.warning(
                        f"[ORDER WARNING] {e.message} (code {e.code}). Retrying smaller size..."
                    )
                    quantity /= 2
                    if quantity < min_qty:
                        print(
                            f"[ORDER FAIL] Quantity {quantity} below minQty {min_qty}. Aborting."
                        )
                        return False
                    attempt += 1
                    time.sleep(1)

                elif e.code == -2022:
                    logger.warning(
                        f"[ORDER NOTICE] ReduceOnly rejected. Treating as success."
                    )
                    return True

                else:
                    logger.error(
                        f"[ORDER ERROR] Binance API error {e.code}: {e.message}"
                    )
                    return False

        logger.error(f"[ORDER FAIL] Max retries exceeded for {side} {symbol}")
        return False

    # === Symbol Filter Utilities ===
    def get_symbol_info(self, symbol: str, is_futures: bool) -> dict:
        try:
            info = (
                self.futures.futures_exchange_info()
                if is_futures
                else self.spot.get_exchange_info()
            )
            for s in info["symbols"]:
                if s["symbol"] == symbol:
                    return s
        except Exception as e:
            logger.error(f"[ERROR] Failed to fetch symbol info for {symbol}: {e}")
        return {}

    def get_min_qty(self, symbol: str, is_futures: bool) -> float:
        info = self.get_symbol_info(symbol, is_futures)
        for f in info.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                return float(f.get("minQty", 0.00001))
        return 0.00001

    def get_min_notional(self, symbol: str, is_futures: bool) -> float:
        info = self.get_symbol_info(symbol, is_futures)
        for f in info.get("filters", []):
            if f.get("filterType") == "NOTIONAL":
                return float(f.get("minNotional", 5))
        return 5

    def get_step_size(self, symbol: str, is_futures: bool) -> float:
        info = self.get_symbol_info(symbol, is_futures)
        for f in info.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                return float(f.get("stepSize", 0.00001))
        return 0.00001

    @staticmethod
    def adjust_to_step_size(quantity: float, step_size: float) -> float:
        precision = abs(int(f"{step_size:e}".split("e")[-1]))
        return round(math.floor(quantity / step_size) * step_size, precision)

    async def async_spot_buy(self, symbol, qty):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.spot_buy(symbol, qty))

    async def async_spot_sell(self, symbol, qty):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.spot_sell(symbol, qty))

    async def async_margin_sell(self, symbol, qty):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.margin_sell(symbol, qty))

    async def async_futures_buy(self, symbol, qty):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.futures_buy(symbol, qty))

    async def async_futures_sell(self, symbol, qty):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.futures_sell(symbol, qty))

    async def async_close_spot_position(self, symbol):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.close_spot_position(symbol)
        )

    async def async_close_futures_position(self, symbol):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.close_futures_position(symbol)
        )
