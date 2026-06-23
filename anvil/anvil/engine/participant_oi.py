"""Participant-wise OI narrative (FII / DII / Pro / Client) — an India-specific edge.

Parses the NSE participant-OI dataset into net index-futures and index-options positioning and
a plain-language read of who is positioned which way. NSE EOD scraping is fragile/anti-bot, so
the network path degrades gracefully (available=False) and a ParticipantOI can be injected for
deterministic use/tests.
"""

from __future__ import annotations

from ..ingest.nse_eod import ParticipantOI


def _num(row: dict, *tokens: str) -> float:
    for key, val in row.items():
        kl = key.lower()
        if all(t in kl for t in tokens):
            try:
                return float(str(val).replace(",", "").strip() or 0.0)
            except ValueError:
                continue
    return 0.0


def _participant_name(row: dict) -> str:
    for key in row:
        if "client type" in key.lower() or key.lower() == "client type":
            return str(row[key]).strip().upper()
    return str(next(iter(row.values()), "")).strip().upper()


def participant_oi_read(
    data: ParticipantOI | None = None, vix: float | None = None, date: str | None = None
) -> dict:
    if data is None:
        try:
            from ..ingest.nse_eod import fetch_india_vix, fetch_participant_oi

            if not date:
                return {"available": False, "note": "Pass a DDMMYYYY date to fetch participant OI."}
            data = fetch_participant_oi(date)
            vix = vix if vix is not None else fetch_india_vix()
        except Exception as e:  # noqa: BLE001 - NSE scraping is fragile; degrade, don't crash
            return {"available": False, "note": f"NSE participant-OI unavailable: {type(e).__name__}"}

    out: dict[str, dict] = {}
    for row in data.rows:
        name = _participant_name(row)
        if name not in ("FII", "DII", "PRO", "CLIENT"):
            continue
        fut_net = _num(row, "future", "index", "long") - _num(row, "future", "index", "short")
        call_long = _num(row, "option", "index", "call", "long")
        put_long = _num(row, "option", "index", "put", "long")
        out[name] = {
            "future_index_net": round(fut_net, 1),
            "option_index_call_long": round(call_long, 1),
            "option_index_put_long": round(put_long, 1),
            "option_index_directional": round(call_long - put_long, 1),
        }

    fii = out.get("FII", {})
    narrative = None
    if fii:
        net = fii["future_index_net"]
        side = "net long" if net > 0 else "net short" if net < 0 else "flat on"
        narrative = f"FII are {side} index futures ({net:+,.0f} net contracts)."

    return {
        "available": bool(out),
        "date": data.date,
        "india_vix": vix,
        "participants": out,
        "narrative": narrative,
        "note": "Participant-wise OI is EOD and best-effort scraped; treat as a daily positioning read.",
    }
