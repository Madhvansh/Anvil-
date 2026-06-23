"""Phase 7 — `anvil paper replay` runs a complete deterministic mock session and prints a report
(zero keys, demo path). This is the minimal end-to-end "mock session today + effectiveness" path."""

from __future__ import annotations

import json

from anvil.cli import main


def _args(extra):
    return [
        "paper", "replay", "--underlying", "NIFTY", "--steps", "5", "--cadence", "14400",
        "--seed", "7", "--no-ledger", "--start", "2026-06-19T03:45:00+00:00", "--expiry", "2026-06-26",
    ] + extra


def test_paper_replay_cli_prints_report(capsys):
    rc = main(_args([]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "PAPER SESSION REPORT" in out
    assert "ACCOUNT" in out and "net P&L" in out
    assert "RISK" in out


def test_paper_replay_cli_json_is_complete(capsys):
    rc = main(_args(["--json"]))
    assert rc == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["summary"]["starting_capital"] > 0
    assert "performance_lab" in rep and "equity_curve" in rep
    # Deterministic + flat at the end of a replay session.
    assert rep["summary"]["open_positions"] == 0
