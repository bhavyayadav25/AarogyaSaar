"""FIX 12 — strict doctor-to-consultation authorization."""
from uuid import uuid4
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def setup_pair():
    db = main.SessionLocal(); s = uuid4().hex[:10]
    doctor = main.User(name='FIX12 Doctor', email=f'fix12-d-{s}@sih26047.local', password_hash=main.hash_password('doctor123'), role='doctor')
    patient = main.User(name='FIX12 Patient', email=f'fix12-p-{s}@sih26047.local', password_hash=main.hash_password('patient123'), role='patient')
    db.add_all([doctor, patient]); db.flush(); main.make_profile(db, patient, 50, 'Other', '')
    enc = main.Encounter(patient_id=patient.id, doctor_id=doctor.id, department='General Medicine', visit_date='2099-02-01', token_number=20000+patient.id, priority='normal', status='in_consultation', reason='FIX12')
    db.add(enc); db.flush()
    c = main.Consultation(patient_id=patient.id, encounter_id=enc.id, title='FIX12', summary='test', consultation_status='in_progress')
    db.add(c); db.commit(); db.refresh(doctor); db.refresh(patient); db.refresh(enc); db.refresh(c)
    ids=(doctor.id, patient.id, enc.id, c.id); db.close(); return ids


def cleanup(ids):
    db=main.SessionLocal(); did,pid,eid,cid=ids
    db.query(main.Consultation).filter(main.Consultation.id==cid).delete(synchronize_session=False)
    db.query(main.Encounter).filter(main.Encounter.id==eid).delete(synchronize_session=False)
    db.query(main.PatientProfile).filter(main.PatientProfile.user_id==pid).delete(synchronize_session=False)
    db.query(main.UserSession).filter(main.UserSession.user_id==did).delete(synchronize_session=False)
    db.query(main.User).filter(main.User.id.in_([did,pid])).delete(synchronize_session=False); db.commit(); db.close()


def test_doctor_cannot_access_another_doctors_consultation_anywhere():
    client=TestClient(main.app); ids=setup_pair()
    try:
        doctor_a=auth(client,'doctor@sih26047.local','doctor123')
        cid=ids[3]
        paths=[
            f'/api/doctor/consultations/{cid}/record',
            f'/api/doctor/consultations/{cid}/copilot',
            f'/api/doctor/consultations/{cid}/clinical-gate',
            f'/api/doctor/consultations/{cid}/explainability',
            f'/api/doctor/consultations/{cid}/ai-summary',
        ]
        for p in paths:
            assert client.get(p,headers=doctor_a).status_code==403, p
        assert client.put(f'/api/doctor/consultations/{cid}/review',headers=doctor_a,json={'doctor_review':'Reviewed','doctor_notes':'x'}).status_code==403
        assert client.put(f'/api/doctor/consultations/{cid}/record',headers=doctor_a,json={'sections':{},'doctor_notes':'x'}).status_code==403
        assert client.post(f'/api/doctor/consultations/{cid}/complete',headers=doctor_a,json={'sections':{},'doctor_notes':'x','doctor_review':'Completed'}).status_code==403
    finally: cleanup(ids)


def test_doctor_consultation_list_is_scoped_to_linked_assigned_encounter():
    client=TestClient(main.app); ids=setup_pair()
    try:
        doctor_a=auth(client,'doctor@sih26047.local','doctor123')
        r=client.get('/api/doctor/consultations',headers=doctor_a); assert r.status_code==200
        assert ids[3] not in {x['id'] for x in r.json()['consultations']}
    finally: cleanup(ids)


def test_doctor_cannot_start_consultation_on_unassigned_encounter():
    db=main.SessionLocal(); s=uuid4().hex[:10]
    patient=main.User(name='FIX12 Unassigned',email=f'fix12-u-{s}@sih26047.local',password_hash=main.hash_password('patient123'),role='patient')
    db.add(patient); db.flush(); main.make_profile(db,patient,40,'Other','')
    enc=main.Encounter(patient_id=patient.id,doctor_id=None,department='General Medicine',visit_date='2099-02-02',token_number=30000+patient.id,priority='normal',status='called',reason='FIX12')
    db.add(enc); db.commit(); eid,pid=enc.id,patient.id; db.close()
    try:
        client=TestClient(main.app); h=auth(client,'doctor@sih26047.local','doctor123')
        r=client.post(f'/api/doctor/encounters/{eid}/consultation',headers=h,json={'encounter_id':eid,'title':'Should fail'})
        assert r.status_code==403
    finally:
        db=main.SessionLocal(); db.query(main.Consultation).filter(main.Consultation.encounter_id==eid).delete(synchronize_session=False); db.query(main.Encounter).filter(main.Encounter.id==eid).delete(synchronize_session=False); db.query(main.PatientProfile).filter(main.PatientProfile.user_id==pid).delete(synchronize_session=False); db.query(main.User).filter(main.User.id==pid).delete(synchronize_session=False); db.commit(); db.close()
