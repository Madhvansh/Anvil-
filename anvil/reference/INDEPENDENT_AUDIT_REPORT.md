# Independent Build-and-Run Audit — `v1` (anvil) vs `v2` (oip)

**Date:** 2026-06-18
**Auditor scope:** `c:\Users\Administrator\Downloads\AUDIT stock market\{v1, v2}`
**Method:** Everything below was established by **building and running** the code, inspecting
databases, and attempting the repos' own Docker/CI paths — **not** by trusting any `.md`.
No repo source or config file was modified (read-and-run only). Virtual environments and one
temporary directory junction lived under `%TEMP%` and were cleaned up.

> **One-line verdict.** **v2 (`oip`) is real, green, and reproducible** on both Python 3.12
> (Docker) and 3.14 (host): 176 tests pass, ruff-clean, demo PASS. **v1 (`anvil`) is also real
> code with a passing suite (97 tests) — but it is broken as delivered**: its package directory
> was renamed `anvil`→`v1`, so it neither imports, runs, nor builds in Docker without a manual
> workaround. Both repos are honest in places and overstated in others; the five most important
> factual discrepancies vs. the two audit docs are in §7.

---

## 1. Environment actually used

| Item | Value (observed) |
|---|---|
| Host OS | Windows 11 (10.0.26200) |
| Host Python | **3.14.4** only (`py -0p` shows just `-V:3.14`) |
| Docker | **29.5.3 server** (daemon was *down* at first probe — `docker info` → HTTP 500 — then came up) |
| Git | 2.51.2.windows |
| v1 venv | prebuilt `v1\.venv` = **Python 3.14.4** (`pyvenv.cfg`), originally created at `…\Stock Market App\anvil\.venv` |
| v2 venv | **none on disk** — built fresh for this audit |

**Runtimes exercised (per the agreed "Docker if up, else host; always also run host 3.14; compare"):**
- **Canonical Docker, Python 3.12** — both repos' Dockerfiles/CI target `python:3.12-slim`.
- **Host, Python 3.14** — v1 from its existing `.venv`; v2 from a fresh `%TEMP%\oip_venv`.

---

## 2. Evidence ledger (key command outputs)

| # | Command (abridged) | Result |
|---|---|---|
| E1 | `docker compose build` (v2) | ✅ image `oip-backend:phase0` built; `py_vollib 1.0.12`, `vollib 1.0.11` installed on 3.12 |
| E2 | `docker compose run --rm backend pytest -m "unit or validation" --strict-markers -q` | ✅ **176 passed, 1 deselected** |
| E3 | `docker compose run --rm backend pytest -q` | ✅ **176 passed, 1 skipped** |
| E4 | `docker compose run --rm backend ruff check .` | ✅ **All checks passed!** |
| E5 | `docker compose run --rm backend python scripts/demo_phase0.py --underlying NIFTY` | ✅ **[PASS] reproducibility … exit 0** |
| E6 | `docker build -t anvil:ci v1` | ❌ **ERROR at `Dockerfile:15  COPY anvil ./anvil` → `"/anvil": not found`** |
| E7 | `v1\.venv\Scripts\python -m pytest -q` (as-shipped) | ❌ **10 errors during collection, `ModuleNotFoundError: No module named 'anvil'`, exit 2** |
| E8 | `v1\.venv\Scripts\python -m anvil.cli pull NIFTY --demo` (as-shipped) | ❌ **`ModuleNotFoundError: No module named 'anvil'`, exit 1** |
| E9 | v1 pytest via `%TEMP%` junction (so `anvil` resolves; no `py_vollib`) | ✅ **97 collected, all passed, exit 0** |
| E10 | v1 `anvil.cli pull NIFTY --demo` via junction | ✅ full analytics printed, **exit 0** |
| E11 | `pip install` v2 deps on Python 3.14 | ✅ **all wheels install** (`py_vollib 1.0.12`, `vollib 1.0.11`, `pyarrow 24.0.0`, `scipy 1.17.1`, `pandas 3.0.3`, `duckdb 1.5.4`, `numpy 2.4.6`, …) |
| E12 | v2 `pytest -q` on host 3.14 (default data dir) | ✅ **176 passed, 1 skipped** (identical to Docker) |
| E13 | v2 `demo_phase0.py` on host 3.14 | ✅ **[PASS] … exit 0** |
| E14 | DuckDB read-only: v1 `demo_ledger.duckdb` | forecasts **503** (`source`: 500 `seed`, 3 `anvil`), outcomes **500** |
| E15 | DuckDB read-only: v1 `demo_store.duckdb` | snapshots **1**, chain_rows **162**, ingest_runs **1** (`source=demo`) |
| E16 | DuckDB read-only: v2 `calibration.duckdb` | forecasts **8**, outcomes **8** (all test-generated) |
| E17 | SQLite read-only: v2 `oip.sqlite` | instruments **2**, snapshots **1**, ingest_runs **1** |
| E18 | `grep log_forecast` in `v2\backend\src` | only the **definition**; **never called** in application code → no forecast producer |

---

## 3. v1 — `anvil`

### 3.1 Real source tree (verified on disk; package name = `anvil`, laid out flat at the repo root)
```
v1/
├─ __init__.py  cli.py  config.py  models.py  pipeline.py
├─ pyproject.toml  Dockerfile  docker-compose.yml  .env.example  .gitignore
├─ README - anvil.md   .github/workflows/ci.yml
├─ engine/      oi.py util.py regime.py greeks.py higher_order.py forward.py
│               gex.py implied_dist.py portfolio.py vol.py
├─ ingest/      base.py demo.py dhan.py nse_eod.py macro.py upstox.py kite.py groww.py
├─ agent/       analyst.py guardrail.py
├─ auth/        token_store.py upstox_auth.py kite_auth.py
├─ ledger/      ledger.py scoring.py
├─ execution/   gateway.py groww_gateway.py
├─ store/       timeseries.py
├─ api/         app.py
├─ tests/       10 files, 62 `def test_` functions (+ parametrize in test_greeks → 97 collected)
├─ .venv/       (Python 3.14.4; has pytest/numpy/scipy/pydantic/duckdb/fastapi/httpx/structlog; NO py_vollib)
└─ anvil_store.duckdb  demo_store.duckdb  demo_ledger.duckdb
```
All modules contain real code (none are empty stubs). `import anvil` is **not** satisfied by an
editable install (no `.pth`/`.egg-link`/`*.dist-info` for `anvil` in the venv).

### 3.2 Build & test results
- **Python pinned:** `pyproject` `requires-python>=3.11`; Dockerfile `FROM python:3.12-slim`.
- **Docker build (E6): FAILS.** `Dockerfile:15` does `COPY anvil ./anvil`, but the build context
  `v1/` has **no `anvil/` subdirectory** (the package files live at the root). Build aborts. Since
  `.github/workflows/ci.yml` runs `docker build -t anvil:ci .` as its first step, **CI cannot run**.
- **Host 3.14, as-shipped (E7/E8): does not run.** `pytest` → **10 collection errors**, every test
  file failing `ModuleNotFoundError: No module named 'anvil'`; **0 tests executed**. The demo
  entrypoint fails identically. Root cause: the directory was renamed `anvil`→`v1`; `conftest.py`
  only inserts `v1/` (not its parent) onto `sys.path`, and there is no install — so `from anvil.… import …`
  cannot resolve. (Tracebacks even show stale bytecode paths `…\Stock Market App\anvil\tests\…`.)
- **Host 3.14, intrinsic (E9): the code itself is green.** With a `%TEMP%` directory junction making
  `anvil` importable (no edits to the repo; `PYTHONDONTWRITEBYTECODE=1`, pytest cache disabled),
  the full suite is **97 collected, all passed, 0 failed, 0 skipped (exit 0)**. `py_vollib` is absent
  yet nothing errors — the vollib cross-check is conditionally guarded.

### 3.3 Demo / entrypoints
`python -m anvil.cli pull NIFTY --demo` — ❌ crashes as-shipped (import error); ✅ via the junction
runs cleanly (exit 0), printing OI/PCR/max-pain, GEX + zero-gamma flip, market-implied distribution,
a rule-based regime read, and beta-weighted portfolio Greeks — all on **synthetic** `DemoConnector`
data. Other entrypoints present: `serve` (FastAPI), `ledger {record|resolve|seed|report}`, `auth`,
`order` (dry-run by default).

### 3.4 Git state
**Not a git repository** — no `.git` in `v1/` or the parent; `git rev-parse` is fatal.

### 3.5 Scaffolding vs. wired reality
- **Connectors:** the only path ever exercised is `DemoConnector` (offline, deterministic synthetic
  chain). `dhan.py` / `upstox.py` / `kite.py` / `groww.py` are **real** `httpx`/SDK clients, but each
  `raise`s without credentials (e.g. `DhanConnector` requires `DHAN_CLIENT_ID`+`DHAN_ACCESS_TOKEN`)
  and is never invoked by tests or the demo. `nse_eod.py` is a real best-effort scraper, also never
  called. → **zero live network calls, ever.**
- **Ledger (real persistence, synthetic data):** `demo_ledger.duckdb` holds **503 forecasts** —
  500 `source='seed'` (synthetic, well-calibrated-by-construction) + 3 `source='anvil'` (emitted from
  the synthetic demo chain) — and **500 resolved outcomes**, all from synthetic inputs.
  **Real market-resolved forecasts = 0.** The mechanics (Brier/log-loss/ECE/reliability, record/resolve)
  are real and tested; the track record is not real.
- **Store:** real DuckDB — `demo_store.duckdb` = 1 demo snapshot / 162 chain rows.
- **Execution:** gated and safe — `AssistedExecutor` dry-run; `AutoExecutor` off by default. No real order.
- **Docker/CI:** present but **broken** (build fails) and never run here.

---

## 4. v2 — `oip`

### 4.1 Real source tree (verified on disk; package `oip` under `backend/src/`)
```
v2/
├─ docker-compose.yml  .dockerignore  .gitignore  README.md  CLAUDE.md  NORTH_STAR.md  PROJECT_SPEC.md
├─ .github/workflows/ci.yml      docs/decisions/ (6 ADRs)      data/fixtures/nse_chain_NIFTY_2026-06-12.json
└─ backend/
   ├─ Dockerfile  pyproject.toml
   ├─ src/oip/
   │   ├─ config.py constants.py
   │   ├─ domain/    models.py enums.py
   │   ├─ quant/     black76.py greeks_service.py
   │   ├─ data/      source.py fixture_replay.py nse_public.py normalize.py
   │   ├─ analytics/ oi.py vol.py gex.py implied_dist.py util.py
   │   ├─ calibration/ ledger.py scoring.py
   │   ├─ storage/   duck.py sqlite_meta.py schema.sql
   │   ├─ pipeline/  ingest.py
   │   └─ api/       app.py service.py analytics_service.py deps.py routes_chain.py routes_greeks.py routes_analytics.py
   ├─ tests/   20 files, 80 `def test_` functions (+ parametrize → 177 collected); markers unit/validation/broker_validation/nse_live
   └─ scripts/ demo_phase0.py  record_fixture.py
```

### 4.2 Build & test results
- **Python pinned:** `requires-python>=3.12`; `backend/Dockerfile` `FROM python:3.12-slim`, `COPY src ./src`
  (sound — `src/` exists), `pip install ".[dev]"`.
- **Docker 3.12 (E1–E5):** image builds; **CI gate** `pytest -m "unit or validation"` = **176 passed,
  1 deselected**; **full** `pytest -q` = **176 passed, 1 skipped**; **ruff** = clean; **demo** = PASS (exit 0).
- **Host 3.14 (E11–E13):** every dependency — including `py_vollib`, `vollib`, `pyarrow`, `scipy`,
  `pandas`, `duckdb` — installs on cp314; full suite = **176 passed, 1 skipped**; demo PASS (exit 0).
  **Identical results to Docker 3.12.**
- The single skip is the `broker_validation` test (its fixture `broker_greeks_nifty.json` is empty).
  The `py_vollib`/`vollib` agreement test **runs and passes** (library installed). 80 test functions
  expand via `@pytest.mark.parametrize` to the 177 collected (176 + 1 skipped).

### 4.3 Demo / entrypoints
`python scripts/demo_phase0.py --underlying NIFTY`: ingest fixture chain → compute Black-76 Greeks →
write Parquet + SQLite → re-read via the query path → **reproducibility self-check byte-stable (tol 1e-9)**
→ exit 0, on both runtimes. The FastAPI app (`uvicorn oip.api.app:app`) is the server entrypoint; a
static page is served and its disclaimer banner is asserted by tests.

### 4.4 Git state
**Not a git repository** — no `.git`; `git rev-parse` is fatal.

### 4.5 Scaffolding vs. wired reality
- **Data:** default `FixtureDataSource` (offline JSON replay) is the only path used by app/tests/demo.
  `nse_public.py` is a **real** live-NSE client, but it is **capture-only** — used solely by
  `scripts/record_fixture.py`, not the running app (default `datasource = "fixture"`). → **zero live
  network calls** in tests/demo.
- **Quant:** real, validated Black-76 (closed-form + `py_vollib` agreement + finite-difference + put-call
  parity + IV round-trip + edge cases). The genuine strength.
- **Analytics:** GEX / implied distribution are real computations but **self-flagged unvalidated**
  (`needs_nse_validation`, `needs_real_world_calibration`).
- **Calibration ledger:** real DuckDB substrate, but `calibration.duckdb` contains only **8 forecasts/
  8 outcomes — all created by the unit tests**, and `log_forecast` is **defined but never called in
  `src/`** → **no forecast producer, no real track record** (an "empty vessel", as its own doc says).
- **Multi-index:** 7 indices configured, but **only NIFTY has a fixture**; everything runs off that one
  committed snapshot.
- **Persistence:** real — `oip.sqlite` shows 2 seeded instruments, 1 snapshot, 1 ingest run.
- **Docker/CI:** sound and **actually runnable** — this audit executed the exact CI gate + demo it specifies.

---

## 5. Comparison table — feature × {state} for each repo

Legend: **✅** exists & tested (passing tests exercise it) · **🟡** exists but stub / untested /
unvalidated / never-run-live / broken · **❌** absent.

| Feature / module | v1 (`anvil`) | v2 (`oip`) |
|---|---|---|
| Black-76 Greeks engine | ✅ `test_greeks` | ✅ validation gate, vollib-agreed |
| Higher-order Greeks (vanna/charm/vomma) | ✅ `engine/higher_order` | ❌ absent |
| GEX + zero-gamma flip | ✅ `test_gex` ¹ | ✅ `test_gex` ¹ |
| Implied distribution (Breeden-Litzenberger) | ✅ `test_implied_dist` ¹ | ✅ `test_implied_dist` ¹ |
| OI analytics (PCR / max-pain / walls / buildup) | ✅ `test_oi` | ✅ `test_oi` |
| Vol / skew / IV-rank | 🟡 `engine/vol` present, **no test** | ✅ `test_vol` |
| Portfolio / beta-weighted risk book | ✅ `test_portfolio` | ❌ absent |
| Regime model | ✅ present (exercised via pipeline; no dedicated test) | ❌ absent |
| Calibration ledger mechanics (Brier / log-loss / reliability) | ✅ `test_ledger` | ✅ `test_ledger` + `test_scoring` |
| Real forecast **producer** | 🟡 exists, synthetic inputs only | ❌ `log_forecast` never called in src |
| Real calibration **track record** | 🟡 500 resolved, all synthetic (0 real) | 🟡 8 rows, all test residue (0 real) |
| Live broker connectors (Upstox/Dhan/Kite/Groww) | 🟡 real code, **0 live calls** | ❌ absent |
| Live NSE data | 🟡 `nse_eod` scraper, never run | 🟡 `nse_public` capture-only, not in app path |
| AI / agent copilot | 🟡 narrator+guardrail tested; Claude path untested | ❌ absent |
| Execution / order gateway | 🟡 dry-run tested w/ fake SDK; never live | ❌ analysis-only |
| Persistence store (DuckDB/Parquet/SQLite) | ✅ `test_store_m2` | ✅ `test_roundtrip` |
| FastAPI service | 🟡 `api/app.py` present, **no API test** | ✅ `test_routes` + `test_analytics_routes` |
| CLI entrypoint | ✅ runs (verified) ² | ❌ none (uses demo script + API) |
| Demo reproducibility self-check | — (CLI prints only) | ✅ `demo_phase0` byte-stable PASS |
| Multi-index config | partial (NIFTY/BANKNIFTY/FINNIFTY mapped) | 🟡 7 configured, only NIFTY fixture |
| Docker build | ❌ **broken** (`COPY anvil` fails) | ✅ builds & runs |
| CI workflow | 🟡 written but **un-runnable** (broken build) | ✅ runnable (gate + demo executed) |
| Test suite (as delivered) | ❌ **0 run** (import error); 🟡 97 pass only via workaround | ✅ 176 pass (3.12 *and* 3.14) |

¹ GEX and implied-distribution are tested deterministically in *both* repos but carry explicit
"not yet validated against real NSE / real-world outcomes" caveats. ² v1's CLI was verified only via
the junction workaround; it is broken as delivered.

---

## 6. Claims that checked out (for fairness)

Not everything is overstated — several doc admissions are accurate and were confirmed:
- v2: **"176 tests pass, ruff-clean"** — confirmed (E2–E4), and reproducible on 3.14 too.
- v2: **demo reproducibility PASS** — confirmed (E5/E13).
- v2: calibration ledger **"Substrate only — EMPTY … nothing logs forecasts → 0 track record"** — confirmed (E16/E18).
- v2: GEX / RND **self-flagged unvalidated**; **live data "still offline fixture only"** — confirmed.
- v1: ledger reliability curve is **synthetic `seed` data, real resolved forecasts "zero"** — confirmed (E14).
- v1: connectors **"zero live calls"**, execution **"no real order ever placed"** — confirmed by code + run.

---

## 7. The five most important factual discrepancies (real behavior vs. the audit docs)

### D1 — Git state is asserted but does not exist
> `MERGED_VERSION_AUDIT.md:54` — *"The git repo is **initialized and staged but not committed**, and
> the M3–M5/M2 modules are currently **untracked**."* (also `:142` *"repo uncommitted"*)

**Reality:** neither `v1`, `v2`, nor the parent folder is a git repository — there is no `.git`
anywhere and `git rev-parse --is-inside-work-tree` is fatal in all three. There is no staging, no
commits, and no tracked/untracked distinction in the delivered artifacts.

### D2 — v1 does not run as delivered, contradicting "96 tests passing / runs offline"
> `MERGED_VERSION_AUDIT.md:16` — *"raised the test bar (25 → **96 tests** …)"*; `:65` — *"\"96 tests
> passing\" — true and meaningful for the math."*

**Reality:** as delivered, v1's suite **collects 0 tests and throws 10 `ModuleNotFoundError: No module
named 'anvil'`** errors (E7), and the demo crashes the same way (E8). The "passing" suite is only
reproducible after a manual workaround for the `anvil`→`v1` directory rename — and the real count is
then **97**, not 96 (E9).

### D3 — v1's Docker/CI is structurally broken, not merely "defined but not run"
> `MERGED_VERSION_AUDIT.md:54` — *"The Dockerfile and CI workflow are written but **were not built/run
> in this environment**."* (`:142` *"Docker/CI defined but never executed here"*)

**Reality:** v1's `docker build` **fails** at `Dockerfile:15 COPY anvil ./anvil → "/anvil": not found`
(E6) — the Dockerfile cannot build this layout at all (no `anvil/` package subdir). That is a harder
defect than "written but idle." (By contrast, v2's Docker/CI genuinely builds and runs — E1–E5.)

### D4 — The "merge" narrative is not in the artifacts, and the two docs disagree on the base
> `MERGED_VERSION_AUDIT.md:31` — *"**Base:** Version A (Anvil)…"* (Anvil base + OIP graft)
> `MERGED_BUILD_AUDIT.md:18,42` — *"the rigorous **OIP spine**…"*, *"from OIP-0 … still the spine."* (OIP base + Anvil graft)

**Reality:** on disk there is **no single merged codebase**. `v1` (package `anvil`) and `v2` (package
`oip`) are two **independent, non-overlapping** implementations — different package names, layouts,
dependencies, and test suites; neither contains the other's modules. v2 concretely **lacks** the very
Anvil features it claims to graft in: regime model, higher-order Greeks, beta-weighted risk book,
broker connectors, execution gateway, and agent are all **absent** from v2 (see §5). The described
merge did not happen in these artifacts.

### D5 — The Python-3.12 pin rationale is stale
> `v1/Dockerfile:2–3` — *"Host runs Python 3.14 (bleeding edge); some broker SDKs (growwapi ≤3.13) and
> quant wheels lag."*  `v2/backend/Dockerfile:2–3` — *"several quant wheels (py_vollib, scipy, etc.)
> may not yet ship cp314 wheels, so all backend dev/test/CI runs in this container."*

**Reality:** on this host, **`py_vollib 1.0.12`, `vollib 1.0.11`, `pyarrow 24.0.0`, `scipy 1.17.1`,
`pandas 3.0.3`, `duckdb 1.5.4` all install cleanly on Python 3.14** (E11), and v2's full suite + demo
pass **identically on 3.14 and 3.12** (E12/E13 vs E3/E5). The stated blocker for running off-container
no longer holds.

---

## 8. Reproduction (exact commands)

```bash
# --- v2 on canonical Docker 3.12 ---
cd "v2" && docker compose build
docker compose run --rm backend pytest -m "unit or validation" --strict-markers -q   # 176 passed, 1 deselected
docker compose run --rm backend pytest -q                                            # 176 passed, 1 skipped
docker compose run --rm backend ruff check .                                         # clean
docker compose run --rm backend python scripts/demo_phase0.py --underlying NIFTY     # [PASS] exit 0

# --- v1 Docker (fails) ---
docker build -t anvil:ci v1                          # ERROR: COPY anvil ./anvil -> "/anvil": not found

# --- v1 host 3.14, as-shipped (fails) ---
v1/.venv/Scripts/python -m pytest -q                 # 10 collection errors: No module named 'anvil'

# --- v1 host 3.14, intrinsic (passes) — junction so `anvil` resolves, repo untouched ---
mklink /J %TEMP%\anvil_audit\anvil  "<abs path>\v1"
set PYTHONPATH=%TEMP%\anvil_audit  & set PYTHONDONTWRITEBYTECODE=1
v1/.venv/Scripts/python -m pytest %TEMP%\anvil_audit\anvil\tests -q -p no:cacheprovider   # 97 passed
rmdir %TEMP%\anvil_audit\anvil       # remove junction only (never the target)

# --- v2 host 3.14 ---
py -3.14 -m venv %TEMP%\oip_venv
%TEMP%\oip_venv\Scripts\python -m pip install numpy scipy pandas pyarrow duckdb vollib py_vollib \
   pydantic pydantic-settings fastapi "uvicorn[standard]" requests python-dateutil tzdata pytest httpx ruff
set PYTHONPATH=<abs path>\v2\backend\src
%TEMP%\oip_venv\Scripts\python -m pytest -q          # (run from v2/backend) 176 passed, 1 skipped
%TEMP%\oip_venv\Scripts\python scripts/demo_phase0.py --underlying NIFTY    # [PASS] exit 0
```

---

## 9. Artifacts created during the audit (disclosure)

Running v2's demo/tests through the repo's **own** bind-mount / default data dir produced gitignored
runtime output under `v2\data\` (`snapshots\*.parquet`, `oip.sqlite`, `calibration.duckdb`) — this is
the demo doing what it is designed to do. The `%TEMP%\oip_venv` venv and the `%TEMP%\anvil_audit`
junction were created outside the repos; the junction has been removed and `v1` verified intact.
**No source or configuration file in `v1`/`v2` was modified.**
