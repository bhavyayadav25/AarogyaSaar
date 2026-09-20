from uuid import uuid4
from fastapi.testclient import TestClient
import main


def register_patient(client):
    email = f"consent-{uuid4().hex[:10]}@sih26047.local"
    r = client.post('/api/auth/register', json={
        'name': 'Consent Gate Test Patient', 'email': email, 'password': 'patient123',
        'age': 35, 'gender': 'Other', 'phone': ''
    })
    assert r.status_code == 200, r.text
    return r.json()['user']['id'], {'Authorization': 'Bearer ' + r.json()['access_token']}


def cleanup(patient_id):
    db = main.SessionLocal()
    try:
        db.query(main.InterviewState).filter(main.InterviewState.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.ConsentRecord).filter(main.ConsentRecord.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.Consultation).filter(main.Consultation.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.Encounter).filter(main.Encounter.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.UserSession).filter(main.UserSession.user_id == patient_id).delete(synchronize_session=False)
        db.query(main.PatientProfile).filter(main.PatientProfile.user_id == patient_id).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id == patient_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_interview_requires_active_consent_before_state_answer_or_complete():
    client = TestClient(main.app)
    patient_id, headers = register_patient(client)
    session_id = f"consent-gate-{uuid4().hex}"
    try:
        # Starting/resuming a server-owned interview cannot create/expose state without consent.
        r = client.get(f'/api/interview/state/{session_id}', params={'patient_id': patient_id}, headers=headers)
        assert r.status_code == 403
        assert 'consent' in r.json()['detail'].lower()

        answer = {
            'patient_id': patient_id, 'session_id': session_id,
            'question_id': 'chief_complaint', 'answer': 'I have a fever',
            'answers': {}, 'language': 'en-IN'
        }
        r = client.post('/api/interview/answer', json=answer, headers=headers)
        assert r.status_code == 403
        assert 'consent' in r.json()['detail'].lower()

        complete = {
            'patient_id': patient_id, 'session_id': session_id,
            'title': 'Clinical History', 'answers': {}, 'structured': {}
        }
        r = client.post('/api/interview/complete', json=complete, headers=headers)
        assert r.status_code == 403
        assert 'consent' in r.json()['detail'].lower()

        # Granting consent unlocks the existing interview flow without changing its API contract.
        r = client.post(f'/api/patients/{patient_id}/consent', headers=headers, json={
            'patient_id': patient_id, 'language': 'en-IN', 'audio_explained': False,
            'consent_type': 'Clinical case-taking', 'granted': True
        })
        assert r.status_code == 200, r.text

        r = client.get(f'/api/interview/state/{session_id}', params={'patient_id': patient_id}, headers=headers)
        assert r.status_code == 404, r.text  # consent passes; session simply does not exist yet

        r = client.post('/api/interview/answer', json=answer, headers=headers)
        assert r.status_code == 200, r.text
    finally:
        cleanup(patient_id)


def test_revoked_consent_blocks_existing_interview_continuation_and_completion():
    client = TestClient(main.app)
    patient_id, headers = register_patient(client)
    session_id = f"consent-revoke-{uuid4().hex}"
    try:
        r = client.post(f'/api/patients/{patient_id}/consent', headers=headers, json={
            'patient_id': patient_id, 'language': 'en-IN', 'audio_explained': False,
            'consent_type': 'Clinical case-taking', 'granted': True
        })
        assert r.status_code == 200

        answer = {
            'patient_id': patient_id, 'session_id': session_id,
            'question_id': 'chief_complaint', 'answer': 'I have a fever',
            'answers': {}, 'language': 'en-IN'
        }
        assert client.post('/api/interview/answer', json=answer, headers=headers).status_code == 200

        assert client.post(f'/api/patients/{patient_id}/consent/revoke', headers=headers).status_code == 200

        r = client.post('/api/interview/answer', json={**answer, 'question_id': 'onset', 'answer': 'for three days'}, headers=headers)
        assert r.status_code == 403

        r = client.get(f'/api/interview/state/{session_id}', params={'patient_id': patient_id}, headers=headers)
        assert r.status_code == 403

        r = client.post('/api/interview/complete', json={
            'patient_id': patient_id, 'session_id': session_id,
            'title': 'Clinical History', 'answers': {}, 'structured': {}
        }, headers=headers)
        assert r.status_code == 403
    finally:
        cleanup(patient_id)
