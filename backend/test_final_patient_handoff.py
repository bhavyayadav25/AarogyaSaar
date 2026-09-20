import sys
from pathlib import Path
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi.testclient import TestClient
import main


def auth(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def test_final_patient_handoff_reaches_assigned_doctor():
    client = TestClient(main.app)
    email = f'final-handoff-{uuid.uuid4().hex[:10]}@example.local'
    password = 'patient123'
    r = client.post('/api/auth/register', json={
        'name': 'Final Handoff Patient', 'email': email, 'password': password,
        'age': 42, 'gender': 'Male', 'phone': '9876543210',
    })
    assert r.status_code == 200, r.text
    patient = {'Authorization': 'Bearer ' + r.json()['access_token']}
    patient_id = r.json()['user']['id']

    departments = client.get('/api/departments', headers=patient)
    assert departments.status_code == 200
    names = [x['name'] for x in departments.json()['departments']]
    assert names == ['General Medicine', 'Cardiology', 'Orthopedics', 'Pediatrics', 'Gynecology']
    assert not any('AI5F' in x or 'Phase' in x for x in names)

    encounter = client.post('/api/encounters', headers=patient, json={
        'patient_id': patient_id, 'department': 'General Medicine',
        'priority': 'normal', 'reason': 'Chest discomfort', 'care_type': 'allopathy',
    })
    assert encounter.status_code == 200, encounter.text
    encounter_data = encounter.json()['encounter']
    encounter_id = encounter_data['id']
    assert encounter_data['doctor_id'] is not None

    consent = client.post(f'/api/patients/{patient_id}/consent', headers=patient, json={
        'patient_id': patient_id, 'language': 'en-IN', 'audio_explained': True, 'granted': True,
    })
    assert consent.status_code == 200, consent.text

    session_id = f'final-{uuid.uuid4().hex}'
    r = client.get('/api/interview/questions', headers=patient, params={
        'patient_id': patient_id, 'language': 'en-IN', 'session_id': session_id,
    })
    assert r.status_code == 200, r.text
    question = r.json()['question']
    completed = False
    for _ in range(100):
        assert question is not None
        r = client.post('/api/interview/answer', headers=patient, json={
            'patient_id': patient_id, 'session_id': session_id,
            'question_id': question['id'], 'answer': 'No additional information',
            'skipped': False, 'answers': {}, 'language': 'en-IN', 'input_mode': 'text',
        })
        assert r.status_code == 200, r.text
        data = r.json()
        if data['completed']:
            completed = True
            assert data['consultation_id'] is not None
            assert data['ai_summary']
            break
        question = data['next_question']
    assert completed

    encounter = client.get(f'/api/encounters/{encounter_id}', headers=patient)
    assert encounter.status_code == 200, encounter.text
    assert encounter.json()['encounter']['doctor_id'] == encounter_data['doctor_id']

    doctor = auth(client, 'doctor@sih26047.local', 'doctor123')
    queue = client.get('/api/queue', headers=doctor, params={'status': 'waiting,called,in_consultation'})
    assert queue.status_code == 200, queue.text
    assert any(x['id'] == encounter_id for x in queue.json()['queue'])

    workspace = client.get(f'/api/doctor/encounters/{encounter_id}/workspace', headers=doctor)
    assert workspace.status_code == 200, workspace.text
    ws = workspace.json()['workspace']
    assert ws['encounter']['id'] == encounter_id
    assert ws['general_consultation'] is not None
    assert ws['interview']
