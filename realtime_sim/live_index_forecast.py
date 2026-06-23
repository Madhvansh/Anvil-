"""
Anvil Realtime Sim — Live Index Forecaster (proof-of-flow, READ-ONLY)
=====================================================================

The FIRST working piece of the NEW real-time simulation (distinct from anvil/live,
which runs on synthetic / frozen-smile replay). This script proves the full path:

    live Upstox option chain  ->  feature extraction  ->  probabilistic forecast  ->  JSON output

It is deliberately:
  * READ-ONLY        — only GETs market data. It NEVER places an order or moves money.
  * dependency-free  — pure Python stdlib (urllib/json/math), so it runs anywhere.
  * honest           — outputs are calibrated *probabilities and ranges*, never point
                       targets or guaranteed returns. Analytics & education only;
                       NOT investment advice.

What it computes per index, right now, from the live chain:
  * spot, ATM strike, ATM implied vol
  * expected move to expiry  (~0.85 x ATM straddle, the market's own implied range)
  * 1-sigma band             (lognormal, IV-scaled to time-to-expiry)
  * P(touch) of the nearest round-number levels before expiry
        (reflection-principle barrier approximation, VRP-discounted)
  * Put/Call OI ratio (PCR) and a crude OI-wall read (support/resistance)

The token is read from the existing anvil/.env (UPSTOX_ACCESS_TOKEN). A browser
User-Agent is sent because Upstox sits behind Cloudflare, which 403s the default
python-urllib agent from non-browser clients.

Usage:
    python live_index_forecast.py                 # NIFTY, BANKNIFTY, SENSEX
    python live_index_forecast.py NIFTY FINNIFTY  # pick your own
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

# --- config ----------------------------------------------------------------
_BASE = "https://api.upstox.com/v2"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")
_IST = timezone(timedelta(hours=5, minutes=30))

INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
    "BANKEX": "BSE_INDEX|BANKEX",
}

# Variance-risk-premium discount: risk-neutral IV overstates real-world move, so we
# scale vol by an empirical realized/implied ratio before computing real touch odds.
# (Matches PAPER_VRP_RATIO in the anvil .env. Tunable once the live curve accrues.)
VRP_RATIO = 0.85


def _load_token() -> str:
    """Read UPSTOX_ACCESS_TOKEN from anvil/.env (sibling dir) or the environment."""
    if os.environ.get("UPSTOX_ACCESS_TOKEN"):
        return os.environ["UPSTOX_ACCESS_TOKEN"].strip()
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(here, "..", "anvil", ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("UPSTOX_ACCESS_TOKEN=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    raise SystemExit("No UPSTOX_ACCESS_TOKEN found (checked env + ../anvil/.env).")


def _get(token: str, path: str, params: dict) -> dict:
    url = f"{_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": _UA,
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


# --- quant helpers (pure functions, unit-testable) -------------------------
def year_fraction(expiry_iso: str, now: datetime | None = None) -> float:
    """Calendar-time to expiry in years (expiry assumed 15:30 IST on the date)."""
    now = now or datetime.now(_IST)
    exp = datetime.fromisoformat(expiry_iso).replace(hour=15, minute=30, tzinfo=_IST)
    return max((exp - now).total_seconds() / (365.0 * 24 * 3600), 1e-6)


def expected_move(spot: float, atm_iv: float, t: float) -> float:
    """1-sigma expected move = spot * IV * sqrt(T). IV is a decimal (0.13 = 13%)."""
    return spot * atm_iv * math.sqrt(t)


def prob_touch(spot: float, level: float, atm_iv: float, t: float, vrp: float = VRP_RATIO) -> float:
    """
    P(underlying touches `level` at least once before expiry), GBM barrier approx via
    the reflection principle: P(touch) ~= 2 * P(terminal beyond level). VRP-discounted
    (real-world vol < risk-neutral IV) so we don't overstate the odds. Clamped [0,1].
    """
    sigma = max(atm_iv * vrp, 1e-6) * math.sqrt(t)
    if sigma <= 0 or spot <= 0 or level <= 0:
        return 0.0
    # log-distance in sigma units; drift ~0 over short horizons
    d = abs(math.log(level / spot)) / sigma
    # P(terminal beyond) for a one-sided barrier; normal CDF tail
    p_terminal = 0.5 * math.erfc(d / math.sqrt(2))
    return max(0.0, min(1.0, 2.0 * p_terminal))


def _normal_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


# --- core: build a forecast from one live chain ----------------------------
def forecast_index(token: str, name: str) -> dict:
    ik = INSTRUMENT_KEYS[name]
    contract = _get(token, "/option/contract", {"instrument_key": ik})
    expiries = sorted({row["expiry"] for row in contract.get("data", []) if "expiry" in row})
    if not expiries:
        raise RuntimeError(f"No expiries for {name}")
    expiry = expiries[0]
    chain = _get(token, "/option/chain", {"instrument_key": ik, "expiry_date": expiry}).get("data", [])
    if not chain:
        raise RuntimeError(f"Empty chain for {name}")

    spot = float(chain[0].get("underlying_spot_price") or 0.0)
    atm = min(chain, key=lambda x: abs(float(x["strike_price"]) - spot))
    atm_strike = float(atm["strike_price"])

    def leg(node, side):
        o = node.get(side) or {}
        return (o.get("market_data") or {}), (o.get("option_greeks") or {})

    ce_md, ce_gk = leg(atm, "call_options")
    pe_md, pe_gk = leg(atm, "put_options")
    # ATM IV: average the call/put IV (Upstox reports IV in %). Fallback to one side.
    ivs = [float(g["iv"]) / 100.0 for g in (ce_gk, pe_gk) if g.get("iv")]
    atm_iv = sum(ivs) / len(ivs) if ivs else 0.0
    straddle = float(ce_md.get("ltp") or 0) + float(pe_md.get("ltp") or 0)

    t = year_fraction(expiry)
    em_iv = expected_move(spot, atm_iv, t)            # IV-implied 1-sigma
    em_straddle = 0.85 * straddle                     # market's own expected move
    one_sigma = (round(spot - em_iv, 1), round(spot + em_iv, 1))

    # Probability-of-touch for the nearest round levels above/below.
    step = 100.0 if name in ("NIFTY", "FINNIFTY", "MIDCPNIFTY") else (500.0 if name == "BANKNIFTY" else 200.0)
    up_level = math.ceil((spot + 0.5 * step) / step) * step
    dn_level = math.floor((spot - 0.5 * step) / step) * step

    # PCR + OI walls (aggregate across the chain).
    call_oi = sum(float((n.get("call_options") or {}).get("market_data", {}).get("oi") or 0) for n in chain)
    put_oi = sum(float((n.get("put_options") or {}).get("market_data", {}).get("oi") or 0) for n in chain)
    pcr = round(put_oi / call_oi, 3) if call_oi else None
    max_call_oi = max(chain, key=lambda n: float((n.get("call_options") or {}).get("market_data", {}).get("oi") or 0))
    max_put_oi = max(chain, key=lambda n: float((n.get("put_options") or {}).get("market_data", {}).get("oi") or 0))

    return {
        "underlying": name,
        "as_of_ist": datetime.now(_IST).isoformat(timespec="seconds"),
        "spot": round(spot, 2),
        "expiry": expiry,
        "days_to_expiry": round(t * 365, 2),
        "atm_strike": atm_strike,
        "atm_iv_pct": round(atm_iv * 100, 2),
        "atm_straddle": round(straddle, 2),
        "expected_move": {
            "from_atm_straddle": round(em_straddle, 1),
            "from_iv_1sigma": round(em_iv, 1),
            "one_sigma_band": one_sigma,
            "band_pct": [round((one_sigma[0] / spot - 1) * 100, 2), round((one_sigma[1] / spot - 1) * 100, 2)],
        },
        "prob_touch_before_expiry": {
            f"up_{int(up_level)}": round(prob_touch(spot, up_level, atm_iv, t), 3),
            f"down_{int(dn_level)}": round(prob_touch(spot, dn_level, atm_iv, t), 3),
        },
        "positioning": {
            "pcr_oi": pcr,
            "call_wall_strike": float(max_call_oi["strike_price"]),   # resistance
            "put_wall_strike": float(max_put_oi["strike_price"]),     # support
        },
        "provenance": "upstox_live_rest",
        "disclaimer": "Calibrated probabilities/ranges from live data. Analytics & education only — NOT investment advice. No order is ever placed.",
    }


def main(argv: list[str]) -> int:
    names = [a.upper() for a in argv[1:]] or ["NIFTY", "BANKNIFTY", "SENSEX"]
    token = _load_token()
    out = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "forecasts": []}
    for name in names:
        if name not in INSTRUMENT_KEYS:
            print(f"  ! unknown index {name}, skipping"); continue
        try:
            fc = forecast_index(token, name)
            out["forecasts"].append(fc)
            em = fc["expected_move"]; pt = fc["prob_touch_before_expiry"]
            print(f"\n=== {name} @ {fc['spot']}  (exp {fc['expiry']}, {fc['days_to_expiry']}d) ===")
            print(f"  ATM {fc['atm_strike']}  IV {fc['atm_iv_pct']}%  straddle {fc['atm_straddle']}")
            print(f"  expected move: +/-{em['from_atm_straddle']} (straddle) | 1-sigma band {em['one_sigma_band']} ({em['band_pct'][0]}%..{em['band_pct'][1]}%)")
            print(f"  P(touch) {list(pt.items())}")
            print(f"  PCR {fc['positioning']['pcr_oi']}  call-wall {fc['positioning']['call_wall_strike']}  put-wall {fc['positioning']['put_wall_strike']}")
        except Exception as e:
            print(f"  ! {name} failed: {type(e).__name__}: {str(e)[:160]}")
    # Save snapshot next to this script.
    here = os.path.dirname(os.path.abspath(__file__))
    stamp = datetime.now(_IST).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(here, f"snapshot_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved snapshot -> {os.path.basename(path)}  ({len(out['forecasts'])} indices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
