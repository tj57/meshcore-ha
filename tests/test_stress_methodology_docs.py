"""Offline checks for the RC stress methodology docs (no RF)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRESS = (ROOT / "docs" / "STRESS_METHODOLOGY.md").read_text(encoding="utf-8")
QA = (ROOT / "docs" / "QA_CHANNEL_POLICY.md").read_text(encoding="utf-8")
RULES = (ROOT / "docs" / "DEVELOPMENT_RULES.md").read_text(encoding="utf-8")


def test_stress_rejects_hundred_ping_gate():
    assert "100-ping burst" in STRESS
    assert "No expectation of **100% RF delivery**" in STRESS or "100% RF delivery" in STRESS


def test_stress_profiles_documented():
    assert "5 requests" in STRESS
    assert "1 s" in STRESS or "1 second" in STRESS
    assert "10 requests" in STRESS
    assert "2 s" in STRESS or "2 second" in STRESS
    assert "5 minutes" in STRESS
    assert "30 minutes" in STRESS


def test_stress_saturation_signals():
    lower = STRESS.lower()
    assert "busy" in lower
    assert "queue_full" in lower or "queue full" in lower
    assert "table_full" in lower
    assert "backpressure" in lower


def test_public_out_of_scope_for_qa():
    assert "out of scope" in QA.lower()
    assert "must **not** transmit protocol commands on Public" in QA or (
        "must not transmit protocol commands on Public" in QA
    )
    assert "negative Public" in QA  # documents removal
    assert "one negative" not in QA.lower()


def test_production_names_and_entry_title():
    assert "mcYogi" in RULES
    assert "mcCtrl" in RULES
    assert "never generates" in RULES.lower() or "Never generates" in RULES
    assert "Co-authored-by: Cursor" in RULES
