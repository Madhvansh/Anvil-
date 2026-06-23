"""Compliance guardrail for agent output.

Anvil is analytics/education, not advice. This blocks any text that crosses into an actionable
recommendation, a price target, or a performance/guarantee claim — the things that trigger SEBI
Research-Analyst obligations or are independently actionable as misleading. Heuristic and
deliberately strict: when in doubt, flag.
"""

from __future__ import annotations

import re

# Each pattern is (label, compiled regex). Case-insensitive.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("actionable_call", re.compile(r"\b(buy|sell|short|go\s+long|book\s+profit|square\s+off)\b\s+"
                                   r"(this|the|that|nifty|banknifty|finnifty|sensex|\d|it|now|today|"
                                   r"calls?|puts?|ce|pe|the\s+\w+)", re.I)),
    ("recommendation", re.compile(r"\b(i|we)\s+(recommend|suggest|advise)\b|\byou\s+should\s+(buy|sell|short|enter|exit)\b", re.I)),
    ("price_target", re.compile(r"\b(target|tgt)\b[^.]{0,20}?\d|\b(buy\s+above|sell\s+below)\b|\bstop[-\s]?loss\s+at\b", re.I)),
    ("guarantee", re.compile(r"\b(guarantee[ds]?|assured|sure[-\s]?shot|risk[-\s]?free|can'?t\s+lose)\b", re.I)),
    ("performance_claim", re.compile(r"\b\d{2,3}\s*%\s*(accuracy|accurate|win[-\s]?rate|profit|returns?|guaranteed)\b", re.I)),
]


def check_compliance(text: str) -> list[str]:
    """Return the labels of any compliance violations found in ``text`` (empty == clean)."""
    if not text:
        return []
    return [label for label, pat in _PATTERNS if pat.search(text)]


def is_compliant(text: str) -> bool:
    return not check_compliance(text)
