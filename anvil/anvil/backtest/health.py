"""Data-health + reconciliation report — trust the inputs before you size on them.

Coverage and gaps across every Phase-1 feed (bhavcopy, index closes, positioning, events/earnings),
plus a reconciliation of two independent NIFTY-close sources (Yahoo ``^NSEI`` vs the bhavcopy
``index_close.json`` cash close). Discipline:

  * **Gaps are reported, never hidden** — a missing trading day (not a holiday) is information.
  * **A reconciliation mismatch beyond tolerance is an integrity FAILURE** (``ok=False``) — two sources
    disagreeing on a settle the gate will trust is exactly the kind of silent error that fabricates edge.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from ..ingest import events, yahoo
from ..ingest import positioning as pos
from ..live.trading_calendar import trading_days

_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
WARN_TOL = 0.005   # 0.5% — flag for review
FAIL_TOL = 0.015   # 1.5% — clear data error (beyond futures-basis noise) → integrity failure
_CLOSE_SYMBOLS = ("^NSEI", "^NSEBANK", "^INDIAVIX", "^BSESN")


def _bhavcopy_dates(cache_dir: Path) -> list[str]:
    out = []
    for p in cache_dir.glob("fo_*.csv"):
        m = _DATE.search(p.name)
        if m:
            out.append(m.group(1))
    return sorted(out)


def _trading_gaps(dates: list[str]) -> list[str]:
    """Trading days between the first and last cached date that are missing (holidays excluded)."""
    if len(dates) < 2:
        return []
    have = set(dates)
    lo, hi = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    return [d.isoformat() for d in trading_days(lo, hi) if d.isoformat() not in have]


def data_health_report(*, cache_dir: str = "data/bhavcopy_cache") -> dict:
    cache_dir = Path(cache_dir)
    bdates = _bhavcopy_dates(cache_dir)
    bhav_gaps = _trading_gaps(bdates)

    icj = cache_dir / "index_close.json"
    index_close = {}
    if icj.exists():
        try:
            index_close = json.loads(icj.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            index_close = {}

    closes = {}
    for sym in _CLOSE_SYMBOLS:
        bars = yahoo.read_cache(sym)
        closes[sym] = {
            "bars": len(bars),
            "span": (f"{bars[0]['date']}…{bars[-1]['date']}" if bars else "—"),
        }

    # Reconcile: Yahoo ^NSEI cash close vs the bhavcopy index_close.json NIFTY close, per shared day.
    yclose = {b["date"]: b["c"] for b in yahoo.read_cache("^NSEI")}
    warnings: list[dict] = []
    failures: list[dict] = []
    for d, m in index_close.items():
        nf, yc = m.get("NIFTY"), yclose.get(d)
        if not (nf and yc):
            continue
        diff = abs(nf - yc) / yc
        if diff > WARN_TOL:
            rec = {"date": d, "bhavcopy": round(nf, 2), "yahoo": round(yc, 2),
                   "diff_pct": round(100 * diff, 3)}
            (failures if diff > FAIL_TOL else warnings).append(rec)

    report = {
        "bhavcopy": {"days": len(bdates), "span": (f"{bdates[0]}…{bdates[-1]}" if bdates else "—"),
                     "missing_trading_days": bhav_gaps},
        "index_close_json": {"days": len(index_close)},
        "closes": closes,
        "positioning_days": len(pos.available_dates()),
        "events": {"macro": len(events.calendar()), "earnings": len(events.earnings_calendar())},
        "reconciliation": {"checked": sum(1 for d in index_close if d in yclose),
                           "warnings": sorted(warnings, key=lambda r: r["date"]),
                           "failures": sorted(failures, key=lambda r: r["date"])},
        "ok": not failures,
    }
    return report


def render_health(report: dict) -> str:
    """Human-readable panel for the CLI."""
    b = report["bhavcopy"]
    lines = ["Anvil data health", "=================",
             f"bhavcopy        : {b['days']} days  {b['span']}"]
    if b["missing_trading_days"]:
        miss = b["missing_trading_days"]
        lines.append(f"  ! missing trading days ({len(miss)}): " + ", ".join(miss[:15])
                     + (" …" if len(miss) > 15 else ""))
    lines.append(f"index_close.json: {report['index_close_json']['days']} days")
    for sym, c in report["closes"].items():
        lines.append(f"closes {sym:<10}: {c['bars']} bars  {c['span']}")
    lines.append(f"positioning     : {report['positioning_days']} days cached")
    lines.append(f"events          : {report['events']['macro']} macro · {report['events']['earnings']} earnings")
    rec = report["reconciliation"]
    lines.append(f"reconciliation  : {rec['checked']} days checked · "
                 f"{len(rec['warnings'])} warn · {len(rec['failures'])} FAIL")
    for r in rec["failures"][:10]:
        lines.append(f"  FAIL {r['date']}: bhav {r['bhavcopy']} vs yahoo {r['yahoo']} ({r['diff_pct']}%)")
    for r in rec["warnings"][:5]:
        lines.append(f"  warn {r['date']}: bhav {r['bhavcopy']} vs yahoo {r['yahoo']} ({r['diff_pct']}%)")
    lines.append("")
    lines.append("STATUS: OK ✓" if report["ok"] else "STATUS: INTEGRITY FAILURE ✗")
    return "\n".join(lines)
