from uuid import uuid4
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def create_patient(client):
    email = f'fix2-{uuid4().hex[:10]}@sih26047.local'
    r = client.post('/api/auth/register', json={
        'name': 'FIX2 Test Patient', 'email': email, 'password': 'patient123',
        'age': 35, 'gender': 'Other', 'phone': ''
    })
    assert r.status_code == 200, r.text
    return email, {'Authorization': 'Bearer ' + r.json()['access_token']}, r.json()['user']['id']


def cleanup_patient(patient_id):
    db = main.SessionLocal()
    try:
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


def make_encounter(patient_id, doctor_id=None):
    db = main.SessionLocal()
    try:
        encounter = main.Encounter(
            patient_id=patient_id,
            doctor_id=doctor_id,
            department='General Medicine',
            visit_date='2099-01-01',
            token_number=900000 + patient_id,
            priority='normal',
            status='waiting',
            reason='FIX2 document authorization test',
        )
        db.add(encounter)
        db.commit()
        db.refresh(encounter)
        return encounter.id
    finally:
        db.close()


def delete_encounter(encounter_id):
    db = main.SessionLocal()
    try:
        db.query(main.Encounter).filter(main.Encounter.id == encounter_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_patient_cannot_cross_access_stored_document_processing_and_read_paths():
    client = TestClient(main.app)
    owner = auth(client, 'patient@sih26047.local', 'patient123')
    _, other, other_id = create_patient(client)
    document_id = None
    try:
        upload = client.post('/api/documents/upload', headers=owner, data={
            'patient_id': 1, 'document_type': 'Other'
        }, files={'file': ('fix2.txt', b'Patient one private medical record', 'text/plain')})
        assert upload.status_code == 200, upload.text
        document_id = upload.json()['document']['id']

        for path, method in [
            (f'/api/documents/{document_id}/verification', 'get'),
            (f'/api/documents/{document_id}/explainability', 'get'),
            (f'/api/documents/{document_id}/timeline-context', 'get'),
            (f'/api/documents/{document_id}/clinical-handoff', 'get'),
            (f'/api/documents/{document_id}/classify', 'post'),
            (f'/api/documents/{document_id}/extract', 'post'),
        ]:
            r = getattr(client, method)(path, headers=other)
            assert r.status_code == 403, f'{method} {path}: {r.status_code} {r.text}'
    finally:
        cleanup_patient(other_id)


def test_raw_document_processing_apis_require_clinical_staff():
    client = TestClient(main.app)
    patient = auth(client, 'patient@sih26047.local', 'patient123')
    payload = {'text': 'Patient has fever and cough', 'filename': 'note.txt', 'requested_type': 'Other'}
    r = client.post('/api/documents/classify', headers=patient, json=payload)
    assert r.status_code == 403
    r = client.post('/api/documents/extract', headers=patient, json={
        'text': 'Hemoglobin 12 g/dL', 'document_type': 'Lab Report'
    })
    assert r.status_code == 403


def test_medical_document_intake_requires_real_encounter_and_owner_or_assigned_doctor():
    client = TestClient(main.app)
    patient_headers = auth(client, 'patient@sih26047.local', 'patient123')
    doctor_headers = auth(client, 'doctor@sih26047.local', 'doctor123')
    _, other_headers, other_id = create_patient(client)
    own_encounter = other_encounter = None
    try:
        own_encounter = make_encounter(1)
        other_encounter = make_encounter(other_id)

        # Patient cannot claim another patient's encounter.
        r = client.post('/api/documents/intake/upload', headers=patient_headers,
                        data={'patient_id': '1', 'encounter_id': str(other_encounter)},
                        files={'document': ('report.pdf', b'%PDF-test', 'application/pdf')})
        assert r.status_code == 403, r.text

        # Patient cannot use a fake/nonexistent encounter even for their own patient id.
        r = client.post('/api/documents/intake/upload', headers=patient_headers,
                        data={'patient_id': '1', 'encounter_id': '999999999'},
                        files={'document': ('report.pdf', b'%PDF-test', 'application/pdf')})
        assert r.status_code == 404, r.text

        # A doctor cannot use an encounter assigned to another/no doctor.
        r = client.post('/api/documents/intake/upload', headers=doctor_headers,
                        data={'patient_id': '1', 'encounter_id': str(own_encounter)},
                        files={'document': ('report.pdf', b'%PDF-test', 'application/pdf')})
        assert r.status_code == 403, r.text

        # Assign the encounter to the demo doctor; upload is then authorized.
        db = main.SessionLocal()
        try:
            enc = db.query(main.Encounter).filter(main.Encounter.id == own_encounter).first()
            enc.doctor_id = db.query(main.User).filter(main.User.email == 'doctor@sih26047.local').first().id
            db.commit()
        finally:
            db.close()
        r = client.post('/api/documents/intake/upload', headers=doctor_headers,
                        data={'patient_id': '1', 'encounter_id': str(own_encounter)},
                        files={'document': ('report.pdf', b'%PDF-test', 'application/pdf')})
        assert r.status_code == 200, r.text
        doc_id = r.json()['document']['document_id']

        # Patient owner may read its own AI-3A document.
        r = client.get(f'/api/documents/intake/{doc_id}', headers=patient_headers)
        assert r.status_code == 200, r.text

        # Other patient cannot read it.
        r = client.get(f'/api/documents/intake/{doc_id}', headers=other_headers)
        assert r.status_code == 403, r.text
    finally:
        delete_encounter(own_encounter) if own_encounter else None
        delete_encounter(other_encounter) if other_encounter else None
        cleanup_patient(other_id)
