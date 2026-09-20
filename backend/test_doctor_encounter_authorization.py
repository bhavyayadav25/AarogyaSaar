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
    da = main.User(name='P0-2 Doctor A', email=f'p02-a-{suffix}@sih26047.local', password_hash=main.hash_password('doctor123'), role='doctor')
    db.add(da); db.flush()
    db.add(main.DoctorProfile(user_id=da.id, specialty='General Medicine', department='General Medicine', active=1))
    db.add(main.User(name='P0-2 Doctor B', email=f'p02-b-{suffix}@sih26047.local', password_hash=main.hash_password('doctor123'), role='doctor'))
    db.flush()
    db.add(main.DoctorProfile(user_id=db.query(main.User).filter(main.User.email.like(f'p02-b-{suffix}@%')).first().id, specialty='General Medicine', department='General Medicine', active=1))
    pa = main.User(name='P0-2 Patient A', email=f'p02-pa-{suffix}@sih26047.local', password_hash=main.hash_password('patient123'), role='patient')
    pb = main.User(name='P0-2 Patient B', email=f'p02-pb-{suffix}@sih26047.local', password_hash=main.hash_password('patient123'), role='patient')
    db.add_all([pa,pb]); db.flush(); main.make_profile(db,pa,30,'Other',''); main.make_profile(db,pb,31,'Other','')
    eb = main.Encounter(patient_id=pb.id, doctor_id=db.query(main.User).filter(main.User.email.like(f'p02-b-{suffix}@%')).first().id, department='General Medicine', visit_date='2099-02-01', token_number=90000+pb.id, priority='normal', status='called', reason='P0-2')
    db.add(eb); db.commit()
    ids=(da.id, db.query(main.User).filter(main.User.email.like(f'p02-b-{suffix}@%')).first().id, pa.id, pb.id, eb.id, da.email)
    db.close(); return ids


def cleanup(ids):
    da, dbid, pa, pb, eid, _ = ids
    db=main.SessionLocal()
    try:
        db.query(main.Consultation).filter(main.Consultation.patient_id.in_([pa,pb])).delete(synchronize_session=False)
        db.query(main.Encounter).filter(main.Encounter.id==eid).delete(synchronize_session=False)
        db.query(main.PatientProfile).filter(main.PatientProfile.user_id.in_([pa,pb])).delete(synchronize_session=False)
        db.query(main.UserSession).filter(main.UserSession.user_id.in_([da,dbid,pa,pb])).delete(synchronize_session=False)
        db.query(main.DoctorProfile).filter(main.DoctorProfile.user_id.in_([da,dbid])).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id.in_([da,dbid,pa,pb])).delete(synchronize_session=False)
        db.commit()
    finally: db.close()


def test_doctor_cannot_access_other_doctors_encounter_or_queue():
    client=TestClient(main.app); ids=make_fixture()
    try:
        doctor=auth(client, ids[5], 'doctor123')
        assert client.get(f'/api/encounters/{ids[4]}', headers=doctor).status_code == 403
        assert client.post(f'/api/encounters/{ids[4]}/status', headers=doctor, json={'status':'in_consultation'}).status_code == 403
        q=client.get('/api/queue', headers=doctor, params={'department':'General Medicine','visit_date':'2099-02-01'})
        assert q.status_code == 200
        assert ids[4] not in {x['id'] for x in q.json()['queue']}
    finally: cleanup(ids)


def test_doctor_cannot_bootstrap_access_by_creating_encounter_for_unassigned_patient():
    client=TestClient(main.app); ids=make_fixture()
    try:
        doctor=auth(client, ids[5], 'doctor123')
        r=client.post('/api/encounters', headers=doctor, json={'patient_id':ids[2], 'doctor_id':ids[0], 'department':'General Medicine','priority':'normal','reason':'attempt'})
        assert r.status_code == 403
    finally: cleanup(ids)
