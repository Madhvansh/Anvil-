"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import get_settings
from ..constants import DISCLAIMER
from ..quant import black76
from . import routes_analytics, routes_chain, routes_greeks

_STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Options Intelligence Platform — Phase 0", version=__version__)

    # Permissive CORS for the Phase 1 Next.js dev origin (no auth/cookies in Phase 0).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {
            "status": "ok",
            "datasource": get_settings().datasource,
            "engine_version": black76.ENGINE_VERSION,
            "disclaimer": DISCLAIMER,
        }

    app.include_router(routes_chain.router)
    app.include_router(routes_greeks.router)
    app.include_router(routes_analytics.router)

    # Mount the static page LAST so API routes take precedence.
    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app


app = create_app()
