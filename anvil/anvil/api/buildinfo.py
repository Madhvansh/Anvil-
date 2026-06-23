"""SPA build stamp — lets the cockpit header warn when the served front-end is stale.

Reads the static ``index.html`` mtime + the hashed ``assets/*`` filenames so the API can report which
build it is serving and a short content hash. Cheap and never raises (a missing static dir just yields
``static_present: False`` — dev runs the Vite server separately)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

_STATIC = Path(__file__).parent / "static"


def build_stamp() -> dict:
    info: dict = {"built": None, "index_mtime": None, "assets": 0, "hash": None,
                  "static_present": False}
    try:
        idx = _STATIC / "index.html"
        info["static_present"] = idx.exists()
        if idx.exists():
            mt = idx.stat().st_mtime
            info["index_mtime"] = mt
            info["built"] = datetime.fromtimestamp(mt, timezone.utc).isoformat()
        assets = _STATIC / "assets"
        names = sorted(p.name for p in assets.glob("*")) if assets.exists() else []
        info["assets"] = len(names)
        if names:
            info["hash"] = hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:12]
    except Exception:  # noqa: BLE001 - build info must never raise
        pass
    return info
