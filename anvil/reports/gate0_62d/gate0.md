# Gate-0 — certification report

> **PROVISIONAL — plumbing validation on 62 trading days, NOT the real go/no-go.** Mainly exercises the resolved targets (conviction/equity); touch/vrp stay identity until depth. Re-certify on the full backfill before trusting any verdict here.

## Verdict: ⛔ NO-GO / ABSTAIN

NO-GO / ABSTAIN — no target sustains the bar yet. 'Not enough evidence' is a correct, honest outcome on this depth; re-certify when the backfill lands.

- **Window:** 2025-09-01 → 2025-11-28
- **Gate / calibration version:** `phase0-1.1.0` / `phase2-1.0.0`
- **Generated:** 2026-06-22T09:53:48.983205+00:00
- **Pass bar:** ≥ 0.65 calibrated accuracy at ≥ 0.1 coverage; operating cell headline-eligible (DSR ≥ 0.95, PBO ≤ 0.5, Harvey t ≥ 3, both OOF edges > 0); trials counted; EV > 0.

## Per-target accuracy / EV at coverage

| target / source | n | calib | op τ | coverage | cal. accuracy | realized EV | DSR | PBO | t | headline | trials | verdict |
|---|--:|:--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|:--:|
| conviction/tip_backtest | 212 | yes | 0.50 | 85.8% | 74.8% | 0.3766 | 0.975 | 0.371 | 2.636 | no | 92 | abstain |
| equity/tip_backtest | 440 | yes | 0.95 | 0.0% | — | — | — | — | — | no | 92 | abstain |

- **conviction/tip_backtest abstains:** battery not headline-eligible (DSR/PBO/t/OOF-edge)
- **equity/tip_backtest abstains:** battery not headline-eligible (DSR/PBO/t/OOF-edge); coverage 0.0 < 0.1; calibrated accuracy None < 0.65; EV-at-coverage None not positive

_Operating point τ is set on EV × coverage (the money frontier) where a P&L target exists, else on the accuracy frontier. Coverage / accuracy / EV are OUT-OF-FOLD (test-fold) numbers at that τ. Every threshold sweep is counted in the trial registry, so the Deflated-Sharpe bar rises with search — abstaining here is honest, not a bug._
