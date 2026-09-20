from uuid import uuid4

from fastapi.testclient import TestClient
import main


def register(client):
    email = f"fix4-{uuid4().hex[:12]}@sih26047.local"
    r = client.post("/api/auth/register", json={
        "name": "FIX4 Audit Patient",
        "email": email,
        "password": "SecurePass123",
        "age": 31,
        "gender": "Other",
        "phone": "",
    })
    assert r.status_code == 200, r.text
    return r.json()["user"]["id"], r.json()["access_token"]


def cleanup(user_id):
    db = main.SessionLocal()
    try:
        db.query(main.AuditEvent).filter(main.AuditEvent.user_id == user_id).delete(synchronize_session=False)
        db.query(main.UserSession).filter(main.UserSession.user_id == user_id).delete(synchronize_session=False)
        db.query(main.PatientProfile).filter(main.PatientProfile.user_id == user_id).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id == user_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_authenticated_request_is_traced_with_request_id_and_status():
    client = TestClient(main.app)
    user_id, token = register(client)
    try:
        request_id = "fix4-trace-001"
        r = client.get(
            f"/api/patients/{user_id}",
            headers={"Authorization": f"Bearer {token}", "X-Request-ID": request_id},
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("X-Request-ID") == request_id

        db = main.SessionLocal()
        try:
            event = (
                db.query(main.AuditEvent)
                .filter(
                    main.AuditEvent.user_id == user_id,
                    main.AuditEvent.request_id == request_id,
                    main.AuditEvent.action == "request_get_200",
                    main.AuditEvent.resource == f"/api/patients/{user_id}",
                )
                .order_by(main.AuditEvent.id.desc())
                .first()
            )
            assert event is not None
            assert event.role == "patient"
        finally:
            db.close()
    finally:
        cleanup(user_id)


def test_failed_authenticated_request_is_also_audited_without_logging_query_data():
    client = TestClient(main.app)
    user_id, token = register(client)
    try:
        request_id = "fix4-denied-001"
        # Patient may only access their own profile. The query value is deliberately
        # sensitive-looking; it must never enter the audit resource field.
        other_id = user_id + 999999
        r = client.get(
            f"/api/patients/{other_id}?search=secret-medical-value",
            headers={"Authorization": f"Bearer {token}", "X-Request-ID": request_id},
        )
        assert r.status_code in {403, 404}

        db = main.SessionLocal()
        try:
            event = (
                db.query(main.AuditEvent)
                .filter(main.AuditEvent.user_id == user_id, main.AuditEvent.request_id == request_id)
                .order_by(main.AuditEvent.id.desc())
                .first()
            )
            assert event is not None
            assert event.action.startswith("request_get_")
            assert "secret-medical-value" not in (event.resource or "")
            assert "?" not in (event.resource or "")
        finally:
            db.close()
    finally:
        cleanup(user_id)
