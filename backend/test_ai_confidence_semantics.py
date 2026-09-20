from ai_confidence_semantics import confidence_semantics
from medical_document_classifier import classify_document
from structured_medical_extractor import extract_structured_medical_data
from document_verification import apply_document_verification


def test_semantics_contract_distinguishes_score_from_clinical_probability():
    s = confidence_semantics("classifier_score")
    assert s["unit"] == "0_to_1"
    assert "clinical probability" in s["not_meaning"]
    assert "diagnostic certainty" in s["not_meaning"]
    assert "model accuracy" in s["not_meaning"]


def test_nlp_and_document_scores_have_distinct_semantics():
    from main import analyze_nlp_text
    nlp = analyze_nlp_text("I have chest pain")
    assert nlp["confidence_semantics"]["kind"] == "classifier_score"
    assert "clinical probability" in nlp["confidence_semantics"]["not_meaning"]

    classification = classify_document("Prescription Rx Tablet Paracetamol 500 mg")
    assert classification.confidence_semantics["kind"] == "document_classification_score"

    extraction = extract_structured_medical_data("Hemoglobin: 13.2 g/dL", "Lab Report")
    item = extraction["items"][0]
    assert item["confidence_semantics"]["kind"] == "extraction_evidence_score"
    assert "measurement accuracy" in item["confidence_semantics"]["not_meaning"]


def test_human_verification_does_not_fabricate_100_percent_ai_confidence():
    extraction = extract_structured_medical_data("Hemoglobin: 13.2 g/dL", "Lab Report")
    original = extraction["items"][0]["confidence"]
    verified = apply_document_verification(extraction, [{"index": 0, "verified": True}])
    item = verified["items"][0]
    assert item["verified"] is True
    assert item["confidence"] == original
    assert "verified_confidence" not in item
    assert item["needs_review"] is False
