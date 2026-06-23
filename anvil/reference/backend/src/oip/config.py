"""Runtime configuration.

Phase 0 needs NO secrets (offline-first). Everything is overridable via `OIP_`-prefixed env vars.
The data directory is derived from the repo root by default so the demo and tests work without any
env setup; docker-compose pins it explicitly to /app/data.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py lives at <repo>/backend/src/oip/config.py → parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OIP_", env_file=".env", extra="ignore")

    data_dir: Path = _DEFAULT_DATA_DIR
    datasource: str = "fixture"  # "fixture" (default) | "nse_public"
    default_risk_free_rate: float = 0.065

    @property
    def fixtures_dir(self) -> Path:
        return self.data_dir / "fixtures"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "oip.sqlite"

    @property
    def calibration_path(self) -> Path:
        return self.data_dir / "calibration.duckdb"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --- Index reference data -------------------------------------------------------------
# Contract (lot) sizes and typical strike spacing per underlying. NSE/BSE revise lot sizes
# periodically, so treat these ONLY as fallbacks — live connectors should read the value
# from the instrument master. Verify before trusting in production.
INDEX_LOT_SIZE: dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 35,
    "FINNIFTY": 65,
    "MIDCPNIFTY": 140,
    "NIFTYNXT50": 25,
    "SENSEX": 20,
    "BANKEX": 30,
}

INDEX_STRIKE_STEP: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "NIFTYNXT50": 100,
    "SENSEX": 100,
    "BANKEX": 100,
}

SUPPORTED_INDICES: list[str] = list(INDEX_LOT_SIZE)


def lot_size(underlying: str, default: int = 1) -> int:
    return INDEX_LOT_SIZE.get(underlying.upper(), default)


def strike_step(underlying: str, default: int = 50) -> int:
    return INDEX_STRIKE_STEP.get(underlying.upper(), default)
