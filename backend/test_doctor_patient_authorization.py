"""FIX 10 — strict doctor-to-patient authorization using existing encounter assignments."""
from uuid import uuid4
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def create_doctor_and_patient():
    db = main.SessionLocal()
    suffix = uuid4().hex[:10]
    doctor = main.User(name='FIX10 Doctor', email=f'fix10-doctor-{suffix}@sih26047.local', password_hash=main.hash_password('doctor123'), role='doctor')
    patient = main.User(name='FIX10 Patient', email=f'fix10-patient-{suffix}@sih26047.local', password_hash=main.hash_password('patient123'), role='patient')
    db.add_all([doctor, patient]); db.flush()
    main.make_profile(db, patient, 50, 'Other', '')
    encounter = main.Encounter(patient_id=patient.id, doctor_id=doctor.id, department='General Medicine', visit_date='2099-01-01', token_number=(10_000 + patient.id), priority='normal', status='completed', reason='FIX10 test')
    db.add(encounter); db.commit()
    ids = (doctor.id, patient.id)
    db.close()
    return ids


def cleanup(ids):
    db = main.SessionLocal()
    try:
        doctor_id, patient_id = ids
        db.query(main.Consultation).filter(main.Consultation.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.Encounter).filter(main.Encounter.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.PatientProfile).filter(main.PatientProfile.user_id == patient_id).delete(synchronize_session=False)
        db.query(main.UserSession).filter(main.UserSession.user_id.in_([doctor_id, patient_id])).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id.in_([doctor_id, patient_id])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_doctor_can_access_assigned_patient_but_not_unassigned_patient():
    client = TestClient(main.app)
    db = main.SessionLocal()
    doctor_b_id = patient_b_id = None
    try:
        doctor_b_id, patient_b_id = create_doctor_and_patient()
        doctor_a = auth(client, 'doctor@sih26047.local', 'doctor123')
        # Make the test relationship explicit rather than relying on fixture row IDs.
        db.add(main.Encounter(patient_id=1, doctor_id=db.query(main.User).filter(main.User.email == 'doctor@sih26047.local').first().id, department='General Medicine', visit_date='2099-03-01', token_number=777001, priority='normal', status='completed', reason='FIX10 demo assignment'))
        db.commit()

        # The demo patient is explicitly assigned to doctor A.
        assert client.get('/api/patients/1', headers=doctor_a).status_code == 200
        assert client.get('/api/patients/1/clinical-summary', headers=doctor_a).status_code == 200

        # Doctor A must not be able to pivot the patient_id to doctor B's patient.
        for path in [
            f'/api/patients/{patient_b_id}',
            f'/api/patients/{patient_b_id}/clinical-summary',
            f'/api/patients/{patient_b_id}/risk-assessment',
            f'/api/patients/{patient_b_id}/decision-support',
            f'/api/patients/{patient_b_id}/medication-intelligence',
            f'/api/patients/{patient_b_id}/investigation-intelligence',
            f'/api/doctor/patients/{patient_b_id}/workspace',
            f'/api/doctor/patients/{patient_b_id}/fhir-preview',
            f'/api/doctor/patients/{patient_b_id}/abdm-readiness',
            f'/api/doctor/patients/{patient_b_id}/abdm-package',
        ]:
            r = client.get(path, headers=doctor_a)
            assert r.status_code == 403, f'{path}: {r.status_code} {r.text}'

        # Directory is also scoped, so doctor A cannot enumerate doctor B's patient.
        r = client.get('/api/patients', headers=doctor_a)
        assert r.status_code == 200
        assert patient_b_id not in {p['id'] for p in r.json()['patients']}
    finally:
        if doctor_b_id and patient_b_id:
            cleanup((doctor_b_id, patient_b_id))
        db.close()


def test_doctor_cannot_read_or_modify_another_doctors_encounter_or_consultation():
    client = TestClient(main.app)
    db = main.SessionLocal()
    doctor_b = patient_b = consultation = None
    try:
        doctor_b_id, patient_b_id = create_doctor_and_patient()
        encounter = db.query(main.Encounter).filter(main.Encounter.patient_id == patient_b_id).first()
        consultation = main.Consultation(patient_id=patient_b_id, encounter_id=encounter.id, title='FIX10', summary='test')
        db.add(consultation); db.commit(); db.refresh(consultation)
        doctor_a = auth(client, 'doctor@sih26047.local', 'doctor123')

        r = client.get(f'/api/encounters/{encounter.id}', headers=doctor_a)
        assert r.status_code == 403
        r = client.get(f'/api/doctor/consultations/{consultation.id}/ai-summary', headers=doctor_a)
        assert r.status_code == 403
        r = client.get(f'/api/doctor/consultations/{consultation.id}/explainability', headers=doctor_a)
        assert r.status_code == 403
        r = client.get(f'/api/doctor/consultations/{consultation.id}/record', headers=doctor_a)
        assert r.status_code == 403
    finally:
        if doctor_b_id and patient_b_id:
            cleanup((doctor_b_id, patient_b_id))
        db.close()


def test_triage_and_admin_keep_hospital_wide_patient_access():
    # This FIX only narrows doctors; it does not unexpectedly narrow authorized triage/admin workflows.
    client = TestClient(main.app)
    db = main.SessionLocal()
    doctor_b_id = patient_b_id = None
    triage = None
    try:
        doctor_b_id, patient_b_id = create_doctor_and_patient()
        triage = db.query(main.User).filter(main.User.role == 'triage').first()
        if not triage:
            triage = main.User(name='FIX10 Triage', email=f'fix10-triage-{uuid4().hex[:10]}@sih26047.local', password_hash=main.hash_password('triage123'), role='triage')
            db.add(triage); db.commit(); db.refresh(triage)
        triage_headers = auth(client, triage.email, 'triage123')
        assert client.get(f'/api/patients/{patient_b_id}', headers=triage_headers).status_code == 200
    finally:
        if doctor_b_id and patient_b_id:
            cleanup((doctor_b_id, patient_b_id))
        if triage and triage.email.startswith('fix10-triage-'):
            db.query(main.UserSession).filter(main.UserSession.user_id == triage.id).delete(synchronize_session=False)
            db.query(main.User).filter(main.User.id == triage.id).delete(synchronize_session=False)
            db.commit()
        db.close()
