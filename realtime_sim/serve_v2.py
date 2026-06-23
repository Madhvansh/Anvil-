"""Anvil Live v2 — a tiny, self-contained live dashboard (pure stdlib http.server).

Opens the v2 recommendations in a browser WITHOUT touching the main Anvil app or rebuilding Docker.
Run:  python serve_v2.py   →  open http://localhost:8090

  * the page renders instantly from the latest saved snapshot (reports/live_v2_*.json),
  * "↻ Run live now" hits the live Upstox feed, regenerates the tip sheet, and reloads,
  * the VRP backtest (real, non-circular) renders offline.

Read-only — no order is ever placed. Analytics & education only; see config.V2_DISCLAIMER.
"""
from __future__ import annotations

import glob
import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import backtest_v2
import config
import live_v2

PORT = int(os.environ.get("ANVIL_RT_PORT", "8090"))


def _latest_snapshot() -> dict | None:
    files = sorted(glob.glob(os.path.join(config.REPORTS_DIR, "live_v2_*.json")))
    if not files:
        return None
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _badge(status: str) -> str:
    color = {"ACTIONABLE": "#16c784", "WATCH": "#f5a623", "ABSTAIN": "#8a8f98"}.get(status, "#8a8f98")
    return f'<span class="badge" style="background:{color}">{html.escape(status)}</span>'


def _market_rows(market: list) -> str:
    out = []
    for m in market:
        sig = m.get("vrp_signal", "")
        scolor = {"SELL_VOL": "#16c784", "BUY_VOL": "#e2574c", "NEUTRAL": "#8a8f98"}.get(sig, "#8a8f98")
        out.append(
            f"<tr><td>{html.escape(str(m['underlying']))}</td>"
            f"<td class='dim'>{html.escape(str(m['asset_class']))}</td>"
            f"<td class='num'>{m['spot']:.2f}</td>"
            f"<td class='dim'>{html.escape(str(m['expiry']))} ({m['days_to_expiry']:.1f}d)</td>"
            f"<td class='num'>{m['atm_iv']*100:.1f}%</td>"
            f"<td class='num'>{m['realized_vol']*100:.1f}%</td>"
            f"<td class='num'>{m['vrp_ratio']:.2f}</td>"
            f"<td><span style='color:{scolor};font-weight:600'>{html.escape(sig)}</span></td>"
            f"<td class='dim'>{html.escape(str(m['regime']))}</td></tr>")
    return "\n".join(out)


def _tip_rows(tips: list) -> str:
    if not tips:
        return "<tr><td colspan='9' class='dim'>No structure cleared the gate — ABSTAIN is the call (no edge worth the risk right now).</td></tr>"
    out = []
    for t in tips:
        legs = ", ".join(f"{lg['side']} {int(lg['strike'])}{lg['option_type']}" for lg in t.get("legs", []))
        out.append(
            f"<tr><td class='num'>{t['rank']}</td><td>{_badge(t['status'])}</td>"
            f"<td><b>{html.escape(str(t['underlying']))}</b> <span class='dim'>{html.escape(str(t['asset_class']))}</span></td>"
            f"<td>{html.escape(str(t['strategy']))}<div class='dim small'>{html.escape(legs)}</div></td>"
            f"<td class='num'>{t['pop']*100:.1f}%</td>"
            f"<td class='num'>{t['ev_on_risk']:.3f}</td>"
            f"<td class='num pos'>₹{t['ev_net_position']:,.0f}</td>"
            f"<td class='num neg'>₹{t['max_loss_position']:,.0f}</td>"
            f"<td class='num'>{t['units']}</td></tr>")
    return "\n".join(out)


def _scorecard_html(sc: dict) -> str:
    tot = sc.get("totals", {})
    ov = sc.get("overall", {})
    head = (f"<div class='kpis'>"
            f"<div class='kpi'><span>{tot.get('resolved_trades',0)}</span>resolved</div>"
            f"<div class='kpi'><span>{tot.get('open_trades',0)}</span>open (live)</div>"
            f"<div class='kpi'><span>{tot.get('abstained',0)}</span>abstained</div>"
            f"<div class='kpi'><span>{tot.get('tips_logged',0)}</span>logged</div></div>")
    if ov.get("n"):
        body = (f"<div class='kpis'>"
                f"<div class='kpi'><span>{ov['win_rate']*100:.0f}%</span>win rate</div>"
                f"<div class='kpi'><span>₹{ov['expectancy_inr']:,.0f}</span>expectancy/trade</div>"
                f"<div class='kpi'><span class='neg'>₹{ov['max_drawdown_inr']:,.0f}</span>max drawdown</div>"
                f"<div class='kpi'><span class='neg'>₹{ov['worst_trade_inr']:,.0f}</span>worst trade</div>"
                f"<div class='kpi'><span>{ov.get('sharpe')}</span>Sharpe</div></div>")
    else:
        body = ("<p class='dim'>0 resolved structures yet — a fresh book has no track record. "
                "The WATCH tips resolve at their option expiries; the live edge accrues <b>forward</b>. "
                "See the VRP backtest below for the honest prior.</p>")
    warn = f"<p class='warn'>⚠ {html.escape(sc['tail_warning'])}</p>" if sc.get("tail_warning") else ""
    return head + body + warn


def _backtest_html() -> str:
    try:
        b = backtest_v2.run_vrp_backtest()
    except Exception as e:
        return f"<p class='dim'>VRP backtest unavailable: {html.escape(str(e))}</p>"
    if b.get("error"):
        return f"<p class='dim'>VRP backtest: {html.escape(b['error'])}</p>"
    m, w, va = b["metrics"], b["window"], b["vrp_audit"]
    return (f"<p class='dim'>{html.escape(b['method'])}</p>"
            f"<p class='dim small'>window {w['start']} → {w['end']} ({w['trading_days']} days) on ₹{int(b['capital_inr']):,}</p>"
            f"<div class='kpis'>"
            f"<div class='kpi'><span>{m['win_rate']*100:.0f}%</span>win rate</div>"
            f"<div class='kpi'><span class='pos'>{m['annualized_return_pct']}%</span>/yr</div>"
            f"<div class='kpi'><span>{m['sharpe']}</span>Sharpe</div>"
            f"<div class='kpi'><span class='neg'>{m['max_drawdown_pct']}%</span>max drawdown</div>"
            f"<div class='kpi'><span class='neg'>{m['worst_day_pct']}%</span>worst day</div>"
            f"<div class='kpi'><span>{va['mean_realized_over_implied']}</span>realized/implied</div></div>"
            f"<p class='warn'>{html.escape(b['honesty'])}</p>")


def render(snapshot: dict | None) -> str:
    if snapshot is None:
        market = tips = []
        gen = "— no snapshot yet —"
        sc_html = "<p class='dim'>Click <b>↻ Run live now</b> to pull the live market and generate the first tip sheet.</p>"
    else:
        market = snapshot.get("market_read", [])
        tips = snapshot.get("tip_sheet", [])
        gen = snapshot.get("generated", "")
        sc_html = _scorecard_html(snapshot.get("scorecard", {}))
    n_act = sum(1 for t in tips if t["status"] == "ACTIONABLE")
    n_watch = sum(1 for t in tips if t["status"] == "WATCH")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Anvil Live v2</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#0d1117;color:#e6edf3;font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}}
.wrap{{max-width:1100px;margin:0 auto;padding:20px}}
h1{{font-size:22px;margin:0}} h2{{font-size:15px;margin:24px 0 8px;color:#9aa4b2;text-transform:uppercase;letter-spacing:.05em}}
.top{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;border-bottom:1px solid #21262d;padding-bottom:14px}}
.live{{color:#16c784;font-weight:600}} .gen{{color:#8a8f98;font-size:12px}}
button{{background:#238636;color:#fff;border:0;border-radius:6px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer}}
button:hover{{background:#2ea043}} button:disabled{{background:#30363d;cursor:wait}}
table{{width:100%;border-collapse:collapse;margin-top:6px;font-size:13px}}
th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid #21262d}} th{{color:#9aa4b2;font-weight:600;font-size:11px;text-transform:uppercase}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .dim{{color:#8a8f98}} .small{{font-size:11px}}
.pos{{color:#16c784}} .neg{{color:#e2574c}}
.badge{{color:#0d1117;font-weight:700;font-size:11px;padding:2px 8px;border-radius:10px}}
.kpis{{display:flex;flex-wrap:wrap;gap:14px;margin:8px 0}}
.kpi{{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:10px 14px;min-width:110px}}
.kpi span{{display:block;font-size:20px;font-weight:700}}
.card{{background:#0f141a;border:1px solid #21262d;border-radius:10px;padding:14px 16px;margin-top:8px}}
.warn{{color:#f5a623;font-size:12px;margin-top:8px}} .disc{{color:#6e7681;font-size:11px;margin-top:24px;border-top:1px solid #21262d;padding-top:12px}}
#overlay{{display:none;position:fixed;inset:0;background:rgba(13,17,23,.85);align-items:center;justify-content:center;font-size:18px;color:#16c784}}
</style></head><body><div class="wrap">
<div class="top"><div><h1>⚒ Anvil Live <span class="live">v2</span></h1>
<div class="gen">maximum-monetization tip sheet · <span class="live">● UPSTOX LIVE</span> · generated {html.escape(str(gen))}</div></div>
<button id="run" onclick="runLive()">↻ Run live now</button></div>

<h2>Maximum-monetization tip sheet — {n_act} actionable · {n_watch} watch</h2>
<table><thead><tr><th>#</th><th>Status</th><th>Underlying</th><th>Strategy / legs</th><th class="num">POP</th>
<th class="num">EV/risk</th><th class="num">Net-EV</th><th class="num">Max loss</th><th class="num">Lots</th></tr></thead>
<tbody>{_tip_rows(tips)}</tbody></table>

<h2>Live market read — VRP · regime · positioning</h2>
<table><thead><tr><th>Underlying</th><th>Class</th><th class="num">Spot</th><th>Expiry</th><th class="num">Impl IV</th>
<th class="num">Real Vol</th><th class="num">VRP</th><th>Signal</th><th>Regime</th></tr></thead>
<tbody>{_market_rows(market)}</tbody></table>

<h2>Live scorecard (track record so far)</h2><div class="card">{sc_html}</div>

<h2>VRP edge — real backtest prior (India VIX vs realized NIFTY, 2y, no look-ahead)</h2><div class="card">{_backtest_html()}</div>

<div class="disc">{html.escape(config.V2_DISCLAIMER)}</div>
</div>
<div id="overlay">Pulling live Upstox feed &amp; pricing structures… (~30–60s)</div>
<script>
function runLive(){{document.getElementById('overlay').style.display='flex';document.getElementById('run').disabled=true;
fetch('/api/run').then(r=>r.json()).then(()=>location.reload()).catch(e=>{{alert('run failed: '+e);location.reload()}});}}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype="text/html; charset=utf-8", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                self._send(render(_latest_snapshot()).encode("utf-8"))
            elif path == "/api/latest":
                self._send(json.dumps(_latest_snapshot() or {}, default=str).encode(), "application/json")
            elif path == "/api/run":
                snap = live_v2.run_cycle(do_resolve=True)
                self._send(json.dumps({"ok": True, "generated": snap.get("generated")}, default=str).encode(), "application/json")
            elif path == "/healthz":
                self._send(b'{"status":"ok"}', "application/json")
            else:
                self._send(b"not found", code=404)
        except Exception as e:  # noqa: BLE001
            self._send(json.dumps({"ok": False, "error": str(e)}).encode(), "application/json", code=500)

    def log_message(self, *a):  # quiet
        pass


def write_static(path: str | None = None) -> str:
    """Render the latest snapshot to a standalone HTML file (no server needed). The 'Run live now'
    button is inert under file:// — the file is a viewable snapshot; run the server for live refresh."""
    path = path or os.path.join(config.REPORTS_DIR, "anvil_live_v2.html")
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    page = render(_latest_snapshot()).replace(
        'onclick="runLive()"',
        'onclick="alert(\'This is a saved snapshot. For live refresh run: python serve_v2.py\')"')
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


def main():
    if "--static" in sys.argv:
        p = write_static()
        print(f"static dashboard written → {p}\n  open it directly in a browser (file://). For live refresh, run without --static.")
        return 0
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Anvil Live v2 dashboard → http://localhost:{PORT}  (Ctrl+C to stop)")
    if _latest_snapshot() is None:
        print("  (no snapshot yet — open the page and click 'Run live now', or run live_v2.py first)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
