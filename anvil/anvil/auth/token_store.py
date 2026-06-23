"""Tiny JSON token cache with broker-correct expiry.

Upstox/Kite tokens die at ~03:30 IST the next day regardless of mint time. We persist the
computed expiry so callers can cheaply check validity and trigger a re-login before market open.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from ..config import SETTINGS
from . import crypto

try:
    from zoneinfo import ZoneInfo

    _IST = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover - zoneinfo always present on 3.11+
    _IST = timezone(timedelta(hours=5, minutes=30))


def expiry_at_0330_ist(now: datetime | None = None) -> datetime:
    """The next 03:30 IST boundary after ``now`` — when an Upstox/Kite token dies."""
    now = now or datetime.now(_IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    now = now.astimezone(_IST)
    boundary = now.replace(hour=3, minute=30, second=0, microsecond=0)
    return boundary if now < boundary else boundary + timedelta(days=1)


class TokenStore:
    def __init__(self, directory: str | None = None):
        self.dir = directory or SETTINGS.token_dir
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, broker: str) -> str:
        return os.path.join(self.dir, f"{broker}.json")

    def save(self, broker: str, access_token: str, expires_at: datetime | None = None, **extra) -> dict:
        exp = expires_at or expiry_at_0330_ist()
        # Encrypt at rest when a secret key is configured (prod); plaintext only in keyless dev.
        ciphertext = crypto.encrypt(access_token)
        stored, enc = (ciphertext, True) if ciphertext is not None else (access_token, False)
        blob = {
            "broker": broker,
            "access_token": stored,
            "enc": enc,
            "expires_at": exp.isoformat(),
            "minted_at": datetime.now(_IST).isoformat(),
            **extra,
        }
        path = self._path(broker)
        with open(path, "w") as f:
            json.dump(blob, f, indent=2)
        try:  # best-effort tighten perms (POSIX)
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - Windows
            pass
        return blob

    def load(self, broker: str) -> dict | None:
        try:
            with open(self._path(broker)) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def is_valid(self, broker: str, now: datetime | None = None) -> bool:
        blob = self.load(broker)
        if not blob or not blob.get("access_token"):
            return False
        try:
            exp = datetime.fromisoformat(blob["expires_at"])
        except (KeyError, ValueError):
            return False
        now = (now or datetime.now(_IST)).astimezone(_IST)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=_IST)
        return now < exp

    def access_token(self, broker: str) -> str | None:
        blob = self.load(broker)
        if not (blob and self.is_valid(broker)):
            return None
        tok = blob.get("access_token")
        return crypto.decrypt(tok) if blob.get("enc") else tok
