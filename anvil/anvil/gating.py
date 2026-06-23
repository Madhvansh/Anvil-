"""Phase 4 emission interlock — the runtime gate on actionable/sized output (ADR 0006).

``personal_mode_armed()`` = ``ANVIL_PERSONAL_MODE`` is on AND Gate-0 has passed (at least one
validation cell clears the kill-switch bar). Until both hold the engine serves PUBLIC analytics only
— no sized/actionable tickets — honoring "don't emit sized personal tips until Gate-0 passes" as a
RUNTIME invariant, so the day the full-depth re-cert clears the gate it flips live with no code
change. Fail-closed: any error or missing verdict => not armed.
"""

from __future__ import annotations

from .config import SETTINGS

_HARVEY_T_BAR = 3.0  # Harvey-Liu minimum t-stat for a certified cell (the Gate-0 bar)


def gate0_passed(validation_store=None) -> bool:
    """True iff at least one validation cell has cleared the gate (headline-eligible AND t ≥ 3).

    Reads the SAME ``TipValidationStore`` the gate writes (``headline_eligible`` is set only when a
    cell clears the DSR/PBO/Harvey-t battery). ``validation_store`` may be injected (tests); otherwise
    it is opened and closed here. Conservative: returns False on any error."""
    own = validation_store is None
    store = validation_store
    try:
        if store is None:
            from .tips.store import TipValidationStore

            store = TipValidationStore()
        for cell in store.all() or []:
            if cell.get("headline_eligible") and float(cell.get("t_stat") or 0.0) >= _HARVEY_T_BAR:
                return True
        return False
    except Exception:  # noqa: BLE001 - fail closed: an unreadable verdict must not arm emission
        return False
    finally:
        if own and store is not None:
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass


def personal_mode_armed(validation_store=None) -> bool:
    """Actionable/sized output may be emitted only when BOTH personal mode is on AND Gate-0 passed."""
    return bool(SETTINGS.personal_mode) and gate0_passed(validation_store)
