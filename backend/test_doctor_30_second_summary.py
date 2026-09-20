from main import generate_physician_summary


def test_30_second_summary_is_concise_and_actionable():
    summary = generate_physician_summary(
        {
            "chief_complaint": "chest pain",
            "onset": "2 days",
            "severity": "moderate",
            "location": "chest",
            "medications": "None",
            "allergies": "None known",
        },
        "urgent",
        [{"id": "chest", "label": "Chest discomfort", "level": "urgent"}],
        {"positive_symptoms": ["shortness of breath"]},
    )
    text = summary["thirty_second_summary"]
    assert "chest pain" in text
    assert "2 days" in text
    assert "Chest discomfort" in text
    assert "clinician review required" in text
    assert len(text) <= 520


def test_30_second_summary_never_claims_safety_clearance():
    summary = generate_physician_summary(
        {"chief_complaint": "headache", "onset": "1 day"},
        "none", [], {},
    )
    text = summary["thirty_second_summary"].lower()
    assert "not a clearance" in text
    assert "diagnosis" not in text


def test_30_second_brief_exposes_scan_first_sections_and_provenance():
    from types import SimpleNamespace
    patient = SimpleNamespace(profile=SimpleNamespace(conditions="Asthma", medications="Inhaler", allergies="None known"))
    encounter = SimpleNamespace(language="en-IN", care_type="allopathy", department="General Medicine", visit_date="2026-09-13", reason="cough")
    summary = generate_physician_summary(
        {"chief_complaint": "cough", "onset": "3 days", "associated_symptoms": "sore throat"},
        "urgent", [{"id": "review", "label": "Safety review", "level": "urgent", "evidence": ["patient response"]}],
        {"positive_symptoms": ["cough"]}, patient, encounter, [SimpleNamespace(id=1, filename="report.pdf", document_type="Lab")]
    )
    brief = summary["brief_sections"]
    assert brief["presenting_concern"]["value"] == "cough"
    assert "Onset: 3 days" in brief["history"]["items"]
    assert "sore throat" in brief["reported_symptoms"]["items"]
    assert brief["safety"]["status"] == "review_required"
    assert brief["important_background"]["items"]
    assert "severity" in brief["verify"]["items"]
    assert brief["documents"]["count"] == 1
    assert brief["provenance"]["clinician_verified"]


def test_30_second_brief_handles_partial_records_without_nulls():
    summary = generate_physician_summary({}, "none", [], {})
    brief = summary["brief_sections"]
    assert brief["presenting_concern"]["value"] == "Not reported"
    assert brief["history"]["items"] == ["Not reported"]
    assert brief["reported_symptoms"]["items"] == ["Not reported"]
    assert brief["important_background"]["items"] == ["Not reported"]
    assert brief["safety"]["status"] == "not_available"
    assert all("null" not in str(value).lower() for value in brief.values())
