from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import main


def register(client, password="SecurePass123"):
    email = f"fix3-{uuid4().hex[:12]}@sih26047.local"
    r = client.post("/api/auth/register", json={
        "name": "FIX3 Security Patient", "email": email, "password": password,
        "age": 30, "gender": "Other", "phone": ""
    })
    assert r.status_code == 200, r.text
    return email, r.json()["user"]["id"], r.json()["access_token"]


def cleanup_user(user_id):
    db = main.SessionLocal()
    try:
        db.query(main.UserSession).filter(main.UserSession.user_id == user_id).delete(synchronize_session=False)
        db.query(main.PatientProfile).filter(main.PatientProfile.user_id == user_id).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id == user_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_new_passwords_use_pbkdf2_and_legacy_sha256_upgrades_on_login():
    client = TestClient(main.app)
    email, user_id, token = register(client)
    try:
        db = main.SessionLocal()
        try:
            user = db.query(main.User).filter(main.User.id == user_id).first()
            assert user.password_hash.startswith("pbkdf2_sha256$")
            legacy = main.hashlib.sha256("LegacyPass123".encode()).hexdigest()
            user.password_hash = legacy
            db.commit()
        finally:
            db.close()

        r = client.post("/api/auth/login", json={"email": email, "password": "LegacyPass123"})
        assert r.status_code == 200, r.text

        db = main.SessionLocal()
        try:
            user = db.query(main.User).filter(main.User.id == user_id).first()
            assert user.password_hash.startswith("pbkdf2_sha256$")
            assert user.password_hash != legacy
        finally:
            db.close()
    finally:
        cleanup_user(user_id)


def test_logout_revokes_only_the_present_session():
    client = TestClient(main.app)
    email, user_id, token1 = register(client)
    try:
        r = client.post("/api/auth/login", json={"email": email, "password": "SecurePass123"})
        assert r.status_code == 200
        token2 = r.json()["access_token"]
        assert token1 != token2

        r = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token1}"})
        assert r.status_code == 200
        assert client.get("/api/security/status", headers={"Authorization": f"Bearer {token1}"}).status_code == 401
        assert client.get("/api/security/status", headers={"Authorization": f"Bearer {token2}"}).status_code == 200
    finally:
        cleanup_user(user_id)


def test_expired_and_idle_sessions_are_rejected_and_idle_session_is_revoked():
    client = TestClient(main.app)
    email, user_id, token = register(client)
    try:
        db = main.SessionLocal()
        try:
            rec = db.query(main.UserSession).filter(main.UserSession.token_hash == main._hash_token(token)).first()
            rec.expires_at = main.utc_now() - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()
        assert client.get("/api/security/status", headers={"Authorization": f"Bearer {token}"}).status_code == 401

        # Create a fresh session, then make it idle beyond the configured limit.
        r = client.post("/api/auth/login", json={"email": email, "password": "SecurePass123"})
        assert r.status_code == 200
        idle_token = r.json()["access_token"]
        db = main.SessionLocal()
        try:
            rec = db.query(main.UserSession).filter(main.UserSession.token_hash == main._hash_token(idle_token)).first()
            rec.last_seen_at = main.utc_now() - timedelta(minutes=main.SESSION_IDLE_MINUTES + 1)
            db.commit()
        finally:
            db.close()
        assert client.get("/api/security/status", headers={"Authorization": f"Bearer {idle_token}"}).status_code == 401
        db = main.SessionLocal()
        try:
            rec = db.query(main.UserSession).filter(main.UserSession.token_hash == main._hash_token(idle_token)).first()
            assert rec.revoked_at is not None
        finally:
            db.close()
    finally:
        cleanup_user(user_id)


def test_repeated_failed_logins_are_rate_limited():
    client = TestClient(main.app)
    email = f"nonexistent-{uuid4().hex[:12]}@sih26047.local"
    main._login_failures.clear()
    try:
        for _ in range(main.LOGIN_MAX_FAILURES):
            r = client.post("/api/auth/login", json={"email": email, "password": "WrongPass123"})
            assert r.status_code == 401
        r = client.post("/api/auth/login", json={"email": email, "password": "WrongPass123"})
        assert r.status_code == 429
    finally:
        main._login_failures.clear()


def test_malformed_or_unknown_bearer_tokens_are_rejected():
    client = TestClient(main.app)
    assert client.get("/api/security/status", headers={"Authorization": "Bearer short"}).status_code == 401
    assert client.get("/api/security/status", headers={"Authorization": "Bearer " + "a" * 64}).status_code == 401
