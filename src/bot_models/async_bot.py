import asyncio
import time
import configs.config as config
from operations.spread_model import SpreadModel
from operations.order_manager import OrderManager
from operations.position_manager import PositionManager
from operations.history_logger import HistoryLogger
from operations.margin_trader import SpotTrader
from operations.notifier import send_telegram_message
from datetime import date
from loguru import logger

LOGGER = "/Users/admin/Documents/BinanceBots/Logs/{t:%Y-%m-%d}_{symbol}.log"


# TODO move all actions between signal and position building
class Bot:
    def __init__(
        self,
        spot_client,
        futures_client,
        symbol: str,
        status_store=None,
        price_cache=None,
    ):
        self.symbol = symbol
        self.asset = symbol.replace("USDT", "")
        self.spot = spot_client
        self.futures = futures_client
        self.price_cache = price_cache

        self.order_manager = OrderManager(
            spot_client=spot_client, futures_client=futures_client
        )
        self.margin_trader = SpotTrader(spot_client=spot_client, config=config)
        self.position_manager = PositionManager(symbol=symbol, config=config)
        self.logger = HistoryLogger(symbol=symbol, config=config)

        self.model = SpreadModel(
            symbol=symbol, config=config, lookback=config.STRATEGY_LOOKBACK
        )
        self.model_sleep = config.SPREAD_MODEL_SLEEP
        self.entry_z = config.STRATEGY_Z_ENTRY
        self.exit_z = config.STRATEGY_Z_EXIT
        self.capital = config.CAPITAL_PER_TRADE
        self.status_store = status_store

        self.last_trade_time = 0
        self.min_trade_interval = config.TRADE_SLEEP  # seconds

        # self.entry_timestamp = None

        logger.add(LOGGER.format(t=date.today(), symbol=self.symbol))

    async def start(self):
        await asyncio.gather(self._model_loop(), self._signal_loop())

    async def fetch_prices(self):
        loop = asyncio.get_event_loop()

        spot_task = loop.run_in_executor(
            None, lambda: self.spot.get_symbol_ticker(symbol=self.symbol)
        )
        fut_task = loop.run_in_executor(
            None, lambda: self.futures.futures_mark_price(symbol=self.symbol)
        )

        try:
            spot_data, fut_data = await asyncio.gather(spot_task, fut_task)
            spot_price = round(float(spot_data["price"]), 3)
            fut_price = round(float(fut_data["markPrice"]), 3)
            return spot_price, fut_price
        except Exception as e:
            logger.error(f"[{self.symbol}] Price fetch error: {e}")
            return None, None

    async def fetch_midpoint_prices(self):
        loop = asyncio.get_event_loop()

        spot_task = loop.run_in_executor(
            None, lambda: self.spot.get_orderbook_ticker(symbol=self.symbol)
        )
        fut_task = loop.run_in_executor(
            None, lambda: self.futures.futures_orderbook_ticker(symbol=self.symbol)
        )

        try:
            spot_data, fut_data = await asyncio.gather(spot_task, fut_task)

            spot_bid = float(spot_data["bidPrice"])
            spot_ask = float(spot_data["askPrice"])
            fut_bid = float(fut_data["bidPrice"])
            fut_ask = float(fut_data["askPrice"])

            spot_price = (spot_bid + spot_ask) / 2
            fut_price = (fut_bid + fut_ask) / 2
            return spot_price, fut_price, spot_ask, fut_bid
        except Exception as e:
            logger.error(f"[{self.symbol}] Midpoint price fetch error: {e}")
            return None, None

    async def _model_loop(self):
        while True:
            try:
                if config.USE_WEBSOCKET:
                    spot = self.price_cache.get_mid("spot")
                    fut = self.price_cache.get_mid("futures")
                elif config.USE_MID_PRICE:
                    spot, fut, _, _ = await self.fetch_midpoint_prices()
                else:
                    spot, fut = await self.fetch_prices()
                if spot and fut:
                    self.model.update(spot, fut)
                logger.success(
                    f"[{self.symbol}] Model updated. {len(self.model.spread_history)}/{config.STRATEGY_LOOKBACK}"
                )
            except Exception as e:
                logger.error(f"[{self.symbol}] Model update error: {e}")
            await asyncio.sleep(self.model_sleep)

    async def _signal_loop(self):
        while True:
            if not self.model.ready():
                await asyncio.sleep(self.model_sleep)
                continue

            try:
                spot_ask = None
                fut_bid = None
                entry_cond = True
                economic_signal = True

                if config.USE_WEBSOCKET:
                    spot = self.price_cache.get_mid("spot")
                    fut = self.price_cache.get_mid("futures")
                elif config.USE_MID_PRICE:
                    spot, fut, spot_ask, fut_bid = await self.fetch_midpoint_prices()
                else:
                    spot, fut = await self.fetch_prices()
                if not spot or not fut:
                    await asyncio.sleep(0.5)
                    continue

                spread = spot - fut
                signal = self.model.get_signal(spread)

                # Respect directional constraints
                if signal == -1 and not config.ALLOW_SHORT_SPREAD:
                    signal = 0

                if self.position_manager.is_open and signal == 0:
                    if config.USE_BOOK_BASED_EXIT:
                        exit_cond = self.should_exit_long()
                        if exit_cond:
                            await self.close_position()
                    else:
                        await self.close_position()


                if config.USE_WEBSOCKET:
                    spot_ask = self.price_cache.spot.get("ask")
                    fut_bid = self.price_cache.futures.get("bid")
                    economic_signal = self.model.get_economic_signal(spot_ask, fut_bid)
                    entry_cond = self.should_enter_long(spot_ask, fut_bid)
                elif spot_ask and fut_bid:
                    economic_signal = self.model.get_economic_signal(spot_ask, fut_bid)
                    entry_cond = self.model.get_entry_signal(spot_ask, fut_bid)

                if (
                    not self.position_manager.is_open
                    and signal in (1, -1)
                    and economic_signal
                    and entry_cond
                ):
                    now = time.time()
                    if (now - self.last_trade_time) > self.min_trade_interval:
                        await self.open_position(signal, spot_ask, fut_bid)
                        self.last_trade_time = now
                        self.entry_timestamp = now

            except Exception as e:
                logger.error(f"[{self.symbol}] Signal loop error: {e}")

            try:
                await asyncio.wait_for(self.price_cache.updated_event.wait(), timeout=2)
                self.price_cache.updated_event.clear()
            except asyncio.TimeoutError:
                pass

    async def open_position(self, direction: int, spot_price: float, fut_price: float):
        try:
            qty = round(self.capital / fut_price, 6)
            side = "LONG" if direction == 1 else "SHORT"

            if side == "LONG":
                tasks = [
                    self.order_manager.async_spot_buy(self.symbol, qty),
                    self.order_manager.async_futures_sell(self.symbol, qty),
                ]
            else:
                tasks = [
                    self.order_manager.async_margin_sell(self.symbol, qty),
                    self.order_manager.async_futures_buy(self.symbol, qty),
                ]

            spot_success, fut_success = await asyncio.gather(*tasks)

            if spot_success and fut_success:
                self.position_manager.open(side, spot_price, fut_price, qty)
                self.logger.log_event(
                    {
                        "Action": "OPEN",
                        "Side": side,
                        "Symbol": self.symbol,
                        "Size": qty,
                        "Futures Entry Price": fut_price,
                        "Spot Entry Price": spot_price,
                    }
                )
            else:
                logger.warning(f"[{self.symbol}] Order failed. Rollback may be needed.")
        except Exception as e:
            self.liquidate_all_positions()
            logger.error(
                f"[ERROR - {self.symbol}] Failed to open position: {e}. "
                f"Closed all open positions."
            )

    async def close_position(self):
        try:
            # side = self.position_manager.side

            # logger.debug(f"[{self.symbol}] Closing {side} position...")

            tasks = [
                self.order_manager.async_close_spot_position(self.symbol),
                self.order_manager.async_close_futures_position(self.symbol),
            ]
            spot_closed, fut_closed = await asyncio.gather(*tasks)

            if spot_closed and fut_closed:
                spot_price, fut_price = await self.fetch_prices()
                result = self.position_manager.close(spot_price, fut_price)
                self.logger.log_event({"Action": "CLOSE", **result})
                if config.TELEGRAM_ENABLED:
                    msg = (
                        f"✅ *Trade Closed* — {self.symbol}\n"
                        f"Side: `{result['Side']}`\n"
                        f"Size: `{result['Size']}`\n"
                        f"PnL: `${result['Total Net PnL (USD)']:.4f}`\n"
                        f"Holding Duration (minutes): `{result['Holding Duration (minutes)']:.2f}`"
                    )
                    send_telegram_message(msg, config)
                # logger.debug(f"[{self.symbol}] Position closed.")
            else:
                logger.warning(f"[{self.symbol}] Close failed.")
        except Exception as e:
            self.liquidate_all_positions()
            logger.error(
                f"[ERROR - {self.symbol}] Close failed: {e}. Closed all open positions."
            )

    def liquidate_all_positions(self):
        liquidate_spot = False
        liquidate_futures = False
        while not (liquidate_spot and liquidate_futures):
            liquidate_spot = self.order_manager.close_position(self.symbol, False)
            liquidate_futures = self.order_manager.close_position(self.symbol, True)

    def should_exit_long(self) -> bool:
        now = time.time()
        time_in_trade = (
            now - self.entry_timestamp if hasattr(self, "entry_timestamp") else 0
        )

        spot_bid = self.price_cache.spot.get("bid")
        fut_ask = self.price_cache.futures.get("ask")

        exit_executable = fut_ask and spot_bid and self.position_manager.calc_total_pnl(spot_bid, fut_ask) >= 0
        timeout = time_in_trade > config.EXIT_TIMEOUT_SECONDS

        return exit_executable or timeout

    @staticmethod
    def should_enter_long(spot_ask: float, fut_bid: float) -> bool:
        return fut_bid and spot_ask and float(fut_bid) > float(spot_ask)
