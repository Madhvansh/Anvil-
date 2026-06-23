"use strict";

const UNDERLYING = "NIFTY";

function num(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function pct(v) {
  if (v === null || v === undefined) return "—";
  return num(v * 100, 2) + "%";
}

function legCells(leg, side) {
  if (!leg) return `<td colspan="6" class="${side}">—</td>`;
  return `
    <td class="${side}">${num(leg.theo_price)}</td>
    <td class="${side}">${pct(leg.iv_used)}</td>
    <td class="${side}">${num(leg.delta, 3)}</td>
    <td class="${side}">${num(leg.gamma, 5)}</td>
    <td class="${side}">${num(leg.theta_per_day)}</td>
    <td class="${side}">${num(leg.vega_per_pct)}</td>`;
}

function renderMeta(d) {
  document.getElementById("disclaimer").textContent = d.disclaimer;
  document.getElementById("src").textContent =
    `${d.future_price_source} · model ${d.price_model} (${d.engine_version})`;
  document.getElementById("meta").innerHTML = `
    <div>Underlying <b>${d.underlying}</b></div>
    <div>Spot <b>${num(d.spot)}</b></div>
    <div>Future <b>${num(d.future_price)}</b><span class="tag">${d.future_price_source}</span></div>
    <div>Expiry <b>${d.expiry}</b></div>
    <div>Snapshot <b>${d.snapshot_ts}</b></div>
    <div>r <b>${pct(d.risk_free_rate)}</b></div>`;
}

function renderTable(rows) {
  const head = `
    <tr>
      <th colspan="6" class="group">CALL — Black-76</th>
      <th class="strike">STRIKE</th>
      <th colspan="6" class="group">PUT — Black-76</th>
    </tr>
    <tr>
      <th>Price</th><th>IV</th><th>Δ</th><th>Γ</th><th>Θ/day</th><th>Vega/1%</th>
      <th class="strike"></th>
      <th>Price</th><th>IV</th><th>Δ</th><th>Γ</th><th>Θ/day</th><th>Vega/1%</th>
    </tr>`;
  const body = rows.map((r) => `
    <tr>
      ${legCells(r.call, "call")}
      <td class="strike">${num(r.strike, 0)}</td>
      ${legCells(r.put, "put")}
    </tr>`).join("");
  document.getElementById("content").innerHTML = `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

async function load() {
  try {
    const resp = await fetch(`/chain?underlying=${UNDERLYING}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderMeta(data);
    renderTable(data.rows);
  } catch (e) {
    document.getElementById("content").innerHTML =
      `<div class="err">Failed to load chain: ${e.message}</div>`;
  }
}

load();
