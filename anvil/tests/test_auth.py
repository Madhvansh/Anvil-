"""M2: auth + account endpoints + per-user encrypted broker tokens."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from anvil.api.app import app
from anvil.auth import broker_store
from anvil.db import create_all, dispose_engine
from anvil.db import engine as dbengine
from anvil.db import repo

OWNER = {"email": "owner@anvil.test", "password": "supersecret1"}


@pytest.fixture
def client(tmp_path):
    # Fresh temp DB per test; lifespan (sqlite) creates tables in the client's event loop.
    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}")
    with TestClient(app) as c:
        yield c


def test_owner_bootstrap_and_session(client):
    assert client.get("/auth/status").json()["needs_setup"] is True

    r = client.post("/auth/register", json=OWNER)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "owner"

    # Registration closes after the first owner.
    assert client.post("/auth/register", json={"email": "x@y.z", "password": "abcdefgh"}).status_code == 403
    assert client.get("/auth/status").json()["needs_setup"] is False

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == OWNER["email"]
    assert me.json()["profile"]["feature_flags"] == {"all": True}


def test_login_logout_and_gating(client):
    client.post("/auth/register", json=OWNER)

    # A fresh client (no cookie) is unauthenticated.
    fresh = TestClient(app)
    assert fresh.get("/auth/me").status_code == 401
    assert fresh.get("/api/profile").status_code == 401
    # ...but public market analytics still work without login.
    assert fresh.get("/api/analyze/NIFTY").status_code == 200

    assert client.post("/auth/login", json={**OWNER, "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json=OWNER).status_code == 200

    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401


def test_profile_and_watchlists(client):
    client.post("/auth/register", json=OWNER)

    pr = client.patch("/api/profile", json={"explain_mode": "expert", "onboarded": True})
    assert pr.status_code == 200
    assert pr.json()["explain_mode"] == "expert" and pr.json()["onboarded"] is True
    assert client.patch("/api/profile", json={"explain_mode": "bogus"}).status_code == 400

    w = client.post("/api/watchlists", json={"name": "Indices", "symbols": ["NIFTY", "BANKNIFTY"], "is_default": True})
    assert w.status_code == 200
    wl_id = w.json()["id"]
    assert len(client.get("/api/watchlists").json()) == 1
    assert client.delete(f"/api/watchlists/{wl_id}").status_code == 200
    assert client.get("/api/watchlists").json() == []


def test_broker_connect_requires_secret(client):
    client.post("/auth/register", json=OWNER)
    # No ANVIL_SECRET_KEY in the test env → refuse to store a token in the clear.
    r = client.post("/api/broker/upstox/connect", json={"access_token": "tok"})
    assert r.status_code == 500


def test_gated_analytics_authed(client):
    client.post("/auth/register", json=OWNER)
    # Authed owner reaches the position-bearing analytics (demo book has positions).
    pr = client.get("/api/portfolio-risk")
    assert pr.status_code == 200 and "net_delta" in pr.json()
    scn = client.get("/api/scenario/NIFTY")
    assert scn.status_code == 200 and scn.json()["has_positions"] is True
    mc = client.post("/api/montecarlo/NIFTY", json={"n_paths": 500, "seed": 1})
    assert mc.status_code == 200 and mc.json()["available"] is True


def test_single_owner_db_guard(monkeypatch, tmp_path):
    # The partial unique index must reject a second owner even if the count check is bypassed.
    from sqlalchemy.exc import IntegrityError

    from anvil.auth import users as users_svc

    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'o.db').as_posix()}")

    async def body():
        await create_all()
        sm = dbengine.get_sessionmaker()
        async with sm() as s:
            await users_svc.register_user(s, "a@x.com", "supersecret1", role="owner")
            await s.commit()
        async with sm() as s:
            try:
                await users_svc.register_user(s, "b@x.com", "supersecret1", role="owner")
                await s.commit()
                raised = False
            except IntegrityError:
                raised = True
        await dispose_engine()
        return raised

    assert asyncio.run(body()) is True


def test_file_token_store_encrypts_at_rest(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    import anvil.auth.crypto as crypto
    from anvil.auth.token_store import TokenStore

    key = Fernet.generate_key()
    monkeypatch.setattr(crypto, "_fernet", lambda: Fernet(key))
    store = TokenStore(directory=str(tmp_path))
    store.save("upstox", "PLAINTEXT-TOKEN")
    raw = (tmp_path / "upstox.json").read_text()
    assert "PLAINTEXT-TOKEN" not in raw  # ciphertext on disk
    assert store.access_token("upstox") == "PLAINTEXT-TOKEN"  # transparently decrypted


def test_broker_token_encryption_roundtrip(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    import anvil.auth.crypto as crypto

    key = Fernet.generate_key()
    monkeypatch.setattr(crypto, "_fernet", lambda: Fernet(key))

    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'b.db').as_posix()}")

    async def body():
        await create_all()
        sm = dbengine.get_sessionmaker()
        async with sm() as s:
            u = await repo.create_user(s, email="o@e.com", password_hash="h")
            await broker_store.save_token(s, user_id=u.id, broker="upstox", access_token="SECRET-123")
            await s.commit()
            uid = u.id
        async with sm() as s:
            assert await broker_store.get_token(s, uid, "upstox") == "SECRET-123"
            conns = await broker_store.list_connections(s, uid)
            assert conns[0]["broker"] == "upstox" and conns[0]["connected"] is True
            # Ciphertext, not plaintext, is at rest.
            row = await broker_store.get_row(s, uid, "upstox")
            assert "SECRET-123" not in row.access_token_enc
        await dispose_engine()

    asyncio.run(body())
