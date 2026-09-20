from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

SUPPORTED = set(main.SUPPORTED_LANGUAGES)


def auth(email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def test_every_supported_language_has_explicit_tts_and_whisper_mapping():
    assert SUPPORTED == set(main.TTS_VOICE_MAP)
    assert SUPPORTED == set(main.WHISPER_LANGUAGE_CODES)


def test_voice_status_reports_consistent_language_coverage():
    headers = auth('admin@sih26047.local', 'admin123')
    r = client.get('/api/voice/status', headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data['languages']) == SUPPORTED
    assert set(data['tts_languages']) == SUPPORTED


def test_voice_language_aliases_cover_supported_languages():
    aliases = {'en':'en-IN','hi':'hi-IN','bn':'bn-IN','ta':'ta-IN','te':'te-IN','mr':'mr-IN','gu':'gu-IN','kn':'kn-IN'}
    for alias, expected in aliases.items():
        assert main._normalize_voice_language(alias) == expected
        assert main._voice_language_code(alias) == expected.split('-')[0]


def test_tts_never_falls_back_to_english_for_supported_language(monkeypatch):
    admin = auth('admin@sih26047.local', 'admin123')
    calls = []

    class FakeCommunicate:
        def __init__(self, text, voice):
            calls.append(voice)
        async def save(self, path):
            with open(path, 'wb') as f:
                f.write(b'audio')

    monkeypatch.setattr(main, 'EDGE_TTS_AVAILABLE', True)
    import types
    monkeypatch.setattr(main, 'edge_tts', types.SimpleNamespace(Communicate=FakeCommunicate))
    for language in sorted(SUPPORTED):
        r = client.post('/api/voice/speak', headers=admin, data={'text':'test', 'language':language})
        assert r.status_code == 200, (language, r.text)
    assert set(calls) == set(main.TTS_VOICE_MAP.values())
