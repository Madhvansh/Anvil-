"""Calibration: the moat. Log probabilistic forecasts, resolve them against realized outcomes,
and score how well-calibrated they are (Brier, log-loss, reliability diagram, band coverage).

This is what turns "accuracy" from a claim into an auditable, compounding asset. The data model is
append-only and reproducible, mirroring the storage discipline of the rest of the platform.
"""
