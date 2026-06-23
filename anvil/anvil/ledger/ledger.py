"""Forecast recording + resolution, DuckDB-backed.

A *forecast* is a timestamped probabilistic claim with a resolvable binary event (e.g.
"P(NIFTY closes within [a,b] by expiry) = 0.68"). When the outcome is known we *resolve*
it (event ∈ {0,1}) and the scoring module turns the accumulated history into a reliability
curve. Forecasts are immutable and idempotent (deterministic id) so the track record cannot
be quietly rewritten.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import duckdb

from ..config import SETTINGS
from . import scoring

# Forecast kinds whose event is computable from a single realized underlying level.
KIND_PROB_IN_BAND = "prob_in_band"
KIND_PROB_ABOVE = "prob_above"
KIND_PROB_BELOW = "prob_below"
# Paper-trading conviction calibration: "did the structure we gave probability p actually win?".
# Resolved from realized P&L (event = P&L > 0), not an underlying level. Lives under the EXCLUDED
# "paper" source class so it gets its own owner-only curve and NEVER blends into the public moat.
KIND_TRADE_WIN = "trade_win"
# Structural decision-brief forecasts (Wave 2): probability of TOUCH (did spot tag K within the
# horizon — resolved from the realized daily HIGH/LOW, not the close) and VRP richness (did realized
# vol come in BELOW implied — i.e. premium was rich). Both live on their own struct_* classes so they
# never blend into the market-implied or tip curves.
KIND_PROB_TOUCH = "prob_touch"
KIND_VRP_RICH = "vrp_rich"

# --- Source classes: the rail that keeps synthetic data out of any real track record. ---
# A forecast's free-form ``source`` (e.g. the connector name) maps to a *class*. Only the
# PUBLIC_CLASSES may ever appear in a user/investor-facing reliability curve. Everything that
# isn't explicitly synthetic ("seed") or a synthetic-but-live demo ("demo") is treated as a
# real "live" forecast; historical out-of-sample forecasts are "backtest".
# "today" = intraday-horizon predictions from the real-day replay: real claims on real outcomes, but
# a DIFFERENT horizon than the expiry forecasts, so they get their own owner-only bucket and never
# blend into the public backtest/live curve.
#
# Tip track record lives on its OWN classes (tip_backtest / tip_live) so the win/loss reliability of
# *issued tips* never blends into the market-implied probability curve (PUBLIC_CLASSES) or the
# owner-only paper/today curves. tip_backtest is out-of-sample historical; tip_live is forward/live.
SOURCE_CLASS: dict[str, str] = {
    "seed": "seed", "backtest": "backtest", "demo": "demo", "paper": "paper", "today": "today",
    "tip_backtest": "tip_backtest", "tip_live": "tip_live",
    "struct_backtest": "struct_backtest", "struct_live": "struct_live",
}
PUBLIC_CLASSES: tuple[str, ...] = ("backtest", "live")
# Issued-tip reliability (win/loss at stated conviction, after costs) — a separate public curve.
TIP_PUBLIC_CLASSES: tuple[str, ...] = ("tip_backtest", "tip_live")
# Structural decision-brief reliability (touch / VRP) — its OWN curve, firewalled from the rest.
STRUCTURAL_CLASSES: tuple[str, ...] = ("struct_backtest", "struct_live")
MIN_SAMPLES_FOR_SCORE = 50


def source_class(source: str | None) -> str:
    """Map a forecast ``source`` to its class. Unknown/real connectors → "live"."""
    return SOURCE_CLASS.get((source or "").lower(), "live")


def calibration_score(ece: float | None, n: int) -> dict:
    """An honest, intuitive headline derived from the reliability curve — NOT an accuracy or
    return claim. Score = round(100·(1−ECE)); 100 = perfectly calibrated. Below a minimum
    sample size it degrades honestly to "insufficient data" rather than inventing a number.
    """
    n = int(n or 0)
    if n < MIN_SAMPLES_FOR_SCORE or ece is None or ece != ece:  # ece != ece → NaN
        return {
            "score": None,
            "rating": "insufficient data",
            "n": n,
            "reading": f"Need {MIN_SAMPLES_FOR_SCORE}+ resolved forecasts to score calibration "
            f"(have {n}).",
        }
    score = max(0, min(100, round(100 * (1 - ece))))
    rating = (
        "well calibrated" if score >= 90
        else "calibrated" if score >= 80
        else "rough" if score >= 70
        else "miscalibrated"
    )
    return {
        "score": score,
        "rating": rating,
        "n": n,
        "reading": "When we say a probability, it comes true about that often "
        "(e.g. our 70% calls land ~70% of the time).",
    }


@dataclass
class Forecast:
    underlying: str
    created_ts: str  # ISO datetime the forecast was made
    resolve_ts: str  # ISO date/datetime when the outcome is known (e.g. expiry)
    kind: str
    params: dict  # e.g. {"lower":..,"upper":..,"nominal":"1sigma"} or {"level":..}
    prob: float  # predicted probability the event == 1
    spot: float
    forward: float
    model_version: str = "black76-1.0.0"
    source: str = "anvil"

    @property
    def id(self) -> str:
        key = "|".join(
            [
                self.underlying,
                self.created_ts,
                self.kind,
                json.dumps(self.params, sort_keys=True),
                self.model_version,
                self.source,
            ]
        )
        return hashlib.sha1(key.encode()).hexdigest()[:16]


def event_for(kind: str, params: dict, realized_value: float) -> int:
    """Resolve a forecast's binary event from the realized underlying level."""
    if kind == KIND_PROB_IN_BAND:
        return int(params["lower"] <= realized_value <= params["upper"])
    if kind == KIND_PROB_ABOVE:
        return int(realized_value >= params["level"])
    if kind == KIND_PROB_BELOW:
        return int(realized_value <= params["level"])
    if kind == KIND_TRADE_WIN:
        # Resolved from realized P&L passed as ``realized_value``: a win is P&L > 0.
        return int(realized_value > 0)
    if kind == KIND_PROB_TOUCH:
        # ``realized_value`` = the realized EXTREME over the horizon (the daily HIGH for an upside
        # barrier, the daily LOW for a downside barrier). The caller picks which extreme by ``dir``.
        if params.get("dir") == "down":
            return int(realized_value <= params["strike"])
        return int(realized_value >= params["strike"])
    if kind == KIND_VRP_RICH:
        # ``realized_value`` = the realized vol over the horizon; the "rich" event happened iff
        # realized came in at/below implied (premium was rich).
        return int(realized_value <= params["implied_vol"])
    raise ValueError(f"Unknown forecast kind: {kind!r}")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id VARCHAR PRIMARY KEY,
    underlying VARCHAR,
    created_ts VARCHAR,
    resolve_ts VARCHAR,
    kind VARCHAR,
    params JSON,
    prob DOUBLE,
    spot DOUBLE,
    forward DOUBLE,
    model_version VARCHAR,
    source VARCHAR
);
CREATE TABLE IF NOT EXISTS outcomes (
    forecast_id VARCHAR PRIMARY KEY,
    resolved_ts VARCHAR,
    realized_value DOUBLE,
    event INTEGER
);
"""


class CalibrationLedger:
    def __init__(self, path: str | None = None):
        self.path = path or SETTINGS.ledger_path
        self.con = duckdb.connect(self.path)
        self.con.execute(_SCHEMA)

    # ---- recording ----
    def record(self, f: Forecast) -> str:
        """Insert a forecast; idempotent (re-recording the same forecast is a no-op)."""
        self.con.execute(
            """INSERT INTO forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (id) DO NOTHING""",
            [
                f.id, f.underlying, f.created_ts, f.resolve_ts, f.kind,
                json.dumps(f.params), f.prob, f.spot, f.forward, f.model_version, f.source,
            ],
        )
        return f.id

    def record_many(self, forecasts: list[Forecast]) -> int:
        for f in forecasts:
            self.record(f)
        return len(forecasts)

    # ---- resolution ----
    def resolve(self, forecast_id: str, realized_value: float, resolved_ts: str | None = None) -> int:
        row = self.con.execute(
            "SELECT kind, params FROM forecasts WHERE id = ?", [forecast_id]
        ).fetchone()
        if row is None:
            raise KeyError(f"No forecast {forecast_id}")
        kind, params = row[0], json.loads(row[1])
        event = event_for(kind, params, realized_value)
        ts = resolved_ts or datetime.now(timezone.utc).isoformat()
        self.con.execute(
            "INSERT INTO outcomes VALUES (?,?,?,?) ON CONFLICT (forecast_id) DO NOTHING",
            [forecast_id, ts, realized_value, event],
        )
        return event

    def pending(self, underlying: str | None = None, due_by: str | None = None) -> list[dict]:
        """Forecasts without an outcome (optionally only those due by ``due_by``)."""
        q = (
            "SELECT f.id, f.underlying, f.resolve_ts, f.kind, f.params, f.prob "
            "FROM forecasts f LEFT JOIN outcomes o ON f.id = o.forecast_id WHERE o.forecast_id IS NULL"
        )
        args: list = []
        if underlying:
            q += " AND f.underlying = ?"
            args.append(underlying)
        if due_by:
            q += " AND f.resolve_ts <= ?"
            args.append(due_by)
        cols = ["id", "underlying", "resolve_ts", "kind", "params", "prob"]
        return [dict(zip(cols, r)) for r in self.con.execute(q, args).fetchall()]

    def resolve_due(self, underlying: str, realized_value: float, as_of: str | None = None) -> int:
        """Resolve all due, unresolved forecasts for an underlying with one realized level.
        Returns the number resolved."""
        as_of = as_of or datetime.now(timezone.utc).isoformat()
        due = self.pending(underlying=underlying, due_by=as_of)
        for row in due:
            self.resolve(row["id"], realized_value, resolved_ts=as_of)
        return len(due)

    # ---- scoring ----
    def _resolved(
        self, kind: str | None = None, classes: tuple[str, ...] | None = None
    ) -> tuple[list[float], list[int]]:
        """Resolved (prob, event) pairs. ``classes`` filters by source class (the rail):
        pass ``None`` for *all* rows (internal/QA) — callers facing users must pass an
        explicit class tuple so synthetic data can never leak in by accident."""
        q = "SELECT f.prob, o.event, f.source FROM forecasts f JOIN outcomes o ON f.id = o.forecast_id"
        args: list = []
        if kind:
            q += " WHERE f.kind = ?"
            args.append(kind)
        rows = self.con.execute(q, args).fetchall()
        if classes is not None:
            rows = [r for r in rows if source_class(r[2]) in classes]
        return [r[0] for r in rows], [r[1] for r in rows]

    def resolved_ordered(
        self, kind: str | None = None, classes: tuple[str, ...] | None = None
    ) -> list[tuple[float, int, str, dict]]:
        """Resolved ``(prob, event, created_ts, params)`` ordered by ``created_ts`` — the time-ordered
        view the calibration layer needs for purged WALK-FORWARD out-of-fold fitting (train on the
        past, test forward). ``classes`` applies the same source-class firewall as ``_resolved``."""
        q = ("SELECT f.prob, o.event, f.created_ts, f.params, f.source "
             "FROM forecasts f JOIN outcomes o ON f.id = o.forecast_id")
        args: list = []
        if kind:
            q += " WHERE f.kind = ?"
            args.append(kind)
        q += " ORDER BY f.created_ts"
        out: list[tuple[float, int, str, dict]] = []
        for prob, event, created, params, src in self.con.execute(q, args).fetchall():
            if classes is not None and source_class(src) not in classes:
                continue
            p = json.loads(params) if isinstance(params, str) else (params or {})
            out.append((float(prob), int(event), created, p))
        return out

    def _pending_count(self, classes: tuple[str, ...] | None = None) -> int:
        rows = self.con.execute(
            "SELECT f.source FROM forecasts f LEFT JOIN outcomes o ON f.id = o.forecast_id "
            "WHERE o.forecast_id IS NULL"
        ).fetchall()
        if classes is not None:
            rows = [r for r in rows if source_class(r[0]) in classes]
        return len(rows)

    def _counts_by_class(self) -> dict[str, int]:
        """Resolved-forecast counts grouped by source class — incl. excluded ('seed'/'demo'),
        so QA can see synthetic data exists in the DB even though it never enters the curve."""
        out: dict[str, int] = {}
        for (src,) in self.con.execute(
            "SELECT f.source FROM forecasts f JOIN outcomes o ON f.id = o.forecast_id"
        ).fetchall():
            c = source_class(src)
            out[c] = out.get(c, 0) + 1
        return out

    def metrics(self, n_bins: int = 10, classes: tuple[str, ...] | None = PUBLIC_CLASSES) -> dict:
        """Calibration metrics. By default ``classes=PUBLIC_CLASSES`` (backtest+live), so seed
        and demo forecasts are excluded from any user-facing report unless a caller *explicitly*
        opts into them. This is the single guardrail that keeps the moat honest."""
        probs, events = self._resolved(classes=classes)
        n = len(probs)
        band_probs, band_events = self._resolved(KIND_PROB_IN_BAND, classes=classes)
        ece = scoring.expected_calibration_error(probs, events, n_bins) if n else None
        return {
            "resolved_count": n,
            "pending_count": self._pending_count(classes=classes),
            "brier": scoring.brier_score(probs, events) if n else None,
            "log_loss": scoring.log_loss(probs, events) if n else None,
            "ece": ece,
            "calibration_score": calibration_score(ece, n),
            "reliability_curve": scoring.reliability_curve(probs, events, n_bins),
            "band_coverage": scoring.coverage(band_probs, band_events),
            "source_class_filter": list(classes) if classes is not None else None,
            "counts_by_class": self._counts_by_class(),
        }

    def metrics_by_class(self, n_bins: int = 10) -> dict[str, dict]:
        """Per-class metrics for the public panels: a separate curve+score for the backtested
        (real EOD, out-of-sample) and live (forward) track records. Synthetic never blends in."""
        return {c: self.metrics(n_bins, classes=(c,)) for c in PUBLIC_CLASSES}

    def metrics_for_tips(self, n_bins: int = 10) -> dict[str, dict]:
        """Issued-tip reliability on its OWN curve (tip_backtest + tip_live): "when a tip said 65%
        conviction, did ~65% win, after costs?". Kept separate from the market-implied probability
        curve (metrics_by_class) and from owner-only paper/today — they never blend."""
        return {c: self.metrics(n_bins, classes=(c,)) for c in TIP_PUBLIC_CLASSES}

    def metrics_for_structural(self, n_bins: int = 10) -> dict[str, dict]:
        """Decision-brief structural reliability (touch / VRP) on its OWN curve (struct_backtest +
        struct_live): "when we said 65% touch, did it touch ~65%?". Firewalled from every other curve.
        Calibration is PER-LABEL (touch labels are correlated across same-day strikes, but that bias is
        harmless to the binned reliability estimate — C3); the significance/edge gate is day-blocked
        elsewhere (`backtest.aggregate.cell_from_daily`)."""
        return {c: self.metrics(n_bins, classes=(c,)) for c in STRUCTURAL_CLASSES}

    def close(self) -> None:
        self.con.close()


def emit_forecasts(chain, dist, regime=None, model_version: str = "black76-1.0.0", source: str = "anvil") -> list[Forecast]:
    """Derive the standard probabilistic forecast set from an analysis of one chain.

    Uses the market-implied distribution: ±1σ and ±0.5σ containment bands plus a
    directional P(close above spot). These are probabilities/ranges — never buy/sell calls.
    """
    if dist is None:
        return []
    spot = chain.spot
    created, resolve = chain.timestamp, chain.expiry
    fwd = getattr(dist, "forward", spot)
    em = dist.expected_move_1sigma
    out: list[Forecast] = []

    def mk(kind, params, prob):
        return Forecast(
            underlying=chain.underlying, created_ts=created, resolve_ts=resolve, kind=kind,
            params=params, prob=float(prob), spot=float(spot), forward=float(fwd),
            model_version=model_version, source=source,
        )

    out.append(mk(KIND_PROB_IN_BAND, {"lower": spot - em, "upper": spot + em, "nominal": "1sigma"},
                  dist.prob_between(spot - em, spot + em)))
    half = 0.5 * em
    out.append(mk(KIND_PROB_IN_BAND, {"lower": spot - half, "upper": spot + half, "nominal": "0.5sigma"},
                  dist.prob_between(spot - half, spot + half)))
    out.append(mk(KIND_PROB_ABOVE, {"level": spot}, dist.prob_above(spot)))
    return out


def emit_structural_forecasts(
    chain, touch_probs: dict, vrp_read: dict | None, horizon_days: int, *,
    resolve_ts: str, model_version: str = "decision-brief-1.0.0", source: str = "struct_live",
) -> list[Forecast]:
    """Record the decision brief's calibratable claims (Wave 2): one PROB_TOUCH per strike (the
    VRP-adjusted physical read is the stated probability) + one VRP_RICH probability. ``resolve_ts`` is
    the horizon end (resolved later from the realized daily high/low and realized vol)."""
    spot, created = float(chain.spot), chain.timestamp
    fwd = spot
    out: list[Forecast] = []

    def mk(kind, params, prob):
        return Forecast(
            underlying=chain.underlying, created_ts=created, resolve_ts=resolve_ts, kind=kind,
            params=params, prob=float(prob), spot=spot, forward=float(fwd),
            model_version=model_version, source=source,
        )

    for k, t in (touch_probs or {}).items():
        p = t.get("p_touch_phys")
        if p is None:
            continue
        out.append(mk(KIND_PROB_TOUCH,
                      {"strike": float(k), "days": int(horizon_days), "dir": t.get("dir", "up")}, p))
    if vrp_read and vrp_read.get("prob_realized_lt_implied") is not None and vrp_read.get("atm_iv"):
        out.append(mk(KIND_VRP_RICH,
                      {"implied_vol": float(vrp_read["atm_iv"]), "days": int(horizon_days)},
                      vrp_read["prob_realized_lt_implied"]))
    return out
