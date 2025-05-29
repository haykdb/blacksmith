from typing import Tuple
import numpy as np
from numba import njit


@njit
def compute_stats(arr: np.ndarray) -> Tuple[float, float]:
    mean = np.mean(arr)
    std = np.std(arr)
    return mean, std


@njit
def compute_zscore(current: float, mean: float, std: float) -> float:
    if std == 0:
        return 0.0
    return (current - mean) / std


@njit
def compute_expected_profit(spread: float, mean: float) -> float:
    return abs(spread - mean)


@njit
def check_signal(
    z: float, entry_z: float, exit_z: float, last_signal: int, allow_short: bool
) -> int:
    if last_signal == 1 and z >= exit_z:
        return 0
    elif last_signal == -1 and z <= -exit_z:
        return 0

    if abs(z) < exit_z:
        return 0
    elif z > entry_z and allow_short:
        return -1
    elif z < -entry_z:
        return 1
    return 2


class SpreadModel:
    def __init__(self, symbol: str, config, lookback: int = 120):
        self.symbol = symbol
        self.lookback = lookback
        self.spread_history = np.zeros(lookback, dtype=np.float64)
        self.ptr = 0
        self.filled = False
        self.entry_signal = 0
        self.allow_short = False
        self.entry_z = 1.5
        self.exit_z = 0.5
        self.TC = config.TC

    def update(self, spot_price: float, futures_price: float):
        spread = spot_price - futures_price
        self.spread_history[self.ptr] = spread
        self.ptr = (self.ptr + 1) % self.lookback
        if self.ptr == 0:
            self.filled = True

    def ready(self) -> bool:
        return self.filled

    def get_array(self) -> np.ndarray:
        if self.filled:
            return self.spread_history
        return self.spread_history[: self.ptr]

    def get_signal(self, spot: float, fut: float) -> int:
        if not self.ready():
            return 0
        spread = spot - fut
        arr = self.get_array()
        mean, std = compute_stats(arr)
        z = compute_zscore(spread, mean, std)
        signal = check_signal(
            z, self.entry_z, self.exit_z, self.entry_signal, self.allow_short
        )
        if signal in (-1, 1):
            self.entry_signal = signal
        return signal

    def calculate_expected_tc(self, spot: float, futures: float) -> float:
        return 2 * (spot * self.TC + futures * self.TC)

    def get_economic_signal(self, spot: float, futures: float) -> bool:
        if not self.ready():
            return False
        spread = spot - futures
        arr = self.get_array()
        mean, _ = compute_stats(arr)
        expected_profit = compute_expected_profit(spread, mean)
        expected_cost = self.calculate_expected_tc(spot, futures)
        return expected_profit >= expected_cost

    @staticmethod
    def get_entry_signal(spot_ask: float, fut_bid: float) -> bool:
        return fut_bid > spot_ask
