"""FIX 13 — centralized FHIR/ABDM patient authorization consistency."""
from uuid import uuid4
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def setup_pair():
    db = main.SessionLocal(); s = uuid4().hex[:10]
    doctor = main.User(name='FIX13 Doctor', email=f'fix13-d-{s}@sih26047.local', password_hash=main.hash_password('doctor123'), role='doctor')
    other = main.User(name='FIX13 Other Doctor', email=f'fix13-o-{s}@sih26047.local', password_hash=main.hash_password('doctor123'), role='doctor')
    patient = main.User(name='FIX13 Patient', email=f'fix13-p-{s}@sih26047.local', password_hash=main.hash_password('patient123'), role='patient')
    db.add_all([doctor, other, patient]); db.flush(); main.make_profile(db, patient, 50, 'Other', '')
    enc = main.Encounter(patient_id=patient.id, doctor_id=other.id, department='General Medicine', visit_date='2099-03-01', token_number=40000+patient.id, priority='normal', status='in_consultation', reason='FIX13')
    db.add(enc); db.commit(); db.refresh(doctor); db.refresh(other); db.refresh(patient); db.refresh(enc)
    ids=(doctor.id, other.id, patient.id, enc.id); db.close(); return ids


def cleanup(ids):
    db=main.SessionLocal(); did,oid,pid,eid=ids
    db.query(main.FHIRExportRecord).filter(main.FHIRExportRecord.patient_id==pid).delete(synchronize_session=False)
    db.query(main.Encounter).filter(main.Encounter.id==eid).delete(synchronize_session=False)
    db.query(main.PatientProfile).filter(main.PatientProfile.user_id==pid).delete(synchronize_session=False)
    db.query(main.UserSession).filter(main.UserSession.user_id.in_([did,oid])).delete(synchronize_session=False)
    db.query(main.User).filter(main.User.id.in_([did,oid,pid])).delete(synchronize_session=False)
    db.commit(); db.close()


def test_unassigned_doctor_is_denied_every_fhir_abdm_patient_endpoint():
    client=TestClient(main.app); ids=setup_pair()
    try:
        # Resolve the unique test doctor's email from the setup record.
        db=main.SessionLocal(); email=db.query(main.User).filter(main.User.id==ids[0]).first().email; db.close()
        h=auth(client,email,'doctor123')
        pid=ids[2]
        paths=[
            f'/api/doctor/patients/{pid}/fhir-preview',
            f'/api/doctor/patients/{pid}/abdm-readiness',
            f'/api/doctor/patients/{pid}/abdm-package',
        ]
        for p in paths:
            assert client.get(p,headers=h).status_code==403, p
        assert client.post(f'/api/doctor/patients/{pid}/abdm-package',headers=h,json={'patient_id':pid}).status_code==403
        assert client.post(f'/api/doctor/patients/{pid}/fhir-validate',headers=h).status_code==403
        assert client.post(f'/api/doctor/patients/{pid}/fhir-export',headers=h,json={'patient_id':pid}).status_code==403
    finally: cleanup(ids)


def test_assigned_doctor_can_use_fhir_preview_and_admin_remains_hospital_wide():
    client=TestClient(main.app); ids=setup_pair()
    try:
        db=main.SessionLocal(); doctor_email=db.query(main.User).filter(main.User.id==ids[1]).first().email; db.close()
        doctor=auth(client,doctor_email,'doctor123')
        pid=ids[2]
        assert client.get(f'/api/doctor/patients/{pid}/fhir-preview',headers=doctor).status_code==200
        assert client.get(f'/api/doctor/patients/{pid}/abdm-readiness',headers=doctor).status_code==200
        admin=auth(client,'admin@sih26047.local','admin123')
        assert client.get(f'/api/doctor/patients/{pid}/fhir-preview',headers=admin).status_code==200
    finally: cleanup(ids)
