import { useEffect, useState } from "react";
import { ApiError, INDEXES, Me, Mode, api, fmt, pct } from "./api";
import { CalibrationDiagonal, EquityCurve, FactorBars, Histogram, OIWalls, PayoffDiagram, RangeCone, RiskCoverageCurve, ScenarioHeat } from "./charts";
import { SimMode, simStore, useSimStore } from "./simStore";
import { Card, Learn, Provenance, Stat, Traffic, Why } from "./ui";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);
  // If we landed here with an OAuth ?code (e.g. a stale service worker served the shell for the
  // Upstox callback), finish the exchange ourselves, then reload clean.
  const [connecting] = useState(() => new URLSearchParams(window.location.search).has("code"));

  async function refresh() {
    try {
      setMe(await api.me());
    } catch {
      setMe(null);
      try {
        setNeedsSetup((await api.status()).needs_setup);
      } catch {
        /* offline */
      }
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("code");
    if (code) {
      api.upstoxExchange(code)
        .then(() => window.location.replace("/?broker=upstox_connected"))
        .catch((e) =>
          window.location.replace(
            "/?broker=upstox_exchange_failed&detail=" +
              encodeURIComponent(e instanceof ApiError ? e.message : "")
          )
        );
      return;
    }
    refresh();
  }, []);

  if (connecting) return <div className="center muted">Connecting your broker…</div>;
  if (loading) return <div className="center muted">Loading Anvil…</div>;
  if (!me) return <Auth needsSetup={needsSetup} onAuthed={refresh} />;
  if (!me.profile.onboarded) return <Onboarding me={me} onDone={refresh} />;
  return <Dashboard me={me} onLogout={refresh} />;
}

/* ---------------------------------------------------------------- auth */
function Auth({ needsSetup, onAuthed }: { needsSetup: boolean; onAuthed: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      if (needsSetup) await api.register(email, password);
      else await api.login(email, password);
      onAuthed();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="center">
      <form className="panel card" onSubmit={submit}>
        <div className="brand" style={{ marginBottom: 14 }}>
          <img className="logo" src="/icon.svg" /> Anvil
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          {needsSetup ? "Create your owner account." : "Sign in to your instance."}
        </p>
        <div className="field">
          <label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div className="field">
          <label>Password{needsSetup ? " (8+ chars)" : ""}</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        <button className="btn" disabled={busy} style={{ width: "100%" }}>
          {needsSetup ? "Create account" : "Sign in"}
        </button>
        {err && <div className="err">{err}</div>}
        <p className="disclaimer">Analytics &amp; education only. Not investment advice.</p>
      </form>
    </div>
  );
}

/* ---------------------------------------------------------------- onboarding */
function Onboarding({ me, onDone }: { me: Me; onDone: () => void }) {
  const [index, setIndex] = useState("NIFTY");
  const [mode, setMode] = useState<Mode>("trader");
  const [busy, setBusy] = useState(false);
  async function finish() {
    setBusy(true);
    await api.patchProfile({ benchmark: index, explain_mode: mode, onboarded: true });
    onDone();
  }
  return (
    <div className="center">
      <div className="panel card">
        <h3>Welcome, {me.email}</h3>
        <p className="q">Let’s tune Anvil to how you trade.</p>
        <div className="field">
          <label>Which index do you trade most?</label>
          <select value={index} onChange={(e) => setIndex(e.target.value)}>
            {INDEXES.map((i) => <option key={i}>{i}</option>)}
          </select>
        </div>
        <div className="field">
          <label>How much detail do you want?</label>
          <div className="seg" style={{ width: "100%" }}>
            {(["simple", "trader", "expert"] as Mode[]).map((m) => (
              <button key={m} type="button" className={mode === m ? "on" : ""} style={{ flex: 1 }} onClick={() => setMode(m)}>
                {m[0].toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <p className="muted" style={{ fontSize: 13 }}>
          Simple = plain-language read · Trader = GEX/OI/IV + your book · Expert = full curves &amp; internals.
          You can change this anytime. Connect a broker later from Settings to see your real positions.
        </p>
        <button className="btn" disabled={busy} style={{ width: "100%" }} onClick={finish}>
          Enter the cockpit
        </button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- dashboard */
type Tab = "today" | "tips" | "momentum" | "sim" | "risk" | "copilot" | "alerts" | "more";

function Dashboard({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [u, setU] = useState(me.profile.benchmark || "NIFTY");
  const [mode, setMode] = useState<Mode>(me.profile.explain_mode || "trader");
  const [tab, setTab] = useState<Tab>("today");
  // Keep-alive: render each tab the first time it's opened, then keep it MOUNTED and merely hide the
  // inactive ones (display:none) instead of unmounting. Tips/Risk/Copilot/Alerts/More then retain
  // their loaded data + in-flight fetches across tab switches — they no longer reset to a loading
  // spinner every time you come back. (The Simulator already survived via its module store; this
  // extends the same "doesn't reset, keeps working in the background" guarantee to every tab.)
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set<Tab>(["today"]));
  useEffect(() => {
    setVisited((v) => (v.has(tab) ? v : new Set(v).add(tab)));
  }, [tab]);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  // The broker OAuth round-trip result, surfaced at the top of the dashboard no matter which tab
  // we land on (the redirect always returns to the default "today" tab). This is what made the
  // Upstox connect outcome invisible before — it was only rendered inside the "More" tab.
  const [broker, setBroker] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const p = q.get("broker");
    if (!p) return;
    const detail = q.get("detail");
    const ok = p.endsWith("_connected");
    const m: Record<string, string> = {
      upstox_connected: "Upstox connected — live market data is on.",
      upstox_exchange_failed:
        "Upstox token exchange failed" +
        (detail ? `: ${detail}` : ". Verify UPSTOX_API_SECRET and that the redirect URI registered in your Upstox app exactly matches the server's UPSTOX_REDIRECT_URI."),
      upstox_session_lost: "You were signed out during the Upstox redirect. Sign in, then click Open login again.",
      upstox_unconfigured: "Set UPSTOX_API_KEY and UPSTOX_API_SECRET on the server, then restart.",
      upstox_error: "Upstox login was cancelled or returned no code.",
    };
    setBroker({ ok, text: m[p] || p });
    window.history.replaceState({}, "", window.location.pathname);
  }, []);

  useEffect(() => {
    let live = true;
    setData(null);
    setErr("");
    // Each panel fails independently — one bad call must never blank the whole tab.
    Promise.all([
      api.brief(u).catch(() => null),
      api.analyze(u).catch(() => null),
      api.calibration().catch(() => null),
      api.eventRisk(u).catch(() => null),
      api.whatChanged(u).catch(() => null),
      api.ivCrush(u).catch(() => null),
    ]).then(([brief, analyze, calibration, event, changed, crush]) => {
      if (!live) return;
      if (!analyze) {
        setErr(`Couldn't load ${u}. Is the data source reachable (or your broker connected)?`);
        return;
      }
      setData({ brief, analyze, calibration, event, changed, crush });
    });
    return () => {
      live = false;
    };
  }, [u]);

  async function setModePersist(m: Mode) {
    setMode(m);
    api.patchProfile({ explain_mode: m }).catch(() => {});
  }

  const prov = data?.analyze?.provenance;
  return (
    <div className="app">
      <div className="topbar">
        <div className="brand"><img className="logo" src="/icon.svg" /> Anvil</div>
        <select value={u} onChange={(e) => setU(e.target.value)} style={{ width: 150 }}>
          {INDEXES.map((i) => <option key={i}>{i}</option>)}
        </select>
        <div className="seg">
          {(["simple", "trader", "expert"] as Mode[]).map((m) => (
            <button key={m} className={mode === m ? "on" : ""} onClick={() => setModePersist(m)}>
              {m[0].toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
        <div className="spacer" />
        <CockpitHeader />
        {prov && <Provenance p={prov} />}
        <button className="btn ghost" onClick={async () => { await api.logout(); onLogout(); }}>Sign out</button>
      </div>

      {broker && (
        <div
          className="banner"
          style={
            broker.ok
              ? { borderColor: "#2c6e49", background: "#10231a", color: "#9be6b8" }
              : { borderColor: "#8b2c2c", background: "#3d1212", color: "#f0a0a0" }
          }
        >
          {broker.text}
          <button className="chip" style={{ marginLeft: 10 }} onClick={() => setBroker(null)}>dismiss</button>
        </div>
      )}

      {prov?.mode === "demo" && (
        <div className="banner">
          {prov.fallback_reason || "Demo data — connect Upstox to switch this instance to live market data."}
        </div>
      )}

      <div className="tabs">
        {(["today", "tips", "momentum", "sim", "risk", "copilot", "alerts", "more"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {t === "today" ? "Today" : t === "tips" ? "Tips" : t === "momentum" ? "Momentum" : t === "sim" ? "Simulator" : t === "more" ? "More" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {err && <div className="banner" style={{ borderColor: "#8b2c2c", background: "#3d1212", color: "#f0a0a0" }}>{err}</div>}
      {tab === "today" && !data && !err && <div className="muted">Loading {u}…</div>}

      {/* Keep-alive panels: mounted on first visit, then hidden (not unmounted) when inactive. */}
      {visited.has("today") && (
        <div style={{ display: tab === "today" ? undefined : "none" }}>{data && <Today data={data} mode={mode} />}</div>
      )}
      {visited.has("tips") && (
        <div style={{ display: tab === "tips" ? undefined : "none" }}><TipsTab u={u} /></div>
      )}
      {visited.has("momentum") && (
        <div style={{ display: tab === "momentum" ? undefined : "none" }}><MomentumTab u={u} /></div>
      )}
      {visited.has("sim") && (
        <div style={{ display: tab === "sim" ? undefined : "none" }}><SimulatorTab u={u} /></div>
      )}
      {visited.has("risk") && (
        <div style={{ display: tab === "risk" ? undefined : "none" }}>{data && <RiskTab u={u} mode={mode} />}</div>
      )}
      {visited.has("copilot") && (
        <div style={{ display: tab === "copilot" ? undefined : "none" }}><CopilotTab u={u} mode={mode} /></div>
      )}
      {visited.has("alerts") && (
        <div style={{ display: tab === "alerts" ? undefined : "none" }}><AlertsTab u={u} /></div>
      )}
      {visited.has("more") && (
        <div style={{ display: tab === "more" ? undefined : "none" }}><SettingsTab u={u} /></div>
      )}

      <p className="disclaimer">
        Analytics &amp; education only. Not investment advice. Probabilities are market-implied (risk-neutral).
      </p>
    </div>
  );
}

/* ---------------------------------------------------------------- today */
function Today({ data, mode }: { data: any; mode: Mode }) {
  const { brief, analyze, calibration, event, changed, crush } = data;
  const g = analyze.gex || {}, d = analyze.implied_distribution || {}, oi = analyze.oi || {}, rg = analyze.regime || {};
  const aboveFlip = g.zero_gamma_flip != null && analyze.spot >= g.zero_gamma_flip;
  // Show the score + diagonal from whichever class actually HAS a score (prefer live), so the big
  // number and the headline never disagree.
  const liveB = calibration?.by_class?.live, btB = calibration?.by_class?.backtest;
  const calBlock = liveB?.calibration_score?.score != null ? liveB
    : btB?.calibration_score?.score != null ? btB : (liveB || btB);
  const calLive = calBlock?.calibration_score || {};
  const calCurve = calBlock?.reliability_curve || [];

  return (
    <>
      {brief && (
        <div className="card brief full" style={{ marginBottom: 14 }}>
          <h3>Daily brief — {brief.underlying}</h3>
          {(brief.lines || []).map((l: string, i: number) => (
            <div className="line" key={i} style={i === 0 ? { fontSize: 16, fontWeight: 600 } : undefined}>{l}</div>
          ))}
        </div>
      )}

      <div className="grid">
        <Card q="Where can the index move by expiry?">
          <RangeCone spot={analyze.spot} em={d.expected_move_1sigma} />
          <div className="stats" style={{ marginTop: 10 }}>
            <Stat k="Spot" v={<span className="mono">{fmt(analyze.spot)}</span>} />
            <Stat k="±1σ move" v={<span className="mono">{fmt(d.expected_move_1sigma)}</span>} />
            <Stat k="P(close &gt; spot)" v={<span className="mono">{pct(d.prob_above_spot)}</span>} />
          </div>
          <Learn title="Why probabilities, not targets?">
            The option market prices a whole distribution of outcomes. We read that ±1σ band straight from it —
            it’s where the index lands ~68% of the time by expiry, not a prediction of a single number.
          </Learn>
        </Card>

        <Card q="Is the market pinned or unstable?">
          <div className="row">
            <Traffic level={aboveFlip ? "low" : "high"} label={aboveFlip ? "Positive gamma (pinned)" : "Negative gamma (unstable)"} />
            <span className="pill">{(rg.label || "—").replace(/_/g, " ")}</span>
          </div>
          <div className="stats" style={{ marginTop: 10 }}>
            <Stat k={<Why text="Above this level dealers tend to dampen moves; below it they amplify them.">Zero-gamma flip</Why>} v={<span className="mono">{fmt(g.zero_gamma_flip)}</span>} />
            <Stat k="Total GEX" v={<span className="mono">{fmt(g.total_gex)}</span>} />
          </div>
          {mode === "expert" && (rg.drivers || []).map((x: string, i: number) => (
            <div key={i} className="muted" style={{ fontSize: 12 }}>• {x}</div>
          ))}
        </Card>

        <Card q="How reliable has Anvil been?">
          <div className="row" style={{ alignItems: "flex-start" }}>
            <CalibrationDiagonal curve={calCurve} />
            <div>
              <div className="big mono">{calLive.score != null ? `${calLive.score}/100` : "—"}</div>
              <div className="muted">{calLive.rating || "building"}</div>
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>{calibration?.headline}</div>
            </div>
          </div>
          <Learn title="What does the calibration score mean?">
            When Anvil says 70%, does it happen ~70% of the time? Dots on the diagonal = honest. It only shows a
            score after enough resolved forecasts, and synthetic/demo data never counts.
          </Learn>
        </Card>

        {mode !== "simple" && (
          <Card q="Where are option writers concentrated?">
            <OIWalls oi={oi} />
            <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Max pain {fmt(oi.max_pain)} · PCR(OI) {oi.pcr_oi?.toFixed?.(2) ?? "—"}</div>
          </Card>
        )}

        {mode !== "simple" && (
          <Card q="Is premium expensive or cheap?">
            <div className="stats">
              <Stat k="ATM IV" v={<span className="mono">{pct(d.atm_iv)}</span>} />
              <Stat k="Skew (RR)" v={<span className="mono">{analyze.skew?.risk_reversal != null ? pct(analyze.skew.risk_reversal) : "—"}</span>} />
              {crush && <Stat k="IV-crush" v={<Traffic level={crush.level} label={`${crush.crush_score}`} />} />}
            </div>
            {crush?.warning && <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{crush.warning}</div>}
          </Card>
        )}

        <Card q="What changed since yesterday?">
          {changed?.available ? (
            <>
              <div>{changed.narrative}</div>
              <div className="stats" style={{ marginTop: 8 }}>
                {(changed.changes || []).slice(0, 4).map((c: any, i: number) => (
                  <Stat key={i} k={c.field.replace(/_/g, " ")} v={
                    <span className={"mono " + (c.direction === "up" ? "pill pos" : c.direction === "down" ? "pill neg" : "")}>
                      {c.field === "regime" ? c.to : `${c.direction === "up" ? "▲" : "▼"} ${fmt(c.to, 2)}`}
                    </span>
                  } />
                ))}
              </div>
            </>
          ) : (
            <div className="muted">First observation — the “since yesterday” view fills in once the daily cycle has run.</div>
          )}
        </Card>

        <Card q="How risky is the run into expiry?">
          <div className="row">
            <Traffic level={event?.risk_level} />
            <span className="muted">{fmt(event?.days_to_expiry, 1)} days to expiry</span>
          </div>
          <div className="stats" style={{ marginTop: 10 }}>
            <Stat k="Theta burn" v={<span className="mono">{event?.theta_burn_pct != null ? pct(event.theta_burn_pct) : "—"}</span>} />
            <Stat k="Dist to max-pain" v={<span className="mono">{event?.distance_to_max_pain_pct != null ? pct(event.distance_to_max_pain_pct) : "—"}</span>} />
          </div>
        </Card>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- risk tab */
function RiskTab({ u, mode }: { u: string; mode: Mode }) {
  const [pf, setPf] = useState<any>(null);
  const [scn, setScn] = useState<any>(null);
  const [mc, setMc] = useState<any>(null);
  useEffect(() => {
    api.portfolio().then(setPf).catch(() => setPf({ error: true }));
    api.scenario(u).then(setScn).catch(() => setScn(null));
    api.montecarlo(u).then(setMc).catch(() => setMc(null));
  }, [u]);

  return (
    <div className="grid">
      <Card q="What is my portfolio risk if the market moves?" full>
        {pf && !pf.error ? (
          <div className="stats">
            <Stat k="Net δ" v={<span className="mono">{fmt(pf.net_delta)}</span>} />
            <Stat k="Net γ" v={<span className="mono">{fmt(pf.net_gamma, 3)}</span>} />
            <Stat k="θ / day" v={<span className="mono">{fmt(pf.net_theta)}</span>} />
            <Stat k="Vega / 1%" v={<span className="mono">{fmt(pf.net_vega)}</span>} />
            <Stat k={`β-wtd δ (${pf.benchmark})`} v={<span className="mono">{fmt(pf.beta_weighted_delta)}</span>} />
            <Stat k="≈ lots" v={<span className="mono">{fmt(pf.bwd_lots, 1)}</span>} />
          </div>
        ) : (
          <div className="muted">No positions. Connect Kite/Groww (or the demo book) to see beta-weighted risk.</div>
        )}
      </Card>

      <Card q="If the index moves X% and IV shifts, what happens to my book?" full>
        <ScenarioHeat grid={scn} />
        {scn?.worst && (
          <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            Worst cell: {fmt(scn.worst.pnl)} at {(scn.worst.spot_shock * 100).toFixed(0)}% spot / {(scn.worst.vol_shift * 100).toFixed(0)} vol.
          </div>
        )}
      </Card>

      {mode !== "simple" && (
        <Card q="What’s the full distribution of my P&L? (Monte Carlo)" full>
          {mc?.available && mc?.has_positions ? (
            <>
              <Histogram edges={mc.histogram.edges} counts={mc.histogram.counts} />
              <div className="stats" style={{ marginTop: 10 }}>
                <Stat k="P(profit)" v={<span className="mono">{pct(mc.p_profit)}</span>} />
                <Stat k="Expected P&L" v={<span className="mono">{fmt(mc.expected_pnl)}</span>} />
                <Stat k="VaR 95%" v={<span className="mono">{fmt(mc.var_95)}</span>} />
                <Stat k="CVaR 95%" v={<span className="mono">{fmt(mc.cvar_95)}</span>} />
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{mc.caveat}</div>
            </>
          ) : (
            <div className="muted">Monte Carlo needs an implied distribution + positions.</div>
          )}
        </Card>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- simulator (paper money loop) */
function PaperBadge() {
  return <span className="pill" style={{ background: "#3d2c12", color: "#f0c674", borderColor: "#8b6c2c" }}>PAPER</span>;
}

function Knob({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (v: number) => void }) {
  return (
    <label className="muted" style={{ display: "flex", flexDirection: "column", fontSize: 11, gap: 2 }}>
      {label}
      <input type="number" value={value} step={step} onChange={(e) => onChange(parseFloat(e.target.value) || 0)} style={{ width: 96 }} />
    </label>
  );
}

/* ------------------------------------------------------------------- tips */
function TipCard({ t }: { t: any }) {
  return (
    <div className="alert">
      <div style={{ flex: 1 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div style={{ fontWeight: 600 }}>
            {String(t.structure || "").replace(/_/g, " ")} · <span className="muted">{t.direction}</span>
          </div>
          <span className={"pill " + (t.tier === "headline" ? "pos" : "")}>{pct(t.conviction)} conviction</span>
        </div>
        {t.rationale && <div className="muted" style={{ fontSize: 12 }}>{t.rationale}</div>}
        <div className="stats" style={{ marginTop: 6 }}>
          <Stat k="Cost-adj EV" v={<span className={"mono pill " + ((t.cost_adjusted_ev ?? 0) >= 0 ? "pos" : "neg")}>{fmt(t.cost_adjusted_ev)}</span>} />
          <Stat k="Max loss" v={<span className="mono">{fmt(t.max_loss)}</span>} />
          <Stat k="Max profit" v={<span className="mono">{t.max_profit != null ? fmt(t.max_profit) : "open"}</span>} />
          <Stat k="Horizon" v={<span className="mono">{fmt(t.horizon_days, 1)}d</span>} />
        </div>
        {(t.signals_fired || []).length > 0 && (
          <div className="row" style={{ gap: 4, marginTop: 4, flexWrap: "wrap" }}>
            {t.signals_fired.map((s: string) => <span key={s} className="chip">{s}</span>)}
          </div>
        )}
        <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
          {(t.legs || []).map((l: any) => `${l.side} ${l.lots}× ${l.strike ? l.strike + (l.option_type || "") : l.instrument_type}`).join("   ·   ")}
        </div>
      </div>
    </div>
  );
}

function DecisionBriefCard({ u }: { u: string }) {
  const [b, setB] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    setB(null);
    setErr("");
    api.decisionBrief(u).then(setB).catch((e) =>
      setErr(e instanceof ApiError && e.status === 403 ? "Decision brief disabled (TIPS_ENABLED=false)."
        : "Couldn't load the decision brief."));
  }, [u]);
  const v = b?.verdict;
  const color = v === "FAVORABLE" ? "#3fb950" : v === "ABSTAIN" ? "#f85149" : v === "UNFAVORABLE" ? "#f0883e" : "#8b949e";
  const env = b?.environment || {};
  const vrp = env.vrp || {};
  const reg = env.regime || {};
  const crush = env.crush_window || {};
  return (
    <Card q={`Decision brief — ${u}`} full>
      <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
        Environment-gate → strike-action. The buyer's read: <b>whether to play</b>, then <b>which strike</b>. <PaperBadge /> {b?.disclaimer || "analytics, not edge-proven."}
      </div>
      {err && <div className="muted" style={{ color: "#f0a0a0" }}>{err}</div>}
      {!b && !err && <div className="muted">Loading…</div>}
      {b && (
        <div className="alert" style={{ borderLeft: `3px solid ${color}` }}>
          <div style={{ flex: 1 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div style={{ fontWeight: 700, color }}>{v}</div>
              <span className="muted" style={{ fontSize: 12 }}>spot {fmt(b.spot)} · {b.horizon_days}d horizon · {b.history_days}d history</span>
            </div>
            {b.flip_condition && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>flip → {b.flip_condition}</div>}
            <div className="stats" style={{ marginTop: 6 }}>
              <Stat k="VRP (premium)" v={<span className="mono">{vrp.richness ?? "—"} · P(rich) {vrp.prob_realized_lt_implied != null ? pct(vrp.prob_realized_lt_implied) : "—"}</span>} />
              <Stat k="IV vs E[RV]" v={<span className="mono">{vrp.atm_iv ?? "—"} / {vrp.e_rv ?? "—"}</span>} />
              <Stat k="Regime" v={<span className="mono">{reg.label ?? "—"} ({reg.agree_count ?? 0}/{reg.signals_total ?? 0})</span>} />
              <Stat k="Crush window" v={<span className="muted" style={{ fontSize: 11 }}>{crush.reason ?? "—"}</span>} />
            </div>
          </div>
        </div>
      )}
      {b && b.strikes?.length > 0 && (
        <table className="mono" style={{ marginTop: 12 }}>
          <thead><tr><th>Strike</th><th>Dir</th><th>Dist</th><th>P(touch)</th><th>risk-neutral</th></tr></thead>
          <tbody>
            {b.strikes.map((s: any, i: number) => (
              <tr key={i} style={{ opacity: s.muted ? 0.5 : 1 }}>
                <td>{fmt(s.strike)}</td><td>{s.dir}</td>
                <td>{s.distance_pct > 0 ? "+" : ""}{s.distance_pct}%</td>
                <td className={s.muted ? "" : "pill pos"}>{pct(s.p_touch_phys)}</td>
                <td className="muted">{pct(s.p_touch_rn)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function PredictionCard({ p, u }: { p: any; u: string }) {
  if (!p) return null;
  const conf = Math.round((p.confidence || 0) * 100);
  const dir = String(p.direction || "neutral");
  const arrow = dir === "bullish" ? "▲" : dir === "bearish" ? "▼" : dir.includes("vol") ? "◆" : "▬";
  const dirColor = dir === "bullish" ? "#3fb950" : dir === "bearish" ? "#f85149" : "#8b949e";
  const cal = p.calibration_reference;
  return (
    <div className="alert" style={{ borderLeft: `3px solid ${dirColor}` }}>
      <div style={{ flex: 1 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 700, fontSize: 16 }}>
            <span style={{ color: dirColor }}>{arrow} {dir.replace(/_/g, " ")}</span>
            <span className="muted" style={{ fontSize: 12 }}>{"  ·  "}{u} @ {fmt(p.spot)}</span>
          </div>
          <div className="row" style={{ gap: 8, alignItems: "center" }}>
            <span className="mono" style={{ fontSize: 22, fontWeight: 700 }}>{conf}%</span>
            {p.edge_verified
              ? <span className="pill pos">Edge-verified ✓</span>
              : <span className="pill" title={p.edge_verified_basis ? `tracking n=${p.edge_verified_basis.n ?? 0}` : "tracking"}>tracking</span>}
          </div>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{p.summary}</div>
        <div className="stats" style={{ marginTop: 6 }}>
          <Stat k="Regime" v={<span className="mono">{String(p.regime_bucket || "").replace(/_/g, " ")}</span>} />
          <Stat k="P(above spot)" v={<span className="mono">{p.prob_above != null ? pct(p.prob_above) : "—"}</span>} />
          <Stat k="Exp. move ±1σ" v={<span className="mono">{p.expected_move != null ? fmt(p.expected_move) : "—"}</span>} />
          <Stat k="Confidence basis" v={<span className="muted" style={{ fontSize: 11 }}>{String(p.confidence_basis || "").replace(/_/g, " ")}</span>} />
        </div>
        {cal && (
          <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
            Measured: when we last said ~{pct(cal.predicted_mean)}, it landed {pct(cal.empirical_freq)} of {cal.count} resolved.
          </div>
        )}
      </div>
    </div>
  );
}

function EquityCard({ t, side }: { t: any; side: "BUY" | "SELL" }) {
  const c = side === "BUY" ? "#3fb950" : "#f85149";
  return (
    <div className="alert" style={{ borderLeft: `3px solid ${c}` }}>
      <div style={{ flex: 1 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div style={{ fontWeight: 600 }}><span style={{ color: c }}>{side}</span> {t.underlying}</div>
          <span className={"pill " + (t.tier === "headline" ? "pos" : "")}>{pct(t.conviction)}{t.tier === "headline" ? " ✓" : ""}</span>
        </div>
        <div className="stats" style={{ marginTop: 4 }}>
          <Stat k="Target" v={<span className="mono">{fmt(t.target)}</span>} />
          <Stat k="Stop" v={<span className="mono">{fmt(t.stop)}</span>} />
          <Stat k="Horizon" v={<span className="mono">{fmt(t.horizon_days, 0)}d</span>} />
        </div>
      </div>
    </div>
  );
}

function TipsTab({ u }: { u: string }) {
  const [tips, setTips] = useState<any>(null);
  const [eq, setEq] = useState<any>(null);
  const [tr, setTr] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setTips(null);
    setErr("");
    api.tips(u).then(setTips).catch((e) =>
      setErr(e instanceof ApiError && e.status === 403
        ? "Tips are disabled on this instance (TIPS_ENABLED=false)."
        : "Couldn't load tips."));
    api.tipsEquities().then(setEq).catch(() => setEq(null));
    api.tipsTrackRecord().then(setTr).catch(() => setTr(null));
  }, [u]);

  const pred = tips?.prediction;
  const headline = tips?.headline || [];
  const watchlist = tips?.watchlist || [];
  const payoffTip = pred?.actionable_tip || headline[0] || watchlist[0] || null;
  const buys = eq?.buys || [];
  const sells = eq?.sells || [];
  const live = tr?.by_class?.tip_live;
  const bt = tr?.by_class?.tip_backtest;
  const liveCurve = live?.reliability_curve || [];
  const btCurve = bt?.reliability_curve || [];
  const liveScore = live?.calibration_score;
  const cells = (tr?.cells || []).filter((c: any) => (c.n ?? 0) > 0).sort((a: any, b: any) => (b.n ?? 0) - (a.n ?? 0));

  return (
    <div className="grid">
      <DecisionBriefCard u={u} />

      <Card q={`Live prediction — ${u}`} full>
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          The engine's best current read, always shown. Confidence is a calibrated probability (not a promise);
          the <b>Edge-verified ✓</b> badge appears only once a structure's edge is MEASURED out-of-sample, after costs. <PaperBadge /> not advice.
        </div>
        {err && <div className="muted" style={{ color: "#f0a0a0" }}>{err}</div>}
        {!tips && !err && <div className="muted">Loading prediction…</div>}
        {pred && <PredictionCard p={pred} u={u} />}
      </Card>

      {pred && (
        <Card q="Why — factors & expected range" full>
          <div className="row" style={{ gap: 16, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div style={{ flex: "1 1 280px", minWidth: 260 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Signals firing (STRONG green · confirmation blue · masked dimmed)</div>
              <FactorBars factors={pred.factors || []} />
            </div>
            <div style={{ flex: "1 1 280px", minWidth: 260 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Market-implied expected range (±1σ / ±2σ)</div>
              <RangeCone spot={pred.spot} em={pred.expected_move} />
            </div>
          </div>
        </Card>
      )}

      {payoffTip && (
        <Card q={`Trade structure — ${String(payoffTip.structure || "").replace(/_/g, " ")}`} full>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
            Held-to-horizon payoff (the same math used to resolve the tip). Orange = spot; shaded = profit/loss zones.
          </div>
          <PayoffDiagram legs={payoffTip.legs} lotSize={payoffTip.lot_size} spot={tips?.spot || pred?.spot} breakevens={payoffTip.breakevens} />
          <TipCard t={payoffTip} />
        </Card>
      )}

      <Card q="Stock tips — cross-sectional BUY / SELL" full>
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Single-stock directional calls, ranked across the F&O universe (momentum + OI buildup). EOD/swing horizon, after costs.
          {eq?.as_of ? <span className="muted"> · as of {String(eq.as_of).slice(0, 10)}</span> : null}
        </div>
        {!eq && <div className="muted">Loading stock tips…</div>}
        {eq && buys.length === 0 && sells.length === 0 && (
          <div className="muted">No stock tips yet — run <span className="mono">anvil tips run-eod --equities</span> to populate.</div>
        )}
        <div className="row" style={{ gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 280px", minWidth: 260 }}>
            <div style={{ fontWeight: 600, color: "#3fb950", marginBottom: 4 }}>BUY</div>
            {buys.length === 0 && <div className="muted" style={{ fontSize: 12 }}>—</div>}
            {buys.map((t: any, i: number) => <EquityCard key={i} t={t} side="BUY" />)}
          </div>
          <div style={{ flex: "1 1 280px", minWidth: 260 }}>
            <div style={{ fontWeight: 600, color: "#f85149", marginBottom: 4 }}>SELL</div>
            {sells.length === 0 && <div className="muted" style={{ fontSize: 12 }}>—</div>}
            {sells.map((t: any, i: number) => <EquityCard key={i} t={t} side="SELL" />)}
          </div>
        </div>
      </Card>

      <Card q={`Edge-proven tips — ${u}`} full>
        <div className="muted" style={{ fontSize: 12 }}>
          Index-option structures whose (structure, regime) cell has MEASURED, post-cost, out-of-sample edge.
          An empty headline is the honest default — the engine stays quiet rather than manufacture a call.
        </div>
        {tips && headline.length === 0 && (
          <div className="muted" style={{ marginTop: 8 }}>No edge-proven tips right now — see the live prediction, the stock tips, and the track record.</div>
        )}
        {headline.map((t: any, i: number) => <TipCard key={i} t={t} />)}
      </Card>

      <Card q="Watchlist — developing signals" full>
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Tradeable structures whose edge isn't yet measured-and-proven. Clearly separated from the headline feed — watch, don't headline-bet them.
        </div>
        {tips && watchlist.length === 0 && <div className="muted">Nothing on the watchlist.</div>}
        {watchlist.map((t: any, i: number) => <TipCard key={i} t={t} />)}
      </Card>

      <Card q="Tip track record — accuracy measured, not claimed" full>
        <div className="muted" style={{ fontSize: 12 }}>
          When a tip states a conviction, does it land that often — after costs? Below: out-of-sample (backtest) and forward/live curves.
          This is the only place an accuracy number appears, and it is measured.
        </div>
        <div className="stats" style={{ marginTop: 8 }}>
          <Stat k="Live resolved" v={<span className="mono">{live?.resolved_count ?? 0}</span>} />
          <Stat k="Live calibration" v={<span className="mono">{liveScore?.score ?? "—"}{liveScore?.rating ? ` · ${liveScore.rating}` : ""}</span>} />
          <Stat k="Backtest resolved" v={<span className="mono">{bt?.resolved_count ?? 0}</span>} />
          <Stat k="Backtest Brier" v={<span className="mono">{bt?.brier ?? "—"}</span>} />
        </div>
        {(liveCurve.length > 0 || btCurve.length > 0) && (
          <div className="row" style={{ gap: 16, marginTop: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Reliability (predicted vs actual)</div>
              <CalibrationDiagonal curve={liveCurve.length ? liveCurve : btCurve} />
            </div>
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Risk-coverage (selective accuracy)</div>
              <RiskCoverageCurve curve={liveCurve.length ? liveCurve : btCurve} />
            </div>
          </div>
        )}
        {liveScore?.reading && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>{liveScore.reading}</div>}
        {cells.length > 0 && (
          <table className="mono" style={{ marginTop: 12 }}>
            <thead><tr><th>Structure</th><th>Regime</th><th>n</th><th>Win-rate</th><th>t</th><th>DSR</th><th>Headline?</th></tr></thead>
            <tbody>
              {cells.slice(0, 20).map((c: any, i: number) => (
                <tr key={i}>
                  <td>{String(c.structure).replace(/_/g, " ")}</td><td>{c.regime_bucket}</td><td>{c.n}</td>
                  <td>{c.win_rate != null ? pct(c.win_rate) : "—"}</td><td>{c.t_stat ?? "—"}</td><td>{c.dsr ?? "—"}</td>
                  <td><span className={"pill " + (c.headline_eligible ? "pos" : "")}>{c.headline_eligible ? "yes" : "no"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

/* ---------------------------------------------------------------- cockpit header (Wave 0) */
// Live heartbeat chip cluster in the topbar: configured source (DEMO/LIVE), whether the go-live
// supervisor is running, the Gate-0 / personal-mode state, and how fresh the recorded snapshot is.
// Consumes /api/cockpit/status; polls every 30s. Silent (renders nothing) until the first read lands
// or if the endpoint is unavailable, so a plain `anvil serve` (no supervisor) degrades cleanly.
function CockpitHeader() {
  const [s, setS] = useState<any>(null);
  const [, setNow] = useState(0);
  useEffect(() => {
    let live = true;
    const tick = () => api.cockpitStatus().then((r) => live && setS(r)).catch(() => {});
    tick();
    const poll = setInterval(tick, 30000);
    // Re-render every 15s so the "updated Xs ago" freshness label keeps counting up between polls.
    const clock = setInterval(() => live && setNow((n) => n + 1), 15000);
    return () => { live = false; clearInterval(poll); clearInterval(clock); };
  }, []);
  if (!s) return null;
  const src = String(s.source || "").toLowerCase();
  const isDemo = src === "demo" || src === "seed" || !src;
  const age = (() => {
    if (!s.freshest_snapshot_ts) return null;
    const t = Date.parse(s.freshest_snapshot_ts);
    if (Number.isNaN(t)) return null;
    const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
    return secs < 90 ? `${secs}s ago` : secs < 5400 ? `${Math.round(secs / 60)}m ago` : `${Math.round(secs / 3600)}h ago`;
  })();
  const livePill = { background: "#10231a", color: "#9be6b8", borderColor: "#2c6e49" } as const;
  return (
    <div className="row" style={{ gap: 6, alignItems: "center", fontSize: 12 }}>
      <span className="pill" style={isDemo ? undefined : livePill} title={s.build?.hash ? `build ${s.build.hash}` : "data source"}>
        {isDemo ? "DEMO" : "LIVE"}{src ? ` · ${src}` : ""}
      </span>
      {s.supervisor_running && <span className="pill pos" title="go-live cockpit supervisor is running">● cockpit</span>}
      <span className={"pill " + (s.gate0_passed ? "pos" : "")} title={s.gate0_passed ? "Gate-0 certified — sized tips can arm" : "Gate-0 not passed — analytics only"}>
        {s.gate0_passed ? "gate ✓" : "gate –"}
      </span>
      {s.personal_mode_armed && <span className="pill pos" title="personal mode armed">armed</span>}
      {age && <span className="muted" title="freshest recorded snapshot">upd {age}</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- momentum (Wave 2) */
// Multi-timeframe + options-flow momentum surface, consuming /api/momentum/{u}. Shows the consensus
// MomentumRead (direction + net agreement across timeframes — never an accuracy %), the per-timeframe
// votes, the options-flow velocity (OI / dealer-γ / IV-rank / term), the fired momentum factors, and the
// honestly-gated prediction (reusing the same PredictionCard/FactorBars the Tips tab uses, so it can
// never drift from how tips are computed). Analytics only — momentum is agreement/velocity, not advice.
function MomentumTab({ u }: { u: string }) {
  const [m, setM] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    setM(null);
    setErr("");
    api.momentum(u).then(setM).catch((e) =>
      setErr(e instanceof ApiError && e.status === 403
        ? "Momentum is disabled on this instance (TIPS_ENABLED=false)."
        : "Couldn't load momentum."));
  }, [u]);

  const mom = m?.momentum;
  const flow = m?.flow;
  const pred = m?.prediction;
  const perTf: Record<string, any> = mom?.per_tf || {};
  const dirColor = (d?: string) => d === "bullish" ? "#3fb950" : d === "bearish" ? "#f85149" : "#8b949e";
  const arrow = (d?: string) => d === "bullish" ? "▲" : d === "bearish" ? "▼" : "▬";

  return (
    <div className="grid">
      <Card q={`Multi-timeframe momentum — ${u}`} full>
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Vol-normalized trend <b>agreement</b> across timeframes (minutes → weeks), fused with options-flow
          velocity. An agreement/velocity read, never an accuracy %. <PaperBadge /> analytics only.
        </div>
        {err && <div className="muted" style={{ color: "#f0a0a0" }}>{err}</div>}
        {!m && !err && <div className="muted">Loading momentum…</div>}
        {m && (
          <>
            {!m.has_series && (
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                Limited bar history — momentum fills in as the candle cache / recorder accrues series.
              </div>
            )}
            <div className="row" style={{ gap: 14, flexWrap: "wrap", alignItems: "center" }}>
              <div style={{ fontWeight: 700, fontSize: 18, color: dirColor(mom?.direction) }}>
                {arrow(mom?.direction)} {String(mom?.direction || "neutral").replace(/_/g, " ")}
              </div>
              <span className="pill">{mom?.agreement ?? 0} net agreement</span>
              <span className="muted">{mom?.n_timeframes ?? 0} timeframes voting</span>
              <span className="muted">strength {mom?.strength != null ? pct(mom.strength) : "—"}</span>
              {flow?.flip && <span className="pill" style={{ background: "#3d2c12", color: "#f0c674", borderColor: "#8b6c2c" }}>γ-flip</span>}
              <span className="muted" style={{ fontSize: 11 }}>{(m.timeframes || []).join(" · ")}</span>
            </div>
            {mom?.note && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>{mom.note}</div>}
            {Object.keys(perTf).length > 0 && (
              <table className="mono" style={{ marginTop: 12 }}>
                <thead><tr><th>Timeframe</th><th>Vote</th><th>Trend score</th><th>RoC</th></tr></thead>
                <tbody>
                  {Object.entries(perTf).map(([tf, v]: [string, any]) => (
                    <tr key={tf}>
                      <td>{tf}</td>
                      <td style={{ color: dirColor(v?.vote) }}>{v?.vote ?? "—"}</td>
                      <td>{v?.score != null ? fmt(v.score, 2) : "—"}</td>
                      <td>{v?.roc != null ? pct(v.roc) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </Card>

      {flow && (
        <Card q="Options-flow velocity — how the chain is moving" full>
          <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
            Velocity of the recorded option chain — OI buildup, dealer-gamma, IV-rank, and term structure.
            Premium read: <b>{String(flow.vol_direction || "neutral").replace(/_/g, " ")}</b>.
          </div>
          <div className="stats">
            <Stat k="OI velocity" v={<span className="mono">{flow.oi ? (flow.oi.building ? "building" : "unwinding") : "—"}{flow.oi?.change != null ? ` · ${pct(flow.oi.change)}` : ""}</span>} />
            <Stat k="Dealer-γ" v={<span className="mono">{flow.gex ? (flow.gex.now_negative_gamma ? "negative" : "positive") : "—"}{flow.gex?.flip ? " · FLIP" : ""}</span>} />
            <Stat k="IV-rank vel" v={<span className="mono">{flow.iv_rank?.direction ? String(flow.iv_rank.direction).replace(/_/g, " ") : "—"}</span>} />
            <Stat k="Term vel" v={<span className="mono">{flow.term?.direction ? String(flow.term.direction).replace(/_/g, " ") : "—"}</span>} />
          </div>
          {(flow.notes || []).length > 0 && (
            <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{flow.notes.join("  ·  ")}</div>
          )}
        </Card>
      )}

      {pred && (
        <Card q={`Momentum-fused prediction — ${u}`} full>
          <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
            The honestly-gated prediction with momentum + flow factors folded into conviction (same spine as Tips).
          </div>
          <PredictionCard p={pred} u={u} />
          {(pred.factors || []).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Signals firing (STRONG green · confirmation blue · masked dimmed)</div>
              <FactorBars factors={pred.factors} />
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function SimulatorTab({ u }: { u: string }) {
  const sim = useSimStore();
  const [account, setAccount] = useState<any>(null);
  const [recs, setRecs] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [acctErr, setAcctErr] = useState("");
  const [cfg, setCfg] = useState<any>({
    capital: 1000000, risk_fraction: 0.05, kelly_fraction: 0.55, max_exposure_pct: 0.4,
    min_conviction: 0.55, seller_mode: true, cadence_s: 60, force_open: false,
  });

  async function load() {
    setAcctErr("");
    try {
      setAccount((await api.paperAccount()).account);
    } catch (e) {
      setAcctErr(e instanceof ApiError && e.status === 403
        ? "Paper trading is disabled on this instance (PAPER_TRADING=false)."
        : "Couldn't load the paper account.");
      return;
    }
    api.paperRecommendations(u).then(setRecs).catch(() => setRecs(null));
    api.paperRuns().then((r) => setRuns(r || [])).catch(() => setRuns([]));
  }
  useEffect(() => { load(); simStore.rehydrateLatest(); }, [u]);
  // Refresh the runs list + account when a run finishes (sim.runId flips).
  useEffect(() => { if (sim.runId) load(); }, [sim.runId]);

  const { mode, running, report, curve } = sim;
  const scorecard = sim.scorecard ? (sim.scorecard[u] || Object.values(sim.scorecard)[0]) : null;
  const traded = (recs?.candidates || []).filter((c: any) => c.action === "trade");
  const s = report?.summary, t = report?.trades, r = report?.risk;
  const by = report?.attribution?.by_strategy || {};

  return (
    <div className="grid">
      <Card q="Personal money-making simulator" full>
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <div className="row"><PaperBadge /> <span className="muted">Recommend → mock-buy → manage → measure. Research, not advice.</span></div>
          <div className="row" style={{ gap: 8 }}>
            <div className="seg">
              {(["today", "replay", "live"] as SimMode[]).map((m) => (
                <button key={m} className={mode === m ? "on" : ""} onClick={() => simStore.setMode(m)}>
                  {m === "today" ? "Today (real day)" : m === "live" ? "Live" : "Replay"}
                </button>
              ))}
            </div>
            {sim.live ? (
              <button className="btn" style={{ borderColor: "#8b2c2c", color: "#f0a0a0" }} onClick={() => simStore.stop()}>■ Stop live</button>
            ) : (
              <button className="btn" disabled={running} onClick={() => simStore.start(u, mode, { ...cfg })}>
                {running ? "Running…" : mode === "today" ? `Run today (${u})` : mode === "live" ? `Go live (${u})` : `Run mock session (${u})`}
              </button>
            )}
          </div>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          {mode === "today"
            ? "Reconstructs today's REAL intraday day from live candles, runs the strategy, and grades its predictions vs the real close. Runs server-side — switching tabs won't stop it."
            : mode === "live"
            ? "Runs with the LIVE market (09:15–15:30 IST), streaming each tick here. Keeps running on the server even if you switch tabs or close this page — press Stop to end it."
            : "Deterministic synthetic replay (seeded), zero keys — demonstrates the strategy's expected behavior."}
        </div>
        {(sim.live || sim.note) && (
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            {sim.live ? <span className="pill pos">● LIVE · {curve.length} ticks</span> : null}
            {sim.note ? <span style={{ marginLeft: 8 }}>{sim.note}</span> : null}
          </div>
        )}
        {mode === "live" && !sim.live && (
          <label className="muted" style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, marginTop: 6 }}>
            <input type="checkbox" checked={!!cfg.force_open} onChange={(e) => setCfg({ ...cfg, force_open: e.target.checked })} />
            demo off-hours (tick on the current chain even when the market is closed)
          </label>
        )}
        <div className="row" style={{ gap: 10, marginTop: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Knob label="Capital ₹" value={cfg.capital} step={100000} onChange={(v) => setCfg({ ...cfg, capital: v })} />
          <Knob label="Risk %/trade" value={Math.round(cfg.risk_fraction * 100)} step={1} onChange={(v) => setCfg({ ...cfg, risk_fraction: v / 100 })} />
          <Knob label="Kelly frac" value={cfg.kelly_fraction} step={0.05} onChange={(v) => setCfg({ ...cfg, kelly_fraction: v })} />
          <Knob label="Max expo %" value={Math.round(cfg.max_exposure_pct * 100)} step={5} onChange={(v) => setCfg({ ...cfg, max_exposure_pct: v / 100 })} />
          <Knob label="Min conviction" value={cfg.min_conviction} step={0.05} onChange={(v) => setCfg({ ...cfg, min_conviction: v })} />
          <label className="muted" style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
            <input type="checkbox" checked={cfg.seller_mode} onChange={(e) => setCfg({ ...cfg, seller_mode: e.target.checked })} /> seller mode
          </label>
        </div>
        {account && (
          <div className="stats" style={{ marginTop: 10 }}>
            <Stat k="Capital" v={<span className="mono">{fmt(account.starting_capital)}</span>} />
            <Stat k="Cash" v={<span className="mono">{fmt(account.cash)}</span>} />
            <Stat k="Realized P&L" v={<span className="mono">{fmt(account.realized_pnl)}</span>} />
          </div>
        )}
        {sim.err && <div className="muted" style={{ color: "#f0a0a0", marginTop: 8 }}>{sim.err}</div>}
        {acctErr && <div className="muted" style={{ color: "#f0a0a0", marginTop: 8 }}>{acctErr}</div>}
      </Card>

      {mode === "today" && scorecard && (
        <Card q="How good were today's predictions?" full>
          <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
            Predicted at the open from the market-implied distribution; graded against the real close. {scorecard.smile}
          </div>
          <div className="stats">
            <Stat k="Open" v={<span className="mono">{fmt(scorecard.open)}</span>} />
            <Stat k="Predicted ±1σ" v={<span className="mono">{fmt(scorecard.band_1sigma?.[0])}–{fmt(scorecard.band_1sigma?.[1])}</span>} />
            <Stat k="Real close" v={<span className="mono">{fmt(scorecard.realized_close)}</span>} />
            <Stat k="Move" v={<span className={"mono pill " + ((scorecard.move ?? 0) >= 0 ? "pos" : "neg")}>{fmt(scorecard.move)}</span>} />
            <Stat k="In ±1σ?" v={<span className={"pill " + (scorecard.hits?.in_1sigma ? "pos" : "neg")}>{scorecard.hits?.in_1sigma ? "yes" : "no"}</span>} />
            <Stat k="Direction" v={<span className={"pill " + (scorecard.hits?.above_open ? "pos" : "neg")}>{scorecard.hits?.above_open ? "up" : "down"}</span>} />
            <Stat k="Brier" v={<span className="mono">{scorecard.brier}</span>} />
          </div>
        </Card>
      )}

      {report && s && (
        <Card q="How effective was the run?" full>
          <div className="stats">
            <Stat k="Net P&L" v={<span className={"mono pill " + (s.net_pnl >= 0 ? "pos" : "neg")}>{fmt(s.net_pnl)}</span>} />
            <Stat k="Return" v={<span className="mono">{fmt(s.return_pct, 2)}%</span>} />
            <Stat k="Trades" v={<span className="mono">{t.n_total}</span>} />
            <Stat k="Win-rate" v={<span className="mono">{t.win_rate != null ? pct(t.win_rate) : "—"}</span>} />
            <Stat k="Profit factor" v={<span className="mono">{t.profit_factor ?? "—"}</span>} />
            <Stat k="Sharpe" v={<span className="mono">{r.sharpe_annualized ?? "—"}</span>} />
            <Stat k="Max DD" v={<span className="mono">{pct(r.max_drawdown)}</span>} />
          </div>
          <div style={{ marginTop: 12 }}><EquityCurve points={curve} start={s.starting_capital} /></div>
          {Object.keys(by).length > 0 && (
            <table className="mono" style={{ marginTop: 12 }}>
              <thead><tr><th>Strategy</th><th>n</th><th>Net P&amp;L</th><th>Win-rate</th></tr></thead>
              <tbody>
                {Object.entries(by).map(([name, b]: [string, any]) => (
                  <tr key={name}>
                    <td>{name.replace(/_/g, " ")}</td><td>{b.n}</td>
                    <td className={b.net_pnl >= 0 ? "pos" : "neg"}>{fmt(b.net_pnl)}</td><td>{pct(b.win_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{report.caveat}</div>
        </Card>
      )}

      <Card q={`Today's ranked trade ideas — ${u}`} full>
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Market-implied edge, defined-risk &amp; seller-mode structures, sized to your aggressive profile. <PaperBadge /> simulation only.
        </div>
        {!recs && !acctErr && <div className="muted">Loading recommendations…</div>}
        {recs && traded.length === 0 && <div className="muted">No high-conviction trades right now — “no-trade” is a valid call.</div>}
        {traded.map((c: any, i: number) => (
          <div className="alert" key={i}>
            <div style={{ flex: 1 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 600 }}>{c.strategy.replace(/_/g, " ")} · <span className="muted">{c.direction}</span></div>
                <span className="pill pos">{pct(c.conviction)} conviction</span>
              </div>
              <div className="muted" style={{ fontSize: 12 }}>{c.entry_reason}</div>
              <div className="stats" style={{ marginTop: 6 }}>
                <Stat k="Max loss" v={<span className="mono">{fmt(c.max_loss)}</span>} />
                <Stat k="Max profit" v={<span className="mono">{c.max_profit != null ? fmt(c.max_profit) : "open"}</span>} />
                <Stat k="EV" v={<span className="mono">{fmt(c.expected_value)}</span>} />
                <Stat k="Units" v={<span className="mono">{c.units}</span>} />
              </div>
              <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                {(c.legs || []).map((l: any) => `${l.side} ${l.lots}× ${l.strike ? l.strike + (l.option_type || "") : l.instrument_type}`).join("   ·   ")}
              </div>
            </div>
          </div>
        ))}
      </Card>

      {runs.length > 0 && (
        <Card q="Recent runs — compare" full>
          <table className="mono">
            <thead><tr><th>#</th><th>mode</th><th>status</th><th>Net P&amp;L</th><th>Return</th><th>Max DD</th></tr></thead>
            <tbody>
              {[...runs].sort((a, b) => (b.id ?? 0) - (a.id ?? 0)).slice(0, 8).map((rn: any) => (
                <tr key={rn.id}>
                  <td>{rn.id}</td><td>{rn.mode}</td><td>{rn.status}</td>
                  <td className={(rn.stats?.net_pnl ?? 0) >= 0 ? "pos" : "neg"}>{fmt(rn.stats?.net_pnl)}</td>
                  <td>{rn.stats?.return_pct != null ? rn.stats.return_pct + "%" : "—"}</td>
                  <td>{rn.stats?.max_drawdown != null ? pct(rn.stats.max_drawdown) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- copilot */
function CopilotTab({ u, mode }: { u: string; mode: Mode }) {
  const [msgs, setMsgs] = useState<{ me?: boolean; text: string }[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.copilotNarrate(u, mode).then((r) => setMsgs([{ text: r.answer }])).catch(() => {});
  }, [u, mode]);

  async function ask() {
    if (!q.trim()) return;
    const question = q;
    setQ("");
    setMsgs((m) => [...m, { me: true, text: question }]);
    setBusy(true);
    try {
      const r = await api.copilotAsk(u, question, mode);
      setMsgs((m) => [...m, { text: r.answer }]);
    } finally {
      setBusy(false);
    }
  }

  const prompts = ["Explain today simply", "What is the biggest risk right now?", "Why did the expected range change?", "What does positive gamma mean here?"];
  return (
    <Card q={`Copilot — grounded in ${u}’s engine numbers`} full>
      <div className="chat">
        {msgs.map((m, i) => <div key={i} className={"bubble" + (m.me ? " me" : "")}>{m.text}</div>)}
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        {prompts.map((p) => <button key={p} className="chip" onClick={() => setQ(p)}>{p}</button>)}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about today’s setup…"
          onKeyDown={(e) => e.key === "Enter" && ask()} />
        <button className="btn" disabled={busy} onClick={ask}>Ask</button>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        The copilot only cites engine numbers and never gives buy/sell calls or price targets.
      </div>
    </Card>
  );
}

/* ---------------------------------------------------------------- alerts */
function AlertsTab({ u }: { u: string }) {
  const [rules, setRules] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [kind, setKind] = useState("gex_flip_cross");

  async function load() {
    setRules(await api.alerts().catch(() => []));
    setEvents(await api.alertEvents().catch(() => []));
  }
  useEffect(() => { load(); }, []);

  async function add() {
    await api.createAlert({ underlying: u, kind, params: kind === "price_band" ? { lower: 0, upper: 999999 } : {} });
    load();
  }
  async function evaluate() {
    await api.evaluateAlerts(u);
    load();
  }

  const KINDS = ["gex_flip_cross", "oi_wall_break", "iv_crush", "event_risk", "unusual_activity", "pcr_threshold", "price_band"];
  return (
    <div className="grid">
      <Card q="Natural-language alerts" full>
        <div className="row">
          <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: 220 }}>
            {KINDS.map((k) => <option key={k}>{k}</option>)}
          </select>
          <button className="btn" onClick={add}>Add for {u}</button>
          <button className="btn ghost" onClick={evaluate}>Evaluate now</button>
        </div>
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>Underlying</th><th>Rule</th><th></th></tr></thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td>{r.underlying}</td><td>{r.kind}</td>
                <td><button className="chip" onClick={async () => { await api.deleteAlert(r.id); load(); }}>delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card q="Alert feed" full>
        {events.length === 0 && <div className="muted">No alerts yet. Add a rule and hit “Evaluate now”.</div>}
        {events.map((e) => (
          <div className="alert" key={e.id}>
            <span className={"sev " + e.severity} />
            <div>
              <div style={{ fontWeight: 600 }}>{e.title}</div>
              <div className="muted" style={{ fontSize: 13 }}>{e.body}</div>
              <div className="muted" style={{ fontSize: 11 }}>{e.fired_at ? new Date(e.fired_at).toLocaleString("en-IN") : ""}</div>
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

/* ---------------------------------------------------------------- settings / more */
/* ------------------------------------------------ trust / methodology panel */
// Read-only substantiation of the "accurate when it speaks" brand: the LIVE reliability curve,
// accuracy-at-coverage, coverage %, the mandatory tail scorecard, the VRP prior, and the honest gate
// state (sized tips stay DARK until Gate-0 certifies). Composes existing endpoints only —
// /api/calibration + /api/tips/trust-dial. Display-only; never influences emission. Full narrative:
// docs/METHODOLOGY.md.
function MethodologyPanel() {
  const [cal, setCal] = useState<any>(null);
  const [dial, setDial] = useState<any>(null);
  const [dialErr, setDialErr] = useState<string | null>(null);

  useEffect(() => {
    api.calibration().then(setCal).catch(() => {});
    api.trustDial().then(setDial).catch((e) => setDialErr(e instanceof ApiError ? e.message : "trust dial unavailable"));
  }, []);

  const liveB = cal?.by_class?.live, btB = cal?.by_class?.backtest;
  const calBlock = liveB?.calibration_score?.score != null ? liveB
    : btB?.calibration_score?.score != null ? btB : (liveB || btB);
  const score = calBlock?.calibration_score || {};
  const curve = calBlock?.reliability_curve || [];

  const gate = dial?.gate || {};
  const passed = !!gate.gate0_passed;
  const cov = dial?.coverage || {};
  const sc = dial?.scorecard || {};
  const op = dial?.accuracy_at_coverage || {};
  const vrp = dial?.vrp_prior;

  const asPct = (v: any) =>
    v == null || Number.isNaN(v) ? "—" : (Math.abs(v) <= 1 ? (v * 100).toFixed(1) : Number(v).toFixed(1)) + "%";
  const inr = (v: any) => (v == null || Number.isNaN(v) ? "—" : "₹" + fmt(v));
  const statGrid = { display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 8 } as const;

  return (
    <>
      <Card q={"How Anvil earns the word “accurate”"} full>
        <div className="muted" style={{ fontSize: 13 }}>
          Anvil is <b>accurate when it speaks</b>: on the ~10–20% of opportunities it is confident enough
          to call, the honest target is <b>~62–68% (stretch 70–80%)</b> — and it <b>abstains</b> on the
          rest. The proof is the <b>live reliability curve</b> below (“when we say 70%, does it happen
          ~70%?”), not a number we assert. Raw all-trades direction is only ~50–55%, and we do not claim
          otherwise. The goal is operator P&amp;L — sizing the few good calls well, not call volume.
        </div>
        <Learn title="Why a conditional accuracy number is the honest one">
          Unconditional 70–80% directional accuracy on a liquid index is not real (leakage,
          multiple-testing, or rule-recovery). Selective abstention buys accuracy by sacrificing
          coverage, so Anvil reports accuracy <i>with</i> its coverage, on a public reliability curve. A
          cell may only headline (“Edge-verified ✓”) after clearing the full battery: day-blocked n,
          Deflated Sharpe ≥ 0.95, PBO ≤ 0.5, Harvey t ≥ 3, out-of-fold edge (purged + CPCV). Full method
          in docs/METHODOLOGY.md.
        </Learn>
      </Card>

      <Card q="Are sized tips live yet?">
        <div className="row" style={{ gap: 8, alignItems: "center" }}>
          <span className={"pill " + (passed ? "pos" : "")}>{passed ? "Gate-0 certified" : "Sized tips: DARK"}</span>
          <span className="muted" style={{ fontSize: 12 }}>
            {passed
              ? "A validation cell cleared Harvey t ≥ 3 — sized personal tips can arm (owner-only)."
              : "No cell has cleared Harvey t ≥ 3 yet, so sized/actionable tips stay silent for everyone — analytics only. The wall auto-arms the moment the edge certifies, with no code change."}
          </span>
        </div>
        <div className="muted mono" style={{ fontSize: 11, marginTop: 6 }}>
          personal_mode={String(!!gate.personal_mode)} · armed={String(!!gate.armed)} · gate0_passed={String(passed)}
        </div>
      </Card>

      <Card q="How reliable has Anvil been? (calibration)">
        <div className="row" style={{ alignItems: "flex-start", gap: 14 }}>
          <CalibrationDiagonal curve={curve} />
          <div>
            <div className="big mono">{score.score != null ? `${score.score}/100` : "—"}</div>
            <div className="muted">{score.rating || "building (insufficient resolved forecasts)"}</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              Calibration Score = 100 × (1 − calibration error). Synthetic/demo data never counts; a score
              only shows past n ≥ 50 resolved forecasts.
            </div>
          </div>
        </div>
      </Card>

      <Card q="Accuracy vs. how often we speak">
        <div className="row" style={{ alignItems: "flex-start", gap: 14 }}>
          <RiskCoverageCurve curve={curve} />
          <div style={{ display: "grid", gap: 6 }}>
            <Stat k="coverage (20d)" v={asPct(cov.coverage_pct)} />
            <Stat k="actionable share" v={asPct(cov.actionable_pct)} />
            <Stat
              k="operating point"
              v={op.win_rate != null ? `${asPct(op.win_rate)} @ t=${fmt(op.t_stat, 2)}` : op.status || "accruing"}
            />
          </div>
        </div>
      </Card>

      <Card q="Resolved-tip scorecard (the tail is shown, never win-rate alone)">
        {sc.n > 0 ? (
          <div style={statGrid}>
            <Stat k="resolved" v={fmt(sc.n)} />
            <Stat k="win-rate" v={asPct(sc.win_rate)} />
            <Stat k="total P&L" v={inr(sc.total_pnl_inr)} />
            <Stat k="max drawdown" v={inr(sc.max_drawdown_inr)} />
            <Stat k="CVaR 5%" v={inr(sc.cvar_5pct_inr)} />
            <Stat k="worst trade" v={inr(sc.worst_trade_inr)} />
            <Stat k="Sharpe" v={fmt(sc.sharpe, 2)} />
            <Stat k="Sortino" v={fmt(sc.sortino, 2)} />
            <Stat k="Calmar" v={fmt(sc.calmar, 2)} />
          </div>
        ) : (
          <div className="muted" style={{ fontSize: 13 }}>
            No resolved live tips yet — the scorecard accrues forward as the moat clock resolves tips at
            their close. Win-rate is never shown without its tail (maxDD, CVaR5%, worst trade).
          </div>
        )}
      </Card>

      {vrp && (
        <Card q="VRP edge prior (a prior — NOT a track record)">
          <div style={statGrid}>
            <Stat k="win-rate" v={asPct(vrp.win_rate)} />
            <Stat
              k="annualized"
              v={vrp.annualized_return_pct != null ? Number(vrp.annualized_return_pct).toFixed(1) + "%" : "—"}
            />
            <Stat k="Sharpe" v={fmt(vrp.sharpe, 2)} />
            <Stat
              k="max drawdown"
              v={vrp.max_drawdown_pct != null ? Number(vrp.max_drawdown_pct).toFixed(1) + "%" : "—"}
            />
            <Stat k="CVaR 5%" v={inr(vrp.cvar_5pct_inr)} />
            <Stat k="worst day" v={inr(vrp.worst_day_inr)} />
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            {vrp.note || "prior, NOT a track record"} — a parameter-free, causal proxy (sell the
            India-VIX-priced 1-day ATM straddle vs. the realized move). It is short-vol: it sells
            insurance, so the left tail is real and must be survived, not averaged away.
          </div>
        </Card>
      )}

      <Card q="The honest small print">
        <div className="muted" style={{ fontSize: 12 }}>
          Analytics &amp; education only — not investment advice. Probabilities are market-implied
          (risk-neutral). The public surface carries no buy/sell/target calls or sized legs (ADR 0004 /
          0006). Engage a SEBI securities lawyer before any accuracy-marketing copy ships. Full method:
          <b> docs/METHODOLOGY.md</b>.
        </div>
        {dialErr && <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>Live dial unavailable: {dialErr}</div>}
      </Card>
    </>
  );
}

function SettingsTab({ u }: { u: string }) {
  const [conns, setConns] = useState<any[]>([]);
  const [broker, setBroker] = useState("upstox");
  const [token, setToken] = useState("");
  const [wls, setWls] = useState<any[]>([]);
  const [wlName, setWlName] = useState("");
  const [entries, setEntries] = useState<any[]>([]);
  const [note, setNote] = useState("");
  const [pw, setPw] = useState({ cur: "", next: "" });
  const [msg, setMsg] = useState("");
  const [src, setSrc] = useState<any>(null);

  async function load() {
    setConns(await api.brokerConnections().catch(() => []));
    setWls(await api.listWatchlists().catch(() => []));
    setEntries(await api.journal().catch(() => []));
    setSrc(await api.sourceStatus().catch(() => null));
  }
  useEffect(() => { load(); }, []);

  // Surface the OAuth round-trip result (?broker=upstox_connected etc.) after the redirect.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("broker");
    if (!p) return;
    const m: Record<string, string> = {
      upstox_connected: "Upstox connected — live data is on.",
      upstox_exchange_failed: "Upstox token exchange failed. Check API key/secret + that the redirect URL matches.",
      upstox_unconfigured: "Set UPSTOX_API_KEY and UPSTOX_API_SECRET on the server first.",
      upstox_error: "Upstox login was cancelled or returned no code.",
    };
    setMsg(m[p] || "");
    window.history.replaceState({}, "", window.location.pathname);
    load();
  }, []);

  async function connectBroker() {
    setMsg("");
    if (broker === "upstox" && !token.trim()) {
      // Full in-app OAuth: bounce to Upstox; it returns to /api/broker/upstox/callback.
      try {
        const r = await api.brokerAuthUrl();
        window.location.href = r.auth_url;
      } catch (e) {
        setMsg(e instanceof ApiError ? e.message : "Set UPSTOX_API_KEY on the server first.");
      }
      return;
    }
    if (!token.trim()) {
      setMsg("Paste the broker's daily access token, then press Connect.");
      return;
    }
    try {
      await api.brokerConnect(broker, token);
      setToken(""); setMsg(broker[0].toUpperCase() + broker.slice(1) + " connected.");
      load();
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : "Connect failed.");
    }
  }

  async function addNote() {
    if (!note.trim()) return;
    await api.addJournal({ text: note, underlying: u });
    setNote(""); load();
  }

  return (
    <div className="grid">
      <MethodologyPanel />
      <Card q="Connect your broker (go live)">
        {src && (
          <div className="row" style={{ gap: 8, alignItems: "center", marginBottom: 8 }}>
            <span className={"chip " + (src.mode === "live" ? "live" : "")}>
              {src.mode === "live" ? `● Live · ${String(src.source || "").toUpperCase()}` : "Demo"}
            </span>
            {src.mode === "live" ? (
              <span className="muted" style={{ fontSize: 12 }}>
                Live market data is on — no need to reconnect. The instance follows whichever broker has a valid token.
              </span>
            ) : (
              src.fallback_reason && <span className="muted" style={{ fontSize: 12 }}>{src.fallback_reason}</span>
            )}
          </div>
        )}
        <div className="muted" style={{ fontSize: 13 }}>
          Live chain/Greeks + your positions. <b>Upstox</b> — click Open login (full OAuth, returns
          here), or paste an Upstox token. <b>Groww / Dhan / Kite</b> — paste that broker's daily access
          token. Tokens are encrypted at rest.
        </div>
        {conns.length > 0 && (
          <div style={{ margin: "8px 0" }}>
            {conns.map((c) => <span key={c.broker} className={"chip " + (c.connected ? "live" : "")}>{c.broker} {c.connected ? "✓" : "expired"}</span>)}
          </div>
        )}
        <div className="row" style={{ marginTop: 8 }}>
          <select value={broker} onChange={(e) => { setBroker(e.target.value); setToken(""); setMsg(""); }} style={{ width: 110 }}>
            <option value="upstox">Upstox</option>
            <option value="groww">Groww</option>
            <option value="dhan">Dhan</option>
            <option value="kite">Kite</option>
          </select>
          <input placeholder={broker === "upstox" ? "(or paste an Upstox token)" : `${broker} access token`} value={token} onChange={(e) => setToken(e.target.value)} />
          <button className="btn" onClick={connectBroker}>{broker === "upstox" && !token.trim() ? "Open login" : "Connect"}</button>
        </div>
        {broker === "groww" && (
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            Pasting a Groww token stores it fine here. Live Groww <i>market data</i> also needs the growwapi
            SDK (the Docker image, Python ≤3.13) <i>and</i> the paid market-data role on your Groww API key —
            Upstox is the ready live path.
          </div>
        )}
        {msg && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>{msg}</div>}
      </Card>

      <Card q="Watchlists">
        <div className="row">
          <input placeholder="Name (e.g. My indices)" value={wlName} onChange={(e) => setWlName(e.target.value)} />
          <button className="btn" onClick={async () => { if (wlName.trim()) { await api.createWatchlist(wlName, [u]); setWlName(""); load(); } }}>Add ({u})</button>
        </div>
        <table style={{ marginTop: 10 }}><tbody>
          {wls.map((w) => (
            <tr key={w.id}>
              <td>{w.name}</td><td>{(w.symbols || []).join(", ")}</td>
              <td><button className="chip" onClick={async () => { await api.deleteWatchlist(w.id); load(); }}>delete</button></td>
            </tr>
          ))}
        </tbody></table>
        {wls.length === 0 && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>No watchlists yet.</div>}
      </Card>

      <Card q="Behavioral journal" full>
        <div className="row">
          <input placeholder="Log a trade thought, emotion, or bias…" value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addNote()} />
          <button className="btn" onClick={addNote}>Add</button>
        </div>
        {entries.map((e) => (
          <div className="alert" key={e.id}>
            <div>
              <div>{e.text}</div>
              <div className="muted" style={{ fontSize: 11 }}>{e.underlying || ""} · {e.ts ? new Date(e.ts).toLocaleString("en-IN") : ""}</div>
            </div>
          </div>
        ))}
        {entries.length === 0 && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>No entries yet.</div>}
      </Card>

      <Card q="Account">
        <div className="field"><input type="password" placeholder="Current password" value={pw.cur} onChange={(e) => setPw({ ...pw, cur: e.target.value })} /></div>
        <div className="field"><input type="password" placeholder="New password (8+ chars)" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} /></div>
        <button className="btn ghost" onClick={async () => {
          setMsg("");
          try { await api.changePassword(pw.cur, pw.next); setPw({ cur: "", next: "" }); setMsg("Password changed."); }
          catch (e) { setMsg(e instanceof ApiError ? e.message : "Failed"); }
        }}>Change password</button>
        {msg && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>{msg}</div>}
      </Card>
    </div>
  );
}
