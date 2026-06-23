"""Resolve a tip to a binary win/loss — the input the ledger scores.

Two routes, both pure:
  * ``resolve_outcome_from_path`` — walk a mark path; first touch of the target ⇒ win, first touch
    of the stop ⇒ loss, neither by horizon end ⇒ resolve on the final mark vs entry. This is the
    target-before-stop-within-horizon rule.
  * ``resolve_outcome_from_pnl`` — when the pipeline already has realized P&L (e.g. paper-style
    mark-to-market), a win is simply P&L > 0 (matches the ledger's KIND_TRADE_WIN convention).
"""

from __future__ import annotations


def resolve_outcome_from_pnl(pnl: float) -> int:
    """1 if the trade made money, else 0 (the ledger's KIND_TRADE_WIN convention)."""
    try:
        return int(float(pnl) > 0.0)
    except (TypeError, ValueError):
        return 0


def resolve_outcome_from_path(
    entry: float,
    target: float | None,
    stop: float | None,
    marks,
    higher_is_win: bool = True,
) -> tuple[int, str]:
    """Walk ``marks`` (values in the same unit as entry/target/stop) in order.

    First touch of ``target`` in the favorable direction ⇒ (1, "target"); first touch of ``stop`` in
    the adverse direction ⇒ (0, "stop"). If a mark would trigger both on the same bar, the STOP wins
    (conservative). If neither triggers by the end, resolve on the final mark vs entry:
    (1, "timeout_win") / (0, "timeout_loss"). Empty path ⇒ (0, "no_path")."""
    seq = [float(m) for m in (marks or []) if m is not None]
    if not seq:
        return 0, "no_path"

    def hit_target(m: float) -> bool:
        if target is None:
            return False
        return m >= target if higher_is_win else m <= target

    def hit_stop(m: float) -> bool:
        if stop is None:
            return False
        return m <= stop if higher_is_win else m >= stop

    for m in seq:
        stopped = hit_stop(m)
        won = hit_target(m)
        if stopped:  # conservative: a bar that breaches both is a loss
            return 0, "stop"
        if won:
            return 1, "target"

    final = seq[-1]
    favorable = (final - entry) > 0 if higher_is_win else (final - entry) < 0
    return (1, "timeout_win") if favorable else (0, "timeout_loss")


def terminal_payoff(legs: list[dict], lot_size: int, settle: float) -> float:
    """Held-to-expiry gross P&L (₹) of a structure at the settlement level ``settle``.

    Exact for European index options held to expiry: each leg's P&L is
    ``sign * (terminal_value - entry_premium) * lots * lot_size`` where terminal_value is the
    option intrinsic at settle (CE: max(S-K,0); PE: max(K-S,0)) or, for a linear FUT/EQ leg, the
    settle level itself. ``sign`` is +1 for BUY, -1 for SELL. Gross — net of costs is computed by
    the caller (subtract the tip's round-trip cost)."""
    pnl = 0.0
    lot = int(lot_size or 1)
    s = float(settle)
    for leg in legs:
        lots = abs(int(leg.get("lots", 0) or 0))
        if lots <= 0:
            continue
        ref = float(leg.get("ref_price", 0.0) or 0.0)
        sign = 1 if str(leg.get("side", "")).upper() == "BUY" else -1
        itype = str(leg.get("instrument_type", "") or "").upper()
        strike = leg.get("strike")
        if itype in ("FUT", "EQ"):
            terminal = s
        elif itype == "CE":
            terminal = max(s - float(strike), 0.0)
        elif itype == "PE":
            terminal = max(float(strike) - s, 0.0)
        else:
            continue
        pnl += sign * (terminal - ref) * lots * lot
    return pnl


def settle_with_modeled_stop(
    legs: list[dict],
    lot_size: int,
    settle: float,
    *,
    max_loss: float,
    defined_risk: bool,
    path: list[tuple[float, float]] | None = None,
) -> dict:
    """Held-to-expiry settlement with an HONEST modeled stop (ported from the v2 tracker, adversary #2).

    ``settle`` settlement is exact intrinsic (``terminal_payoff``). When a daily ``path`` of
    ``(low, high)`` underlying bars (strictly after entry, up to expiry) is supplied, each bar's adverse
    extreme is marked at intrinsic as a conservative, IV-free MTM proxy to get MAE/MFE and to detect a
    stop breach (position loss ≤ ``-max_loss``). Booking: a defined-risk structure books the stop (the
    wings bound the loss); a NAKED structure books the WORSE of (stop, true settlement) — a >3σ gap
    fills worse than the stop, so we never truncate the tail. With ``path=None`` this degrades to the
    exact ``terminal_payoff`` (``pnl_final == pnl_settle``) so existing resolution is byte-identical.

    Returns ``{pnl_settle, pnl_final, ret_on_risk, mae, mfe, stop_hit}`` (gross of cost; the caller nets)."""
    pnl_settle = terminal_payoff(legs, lot_size, settle)
    ml = abs(float(max_loss or 0.0))
    mae = mfe = 0.0
    stop_hit = False
    if path and ml > 0:
        for low, high in path:
            for px in (low, high):
                try:
                    pl = terminal_payoff(legs, lot_size, float(px))
                except (TypeError, ValueError):
                    continue
                mae = min(mae, pl)
                mfe = max(mfe, pl)
                if pl <= -ml:
                    stop_hit = True
    if stop_hit:
        stop_pnl = -ml
        pnl_final = stop_pnl if defined_risk else min(stop_pnl, pnl_settle)  # naked: worse of the two
    else:
        pnl_final = pnl_settle
    ret_on_risk = (pnl_final / ml) if ml > 0 else 0.0
    return {
        "pnl_settle": round(pnl_settle, 2),
        "pnl_final": round(pnl_final, 2),
        "ret_on_risk": round(ret_on_risk, 4),
        "mae": round(mae, 2),
        "mfe": round(mfe, 2),
        "stop_hit": stop_hit,
    }
