from uuid import uuid4
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def create_patient(client):
    email = f'fix1-{uuid4().hex[:10]}@sih26047.local'
    r = client.post('/api/auth/register', json={
        'name': 'FIX1 Test Patient', 'email': email, 'password': 'patient123',
        'age': 35, 'gender': 'Other', 'phone': ''
    })
    assert r.status_code == 200, r.text
    return email, {'Authorization': 'Bearer ' + r.json()['access_token']}, r.json()['user']['id']


def cleanup_patient(patient_id):
    db = main.SessionLocal()
    try:
        # Test-only cleanup for the temporary patient and dependent prototype rows.
        db.query(main.VoiceTurn).filter(main.VoiceTurn.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.InterviewState).filter(main.InterviewState.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.AccessibilityPreference).filter(main.AccessibilityPreference.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.ConsentRecord).filter(main.ConsentRecord.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.AyushAssessment).filter(main.AyushAssessment.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.Consultation).filter(main.Consultation.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.Encounter).filter(main.Encounter.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.MedicalDocument).filter(main.MedicalDocument.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.FHIRExportRecord).filter(main.FHIRExportRecord.patient_id == patient_id).delete(synchronize_session=False)
        db.query(main.UserSession).filter(main.UserSession.user_id == patient_id).delete(synchronize_session=False)
        db.query(main.PatientProfile).filter(main.PatientProfile.user_id == patient_id).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id == patient_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_patient_cannot_access_another_patients_profile_and_clinical_data():
    client = TestClient(main.app)
    headers = auth(client, 'patient@sih26047.local', 'patient123')
    email, other_headers, other_id = create_patient(client)
    try:
        for path in [
            f'/api/patients/{other_id}',
            f'/api/patients/{other_id}/consultations',
            f'/api/patients/{other_id}/documents',
            f'/api/patients/{other_id}/timeline',
            f'/api/patients/{other_id}/clinical-summary',
            f'/api/patients/{other_id}/consent',
            f'/api/patients/{other_id}/ayush',
            f'/api/patients/{other_id}/accessibility',
        ]:
            r = client.get(path, headers=headers)
            assert r.status_code == 403, f'{path}: {r.status_code} {r.text}'

        r = client.put(f'/api/patients/{other_id}', headers=headers, json={
            'name': 'tampered', 'age': 40, 'gender': 'Other', 'phone': '',
            'blood_group': '', 'allergies': '', 'conditions': '', 'medications': '', 'address': ''
        })
        assert r.status_code == 403

        # The owning patient can still access their own profile.
        r = client.get('/api/patients/1', headers=headers)
        assert r.status_code == 200
    finally:
        cleanup_patient(other_id)


def test_patient_cannot_access_clinician_or_interoperability_endpoints():
    client = TestClient(main.app)
    patient = auth(client, 'patient@sih26047.local', 'patient123')
    blocked = [
        '/api/doctor/consultations',
        '/api/doctor/patients/1/workspace',
        '/api/doctor/patients/1/fhir-preview',
        '/api/doctor/patients/1/abdm-readiness',
        '/api/doctor/patients/1/abdm-package',
        '/api/doctor/patients/1/fhir-validate',
    ]
    for path in blocked:
        method = 'post' if path.endswith('fhir-validate') else 'get'
        r = getattr(client, method)(path, headers=patient)
        assert r.status_code == 403, f'{path}: {r.status_code} {r.text}'


def test_fhir_export_uses_authenticated_actor_not_client_supplied_id():
    client = TestClient(main.app)
    doctor = auth(client, 'doctor@sih26047.local', 'doctor123')
    db = main.SessionLocal()
    try:
        doctor_id = db.query(main.User).filter(main.User.email == 'doctor@sih26047.local').first().id
        if not db.query(main.Encounter).filter(main.Encounter.patient_id == 1, main.Encounter.doctor_id == doctor_id).first():
            db.add(main.Encounter(patient_id=1, doctor_id=doctor_id, department='General Medicine', visit_date='2099-03-02', token_number=777002, priority='normal', status='completed', reason='FHIR auth test'))
            db.commit()
    finally:
        db.close()
    r = client.post('/api/doctor/patients/1/fhir-export', headers=doctor, json={
        'patient_id': 1, 'exported_by': 999999, 'abha_address': None
    })
    assert r.status_code == 200, r.text
    export_id = r.json()['export_id']
    db = main.SessionLocal()
    try:
        rec = db.query(main.FHIRExportRecord).filter(main.FHIRExportRecord.id == export_id).first()
        assert rec is not None
        doctor_id = db.query(main.User).filter(main.User.email == 'doctor@sih26047.local').first().id
        assert rec.exported_by == doctor_id
    finally:
        db.query(main.FHIRExportRecord).filter(main.FHIRExportRecord.id == export_id).delete(synchronize_session=False)
        db.commit()
        db.close()
