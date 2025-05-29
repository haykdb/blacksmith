# async_bot.py  –  drop into src/bot_models/

import asyncio, time
from datetime import date
import configs.config as config

from operations.order_manager import OrderManager, fast_round
from operations.position_manager import PositionManager
from operations.history_logger import HistoryLogger
from operations.margin_trader import SpotTrader
from operations.notifier import send_telegram_message, async_send_telegram_message
from operations.spread_model import SpreadModel
from operations.price_cache import PriceCache   # only used if USE_WEBSOCKET
from operations.kalman_filter import KalmanSpreadModel


class Bot:
    def __init__(self, spot_client, futures_client, symbol: str,
                 status_store=None, price_cache: PriceCache = None):

        self.symbol  = symbol
        self.asset   = symbol.replace("USDT", "")
        self.spot    = spot_client
        self.futures = futures_client
        self.price_cache = price_cache        # may be None in REST mode

        self.order_manager   = OrderManager(spot_client, futures_client)
        self.margin_trader   = SpotTrader(spot_client, config)
        self.position_manager = PositionManager(symbol, config)
        self.logger = HistoryLogger(symbol, config)

        if config.USE_KALMAN:
            self.model = KalmanSpreadModel(symbol, config)
        else:
            self.model  = SpreadModel(symbol, config, lookback=config.STRATEGY_LOOKBACK)
        self.model_sleep = config.SPREAD_MODEL_SLEEP
        self.capital     = config.CAPITAL_PER_TRADE

        self.last_trade_time = 0.0
        self.last_entry_time = 0.0
        self.min_trade_interval = config.TRADE_SLEEP         # seconds
        self.entry_timestamp: float = 0.0

    # ---------------------------------------------------------------- helpers
    async def _get_prices(self):
        """
        Returns: spot_mid, fut_mid, spot_ask, fut_bid  (None if not available)
        """
        # --- 1. WebSocket feed ------------------------------------------------
        if config.USE_WEBSOCKET:
            spot_mid, fut_mid = self.price_cache.get_mid_prices()
            spot_ask = self.price_cache.spot_ask
            fut_bid  = self.price_cache.fut_bid
            spot_bid = self.price_cache.spot_bid
            fut_ask = self.price_cache.fut_ask
            return spot_mid, fut_mid, spot_ask, fut_bid, spot_bid, fut_ask

        loop = asyncio.get_event_loop()

        # --- 2. REST midpoint feed -------------------------------------------
        if config.USE_MID_PRICE:
            spot_data, fut_data = await asyncio.gather(
                loop.run_in_executor(None, lambda: self.spot.get_orderbook_ticker(symbol=self.symbol)),
                loop.run_in_executor(None, lambda: self.futures.futures_orderbook_ticker(symbol=self.symbol)),
            )
            sb, sa = float(spot_data["bidPrice"]), float(spot_data["askPrice"])
            fb, fa = float(fut_data["bidPrice"]),  float(fut_data["askPrice"])
            return (sb + sa) / 2, (fb + fa) / 2, sa, fb, sb, fa

        # --- 3. Last / mark fallback ------------------------------------------
        spot_d, fut_d = await asyncio.gather(
            loop.run_in_executor(None, lambda: self.spot.get_symbol_ticker(symbol=self.symbol)),
            loop.run_in_executor(None, lambda: self.futures.futures_mark_price(symbol=self.symbol)),
        )
        return float(spot_d["price"]), float(fut_d["markPrice"]), None, None, None, None

    # ---------------------------------------------------------------- model loop
    async def _model_loop(self):
        while True:
            try:
                spot, fut, *_ = await self._get_prices()
                if spot and fut:
                    self.model.update(spot, fut)
            except Exception as e:
                print(e)
            # Wait on WebSocket tick, else small sleep
            if config.USE_WEBSOCKET:
                try:
                    await asyncio.wait_for(self.price_cache.updated_event.wait(),
                                           timeout=2)
                    self.price_cache.updated_event.clear()
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(self.model_sleep)

    # ---------------------------------------------------------------- signal loop
    async def _signal_loop(self):
        while True:
            if not self.model.ready():
                await asyncio.sleep(self.model_sleep)
                continue

            try:
                spot, fut, spot_ask, fut_bid, spot_bid, fut_ask = await self._get_prices()
                if spot is None or fut is None:
                    await asyncio.sleep(0.3)
                    continue

                # --------------- signal from JIT SpreadModel ------------------
                signal = 1 if (spot_ask - fut_bid) / fut_bid >= 0.002  else 2 # self.model.get_signal(spot, fut)
                signal = 0 if spot_bid <= fut_ask else signal
                if signal == -1 and not config.ALLOW_SHORT_SPREAD:
                    signal = 0

                # --------------- handle exit ---------------------------------
                if self.position_manager.is_open and signal == 0:
                    if time.time() - self.last_entry_time > config.MIN_HOLDING_SECONDS:
                        if config.USE_BOOK_BASED_EXIT and spot_bid and fut_ask:
                            if self.should_exit_long(spot_bid=spot_bid, fut_ask=fut_ask):
                                await self.close_position()
                        else:
                            await self.close_position()

                # --------------- entry filters ------------------------------
                if spot_ask and fut_bid:
                    economic_ok = True # self.model.get_economic_signal(spot_ask, fut_bid)
                    entry_ok    = self.model.get_entry_signal(spot_ask, fut_bid)
                else:
                    economic_ok = entry_ok = True      # fallback

                if (not self.position_manager.is_open and
                        signal in (1, -1) and economic_ok and entry_ok):
                    if time.time() - self.last_trade_time > self.min_trade_interval:
                        await self.open_position(signal, spot, fut)
                        self.last_trade_time = self.last_entry_time = time.time()

            except Exception as e:
                print(e)

            # Wait on WebSocket tick, else small sleep
            if config.USE_WEBSOCKET:
                try:
                    await asyncio.wait_for(self.price_cache.updated_event.wait(),
                                           timeout=2)
                    self.price_cache.updated_event.clear()
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(config.TRADE_SLEEP)

    # ---------------------------------------------------------------- open/close
    async def open_position(self, direction: int, spot_mid: float, fut_mid: float):
        qty = fast_round(self.capital / fut_mid, 1e-6)
        side = "LONG" if direction == 1 else "SHORT"

        tasks = (
            [self.order_manager.async_spot_buy(self.symbol, qty),
             self.order_manager.async_futures_sell(self.symbol, qty)]
            if side == "LONG" else
            [self.order_manager.async_margin_sell(self.symbol, qty),
             self.order_manager.async_futures_buy(self.symbol, qty)]
        )
        spot_ok, fut_ok = await asyncio.gather(*tasks)

        if spot_ok and fut_ok:
            self.position_manager.open(side, spot_mid, fut_mid, qty)
            self.logger.log_event({
                "Action": "OPEN",
                "Side": side,
                "Symbol": self.symbol,
                "Size": f"{qty:.6f}",
                "Spot Entry": f"{spot_mid:.4f}",
                "Fut Entry": f"{fut_mid:.4f}",
                "Entry Time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            })

    async def close_position(self):
        spot_closed, fut_closed = await asyncio.gather(
            self.order_manager.async_close_spot_position(self.symbol),
            self.order_manager.async_close_futures_position(self.symbol)
        )
        if spot_closed and fut_closed:
            spot_px, fut_px, *_ = await self._get_prices()
            result = self.position_manager.close(spot_px, fut_px)
            self.logger.log_event({"Action": "CLOSE", **result})
            if config.TELEGRAM_ENABLED:
                msg = (
                    f"✅ *Trade Closed* — {self.symbol}\n"
                    f"Side: `{result['Side']}`\n"
                    f"Size: `{result['Size']}`\n"
                    f"PnL: `${result['Total PnL']:.4f}`\n"
                    f"Hold: `{result['Hold (min)']}` min"
                )
                await async_send_telegram_message(msg, config)

    # ---------------------------------------------------------------- helpers
    def should_exit_long(self, spot_bid: float, fut_ask: float) -> bool:
        timeout = time.time() - self.entry_timestamp > config.EXIT_TIMEOUT_SECONDS
        pnl_ok  = self.position_manager.calc_total_pnl(spot_bid, fut_ask) >= 0
        return pnl_ok or timeout

    @staticmethod
    def should_enter_long(spot_ask: float, fut_bid: float) -> bool:
        return fut_bid > spot_ask

    # ---------------------------------------------------------------- run entry
    async def start(self):
        await asyncio.gather(self._model_loop(), self._signal_loop())
