from uuid import uuid4
from fastapi.testclient import TestClient
import main


def _make_patient(client):
    db = main.SessionLocal()
    suffix = uuid4().hex[:8]
    patient = main.User(name='Regression Patient', email=f'reg-{suffix}@local', password_hash=main.hash_password('patient123'), role='patient')
    db.add(patient); db.flush(); main.make_profile(db, patient, 45, 'Other', '')
    db.commit(); pid = patient.id; email = patient.email; db.close()
    token = client.post('/api/auth/login', json={'email': email, 'password': 'patient123'}).json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    client.post(f'/api/patients/{pid}/consent', headers=headers, json={'patient_id': pid, 'language': 'en-IN', 'granted': True})
    return pid, headers


def _cleanup(pid):
    db = main.SessionLocal()
    for model, field in [(main.Consultation, main.Consultation.patient_id), (main.InterviewState, main.InterviewState.patient_id), (main.VoiceTurn, main.VoiceTurn.patient_id), (main.ConsentRecord, main.ConsentRecord.patient_id), (main.Encounter, main.Encounter.patient_id), (main.PatientProfile, main.PatientProfile.user_id), (main.UserSession, main.UserSession.user_id)]:
        db.query(model).filter(field == pid).delete(synchronize_session=False)
    db.query(main.User).filter(main.User.id == pid).delete(synchronize_session=False)
    db.commit(); db.close()


def test_completed_answer_creates_doctor_handoff_and_thirty_second_summary():
    main._ai_rate_failures.clear()
    client = TestClient(main.app); pid, headers = _make_patient(client); session_id = str(uuid4())
    try:
        question = client.get('/api/interview/questions', headers=headers, params={'patient_id': pid, 'language': 'en-IN', 'session_id': session_id}).json()['question']
        count = 0
        while True:
            response = client.post('/api/interview/answer', headers=headers, json={
                'patient_id': pid, 'session_id': session_id, 'question_id': question['id'],
                'answer': 'chest pain' if count == 0 else '', 'skipped': count != 0,
                'language': 'en-IN', 'input_mode': 'text' if count == 0 else 'skipped',
            })
            assert response.status_code == 200, response.text
            payload = response.json(); count += 1
            if payload['completed']:
                assert payload['consultation_id']
                assert 'chest pain' in payload['ai_summary']['thirty_second_summary']
                break
            question = payload['next_question']
    finally:
        _cleanup(pid)


def test_all_skipped_interview_cannot_complete():
    main._ai_rate_failures.clear()
    client = TestClient(main.app); pid, headers = _make_patient(client); session_id = str(uuid4())
    try:
        question = client.get('/api/interview/questions', headers=headers, params={'patient_id': pid, 'language': 'en-IN', 'session_id': session_id}).json()['question']
        while True:
            response = client.post('/api/interview/answer', headers=headers, json={
                'patient_id': pid, 'session_id': session_id, 'question_id': question['id'],
                'answer': '', 'skipped': True, 'language': 'en-IN', 'input_mode': 'skipped',
            })
            assert response.status_code == 200
            payload = response.json()
            if payload['completed']:
                # Completion is deliberately rejected at the persistence boundary.
                assert False, 'all-skipped interview unexpectedly completed'
            question = payload['next_question']
    except AssertionError as exc:
        if str(exc) == 'all-skipped interview unexpectedly completed':
            raise
        # The endpoint must return 400 on the final skipped answer.
        assert response.status_code == 400
    finally:
        _cleanup(pid)
