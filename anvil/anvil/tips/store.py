"""Per-cell tip validation reports — the MEASURED evidence the headline/watchlist gate reads.

One row per ``(structure, regime_bucket, underlying)`` cell, written by the tip backtest (and later
refreshed with live evidence). ``headline_eligible`` is the conjunction of every guard (sample size,
calibrated win-rate, positive post-cost edge, Harvey t-stat, Deflated Sharpe, low PBO, robust
bootstrap tail). The gate never recomputes — it just reads this verdict, so a tip is promoted to
headline only on standing, measured proof.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import duckdb

from ..config import SETTINGS

# Bump when the gate's inputs/logic change so previously-certified ``headline_eligible`` verdicts
# from an older gate no longer count as fresh (read by ``tips.gate.decide_tier``). Phase 0 hardening
# (honest trial-count, day-blocking, CPCV, deflation tidy) is a behavioural change → new version.
GATE_VERSION = "phase0-1.1.0"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tip_validation (
    structure VARCHAR,
    regime_bucket VARCHAR,
    underlying VARCHAR,
    n INTEGER,
    win_rate DOUBLE,
    mean_conviction DOUBLE,
    mean_net_pnl DOUBLE,
    cost_adjusted_edge DOUBLE,
    t_stat DOUBLE,
    dsr DOUBLE,
    pbo DOUBLE,
    robustness_p_low DOUBLE,
    headline_eligible BOOLEAN,
    updated_ts VARCHAR,
    model_version VARCHAR,
    PRIMARY KEY (structure, regime_bucket, underlying)
);
"""

_COLS = [
    "structure", "regime_bucket", "underlying", "n", "win_rate", "mean_conviction",
    "mean_net_pnl", "cost_adjusted_edge", "t_stat", "dsr", "pbo", "robustness_p_low",
    "headline_eligible", "updated_ts", "model_version",
]


@dataclass
class TipValidationReport:
    structure: str
    regime_bucket: str
    underlying: str
    n: int
    win_rate: float
    mean_conviction: float
    mean_net_pnl: float
    cost_adjusted_edge: float
    t_stat: float
    dsr: float
    pbo: float
    robustness_p_low: float
    headline_eligible: bool
    updated_ts: str = ""
    model_version: str = ""


class TipValidationStore:
    def __init__(self, path: str | None = None):
        self.path = path or SETTINGS.store_path
        self.con = duckdb.connect(self.path)
        self.con.execute(_SCHEMA)
        try:  # older DBs created before the freshness column existed
            self.con.execute("ALTER TABLE tip_validation ADD COLUMN IF NOT EXISTS model_version VARCHAR")
        except duckdb.Error:
            pass

    def upsert(self, r: TipValidationReport) -> None:
        d = asdict(r)
        self.con.execute(
            f"INSERT OR REPLACE INTO tip_validation ({','.join(_COLS)}) "
            f"VALUES ({','.join('?' for _ in _COLS)})",
            [d[c] for c in _COLS],
        )

    def get(self, structure: str, regime_bucket: str, underlying: str) -> dict | None:
        row = self.con.execute(
            f"SELECT {','.join(_COLS)} FROM tip_validation "
            "WHERE structure=? AND regime_bucket=? AND underlying=?",
            [structure, regime_bucket, underlying.upper()],
        ).fetchone()
        return dict(zip(_COLS, row)) if row else None

    def all(self) -> list[dict]:
        rows = self.con.execute(f"SELECT {','.join(_COLS)} FROM tip_validation").fetchall()
        return [dict(zip(_COLS, r)) for r in rows]

    def close(self) -> None:
        self.con.close()


_ISSUED_SCHEMA = """
CREATE TABLE IF NOT EXISTS tips_issued (
    tip_id VARCHAR PRIMARY KEY,
    ledger_forecast_id VARCHAR,
    underlying VARCHAR,
    created_ts VARCHAR,
    resolve_ts VARCHAR,
    structure VARCHAR,
    regime_bucket VARCHAR,
    tier VARCHAR,
    source VARCHAR,
    lot_size INTEGER,
    round_trip_cost DOUBLE,
    max_loss DOUBLE,
    legs JSON,
    payload JSON,
    resolved BOOLEAN,
    outcome INTEGER,
    resolved_ts VARCHAR,
    net_pnl DOUBLE,
    ret DOUBLE
);
"""


class IssuedTipStore:
    """Persistence for issued tips (with legs) so swing tips can be RESOLVED across days. Idempotent
    by content-hashed ``tip_id`` (re-issuing the same tip on the same bar is a no-op). The realized
    ``net_pnl``/``ret`` are stored on resolution so live evidence can be RE-validated (``backtest.
    revalidate``) into headline-eligible cells without re-running the historical backtest."""

    def __init__(self, path: str | None = None):
        self.path = path or SETTINGS.store_path
        self.con = duckdb.connect(self.path)
        self.con.execute(_ISSUED_SCHEMA)
        for ddl in ("ALTER TABLE tips_issued ADD COLUMN IF NOT EXISTS net_pnl DOUBLE",
                    "ALTER TABLE tips_issued ADD COLUMN IF NOT EXISTS ret DOUBLE"):
            try:  # older DBs created before these columns existed
                self.con.execute(ddl)
            except duckdb.Error:
                pass
        # Phase-5 coverage: how often the engine SPEAKS (actionable) vs abstains, per (day, underlying,
        # source). The denominator behind "size the few good calls well, not call volume."
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS tip_coverage ("
            "day VARCHAR, underlying VARCHAR, source VARCHAR, passes INTEGER, actionable_count INTEGER, "
            "watch_count INTEGER, abstain_count INTEGER, headline_count INTEGER, conviction_sum DOUBLE, "
            "spoke_count INTEGER, updated_ts VARCHAR, PRIMARY KEY (day, underlying, source))"
        )

    _INSERT_COLS = [
        "tip_id", "ledger_forecast_id", "underlying", "created_ts", "resolve_ts", "structure",
        "regime_bucket", "tier", "source", "lot_size", "round_trip_cost", "max_loss", "legs",
        "payload", "resolved", "outcome", "resolved_ts", "net_pnl", "ret",
    ]

    def record(self, tip) -> str:
        """Persist an issued tip (no-op if already present). Returns the tip_id."""
        self.con.execute(
            f"INSERT INTO tips_issued ({','.join(self._INSERT_COLS)}) "
            f"VALUES ({','.join('?' for _ in self._INSERT_COLS)}) ON CONFLICT (tip_id) DO NOTHING",
            [
                tip.tip_id, tip.ledger_forecast_id, tip.underlying, tip.created_ts, tip.resolve_ts,
                tip.structure, tip.regime_bucket, tip.tier, tip.source, int(tip.lot_size),
                float(tip.round_trip_cost), float(tip.max_loss), json.dumps(tip.legs),
                json.dumps(tip.to_dict()), False, None, None, None, None,
            ],
        )
        return tip.tip_id

    def due_unresolved(self, underlying: str, as_of_date: str) -> list[dict]:
        """Unresolved tips for ``underlying`` whose expiry settles on/before ``as_of_date`` (YYYY-MM-DD)."""
        rows = self.con.execute(
            "SELECT tip_id, ledger_forecast_id, lot_size, round_trip_cost, max_loss, legs, resolve_ts "
            "FROM tips_issued WHERE underlying=? AND resolved=FALSE AND substr(resolve_ts,1,10) <= ?",
            [underlying.upper(), as_of_date[:10]],
        ).fetchall()
        cols = ["tip_id", "ledger_forecast_id", "lot_size", "round_trip_cost", "max_loss", "legs", "resolve_ts"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["legs"] = json.loads(d["legs"]) if isinstance(d["legs"], str) else d["legs"]
            out.append(d)
        return out

    def mark_resolved(self, tip_id: str, outcome: int, resolved_ts: str,
                      net_pnl: float | None = None, ret: float | None = None) -> None:
        self.con.execute(
            "UPDATE tips_issued SET resolved=TRUE, outcome=?, resolved_ts=?, net_pnl=?, ret=? "
            "WHERE tip_id=?",
            [int(outcome), resolved_ts, net_pnl, ret, tip_id],
        )

    def resolved_cells(self, sources: tuple[str, ...] = ("tip_live",)) -> dict:
        """Aggregate RESOLVED tips into the ``{(structure, regime_bucket, underlying): cell}`` shape
        ``backtest.aggregate.validate_cells`` consumes — the evidence for live re-validation. Reads
        the stored realized ``ret``/``net_pnl`` and the conviction from each payload."""
        from collections import defaultdict

        ph = ",".join("?" for _ in sources)
        rows = self.con.execute(
            f"SELECT structure, regime_bucket, underlying, outcome, net_pnl, ret, resolved_ts, payload "
            f"FROM tips_issued WHERE resolved=TRUE AND source IN ({ph}) AND ret IS NOT NULL",
            list(sources),
        ).fetchall()
        cells: dict = defaultdict(
            lambda: {"returns": [], "net": [], "conv": [], "wins": 0, "by_day": defaultdict(list)})
        for structure, bucket, u, outcome, net, ret, rts, payload in rows:
            conv = 0.0
            try:
                conv = float((json.loads(payload) if isinstance(payload, str) else payload).get("conviction") or 0.0)
            except (TypeError, ValueError, AttributeError):
                pass
            day = (rts or "")[:10]
            for key in {(structure, bucket, u), (structure, bucket, "EQUITY")} if structure == "equity_directional" else {(structure, bucket, u)}:
                c = cells[key]
                c["returns"].append(float(ret))
                c["net"].append(float(net) if net is not None else 0.0)
                c["conv"].append(conv)
                c["wins"] += int(outcome or 0)
                if day:
                    c["by_day"][day].append(float(ret))
        return cells

    def resolved_spans(self, sources: tuple[str, ...] = ("tip_live",)) -> list[tuple[str, str]]:
        """``(created_ts, resolve_ts)`` for every resolved tip in ``sources`` — the label horizons the
        live re-validation gate turns into its OOF embargo (so multi-day live tips don't leak)."""
        ph = ",".join("?" for _ in sources)
        rows = self.con.execute(
            f"SELECT created_ts, resolve_ts FROM tips_issued "
            f"WHERE resolved=TRUE AND source IN ({ph}) AND ret IS NOT NULL",
            list(sources),
        ).fetchall()
        return [(c, r) for c, r in rows]

    def resolved_samples(self, sources: tuple[str, ...] = ("tip_live",)) -> list[dict]:
        """Flat per-tip resolved rows for Gate-0 — one dict per decision with the raw score, realized
        win/return, resolution day and regime, aligned so the calibrated accuracy/EV-at-coverage curves
        can be built. Reads conviction from the payload; ``ret`` is already NET of round-trip cost."""
        import json

        ph = ",".join("?" for _ in sources)
        rows = self.con.execute(
            f"SELECT structure, regime_bucket, underlying, outcome, net_pnl, ret, created_ts, "
            f"resolve_ts, resolved_ts, payload FROM tips_issued "
            f"WHERE resolved=TRUE AND source IN ({ph}) AND ret IS NOT NULL",
            list(sources),
        ).fetchall()
        out: list[dict] = []
        for structure, bucket, u, outcome, net, ret, created, resolve, rts, payload in rows:
            conv = 0.0
            try:
                conv = float((json.loads(payload) if isinstance(payload, str) else payload).get("conviction") or 0.0)
            except (TypeError, ValueError, AttributeError):
                pass
            out.append({
                "structure": structure, "regime_bucket": bucket, "underlying": u,
                "raw_score": conv, "event": int(outcome or 0), "ret": float(ret),
                "net": float(net) if net is not None else 0.0,
                "created_ts": created, "resolve_ts": resolve, "day": (rts or "")[:10],
            })
        return out

    def resolved_payloads(self, sources: tuple[str, ...] = ("tip_live",)) -> list[tuple[dict, int]]:
        """``(payload_dict, outcome)`` for resolved tips — the basis for meta-label feature extraction
        (the payload carries ``conviction`` + ``signals_fired`` + ``regime_bucket``). Skips unparseable rows."""
        import json

        ph = ",".join("?" for _ in sources)
        rows = self.con.execute(
            f"SELECT payload, outcome FROM tips_issued WHERE resolved=TRUE AND source IN ({ph})",
            list(sources),
        ).fetchall()
        out: list[tuple[dict, int]] = []
        for payload, outcome in rows:
            try:
                pd = json.loads(payload) if isinstance(payload, str) else payload
            except (TypeError, ValueError):
                continue
            if isinstance(pd, dict):
                out.append((pd, int(outcome or 0)))
        return out

    # --- Phase-5 coverage logging --------------------------------------------
    def bump_coverage(self, day: str, underlying: str, source: str, *, spoke: bool,
                      actionable: bool, watch: bool, headline: bool, conviction: float | None) -> None:
        """ADDITIVE one-pass increment (the LIVE tick path — a run is a session; coverage % is this
        session's speak rate). Counts one engine pass and folds in whether it spoke and at what tier."""
        conv = float(conviction) if (spoke and conviction is not None) else 0.0
        self.con.execute(
            "INSERT INTO tip_coverage (day, underlying, source, passes, actionable_count, watch_count, "
            "abstain_count, headline_count, conviction_sum, spoke_count, updated_ts) "
            "VALUES (?,?,?,1,?,?,?,?,?,?,?) "
            "ON CONFLICT (day, underlying, source) DO UPDATE SET "
            "passes = tip_coverage.passes + 1, "
            "actionable_count = tip_coverage.actionable_count + EXCLUDED.actionable_count, "
            "watch_count = tip_coverage.watch_count + EXCLUDED.watch_count, "
            "abstain_count = tip_coverage.abstain_count + EXCLUDED.abstain_count, "
            "headline_count = tip_coverage.headline_count + EXCLUDED.headline_count, "
            "conviction_sum = tip_coverage.conviction_sum + EXCLUDED.conviction_sum, "
            "spoke_count = tip_coverage.spoke_count + EXCLUDED.spoke_count, "
            "updated_ts = EXCLUDED.updated_ts",
            [day[:10], underlying.upper(), source, int(actionable), int(watch),
             int(not spoke), int(headline), conv, int(spoke), day],
        )

    def set_coverage_day(self, day: str, underlying: str, source: str, *, passes: int, actionable: int,
                         watch: int, abstain: int, headline: int, conviction_sum: float, spoke: int) -> None:
        """IDEMPOTENT day-grained write (the EOD cycle path — derive from the day's issued tips and
        REPLACE, so re-running a day overwrites instead of inflating)."""
        self.con.execute(
            "INSERT OR REPLACE INTO tip_coverage (day, underlying, source, passes, actionable_count, "
            "watch_count, abstain_count, headline_count, conviction_sum, spoke_count, updated_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [day[:10], underlying.upper(), source, int(passes), int(actionable), int(watch),
             int(abstain), int(headline), float(conviction_sum), int(spoke), day],
        )

    def coverage_rolling(self, n_days: int = 20, underlying: str | None = None) -> dict:
        """Rolling coverage over the last ``n_days`` distinct days: speak rate, actionable rate, mean
        conviction when it spoke. The honest 'how often the engine speaks' dial."""
        args: list = []
        where = ""
        if underlying:
            where = "WHERE underlying=?"
            args.append(underlying.upper())
        days = [r[0] for r in self.con.execute(
            f"SELECT DISTINCT day FROM tip_coverage {where} ORDER BY day DESC LIMIT ?",
            [*args, int(n_days)]).fetchall()]
        if not days:
            return {"days": 0, "passes": 0, "coverage_pct": None, "actionable_pct": None,
                    "mean_conviction_when_spoke": None}
        ph = ",".join("?" for _ in days)
        sums = self.con.execute(
            f"SELECT COALESCE(SUM(passes),0), COALESCE(SUM(spoke_count),0), COALESCE(SUM(actionable_count),0), "
            f"COALESCE(SUM(conviction_sum),0.0) FROM tip_coverage {('WHERE' if not where else where + ' AND')} day IN ({ph})",
            [*args, *days]).fetchone()
        passes, spoke, actionable, conv_sum = int(sums[0]), int(sums[1]), int(sums[2]), float(sums[3])
        return {
            "days": len(days),
            "passes": passes,
            "coverage_pct": round(spoke / passes, 4) if passes else None,
            "actionable_pct": round(actionable / passes, 4) if passes else None,
            "mean_conviction_when_spoke": round(conv_sum / spoke, 4) if spoke else None,
        }

    def recent(self, underlying: str | None = None, tier: str | None = None, limit: int = 50) -> list[dict]:
        """Most-recently-issued tips' payloads (for the API feed)."""
        q = "SELECT payload FROM tips_issued"
        clauses, args = [], []
        if underlying:
            clauses.append("underlying=?")
            args.append(underlying.upper())
        if tier:
            clauses.append("tier=?")
            args.append(tier)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_ts DESC LIMIT ?"
        args.append(int(limit))
        return [json.loads(r[0]) for r in self.con.execute(q, args).fetchall()]

    def close(self) -> None:
        self.con.close()
