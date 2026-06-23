import { fmt } from "./api";

// All charts are dependency-free inline SVG so the bundle stays tiny and we control the look.

export function RangeCone({ spot, em }: { spot: number; em: number | null | undefined }) {
  if (!em || !spot) return <div className="muted">No implied distribution.</div>;
  const W = 520, H = 130, padX = 40;
  const lo = spot - 2.4 * em, hi = spot + 2.4 * em;
  const x = (v: number) => padX + ((v - lo) / (hi - lo)) * (W - 2 * padX);
  const midY = H / 2;
  const band = (k: number) => (
    <rect x={x(spot - k * em)} y={midY - 8 - k * 18} width={x(spot + k * em) - x(spot - k * em)}
      height={16 + k * 36} rx={8} fill={k === 1 ? "#4493f833" : "#4493f81a"} stroke="#4493f855" />
  );
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="expected range cone">
      {band(2)}
      {band(1)}
      <line x1={x(spot)} y1={20} x2={x(spot)} y2={H - 22} stroke="#e6edf3" strokeWidth={2} />
      <circle cx={x(spot)} cy={midY} r={4} fill="#f0883e" />
      <text x={x(spot)} y={14} textAnchor="middle" style={{ fill: "#e6edf3" }}>{fmt(spot)}</text>
      <text x={x(spot - em)} y={H - 6} textAnchor="middle">{fmt(spot - em)}</text>
      <text x={x(spot + em)} y={H - 6} textAnchor="middle">{fmt(spot + em)}</text>
      <text x={padX} y={H - 6}>−2σ</text>
      <text x={W - padX} y={H - 6} textAnchor="end">+2σ</text>
    </svg>
  );
}

export function CalibrationDiagonal({ curve }: { curve: any[] }) {
  const S = 220, pad = 24;
  const px = (v: number) => pad + v * (S - 2 * pad);
  const py = (v: number) => S - pad - v * (S - 2 * pad);
  return (
    <svg viewBox={`0 0 ${S} ${S}`} width="100%" style={{ maxWidth: 260 }} role="img" aria-label="calibration diagonal">
      <rect x={pad} y={pad} width={S - 2 * pad} height={S - 2 * pad} fill="#0b0f16" stroke="#30363d" />
      <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)} stroke="#8b949e" strokeDasharray="4 4" />
      {(curve || []).map((b, i) => (
        <circle key={i} cx={px(b.predicted_mean)} cy={py(b.empirical_freq)}
          r={Math.max(3, Math.min(9, Math.sqrt(b.count)))} fill="#4493f8aa" stroke="#4493f8" />
      ))}
      <text x={S / 2} y={S - 4} textAnchor="middle">predicted →</text>
      <text x={10} y={S / 2} textAnchor="middle" transform={`rotate(-90 10 ${S / 2})`}>actual →</text>
    </svg>
  );
}

export function Histogram({ edges, counts }: { edges: number[]; counts: number[] }) {
  if (!edges?.length || !counts?.length) return null;
  const W = 520, H = 150, pad = 28;
  const maxC = Math.max(...counts, 1);
  const n = counts.length;
  const bw = (W - 2 * pad) / n;
  const zeroX = pad + ((0 - edges[0]) / (edges[n] - edges[0])) * (W - 2 * pad);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="P&L distribution">
      {counts.map((c, i) => {
        const h = (c / maxC) * (H - 2 * pad);
        const mid = (edges[i] + edges[i + 1]) / 2;
        return <rect key={i} x={pad + i * bw + 1} y={H - pad - h} width={bw - 2} height={h} rx={2}
          fill={mid >= 0 ? "#3fb95099" : "#f8514999"} />;
      })}
      <line x1={zeroX} y1={pad - 6} x2={zeroX} y2={H - pad} stroke="#e6edf3" strokeWidth={1} strokeDasharray="3 3" />
      <text x={pad} y={H - 6}>{fmt(edges[0])}</text>
      <text x={W - pad} y={H - 6} textAnchor="end">{fmt(edges[n])}</text>
      <text x={zeroX} y={pad - 8} textAnchor="middle" style={{ fill: "#e6edf3" }}>P&amp;L=0</text>
    </svg>
  );
}

export function ScenarioHeat({ grid }: { grid: any }) {
  if (!grid?.has_positions || !grid?.cells?.length)
    return <div className="muted">Connect positions (or the demo book) to see scenario P&amp;L.</div>;
  const spots: number[] = grid.spot_shocks;
  const vols: number[] = grid.vol_shifts;
  const max = Math.max(1, ...grid.cells.map((c: any) => Math.abs(c.pnl)));
  const color = (p: number) => {
    const t = Math.min(1, Math.abs(p) / max);
    return p >= 0 ? `rgba(63,185,80,${0.15 + 0.6 * t})` : `rgba(248,81,73,${0.15 + 0.6 * t})`;
  };
  const cell = (ss: number, vs: number) => grid.cells.find((c: any) => c.spot_shock === ss && c.vol_shift === vs);
  return (
    <table className="mono">
      <thead>
        <tr><th>IV \ Spot</th>{spots.map((s) => <th key={s}>{(s * 100).toFixed(0)}%</th>)}</tr>
      </thead>
      <tbody>
        {vols.map((v) => (
          <tr key={v}>
            <td>{v >= 0 ? "+" : ""}{(v * 100).toFixed(0)}v</td>
            {spots.map((s) => {
              const c = cell(s, v);
              return <td key={s} style={{ background: color(c?.pnl ?? 0) }}>{fmt(c?.pnl ?? 0)}</td>;
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function EquityCurve({ points, start }: { points: { equity: number }[]; start: number }) {
  if (!points?.length) return <div className="muted">No equity curve yet — run a mock session.</div>;
  const W = 520, H = 160, pad = 34;
  const eqs = points.map((p) => p.equity);
  const lo = Math.min(start, ...eqs), hi = Math.max(start, ...eqs);
  const span = hi - lo || 1;
  const x = (i: number) => pad + (i / (points.length - 1 || 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - lo) / span) * (H - 2 * pad);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join(" ");
  const end = eqs[eqs.length - 1];
  const up = end >= start;
  const startY = y(start);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="paper equity curve">
      <line x1={pad} y1={startY} x2={W - pad} y2={startY} stroke="#8b949e" strokeDasharray="4 4" />
      <path d={path} fill="none" stroke={up ? "#3fb950" : "#f85149"} strokeWidth={2} />
      <text x={pad} y={14}>{fmt(hi)}</text>
      <text x={pad} y={H - 6}>{fmt(lo)}</text>
      <text x={W - pad} y={14} textAnchor="end" style={{ fill: up ? "#3fb950" : "#f85149" }}>
        {up ? "▲" : "▼"} {fmt(end)}
      </text>
    </svg>
  );
}

export function OIWalls({ oi }: { oi: any }) {
  const calls: [number, number][] = oi?.call_resistance || [];
  const puts: [number, number][] = oi?.put_support || [];
  const max = Math.max(1, ...calls.map((c) => c[1]), ...puts.map((p) => p[1]));
  const Bar = ({ k, v, side }: { k: number; v: number; side: "call" | "put" }) => (
    <div className="row" style={{ gap: 8 }}>
      <span className="mono" style={{ width: 64 }}>{fmt(k)}</span>
      <div style={{ flex: 1, background: "#0b0f16", borderRadius: 6, overflow: "hidden" }}>
        <div style={{ width: `${(v / max) * 100}%`, height: 14, background: side === "call" ? "#f8514988" : "#3fb95088" }} />
      </div>
      <span className="mono muted" style={{ width: 70, textAlign: "right" }}>{fmt(v)}</span>
    </div>
  );
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div className="muted" style={{ fontSize: 12 }}>Call walls (resistance)</div>
      {calls.map((c, i) => <Bar key={"c" + i} k={c[0]} v={c[1]} side="call" />)}
      <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Put walls (support)</div>
      {puts.map((p, i) => <Bar key={"p" + i} k={p[0]} v={p[1]} side="put" />)}
    </div>
  );
}

// Terminal-payoff hockey-stick for a structure — the SAME math as Python ``terminal_payoff`` so the
// drawn P&L matches how a tip is resolved. EQ/FUT legs are linear; CE/PE are intrinsic at expiry.
export function PayoffDiagram(
  { legs, lotSize, spot, breakevens }:
  { legs: any[]; lotSize: number; spot: number; breakevens?: number[] },
) {
  if (!legs?.length || !spot) return <div className="muted">No structure to plot.</div>;
  const lot = lotSize || 1;
  const payoff = (S: number) => {
    let p = 0;
    for (const l of legs) {
      const lots = Math.abs(l.lots || 0);
      if (lots <= 0) continue;
      const ref = l.ref_price || 0;
      const sign = String(l.side).toUpperCase() === "BUY" ? 1 : -1;
      const itype = String(l.instrument_type || l.option_type || "").toUpperCase();
      let terminal: number;
      if (itype === "FUT" || itype === "EQ") terminal = S;
      else if (itype === "CE") terminal = Math.max(S - (l.strike || 0), 0);
      else if (itype === "PE") terminal = Math.max((l.strike || 0) - S, 0);
      else continue;
      p += sign * (terminal - ref) * lots * lot;
    }
    return p;
  };
  const ks = legs.map((l) => l.strike).filter((x: any) => x != null) as number[];
  const dists = ks.length ? ks.map((k) => Math.abs(k - spot)) : [spot * 0.08];
  const span = Math.max(spot * 0.08, ...dists) * 1.6;
  const lo = spot - span, hi = spot + span;
  const N = 64;
  const xs = Array.from({ length: N + 1 }, (_, i) => lo + ((hi - lo) * i) / N);
  const ys = xs.map(payoff);
  const yMin = Math.min(...ys, 0), yMax = Math.max(...ys, 0);
  const W = 520, H = 170, pad = 30;
  const X = (v: number) => pad + ((v - lo) / (hi - lo)) * (W - 2 * pad);
  const Y = (v: number) => H - pad - ((v - yMin) / (yMax - yMin || 1)) * (H - 2 * pad);
  const pts = xs.map((x, i) => `${X(x).toFixed(1)},${Y(ys[i]).toFixed(1)}`).join(" ");
  const zeroY = Y(0);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="payoff diagram">
      <rect x={pad} y={pad} width={W - 2 * pad} height={H - 2 * pad} fill="#0b0f16" stroke="#30363d" />
      <rect x={pad} y={pad} width={W - 2 * pad} height={Math.max(0, zeroY - pad)} fill="#3fb95012" />
      <rect x={pad} y={zeroY} width={W - 2 * pad} height={Math.max(0, H - pad - zeroY)} fill="#f8514912" />
      <line x1={pad} y1={zeroY} x2={W - pad} y2={zeroY} stroke="#8b949e" strokeDasharray="4 4" />
      <line x1={X(spot)} y1={pad} x2={X(spot)} y2={H - pad} stroke="#f0883e" strokeWidth={1} strokeDasharray="2 3" />
      {(breakevens || []).map((b, i) => (
        <line key={i} x1={X(b)} y1={pad} x2={X(b)} y2={H - pad} stroke="#e6edf3" strokeWidth={1} opacity={0.4} />
      ))}
      <polyline points={pts} fill="none" stroke="#4493f8" strokeWidth={2} />
      <text x={pad} y={H - 8}>{fmt(lo)}</text>
      <text x={W - pad} y={H - 8} textAnchor="end">{fmt(hi)}</text>
      <text x={X(spot)} y={pad - 4} textAnchor="middle" style={{ fill: "#f0883e" }}>spot {fmt(spot)}</text>
      <text x={pad + 4} y={pad + 12} style={{ fill: "#3fb950" }}>max {fmt(yMax)}</text>
      <text x={pad + 4} y={H - pad - 4} style={{ fill: "#f85149" }}>min {fmt(yMin)}</text>
    </svg>
  );
}

// Which factors fired, how strongly, and which way — STRONG green, CONFIRMATION blue, regime-masked
// dimmed. Reuses the OIWalls bar idiom. Honest: strength is a weight, not a probability.
export function FactorBars({ factors }: { factors: any[] }) {
  const fired = (factors || []).filter((f) => f.fired);
  if (!fired.length) return <div className="muted" style={{ fontSize: 12 }}>No factors fired in this regime.</div>;
  return (
    <div style={{ display: "grid", gap: 7 }}>
      {fired.map((f, i) => {
        const w = Math.round(Math.min(1, f.strength || 0) * 100);
        const strong = f.edge_tier === "strong";
        const masked = !f.active;
        const color = masked ? "#6e7681" : strong ? "#3fb950" : "#4493f8";
        return (
          <div key={i} style={{ opacity: masked ? 0.55 : 1 }}>
            <div className="row" style={{ justifyContent: "space-between", fontSize: 11 }}>
              <span>{String(f.name).replace(/_/g, " ")}{f.direction ? <span className="muted"> · {f.direction}</span> : null}</span>
              <span className="muted">{strong ? "STRONG" : "confirm"}{masked ? " · masked" : ""}</span>
            </div>
            <div style={{ background: "#0b0f16", borderRadius: 4, height: 8, overflow: "hidden" }}>
              <div style={{ width: `${w}%`, background: color, height: 8 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Risk-coverage: starting from the highest-confidence tips and widening, how does measured accuracy
// trade off against how often we speak? Built from the live reliability bins — measured, not asserted.
export function RiskCoverageCurve({ curve }: { curve: any[] }) {
  const bins = (curve || []).filter((b) => (b.count || 0) > 0)
    .slice().sort((a, b) => (b.predicted_mean || 0) - (a.predicted_mean || 0));
  const total = bins.reduce((s, b) => s + (b.count || 0), 0);
  if (!total) return <div className="muted" style={{ fontSize: 12 }}>Not enough resolved tips for a risk-coverage curve yet.</div>;
  let cum = 0, wacc = 0;
  const pts: [number, number][] = [];
  for (const b of bins) { cum += b.count; wacc += (b.empirical_freq || 0) * b.count; pts.push([cum / total, wacc / cum]); }
  const S = 220, pad = 26;
  const X = (v: number) => pad + v * (S - 2 * pad);
  const Y = (v: number) => S - pad - v * (S - 2 * pad);
  const line = pts.map(([c, a]) => `${X(c).toFixed(1)},${Y(a).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${S} ${S}`} width="100%" style={{ maxWidth: 260 }} role="img" aria-label="risk-coverage curve">
      <rect x={pad} y={pad} width={S - 2 * pad} height={S - 2 * pad} fill="#0b0f16" stroke="#30363d" />
      <line x1={X(0)} y1={Y(0.5)} x2={X(1)} y2={Y(0.5)} stroke="#8b949e" strokeDasharray="3 3" />
      <polyline points={line} fill="none" stroke="#3fb950" strokeWidth={2} />
      {pts.map(([c, a], i) => <circle key={i} cx={X(c)} cy={Y(a)} r={3} fill="#3fb950" />)}
      <text x={S / 2} y={S - 4} textAnchor="middle">coverage →</text>
      <text x={10} y={S / 2} textAnchor="middle" transform={`rotate(-90 10 ${S / 2})`}>accuracy →</text>
    </svg>
  );
}
