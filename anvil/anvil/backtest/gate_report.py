"""Write the Gate-0 verdict as one legible, reviewable artifact: ``gate0.json`` (machine-readable, also
the data source for the web reliability charts), ``gate0.md`` (human go/no-go with the per-target tables),
and ``gate0.svg`` (accuracy- and EV-vs-coverage curves). The plot is hand-rolled SVG so the report needs
NO new dependency (matplotlib/plotly aren't in the Python deps, and Python 3.14 wheels are uncertain)."""

from __future__ import annotations

import json
from pathlib import Path

# A small categorical palette for the per-target curves.
_PALETTE = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"]


def _fmt(v, nd: int = 3) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return "—" if f != f else f"{f:.{nd}f}"


def _pct(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if f != f else f"{f * 100:.1f}%"


# --------------------------------------------------------------------------- SVG plotting (no deps)
def _panel(curves: list[dict], *, title: str, y_key: str, y_label: str, x0: float, y0: float,
           w: float, h: float, hlines: list[tuple[float, str]] | None = None,
           vlines: list[tuple[float, str]] | None = None, y_auto: bool = False) -> str:
    """One coverage(x) vs metric(y) panel. ``curves`` = [{label, color, coverage:[...], <y_key>:[...],
    op:(cov,y)}]. ``y_auto`` autoscales y (for EV which can be negative); otherwise y∈[0,1]."""
    pad_l, pad_b, pad_t, pad_r = 46.0, 28.0, 26.0, 12.0
    px, py = x0 + pad_l, y0 + pad_t
    pw, ph = w - pad_l - pad_r, h - pad_t - pad_b

    ys = [v for c in curves for v in c.get(y_key, []) if v is not None and v == v]
    if y_auto and ys:
        lo, hi = min(ys), max(ys)
        if hi - lo < 1e-9:
            lo, hi = lo - 0.01, hi + 0.01
        pad = (hi - lo) * 0.1
        ymin, ymax = lo - pad, hi + pad
    else:
        ymin, ymax = 0.0, 1.0

    def sx(cov):
        return px + max(0.0, min(1.0, cov)) * pw

    def sy(val):
        t = (val - ymin) / (ymax - ymin) if ymax > ymin else 0.5
        return py + (1.0 - max(0.0, min(1.0, t))) * ph

    out = [f'<g><text x="{px:.1f}" y="{y0 + 16:.1f}" font-size="13" font-weight="600" '
           f'fill="#111827">{title}</text>']
    # axes box
    out.append(f'<rect x="{px:.1f}" y="{py:.1f}" width="{pw:.1f}" height="{ph:.1f}" fill="#ffffff" '
               f'stroke="#d1d5db" stroke-width="1"/>')
    # y ticks
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        val = ymin + frac * (ymax - ymin)
        yy = sy(val)
        out.append(f'<line x1="{px:.1f}" y1="{yy:.1f}" x2="{px + pw:.1f}" y2="{yy:.1f}" '
                   f'stroke="#f3f4f6" stroke-width="1"/>')
        out.append(f'<text x="{px - 5:.1f}" y="{yy + 3:.1f}" font-size="9" text-anchor="end" '
                   f'fill="#6b7280">{val:.2f}</text>')
    # x ticks
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        xx = sx(frac)
        out.append(f'<text x="{xx:.1f}" y="{py + ph + 14:.1f}" font-size="9" text-anchor="middle" '
                   f'fill="#6b7280">{frac:.2f}</text>')
    out.append(f'<text x="{px + pw / 2:.1f}" y="{py + ph + 26:.1f}" font-size="10" '
               f'text-anchor="middle" fill="#374151">coverage</text>')
    out.append(f'<text x="{x0 + 12:.1f}" y="{py + ph / 2:.1f}" font-size="10" fill="#374151" '
               f'transform="rotate(-90 {x0 + 12:.1f} {py + ph / 2:.1f})" text-anchor="middle">{y_label}</text>')
    # reference lines
    for yv, lbl in (hlines or []):
        yy = sy(yv)
        out.append(f'<line x1="{px:.1f}" y1="{yy:.1f}" x2="{px + pw:.1f}" y2="{yy:.1f}" '
                   f'stroke="#9ca3af" stroke-width="1" stroke-dasharray="4 3"/>')
        out.append(f'<text x="{px + pw - 2:.1f}" y="{yy - 3:.1f}" font-size="8" text-anchor="end" '
                   f'fill="#6b7280">{lbl}</text>')
    for xv, lbl in (vlines or []):
        xx = sx(xv)
        out.append(f'<line x1="{xx:.1f}" y1="{py:.1f}" x2="{xx:.1f}" y2="{py + ph:.1f}" '
                   f'stroke="#9ca3af" stroke-width="1" stroke-dasharray="4 3"/>')
        out.append(f'<text x="{xx + 2:.1f}" y="{py + 10:.1f}" font-size="8" fill="#6b7280">{lbl}</text>')
    # curves
    for c in curves:
        covs = c.get("coverage", [])
        yvs = c.get(y_key, [])
        pts = sorted(((cv, yv) for cv, yv in zip(covs, yvs) if yv is not None and yv == yv),
                     key=lambda p: p[0])
        if pts:
            d = " ".join(f"{sx(cv):.1f},{sy(yv):.1f}" for cv, yv in pts)
            out.append(f'<polyline points="{d}" fill="none" stroke="{c["color"]}" stroke-width="1.6"/>')
        op = c.get("op")
        if op and op[1] is not None and op[1] == op[1]:
            out.append(f'<circle cx="{sx(op[0]):.1f}" cy="{sy(op[1]):.1f}" r="3.5" '
                       f'fill="{c["color"]}" stroke="#ffffff" stroke-width="1"/>')
    out.append("</g>")
    return "".join(out)


def _legend(curves: list[dict], x: float, y: float) -> str:
    out = []
    for i, c in enumerate(curves):
        yy = y + i * 15
        out.append(f'<rect x="{x:.1f}" y="{yy - 8:.1f}" width="10" height="10" fill="{c["color"]}"/>')
        out.append(f'<text x="{x + 15:.1f}" y="{yy + 1:.1f}" font-size="10" fill="#374151">'
                   f'{c["label"]}</text>')
    return "".join(out)


def render_svg(result: dict) -> str:
    targets = [t for t in result.get("targets", []) if t.get("evaluable") and t.get("curve", {}).get("coverage")]
    th = result.get("thresholds", {})
    acc_target = th.get("accuracy_target", 0.65)
    min_cov = th.get("min_coverage", 0.10)

    acc_curves, ev_curves = [], []
    for i, t in enumerate(targets):
        color = _PALETTE[i % len(_PALETTE)]
        cur = t["curve"]
        label = f"{t['target']}/{t['source_class']}"
        acc_curves.append({"label": label, "color": color, "coverage": cur["coverage"],
                           "accuracy": cur["accuracy"], "op": (t.get("coverage"), t.get("accuracy"))})
        if "realized_ev" in cur:
            ev_curves.append({"label": label, "color": color, "coverage": cur["coverage"],
                              "realized_ev": cur["realized_ev"],
                              "op": (t.get("coverage"), t.get("realized_ev"))})

    width, ph = 760, 300
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {ph * 2 + 40}" '
            f'font-family="ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif">',
            f'<rect width="{width}" height="{ph * 2 + 40}" fill="#f9fafb"/>']
    if not acc_curves:
        body.append('<text x="20" y="40" font-size="14" fill="#374151">Gate-0: no evaluable '
                    'targets with a coverage curve (insufficient resolved evidence).</text></svg>')
        return "".join(body)
    body.append(_panel(acc_curves, title="Calibrated accuracy vs coverage", y_key="accuracy",
                       y_label="calibrated accuracy", x0=0, y0=10, w=width - 150, h=ph,
                       hlines=[(acc_target, f"target {acc_target:.2f}")],
                       vlines=[(min_cov, f"min cov {min_cov:.2f}")]))
    body.append(_legend(acc_curves, width - 140, 36))
    if ev_curves:
        body.append(_panel(ev_curves, title="Realized EV (net of cost) vs coverage", y_key="realized_ev",
                           y_label="EV / unit risk", x0=0, y0=ph + 30, w=width - 150, h=ph,
                           hlines=[(0.0, "breakeven")], vlines=[(min_cov, f"min cov {min_cov:.2f}")],
                           y_auto=True))
        body.append(_legend(ev_curves, width - 140, ph + 56))
    body.append("</svg>")
    return "".join(body)


# --------------------------------------------------------------------------- Markdown
def render_markdown(result: dict) -> str:
    th = result.get("thresholds", {})
    data = result.get("data", {})
    verdict = result.get("verdict", {})
    lines: list[str] = []
    lines.append("# Gate-0 — certification report")
    lines.append("")
    if data.get("provisional"):
        depth = data.get("depth_days")
        lines.append(f"> **PROVISIONAL — plumbing validation on {depth or 'cached'} trading days, NOT the "
                     "real go/no-go.** Mainly exercises the resolved targets (conviction/equity); "
                     "touch/vrp stay identity until depth. Re-certify on the full backfill before trusting "
                     "any verdict here.")
        lines.append("")
    go = verdict.get("pass")
    lines.append(f"## Verdict: {'✅ GO' if go else '⛔ NO-GO / ABSTAIN'}")
    lines.append("")
    lines.append(verdict.get("summary", ""))
    lines.append("")
    rng = data.get("date_range")
    lines.append(f"- **Window:** {rng[0]} → {rng[1]}" if rng else "- **Window:** (unspecified)")
    lines.append(f"- **Gate / calibration version:** `{result.get('gate_version')}` / "
                 f"`{result.get('calibration_version')}`")
    lines.append(f"- **Generated:** {result.get('generated_ts') or '(unstamped)'}")
    lines.append(f"- **Pass bar:** ≥ {th.get('accuracy_target')} calibrated accuracy at ≥ "
                 f"{th.get('min_coverage')} coverage; operating cell headline-eligible "
                 f"(DSR ≥ 0.95, PBO ≤ 0.5, Harvey t ≥ 3, both OOF edges > 0); trials counted; EV > 0.")
    lines.append("")
    lines.append("## Per-target accuracy / EV at coverage")
    lines.append("")
    lines.append("| target / source | n | calib | op τ | coverage | cal. accuracy | realized EV | "
                 "DSR | PBO | t | headline | trials | verdict |")
    lines.append("|---|--:|:--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|:--:|")
    for t in result.get("targets", []):
        name = f"{t['target']}/{t['source_class']}"
        if not t.get("evaluable"):
            lines.append(f"| {name} | {t.get('n')} | — | — | — | — | — | — | — | — | — | — | "
                         f"abstain ({t.get('note', 'insufficient')}) |")
            continue
        b = t.get("battery", {})
        v = "✅ pass" if t.get("verdict", {}).get("pass") else "abstain"
        lines.append(
            f"| {name} | {t.get('n')} | {'yes' if t.get('calibrated') else 'no'} | "
            f"{_fmt(t.get('operating_tau'), 2)} | {_pct(t.get('coverage'))} | {_pct(t.get('accuracy'))} | "
            f"{_fmt(t.get('realized_ev'), 4)} | {_fmt(b.get('dsr'))} | {_fmt(b.get('pbo'))} | "
            f"{_fmt(b.get('t_stat'))} | {'yes' if b.get('headline_eligible') else 'no'} | "
            f"{t.get('trials')} | {v} |")
    lines.append("")
    # Per-target reasons (why an abstain)
    for t in result.get("targets", []):
        reasons = t.get("verdict", {}).get("reasons") or []
        if t.get("evaluable") and reasons and not t.get("verdict", {}).get("pass"):
            lines.append(f"- **{t['target']}/{t['source_class']} abstains:** " + "; ".join(reasons))
    lines.append("")
    lines.append("_Operating point τ is set on EV × coverage (the money frontier) where a P&L target "
                 "exists, else on the accuracy frontier. Coverage / accuracy / EV are OUT-OF-FOLD "
                 "(test-fold) numbers at that τ. Every threshold sweep is counted in the trial registry, "
                 "so the Deflated-Sharpe bar rises with search — abstaining here is honest, not a bug._")
    lines.append("")
    return "\n".join(lines)


def write_gate0_report(result: dict, out_dir, *, now_ts: str | None = None,
                       provisional: bool | None = None) -> dict:
    """Write ``gate0.{json,md,svg}`` into ``out_dir``; returns the written paths. ``now_ts`` /
    ``provisional`` override the values already on ``result`` (timestamps are stamped by the caller —
    the workflow/runtime has no wall clock)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if now_ts is not None:
        result["generated_ts"] = now_ts
    if provisional is not None:
        result.setdefault("data", {})["provisional"] = provisional

    json_path = out / "gate0.json"
    md_path = out / "gate0.md"
    svg_path = out / "gate0.svg"
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    svg_path.write_text(render_svg(result), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "svg": str(svg_path)}
