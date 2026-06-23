"""Broker authentication: daily token flows + a small token cache.

Both Upstox and Kite issue access tokens that expire daily with NO refresh token, so an
interactive login is required once per trading day. These helpers do the OAuth/login dance
and persist the token (with its real expiry) so the rest of the app just reads it.
"""

from .token_store import TokenStore, expiry_at_0330_ist

__all__ = ["TokenStore", "expiry_at_0330_ist"]
