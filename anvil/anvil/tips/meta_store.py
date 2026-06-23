"""Persistence + process-wide cache for the trained meta-label (Innovation I.4).

The nightly cycle refits a ``MetaLabel`` from resolved history and ``save``s it here as a small JSON
(coefficients + standardizer); the live/cockpit/API predict path calls ``get_meta_label()`` to load it
(cached, refreshed when the file changes) and inject it into ``predict_for_chain``. JSON, not DuckDB, so
it never contends with a writer lock. Everything is None-safe: no file / unparseable / untrained → None,
and the prediction simply abstains on ``act_probability`` (cold-start honest).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..config import SETTINGS
from .meta_label import LogisticModel, MetaLabel


def _default_path() -> str:
    return SETTINGS.meta_label_path


def save(meta: MetaLabel, path: str | None = None) -> str:
    """Persist a trained MetaLabel to JSON. Returns the path."""
    p = Path(path or _default_path())
    if p.parent and str(p.parent) not in (".", ""):
        p.parent.mkdir(parents=True, exist_ok=True)
    m = meta.model
    data = {
        "feature_names": list(meta.feature_names),
        "n": int(meta.n),
        "coef": m.coef.tolist() if m.coef is not None else None,
        "intercept": float(m.intercept),
        "mean": m.mean_.tolist() if m.mean_ is not None else None,
        "std": m.std_.tolist() if m.std_ is not None else None,
        "l2": m.l2,
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def load(path: str | None = None) -> MetaLabel | None:
    """Rebuild a MetaLabel from its JSON; None if missing/unparseable/untrained."""
    p = Path(path or _default_path())
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not data or not data.get("coef") or not data.get("feature_names"):
        return None
    m = LogisticModel(float(data.get("l2", 1.0)))
    m.coef = np.asarray(data["coef"], dtype=float)
    m.intercept = float(data.get("intercept", 0.0))
    m.mean_ = np.asarray(data["mean"], dtype=float) if data.get("mean") is not None else None
    m.std_ = np.asarray(data["std"], dtype=float) if data.get("std") is not None else None
    if m.mean_ is None or m.std_ is None:
        return None
    return MetaLabel(data["feature_names"], m, int(data.get("n", 0)))


_CACHE: dict = {"mtime": None, "meta": None, "path": None}


def get_meta_label(path: str | None = None):
    """Process-wide cached MetaLabel, reloaded when the file's mtime changes (cheap per-tick). None when
    no model is persisted yet → callers pass it through and the prediction abstains on act_probability."""
    p = Path(path or _default_path())
    try:
        mt = p.stat().st_mtime if p.exists() else None
    except OSError:
        mt = None
    if mt != _CACHE["mtime"] or str(p) != _CACHE["path"]:
        _CACHE["meta"] = load(str(p))
        _CACHE["mtime"] = mt
        _CACHE["path"] = str(p)
    return _CACHE["meta"]


def refresh_cache() -> None:
    """Force the next ``get_meta_label`` to reload (used by tests / after a save in-process)."""
    _CACHE["mtime"] = object()  # sentinel != any real mtime
