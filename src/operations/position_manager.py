from datetime import datetime, timezone
from typing import Dict
import numpy as np
from numba import njit


@njit
def pnl_math(
    side_flag: int,  # +1 = LONG, -1 = SHORT
    spot_entry: float,
    spot_exit: float,
    fut_entry: float,
    fut_exit: float,
    size: float,
    fee_rate: float,
):
    """
    side_flag : +1 for LONG spread, -1 for SHORT spread
    returns spot_pnl , fut_pnl , total_net
    """
    if side_flag == 1:  # LONG  ⟹ long-spot / short-fut
        spot_pnl = (spot_exit - spot_entry) * size
        fut_pnl = (fut_entry - fut_exit) * size
    else:  # SHORT ⟹ short-spot / long-fut
        spot_pnl = (spot_entry - spot_exit) * size
        fut_pnl = (fut_exit - fut_entry) * size

    gross = spot_pnl + fut_pnl
    notional = (spot_entry + spot_exit + fut_entry + fut_exit) * size
    fees = fee_rate * notional
    return spot_pnl, fut_pnl, gross - fees


class PositionManager:
    def __init__(self, symbol: str, config):
        self.cfg = config
        self.symbol = symbol
        self.reset()

    # ---------- open / close ------------------------------------------------
    def open(self, side: str, spot_price: float, fut_price: float, size: float):
        if self.is_open:
            raise RuntimeError("Position already open.")

        self.side_flag = 1 if side == "LONG" else -1  # numeric flag for jit
        self.side = side
        self.spot_entry = spot_price
        self.fut_entry = fut_price
        self.size = size
        self.entry_time = datetime.now(tz=timezone.utc)
        self.is_open = True

    def close(self, spot_exit: float, fut_exit: float) -> Dict:
        if not self.is_open:
            raise RuntimeError("No open position.")

        now = datetime.now(tz=timezone.utc)

        spot_pnl, fut_pnl, total_net = pnl_math(
            self.side_flag,
            self.spot_entry,
            spot_exit,
            self.fut_entry,
            fut_exit,
            self.size,
            self.cfg.TC,
        )

        hold_min = round((now - self.entry_time).total_seconds() / 60, 2)

        result = {
            "Action": "CLOSE",
            "Side": self.side,
            "Symbol": self.symbol,
            "Size": round(self.size, 6),
            "Spot Entry": round(self.spot_entry, 4),
            "Spot Exit": round(spot_exit, 4),
            "Fut Entry": round(self.fut_entry, 4),
            "Fut Exit": round(fut_exit, 4),
            "Entry Time": self.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Exit Time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "Spot PnL": round(spot_pnl, 4),
            "Fut PnL": round(fut_pnl, 4),
            "Total PnL": round(total_net, 4),
            "Hold (min)": hold_min,
        }

        self.reset()
        return result

    # ---------- fast run-time helpers ---------------------------------------
    def calc_total_pnl(self, spot_px: float, fut_px: float) -> float:
        if not self.is_open:
            return 0.0
        _, _, net = pnl_math(
            self.side_flag,
            self.spot_entry,
            spot_px,
            self.fut_entry,
            fut_px,
            self.size,
            self.cfg.TC,
        )
        return net

    # ---------- state / util -------------------------------------------------
    def reset(self):
        self.side = None
        self.side_flag = 0
        self.spot_entry = 0.0
        self.fut_entry = 0.0
        self.size = 0.0
        self.entry_time = None
        self.is_open = False

    def position_info(self) -> str:
        if self.is_open:
            return (
                f"[POSITION] {self.side} | Spot {self.spot_entry:.2f} | "
                f"Fut {self.fut_entry:.2f} | Size {self.size}"
            )
        return "No open position."

    # ---------- static REST helpers (unchanged) -----------------------------
    @staticmethod
    def get_futures_position_size(futures_client, symbol: str) -> float:
        info = futures_client.futures_position_information(symbol=symbol)
        return float(info[0]["positionAmt"])

    @staticmethod
    def get_spot_balance(spot_client, asset: str) -> float:
        bal = next(
            b for b in spot_client.get_account()["balances"] if b["asset"] == asset
        )
        return float(bal["free"]) + float(bal["locked"])

    @staticmethod
    def get_margin_position(spot_client, asset: str) -> Dict[str, float]:
        acc = spot_client.get_margin_account()
        item = next(x for x in acc["userAssets"] if x["asset"] == asset)
        borrowed = float(item["borrowed"])
        net = float(item["free"]) - borrowed
        return {"borrowed": borrowed, "net_position": net}

    def check_all_positions_closed(self, spot_c, futures_c, symbol, asset) -> bool:
        fut = abs(self.get_futures_position_size(futures_c, symbol))
        bal = self.get_spot_balance(spot_c, asset)
        borrowed = self.get_margin_position(spot_c, asset)["borrowed"]
        return fut < 1e-6 and bal < 1e-6 and borrowed < 1e-6

    def get_total_notional(self, spot_px: float, fut_px: float) -> float:
        if not self.is_open:
            return 0.0
        return self.size * (spot_px + fut_px)
