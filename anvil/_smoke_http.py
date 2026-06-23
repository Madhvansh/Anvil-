"""One-off end-to-end HTTP smoke via TestClient (not collected by pytest). Delete after."""
import os
os.environ.setdefault("ANVIL_DATABASE_URL", "sqlite+aiosqlite:///./_smoke_app.db")
os.environ.setdefault("ANVIL_STORE_PATH", "_smoke_store.duckdb")
os.environ.setdefault("ANVIL_LEDGER_PATH", "_smoke_ledger.duckdb")
os.environ.setdefault("ANVIL_BARS_PATH", "_smoke_bars.duckdb")
os.environ.setdefault("ANVIL_STOCK_UNIVERSE_TOP_N", "6")

from fastapi.testclient import TestClient

from anvil.db import engine as dbengine

dbengine.init_engine(os.environ["ANVIL_DATABASE_URL"])
from anvil.api.app import app  # noqa: E402

with TestClient(app) as c:
    print("register:", c.post("/auth/register", json={"email": "smoke@anvil.test", "password": "supersecret1"}).status_code)

    ru = c.get("/api/tips/universe")
    stocks = ru.json().get("stocks") if ru.status_code == 200 else []
    print("universe:", ru.status_code, stocks)

    re = c.get("/api/tips/equities")
    print("equities:", re.status_code)
    if re.status_code == 200:
        b = re.json()
        print("  live=%s stale=%s computed=%s errors=%d" % (
            b.get("live"), b.get("stale"), b.get("computed_ts"), len(b.get("errors") or [])))
        print("  BUYS :", [(x["underlying"], round(x["conviction"], 3), x.get("n_factors_fired")) for x in b["buys"][:5]])
        print("  SELLS:", [(x["underlying"], round(x["conviction"], 3), x.get("n_factors_fired")) for x in b["sells"][:5]])
    else:
        print("  ", re.text[:300])

    sym = (stocks or ["INFY"])[0]
    rt = c.get(f"/api/tips/{sym}")
    print(f"tips/{sym}:", rt.status_code, (rt.json().get("prediction") or {}).get("summary") if rt.status_code == 200 else rt.text[:200])
    rm = c.get(f"/api/momentum/{sym}")
    print(f"momentum/{sym}:", rm.status_code, (rm.json().get("momentum") or {}).get("direction") if rm.status_code == 200 else rm.text[:150])
    print("track-record:", c.get("/api/tips/track-record").status_code)
    print("trust-dial:", c.get("/api/tips/trust-dial").status_code)
