from main import SUPPORTED_LANGUAGES, AYUSH_DASHAVIDHA, localized_ayush_questions, generate_physician_summary


def test_patient_languages_are_exactly_english_hindi_bangla():
    assert set(SUPPORTED_LANGUAGES) == {"en-IN", "hi-IN", "bn-IN"}


def test_ayush_has_options_and_measurement_contract_for_supported_languages():
    for lang in SUPPORTED_LANGUAGES:
        questions = localized_ayush_questions(lang)
        assert len(questions) == len(AYUSH_DASHAVIDHA)
        assert sum(bool(q.get("options")) for q in questions) >= 7
        assert questions[4]["id"] == "pramana"
        assert questions[4]["type"] == "measurements"
    assert localized_ayush_questions("bn-IN")[0]["question"] != localized_ayush_questions("en-IN")[0]["question"]


def test_physician_summary_contains_data_driven_thirty_second_summary():
    summary = generate_physician_summary(
        {"chief_complaint": "chest pain", "onset": "2 days", "severity": "severe", "location": "chest"},
        "urgent",
        [{"id": "chest", "label": "Chest discomfort", "level": "urgent"}],
        {},
    )
    assert "chest pain" in summary["thirty_second_summary"]
    assert "2 days" in summary["thirty_second_summary"]
    assert "Chest discomfort" in summary["thirty_second_summary"]
