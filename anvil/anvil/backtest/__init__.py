"""Honest backtesting lab — a real, out-of-sample calibration curve from EOD history.

The guarantee the product sells is calibration, so the backtester's integrity *is* the
product. Two biases are guarded as **failing tests**, not warnings:

  * **look-ahead** — a forecast may only use data dated on/before its as-of day, and is
    resolved strictly at its expiry settlement (never an earlier or a "today" level);
  * **survivorship** — only contracts that actually traded (OI or volume > 0) on the as-of
    day are usable, so phantom/never-traded strikes can't flatter the curve.

See ``asof.AsOfContext`` (the guard layer) and ``runner.run_backtest`` (the walk-forward).
"""

from .asof import AsOfContext, LookAheadError, SurvivorshipError, filter_liquid
from .data import BhavcopyArchive
from .runner import run_backtest

__all__ = [
    "AsOfContext",
    "LookAheadError",
    "SurvivorshipError",
    "filter_liquid",
    "BhavcopyArchive",
    "run_backtest",
]
