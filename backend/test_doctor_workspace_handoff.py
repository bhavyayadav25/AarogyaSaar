from uuid import uuid4
import json
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def fixture():
    db = main.SessionLocal(); s=uuid4().hex[:10]
    doctor=main.User(name='Workspace Doctor',email=f'ws-doc-{s}@x.local',password_hash=main.hash_password('doctor123'),role='doctor')
    other=main.User(name='Other Doctor',email=f'ws-other-{s}@x.local',password_hash=main.hash_password('doctor123'),role='doctor')
    patient=main.User(name='Workspace Patient',email=f'ws-pat-{s}@x.local',password_hash=main.hash_password('patient123'),role='patient')
    db.add_all([doctor,other,patient]); db.flush(); main.make_profile(db,patient,40,'Other','')
    db.add_all([main.DoctorProfile(user_id=doctor.id,specialty='General Medicine',department='General Medicine',active=1), main.DoctorProfile(user_id=other.id,specialty='General Medicine',department='General Medicine',active=1)])
    db.flush()
    e1=main.Encounter(patient_id=patient.id,doctor_id=doctor.id,department='General Medicine',visit_date='2026-09-04',token_number=910000+patient.id,priority='normal',status='waiting',reason='Current visit')
    e2=main.Encounter(patient_id=patient.id,doctor_id=other.id,department='General Medicine',visit_date='2026-09-03',token_number=920000+patient.id,priority='normal',status='completed',reason='Old visit')
    db.add_all([e1,e2]); db.flush()
    handoff_structured={
        'chief_complaint':'Cough',
        'clinical_evidence':[{'question_id':'chief_complaint','question':'What is the main problem?','text':'Cough for 3 days','skipped':False,'input_mode':'text'}],
        'language':'en-IN', 'care_type':'allopathy'
    }
    c1=main.Consultation(patient_id=patient.id,encounter_id=e1.id,title='Current AI History',summary='current',structured_data=json.dumps(handoff_structured))
    c2=main.Consultation(patient_id=patient.id,encounter_id=e2.id,title='Other Doctor History',summary='other',structured_data='{}')
    db.add_all([c1,c2]); db.commit(); ids=(doctor.id,other.id,patient.id,doctor.email,other.email,patient.email,e1.id,e2.id); db.close(); return ids


def cleanup(ids):
    did,oid,pid,*_=ids; db=main.SessionLocal()
    try:
        db.query(main.Consultation).filter(main.Consultation.patient_id==pid).delete(synchronize_session=False)
        db.query(main.Encounter).filter(main.Encounter.patient_id==pid).delete(synchronize_session=False)
        db.query(main.PatientProfile).filter(main.PatientProfile.user_id==pid).delete(synchronize_session=False)
        db.query(main.DoctorProfile).filter(main.DoctorProfile.user_id.in_([did,oid])).delete(synchronize_session=False)
        db.query(main.UserSession).filter(main.UserSession.user_id.in_([did,oid,pid])).delete(synchronize_session=False)
        db.query(main.User).filter(main.User.id.in_([did,oid,pid])).delete(synchronize_session=False); db.commit()
    finally: db.close()


def test_doctor_workspace_consumes_exact_assigned_encounter():
    client=TestClient(main.app); ids=fixture()
    try:
        did,oid,pid,de,oe,pe,e1,e2=ids; h=auth(client,de,'doctor123')
        patients=client.get('/api/patients',headers=h); assert patients.status_code==200
        p=next(x for x in patients.json()['patients'] if x['id']==pid); assert p['encounter_id']==e1
        ws=client.get(f'/api/doctor/patients/{pid}/workspace',headers=h,params={'encounter_id':e1})
        assert ws.status_code==200, ws.text
        data=ws.json(); assert data['encounter']['id']==e1
        assert [c['id'] for c in data['consultations']]
        assert {c['encounter_id'] for c in data['consultations']}=={e1}
        assert data['consultations'][0]['title']=='Current AI History'
    finally: cleanup(ids)


def test_doctor_cannot_open_same_patient_through_other_doctors_encounter():
    client=TestClient(main.app); ids=fixture()
    try:
        did,oid,pid,de,oe,pe,e1,e2=ids; h=auth(client,de,'doctor123')
        r=client.get(f'/api/doctor/patients/{pid}/workspace',headers=h,params={'encounter_id':e2})
        assert r.status_code==403, r.text
    finally: cleanup(ids)


def test_start_consultation_preserves_patient_handoff():
    client=TestClient(main.app); ids=fixture()
    try:
        did,oid,pid,de,oe,pe,e1,e2=ids; h=auth(client,de,'doctor123')
        assert client.post(f'/api/encounters/{e1}/status',headers=h,json={'status':'called'}).status_code==200
        before=client.get(f'/api/doctor/encounters/{e1}/workspace',headers=h)
        assert before.status_code==200, before.text
        assert before.json()['workspace']['interview'][0]['answer']=='Cough for 3 days'

        started=client.post(f'/api/doctor/encounters/{e1}/consultation',headers=h,json={'encounter_id':e1,'title':'Clinical consultation'})
        assert started.status_code==200, started.text

        after=client.get(f'/api/doctor/encounters/{e1}/workspace',headers=h)
        assert after.status_code==200, after.text
        workspace=after.json()['workspace']
        assert workspace['encounter']['status']=='in_consultation'
        assert workspace['interview'][0]['answer']=='Cough for 3 days'
        assert workspace['general_consultation']['title']=='Current AI History'
        assert workspace['clinical_summary']['headline']=='Cough'
        assert any(c['title']=='Clinical consultation' for c in workspace['consultations'])
    finally: cleanup(ids)


def test_start_consultation_is_idempotent_and_keeps_handoff_separate():
    client=TestClient(main.app); ids=fixture()
    try:
        did,oid,pid,de,oe,pe,e1,e2=ids; h=auth(client,de,'doctor123')
        assert client.post(f'/api/encounters/{e1}/status',headers=h,json={'status':'called'}).status_code==200
        first=client.post(f'/api/doctor/encounters/{e1}/consultation',headers=h,json={'encounter_id':e1,'title':'Clinical consultation'})
        assert first.status_code==200 and first.json()['created'] is True
        first_id=first.json()['consultation']['consultation_id']
        second=client.post(f'/api/doctor/encounters/{e1}/consultation',headers=h,json={'encounter_id':e1,'title':'Clinical consultation'})
        assert second.status_code==200 and second.json()['created'] is False
        assert second.json()['consultation']['consultation_id']==first_id
        db=main.SessionLocal()
        try:
            rows=db.query(main.Consultation).filter(main.Consultation.encounter_id==e1).all()
            assert len([c for c in rows if c.consultation_type=='clinician'])==1
            assert len([c for c in rows if c.consultation_type=='handoff'])==1
        finally: db.close()
        ws=client.get(f'/api/doctor/encounters/{e1}/workspace',headers=h).json()['workspace']
        assert ws['general_consultation']['consultation_type']=='handoff'
        clinical=[c for c in ws['consultations'] if c['consultation_type']=='clinician']
        assert len(clinical)==1
        assert ws['interview'][0]['answer']=='Cough for 3 days'
    finally: cleanup(ids)


def test_start_consultation_cannot_cross_patient_or_encounter():
    client=TestClient(main.app); ids=fixture()
    try:
        did,oid,pid,de,oe,pe,e1,e2=ids; h=auth(client,de,'doctor123')
        assert client.post(f'/api/encounters/{e1}/status',headers=h,json={'status':'called'}).status_code==200
        r=client.post(f'/api/doctor/encounters/{e2}/consultation',headers=h,json={'encounter_id':e2,'title':'Clinical consultation'})
        assert r.status_code==403
        db=main.SessionLocal()
        try:
            assert db.query(main.Consultation).filter(main.Consultation.encounter_id==e2, main.Consultation.consultation_type=='clinician').count()==0
        finally: db.close()
    finally: cleanup(ids)
