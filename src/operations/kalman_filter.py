from typing import Tuple
import numpy as np

try:
    from numba import njit
except ImportError:

    def njit(*a, **k):
        def wrap(fn):
            return fn

        return wrap


# --------------------------- jit kernels ---------------------------
@njit
def kf_update(y, mu_prev, P_prev, q, r):
    mu_pred = mu_prev
    P_pred = P_prev + q
    K = P_pred / (P_pred + r)
    mu_new = mu_pred + K * (y - mu_pred)
    P_new = (1.0 - K) * P_pred
    return mu_new, P_new


@njit
def z_from_state(y, mu, P):
    return 0.0 if P == 0.0 else (y - mu) / np.sqrt(P)


@njit
def compute_signal(z, entry_z, exit_z, allow_short, last_entry) -> Tuple[int, int]:
    if last_entry == 1 and z >= exit_z:  # close LONG
        return 0, 0
    if last_entry == -1 and z <= -exit_z:  # close SHORT
        return 0, 0
    if abs(z) < exit_z:
        return 0, 0
    if z > entry_z and allow_short:
        return -1, -1
    if z < -entry_z:
        return 1, 1
    return 2, last_entry


@njit
def exp_profit(spread, mean):
    return abs(spread - mean)


# --------------------------- model class ---------------------------
class KalmanSpreadModel:
    """
    Adaptive-q Kalman filter:
        q_t = q_base + beta * |residual_t|
    """

    def __init__(self, symbol: str, cfg):
        self.symbol = symbol
        self.q_base = cfg.KALMAN_Q_BASE
        self.beta = cfg.KALMAN_Q_BETA
        self.r = cfg.KALMAN_R

        self.mu = 0.0
        self.P = 1.0
        self.ready_flag = False

        # thresholds
        self.entry_z = cfg.STRATEGY_Z_ENTRY
        self.exit_z = cfg.STRATEGY_Z_EXIT
        self.allow_short = cfg.ALLOW_SHORT_SPREAD
        self.TC = cfg.TC
        self.last_entry = 0

    # ---------------------------------------------------------------- update
    def update(self, spot: float, fut: float):
        y = spot - fut
        if not self.ready_flag:
            self.mu, self.P = y, 1e-8
            self.ready_flag = True
            return

        residual = y - self.mu
        q_t = self.q_base + self.beta * abs(residual)
        self.mu, self.P = kf_update(y, self.mu, self.P, q_t, self.r)
        if self.symbol == "HUMAUSDT":
            K = (self.P + q_t) / (self.P + q_t + self.r)
            print(self.symbol, self.mu, self.P, K, q_t, self.r, spot, fut)

    def ready(self) -> bool:
        return self.ready_flag

    # ---------------------------------------------------------------- signal
    def get_signal(self, spot: float, fut: float) -> int:
        if not self.ready_flag:
            return 0
        z = z_from_state(spot - fut, self.mu, self.P)
        sig, self.last_entry = compute_signal(
            z, self.entry_z, self.exit_z, self.allow_short, self.last_entry
        )
        if self.symbol == "HUMAUSDT":
            print(z, spot - fut)
        return sig

    # ---------------------------------------------------------------- econ filter
    def calculate_expected_tc(self, spot: float, fut: float) -> float:
        return 2 * (spot + fut) * self.TC

    def get_economic_signal(self, spot_ask: float, fut_bid: float) -> bool:
        if not self.ready_flag:
            return False
        spread = spot_ask - fut_bid
        pf = exp_profit(spread, self.mu)
        tc = self.calculate_expected_tc(spot_ask, fut_bid)
        return pf >= tc

    @staticmethod
    def get_entry_signal(spot_ask: float, fut_bid: float) -> bool:
        return fut_bid > spot_ask
