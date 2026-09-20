from pathlib import Path


MAIN = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


def test_patient_facing_safety_message_is_not_reassuring():
    assert "No immediate red flag was identified" not in MAIN
    assert "no immediate red flag identified" not in MAIN.lower()
    assert "No red flag identified" not in MAIN
    assert "No safety rule matched the information collected so far." in MAIN
    assert "This does not mean the patient is medically safe" in MAIN
    assert "clinical review remains required" in MAIN


def test_clinical_handoff_does_not_make_a_negative_safety_claim():
    assert "no immediate red flag identified by prototype rules" not in MAIN.lower()
    assert "This does not establish clinical safety; clinician review remains required." in MAIN
