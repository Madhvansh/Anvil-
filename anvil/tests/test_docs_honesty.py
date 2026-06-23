"""Docs-honesty lint as FAILING tests (Phase 6 — Docs / ADRs / identity).

The honest framing IS the product's positioning. If a doc reintroduces the unconditional
"…directional accuracy is the main goal" headline, asserts a spot-BSM pricing capability the engine
does not have, or the ADR set grows a numbering gap — these tests fail the build. The honest story is
enforced here, not asserted in prose (mirroring ``test_backtest_guards``). See ``docs/METHODOLOGY.md``
and ADRs 0002 / 0004 / 0005 / 0006.

Surgical by design: the research docs (``hypothesis.md``, ``revamp/*``) legitimately *quote* the
unconditional 70-80% claim in order to debunk it, so the lint targets the specific bug phrasings and
the brand/canonical surfaces only.
"""

from __future__ import annotations

import re
from pathlib import Path


def _docs_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "docs" / "ANVIL.md").exists():
            return parent / "docs"
    raise AssertionError("could not locate docs/ANVIL.md from the test file")


DOCS = _docs_dir()
ANVIL_MD = (DOCS / "ANVIL.md").read_text(encoding="utf-8")

# The brand/canonical surfaces the lint holds to the conditional framing. NOT hypothesis.md or the
# revamp plans, which quote the unconditional number to refute it.
_GOVERNED = ("ANVIL.md", "PITCH.md", "METHODOLOGY.md")

# A 70-80% claim is only honest next to a selective-coverage qualifier.
_QUALIFIERS = ("when it speaks", "speaks", "gated", "coverage", "subset", "stretch",
               "conditional", "reliability", "abstain", "selective")

_RANGE = re.compile(r"70\s*[–\-]\s*80")


def _adr_numbers() -> list[int]:
    nums: list[int] = []
    for f in (DOCS / "decisions").glob("*.md"):
        m = re.match(r"(\d{4})-", f.name)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def test_no_unconditional_accuracy_headline():
    """The exact resurrected bug — '… accuracy is the main goal' — must be gone from EVERY doc.
    The honest selective framing replaced it (ANVIL.md §1 / METHODOLOGY.md)."""
    bug = re.compile(r"accuracy\s+is\s+the\s+main\s+goal", re.I)
    offenders = [md.name for md in DOCS.rglob("*.md") if bug.search(md.read_text(encoding="utf-8"))]
    assert not offenders, f"unconditional 'accuracy is the main goal' headline resurfaced in: {offenders}"


def test_70_80_only_appears_qualified_in_brand_docs():
    """In the brand/canonical docs every '70-80%' must sit next to a selective-coverage qualifier —
    the kept brand stays honest (conditional), the unconditional headline stays banned."""
    for name in _GOVERNED:
        p = DOCS / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        low = text.lower()
        for m in _RANGE.finditer(text):
            window = low[max(0, m.start() - 200): m.end() + 200]
            assert any(q in window for q in _QUALIFIERS), (
                f"{name}: a '70-80%' claim near offset {m.start()} lacks a coverage/selective "
                f"qualifier — it must read as conditional, not an unconditional headline."
            )


def test_anvil_md_never_claims_spot_bsm():
    """ANVIL.md must affirm Black-76-on-futures and never assert a CURRENT spot-BSM capability: every
    'BSM/Black-Scholes on spot' mention must be the negation 'never … on spot' (ADR 0002 / 0005)."""
    assert "never BSM on spot" in ANVIL_MD, "ANVIL.md should affirm 'never BSM on spot' (ADR 0002)."
    for m in re.finditer(r"(bsm|black[-\s]?scholes)[^.\n]{0,20}\bon\s+spot", ANVIL_MD, re.I):
        prefix = ANVIL_MD[max(0, m.start() - 12): m.start()].lower()
        assert "never" in prefix, (
            f"ANVIL.md: a spot-BSM mention near offset {m.start()} is not negated — the engine prices "
            f"Black-76 on futures (ADR 0002); single-stock options are deferred (ADR 0005)."
        )


def test_adr_set_is_contiguous():
    """The live ADR tree must be contiguous 0001..N — ADR 0005 (BSM-on-spot deferral) closes the
    historical 0004->0006 jump (Phase 6)."""
    nums = _adr_numbers()
    assert nums, "no ADRs found in docs/decisions/"
    assert set(nums) == set(range(1, max(nums) + 1)), (
        f"ADR numbering has a gap: found {nums}; expected contiguous 1..{max(nums)} "
        f"(ADR 0005 must exist as the BSM-on-spot deferral)."
    )
    for needed in (4, 5, 6):
        assert needed in nums, f"ADR {needed:04d} is missing from docs/decisions/"


def test_methodology_doc_exists_and_is_linked():
    """The §1 brand line links to METHODOLOGY.md — it must exist (no dead link) and carry the honest
    conditional framing (reliability curve + abstention)."""
    meth = DOCS / "METHODOLOGY.md"
    assert meth.exists(), "docs/METHODOLOGY.md (the brand-substantiation disclosure) is missing."
    text = meth.read_text(encoding="utf-8").lower()
    assert "reliability curve" in text and "abstain" in text, (
        "METHODOLOGY.md must explain the reliability curve + abstention (the honest substantiation)."
    )
    assert "methodology.md" in ANVIL_MD.lower(), "ANVIL.md §1 should link to METHODOLOGY.md."


def test_public_wall_predicates_exist_and_dark_by_default():
    """The docs claim a personal-mode wall (ADR 0006); the predicates they reference must exist and
    the wall must be DARK by default (personal mode off => not armed, no store access)."""
    from anvil.gating import gate0_passed, personal_mode_armed

    assert callable(gate0_passed) and callable(personal_mode_armed)
    # personal_mode defaults off under pytest, so this short-circuits to False with no DB access.
    assert personal_mode_armed() is False, (
        "ADR 0006: with ANVIL_PERSONAL_MODE off the wall must be dark (personal_mode_armed() == False)."
    )
