from typing import Tuple, List, Optional
import numpy as np
from loguru import logger


class SpreadModel:
    def __init__(self, symbol: str, config, lookback: int = 120):
        self.lookback = lookback
        self.symbol = symbol
        self.spread_history: List[float] = []
        self.entry_signal_m1: Optional[int] = None
        self.allow_short = False
        self.entry_z = 1.5
        self.exit_z = 0.5
        self.TC = config.TC

    def update(self, spot_price: float, futures_price: float):
        spread = spot_price - futures_price
        self.spread_history.append(spread)
        self.spread_history = self.spread_history[-self.lookback :]

    def ready(self) -> bool:
        return len(self.spread_history) >= self.lookback

    def stats(self) -> Tuple:
        if not self.ready():
            return None, None
        mean = np.mean(self.spread_history)
        std = np.std(self.spread_history)
        return mean, std

    def zscore(self, current_spread: float) -> float:
        mean, std = self.stats()
        if std is None or std == 0:
            return 0
        return (current_spread - mean) / std

    def get_signal(self, spread: float):

        z = self.zscore(spread)
        # logger.info(f"[STRATEGY] {self.symbol} Z-score: {round(z, 2)}")

        if not self.entry_signal_m1 is None:
            if self.entry_signal_m1 == 1 and z >= self.exit_z:
                return 0
            elif self.entry_signal_m1 == -1 and z <= -self.exit_z:
                return 0

        if abs(z) < self.exit_z:
            return 0
        elif z > self.entry_z and self.allow_short:
            self.entry_signal_m1 = -1
            return -1
        elif z < -self.entry_z:
            self.entry_signal_m1 = 1
            return 1
        return 2

    def calculate_expected_tc(self, spot: float, futures: float) -> float:
        return 2 * (spot * self.TC + futures * self.TC)

    def calculate_expected_profit(self, spread: float, mean: float) -> float:
        if len(self.spread_history) < self.lookback:
            return 0.0
        return abs(spread - mean)

    def get_economic_signal(self, spot: float, futures: float) -> bool:
        spread = spot - futures
        mean, _ = self.stats()
        exp_pf = self.calculate_expected_profit(spread, mean)
        exp_tc = self.calculate_expected_tc(spot, futures)
        # logger.info(
        #     f"[SPREAD {self.symbol}] Spread: {spread:2f}, Mean: {mean:2f}, PF: {exp_pf:2f}, TC: {exp_tc:2f}"
        # )
        return bool(exp_pf >= exp_tc)

    @staticmethod
    def get_entry_signal(spot_ask: float, fut_bid: float) -> bool:
        return fut_bid > spot_ask
