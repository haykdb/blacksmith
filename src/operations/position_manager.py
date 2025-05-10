from datetime import datetime, timezone
from typing import Union, Dict
from loguru import logger


class PositionManager:
    def __init__(self, symbol: str, config):
        self.config = config
        self.symbol = symbol
        self.side: Union[str, None] = None
        self.spot_entry_price: float = 0.0
        self.futures_entry_price: float = 0.0
        self.size: float = 0.0
        self.entry_time: Union[datetime, None] = None
        self.is_open: bool = False

    def open(self, side: str, spot_price: float, futures_price: float, size: float):
        if self.is_open:
            raise Exception(
                "Position already open. Must close before opening a new one."
            )

        self.side = side  # 'LONG' or 'SHORT'
        self.spot_entry_price = spot_price
        self.futures_entry_price = futures_price
        self.size = size
        self.entry_time = datetime.now(tz=timezone.utc)
        self.is_open = True

    def close(self, spot_exit_price: float, futures_exit_price: float) -> Dict:
        if not self.is_open:
            raise Exception("No open position to close.")

        exit_time = datetime.now(tz=timezone.utc)

        # Spot and Futures PnL
        if self.side == "LONG":
            spot_pnl = (spot_exit_price - self.spot_entry_price) * self.size
            futures_pnl = (self.futures_entry_price - futures_exit_price) * self.size
        elif self.side == "SHORT":
            spot_pnl = (self.spot_entry_price - spot_exit_price) * self.size
            futures_pnl = (futures_exit_price - self.futures_entry_price) * self.size
        else:
            raise Exception("Invalid side.")

        estimated_fee_rate = self.config.TC
        notional = (
            self.spot_entry_price
            + spot_exit_price
            + self.futures_entry_price
            + futures_exit_price
        ) * self.size
        fees = estimated_fee_rate * notional
        total_net_pnl = spot_pnl + futures_pnl - fees

        if not self.entry_time is None:
            holding_minutes = round(
                (exit_time - self.entry_time).total_seconds() / 60, 2
            )
        else:
            holding_minutes = 99999999

        result = {
            "Action": "CLOSE",
            "Side": self.side,
            "Symbol": self.symbol,
            "Size": round(self.size, 6),
            "Spot Entry Price": round(self.spot_entry_price, 4),
            "Spot Exit Price": round(spot_exit_price, 4),
            "Futures Entry Price": round(self.futures_entry_price, 4),
            "Futures Exit Price": round(futures_exit_price, 4),
            "Entry Time": (
                self.entry_time.strftime("%Y-%m-%d %H:%M:%S")
                if not self.entry_time is None
                else "00:00:00:FALSE"
            ),
            "Exit Time": exit_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Spot PnL (USD)": round(spot_pnl, 4),
            "Futures PnL (USD)": round(futures_pnl, 4),
            "Total Net PnL (USD)": round(total_net_pnl, 4),
            "Holding Duration (minutes)": holding_minutes,
        }

        self.reset()
        return result

    def position_info(self) -> str:
        if self.is_open:
            return f"[POSITION]: {self.side} Spread, Spot Entry: {self.spot_entry_price}, Futures Entry: {self.futures_entry_price}."
        else:
            return "No OPEN Positions at the moment."

    def calc_closing_spot_pnl(self, exit_spot_price: float) -> float:
        if not self.is_open:
            raise ValueError(
                f"Trying to calculate spot closing pnl when position is closed."
            )
        if self.side == "LONG":
            spot_pnl = (exit_spot_price - self.spot_entry_price) * self.size
        else:
            spot_pnl = (self.spot_entry_price - exit_spot_price) * self.size
        return spot_pnl

    def calc_closing_futures_pnl(self, exit_futures_price: float) -> float:
        if not self.is_open:
            raise ValueError(
                f"Trying to calculate futures closing pnl when position is closed."
            )
        if self.side == "LONG":
            futures_pnl = (self.futures_entry_price - exit_futures_price) * self.size
        else:
            futures_pnl = (exit_futures_price - self.futures_entry_price) * self.size
        return futures_pnl

    def calc_total_pnl(
        self, exit_spot_price: float, exit_futures_price: float
    ) -> float:
        spot_pnl = self.calc_closing_spot_pnl(exit_spot_price)
        futures_pnl = self.calc_closing_futures_pnl(exit_futures_price)
        return spot_pnl + futures_pnl

    def get_futures_entry_side(self) -> str:
        assert self.is_open
        if self.side == "LONG":
            return "SELL"
        else:
            return "BUY"

    def reset(self):
        self.side = None
        self.spot_entry_price = 0
        self.futures_entry_price = 0
        self.size = 0
        self.entry_time = None
        self.is_open = False

    @staticmethod
    def get_futures_position_size(futures_client, symbol: str) -> float:
        info = futures_client.futures_position_information(symbol=symbol)
        return float(info[0]["positionAmt"])

    @staticmethod
    def get_spot_balance(spot_client, asset: str) -> float:
        account = spot_client.get_account()
        for balance in account["balances"]:
            if balance["asset"] == asset:
                return float(balance["free"]) + float(balance["locked"])
        return 0.0

    @staticmethod
    def get_margin_position(spot_client, asset: str) -> Dict[str, float]:
        account = spot_client.get_margin_account()
        for item in account["userAssets"]:
            if item["asset"] == asset:
                borrowed = float(item["borrowed"])
                net_position = float(item["free"]) - borrowed
                return {"borrowed": borrowed, "net_position": net_position}
        return {"borrowed": 0.0, "net_position": 0.0}

    def check_all_positions_closed(
        self, spot_client, futures_client, symbol: str, asset: str
    ) -> bool:
        fut_size = abs(self.get_futures_position_size(futures_client, symbol))
        spot_balance = self.get_spot_balance(spot_client, asset)
        margin = self.get_margin_position(spot_client, asset)
        borrowed = margin["borrowed"]

        logger.debug(
            f"[CHECK] Futures: {fut_size:.6f}, Spot: {spot_balance:.6f}, Margin Borrowed: {borrowed:.6f}"
        )

        return fut_size < 1e-6 and spot_balance < 1e-6 and borrowed < 1e-6

    def get_total_notional(self, spot_price: float, futures_price: float) -> float:
        if not self.is_open:
            return 0.0
        return self.size * (spot_price + futures_price)
