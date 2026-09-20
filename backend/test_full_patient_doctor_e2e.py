from uuid import uuid4
from fastapi.testclient import TestClient
import main


def _auth(client, email, password):
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def _fixture():
    db = main.SessionLocal()
    suffix = uuid4().hex[:10]
    patient = main.User(name='E2E Patient', email=f'e2e-patient-{suffix}@sih26047.local', password_hash=main.hash_password('patient123'), role='patient')
    doctor = main.User(name='E2E Doctor', email=f'e2e-doctor-{suffix}@sih26047.local', password_hash=main.hash_password('doctor123'), role='doctor')
    db.add_all([patient, doctor])
    db.flush()
    main.make_profile(db, patient, 42, 'Other', '')
    db.add(main.DoctorProfile(user_id=doctor.id, specialty='General Medicine', department='General Medicine', active=1))
    db.commit()
    ids = (patient.id, doctor.id, patient.email, doctor.email)
    db.close()
    return ids


def _cleanup(ids):
    patient_id, doctor_id, _, _ = ids
    db = main.SessionLocal()
    try:
        encounter_ids = [x[0] for x in db.query(main.Encounter.id).filter(main.Encounter.patient_id == patient_id).all()]
        db.query(main.Consultation).filter(main.Consultation.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.InterviewState).filter(main.InterviewState.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.VoiceTurn).filter(main.VoiceTurn.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.ConsentRecord).filter(main.ConsentRecord.patient_id == patient_id).delete(synchronize_session=False)
        if encounter_ids:
            db.query(main.Encounter).filter(main.Encounter.id.in_(encounter_ids)).delete(synchronize_session=False)
        db.query(main.PatientProfile).filter(main.PatientProfile.user_id == patient_id).delete(synchronize_session=False)
        db.query(main.DoctorProfile).filter(main.DoctorProfile.user_id == doctor_id).delete(synchronize_session=False)
        db.query(main.UserSession).filter(main.UserSession.user_id.in_([patient_id, doctor_id])).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id.in_([patient_id, doctor_id])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_complete_patient_to_doctor_journey_and_consent_gate():
    client = TestClient(main.app)
    ids = _fixture()
    try:
        patient_id, doctor_id, patient_email, doctor_email = ids
        patient_headers = _auth(client, patient_email, 'patient123')

        # Consent is a hard backend gate, not merely a frontend navigation rule.
        revoked = client.post(f'/api/patients/{patient_id}/consent/revoke', headers=patient_headers)
        assert revoked.status_code == 200
        blocked = client.get('/api/interview/questions', headers=patient_headers,
                             params={'patient_id': patient_id, 'language': 'en-IN'})
        assert blocked.status_code == 403

        granted = client.post(f'/api/patients/{patient_id}/consent', headers=patient_headers,
                              json={'patient_id': patient_id, 'language': 'en-IN', 'audio_explained': False, 'granted': True})
        assert granted.status_code == 200

        started = client.get('/api/interview/questions', headers=patient_headers,
                             params={'patient_id': patient_id, 'language': 'en-IN'})
        assert started.status_code == 200
        question = started.json()['question']
        session_id = str(uuid4())

        answer = client.post('/api/interview/answer', headers=patient_headers, json={
            'patient_id': patient_id,
            'session_id': session_id,
            'question_id': question['id'],
            'answer': 'I have fever and cough for three days',
            'answers': {},
            'language': 'en-IN',
        })
        assert answer.status_code == 200, answer.text

        state = client.get(f'/api/interview/state/{session_id}', headers=patient_headers,
                           params={'patient_id': patient_id})
        assert state.status_code == 200
        structured = state.json()['structured']

        # Revoke during the active session: continuation and completion must stop.
        revoked = client.post(f'/api/patients/{patient_id}/consent/revoke', headers=patient_headers)
        assert revoked.status_code == 200
        blocked_state = client.get(f'/api/interview/state/{session_id}', headers=patient_headers,
                                   params={'patient_id': patient_id})
        assert blocked_state.status_code == 403
        blocked_complete = client.post('/api/interview/complete', headers=patient_headers, json={
            'patient_id': patient_id,
            'session_id': session_id,
            'title': 'Blocked history',
            'answers': structured,
            'structured': structured,
        })
        assert blocked_complete.status_code == 403

        # Re-grant consent and complete the exact server-owned history.
        granted = client.post(f'/api/patients/{patient_id}/consent', headers=patient_headers,
                              json={'patient_id': patient_id, 'language': 'en-IN', 'audio_explained': False, 'granted': True})
        assert granted.status_code == 200
        completed = client.post('/api/interview/complete', headers=patient_headers, json={
            'patient_id': patient_id,
            'session_id': session_id,
            'title': structured.get('chief_complaint', 'AI Clinical History'),
            'answers': structured,
            'structured': structured,
        })
        assert completed.status_code == 200, completed.text
        consultation_id = completed.json()['consultation_id']

        # Doctor receives the same patient through the assigned encounter.
        db = main.SessionLocal()
        try:
            encounter = db.query(main.Encounter).filter(main.Encounter.patient_id == patient_id).order_by(main.Encounter.created_at.desc()).first()
            assert encounter is not None and encounter.doctor_id is not None
            routed_doctor = db.query(main.User).filter(main.User.id == encounter.doctor_id, main.User.role == 'doctor').first()
            assert routed_doctor is not None
            routed_doctor_email = routed_doctor.email
        finally:
            db.close()
        doctor_headers = _auth(client, routed_doctor_email, 'doctor123')
        doctor_list = client.get('/api/doctor/consultations', headers=doctor_headers)
        assert doctor_list.status_code == 200
        handed_off = next(x for x in doctor_list.json()['consultations'] if x['id'] == consultation_id)
        encounter_id = handed_off['encounter_id']
        assert encounter_id is not None

        patients = client.get('/api/patients', headers=doctor_headers)
        assert patients.status_code == 200
        doctor_patient = next(x for x in patients.json()['patients'] if x['id'] == patient_id)
        assert doctor_patient['encounter_id'] == encounter_id

        workspace = client.get(f'/api/doctor/patients/{patient_id}/workspace', headers=doctor_headers,
                               params={'encounter_id': encounter_id})
        assert workspace.status_code == 200, workspace.text
        data = workspace.json()
        assert data['encounter']['id'] == encounter_id
        exact = next(x for x in data['consultations'] if x['id'] == consultation_id)
        assert exact['encounter_id'] == encounter_id
        assert exact['title'] == structured.get('chief_complaint')

        # Review remains attached to the same consultation/handoff.
        review = client.put(f'/api/doctor/consultations/{consultation_id}/review', headers=doctor_headers,
                            json={'doctor_review': 'Reviewed', 'doctor_notes': 'Reviewed AI-assisted history.'})
        assert review.status_code == 200
        workspace_after_review = client.get(f'/api/doctor/patients/{patient_id}/workspace', headers=doctor_headers,
                                            params={'encounter_id': encounter_id})
        assert workspace_after_review.status_code == 200
        reviewed = next(x for x in workspace_after_review.json()['consultations'] if x['id'] == consultation_id)
        assert reviewed['doctor_review'] == 'Reviewed'

        # Exact encounter scoping: a fabricated/non-patient encounter cannot be opened.
        wrong = client.get(f'/api/doctor/patients/{patient_id}/workspace', headers=doctor_headers,
                           params={'encounter_id': 999999999})
        assert wrong.status_code == 404
    finally:
        _cleanup(ids)
