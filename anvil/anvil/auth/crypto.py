"""Symmetric encryption for broker tokens at rest (Fernet/AES).

The key is derived from ``ANVIL_SECRET_KEY`` (SHA-256 → urlsafe base64). If no secret is
set, encryption is unavailable and the caller must refuse to persist a token rather than
store it in the clear — secrets never hit the DB unprotected.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import SETTINGS


def _fernet() -> Fernet | None:
    secret = SETTINGS.secret_key
    if not secret:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encryption_available() -> bool:
    return _fernet() is not None


def encrypt(plaintext: str) -> str | None:
    f = _fernet()
    return f.encrypt(plaintext.encode()).decode() if f else None


def decrypt(ciphertext: str) -> str | None:
    f = _fernet()
    if not f:
        return None
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None
