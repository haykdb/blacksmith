# operations/order_manager.py
import asyncio, time, math, functools, logging
from binance.exceptions import BinanceAPIException  # type: ignore
from binance.client import Client  # type: ignore
from numba import njit

logger = logging.getLogger("OrderManager")


# -------- small, hot helper -------------------------------------------------
# @njit
def fast_round(qty: float, step: float) -> float:
    """Round DOWN to nearest step size using only native math."""
    precision = abs(int(f"{step:e}".split("e")[-1]))
    return round(math.floor(qty / step) * step, precision)


# ----------------------------------------------------------------------------
class OrderManager:
    def __init__(self, spot_client: Client, futures_client: Client):
        self.spot = spot_client
        self.futures = futures_client

    # ======== public spot wrappers ==========================================
    def spot_buy(self, sym: str, qty: float) -> bool:
        return self._safe_order(sym, "BUY", qty, False)

    def spot_sell(self, sym: str, qty: float) -> bool:
        return self._safe_order(sym, "SELL", qty, False)

    def margin_sell(self, sym: str, qty: float) -> bool:
        # borrowing logic is outside scope; assume isolated margin enabled
        return self._safe_order(sym, "SELL", qty, False)

    # ======== public futures wrappers =======================================
    def futures_buy(self, sym: str, qty: float, reduce=False) -> bool:
        return self._safe_order(sym, "BUY", qty, True, reduce)

    def futures_sell(self, sym: str, qty: float, reduce=False) -> bool:
        return self._safe_order(sym, "SELL", qty, True, reduce)

    # ======== close helpers ==================================================
    def close_futures_position(self, symbol: str) -> bool:
        try:
            info = self.futures.futures_position_information(symbol=symbol)
            if not info:
                return True
            pos_amt = float(info[0]["positionAmt"])
            if abs(pos_amt) < 1e-6:
                return True
            side = "SELL" if pos_amt > 0 else "BUY"
            return self._safe_order(symbol, side, abs(pos_amt), True, True)
        except Exception as e:
            logger.error(f"[{symbol}] Close futures failed: {e}")
            return False

    def close_spot_position(self, symbol: str) -> bool:
        try:
            asset = symbol.replace("USDT", "")
            bal = next(
                b for b in self.spot.get_account()["balances"] if b["asset"] == asset
            )
            qty = float(bal["free"]) + float(bal["locked"])
            if qty < 1e-8:
                return True
            return self.spot_sell(symbol, qty)
        except Exception as e:
            logger.error(f"[{symbol}] Close spot failed: {e}")
            return False

    # -------- core order executor -------------------------------------------
    def _safe_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        is_futures: bool,
        reduce_only: bool = False,
        max_retries: int = 3,
    ) -> bool:
        step = self.get_step_size(symbol, is_futures)
        min_qty = self.get_min_qty(symbol, is_futures)

        for attempt in range(max_retries):
            qty_adj = fast_round(quantity, step)
            if qty_adj < min_qty:
                logger.error(f"[{symbol}] Qty {qty_adj} < minQty {min_qty}. Abort.")
                return False

            try:
                if is_futures:
                    self.futures.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type="MARKET",
                        quantity=qty_adj,
                        reduceOnly=reduce_only,
                    )
                else:
                    self.spot.create_order(
                        symbol=symbol, side=side, type="MARKET", quantity=qty_adj
                    )
                return True

            except BinanceAPIException as e:
                if e.code in (-1013, -4131):  # qty / price filter
                    quantity = qty_adj / 2  # halve & retry
                    time.sleep(1.5**attempt)
                    continue
                if e.code == -2022:  # Reduce-only rejected -> ok
                    return True
                logger.error(f"[{symbol}] Order error {e.code}: {e.message}")
                return False
            except Exception as e:
                logger.error(f"[{symbol}] Unknown order err: {e}")
                return False
        return False

    # -------- exchange-info helpers (cached) ---------------------------------
    @functools.lru_cache(maxsize=256)
    def get_symbol_info(self, symbol: str, is_fut: bool) -> dict:
        info = (
            self.futures.futures_exchange_info()
            if is_fut
            else self.spot.get_exchange_info()
        )
        return next(s for s in info["symbols"] if s["symbol"] == symbol)

    def get_filter(self, symbol: str, is_fut: bool, ftype: str, field: str, dflt):
        info = self.get_symbol_info(symbol, is_fut)
        for f in info["filters"]:
            if f["filterType"] == ftype:
                return float(f.get(field, dflt))
        return dflt

    def get_min_qty(self, s: str, is_f: bool) -> float:
        return self.get_filter(s, is_f, "LOT_SIZE", "minQty", 1e-5)

    def get_min_notional(self, s: str, is_f: bool) -> float:
        return self.get_filter(s, is_f, "NOTIONAL", "minNotional", 5)

    def get_step_size(self, s: str, is_f: bool) -> float:
        return self.get_filter(s, is_f, "LOT_SIZE", "stepSize", 1e-5)

    # -------- async wrappers (DRY) ------------------------------------------
    async def _run_async(self, fn, *args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args))

    async def async_spot_buy(self, s, q):
        return await self._run_async(self.spot_buy, s, q)

    async def async_spot_sell(self, s, q):
        return await self._run_async(self.spot_sell, s, q)

    async def async_margin_sell(self, s, q):
        return await self._run_async(self.margin_sell, s, q)

    async def async_futures_buy(self, s, q):
        return await self._run_async(self.futures_buy, s, q)

    async def async_futures_sell(self, s, q):
        return await self._run_async(self.futures_sell, s, q)

    async def async_close_spot_position(self, s):
        return await self._run_async(self.close_spot_position, s)

    async def async_close_futures_position(self, s):
        return await self._run_async(self.close_futures_position, s)
