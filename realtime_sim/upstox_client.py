"""
Read-only Upstox market-data client (pure stdlib).

  * resolve_equity_key(symbol)   - NSE equity instrument key from the public master (cached)
  * ltp(instrument_key)          - last traded price
  * option_chain(underlying)     - nearest-expiry index chain with Greeks/OI
  * option_chain_by_key(key)     - nearest-expiry chain for ANY underlying (index OR stock F&O)
  * daily_candles(key, days)     - historical daily OHLC (oldest->newest)
  * intraday_candles(key, ivl)   - today's intraday OHLC (oldest->newest)

Upstox sits behind Cloudflare (403s the default urllib agent), so every request sends a browser
User-Agent. Token from ../anvil/.env or env. NOTHING here places an order.
"""
from __future__ import annotations

import gzip
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

from config import INDEX_INSTRUMENT_KEYS

_BASE = "https://api.upstox.com/v2"
_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")
_HERE = os.path.dirname(os.path.abspath(__file__))
_MASTER_CACHE = os.path.join(_HERE, ".nse_equity_master.json")


def _lot_size_from_contract(rows, expiry=None):
    cands = [r for r in rows if (expiry is None or r.get("expiry") == expiry)] or rows
    for r in cands:
        for k in ("lot_size", "lotSize", "minimum_lot", "freeze_quantity"):
            v = r.get(k)
            if v:
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    pass
    return None


def load_token():
    if os.environ.get("UPSTOX_ACCESS_TOKEN"):
        return os.environ["UPSTOX_ACCESS_TOKEN"].strip()
    env_path = os.path.join(_HERE, "..", "anvil", ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("UPSTOX_ACCESS_TOKEN=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    raise SystemExit("No UPSTOX_ACCESS_TOKEN (checked env + ../anvil/.env).")


class UpstoxClient:
    def __init__(self, token=None, timeout=20.0):
        self.token = token or load_token()
        self.timeout = timeout
        self._eq_keys = None

    def _get(self, url, auth=True, gz=False):
        headers = {"User-Agent": _UA, "Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read()
                    return gzip.decompress(raw) if gz else raw
            except Exception as e:
                last = e
                time.sleep(1.0 + attempt)
        raise RuntimeError(f"GET failed after retries: {url} :: {last}")

    def _get_json(self, path, params, auth=True):
        url = f"{_BASE}{path}?{urllib.parse.urlencode(params)}"
        return json.loads(self._get(url, auth=auth).decode())

    def _equity_keys(self):
        if self._eq_keys is not None:
            return self._eq_keys
        if os.path.exists(_MASTER_CACHE) and (time.time() - os.path.getmtime(_MASTER_CACHE)) < 86400:
            self._eq_keys = json.load(open(_MASTER_CACHE))
            return self._eq_keys
        data = json.loads(self._get(_MASTER_URL, auth=False, gz=True).decode())
        keys = {}
        for d in data:
            if d.get("segment") == "NSE_EQ" or d.get("instrument_type") == "EQ":
                ts = (d.get("trading_symbol") or d.get("tradingsymbol") or "").upper()
                ik = d.get("instrument_key")
                if ts and ik and ts not in keys:
                    keys[ts] = ik
        json.dump(keys, open(_MASTER_CACHE, "w"))
        self._eq_keys = keys
        return keys

    def resolve_equity_key(self, symbol):
        return self._equity_keys().get(symbol.upper())

    def ltp(self, instrument_key):
        j = self._get_json("/market-quote/ltp", {"instrument_key": instrument_key})
        for v in (j.get("data") or {}).values():
            if v.get("last_price") is not None:
                return float(v["last_price"])
        return None

    def option_chain(self, underlying):
        ik = INDEX_INSTRUMENT_KEYS[underlying.upper()]
        contract = self._get_json("/option/contract", {"instrument_key": ik})
        rows = contract.get("data", [])
        expiries = sorted({r["expiry"] for r in rows if "expiry" in r})
        if not expiries:
            raise RuntimeError(f"No expiries for {underlying}")
        expiry = expiries[0]
        lot = _lot_size_from_contract(rows, expiry)
        chain = self._get_json("/option/chain", {"instrument_key": ik, "expiry_date": expiry}).get("data", [])
        return {"expiry": expiry, "rows": chain, "lot_size": lot, "instrument_key": ik}

    def option_chain_by_key(self, instrument_key, max_days=45):
        from datetime import date as _date
        contract = self._get_json("/option/contract", {"instrument_key": instrument_key})
        rows = contract.get("data", [])
        today = _date.today().isoformat()
        exps = sorted({r["expiry"] for r in rows if r.get("expiry") and r["expiry"] >= today})
        if not exps:
            raise RuntimeError(f"No (future) expiries for {instrument_key}")
        within = [e for e in exps if (_date.fromisoformat(e) - _date.today()).days <= max_days]
        expiry = (within or exps)[0]
        lot = _lot_size_from_contract(rows, expiry)
        chain = self._get_json("/option/chain", {"instrument_key": instrument_key, "expiry_date": expiry}).get("data", [])
        return {"expiry": expiry, "rows": chain, "lot_size": lot, "instrument_key": instrument_key}

    @staticmethod
    def _norm(candles):
        out = [{"ts": c[0], "o": float(c[1]), "h": float(c[2]), "l": float(c[3]),
                "c": float(c[4]), "v": float(c[5] or 0)} for c in candles]
        out.sort(key=lambda x: x["ts"])
        return out

    def daily_candles(self, instrument_key, days=400):
        to = date.today().isoformat()
        frm = (date.today() - timedelta(days=int(days * 1.6) + 10)).isoformat()
        j = self._get_json(f"/historical-candle/{urllib.parse.quote(instrument_key)}/day/{to}/{frm}", {})
        return self._norm(j.get("data", {}).get("candles", []))[-days:]

    def intraday_candles(self, instrument_key, interval="30minute"):
        j = self._get_json(f"/historical-candle/intraday/{urllib.parse.quote(instrument_key)}/{interval}", {})
        return self._norm(j.get("data", {}).get("candles", []))
