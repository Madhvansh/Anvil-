"""M5: compliance guardrail + grounded deterministic narration."""

from anvil.agent.analyst import GroundedAnalyst, build_context, narrate
from anvil.agent.guardrail import check_compliance, is_compliant
from anvil.ingest.demo import DemoConnector
from anvil.pipeline import analyze_chain


def test_guardrail_blocks_actionable_calls():
    assert "actionable_call" in check_compliance("Just buy NIFTY now, easy money")
    assert "recommendation" in check_compliance("You should sell your puts")
    assert "price_target" in check_compliance("Target 25000 by Friday expiry")
    assert "guarantee" in check_compliance("This is a sure-shot risk-free setup")
    assert "performance_claim" in check_compliance("Our model has 92% accuracy")


def test_guardrail_allows_analytics_language():
    txt = ("Net GEX is positive and spot is above the zero-gamma flip, implying dealer hedging "
           "dampens moves (mean-reverting regime). Market-implied 1-sigma move is ~120 points.")
    assert is_compliant(txt)
    assert check_compliance(txt) == []


def _payload():
    conn = DemoConnector()
    return analyze_chain(conn.get_chain("NIFTY"), conn.get_positions())


def test_narration_is_grounded_and_compliant():
    p = _payload()
    text = narrate(p)
    # grounded: mentions the regime label and the engine's flip level
    assert p["regime"]["label"].split("_")[0] in text.lower() or "regime" in text.lower()
    assert "flip" in text.lower()
    assert "not investment advice" in text.lower()
    # and it never trips the compliance guardrail
    assert is_compliant(text)


def test_build_context_only_engine_fields():
    p = _payload()
    ctx = build_context(p, ledger_metrics={"resolved_count": 5, "brier": 0.16, "ece": 0.02, "band_coverage": {}})
    assert ctx["underlying"] == "NIFTY"
    assert "gex" in ctx and "implied_distribution" in ctx
    assert ctx["calibration"]["resolved_count"] == 5


def test_ask_without_api_key_falls_back_to_narrator(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = GroundedAnalyst().ask("Should I buy?", _payload())
    assert res["model"] == "deterministic-narrator"
    assert is_compliant(res["answer"])
