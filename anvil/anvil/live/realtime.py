"""RealtimeEngine — the shared loop body for realtime and replay.

One ``run_tick`` per underlying: mark open positions, trip the kill-switch, manage exits, then
generate candidates and (paper-only) open the top-ranked through the Risk Governor, recording each
trade's conviction into the calibration moat. ``replay`` drives it deterministically over a seeded
synthetic path (zero keys, reproducible bit-for-bit); the live driver lands in Phase 3b. Conviction
forecasts resolve from realized P&L on close. In-memory by design; DB persistence wraps it (Phase 5).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..config import SETTINGS
from ..paper.account import PaperBook
from ..paper.calibration import record_conviction, resolve_conviction
from ..paper.gateway import PaperBrokerGateway
from ..paper.governor import RiskGovernor
from ..paper.report import run_report
from ..strategy import TRADE, SignalContext, generate_candidates
from .chain_source import ReplaySource
from .clock import ReplayClock

_MAX_MISSED = 200


class RealtimeEngine:
    def __init__(
        self,
        book: PaperBook | None = None,
        governor: RiskGovernor | None = None,
        ledger=None,
        max_opens_per_tick: int = 3,
        gen_cfg=None,
    ):
        self.book = book or PaperBook(gateway=PaperBrokerGateway())
        self.governor = governor or RiskGovernor()
        self.ledger = ledger
        self.max_opens_per_tick = int(max_opens_per_tick)
        # Optional per-run strategy/sizing config (tuning knobs). None -> GenConfig.from_settings().
        self.gen_cfg = gen_cfg
        self.iv_history: dict[str, list[float]] = {}
        self.missed: list[dict] = []
        self._closed_count = 0

    # --- shared per-underlying tick body -----------------------------------
    def run_tick(self, ctx: SignalContext, ts: str) -> None:
        self.book.mark_to_market(ctx)
        tripped = self.book.maybe_kill_switch(ctx)
        if not tripped:
            self.book.manage(ctx)
        self._resolve_new_closed()
        if not tripped and not self.book.halted:
            self._maybe_open(ctx, ts)
        if ctx.atm_iv:
            self.iv_history.setdefault(ctx.underlying, []).append(ctx.atm_iv)

    def _maybe_open(self, ctx: SignalContext, ts: str) -> None:
        opened = 0
        for cand in generate_candidates(ctx, self.book.equity(), cfg=self.gen_cfg):
            if cand.action != TRADE:
                continue
            if opened >= self.max_opens_per_tick:
                break
            pos, verdict = self.book.try_open(cand, ctx, self.governor, ts=ts)
            if pos is not None:
                if self.ledger is not None:
                    record_conviction(self.ledger, pos, ctx.spot, ctx.forward)
                opened += 1
            elif verdict is not None and not verdict.approved and len(self.missed) < _MAX_MISSED:
                self.missed.append({
                    "ts": ts, "underlying": cand.underlying, "strategy": cand.strategy,
                    "direction": cand.direction, "conviction": round(cand.conviction, 4),
                    "reasons": verdict.reasons,
                })

    def _resolve_new_closed(self) -> None:
        for pos in self.book.closed[self._closed_count:]:
            if self.ledger is not None and pos.ledger_forecast_id:
                try:
                    resolve_conviction(self.ledger, pos)
                except Exception:  # noqa: BLE001 - resolution must not crash the loop
                    pass
        self._closed_count = len(self.book.closed)

    # --- deterministic replay ----------------------------------------------
    def replay(
        self,
        underlyings,
        *,
        start_ts: str,
        expiry: str,
        steps: int = 24,
        cadence_s: int = 3600,
        seed: int = 7,
        source_label: str = "demo",
    ) -> dict:
        underlyings = [u.upper() for u in underlyings]
        src = ReplaySource(underlyings, start_ts, expiry, steps, seed=seed, cadence_s=cadence_s)
        clock = ReplayClock(start_ts, steps, cadence_s)
        last_ctx: dict[str, SignalContext] = {}
        last_ts = start_ts

        for step, ts in enumerate(clock.ticks()):
            for u in underlyings:
                chain = src.chain(u, ts, step)
                ctx = SignalContext(chain, iv_history=list(self.iv_history.get(u, [])), source=source_label)
                self.run_tick(ctx, ts)
                last_ctx[u] = ctx
            last_ts = ts
            self.book.record_equity_point(ts)

        # Session end: flatten everything at the last seen quote and resolve convictions.
        for ctx in last_ctx.values():
            self.book.flatten(ctx, reason="session_end")
        self._resolve_new_closed()
        if last_ctx:
            end_ts = (datetime.fromisoformat(last_ts.replace("Z", "+00:00")) + timedelta(seconds=1)).isoformat()
            self.book.record_equity_point(end_ts)

        meta = {
            "mode": "replay", "underlyings": underlyings, "steps": steps, "cadence_s": cadence_s,
            "seed": seed, "source": source_label, "start_ts": start_ts, "expiry": expiry,
            "vrp_ratio": SETTINGS.paper_vrp_ratio, "seller_mode": SETTINGS.paper_seller_mode,
        }
        return run_report(self.book, ledger=self.ledger, missed=self.missed, meta=meta)


# Module-level singleton for the API/worker lifespan (started only when a run is created).
_ENGINE: RealtimeEngine | None = None


def get_engine() -> RealtimeEngine | None:
    return _ENGINE


def set_engine(engine: RealtimeEngine | None) -> None:
    global _ENGINE
    _ENGINE = engine
