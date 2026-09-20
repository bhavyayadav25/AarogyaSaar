"""P0 #5: repeat the real patient -> doctor -> admin handoff ten times.

This is a reliability/regression test, not a synthetic endpoint-only smoke test.
Each iteration creates a fresh patient, creates today's encounter, completes the
full interview, verifies the assigned doctor's queue/workspace, and verifies the
hospital admin analytics reflect the encounter. Test-created records are removed
at the end so repeated runs do not pollute the demo database.
"""

import uuid
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient
import main


PATIENT_PASSWORD = "patient123"
DOCTOR_EMAIL = "doctor@sih26047.local"
DOCTOR_PASSWORD = "doctor123"
ADMIN_EMAIL = "admin@sih26047.local"
ADMIN_PASSWORD = "admin123"


def _login(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def _complete_interview(client, headers, patient_id):
    session_id = f"p0-5-{uuid.uuid4().hex}"
    response = client.post(
        f"/api/patients/{patient_id}/consent",
        headers=headers,
        json={
            "patient_id": patient_id,
            "language": "en-IN",
            "audio_explained": True,
            "granted": True,
        },
    )
    assert response.status_code == 200, response.text

    response = client.get(
        "/api/interview/questions",
        headers=headers,
        params={"patient_id": patient_id, "language": "en-IN", "session_id": session_id},
    )
    assert response.status_code == 200, response.text
    question = response.json()["question"]

    for _ in range(100):
        assert question is not None
        response = client.post(
            "/api/interview/answer",
            headers=headers,
            json={
                "patient_id": patient_id,
                "session_id": session_id,
                "question_id": question["id"],
                "answer": "I have no additional information",
                "skipped": False,
                "answers": {},
                "language": "en-IN",
                "input_mode": "text",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        if data["completed"]:
            assert data.get("consultation_id") is not None
            assert data.get("ai_summary")
            return
        question = data["next_question"]

    raise AssertionError("Interview did not complete within 100 questions")


def test_p0_5_patient_doctor_admin_handoff_ten_consecutive_runs():
    client = TestClient(main.app)
    admin_headers = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    doctor_headers = _login(client, DOCTOR_EMAIL, DOCTOR_PASSWORD)
    created_patient_ids = []

    try:
        doctor_user = (
            db := main.SessionLocal()
        ).query(main.User).filter(main.User.email == DOCTOR_EMAIL).first()
        assert doctor_user is not None
        doctor_id = doctor_user.id
        db.close()

        for run_number in range(1, 11):
            email = f"p0-5-{uuid.uuid4().hex[:12]}@example.local"
            response = client.post(
                "/api/auth/register",
                json={
                    "name": f"Regression Patient {run_number}",
                    "email": email,
                    "password": PATIENT_PASSWORD,
                    "age": 35 + run_number,
                    "gender": "Female",
                    "phone": f"90000{run_number:05d}",
                },
            )
            assert response.status_code == 200, response.text
            patient_headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            patient_id = response.json()["user"]["id"]
            created_patient_ids.append(patient_id)

            response = client.post(
                "/api/encounters",
                headers=patient_headers,
                json={
                    "patient_id": patient_id,
                    "department": "General Medicine",
                    "priority": "normal",
                    "reason": "Headache for two days",
                    "care_type": "allopathy",
                },
            )
            assert response.status_code == 200, response.text
            encounter = response.json()["encounter"]
            encounter_id = encounter["id"]
            assert encounter["doctor_id"] == doctor_id
            assert encounter["status"] == "waiting"

            _complete_interview(client, patient_headers, patient_id)

            response = client.get(
                f"/api/encounters/{encounter_id}", headers=patient_headers
            )
            assert response.status_code == 200, response.text
            assert response.json()["encounter"]["doctor_id"] == doctor_id

            response = client.get(
                "/api/queue",
                headers=doctor_headers,
                params={"status": "waiting,called,in_consultation"},
            )
            assert response.status_code == 200, response.text
            assert any(item["id"] == encounter_id for item in response.json()["queue"])

            response = client.get(
                f"/api/doctor/encounters/{encounter_id}/workspace",
                headers=doctor_headers,
            )
            assert response.status_code == 200, response.text
            workspace = response.json()["workspace"]
            assert workspace["encounter"]["id"] == encounter_id
            assert workspace.get("general_consultation") is not None
            assert workspace.get("interview")

            today = date.today().isoformat()
            response = client.get(
                "/api/admin/analytics",
                headers=admin_headers,
                params={"start_date": today, "end_date": today},
            )
            assert response.status_code == 200, response.text
            overview = response.json()["overview"]
            assert overview["encounters"] >= run_number
            assert overview["assigned_doctors"] >= 1

    finally:
        # Remove only records created by this test. This keeps the real demo
        # account/data intact and makes the ten-run regression repeatable.
        db = main.SessionLocal()
        try:
            ids = created_patient_ids
            if ids:
                db.query(main.VoiceTurn).filter(main.VoiceTurn.patient_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.AyushAssessment).filter(main.AyushAssessment.patient_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.MedicalDocument).filter(main.MedicalDocument.patient_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.ConsentRecord).filter(main.ConsentRecord.patient_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.AccessibilityPreference).filter(main.AccessibilityPreference.patient_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.Consultation).filter(main.Consultation.patient_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.InterviewState).filter(main.InterviewState.patient_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.Encounter).filter(main.Encounter.patient_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.PatientProfile).filter(main.PatientProfile.user_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.UserSession).filter(main.UserSession.user_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.AuditEvent).filter(main.AuditEvent.user_id.in_(ids)).delete(synchronize_session=False)
                db.query(main.User).filter(main.User.id.in_(ids)).delete(synchronize_session=False)
                db.commit()
        finally:
            db.close()
