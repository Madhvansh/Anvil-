"""Anvil Live v2 — analytics engine (pure stdlib).

Turns a live option chain + the underlying's recent candles into the decision surface the
monetization layer needs:

  * VRP        — implied ATM IV vs recent realized vol. The whole edge: when realized runs
                 BELOW implied, the option premium is "rich" and selling it has positive EV.
  * GEX        — net dealer gamma exposure across the chain → a pinning (mean-revert) vs
                 trend-amplify regime read, plus the zero-gamma flip level.
  * Regime     — composite of VRP + GEX + recent trend → which strategy family fits.
  * Terminal distribution — a risk-neutral (implied σ) AND a physical (realized ≈ vrp·implied σ)
                 lognormal for S_T, used to price every structure's prob-of-profit and EV.

Faithful pure-stdlib port of anvil/anvil/strategy/context.py + engine/{gex,regime,implied_dist}.
No scipy/numpy; the normal CDF is math.erf. Read-only — no orders.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import config
from features import candle_features, realized_vol, year_fraction

_TRADING_DAYS = 252.0


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def black76_price(option_type: str, forward: float, strike: float, t: float, sigma: float) -> float:
    """Black-76 option price on the forward (r≈0 for the short horizon). Pure stdlib.

    Used to MARK-TO-MARKET an open structure at an interior path point so MAE/MFE and the modeled
    stop reflect the TRUE option value (intrinsic + time value), not intrinsic alone. At expiry
    (t→0) this collapses to intrinsic, so settlement P&L is unaffected.
    """
    if t <= 0 or sigma <= 0 or forward <= 0 or strike <= 0:
        return max(forward - strike, 0.0) if option_type == "CE" else max(strike - forward, 0.0)
    s = sigma * math.sqrt(t)
    d1 = (math.log(forward / strike) + 0.5 * s * s) / s
    d2 = d1 - s
    if option_type == "CE":
        return forward * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1)


# --- option-chain row navigation (Upstox node shape) ------------------------
def _leg(node: dict, side: str) -> tuple[dict, dict]:
    o = node.get(side) or {}
    return (o.get("market_data") or {}), (o.get("option_greeks") or {})


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _mid(md: dict) -> float | None:
    bid, ask = _f(md.get("bid_price")), _f(md.get("ask_price"))
    if bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2.0
    ltp = _f(md.get("ltp"))
    return ltp if ltp > 0 else None


@dataclass
class StructureLeg:
    side: str           # BUY | SELL
    option_type: str    # CE | PE | FUT
    strike: float | None
    mid: float          # per-share mid
    bid: float | None
    ask: float | None
    oi: float
    delta: float | None
    gamma: float | None


@dataclass
class MarketState:
    underlying: str
    asset_class: str        # index | stock
    instrument_key: str
    expiry: str
    spot: float
    forward: float
    lot_size: int
    T: float                # year fraction to expiry
    days_to_expiry: float
    atm_strike: float
    atm_iv: float           # implied (annualized)
    realized_vol_annual: float
    vrp_ratio: float        # realized / implied  (<1 = implied rich = sell-favourable)
    vrp_signal: str         # SELL_VOL | BUY_VOL | NEUTRAL
    net_gex: float
    gex_regime: str         # positive_gamma_mean_revert | negative_gamma_trend_amplify | neutral_mixed
    zero_gamma: float | None
    regime: str             # final composite label
    pcr: float | None
    call_wall: float
    put_wall: float
    expected_move: float    # 1σ implied move in points (spot·iv·√T)
    trend_z: float          # recent 5d momentum in daily-vol units
    rows_by_strike: dict = field(default_factory=dict)   # strike -> node
    strikes: list = field(default_factory=list)
    candle_feats: dict = field(default_factory=dict)

    # --- chain navigation ---------------------------------------------------
    def nearest_strike(self, target: float) -> float | None:
        return min(self.strikes, key=lambda k: abs(k - target)) if self.strikes else None

    def leg(self, strike: float | None, option_type: str) -> StructureLeg | None:
        if strike is None or strike not in self.rows_by_strike:
            return None
        side_key = "call_options" if option_type == "CE" else "put_options"
        md, gk = _leg(self.rows_by_strike[strike], side_key)
        mid = _mid(md)
        if mid is None or mid <= 0:
            return None
        return StructureLeg(
            side="", option_type=option_type, strike=float(strike), mid=float(mid),
            bid=_f(md.get("bid_price")) or None, ask=_f(md.get("ask_price")) or None,
            oi=_f(md.get("oi")), delta=_f(gk.get("delta")) if gk.get("delta") is not None else None,
            gamma=_f(gk.get("gamma")) if gk.get("gamma") is not None else None)

    # --- probability helpers ------------------------------------------------
    def _prob_above(self, level: float, sigma_annual: float) -> float:
        """Lognormal P(S_T > level): N(d2), F=forward, σ=sigma_annual."""
        if level <= 0 or self.forward <= 0 or sigma_annual <= 0 or self.T <= 0:
            return float(self.forward > level)
        s = sigma_annual * math.sqrt(self.T)
        d2 = (math.log(self.forward / level) - 0.5 * s * s) / s
        return _norm_cdf(d2)

    def prob_above_rn(self, level: float) -> float:
        return self._prob_above(level, self.atm_iv)

    def _phys(self, level: float) -> float:
        """Map a rupee level into physical-σ space (realized runs vrp_ratio of implied)."""
        vr = self.vrp_ratio if 0 < self.vrp_ratio else 1.0
        # cap the discount so a wild realized estimate can't invent edge
        vr = max(0.6, min(1.15, vr))
        return self.spot + (level - self.spot) / vr

    def prob_above_phys(self, level: float) -> float:
        return self.prob_above_rn(self._phys(level))

    def prob_below_phys(self, level: float) -> float:
        return max(0.0, 1.0 - self.prob_above_phys(level))

    def prob_between_phys(self, lo: float, hi: float) -> float:
        return max(0.0, self.prob_above_phys(lo) - self.prob_above_phys(hi))

    # --- physical terminal distribution (for EV integration) ----------------
    def physical_grid(self, n: int = 161, width_sigmas: float = 4.0) -> list[tuple[float, float]]:
        """Discretized physical distribution of S_T as [(price, probability_mass), ...].

        Realized ≈ vrp_ratio·implied, so σ_phys = atm_iv·min(vrp_ratio,1) (capped). Lognormal,
        martingale around forward. Used to integrate any structure's payoff into an EV/POP.
        """
        vr = max(0.6, min(1.0, self.vrp_ratio if self.vrp_ratio > 0 else 0.85))
        sig = max(self.atm_iv * vr, 1e-4) * math.sqrt(max(self.T, 1e-6))
        if sig <= 0 or self.forward <= 0:
            return [(self.spot, 1.0)]
        mu = math.log(self.forward) - 0.5 * sig * sig
        lo, hi = mu - width_sigmas * sig, mu + width_sigmas * sig
        step = (hi - lo) / (n - 1)
        pts, total = [], 0.0
        for i in range(n):
            x = lo + i * step                      # x = ln(S_T)
            pdf = math.exp(-0.5 * ((x - mu) / sig) ** 2) / (sig * math.sqrt(2 * math.pi))
            mass = pdf * step
            pts.append((math.exp(x), mass))
            total += mass
        return [(p, m / total) for p, m in pts] if total > 0 else pts


# ----------------------------------------------------------------------------
def _net_gex(rows: list, spot: float, lot: int) -> tuple[float, str, float | None]:
    """Net dealer gamma exposure across the chain.

    Convention (SqueezeMetrics-style): dealers are net LONG calls / SHORT puts, so call gamma
    adds and put gamma subtracts. Dollar-gamma per 1% move = γ·OI·lot·S²·0.01. Positive net GEX
    ⇒ dealers long gamma ⇒ they fade moves ⇒ PINNING/mean-revert. Negative ⇒ trend-amplify.
    zero_gamma = strike where cumulative GEX flips sign (the regime pivot). Documented assumption.
    """
    per_strike = []
    net = 0.0
    for n in rows:
        k = _f(n.get("strike_price"))
        _, cg = _leg(n, "call_options")
        _, pg = _leg(n, "put_options")
        cmd, _ = _leg(n, "call_options")
        pmd, _ = _leg(n, "put_options")
        cgex = _f(cg.get("gamma")) * _f(cmd.get("oi")) * lot * spot * spot * 0.01
        pgex = _f(pg.get("gamma")) * _f(pmd.get("oi")) * lot * spot * spot * 0.01
        s = cgex - pgex
        per_strike.append((k, s))
        net += s
    zero_gamma = None
    per_strike.sort(key=lambda x: x[0])
    cum = 0.0
    prev_k = None
    for k, s in per_strike:
        new = cum + s
        if prev_k is not None and ((cum <= 0 < new) or (cum >= 0 > new)):
            zero_gamma = round((prev_k + k) / 2.0, 2)
        cum, prev_k = new, k
    if net > 0:
        regime = "positive_gamma_mean_revert"
    elif net < 0:
        regime = "negative_gamma_trend_amplify"
    else:
        regime = "neutral_mixed"
    return net, regime, zero_gamma


def build_state(underlying: str, asset_class: str, chain: dict, candles: list,
                instrument_key: str) -> MarketState | None:
    rows = chain.get("rows") or []
    if not rows:
        return None
    spot = _f(rows[0].get("underlying_spot_price"))
    if spot <= 0:
        return None
    lot = int(chain.get("lot_size") or config.V2_LOT_SIZE_FALLBACK.get(underlying, 50) or 50)
    strikes = sorted({_f(n.get("strike_price")) for n in rows if _f(n.get("strike_price")) > 0})
    rows_by_strike = {_f(n.get("strike_price")): n for n in rows}
    atm = min(strikes, key=lambda k: abs(k - spot)) if strikes else spot

    # implied ATM IV from the ATM call/put greeks
    atm_node = rows_by_strike.get(atm, {})
    _, ce_gk = _leg(atm_node, "call_options")
    _, pe_gk = _leg(atm_node, "put_options")
    ivs = [_f(g.get("iv")) / 100.0 for g in (ce_gk, pe_gk) if _f(g.get("iv")) > 0]
    atm_iv = sum(ivs) / len(ivs) if ivs else 0.0
    if atm_iv <= 0:
        return None

    T = year_fraction(chain["expiry"])
    dte = round(T * 365.0, 3)
    forward = spot  # short-horizon: carry is negligible vs IV; spot ≈ forward

    feats = candle_features(candles) if candles else {"ok": False}
    rv_daily = realized_vol([c["c"] for c in candles], 20) if candles else 0.0
    rv_annual = rv_daily * math.sqrt(_TRADING_DAYS)
    if rv_annual > 0 and atm_iv > 0:
        vrp_ratio = rv_annual / atm_iv
        if vrp_ratio <= config.V2_VRP_SELL_RATIO:
            vrp_signal = "SELL_VOL"
        elif vrp_ratio >= config.V2_VRP_BUY_RATIO:
            vrp_signal = "BUY_VOL"
        else:
            vrp_signal = "NEUTRAL"
    else:
        # No realized-vol history → do NOT fabricate a sell signal; stay neutral, no VRP discount.
        vrp_ratio = 1.0
        vrp_signal = "NEUTRAL"

    net_gex, gex_regime, zero_gamma = _net_gex(rows, spot, lot)

    # PCR + walls
    call_oi = sum(_f((n.get("call_options") or {}).get("market_data", {}).get("oi")) for n in rows)
    put_oi = sum(_f((n.get("put_options") or {}).get("market_data", {}).get("oi")) for n in rows)
    pcr = (put_oi / call_oi) if call_oi > 0 else None
    call_wall = max(rows, key=lambda n: _f((n.get("call_options") or {}).get("market_data", {}).get("oi")))
    put_wall = max(rows, key=lambda n: _f((n.get("put_options") or {}).get("market_data", {}).get("oi")))

    expected_move = spot * atm_iv * math.sqrt(max(T, 1e-6))

    # recent trend in daily-vol units
    trend_z = 0.0
    if feats.get("ok") and rv_daily > 1e-9:
        trend_z = feats["r5"] / (rv_daily * math.sqrt(5))

    regime = _composite_regime(vrp_signal, gex_regime, trend_z)

    return MarketState(
        underlying=underlying, asset_class=asset_class, instrument_key=instrument_key,
        expiry=chain["expiry"], spot=spot, forward=forward, lot_size=lot, T=T, days_to_expiry=dte,
        atm_strike=atm, atm_iv=atm_iv, realized_vol_annual=rv_annual, vrp_ratio=vrp_ratio,
        vrp_signal=vrp_signal, net_gex=net_gex, gex_regime=gex_regime, zero_gamma=zero_gamma,
        regime=regime, pcr=pcr, call_wall=_f(call_wall["strike_price"]),
        put_wall=_f(put_wall["strike_price"]), expected_move=expected_move, trend_z=trend_z,
        rows_by_strike=rows_by_strike, strikes=strikes, candle_feats=feats)


def _composite_regime(vrp_signal: str, gex_regime: str, trend_z: float) -> str:
    """Blend VRP + GEX + trend into the final regime that picks the strategy family.

    Premium-selling (short_vol) needs BOTH rich implied (VRP) AND a non-trending tape; a strong
    trend or cheap IV flips us to trend/long-vol. This stops us from selling into a runaway move.
    """
    strong_trend = abs(trend_z) >= 1.0
    if vrp_signal == "BUY_VOL":
        return "negative_gamma_trend_amplify"
    if strong_trend and gex_regime == "negative_gamma_trend_amplify":
        return "negative_gamma_trend_amplify"
    if vrp_signal == "SELL_VOL" and not strong_trend:
        return "positive_gamma_mean_revert"
    if gex_regime == "positive_gamma_mean_revert" and vrp_signal != "BUY_VOL":
        return "positive_gamma_mean_revert"
    return "neutral_mixed"
