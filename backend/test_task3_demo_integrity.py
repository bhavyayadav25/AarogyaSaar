import pytest
from seed_demo import seed as reset_and_seed
import json
import main
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_demo():
    reset_and_seed()


def auth(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password}); assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}


def test_seeded_demo_relationships_and_languages():
    db=main.SessionLocal()
    try:
        patients=db.query(main.User).filter(main.User.role=='patient').all()
        assert {p.email for p in patients} >= {'patient@sih26047.local','patient2@sih26047.local','patient3@sih26047.local'}
        expected={'patient@sih26047.local':'hi-IN','patient2@sih26047.local':'bn-IN','patient3@sih26047.local':'en-IN'}
        for p in patients:
            if p.email not in expected: continue
            e=db.query(main.Encounter).filter(main.Encounter.patient_id==p.id).first()
            if p.email=='patient2@sih26047.local':
                assert e is None
                continue
            assert e is not None
            assert e.language==expected[p.email]
            doctor=db.query(main.User).filter(main.User.email=='doctor@sih26047.local').one()
            assert e.doctor_id==doctor.id
            state=db.query(main.InterviewState).filter(main.InterviewState.encounter_id==e.id).one()
            assert state.patient_id==p.id and state.language==e.language
            c=db.query(main.Consultation).filter(main.Consultation.encounter_id==e.id).one()
            assert c.patient_id==p.id
            doc=db.query(main.MedicalDocument).filter(main.MedicalDocument.encounter_id==e.id).one()
            assert doc.patient_id==p.id
            structured=json.loads(c.structured_data)
            assert structured['encounter_id']==e.id
    finally: db.close()


def test_doctor_queue_and_workspace_are_encounter_scoped():
    client=TestClient(main.app); h=auth(client,'doctor@sih26047.local','doctor123')
    q=client.get('/api/queue',headers=h); assert q.status_code==200,q.text
    rows=q.json()['queue']; assert len(rows)==1
    ids={r['id'] for r in rows}; assert ids=={2}
    for row in rows:
        ws=client.get(f"/api/doctor/encounters/{row['id']}/workspace",headers=h)
        assert ws.status_code==200,ws.text
        w=ws.json()['workspace']
        assert w['patient']['id']==row['patient_id']
        assert w['encounter']['id']==row['id']
        assert w['encounter']['doctor_id']==row['doctor_id']
        assert all(d['id'] for d in w['documents'])
        assert all(c['id'] for c in w['consultations'])
        assert all(item['answer'] for item in w['interview'])
        assert w['encounter']['language'] in main.SUPPORTED_LANGUAGES


def test_doctor_patient_isolation_between_seeded_patients():
    client=TestClient(main.app); h=auth(client,'doctor@sih26047.local','doctor123')
    db=main.SessionLocal()
    try:
        ps=db.query(main.User).filter(main.User.role=='patient').order_by(main.User.id).all()
        with_encounters=[p for p in ps if db.query(main.Encounter).filter(main.Encounter.patient_id==p.id).first()]
        a,b=with_encounters[0],with_encounters[1]
        ea=db.query(main.Encounter).filter(main.Encounter.patient_id==a.id).one()
        eb=db.query(main.Encounter).filter(main.Encounter.patient_id==b.id).one()
    finally: db.close()
    wa=client.get(f'/api/doctor/patients/{a.id}/workspace',headers=h,params={'encounter_id':ea.id}).json()
    wb=client.get(f'/api/doctor/patients/{b.id}/workspace',headers=h,params={'encounter_id':eb.id}).json()
    assert wa['patient']['id']==a.id and wa['encounter']['id']==ea.id
    assert wb['patient']['id']==b.id and wb['encounter']['id']==eb.id
    assert {c['patient_id'] if 'patient_id' in c else None for c in wa['consultations']} == {None}
    assert all(c['encounter_id']==ea.id for c in wa['consultations'])
    assert all(c['encounter_id']==eb.id for c in wb['consultations'])
    assert all(d['encounter_id']==ea.id for d in wa['documents'])
    assert all(d['encounter_id']==eb.id for d in wb['documents'])


def test_multilingual_handoff_preserves_original_answers_and_has_english_summary():
    client=TestClient(main.app); h=auth(client,'doctor@sih26047.local','doctor123')
    expected={
        1: ('hi-IN','तीन दिनों से बुखार और शरीर में दर्द','Fever and generalized body ache for 3 days.'),
        2: ('en-IN','Headache since yesterday','Headache since yesterday'),
    }
    for encounter_id,(language,original,english_phrase) in expected.items():
        data=client.get(f'/api/doctor/encounters/{encounter_id}/workspace',headers=h).json()['workspace']
        assert data['encounter']['language']==language
        assert data['general_consultation']['structured']['language']==language
        assert original in [x['answer'] for x in data['interview']]
        ai=data['general_consultation']['ai_summary']
        assert ai['patient_overview']['language']==language
        assert isinstance(ai['clinical_summary'],str) and ai['clinical_summary']
        assert english_phrase.split()[0].lower() in ai['headline'].lower()

    # Bangla remains an actual supported patient language, but no old Amit handoff
    # is seeded into the clean doctor queue.
    bangla=client.post('/api/auth/login',json={'email':'patient2@sih26047.local','password':'patient123'})
    assert bangla.status_code==200
    patient_headers={'Authorization':'Bearer '+bangla.json()['access_token']}
    questions=client.get('/api/interview/questions',headers=patient_headers,params={'patient_id':4,'language':'bn-IN','session_id':'bangla-regression'})
    assert questions.status_code==200
    assert questions.json()['language']=='bn-IN'
    assert questions.json()['question']['text'] != main.COMMON_QUESTIONS[0]['text']


def test_clean_demo_keeps_bangla_patient_account_without_preseeded_amit_handoff():
    client=TestClient(main.app)
    headers=auth(client,'patient2@sih26047.local','patient123')
    active=client.get('/api/patients/4/active-encounter',headers=headers)
    assert active.status_code==200 and active.json()['encounter'] is None
    consultations=client.get('/api/patients/4/consultations',headers=headers)
    assert consultations.status_code==200 and consultations.json()['consultations']==[]
    docs=client.get('/api/patients/4/documents',headers=headers)
    assert docs.status_code==200 and docs.json()['documents']==[]
