# Handoff — Options Intelligence Platform
What I did
I penetrated the entire codebase with a read-only multi-agent workflow (8 agents across 7 domains + a completeness critic, 202 tool calls) plus direct reads of every keystone file and the full git history, then wrote a comprehensive single source-of-truth handoff and verified every operational claim by actually running the suite in Docker.

The deliverable — handoff.md (13 sections)
§1–3 — honest TL;DR status, the mission/rails, and the build timeline (Phase 0 → hardening → strategy docs → Increment 1, plus the dirty working tree).
§4–5 — the methodology (test-first against an independent oracle, reproducibility, code-enforced honesty flags) and an architecture diagram + module map.
§6 — module-by-module deep-dive: domain model, the Black-76 engine (formulas, raw-vs-presentation units, the r ∈ (−0.5,1.0) guard), data layer (cost-of-carry forward + provenance), storage/pipeline (snapshot_id semantics), analytics (OI/vol/GEX/implied-dist with verbatim warnings), the calibration moat seed, the API/frontend/demo.
§7–9 — tests & markers, verified Docker evidence, ADRs at a glance.
§10–13 — risks, prioritized roadmap + my concrete ideas, a map of how the scattered strategy docs relate, and a next-session quickstart.
Verified evidence baked into §8 (real run, Python 3.12 image)
ruff: All checks passed
177 tests collected, 176 pass / 1 skipped (the empty broker_validation fixture) — so the audit's "176 tests pass" is confirmed, not an inherited claim
Demo: [PASS] reproducibility check — all 10 legs re-read byte-stable (tol=1e-09)
Corrections I caught and folded in (the inherited docs were wrong/incomplete)
The "176 tests" needed grounding — it's 177 collected / 176 passing, expanded from 80 functions via parametrization.
ADR 0005 is the Python-3.12 Docker pin, not a "spot→futures" ADR.
The backtester look-ahead/survivorship guards the rails promise do not exist yet — flagged as aspirational.
The calibration ledger has zero production callers (empty moat) — called out as the single most important fact.
The snapshot_id overwrite footgun and the non-standard PHASE1_BACKLOG- not anvil.md filename.
> **Single source-of-truth for anyone (human or a fresh Claude session) picking up this repo.**
> It documents the *complete codebase in depth*, what was built and why, the methodology, the honest
> current state, the risks, and the road ahead. Where other docs disagree with the code, **the code
> wins and this document says so.**
>
> _Author: Claude (Claude Code). Date: 2026‑06‑18. Status: Phase 0 + hardening + Increment 1._

> **Disclaimer (a hard rail, not boilerplate).** Everything this platform produces — including Greeks
> — is *computed analytics* and *probabilistic context*, **not investment advice**. No accuracy or
> guaranteed return is claimed anywhere. The disclaimer is enforced in code
> ([constants.py](backend/src/oip/constants.py)) and printed on every output surface.

---

## 0. How to use this document

- **New here? Read §1 (status), §2 (mission), §5 (architecture), then §13 (quickstart).**
- **Going to write code? Read §4 (methodology), §6 (deep-dive), §7 (tests), §10 (risks).**
- **Deciding what to build next? Read §10 (gaps) and §11 (roadmap & ideas).**
- **Confused by the many strategy docs in the repo? Read §12 (document map).**

**Table of contents**

| # | Section |
|---|---|
| 1 | TL;DR — honest status |
| 2 | Mission & non-negotiable rails |
| 3 | Past actions — the build timeline |
| 4 | Methodology — how this codebase is built |
| 5 | Architecture overview |
| 6 | Codebase deep-dive (module by module) |
| 7 | Tests & quality |
| 8 | Verified evidence (this session's Docker run) |
| 9 | Architecture decisions (ADRs) at a glance |
| 10 | What's missing & the real risks |
| 11 | Roadmap, next increments & my ideas |
| 12 | Document map & repo orientation |
| 13 | Next-session quickstart |

---

## 1. TL;DR — honest status

The repo is a **calibrated options-intelligence platform for Indian markets (NSE/BSE)**. As of this
handoff it is a **correct, broad, test-first analytics foundation with an empty moat** — roughly
**one‑fifth of the way to a monetizable product**.

**What is real and demonstrable:**
- A **futures-correct Black‑76 Greeks engine** (Indian index options settle off futures, not spot),
  validated by an independent oracle, put-call parity, finite differences, IV round-trips, and a
  third-party library cross-check.
- An **offline, reproducible pipeline**: fixture chain → normalize → Greeks → DuckDB+Parquet/SQLite
  → FastAPI → static page, with a byte-stable reproducibility self-check.
- A **broad analytics surface** computed on the futures-correct engine: OI (PCR, max-pain, walls,
  buildup), vol (ATM IV, smile, skew, IV rank/percentile), **GEX + zero-gamma flip**, and a
  **Breeden-Litzenberger implied distribution** — each carrying explicit honesty flags.
- A **calibration-ledger substrate** (Brier / log-loss / reliability / coverage scoring + an
  append-only, reproducible forecast→outcome store).

**What is NOT here yet (be brutally clear):**
- **The moat is an empty vessel.** Nothing produces forecasts, so `log_forecast()` has **zero
  production callers** and the reliability curve has **zero track record**.
- **No backtesting lab.** The look-ahead / survivorship guards that the rails *promise as failing
  tests* **do not exist yet** — they are aspirational, not implemented.
- **No risk book, no live data, no copilot, no regime model, no higher-order Greeks.**
- **No UI for the new analytics** — the static page still renders only chain + Greeks.
- **Multi-index is config-only** — 7 indices are configured but **only NIFTY has a fixture**.

**One-line verdict:** *a materially trustworthy foundation with the moat scaffolded but empty; the
hard, monetizable 80% (forecasts → ledger, backtest lab, risk book, UI, live data) is still ahead.*

---

## 2. Mission & non-negotiable rails

**Mission** (from [NORTH_STAR.md](NORTH_STAR.md)): build the options-intelligence platform that wins
on **trust, not hype** — every forecast is a *probability* shown with its *live, auditable
calibration track record*; plus a cross-broker unified risk view and an AI analyst grounded in the
user's real positions. Primary user: a **directional / buyer-leaning trader**.

**Hard rails — do not cross** (from [CLAUDE.md](CLAUDE.md) / [NORTH_STAR.md](NORTH_STAR.md)):
1. **Calibrated, not "accurate."** Forecasts are probabilities/distributions, never point targets.
   Calibration (Brier, reliability diagram, coverage) is computed on realized outcomes and shown
   alongside every forecast. No "accuracy"/guaranteed-return claims anywhere. Disclaimer on every
   forecast surface.
2. **Correctness is earned.** Quant code is **test-first**; nothing merges without a passing check.
3. **Backtester guards are failing tests** (look-ahead & survivorship) — not warnings. *(Not built
   yet; see §10.)*
4. **Greeks are Black‑76 on the futures price** (validated against broker values; Kite does not serve
   Greeks via API).

Everything outside these is open to design at the plan gate.

---

## 3. Past actions — the build timeline

Four commits on `main`, then an uncommitted working-tree shuffle.

| Commit | What it delivered |
|---|---|
| `a381a28` **Phase 0 foundation** | The end-to-end thin slice: `ingest → Black‑76 Greeks → store → query → display`. 66 files / ~3,620 lines: engine, domain model, data adapters, storage, pipeline, API, static page, the full quant test suite, 6 ADRs, CI, Docker, fixtures. |
| `76c317a` **Phase 0 hardening** | Applied **11 confirmed findings** from an adversarial multi-agent review: tightened `black76` input guards, `normalize` defensiveness, storage round-trip (int/null handling, JSON-safety), SQLite WAL/threadpool safety, and added regression tests. |
| `d0d8992` **Strategy docs** | Added [`COMPARISON_AND_MERGE.md`](COMPARISON_AND_MERGE.md) + [`MERGED_BLUEPRINT.md`](MERGED_BLUEPRINT.md) — the two-version comparison and the merge plan. |
| `c09c07c` **Increment 1** | The analytics breadth + moat seed graft. 23 files / ~1,241 lines: `analytics/` (oi, vol, gex, implied_dist, util), `calibration/` (scoring, ledger), multi-index `config.py`, the `/analytics` + `/calibration` API, and their tests. |

**Working tree right now (uncommitted):**
- `D docs/PHASE1_BACKLOG.md` — deleted from tracking…
- `?? docs/PHASE1_BACKLOG- not anvil.md` — …and re-added under a **non-standard filename** (this is
  the real, current backlog — see §11). *Recommend renaming back to `docs/PHASE1_BACKLOG.md`.*
- `?? MERGED_BUILD_AUDIT.md` — the brutal as-built audit (untracked; should be committed).
- `?? Anvil-vs-VersionB-Comparison.md` — historical dossier of the "other version" (Anvil) used to
  drive the merge; reference only, not part of the product.

> **Note on "the other version (Anvil)."** Earlier work explored two versions of this idea. This repo
> is the **merged** version: the rigorous OIP spine (this codebase) with Anvil's analytics breadth
> grafted on. Anvil still has things this repo doesn't yet (regime model, higher-order Greeks,
> beta-weighted risk book, gated execution seam) — those are roadmap items, not present here.

---

## 4. Methodology — how this codebase is built

The discipline is the product's credibility, so it's worth internalizing before changing anything.

- **Test-first quant, validated against an *independent* oracle.** The engine is never checked
  against itself. [conftest.py](backend/tests/conftest.py) hand-writes a separate SciPy `Black76Reference`;
  correctness is pinned by **five independent strategies**: known closed-form values, **put-call
  parity** (`C − P = e^{−rt}(F − K)`, model-agnostic), **finite-difference** cross-checks of every
  analytic Greek, **IV round-trip** (`implied_vol(price(σ)) == σ`), and a **third-party `py_vollib`
  agreement** check. Plus the Black‑76 identity `ρ == −t·price` at `rel 1e-10`.
- **Reproducibility as a self-check, not a hope.** Re-ingesting the same fixture yields the same
  deterministic `snapshot_id`, overwrites the same Parquet, and the demo asserts re-read Greeks equal
  freshly-computed ones to `1e-9`. ISO-string timestamps avoid float/timezone drift. The
  `engine_version` and `iv_used` are stored with every Greek so results are reproducible from storage.
- **Units & conventions are explicit and centralized.** The engine returns **raw academic units**;
  the *only* place they're scaled for display (θ/365, vega/100, ρ/100) is
  [greeks_service.py](backend/src/oip/quant/greeks_service.py). This keeps the math a clean oracle and
  prevents 100× unit mistakes.
- **Honesty is a code-enforced contract, not a doc.** The `DISCLAIMER` ships on every API payload;
  unvalidated analytics carry boolean flags (`needs_nse_validation`, `needs_real_world_calibration`);
  the empty calibration endpoint says so in its `note`. Removing them is a code change, reviewable.
- **Provenance is auditable.** `FuturePriceSource` records whether the Black‑76 forward was a real
  NSE future or a derived cost-of-carry forward, so a derived-forward Greek is never mistaken for a
  real-future one.
- **Decisions are durable.** Every accepted architecture choice is a short dated ADR in
  [docs/decisions/](docs/decisions/) (decision + why); deferrals are logged in the Phase-1 backlog so
  future sessions inherit context.
- **Workflow:** explore → plan → implement → verify → commit. Non-trivial work is planned at a gate
  before coding; the build is verified with a runnable check and the evidence shown (this handoff's
  §8 is an instance).

---

## 5. Architecture overview

A single Python 3.12 service. Phase 0 is offline-first with zero credentials.

```
                ┌────────────── DataSource (Protocol) ──────────────┐
 committed JSON │  FixtureDataSource (offline, deterministic)        │   Kite/Groww (Phase 1, drop-in)
   fixtures ───►│  NsePublicDataSource (capture-only, non-gating)    │
                └───────────────────────┬───────────────────────────┘
                                        │ raw NSE payload
                                        ▼
                              normalize.py  ──►  OptionChain  (spot + futures price + provenance)
                                        │            (Pydantic, frozen)
                                        ▼
                       greeks_service.compute_chain_greeks
                                        │   (Black‑76 on F; raw units → presentation units)
                                        ▼
                              pipeline.ingest ──►  DuckStore (Parquet lake)   +  SqliteMeta (registry/audit)
                                        │              chain.parquet / greeks.parquet      instruments/snapshots/ingest_runs
                                        ▼
                       FastAPI  /chain  /greeks  /analytics/{u}  /calibration  /health
                                        │           (analytics computed live; chain/greeks read from store)
                                        ▼
                        static app.js + index.html  (renders chain+Greeks today)

   parallel substrate:  calibration/ ── scoring.py (Brier/log-loss/reliability/coverage)
                                       └ ledger.py  (append-only forecast→outcome DuckDB store)  ← EMPTY
```

**Module map** (`backend/src/oip/`):

| Package | Responsibility |
|---|---|
| [domain/](backend/src/oip/domain/) | Frozen Pydantic models (`OptionChain`, `ChainRow`, `OptionQuote`, `GreeksResult`) + enums |
| [quant/](backend/src/oip/quant/) | `black76.py` math oracle + `greeks_service.py` chain-level orchestration & scaling |
| [data/](backend/src/oip/data/) | `DataSource` protocol, fixture replay, NSE capture, normalization |
| [storage/](backend/src/oip/storage/) | DuckDB+Parquet lake (`duck.py`), SQLite metadata (`sqlite_meta.py`, `schema.sql`) |
| [pipeline/](backend/src/oip/pipeline/) | `ingest.py` end-to-end orchestration + deterministic `snapshot_id` |
| [analytics/](backend/src/oip/analytics/) | oi, vol, gex, implied_dist, util — positioning/structure signals |
| [calibration/](backend/src/oip/calibration/) | scoring + append-only ledger (the moat seed) |
| [api/](backend/src/oip/api/) | FastAPI app, deps, services, routes, static frontend |
| [config.py](backend/src/oip/config.py) · [constants.py](backend/src/oip/constants.py) | Settings (env `OIP_*`), index reference data, disclaimer, IST |

---

## 6. Codebase deep-dive (module by module)

### 6.1 Domain model & enums — [domain/models.py](backend/src/oip/domain/models.py), [domain/enums.py](backend/src/oip/domain/enums.py)

The internal, normalized language the whole platform speaks. All models are **frozen Pydantic
`BaseModel`s** (immutable → reproducible).

- **`OptionQuote`** — one side of a strike: `last_price, bid, ask, oi, volume, iv_source`.
  **`iv_source` is a DECIMAL** (`0.12` = 12%), not a percent — NSE percentages are divided by 100 at
  normalization.
- **`ChainRow`** — `strike, expiry, call: OptionQuote|None, put: OptionQuote|None`.
- **`OptionChain`** — `underlying, exchange, spot, future_price, future_price_source, snapshot_ts
  (tz-aware IST), risk_free_rate (decimal), rows`. **`future_price` is the Black‑76 input, never
  spot.** Property `.strikes`.
- **`GreeksResult`** — presentation-unit Greeks for one leg, **carrying the inputs that produced it**
  (`iv_used, t_years, price_model, engine_version`) so every Greek is reproducible from storage.
- **Enums** (`StrEnum`, serialize as their value): `OptionType` (`CALL='c'`, `PUT='p'` — single-char
  flags flow straight into the engine), `Exchange` (`NSE`/`BSE`), `FuturePriceSource`
  (`nse_futures` / `derived_cost_of_carry` / `kite` / `fixture`).

### 6.2 Quant engine — [quant/black76.py](backend/src/oip/quant/black76.py), [quant/greeks_service.py](backend/src/oip/quant/greeks_service.py)

The heart of "correctness is earned." `ENGINE_VERSION = "black76-1.0.0"`.

**`black76.py` — a raw-unit math oracle.** Pricing/IV use `py_vollib` (the `black` module) when
importable, with a **self-contained SciPy/NumPy closed form as fallback**; analytic Greeks are always
closed-form here. Public functions: `price`, `delta`, `gamma`, `vega`, `theta`, `rho`, `implied_vol`,
`all_greeks` (returns the frozen `Greeks` dataclass). Key conventions & guards:

- **Raw units:** price in currency; δ/γ dimensionless; **vega per 1.00 (100%) vol**; **theta per
  YEAR**; **rho per 1.00 (100%) rate**.
- **Formulas:** `d1 = (ln(F/K) + ½σ²t)/(σ√t)`, `d2 = d1 − σ√t`, `df = e^{−rt}`. Call `df(F·N(d1) −
  K·N(d2))`; gamma `df·n(d1)/(F·σ√t)`; vega `df·F·n(d1)·√t`; **`rho = −t·price`** exactly (r enters
  only via `df`).
- **Input guards** (`_validate`): `F,K,t > 0`; **`r` must be a *decimal* in `(−0.5, 1.0)`** — this
  catches the percent-vs-decimal mistake (passing `6.5` instead of `0.065` raises rather than
  silently mispricing the whole chain); `σ > 0`. NaN/inf rejected.
- **Option-type aliases:** `c/p/call/put/ce/pe` all accepted (`ce`/`pe` are Indian conventions).

**`greeks_service.py` — chain orchestration + the *only* unit scaling.** `compute_chain_greeks`
iterates the chain, computes `t = year_fraction(...)` (**ACT/365 to 15:30 IST market close**; naive
timestamps assumed IST), **skips** legs with `t ≤ 0` or no usable IV (if `iv_source` is missing it
backs IV out of `last_price`; if that fails, the leg is **silently skipped, never guessed**), and
scales raw → presentation: **`theta_per_day = θ/365`, `vega_per_pct = vega/100`, `rho = ρ/100`.**

> ⚠️ **Footguns:** (a) raw-vs-presentation units — never compare engine output to a broker terminal
> without scaling; (b) a naive (`tzinfo`-less) `snapshot_ts` is *silently* treated as IST — a UTC
> timestamp would make `t_years` (and thus every Greek) wrong; (c) skipped legs are silent — a low
> Greek `row_count` means missing IVs, not a bug.

### 6.3 Data layer — [data/source.py](backend/src/oip/data/source.py), [data/fixture_replay.py](backend/src/oip/data/fixture_replay.py), [data/nse_public.py](backend/src/oip/data/nse_public.py), [data/normalize.py](backend/src/oip/data/normalize.py)

- **`DataSource` (runtime-checkable Protocol)** — the single seam: `fetch_chain(ChainRequest) →
  OptionChain`, `list_expiries(underlying) → list[date]`, properties `name`, `requires_credentials`.
  Kite/Groww are future drop-ins.
- **`FixtureDataSource`** — offline replay of committed JSON; picks the **latest fixture by lexical
  ISO-date sort**; `requires_credentials = False`.
- **`NsePublicDataSource`** — **capture-only** (warms cookies, GETs the public option-chain endpoint).
  Used by [scripts/record_fixture.py](backend/scripts/record_fixture.py); **not** a resilient live
  source (no retry/rate-limit/schema-drift handling) — hardening is Phase-1 work.
- **`normalize.py`** — converts a raw NSE payload into an `OptionChain`. NSE exposes only **spot**, so
  when no real future is supplied it **derives a cost-of-carry forward `F = spot·e^{(r−q)t}` (q≈0 for
  short-dated NIFTY)** and tags `future_price_source = derived_cost_of_carry`. Defensive: blank/`-`
  IVs → `None` (one bad leg never aborts the chain); expiry auto-selection **skips already-expired
  (`t ≤ 0`) contracts**; `underlying` canonicalized uppercase; NSE day-first dates (`26-Jun-2026`)
  parsed explicitly (never via `fromisoformat`).
- **Fixture shape** — [data/fixtures/nse_chain_NIFTY_2026-06-12.json](data/fixtures/nse_chain_NIFTY_2026-06-12.json):
  a wrapper `{_oip_meta: {future_price: 22014.5, source: nse_futures, risk_free_rate: 0.065, …}, raw:
  {records: {…NSE shape…}}}` with **5 strikes (21500–22500), 26-Jun-2026 expiry**. The `_oip_meta`
  lets a fixture inject a real recorded future without touching the raw payload. *(Marked "synthetic
  but realistically shaped — NOT live market data.")*

### 6.4 Storage + pipeline — [storage/duck.py](backend/src/oip/storage/duck.py), [storage/sqlite_meta.py](backend/src/oip/storage/sqlite_meta.py), [storage/schema.sql](backend/src/oip/storage/schema.sql), [pipeline/ingest.py](backend/src/oip/pipeline/ingest.py)

- **`DuckStore`** — a Parquet "lake" read via in-process DuckDB SQL. `write_snapshot` / `write_greeks`
  partition by `underlying` + `snapshot_date`; `read_chain_with_greeks` does a **LEFT JOIN on
  (snapshot_id, strike, option_type, expiry)** (Greek columns are NULL if not yet computed).
  `_records/_clean` make output **JSON-safe**: Timestamps → ISO strings, NaN/NaT → None, and `oi`/
  `volume` are coerced back to `int` after Parquet's null-induced float promotion.
- **`SqliteMeta`** — operational metadata only (pointers, not data). Opened with
  `check_same_thread=False`, **WAL** + `busy_timeout` for FastAPI's threadpool. Tables (from
  [schema.sql](backend/src/oip/storage/schema.sql)): **`instruments`** (symbol/name/exchange/lot_size/
  kind), **`snapshots`** (registry → chain/greeks Parquet paths, `row_count`, indexed on
  `(underlying, snapshot_ts)`), **`ingest_runs`** (audit: status/started/finished/error).
- **`ingest()`** — fetch → `compute_chain_greeks` → `write_snapshot`/`write_greeks` →
  `register_snapshot` → `record_ingest_run`; **on any exception it records an `error` run, then
  re-raises**. `snapshot_id_for = f"{underlying}_{expiryYYYYMMDD}_{tsYYYYMMDDTHHMMSS}_{source}"` —
  **deterministic, but NOT a content hash**, and built from **`rows[0].expiry`** only.

> ⚠️ **`snapshot_id` is a reproducibility *and* a footgun.** Same fixture → same id → idempotent
> overwrite (good, makes the demo's self-check meaningful). But if a *live* source returns different
> data for the same `(underlying, expiry, ts, source)`, it **silently overwrites** the old snapshot.
> A content-hash id is the recommended Phase-1 fix (see §11). `row_count` is the **Greeks** count
> (legs with IV), not chain legs.

### 6.5 Analytics — [analytics/oi.py](backend/src/oip/analytics/oi.py), [vol.py](backend/src/oip/analytics/vol.py), [gex.py](backend/src/oip/analytics/gex.py), [implied_dist.py](backend/src/oip/analytics/implied_dist.py), [util.py](backend/src/oip/analytics/util.py)

Increment 1's breadth. All computed **on the futures price** (ATM = strike nearest **`future_price`**,
not spot — a common surprise). [util.py](backend/src/oip/analytics/util.py) provides `chain_t_years`,
`atm_strike`, and `effective_iv` (reported IV, else backed out of `last_price`).

- **OI** — `pcr_oi` / `pcr_volume` (Σput/Σcall); **`max_pain`** = strike minimizing total writer
  payout `Σ max(S−K,0)·callOI + max(K−S,0)·putOI` over all strikes; `oi_walls` (top-N call resistance
  / put support by OI); **`classify_buildup`** 4-state matrix on (Δprice, ΔOI):
  long_buildup / short_buildup / short_covering / long_unwinding.
- **Vol** — `atm_iv` (mean of call/put effective IV at ATM); `iv_smile` (per-strike (call_iv,
  put_iv)); **`skew`** = OTM-put-IV − OTM-call-IV at ±wing% (positive = the usual equity-index
  downside skew); `iv_rank` / `iv_percentile` over a caller-supplied **history** (returns `None`
  until ≥2 samples — and *nothing currently captures that history*, see §10).
- **GEX** — [gex.py](backend/src/oip/analytics/gex.py): per-strike `gamma·OI·lot_size·F²·0.01`, signed
  **`+` call / `−` put by default × `dealer_sign`**; `total_gex`, `call_walls`/`put_walls`, and a
  **zero-gamma flip** found by gridding `F·(1±12%)` in 240 steps and linearly interpolating the
  sign change nearest spot. **`needs_nse_validation = True` (always).** The docstring warns verbatim:
  *"⚠️ NEEDS LIVE NSE VALIDATION… treat GEX levels/flip as a HYPOTHESIS, not a calibrated signal."*
- **Implied distribution** — [implied_dist.py](backend/src/oip/analytics/implied_dist.py): two
  expected-move proxies (`em_atm_iv = F·σ_atm·√t`; `em_straddle` = ATM call+put price) and a
  **Breeden-Litzenberger risk-neutral density** `f(K) = e^{rt}·∂²C/∂K²` via a **non-uniform second
  difference** over Black‑76 call prices, clipped ≥0 and normalized to integrate to 1, with
  `prob_above` / `prob_inside` queries. **`needs_real_world_calibration = True`** — it's
  *risk-neutral*, not a real-world forecast. Needs ≥3 strikes; assumes sticky-strike.

### 6.6 Calibration — the moat seed — [calibration/scoring.py](backend/src/oip/calibration/scoring.py), [calibration/ledger.py](backend/src/oip/calibration/ledger.py)

The differentiator's substrate. **Built and tested, but dormant.**

- **`scoring.py`** (pure functions, known-value tested): **Brier** `mean((p−o)²)` (0 perfect, 0.25
  always-50%, 1 worst); **log-loss** (cross-entropy, `ε`-clipped); **`reliability_bins`** (10
  equal-width buckets → `mean_predicted` vs `observed_freq`, the reliability diagram); **`coverage`**
  (fraction of `(lo,hi,realized)` intervals that contain `realized`).
- **`ledger.py`** — append-only **DuckDB** store, two tables: **`forecasts`** (`forecast_id` PK,
  `created_ts`, `underlying`, `horizon`, `kind`, `level_low/high`, `prob`, `model_version`, `regime`,
  `drivers` JSON) and **`outcomes`** (`forecast_id` PK, `resolved_ts`, `realized_value`, `outcome`).
  Four forecast **kinds** (`prob_above`, `prob_below`, `prob_up`, `prob_inside`) whose binary outcome
  is **derived on `resolve()`**. **Reproducible by design:** every id and timestamp is
  **caller-supplied** (no wall-clock); re-logging an id is an **idempotent upsert** (DELETE+INSERT).
  `summary()` returns counts + Brier + log-loss + reliability bins.

> 🟡 **The single most important fact in this repo:** **nothing calls `log_forecast()`.** The schema,
> scoring, and store are real and reproducible, but **zero forecasts are logged → zero track record →
> the moat does not yet exist in usable form.** Starting this loop is the highest-leverage next move
> (§11).

### 6.7 API + frontend + demo — [api/app.py](backend/src/oip/api/app.py), [api/deps.py](backend/src/oip/api/deps.py), [api/service.py](backend/src/oip/api/service.py), [api/analytics_service.py](backend/src/oip/api/analytics_service.py), routes, [static/app.js](backend/src/oip/api/static/app.js), [scripts/demo_phase0.py](backend/scripts/demo_phase0.py)

- **App wiring** ([app.py](backend/src/oip/api/app.py)): `create_app()` adds permissive CORS
  (all origins, **GET only**), includes the chain/greeks/analytics routers, and **mounts static
  LAST** so API routes win (`html=True` → unknown paths serve `index.html`). Dependencies
  ([deps.py](backend/src/oip/api/deps.py)) are **fresh per request** (stateless; generator deps close
  SQLite/DuckDB).
- **Endpoints** (every payload carries `disclaimer`):

  | Method · path | Purpose / shape |
  |---|---|
  | `GET /health` | `{status, datasource, engine_version, disclaimer}` |
  | `GET /chain?underlying=NIFTY[&snapshot_id]` | latest (or specific) chain joined with Greeks, rows grouped by strike; **auto-ingests the fixture if no snapshot exists** |
  | `GET /chain/{snapshot_id}` | a specific stored snapshot (audit/reproducibility); 404 if unknown |
  | `GET /greeks?underlying&strike&option_type[&snapshot_id]` | one leg's Greeks; 400 on bad option type, 404 if strike absent |
  | `GET /analytics/{underlying}` | **live-computed** OI + vol + GEX + implied-dist with honesty flags; 404 if no fixture |
  | `GET /calibration[?underlying]` | ledger `summary()` + a note that it's empty until forecasts are logged |

- **Frontend** ([static/app.js](backend/src/oip/api/static/app.js) + index.html): a single static
  page that fetches `/chain?underlying=NIFTY` and renders call/put legs (price, IV, Δ, Γ, Θ/day,
  Vega/1%). The disclaimer is a **persistent, non-dismissible banner** present in the HTML *before* JS
  runs. **It does NOT call `/analytics` or `/calibration`** — there is no UI for the new analytics.
- **Demo** ([scripts/demo_phase0.py](backend/scripts/demo_phase0.py)): the end-to-end proof and CI
  smoke gate — ingest → Greeks → store → re-read via the query path → assert re-read == freshly
  computed within `1e-9`; **exit 0 on PASS, 1 on any mismatch.**

### 6.8 Config & constants — [config.py](backend/src/oip/config.py), [constants.py](backend/src/oip/constants.py)

- **`Settings`** (pydantic-settings, env prefix `OIP_`): `data_dir` (defaults to `<repo>/data`),
  `datasource` (`fixture`|`nse_public`), `default_risk_free_rate = 0.065`; derived paths for
  fixtures / snapshots / SQLite / calibration DuckDB.
- **Index reference data** — `INDEX_LOT_SIZE` & `INDEX_STRIKE_STEP` for **7 indices** (NIFTY,
  BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX) with `lot_size()`/`strike_step()`
  helpers. **Fallbacks only** — live connectors must read lot sizes from the instrument master.
- **`DISCLAIMER`** — the exact hard-rail string shown everywhere; `IST_TZ = "Asia/Kolkata"`.

---

## 7. Tests & quality

- **Layout:** **80 `test_` functions across 20 files** under [backend/tests/](backend/tests/) (quant
  9 files, data 2, storage 1, pipeline 1, analytics 4, calibration 2, api 2, conftest). **13 of them
  are `@pytest.mark.parametrize`d**, so the *collected* count is higher than 80: this session collected
  **177 tests and 176 pass** (the 1 skipped is the empty `broker_validation` fixture). The
  MERGED_BUILD_AUDIT's "176 tests pass" is therefore accurate — verified in §8.
- **Markers** ([pyproject.toml](backend/pyproject.toml)): **`unit`** (fast, self-contained) and
  **`validation`** (quant correctness) are the **merge gate**; **`broker_validation`** (vs broker-shown
  Greeks — format finalized, fixture empty) and **`nse_live`** (hits NSE) are **non-gating**.
- **The oracle:** [conftest.py](backend/tests/conftest.py)'s hand-written `Black76Reference` (never
  the engine validating itself) + `sample_chain` (3 strikes) / `wide_chain` (9 strikes w/ smile) +
  `tmp_settings` (isolated temp data dir).
- **Tooling:** `ruff` (line-length 100; `E,F,I,UP,B`; ignores `E501`, `B008`); pinned deps in
  [requirements.lock](backend/requirements.lock); CI ([.github/workflows/ci.yml](.github/workflows/ci.yml))
  runs **ruff → `pytest -m "unit or validation" --strict-markers` (gate) → the demo smoke check**,
  with `broker_validation`/`nse_live` as non-gating `continue-on-error` steps. Everything runs in the
  Python 3.12 Docker image (ADR 0005).

---

## 8. Verified evidence (this session's Docker run)

> _Per the project's "show the evidence, don't assert success" rule, this section is filled from an
> actual run in the Python 3.12 Docker image during this handoff._

<!-- EVIDENCE_BLOCK -->
Run on **2026‑06‑18** in the pinned **Python 3.12** image (`docker compose build` → exit 0):

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | **All checks passed!** (exit 0) |
| Collected tests | `pytest --collect-only -q` | **177 tests collected** |
| **Merge gate** | `pytest -m "unit or validation" --strict-markers -q` | **176 passed, 1 deselected** in 24.71s |
| Full suite | `pytest --strict-markers -q` | **176 passed, 1 skipped** in 24.95s |
| Reproducibility demo | `python scripts/demo_phase0.py --underlying NIFTY` | **`[PASS]` — all 10 legs re-read byte-stable (tol=1e‑09)** |

```text
===== RUFF =====
All checks passed!
===== COLLECT-ONLY (true test count) =====
177 tests collected in 13.33s
===== TEST GATE: pytest -m 'unit or validation' =====
176 passed, 1 deselected, 1 warning in 24.71s
===== ALL MARKERS (full count) =====
176 passed, 1 skipped, 1 warning in 24.95s
===== DEMO: reproducibility self-check =====
[PASS] reproducibility check — all 10 legs re-read byte-stable (tol=1e-09).
Disclaimer: computed analytics (Black-76 on the futures price), not investment advice.
```

**Reading the numbers:** **177** tests are collected; **176 pass**. The **1 skipped/deselected** is
`test_broker_validation` — it skips cleanly because [broker_greeks_nifty.json](backend/tests/fixtures/broker_greeks_nifty.json)
has **no rows yet** (the format is finalized; real broker Greeks are Phase‑1 backlog A1). So the
MERGED_BUILD_AUDIT's "176 tests pass" is **accurate and reproduced here** — it's the count of
*passing* tests (177 collected, expanded from 80 `test_` functions via 13 parametrizations).

**One warning** surfaced (non-blocking): `StarletteDeprecationWarning: Using httpx with
starlette.testclient is deprecated` — a FastAPI test-client dependency note, not a code defect; worth
tracking when bumping FastAPI/httpx.
<!-- /EVIDENCE_BLOCK -->

---

## 9. Architecture decisions (ADRs) at a glance

From [docs/decisions/](docs/decisions/) — decision + why (one line each):

| ADR | Decision | Why |
|---|---|---|
| [0001](docs/decisions/0001-stack-python-fastapi-static-frontend.md) | Python 3.12 + FastAPI backend; **static HTML/JS** page in Phase 0 (Next.js deferred) | One container, immediate slice, same JSON API reused later |
| [0002](docs/decisions/0002-offline-first-data-adapters.md) | **`DataSource` protocol**; Phase 0 = fixtures + capture-only NSE; brokers drop in later | Zero credentials, deterministic CI |
| [0003](docs/decisions/0003-storage-duckdb-sqlite-defer-postgres-redis.md) | **DuckDB+Parquet** (snapshots) + **SQLite** (metadata); defer Postgres/Timescale/Redis | Zero infra, hermetic demo + CI |
| [0004](docs/decisions/0004-greeks-black76-pyvollib.md) | **Black‑76 on futures**, py_vollib + SciPy fallback, raw-unit engine + presentation scaling, independent oracle | Indian options settle off futures; own/validate the math |
| [0005](docs/decisions/0005-python-3.12-docker-pin.md) | **Pin Python 3.12 in Docker**; prefer real NSE future, else derived cost-of-carry forward (source-tagged) | Host is 3.14 (quant wheels may lack cp314); reproducible builds + auditable forward |
| [0006](docs/decisions/0006-deferred-backlog-policy.md) | Maintain the **Phase-1 backlog** as the canonical deferral record | Future sessions inherit context |

> **Correction to inherited notes:** ADR 0005 is the *Python-3.12 Docker pin* (the cost-of-carry
> forward is a note *inside* it and in 0004) — it is **not** a standalone "spot→futures" ADR.

---

## 10. What's missing & the real risks

1. **The moat is empty (highest risk).** No forecast producer → `log_forecast()` never called →
   reliability curve has no track record. Calibration credibility takes *months* of logged forecasts;
   not starting the loop is the most expensive delay.
2. **The backtester guards don't exist.** The rails promise look-ahead & survivorship guards as
   *failing tests*; **no such tests are in the repo.** Treat that rail as a TODO, not a control.
   Until it exists, no forecast should be trusted/shown.
3. **GEX is shippable-looking but unvalidated.** US sign/level conventions, raw ₹ magnitudes; flagged
   `needs_nse_validation`. Showing it as a signal today would violate the trust thesis.
4. **Implied distribution is risk-neutral, not calibrated** (`needs_real_world_calibration`), crude
   (sticky-strike, few fixture strikes).
5. **No risk book** — the headline "cross-broker net Greeks + beta-to-Nifty" pillar is absent (Anvil
   has it; this repo doesn't yet).
6. **No delivery surface for analytics** — `/analytics` works but nothing renders it; the page shows
   only chain+Greeks.
7. **Single fixture, single expiry, no live data.** Multi-index is config-only (only NIFTY has data);
   everything runs off one committed snapshot; IV-rank/percentile have no captured history to read.
8. **`snapshot_id` drift footgun** — deterministic but not content-addressed; live re-ingest can
   silently overwrite differing data.
9. **Native runtime is blocked on host** — host Python is 3.14; the quant stack needs the 3.12 Docker
   image (cp314 wheels not yet available). Docker is effectively required.

---

## 11. Roadmap, next increments & my ideas

**Strict priority order (each makes the next worth more):**

1. **Forecast producer → start logging to the ledger.** Even a simple, honest model — e.g.
   **expected-move band probabilities** straight from the implied distribution (`prob_inside`,
   `prob_above`) — logged daily via `log_forecast()` and resolved against realized index levels.
   *This starts the moat clock and exercises the whole loop end-to-end; it is the single
   highest-leverage thing left.*
2. **Honest backtesting lab** — walk-forward/OOS by construction, **look-ahead & survivorship guards
   implemented as tests that FAIL the build**, cost/slippage modeling. *Deliverable: a known
   look-ahead violation makes the run fail, not warn.*
3. **Beta-weighted risk book on Black‑76** — consolidate Kite+Groww positions; net Greeks; beta-to-
   Nifty; scenario grid (spot×IV) + Monte-Carlo P&L. *Reconcile to a hand-computed fixture within
   tolerance.*
4. **Real UI** — render the analytics **and the reliability curve** (the curve is the entire pitch).
5. **Live data** — promote `NsePublicDataSource` to resilient; add `KiteDataSource`/`GrowwDataSource`
   (real futures price replaces the derived forward); capture broker-shown Greeks to **activate the
   `broker_validation` gate**.
6. **Regime model + higher-order Greeks (vanna/charm/vomma) → grounded copilot → monetization.**

The deferred work behind each Phase-0 choice (Kite/Groww, NSE hardening, Postgres/Timescale+Redis,
Next.js, native Python, higher-order Greeks) is catalogued in the backlog
([docs/PHASE1_BACKLOG- not anvil.md](docs/PHASE1_BACKLOG-%20not%20anvil.md)) and mapped to the ADR
each was deferred from.

**My concrete suggestions for the next owner (smaller, high-leverage):**
- **Content-hash the `snapshot_id`** (or append a short content hash) so live re-ingest can't silently
  overwrite differing data — closes the §10.8 footgun and makes the lake truly append-only.
- **Capture snapshot history** during ingest so `iv_rank`/`iv_percentile` become meaningful (today
  they always need a history nobody supplies).
- **A daily scheduled "log + resolve" job** is the minimum viable moat starter — pair it with item 1.
- **Add structured logging on skipped legs** in `compute_chain_greeks` so a low Greek `row_count` is
  diagnosable instead of silent.
- **Rename `docs/PHASE1_BACKLOG- not anvil.md` → `docs/PHASE1_BACKLOG.md`** and commit
  `MERGED_BUILD_AUDIT.md` to clean the working tree.

---

## 12. Document map & repo orientation

The repo has many markdown docs; here's what's authoritative vs historical.

| Doc | Role |
|---|---|
| **[CLAUDE.md](CLAUDE.md)** | Project instructions for Claude Code — the non-negotiables & workflow. **Authoritative.** |
| **[NORTH_STAR.md](NORTH_STAR.md)** | Mission & hard rails (the "why" and the rails). **Authoritative.** |
| **[PROJECT_SPEC.md](PROJECT_SPEC.md)** | The founding brief — 7 feature pillars, data layer, phased roadmap. Reference for vision. |
| **[docs/decisions/](docs/decisions/)** | The 6 ADRs — accepted, dated architecture decisions. **Authoritative for "why it's built this way."** |
| **[docs/PHASE1_BACKLOG- not anvil.md](docs/PHASE1_BACKLOG-%20not%20anvil.md)** | The live deferral log + roadmap pillars (Phases 1–6). **Authoritative for "what's next."** (Note the non-standard filename.) |
| **[MERGED_BUILD_AUDIT.md](MERGED_BUILD_AUDIT.md)** | The brutal as-built audit & three-way comparison. Honest status snapshot; **this handoff supersedes/extends it.** |
| **[MERGED_BLUEPRINT.md](MERGED_BLUEPRINT.md)** · **[COMPARISON_AND_MERGE.md](COMPARISON_AND_MERGE.md)** | The pre-build merge plan & version comparison. **Historical** (planning artifacts). |
| **[Anvil-vs-VersionB-Comparison.md](Anvil-vs-VersionB-Comparison.md)** | Dossier of the "other version" (Anvil). **Historical**, but the source of the un-ported features (regime, higher-order Greeks, risk book). |
| **[README.md](README.md)** | Quick start + API table. Good first run; this handoff is the deeper map. |

**Start-here order for a new owner:** this `handoff.md` → README (run it) → MERGED_BUILD_AUDIT (the
honest gaps) → ADRs (the why) → the backlog (the next).

---

## 13. Next-session quickstart

**Prereqs:** Docker (the only hard requirement — the host's Python 3.14 lacks the quant wheels; the
image pins 3.12).

```bash
# from the repo root
docker compose build                                                            # build the 3.12 image

# the merge gate (quant correctness + units)
docker compose run --rm backend pytest -m "unit or validation" --strict-markers -q
docker compose run --rm backend pytest --collect-only -q | tail -1              # true collected count

# end-to-end reproducibility proof (CI smoke gate)
docker compose run --rm backend python scripts/demo_phase0.py --underlying NIFTY

# serve API + page, then open http://localhost:8000/
docker compose up
# try: /health · /chain?underlying=NIFTY · /greeks?underlying=NIFTY&strike=22000&option_type=c
#      /analytics/NIFTY · /calibration?underlying=NIFTY
```

**Where to start Increment 2:** build a minimal **forecast producer** that turns the implied
distribution into band probabilities and calls
[`CalibrationLedger.log_forecast()`](backend/src/oip/calibration/ledger.py), plus a resolver that
calls `resolve()` against realized levels — then surface `summary()`/the reliability curve. That is
the first step that turns this trustworthy foundation into a product with a moat.

> **Re-capturing a fixture (optional, needs live NSE):**
> `docker compose run --rm backend python scripts/record_fixture.py --underlying NIFTY` — writes a new
> dated fixture (with `future_price=null` → derived forward until the real NSE futures quote is wired
> in, ADR 0005 / backlog A2).
