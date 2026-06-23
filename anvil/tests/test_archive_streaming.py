"""Wave 5 — BhavcopyArchive.iter_days streaming loader: equivalence to from_cache_dir + bounded memory."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from anvil.backtest import BhavcopyArchive

FIX = (Path(__file__).parent / "fixtures" / "bhavcopy_fo_sample.csv").read_text()


def _make_dir(tmp_path):
    (tmp_path / "fo_2026-06-12.csv").write_text(FIX, encoding="utf-8")
    (tmp_path / "fo_2026-06-13.csv").write_text(FIX, encoding="utf-8")
    (tmp_path / "index_close.json").write_text(
        json.dumps({"2026-06-12": {"NIFTY": 24010.0}, "2026-06-13": {"NIFTY": 24100.0}}),
        encoding="utf-8")
    return str(tmp_path)


def test_iter_days_matches_from_cache_dir(tmp_path):
    cdir = _make_dir(tmp_path)
    full = BhavcopyArchive.from_cache_dir(cdir)
    streamed = {d.isoformat(): arch for d, arch in BhavcopyArchive.iter_days(cdir)}
    assert set(streamed) == {"2026-06-12", "2026-06-13"}
    for d in full.trading_days():
        fc = full.chains_on(d)
        sc = streamed[d.isoformat()].chains_on(d)
        assert len(fc) == len(sc) and [c.expiry for c in fc] == [c.expiry for c in sc]
        # forward close still resolvable from the shared (whole) index_close.json
        assert streamed[d.isoformat()].index_close_on(d, "NIFTY") == full.index_close_on(d, "NIFTY")


def test_iter_days_bounded_memory(tmp_path):
    cdir = _make_dir(tmp_path)
    for _d, arch in BhavcopyArchive.iter_days(cdir):
        assert len(arch.rows_by_date) == 1          # only ONE day held at a time


def test_iter_days_window_keeps_trailing(tmp_path):
    cdir = _make_dir(tmp_path)
    last = None
    for _d, arch in BhavcopyArchive.iter_days(cdir, window=2):
        last = arch
    assert 1 <= len(last.rows_by_date) <= 2          # rolling window, not the whole dir


def test_iter_days_date_filter(tmp_path):
    cdir = _make_dir(tmp_path)
    days = [d for d, _a in BhavcopyArchive.iter_days(cdir, start=date(2026, 6, 13))]
    assert days == [date(2026, 6, 13)]


def _cert_dir(tmp_path):
    """A real chain day + its expiry day (with a realized close) so tips can issue AND resolve."""
    (tmp_path / "fo_2026-06-12.csv").write_text(FIX, encoding="utf-8")
    (tmp_path / "fo_2026-06-26.csv").write_text("", encoding="utf-8")  # expiry day, empty F&O
    (tmp_path / "index_close.json").write_text(
        json.dumps({"2026-06-12": {"NIFTY": 24010.0}, "2026-06-26": {"NIFTY": 24300.0}}),
        encoding="utf-8")
    return str(tmp_path)


def test_streaming_backtest_equivalence(tmp_path):
    """run_tip_backtest_streaming must produce BYTE-IDENTICAL cells/verdicts to the in-memory path."""
    from anvil.backtest.tip_backtest import run_tip_backtest, run_tip_backtest_streaming
    from anvil.ledger.ledger import CalibrationLedger
    from anvil.tips.store import TipValidationStore

    cdir = _cert_dir(tmp_path)

    led1 = CalibrationLedger(str(tmp_path / "l1.duckdb"))
    st1 = TipValidationStore(str(tmp_path / "s1.duckdb"))
    try:
        r1 = run_tip_backtest(BhavcopyArchive.from_cache_dir(cdir), ["NIFTY"], led1, st1)
    finally:
        led1.close()
        st1.close()

    led2 = CalibrationLedger(str(tmp_path / "l2.duckdb"))
    st2 = TipValidationStore(str(tmp_path / "s2.duckdb"))
    try:
        r2 = run_tip_backtest_streaming(cdir, ["NIFTY"], led2, st2)
    finally:
        led2.close()
        st2.close()

    import math

    def _eq(a, b):
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return True
        return a == b

    assert r1["recorded"] == r2["recorded"]
    assert r1["resolved"] == r2["resolved"]
    assert r1["cells"] == r2["cells"]
    assert _eq(r1["global_pbo"], r2["global_pbo"])

    def _key(rep):
        return (rep["structure"], rep["regime_bucket"], rep["underlying"])

    m1 = {_key(r): r for r in r1["reports"]}
    m2 = {_key(r): r for r in r2["reports"]}
    assert set(m1) == set(m2)
    for k in m1:
        assert m1[k]["n"] == m2[k]["n"]
        assert _eq(m1[k]["win_rate"], m2[k]["win_rate"])
        assert _eq(m1[k]["t_stat"], m2[k]["t_stat"])
        assert m1[k]["headline_eligible"] == m2[k]["headline_eligible"]


def test_parallel_backtest_equivalence_workers1(tmp_path):
    """run_tip_backtest_parallel (compute-then-reduce) must equal the serial streaming path."""
    import math

    from anvil.backtest.tip_backtest import run_tip_backtest_parallel, run_tip_backtest_streaming
    from anvil.ledger.ledger import CalibrationLedger
    from anvil.tips.store import TipValidationStore

    cdir = _cert_dir(tmp_path)

    def _run(fn, tag, **kw):
        led = CalibrationLedger(str(tmp_path / f"l_{tag}.duckdb"))
        st = TipValidationStore(str(tmp_path / f"s_{tag}.duckdb"))
        try:
            return fn(cdir, ["NIFTY"], led, st, **kw)
        finally:
            led.close()
            st.close()

    rs = _run(run_tip_backtest_streaming, "s")
    rp = _run(run_tip_backtest_parallel, "p", workers=1)

    def _eq(a, b):
        return (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b)) or a == b

    assert rs["recorded"] == rp["recorded"] and rs["resolved"] == rp["resolved"]
    assert rs["cells"] == rp["cells"]
    k = lambda r: (r["structure"], r["regime_bucket"], r["underlying"])  # noqa: E731
    ms = {k(r): r for r in rs["reports"]}
    mp = {k(r): r for r in rp["reports"]}
    assert set(ms) == set(mp)
    for key in ms:
        assert ms[key]["n"] == mp[key]["n"]
        assert _eq(ms[key]["win_rate"], mp[key]["win_rate"])
        assert _eq(ms[key]["t_stat"], mp[key]["t_stat"])
        assert ms[key]["headline_eligible"] == mp[key]["headline_eligible"]
