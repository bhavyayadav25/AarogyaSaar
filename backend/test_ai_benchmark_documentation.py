from pathlib import Path


def test_benchmark_documentation_exists_and_has_required_boundaries():
    root = Path(__file__).resolve().parent
    protocol = (root / "ai_benchmark_protocol.md").read_text(encoding="utf-8")
    results = (root / "ai_benchmark_results.md").read_text(encoding="utf-8")

    required_protocol = [
        "engineering evaluation",
        "clinical validation study",
        "Metric definitions",
        "Case-level pass rule",
        "Reproducibility",
        "confidence values returned by the NLP layer are not calibrated probabilities",
        "independent test-set result",
    ]
    for phrase in required_protocol:
        assert phrase in protocol

    required_results = [
        "Dataset version:** 5F.1",
        "Cases:** 20",
        "13 / 20 (65.0%)",
        "100.0%",
        "69.57%",
        "82.05%",
        "85.0%",
        "not clinical accuracy",
        "clinician review",
    ]
    for phrase in required_results:
        assert phrase in results
