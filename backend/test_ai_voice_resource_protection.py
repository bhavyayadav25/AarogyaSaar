"""FIX 7 — AI/voice abuse and resource protection regression tests."""

from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _request(path="/api/voice/speak", host="127.0.0.1"):
    import main
    return SimpleNamespace(url=SimpleNamespace(path=path), client=SimpleNamespace(host=host))


def test_rate_limit_blocks_expensive_endpoint_after_configured_attempts():
    import main
    old_max = main.VOICE_TTS_RATE_MAX
    old_window = main.AI_RATE_WINDOW_SECONDS
    main.VOICE_TTS_RATE_MAX = 2
    main.AI_RATE_WINDOW_SECONDS = 60
    main._ai_rate_failures.clear()
    actor = {"id": 900001, "role": "patient"}
    try:
        main.enforce_resource_rate_limit(_request(), actor)
        main.enforce_resource_rate_limit(_request(), actor)
        try:
            main.enforce_resource_rate_limit(_request(), actor)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 429
            assert "Retry-After" in (getattr(exc, "headers", {}) or {})
        else:
            raise AssertionError("third expensive request was not rate limited")
    finally:
        main.VOICE_TTS_RATE_MAX = old_max
        main.AI_RATE_WINDOW_SECONDS = old_window
        main._ai_rate_failures.clear()


def test_rate_limit_keys_authenticated_users_separately():
    import main
    main._ai_rate_failures.clear()
    old_max = main.VOICE_TTS_RATE_MAX
    main.VOICE_TTS_RATE_MAX = 1
    try:
        main.enforce_resource_rate_limit(_request(), {"id": 1, "role": "patient"})
        main.enforce_resource_rate_limit(_request(), {"id": 2, "role": "patient"})
    finally:
        main.VOICE_TTS_RATE_MAX = old_max
        main._ai_rate_failures.clear()


def test_transcription_and_tts_have_bounded_concurrency_controls():
    import main
    assert main.MAX_CONCURRENT_TRANSCRIPTIONS >= 1
    assert main.MAX_CONCURRENT_TTS >= 1
    assert main._transcription_semaphore._value == main.MAX_CONCURRENT_TRANSCRIPTIONS
    assert main._tts_semaphore._value == main.MAX_CONCURRENT_TTS


def test_bounded_text_rejects_oversized_ai_input():
    import main
    try:
        main._bounded_text("x" * 1001, 1000)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 413
    else:
        raise AssertionError("oversized text was accepted")
