"""Make `import anvil` work even without an editable install, and isolate the DuckDB/sqlite stores
PER xdist WORKER so parallel workers (`pytest -n auto`) never contend for the shared store file.

The env vars are set BEFORE any `anvil` import (this conftest runs at collection start, before tests
import anvil), so ``config.Settings`` — which reads os.environ at class definition — picks up the
per-worker paths. With ``--dist loadscope`` each test module stays on one worker, so any intra-module
state on the default store behaves exactly as in a serial run; only cross-worker contention is removed.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
_dbdir = Path(tempfile.gettempdir()) / "anvil_test_dbs" / _worker
_dbdir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("ANVIL_NO_DOTENV", "1")  # tests must see clean defaults, never a repo .env
# Assign UNCONDITIONALLY (not setdefault): xdist workers INHERIT the controller's env, where these are
# already set to the controller's "main" path — a setdefault would leave every worker sharing one file
# and contending. Keying on PYTEST_XDIST_WORKER (set per worker) gives each its own isolated stores.
os.environ["ANVIL_STORE_PATH"] = str(_dbdir / "store.duckdb")
os.environ["ANVIL_LEDGER_PATH"] = str(_dbdir / "ledger.duckdb")
os.environ["ANVIL_DATABASE_URL"] = f"sqlite+aiosqlite:///{(_dbdir / 'app.db').as_posix()}"
