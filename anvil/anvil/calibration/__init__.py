"""Phase 2 — the calibration layer.

Turns each target's RAW score into a CALIBRATED probability (pure-numpy isotonic / scipy Platt /
honest identity), measures the gain OUT-OF-FOLD, sets the abstain threshold from MEASURED coverage,
and persists auditable, source-class-firewalled calibrators. Calibration is the honesty rail + the
precondition for honest sizing — it is deliberately NOT wired into the gate's certification (that
would be circular) and never changes sizing math.
"""

from __future__ import annotations

# Freshness rail (parallel to tips.store.GATE_VERSION). Defined FIRST so the submodules below — and
# service.py's ``from . import CALIBRATION_VERSION`` — resolve during package import.
CALIBRATION_VERSION = "phase2-1.0.0"

from .combine import (  # noqa: E402
    LogisticStacker,
    combine_calibrated,
    ledoit_wolf_cov,
    whiten_inputs,
)
from .conformal import (  # noqa: E402
    AdaptiveConformal,
    mondrian_thresholds,
    risk_coverage_threshold,
)
from .crossval import oof_calibration_metrics, oof_predictions  # noqa: E402
from .isotonic import (  # noqa: E402
    BlendedCalibrator,
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    calibrator_from_params,
    fit_calibrator,
    pav_isotonic,
)
from .service import CalibrationService, fit_all_targets  # noqa: E402
from .store import CalibratorRecord, CalibratorStore  # noqa: E402

__all__ = [
    "CALIBRATION_VERSION",
    "pav_isotonic",
    "fit_calibrator",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "IdentityCalibrator",
    "BlendedCalibrator",
    "calibrator_from_params",
    "oof_calibration_metrics",
    "oof_predictions",
    "risk_coverage_threshold",
    "mondrian_thresholds",
    "AdaptiveConformal",
    "whiten_inputs",
    "combine_calibrated",
    "ledoit_wolf_cov",
    "LogisticStacker",
    "CalibratorStore",
    "CalibratorRecord",
    "CalibrationService",
    "fit_all_targets",
]
