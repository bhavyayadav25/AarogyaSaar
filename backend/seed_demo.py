"""Reproducible AarogyaSaar SIH26047 demo reset/seed.

Usage:
    python seed_demo.py --reset

This operates on the existing SQLAlchemy models; it does not create a parallel
API or schema. It is intended for a presentation/demo environment only.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import main

DB_PATH = Path(main.BASE_DIR) / "sih26047.db"
DOC_SOURCE_DIR = Path(main.BASE_DIR) / "uploads"
DOC_TARGET_DIR = Path(main.BASE_DIR) / "data" / "documents"

DEMO_PASSWORD = "patient123"
DOCTOR_PASSWORD = "doctor123"
ADMIN_PASSWORD = "admin123"

PATIENTS = [
    {
        "name": "Priya Sharma", "email": "patient@sih26047.local", "age": 42,
        "gender": "Female", "phone": "+91 90000 00000", "language": "hi-IN",
        "complaint": "तीन दिनों से बुखार और शरीर में दर्द",
        "answers": {
            "chief_complaint": "तीन दिनों से बुखार और शरीर में दर्द",
            "onset": "तीन दिन पहले धीरे-धीरे शुरू हुआ",
            "location": "पूरे शरीर में दर्द, खासकर पीठ में",
            "severity": "मध्यम",
            "character": "भारी और दर्द जैसा",
            "associated": "ठंड लगना और कमजोरी",
            "medications": "अभी कोई दवा नहीं ले रही हूँ",
            "allergies": "कोई ज्ञात एलर्जी नहीं",
            "past_history": "कोई महत्वपूर्ण बीमारी नहीं",
            "family_history": "माता को उच्च रक्तचाप है",
        },
        "risk": "watch", "red_flags": [{"id": "fever-watch", "level": "watch", "label": "Fever requiring clinical review", "message": "Patient reports fever for three days; clinician should assess duration and associated symptoms."}],
        "document": "demo_1_CBC_Blood_Test_Report.pdf",
    },
    {
        "name": "Amit Verma", "email": "patient2@sih26047.local", "age": 35,
        "gender": "Male", "phone": "+91 90000 00001", "language": "bn-IN",
        "complaint": "দুই দিন ধরে কাশি ও গলা ব্যথা",
        "answers": {
            "chief_complaint": "দুই দিন ধরে কাশি ও গলা ব্যথা",
            "onset": "দুই দিন আগে হঠাৎ শুরু হয়েছে",
            "location": "গলা ও বুকের উপরের দিকে",
            "severity": "হালকা থেকে মাঝারি",
            "character": "শুষ্ক কাশি এবং জ্বালাভাব",
            "associated": "হালকা নাক দিয়ে পানি পড়া",
            "medications": "কোনও ওষুধ এখন নিচ্ছি না",
            "allergies": "কোনও পরিচিত অ্যালার্জি নেই",
            "past_history": "অ্যাজমা বা বড় কোনও অসুখের ইতিহাস নেই",
            "family_history": "বিশেষ কিছু নেই",
        },
        "risk": "none", "red_flags": [],
        "document": "demo_2_Chest_XRay_Report.pdf",
    },
    {
        "name": "Sneha Gupta", "email": "patient3@sih26047.local", "age": 29,
        "gender": "Female", "phone": "+91 90000 00002", "language": "en-IN",
        "complaint": "Headache since yesterday",
        "answers": {
            "chief_complaint": "Headache since yesterday",
            "onset": "Started yesterday gradually",
            "location": "Across the forehead",
            "severity": "Mild",
            "character": "Dull pressure",
            "associated": "Tiredness after a long workday",
            "medications": "No regular medicines",
            "allergies": "No known allergies",
            "past_history": "No significant medical history",
            "family_history": "No significant family history",
        },
        "risk": "none", "red_flags": [],
        "document": "demo_3_Previous_Consultation_Report.pdf",
    },
]


def reset_tables(db):
    # Delete in dependency order while keeping the existing schema intact.
    for model in [
        main.AuditEvent, main.UserSession, main.FHIRExportRecord,
        main.MedicalDocument, main.AyushAssessment, main.ConsentRecord,
        main.VoiceTurn, main.InterviewState, main.Consultation,
        main.Encounter, main.AccessibilityPreference, main.PatientProfile,
        main.DoctorAvailability, main.RoutingRule, main.OPDConfiguration,
        main.DoctorProfile, main.User, main.HospitalConfiguration,
        main.Department,
    ]:
        db.query(model).delete(synchronize_session=False)
    db.commit()
    # SQLite's sequence table is present for this schema. Reset it so the clean
    # demo keeps stable IDs (patient=1, doctor=2, admin=3).
    try:
        db.execute(main.sql_text("DELETE FROM sqlite_sequence"))
        db.commit()
    except Exception:
        db.rollback()


def add_document(db, patient_id: int, encounter_id: int, filename: str):
    source = DOC_SOURCE_DIR / filename
    if not source.exists():
        raise RuntimeError(f"Required demo document is missing: {source}")
    target_name = filename
    target = DOC_TARGET_DIR / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    text_map = {
        "demo_1_CBC_Blood_Test_Report.pdf": "Complete Blood Count (CBC)\nHemoglobin: 13.8 g/dL\nWhite blood cell count: 7.2 x10^9/L\nPlatelets: 245 x10^9/L",
        "demo_2_Chest_XRay_Report.pdf": "Chest X-Ray\nFindings: Lungs are clear in the provided demonstration image.\nImpression: No acute cardiopulmonary abnormality identified in this demo report.",
        "demo_3_Previous_Consultation_Report.pdf": "Previous Consultation Summary\nDepartment: General Medicine\nAssessment: Routine outpatient consultation record for demonstration.\nFollow-up: Review with the assigned clinician as advised.",
    }
    dtype = "Lab Report" if "CBC" in filename else "Imaging Report" if "XRay" in filename else "Discharge Summary"
    db.add(main.MedicalDocument(
        patient_id=patient_id, encounter_id=encounter_id, filename=target_name,
        document_type=dtype, mime_type="application/pdf", stored_path=target_name,
        extracted_text=text_map[filename], extracted_data="[]", classification=dtype,
        classification_confidence="1.0", classification_method="Demo document classifier",
        classification_evidence="[]", classification_needs_review=0,
        structured_extraction=json.dumps({"schema_version": "demo", "document_type": dtype, "items": [], "needs_review": False}),
        extraction_needs_review=0, extraction_method="Demo-safe stored document",
        verification_status="Verified", status="Processed",
    ))


def seed():
    db = main.SessionLocal()
    try:
        reset_tables(db)
        # Remove all stored demo/test document artifacts, then restore only the
        # three presentation-safe PDFs used below.
        DOC_TARGET_DIR.mkdir(parents=True, exist_ok=True)
        for path in DOC_TARGET_DIR.iterdir():
            if path.is_file():
                path.unlink()
        for path in DOC_SOURCE_DIR.iterdir():
            if path.is_file() and path.name not in {
                "demo_1_CBC_Blood_Test_Report.pdf",
                "demo_2_Chest_XRay_Report.pdf",
                "demo_3_Previous_Consultation_Report.pdf",
            }:
                path.unlink()
        hospital = main.HospitalConfiguration(hospital_name="AarogyaSaar District Hospital", facility_code="AS-DH-26047", timezone="Asia/Kolkata", default_department="General Medicine", active=1)
        db.add(hospital)
        department = main.Department(name="General Medicine", specialty="General Medicine", active=1)
        db.add(department)
        db.add(main.OPDConfiguration(department="General Medicine", working_days="Mon,Tue,Wed,Thu,Fri", start_time="09:00", end_time="17:00", active=1))

        # Keep stable demo IDs: patient=1, doctor=2, admin=3.
        first_patient = main.User(name=PATIENTS[0]["name"], email=PATIENTS[0]["email"], password_hash=main.hash_password(DEMO_PASSWORD), role="patient")
        db.add(first_patient); db.flush()
        db.add(main.PatientProfile(user_id=first_patient.id, age=PATIENTS[0]["age"], gender=PATIENTS[0]["gender"], phone=PATIENTS[0]["phone"], blood_group="", allergies="", conditions="", medications="", address=""))
        doctor = main.User(name="Dr. Ananya Verma", email=main.DEMO_DOCTOR_EMAIL, password_hash=main.hash_password(DOCTOR_PASSWORD), role="doctor")
        admin = main.User(name="Neha Kapoor", email=main.DEMO_ADMIN_EMAIL, password_hash=main.hash_password(ADMIN_PASSWORD), role="admin")
        db.add_all([doctor, admin]); db.flush()
        db.add(main.DoctorProfile(user_id=doctor.id, specialty="General Medicine", department="General Medicine", registration_number="UP-MED-20481", room_number="Room 12", active=1))

        today = date.today().isoformat()
        # The first patient was inserted above so the demo identifiers remain stable.
        # Amit Verma remains the existing Bangla-language demo account so the patient
        # can exercise the Bangla onboarding/interview flow, but his old pre-seeded
        # clinical handoff is intentionally not included in the clean demo queue.
        # This removes the distracting Amit summary without inventing a replacement
        # patient or changing the production workflow.
        for idx, item in enumerate(PATIENTS, start=1):
            patient = first_patient if idx == 1 else main.User(name=item["name"], email=item["email"], password_hash=main.hash_password(DEMO_PASSWORD), role="patient")
            if idx != 1:
                db.add(patient); db.flush()
            if idx != 1:
                db.add(main.PatientProfile(user_id=patient.id, age=item["age"], gender=item["gender"], phone=item["phone"], blood_group="", allergies="", conditions="", medications="", address=""))
            db.add(main.AccessibilityPreference(patient_id=patient.id, language=item["language"], input_mode="touch", font_scale="1.0", high_contrast=0, reduced_motion=0, captions=1, audio_enabled=1, audio_speed="1.0", assisted_mode=0))
            db.add(main.ConsentRecord(patient_id=patient.id, consent_type="Clinical case-taking", version="5B.1", language=item["language"], granted=1, audio_explained=1, scope="AI-assisted case taking, document processing, AYUSH intake, physician review"))
            if item["email"] == "patient2@sih26047.local":
                continue
            encounter = main.Encounter(patient_id=patient.id, doctor_id=doctor.id, department="General Medicine", language=item["language"], visit_date=today, token_number=idx, priority=item["risk"] if item["risk"] in {"urgent", "emergency"} else "normal", status="completed" if idx == 1 else "waiting", reason=item["complaint"], care_type="allopathy", triage_status="unreviewed", completed_at=main.utc_now() if idx == 1 else None)
            db.add(encounter); db.flush()
            session_id = f"demo-{item['email'].split('@')[0]}-{idx}"
            structured = dict(item["answers"])
            structured.update({"language": item["language"], "care_type": "allopathy", "encounter_id": encounter.id})
            evidence = []
            for qid, answer in item["answers"].items():
                evidence.append({"question_id": qid, "question": qid.replace("_", " ").title(), "text": answer, "skipped": False, "input_mode": "text"})
            structured["clinical_evidence"] = evidence
            state = main.InterviewState(patient_id=patient.id, encounter_id=encounter.id, session_id=session_id, language=item["language"], pathway="general", current_question_id=None, status="completed", structured_data=json.dumps(structured, ensure_ascii=False), answered_question_ids=json.dumps(list(item["answers"].keys())), conversation=json.dumps(evidence, ensure_ascii=False), risk_level=item["risk"], red_flags=json.dumps(item["red_flags"], ensure_ascii=False), version="AI-2.1")
            db.add(state); db.flush()
            summary = " | ".join(f"{k.replace('_',' ').title()}: {v}" for k, v in item["answers"].items())
            nlp = main.analyze_nlp_text(" ".join(item["answers"].values()), item["language"])
            physician_summary = main.generate_physician_summary(structured, item["risk"], item["red_flags"], nlp, patient=patient, encounter=encounter, documents=[])
            consultation = main.Consultation(patient_id=patient.id, encounter_id=encounter.id, title=item["complaint"][:80], summary=summary, status="Health history — summary ready", risk_level=item["risk"], red_flags=json.dumps(item["red_flags"], ensure_ascii=False), doctor_review="Pending", structured_data=json.dumps(structured, ensure_ascii=False), nlp_data=json.dumps(nlp, ensure_ascii=False), ai_summary=json.dumps(physician_summary, ensure_ascii=False), ai_summary_generated_at=main.utc_now(), consultation_status="draft")
            db.add(consultation)
            db.flush()
            add_document(db, patient.id, encounter.id, item["document"])
        db.commit()
        print("AarogyaSaar demo database reset and seeded successfully.")
        print("Accounts: patient@sih26047.local / patient123; patient2@sih26047.local / patient123; patient3@sih26047.local / patient123; doctor@sih26047.local / doctor123; admin@sih26047.local / admin123")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Reset and seed the demo database")
    args = parser.parse_args()
    if not args.reset:
        parser.error("Demo data is destructive; pass --reset explicitly.")
    if main.IS_PRODUCTION:
        raise SystemExit("Refusing to reset demo data in production.")
    seed()
