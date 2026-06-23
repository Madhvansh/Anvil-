"""Probability calibrators — the missing heart of the "calibration-first" engine.

Maps a target's RAW score (a conviction, a touch probability, a VRP-rich probability) to a
CALIBRATED probability, learned from the resolved-outcome history. Three calibrators, one fit gate:

  * ``IsotonicCalibrator`` — pure-numpy Pool-Adjacent-Violators (PAV) monotone fit, then linear
    interpolation between knots (scikit-learn is NOT a dependency, so PAV is hand-rolled);
  * ``PlattCalibrator`` — a 2-parameter logistic ``sigmoid(a·s+b)`` fit (scipy), label-smoothed so a
    small sample can't drive it to overconfidence; the fallback when scores are too clustered for PAV;
  * ``IdentityCalibrator`` — a near-no-op clip; the HONEST default when there isn't enough data.

``fit_calibrator`` is the degradation gate (the load-bearing guard given the near-empty live store):
below ``min_samples`` it returns identity; in the mid-n band it fits then SHRINKS toward identity by
``λ = (n-min_samples)/(blend_floor_n-min_samples)`` so the map *glides* up as live data accrues
instead of lurching the night it crosses the threshold. The deployed map is fit on all available
PAST data; its *reported quality* is always measured OUT-OF-FOLD (see ``crossval``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_EPS = 1e-6


def pav_isotonic(x, y, w=None) -> tuple[np.ndarray, np.ndarray]:
    """Pool-Adjacent-Violators: the weighted least-squares non-decreasing fit of ``y`` on ``x``.

    Returns ``(knots_x, knots_y)`` — one non-decreasing fitted value per UNIQUE ``x`` (ties in ``x``
    pre-aggregated by weighted mean). Pure numpy. The standard algorithm: sort by x, then sweep left
    to right pooling a new block into the previous one whenever it would violate monotonicity,
    cascading the merge backward until the sequence is non-decreasing again.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    w = np.ones_like(y) if w is None else np.asarray(w, dtype=float)
    if x.size == 0:
        return np.asarray([]), np.asarray([])
    order = np.argsort(x, kind="mergesort")
    x, y, w = x[order], y[order], w[order]

    # Aggregate duplicate x into a single weighted-mean point (so knots are at unique x).
    ux, inv = np.unique(x, return_inverse=True)
    m = ux.size
    gy = np.zeros(m)
    gw = np.zeros(m)
    np.add.at(gy, inv, y * w)
    np.add.at(gw, inv, w)
    gw_safe = np.where(gw > 0.0, gw, 1.0)
    gy = gy / gw_safe

    # PAV sweep. Each block carries (value, weight, span = #unique-x it covers).
    vals: list[float] = []
    wts: list[float] = []
    spans: list[int] = []
    for i in range(m):
        v, ww, sp = float(gy[i]), float(gw[i]), 1
        while vals and vals[-1] > v:  # strict violation of non-decreasing → pool backward
            pv, pw, ps = vals.pop(), wts.pop(), spans.pop()
            v = (pv * pw + v * ww) / (pw + ww)
            ww = pw + ww
            sp = ps + sp
        vals.append(v)
        wts.append(ww)
        spans.append(sp)

    fitted = np.empty(m)
    idx = 0
    for v, sp in zip(vals, spans):
        fitted[idx: idx + sp] = v
        idx += sp
    return ux, np.clip(fitted, _EPS, 1.0 - _EPS)


def _scalarize(p, out: np.ndarray):
    """Return a Python float when the caller passed a scalar, else the array (mirror input shape)."""
    return float(out.reshape(-1)[0]) if np.isscalar(p) or np.ndim(p) == 0 else out


@dataclass
class IdentityCalibrator:
    """The honest no-op: clip to [0,1]. Used whenever there isn't enough data to calibrate."""

    kind: str = "identity"

    def predict(self, p):
        out = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
        return _scalarize(p, out)

    def to_params(self) -> dict:
        return {"kind": "identity"}


@dataclass
class IsotonicCalibrator:
    knots_x: np.ndarray
    knots_y: np.ndarray
    n: int = 0
    kind: str = "isotonic"

    def predict(self, p):
        p = np.asarray(p, dtype=float)
        if self.knots_x.size == 0:
            out = np.clip(p, 0.0, 1.0)
        else:
            out = np.clip(np.interp(p, self.knots_x, self.knots_y), _EPS, 1.0 - _EPS)
        return _scalarize(p, out)

    def to_params(self) -> dict:
        return {"kind": "isotonic", "knots_x": [float(v) for v in self.knots_x],
                "knots_y": [float(v) for v in self.knots_y], "n": int(self.n)}


@dataclass
class PlattCalibrator:
    a: float
    b: float
    n: int = 0
    kind: str = "platt"

    def predict(self, p):
        p = np.asarray(p, dtype=float)
        z = self.a * p + self.b
        out = np.clip(1.0 / (1.0 + np.exp(-z)), _EPS, 1.0 - _EPS)
        return _scalarize(p, out)

    def to_params(self) -> dict:
        return {"kind": "platt", "a": float(self.a), "b": float(self.b), "n": int(self.n)}


@dataclass
class BlendedCalibrator:
    """A base calibrator shrunk toward identity by ``lam`` — the mid-n glide path. ``lam=1`` is the
    full base map; ``lam=0`` is identity."""

    base: object
    lam: float
    kind: str = "blended"

    def predict(self, p):
        p = np.asarray(p, dtype=float)
        base_p = np.asarray(self.base.predict(p), dtype=float)
        out = np.clip(self.lam * base_p + (1.0 - self.lam) * np.clip(p, 0.0, 1.0), _EPS, 1.0 - _EPS)
        return _scalarize(p, out)

    def to_params(self) -> dict:
        return {"kind": "blended", "lam": float(self.lam), "base": self.base.to_params()}


def fit_platt(scores, events) -> PlattCalibrator:
    """Fit ``sigmoid(a·s+b)`` by minimizing label-smoothed log-loss (scipy L-BFGS-B). The Platt
    smoothing prior (``y+ = (N+ +1)/(N+ +2)``, ``y- = 1/(N- +2)``) keeps a small sample from driving
    the sigmoid to 0/1."""
    from scipy.optimize import minimize

    s = np.asarray(scores, dtype=float)
    y = np.asarray(events, dtype=float)
    n1 = float(y.sum())
    n0 = float(y.size - n1)
    hi = (n1 + 1.0) / (n1 + 2.0)
    lo = 1.0 / (n0 + 2.0)
    t = np.where(y > 0.0, hi, lo)

    def nll(params):
        a, b = params
        z = a * s + b
        p = np.clip(1.0 / (1.0 + np.exp(-z)), 1e-12, 1.0 - 1e-12)
        return float(-np.mean(t * np.log(p) + (1.0 - t) * np.log(1.0 - p)))

    res = minimize(nll, x0=np.array([1.0, 0.0]), method="L-BFGS-B")
    a, b = float(res.x[0]), float(res.x[1])
    return PlattCalibrator(a=a, b=b, n=int(s.size))


def fit_calibrator(scores, events, *, min_samples: int = 50, blend_floor_n: int = 200,
                   prefer: str = "isotonic") -> tuple[object, dict]:
    """Fit the deployed calibrator with HONEST thin-data degradation.

      * ``n < min_samples`` or a single outcome class → ``IdentityCalibrator`` (``degraded=True``);
      * ``min_samples ≤ n < blend_floor_n`` → fit, then ``BlendedCalibrator`` shrunk toward identity
        by ``λ`` (glides up with n);
      * ``n ≥ blend_floor_n`` → the full base map (Platt fallback if scores are too clustered for PAV).

    Returns ``(calibrator, diagnostics)``.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(events, dtype=float)
    n = int(s.size)
    diag = {"n": n, "degraded": False, "lambda": 1.0, "kind": "identity"}

    if n < int(min_samples) or np.unique(y).size < 2:
        diag["degraded"] = True
        return IdentityCalibrator(), diag

    n_distinct = int(np.unique(s).size)
    if prefer == "isotonic" and n_distinct >= 3:
        kx, ky = pav_isotonic(s, y)
        base: object = IsotonicCalibrator(kx, ky, n=n)
        diag["kind"] = "isotonic"
    else:
        base = fit_platt(s, y)
        diag["kind"] = "platt"

    if n < int(blend_floor_n):
        span = max(1, int(blend_floor_n) - int(min_samples))
        lam = float(min(1.0, max(0.0, (n - int(min_samples)) / span)))
        diag["lambda"] = lam
        if lam < 1.0:
            return BlendedCalibrator(base, lam), diag
    return base, diag


def calibrator_from_params(d: dict | None) -> object:
    """Rehydrate a persisted calibrator from its ``to_params()`` dict."""
    if not d:
        return IdentityCalibrator()
    kind = d.get("kind")
    if kind == "isotonic":
        return IsotonicCalibrator(np.asarray(d.get("knots_x") or [], dtype=float),
                                  np.asarray(d.get("knots_y") or [], dtype=float),
                                  n=int(d.get("n") or 0))
    if kind == "platt":
        return PlattCalibrator(a=float(d.get("a", 1.0)), b=float(d.get("b", 0.0)),
                               n=int(d.get("n") or 0))
    if kind == "blended":
        return BlendedCalibrator(calibrator_from_params(d.get("base")), float(d.get("lam", 1.0)))
    return IdentityCalibrator()
