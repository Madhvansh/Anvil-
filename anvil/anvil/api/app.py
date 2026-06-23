"""FastAPI service. Analytics only — never trades.

    uvicorn anvil.api.app:app --reload

Data endpoints live under ``/api/*`` (see ``api/routers/``); the cockpit/SPA is served
at ``/``. Health stays at ``/health`` for container/uptime checks.

DISCLAIMER: analytics & education only, not investment advice.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from ..config import SETTINGS
from ..obs import RequestLogMiddleware, configure_logging
from .routers import (
    account,
    advanced,
    agent,
    alerts,
    analytics,
    auth,
    brief,
    broker,
    cockpit,
    copilot,
    decision_brief,
    journal,
    ledger,
    momentum,
    paper,
    portfolio,
    snapshot,
    tips,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: on sqlite, ensure tables exist so `anvil serve` works out of the box.
    # Prod (Postgres) owns its schema through `alembic upgrade head` on container start.
    if SETTINGS.database_url.startswith("sqlite"):
        from ..db.engine import create_all

        await create_all()
    # Wave 0: when enabled (anvil go-live), run the live cockpit (recorder + predictions + nightly moat
    # clock) in THIS process. `anvil serve` leaves it off, so the plain API path is unchanged.
    if SETTINGS.live_supervisor_enabled:
        from ..live.supervisor import LiveSupervisor, set_supervisor

        sup = LiveSupervisor(force_open=SETTINGS.cockpit_force_open)
        try:
            await sup.start()
            set_supervisor(sup)
        except Exception as exc:  # noqa: BLE001 - the cockpit must never take down the whole API
            # Most common cause: the research store (anvil_store.duckdb) is locked because another
            # `anvil go-live` / `anvil record` is already running — DuckDB allows a single writer. Rather
            # than crash startup with a traceback, serve the public analytics API + SPA degraded (cockpit
            # off). /health and /api/cockpit/status then report supervisor_running:false.
            try:
                await sup.stop()
            except Exception:  # noqa: BLE001
                pass
            set_supervisor(None)
            detail = str(exc)
            locked = "being used by another process" in detail or "lock" in detail.lower()
            print(
                "  ! Live cockpit supervisor could NOT start — serving the analytics API + SPA only.\n"
                + ("    Cause: another Anvil instance is already running (anvil_store.duckdb is locked).\n"
                   "    Fix:   stop the other `anvil go-live` / `anvil record`, then run a single instance.\n"
                   if locked else "")
                + f"    detail: {detail[:200]}"
            )
    try:
        yield
    finally:
        if SETTINGS.live_supervisor_enabled:
            from ..live.supervisor import get_supervisor, set_supervisor

            sup = get_supervisor()
            if sup is not None:
                await sup.stop()
            set_supervisor(None)


configure_logging()
app = FastAPI(title="Anvil Options Intelligence", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware)
_STATIC = Path(__file__).parent / "static"

# Dev only: allow the Vite dev server (cross-origin :5173 -> :8000) to call the API with
# cookies. Prod serves the built SPA from the same origin, so no CORS is needed there.
if SETTINGS.dev_mode:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

for _router in (
    auth.router,
    account.router,
    broker.router,
    journal.router,
    alerts.router,
    analytics.router,
    advanced.router,
    brief.router,
    copilot.router,
    portfolio.router,
    agent.router,
    ledger.router,
    snapshot.router,
    paper.router,
    tips.router,
    momentum.router,
    cockpit.router,
    decision_brief.router,
):
    app.include_router(_router)


@app.get("/health")
async def health():
    db_ok = False
    try:
        from sqlalchemy import text

        from ..db.engine import get_engine

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001 - health must never raise
        db_ok = False
    from ..live.supervisor import get_supervisor
    from .buildinfo import build_stamp

    _sup = get_supervisor()
    return {
        "status": "ok",
        "version": app.version,
        "source": SETTINGS.primary_data_source,
        "trading_automation": SETTINGS.trading_automation,
        "db": db_ok,
        "build": build_stamp(),
        "supervisor_running": bool(_sup is not None and _sup.status().get("running")),
    }


# --- Service-worker kill-switch -------------------------------------------------------------
# A former vite-plugin-pwa build precached the SPA shell and registered a NavigationRoute that
# hijacked navigations (including the full-page Upstox OAuth return to /?broker=...). After
# connecting a broker the browser was served the *precached* old shell instead of the live one,
# stranding users on an old, tab-less "demo" build. We no longer ship a PWA worker.
#
# These routes are served from the network with `no-store`, so any browser that still has the
# old worker installed fetches this on its next update check, unregisters it, clears its caches,
# and reloads onto the live app — no hard refresh required. (To re-enable a PWA later, remove
# these two routes so the static sw.js/registerSW.js are served instead.)
_KILL_SW_JS = """\
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) {
  event.waitUntil((async function () {
    try { var keys = await caches.keys(); await Promise.all(keys.map(function (k) { return caches.delete(k); })); } catch (e) {}
    try { await self.clients.claim(); } catch (e) {}
    try { await self.registration.unregister(); } catch (e) {}
    try { var cs = await self.clients.matchAll({ type: "window" }); cs.forEach(function (c) { c.navigate(c.url); }); } catch (e) {}
  })());
});
"""
_KILL_REGISTER_JS = """\
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.getRegistrations()
    .then(function (rs) { rs.forEach(function (r) { r.unregister(); }); })
    .catch(function () {});
}
"""
_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}


@app.get("/sw.js", include_in_schema=False)
def service_worker_killswitch():
    return Response(_KILL_SW_JS, media_type="text/javascript", headers=_NO_STORE)


@app.get("/registerSW.js", include_in_schema=False)
def register_sw_killswitch():
    return Response(_KILL_REGISTER_JS, media_type="text/javascript", headers=_NO_STORE)


class _SpaStaticFiles(StaticFiles):
    """Content-hashed /assets/* are immutable; the HTML shell and icons must always be
    revalidated so a fresh build is picked up on the next load — a user is never pinned to an
    old shell again."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


# Serve the built React/Vite SPA at / (assets, icons). Mounted LAST so the /api, /auth, /health
# and /sw.js routes above take precedence. Falls back to a build hint if not built yet.
if (_STATIC / "index.html").exists():
    app.mount("/", _SpaStaticFiles(directory=_STATIC, html=True), name="spa")
else:

    @app.get("/", include_in_schema=False)
    def home():
        return HTMLResponse(
            "<h1>Anvil</h1><p>Build the web app: <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>, "
            "then reload.</p>"
        )
