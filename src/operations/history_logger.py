import csv, os, threading
from datetime import date
from pathlib import Path
from queue import SimpleQueue
from typing import Dict, List

COLUMNS: List[str] = [
    "Action",
    "Side",
    "Symbol",
    "Size",
    "Spot Entry",
    "Spot Exit",
    "Fut Entry",
    "Fut Exit",
    "Entry Time",
    "Exit Time",
    "Spot PnL",
    "Fut PnL",
    "Total PnL",
    "Hold (min)",
]


class HistoryLogger:
    """
    Keeps a CSV file open for fast appends.
    Uses a tiny background thread so async code never blocks on disk I/O.
    """

    def __init__(self, symbol: str, cfg):
        self.path = Path(
            cfg.TRADE_LOG_PATH.format(symbol=symbol, t=date.today())
        ).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        new_file = not self.path.exists()
        self.file = self.path.open("a", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=COLUMNS)
        if new_file:
            self.writer.writeheader()
            self.file.flush()

        # background queue + thread
        self.q: SimpleQueue = SimpleQueue()
        self.thread = threading.Thread(target=self._writer_loop, daemon=True)
        self.thread.start()

    # ------------------------------------------------------------------ public
    def log_event(self, row: Dict[str, str]):
        """Enqueue a row; return immediately."""
        self.q.put(row)

    # ---------------------------------------------------------------- internal
    def _writer_loop(self):
        while True:
            row = self.q.get()
            try:
                self.writer.writerow(row)
                self.file.flush()
            except Exception as e:
                # basic safeguard – in prod you might log this elsewhere
                print(f"[HistoryLogger] write error: {e}")
