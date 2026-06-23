// Module-level simulator run store. Lives ABOVE the Simulator tab so a run keeps going (and its
// result survives) when you switch to another tab — the React component can unmount, but the
// in-flight request + state live here. On mount the tab also rehydrates the latest run from the
// server (covers a page reload, for completed runs).
import { useSyncExternalStore } from "react";
import { api } from "./api";

export type SimMode = "replay" | "today" | "live";

export interface SimState {
  running: boolean;
  live: boolean; // a live session is streaming
  mode: SimMode;
  underlying: string;
  report: any | null;
  curve: any[];
  scorecard: any | null;
  runId: number | null;
  err: string;
  note: string;
  startedAt: number | null;
}

let state: SimState = {
  running: false, live: false, mode: "today", underlying: "NIFTY", report: null, curve: [],
  scorecard: null, runId: null, err: "", note: "", startedAt: null,
};
let es: EventSource | null = null;
const listeners = new Set<() => void>();
function set(p: Partial<SimState>) {
  state = { ...state, ...p };
  listeners.forEach((l) => l());
}

export const simStore = {
  subscribe(l: () => void) {
    listeners.add(l);
    return () => { listeners.delete(l); };
  },
  get(): SimState {
    return state;
  },
  setMode(mode: SimMode) {
    set({ mode });
  },
  async start(underlying: string, mode: SimMode, config: Record<string, any>) {
    if (state.running || state.live) return;
    set({ running: true, live: false, err: "", note: "", underlying, mode, report: null, curve: [], scorecard: null, runId: null, startedAt: Date.now() });
    try {
      if (mode === "live") {
        const r = await api.paperRun({ mode: "live", underlyings: [underlying], cadence_s: config.cadence_s || 60, config });
        if (!r.run_id) throw new Error("live run did not start");
        set({ running: false, live: true, runId: r.run_id, curve: [] });
        this._openStream(r.run_id);
        return;
      }
      const body: any =
        mode === "today"
          ? { mode: "today", underlyings: [underlying], config }
          : { underlyings: [underlying], steps: 20, cadence_s: 7200, seed: 7, config };
      const rep = await api.paperRun(body);
      const curve = rep.run_id ? await api.paperEquityCurve(rep.run_id).catch(() => []) : [];
      set({ running: false, report: rep, curve, runId: rep.run_id ?? null, scorecard: rep.prediction_scorecard ?? null });
    } catch (e: any) {
      set({ running: false, live: false, err: e?.message || "Run failed." });
    }
  },
  _openStream(runId: number) {
    try { es?.close(); } catch { /* ignore */ }
    es = new EventSource(`/api/paper/runs/${runId}/stream`);
    es.onmessage = (ev) => {
      let d: any;
      try { d = JSON.parse(ev.data); } catch { return; }
      if (d.done) {
        try { es?.close(); } catch { /* ignore */ }
        es = null;
        set({ live: false, note: d.note || "" });
        // pull the persisted final curve + run summary
        api.paperEquityCurve(runId).then((c) => set({ curve: c || [] })).catch(() => {});
        return;
      }
      if (d.ts && d.equity != null) {
        set({ curve: [...state.curve, { ts: d.ts, equity: d.equity, cash: d.cash, unrealized_pnl: d.unrealized_pnl, realized_pnl: d.realized_pnl, drawdown: d.drawdown, open_positions: d.open_positions }] });
      }
    };
    es.onerror = () => { /* EventSource auto-reconnects; nothing to do */ };
  },
  async stop() {
    if (state.runId) { try { await api.paperStop(state.runId); } catch { /* ignore */ } }
    try { es?.close(); } catch { /* ignore */ }
    es = null;
    set({ live: false });
  },
  // Reload recovery: show the most recent completed run's summary + equity curve.
  async rehydrateLatest() {
    if (state.report || state.running) return;
    try {
      const runs = await api.paperRuns();
      if (!runs?.length) return;
      const latest = [...runs].sort((a, b) => (b.id ?? 0) - (a.id ?? 0))[0];
      if (latest?.status === "done" && latest.stats) {
        const curve = await api.paperEquityCurve(latest.id).catch(() => []);
        set({
          report: { summary: latest.stats, trades: latest.stats, risk: latest.stats, attribution: {}, rehydrated: true },
          curve, runId: latest.id, mode: (latest.mode === "replay" ? "replay" : "today"),
        });
      }
    } catch {
      /* ignore */
    }
  },
};

export function useSimStore(): SimState {
  return useSyncExternalStore(simStore.subscribe, simStore.get);
}
