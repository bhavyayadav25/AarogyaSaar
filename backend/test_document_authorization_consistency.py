"""Stored medical document resource authorization regression tests."""
from uuid import uuid4
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def setup_document_case():
    db = main.SessionLocal()
    s = uuid4().hex[:10]
    doctor = main.User(name="Doc A", email=f"doc-a-{s}@sih26047.local", password_hash=main.hash_password("doctor123"), role="doctor")
    other = main.User(name="Doc B", email=f"doc-b-{s}@sih26047.local", password_hash=main.hash_password("doctor123"), role="doctor")
    patient = main.User(name="Doc Patient", email=f"doc-p-{s}@sih26047.local", password_hash=main.hash_password("patient123"), role="patient")
    db.add_all([doctor, other, patient])
    db.flush()
    main.make_profile(db, patient, 45, "Other", "")
    encounter = main.Encounter(
        patient_id=patient.id, doctor_id=other.id, department="General Medicine",
        visit_date="2099-04-01", token_number=50000 + patient.id,
        priority="normal", status="in_consultation", reason="Document auth"
    )
    document = main.MedicalDocument(
        patient_id=patient.id, filename="report.txt", document_type="Lab Report",
        mime_type="text/plain", extracted_text="hemoglobin 12", extracted_data="[]",
        structured_extraction='{"schema_version":"AI-3D.1","needs_review":true,"items":[{"category":"measurement","label":"hemoglobin","value":"12","confidence":0.95,"needs_review":true,"evidence":"hemoglobin 12"}]}',
        verification_status="Pending", status="Processed"
    )
    db.add_all([encounter, document])
    db.commit()
    db.refresh(doctor); db.refresh(other); db.refresh(patient); db.refresh(encounter); db.refresh(document)
    ids = (doctor.id, other.id, patient.id, encounter.id, document.id)
    db.close()
    return ids


def cleanup(ids):
    db = main.SessionLocal()
    did, oid, pid, eid, docid = ids
    db.query(main.MedicalDocument).filter(main.MedicalDocument.id == docid).delete(synchronize_session=False)
    db.query(main.Encounter).filter(main.Encounter.id == eid).delete(synchronize_session=False)
    db.query(main.PatientProfile).filter(main.PatientProfile.user_id == pid).delete(synchronize_session=False)
    db.query(main.UserSession).filter(main.UserSession.user_id.in_([did, oid])).delete(synchronize_session=False)
    db.query(main.User).filter(main.User.id.in_([did, oid, pid])).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_unassigned_doctor_cannot_access_or_modify_stored_document():
    client = TestClient(main.app)
    ids = setup_document_case()
    try:
        db = main.SessionLocal()
        email = db.query(main.User).filter(main.User.id == ids[0]).first().email
        db.close()
        h = auth(client, email, "doctor123")
        did = ids[4]
        assert client.get(f"/api/documents/{did}/verification", headers=h).status_code == 403
        assert client.get(f"/api/documents/{did}/explainability", headers=h).status_code == 403
        assert client.get(f"/api/documents/{did}/timeline-context", headers=h).status_code == 403
        assert client.get(f"/api/documents/{did}/clinical-handoff", headers=h).status_code == 403
        assert client.post(f"/api/documents/{did}/classify", headers=h).status_code == 403
        assert client.post(f"/api/documents/{did}/extract", headers=h).status_code == 403
        assert client.post(
            f"/api/documents/{did}/verify", headers=h,
            json={"verified_items": [], "notes": "unauthorized"}
        ).status_code == 403
    finally:
        cleanup(ids)


def test_assigned_doctor_can_access_and_verify_stored_document():
    client = TestClient(main.app)
    ids = setup_document_case()
    try:
        db = main.SessionLocal()
        email = db.query(main.User).filter(main.User.id == ids[1]).first().email
        db.close()
        h = auth(client, email, "doctor123")
        did = ids[4]
        assert client.get(f"/api/documents/{did}/verification", headers=h).status_code == 200
        assert client.get(f"/api/documents/{did}/explainability", headers=h).status_code == 200
        assert client.get(f"/api/documents/{did}/timeline-context", headers=h).status_code == 200
        assert client.get(f"/api/documents/{did}/clinical-handoff", headers=h).status_code == 200
        assert client.post(f"/api/documents/{did}/classify", headers=h).status_code == 200
        assert client.post(f"/api/documents/{did}/extract", headers=h).status_code == 200
        assert client.post(
            f"/api/documents/{did}/verify", headers=h,
            json={"verified_items": [{"index": 0, "verified": True}], "notes": "verified by assigned doctor"}
        ).status_code == 200
    finally:
        cleanup(ids)


def test_admin_retains_hospital_wide_document_access():
    client = TestClient(main.app)
    ids = setup_document_case()
    try:
        h = auth(client, "admin@sih26047.local", "admin123")
        did = ids[4]
        assert client.get(f"/api/documents/{did}/verification", headers=h).status_code == 200
        assert client.get(f"/api/documents/{did}/explainability", headers=h).status_code == 200
    finally:
        cleanup(ids)
