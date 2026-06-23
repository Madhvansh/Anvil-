"""Live re-validation: resolved ``tip_live`` outcomes (with stored realized ret) re-aggregate into
per-cell verdicts via the SAME battery the backtest uses. A clearly losing cell never becomes
headline-eligible; the mechanics (cells built, totals counted) hold."""

from __future__ import annotations

import tempfile

from anvil.backtest.revalidate import revalidate_from_live
from anvil.tips.store import IssuedTipStore, TipValidationStore
from anvil.tips.types import Tip


def _tip(symbol: str, i: int, conviction: float = 0.6) -> Tip:
    return Tip(
        underlying=symbol, created_ts=f"2026-01-{i:02d}T15:30:00+05:30",
        resolve_ts=f"2026-01-{i+5:02d}T15:30:00+05:30", horizon_days=5.0,
        structure="equity_directional", direction="bullish",
        legs=[{"side": "BUY", "lots": 1, "instrument_type": "EQ", "ref_price": 100.0, "symbol": symbol}],
        conviction=conviction, edge_prob=conviction, gross_ev=10.0, round_trip_cost=2.0,
        cost_adjusted_ev=8.0, max_loss=1000.0, max_profit=1600.0, entry_debit_credit=100.0,
        lot_size=1, regime_bucket="xs_momentum", source="tip_live")


def test_revalidate_builds_cells_and_rejects_losing():
    with tempfile.TemporaryDirectory() as td:
        istore = IssuedTipStore(f"{td}/iss.duckdb")
        try:
            # 12 resolved LOSING tips across two symbols & several days (negative ret).
            for i in range(1, 13):
                sym = "AAA" if i % 2 else "BBB"
                t = _tip(sym, i)
                istore.record(t)
                istore.mark_resolved(t.tip_id, outcome=0,
                                     resolved_ts=f"2026-01-{i+5:02d}T16:00:00+05:30",
                                     net_pnl=-500.0, ret=-0.5)
            vstore = TipValidationStore(f"{td}/tv.duckdb")
            res = revalidate_from_live(issued_store=istore, validation_store=vstore, min_samples=5)
            # cells = AAA, BBB, and the pooled EQUITY (equity tips feed both their symbol + the pool)
            assert res["cells"] == 3
            assert res["headline_cells"] == 0  # losing evidence can never headline
            pooled = vstore.get("equity_directional", "xs_momentum", "EQUITY")
            assert pooled["n"] == 12 and pooled["win_rate"] == 0.0
            assert vstore.get("equity_directional", "xs_momentum", "AAA")["n"] == 6
            vstore.close()
        finally:
            istore.close()
