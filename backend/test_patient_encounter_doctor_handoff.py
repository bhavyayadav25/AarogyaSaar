from uuid import uuid4
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def make_fixture():
    db = main.SessionLocal()
    suffix = uuid4().hex[:10]
    doctor = main.User(name='Handoff Doctor', email=f'handoff-doc-{suffix}@sih26047.local', password_hash=main.hash_password('doctor123'), role='doctor')
    patient = main.User(name='Handoff Patient', email=f'handoff-pat-{suffix}@sih26047.local', password_hash=main.hash_password('patient123'), role='patient')
    db.add_all([doctor, patient]); db.flush()
    main.make_profile(db, patient, 35, 'Other', '')
    db.add(main.DoctorProfile(user_id=doctor.id, specialty='General Medicine', department='Handoff Medicine', active=1))
    db.flush()
    from datetime import date
    db.add(main.Encounter(patient_id=patient.id, doctor_id=doctor.id, department='Handoff Medicine', visit_date=date.today().isoformat(), token_number=900000 + patient.id, priority='normal', status='waiting', reason='Handoff fixture'))
    db.commit()
    ids = (doctor.id, patient.id, doctor.email, patient.email)
    db.close()
    return ids


def cleanup(ids):
    doctor_id, patient_id, _, _ = ids
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
        db.query(main.UserSession).filter(main.UserSession.user_id.in_([doctor_id, patient_id])).delete(synchronize_session=False)
        db.query(main.DoctorProfile).filter(main.DoctorProfile.user_id == doctor_id).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id.in_([doctor_id, patient_id])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def grant_consent(client, headers, patient_id):
    r = client.post(f'/api/patients/{patient_id}/consent', headers=headers, json={
        'patient_id': patient_id, 'language': 'en-IN', 'audio_explained': False, 'granted': True
    })
    assert r.status_code == 200, r.text


def test_starting_interview_creates_routed_encounter_for_doctor_handoff():
    client = TestClient(main.app)
    ids = make_fixture()
    try:
        doctor_id, patient_id, doctor_email, patient_email = ids
        patient_headers = auth(client, patient_email, 'patient123')
        doctor_headers = auth(client, doctor_email, 'doctor123')
        grant_consent(client, patient_headers, patient_id)

        start = client.get('/api/interview/questions', headers=patient_headers, params={'patient_id': patient_id, 'language': 'en-IN'})
        assert start.status_code == 200, start.text

        db = main.SessionLocal()
        try:
            encounter = db.query(main.Encounter).filter(main.Encounter.patient_id == patient_id).one()
            assert encounter.doctor_id == doctor_id
            assert encounter.status == 'waiting'
        finally:
            db.close()

        patients = client.get('/api/patients', headers=doctor_headers)
        assert patients.status_code == 200, patients.text
        assert patient_id in {p['id'] for p in patients.json()['patients']}
    finally:
        cleanup(ids)


def test_interview_completion_links_history_to_handoff_encounter():
    client = TestClient(main.app)
    ids = make_fixture()
    try:
        doctor_id, patient_id, doctor_email, patient_email = ids
        patient_headers = auth(client, patient_email, 'patient123')
        doctor_headers = auth(client, doctor_email, 'doctor123')
        grant_consent(client, patient_headers, patient_id)
        start = client.get('/api/interview/questions', headers=patient_headers, params={'patient_id': patient_id, 'language': 'en-IN'})
        assert start.status_code == 200, start.text

        payload = {
            'patient_id': patient_id,
            'session_id': str(uuid4()),
            'title': 'Handoff test history',
            'answers': {'chief_complaint': 'fever'},
            'structured': {'chief_complaint': 'fever'}
        }
        complete = client.post('/api/interview/complete', headers=patient_headers, json=payload)
        assert complete.status_code == 200, complete.text
        consultation_id = complete.json()['consultation_id']

        db = main.SessionLocal()
        try:
            record = db.query(main.Consultation).filter(main.Consultation.id == consultation_id).one()
            encounter = db.query(main.Encounter).filter(main.Encounter.id == record.encounter_id).one()
            assert record.patient_id == patient_id
            assert record.encounter_id == encounter.id
            assert encounter.doctor_id == doctor_id
        finally:
            db.close()

        histories = client.get('/api/doctor/consultations', headers=doctor_headers)
        assert histories.status_code == 200, histories.text
        assert consultation_id in {c['id'] for c in histories.json()['consultations']}
    finally:
        cleanup(ids)
