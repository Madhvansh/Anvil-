"""End-to-end tip backtest on a deterministic demo-chain archive: tips issue look-ahead-guarded,
resolve held-to-expiry against the realized close, land in the tip ledger curve, and — with too few
trades to clear the validation battery — stay OFF the headline feed (the honest default)."""

from datetime import date

from anvil.backtest.tip_backtest import run_tip_backtest
from anvil.ingest.demo import build_demo_chain
from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.store import TipValidationStore


class _DemoArchive:
    """Day 1 issues from a demo chain (expiry on day 2); day 2 is the expiry with a realized close."""

    def __init__(self, issue: date, expiry: date, settle: float):
        self.issue, self.expiry, self.settle = issue, expiry, settle
        self._exp = expiry.isoformat()
        self._ts = f"{issue.isoformat()}T15:30:00+05:30"

    def trading_days(self, start=None, end=None):
        return [self.issue, self.expiry]

    def chains_on(self, d):
        if d == self.issue:
            return [build_demo_chain("NIFTY", spot=24000.0, expiry=self._exp, timestamp=self._ts)]
        return []

    def index_close_on(self, d, u):
        return self.settle if (d == self.expiry and u.upper() == "NIFTY") else None


def _run(tmp_path, settle=24010.0, min_samples=1):
    arch = _DemoArchive(date(2026, 6, 12), date(2026, 6, 26), settle)
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    store = TipValidationStore(path=str(tmp_path / "tv.duckdb"))
    res = run_tip_backtest(arch, ["NIFTY"], led, store, min_samples=min_samples)
    return res, led, store


def test_tips_issue_and_resolve_held_to_expiry(tmp_path):
    res, led, store = _run(tmp_path)
    try:
        assert res["recorded"] >= 1, "demo chain should yield tradeable tips"
        assert res["resolved"] == res["recorded"], "every issued tip resolves at expiry"
        # the tip-backtest curve carries exactly the resolved tips, on its OWN class
        tip_curve = led.metrics_for_tips()["tip_backtest"]
        assert tip_curve["resolved_count"] == res["resolved"]
        # and nothing leaked into the public probability curve
        assert led.metrics()["resolved_count"] == 0
    finally:
        led.close()
        store.close()


def test_thin_evidence_never_reaches_headline(tmp_path):
    # Even with min_samples=1, a 1–few-trade cell can't clear t-stat/DSR/PBO → no headline.
    res, led, store = _run(tmp_path)
    try:
        assert res["headline_cells"] == 0
        # the gate agrees: a freshly-built tip in any backtested cell stays on the watchlist
        for r in res["reports"]:
            assert r["headline_eligible"] is False
    finally:
        led.close()
        store.close()


def test_backtest_writes_validation_cells(tmp_path):
    res, led, store = _run(tmp_path)
    try:
        assert res["cells"] >= 1
        assert len(store.all()) == res["cells"]
    finally:
        led.close()
        store.close()
