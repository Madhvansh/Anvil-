"""Anvil paper-trading simulator (PRIVATE to the paper-trading subsystem).

Realistic mock fills (spread + slippage + India F&O charges), a position lifecycle with
mark-to-market and exit management, a portfolio Risk Governor, and a SPAN-lite margin model.
Gated behind the ``paper_trading`` feature flag; real placement stays on the ``AssistedExecutor``
/ ``TRADING_AUTOMATION`` rail (untouched).
"""

from __future__ import annotations

from .account import PaperBook
from .calibration import paper_calibration, record_conviction, resolve_conviction
from .gateway import PaperBrokerGateway
from .governor import GovernorConfig, RiskGovernor, Verdict
from .report import run_report
from .state import EquityPoint, Fill, PaperLeg, PaperPosition

__all__ = [
    "PaperBook",
    "PaperBrokerGateway",
    "RiskGovernor",
    "GovernorConfig",
    "Verdict",
    "PaperPosition",
    "PaperLeg",
    "Fill",
    "EquityPoint",
    "run_report",
    "record_conviction",
    "resolve_conviction",
    "paper_calibration",
]
