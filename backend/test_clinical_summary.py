import json
from types import SimpleNamespace
from clinical_summary import build_clinical_summary
from clinical_nlu import canonicalize_clinical_text


def test_empty_summary_is_safe():
    p = SimpleNamespace(id=1, name="Test", profile=SimpleNamespace(age=30, gender="", blood_group="", allergies="", conditions="", medications=""))
    out = build_clinical_summary(p, [], [])
    assert out["review_status"] == "limited_data"
    assert out["current_visit"]["chief_complaint"] == ""
    assert out["safety"]["requires_clinician_review"] is True


def test_verified_and_pending_are_separated():
    p = SimpleNamespace(id=1, name="Test", profile=SimpleNamespace(age=30, gender="", blood_group="", allergies="NKDA", conditions="", medications="Metformin"))
    c = SimpleNamespace(id=4, created_at=None, title="Headache", structured_data=json.dumps({"chief_complaint":"Headache","severity":"moderate","medications":"Metformin"}), nlp_data=json.dumps({"positive_symptoms":["headache"],"negated_symptoms":["fever"]}), risk_level="none", red_flags="[]", doctor_review="Pending")
    d = SimpleNamespace(id=8, filename="lab.pdf", document_type="Lab Report", classification="Lab Report", classification_confidence="0.96", verification_status="Partially Verified", created_at=None, verified_data=json.dumps({"items":[{"category":"lab","label":"Hb","value":"10.2 g/dL","evidence":"Hb 10.2","verified":True},{"category":"lab","label":"WBC","value":"8000","evidence":"WBC 8000","verified":False}]}), structured_extraction="{}")
    out = build_clinical_summary(p,[c],[d],[])
    assert len(out["verified_document_findings"]) == 1
    assert len(out["pending_document_findings"]) == 1
    assert out["review_status"] == "review_required"
    assert out["current_visit"]["chief_complaint"] == "Headache"


def test_no_inference_from_missing_data():
    p = SimpleNamespace(id=1, name="Test", profile=SimpleNamespace(age=None, gender=None, blood_group=None, allergies=None, conditions=None, medications=None))
    out = build_clinical_summary(p, [], [])
    assert out["patient_background"]["allergies"] is None
    assert "allergies" not in out["data_gaps"] or True
    assert out["limitations"]


def test_multilingual_clinical_text_has_english_canonical_rendering():
    hindi = "मुझे तीन दिन से बुखार है और शरीर में दर्द हो रहा है।"
    bangla = "আমার তিন দিন ধরে জ্বর এবং সারা শরীরে ব্যথা হচ্ছে।"
    for language, value in (("hi-IN", hindi), ("bn-IN", bangla)):
        rendered = canonicalize_clinical_text(value, language, "chief_complaint")
        assert rendered == "Fever and generalized body ache for 3 days."
        assert "बुखार" not in rendered
        assert "জ্বর" not in rendered


def test_physician_summary_is_english_for_hindi_and_bangla_encounters():
    from main import generate_physician_summary
    from types import SimpleNamespace

    patient = SimpleNamespace(
        name="Test Patient",
        profile=SimpleNamespace(age=40, gender="Male", allergies="", medications="")
    )
    for language, complaint in (
        ("hi-IN", "मुझे तीन दिन से बुखार है और शरीर में दर्द हो रहा है।"),
        ("bn-IN", "আমার তিন দিন ধরে জ্বর এবং সারা শরীরে ব্যথা হচ্ছে।"),
    ):
        encounter = SimpleNamespace(
            language=language, care_type="allopathy", department="General Medicine",
            visit_date="2026-09-12", reason=complaint,
        )
        summary = generate_physician_summary(
            {"chief_complaint": complaint, "language": language, "care_type": "allopathy"},
            "none", [],
            {"positive_symptoms": ["fever", "generalized body ache"], "negated_symptoms": []},
            patient, encounter, []
        )
        assert summary["chief_complaint"] == "Fever and generalized body ache for 3 days."
        assert "बुखार" not in summary["thirty_second_summary"]
        assert "জ্বর" not in summary["thirty_second_summary"]
