"""Validate AarogyaSaar patient -> encounter -> handoff relationships."""
from __future__ import annotations
import json
import sys
import main


def validate():
    db = main.SessionLocal(); errors=[]; checks=[]
    try:
        def check(name, condition, detail):
            checks.append((name, bool(condition), detail))
            if not condition: errors.append(f"{name}: {detail}")
        patients=db.query(main.User).filter(main.User.role=='patient').all()
        doctors=db.query(main.User).filter(main.User.role=='doctor').all()
        check('one hospital', db.query(main.HospitalConfiguration).count()==1, f"count={db.query(main.HospitalConfiguration).count()}")
        check('demo patients', len(patients)>=2, f"count={len(patients)}")
        check('active doctor', any(d.doctor_profile and d.doctor_profile.active for d in doctors), f"doctors={len(doctors)}")
        for e in db.query(main.Encounter).all():
            p=db.query(main.User).filter(main.User.id==e.patient_id, main.User.role=='patient').first()
            d=db.query(main.User).filter(main.User.id==e.doctor_id, main.User.role=='doctor').first() if e.doctor_id else None
            check(f'encounter {e.id} patient', p is not None, f'patient_id={e.patient_id}')
            check(f'encounter {e.id} doctor', d is not None, f'doctor_id={e.doctor_id}')
            check(f'encounter {e.id} language', e.language in main.SUPPORTED_LANGUAGES, f'language={e.language}')
            states=db.query(main.InterviewState).filter(main.InterviewState.encounter_id==e.id).all()
            check(f'encounter {e.id} interview state', len(states)==1, f'count={len(states)}')
            for st in states:
                check(f'interview {st.id} patient match', st.patient_id==e.patient_id, f'{st.patient_id}!={e.patient_id}')
                check(f'interview {st.id} language match', st.language==e.language, f'{st.language}!={e.language}')
                try: data=json.loads(st.structured_data or '{}')
                except Exception: data={}
                check(f'interview {st.id} has evidence', bool(data.get('clinical_evidence')), f"evidence_count={len(data.get('clinical_evidence') or [])}")
            consultations=db.query(main.Consultation).filter(main.Consultation.encounter_id==e.id).all()
            check(f'encounter {e.id} consultation', len(consultations)>=1, f'count={len(consultations)}')
            for c in consultations:
                check(f'consultation {c.id} patient match', c.patient_id==e.patient_id, f'{c.patient_id}!={e.patient_id}')
            docs=db.query(main.MedicalDocument).filter(main.MedicalDocument.encounter_id==e.id).all()
            check(f'encounter {e.id} docs', len(docs)>=1, f'count={len(docs)}')
            for doc in docs:
                check(f'document {doc.id} patient match', doc.patient_id==e.patient_id, f'{doc.patient_id}!={e.patient_id}')
        # Generic orphan checks requested by Task 3.
        checks_sql = [
            ('orphan encounters', 'SELECT COUNT(*) FROM encounters e LEFT JOIN users u ON u.id=e.patient_id WHERE u.id IS NULL'),
            ('orphan documents', 'SELECT COUNT(*) FROM medical_documents d LEFT JOIN encounters e ON e.id=d.encounter_id WHERE d.encounter_id IS NOT NULL AND e.id IS NULL'),
            ('document patient mismatch', 'SELECT COUNT(*) FROM medical_documents d JOIN encounters e ON e.id=d.encounter_id WHERE d.patient_id<>e.patient_id'),
            ('orphan consultations', 'SELECT COUNT(*) FROM consultations c LEFT JOIN encounters e ON e.id=c.encounter_id WHERE c.encounter_id IS NOT NULL AND e.id IS NULL'),
            ('consultation patient mismatch', 'SELECT COUNT(*) FROM consultations c JOIN encounters e ON e.id=c.encounter_id WHERE c.patient_id<>e.patient_id'),
            ('orphan interview encounters', 'SELECT COUNT(*) FROM interview_states s LEFT JOIN encounters e ON e.id=s.encounter_id WHERE s.encounter_id IS NOT NULL AND e.id IS NULL'),
            ('interview patient mismatch', 'SELECT COUNT(*) FROM interview_states s JOIN encounters e ON e.id=s.encounter_id WHERE s.patient_id<>e.patient_id'),
            ('orphan assignment doctors', "SELECT COUNT(*) FROM encounters e LEFT JOIN users u ON u.id=e.doctor_id WHERE e.doctor_id IS NOT NULL AND (u.id IS NULL OR u.role<>'doctor')"),
        ]
        for name,sql in checks_sql:
            n=db.execute(main.sql_text(sql)).scalar_one(); check(name,n==0,f'count={n}')
        return checks, errors
    finally: db.close()

if __name__=='__main__':
    checks,errors=validate()
    for n,ok,d in checks: print(('PASS' if ok else 'FAIL'), n, '-', d)
    sys.exit(1 if errors else 0)
