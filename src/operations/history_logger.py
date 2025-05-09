# history_logger.py

import csv
import os
from datetime import date
from typing import Dict

COLUMNS = [
    "Action",
    "Side",
    "Symbol",
    "Size",
    "Spot Entry Price",
    "Spot Exit Price",
    "Futures Entry Price",
    "Futures Exit Price",
    "Entry Time",
    "Exit Time",
    "Spot PnL (USD)",
    "Futures PnL (USD)",
    "Total Net PnL (USD)",
    "Holding Duration (minutes)",
]


class HistoryLogger:

    def __init__(self, symbol: str, config):
        self.symbol = symbol
        self.config = config

    def log_event(self, event_data: Dict[str, str]):
        path = os.path.abspath(
            self.config.TRADE_LOG_PATH.format(symbol=self.symbol, t=date.today())
        )
        file_exists = os.path.exists(path)

        if not os.path.exists(path):
            with open(path, "a", newline="") as csvfile:
                pass

        with open(path, "a", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=COLUMNS)

            if not file_exists:
                writer.writeheader()

            writer.writerow(event_data)
