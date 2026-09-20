"""FIX 6 file-upload security regression tests."""

from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def test_filename_is_display_safe_and_never_controls_storage_path():
    import main
    safe = main._safe_original_filename("../../patient\nreport\x00.pdf")
    assert safe == "patient_report.pdf"
    assert "/" not in safe and "\\" not in safe


def test_document_content_must_match_extension():
    import main
    try:
        main._validate_document_bytes("report.pdf", "application/pdf", b"not-a-pdf")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 415
    else:
        raise AssertionError("mismatched document content was accepted")


def test_document_size_limit_is_enforced_without_full_storage():
    import main
    old = main.MAX_DOCUMENT_UPLOAD_BYTES
    main.MAX_DOCUMENT_UPLOAD_BYTES = 4
    try:
        try:
            main._validate_document_bytes("report.pdf", "application/pdf", b"%PDF-12345")
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 413
        else:
            raise AssertionError("oversized document was accepted")
    finally:
        main.MAX_DOCUMENT_UPLOAD_BYTES = old
