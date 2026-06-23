"""M1 app-spine smoke: the ORM schema builds and the repo round-trips on a throwaway
sqlite database. Kept dependency-light — a sync test drives the async code via
``asyncio.run`` rather than pulling in pytest-asyncio."""

from __future__ import annotations

import asyncio

from anvil.db import create_all, dispose_engine
from anvil.db import engine as dbengine
from anvil.db import repo


def test_schema_and_repo_roundtrip(tmp_path):
    db = tmp_path / "spine.db"
    dbengine.init_engine(f"sqlite+aiosqlite:///{db.as_posix()}")

    async def body():
        await create_all()
        sm = dbengine.get_sessionmaker()
        async with sm() as s:
            u = await repo.create_user(s, email="Owner@Example.com", password_hash="hash")
            await repo.ensure_profile(s, u.id)
            await repo.add_watchlist(
                s, user_id=u.id, name="Indices", symbols=["NIFTY", "BANKNIFTY"], is_default=True
            )
            await s.commit()
            uid = u.id

        async with sm() as s:
            got = await repo.get_user_by_email(s, "owner@example.com")
            assert got is not None and got.id == uid
            assert got.email == "owner@example.com"  # normalized to lowercase
            assert await repo.count_users(s) == 1
            prof = await repo.ensure_profile(s, got.id)
            assert prof.feature_flags == {"all": True}  # everything unlocked (no tiers)
            assert prof.explain_mode == "trader"
            assert prof.onboarded is False
            wls = await repo.list_watchlists(s, got.id)
            assert len(wls) == 1
            assert wls[0].symbols == ["NIFTY", "BANKNIFTY"]
            assert wls[0].is_default is True

        await dispose_engine()

    asyncio.run(body())
