from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import hashlib
import asyncio
import hmac
import time
import re
import json
import os
import uuid
import secrets
import tempfile
import stat
import subprocess
from typing import Optional, List, Dict, Any
from fastapi import Request
from sqlalchemy.exc import IntegrityError

from clinical_nlu import extract_clinical_entities, canonicalize_clinical_text
from ai_confidence_semantics import confidence_semantics
from conversation_repair import analyze_repair, localized_response
from adaptive_interview_orchestrator import build_turn_response
from clinical_safety_triage import evaluate_safety, PRIORITY as SAFETY_PRIORITY
from medical_document_intake.integration import register_medical_document_intake
from medical_document_classifier import classify_document
from structured_medical_extractor import extract_structured_medical_data
from document_verification import build_verification_summary, apply_document_verification
from clinical_timeline import build_timeline
from clinical_provenance_explainability import explain_document, explain_timeline
from clinical_handoff import build_clinical_handoff
from clinical_summary import build_clinical_summary
from clinical_risk_assessment import build_risk_assessment
from clinical_decision_support import build_decision_support
from medication_reconciliation import build_medication_intelligence
from investigation_intelligence import build_investigation_intelligence
from clinical_question_assistant import answer_clinical_question
from consultation_copilot import build_consultation_copilot
from final_clinical_safety_gate import build_final_clinical_gate
from integration_audit import build_integration_audit
from encounter_queue_workflow import (normalize_department, normalize_priority, normalize_status, can_transition, queue_sort_key, serialize_encounter, ROLE_CAN_MANAGE_QUEUE)
from doctor_workspace import build_doctor_workspace
from consultation_workflow import build_consultation_payload, normalize_sections, consultation_summary
from clinical_triage_workflow import (TRIAGE_ROLES, normalize_triage_action, triage_action_status, serialize_triage_item, build_triage_dashboard)
from hospital_analytics import build_analytics_dashboard

# Phase AI-1D: optional local speech stack. The server remains usable when these
# packages/models are not installed; voice endpoints return a clear setup error.
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except Exception:
    WhisperModel = None
    FASTER_WHISPER_AVAILABLE = False

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except Exception:
    edge_tts = None
    EDGE_TTS_AVAILABLE = False

# Phase 5C: lightweight local NLP/ML layer (no external model/API required)
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False

from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, inspect, text as sql_text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
APP_ENV = os.getenv("SIH_ENV", "demo").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}
DEMO_MODE = os.getenv("SIH_DEMO_MODE", "1" if APP_ENV in {"demo", "development", "dev", "test"} else "0").strip().lower() in {"1", "true", "yes", "on"}

_DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'sih26047.db'}"
DATABASE_URL = os.getenv("SIH_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
if not DATABASE_URL:
    raise RuntimeError("SIH_DATABASE_URL cannot be empty.")

UPLOAD_DIR = Path(os.getenv("SIH_UPLOAD_DIR", str(BASE_DIR / "uploads"))).expanduser().resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Clinical files should not be world-readable when the filesystem permits it.
try:
    UPLOAD_DIR.chmod(0o700)
except OSError:
    pass

VOICE_TMP_DIR = UPLOAD_DIR / "voice_tmp"
VOICE_TMP_DIR.mkdir(parents=True, exist_ok=True)
try:
    VOICE_TMP_DIR.chmod(0o700)
except OSError:
    pass

MAX_DOCUMENT_UPLOAD_BYTES = int(os.getenv("SIH_MAX_DOCUMENT_UPLOAD_MB", "10")) * 1024 * 1024
MAX_VOICE_UPLOAD_BYTES = int(os.getenv("SIH_MAX_VOICE_UPLOAD_MB", "25")) * 1024 * 1024

# FIX 7 — abuse/resource protection for expensive AI and voice operations.
AI_RATE_WINDOW_SECONDS = int(os.getenv("SIH_AI_RATE_WINDOW_SECONDS", "60"))
AI_RATE_MAX_REQUESTS = int(os.getenv("SIH_AI_RATE_MAX_REQUESTS", "30"))
VOICE_TRANSCRIBE_RATE_MAX = int(os.getenv("SIH_VOICE_TRANSCRIBE_RATE_MAX", "5"))
VOICE_TTS_RATE_MAX = int(os.getenv("SIH_VOICE_TTS_RATE_MAX", "20"))
DOCUMENT_AI_RATE_MAX = int(os.getenv("SIH_DOCUMENT_AI_RATE_MAX", "15"))
MAX_CONCURRENT_TRANSCRIPTIONS = max(1, int(os.getenv("SIH_MAX_CONCURRENT_TRANSCRIPTIONS", "1")))
MAX_CONCURRENT_TTS = max(1, int(os.getenv("SIH_MAX_CONCURRENT_TTS", "4")))
_ai_rate_failures: dict[str, list[float]] = {}
_ai_rate_lock = __import__("threading").Lock()
_transcription_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRANSCRIPTIONS)
_tts_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TTS)
WHISPER_MODEL_SIZE = os.getenv("MEDIKIOSK_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("MEDIKIOSK_WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.getenv("MEDIKIOSK_WHISPER_COMPUTE_TYPE", "int8")
# Every UI-supported Indian language has an explicit server TTS voice.
# Keeping this mapping complete prevents an accidental fallback to English.
TTS_VOICE_MAP = {
    "en-IN": os.getenv("MEDIKIOSK_TTS_EN_IN", "en-IN-NeerjaNeural"),
    "hi-IN": os.getenv("MEDIKIOSK_TTS_HI_IN", "hi-IN-SwaraNeural"),
    "bn-IN": os.getenv("MEDIKIOSK_TTS_BN_IN", "bn-IN-TanishaaNeural"),
}
WHISPER_LANGUAGE_CODES = {"en-IN": "en", "hi-IN": "hi", "bn-IN": "bn"}
_whisper_model = None

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def utc_now() -> datetime:
    """Return current UTC as a naive datetime for the existing DB schema.

    The database columns currently use timezone-naive SQLAlchemy DateTime and
    historically stored UTC values. We obtain the timestamp from the explicit
    UTC-aware clock, then remove tzinfo at the persistence boundary so existing
    records and comparisons remain compatible.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    profile = relationship("PatientProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    doctor_profile = relationship("DoctorProfile", back_populates="user", uselist=False, cascade="all, delete-orphan", foreign_keys="DoctorProfile.user_id")
    consultations = relationship("Consultation", back_populates="patient", cascade="all, delete-orphan")


class PatientProfile(Base):
    __tablename__ = "patient_profiles"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    blood_group = Column(String, nullable=True)
    allergies = Column(Text, nullable=True)
    conditions = Column(Text, nullable=True)
    medications = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    user = relationship("User", back_populates="profile")


class MedicalDocument(Base):
    __tablename__ = "medical_documents"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=True, index=True)
    filename = Column(String, nullable=False)
    document_type = Column(String, nullable=False, default="Other")
    mime_type = Column(String, nullable=True)
    stored_path = Column(String, nullable=True)
    extracted_text = Column(Text, nullable=True)
    extracted_data = Column(Text, nullable=True)
    classification = Column(String, nullable=True)
    classification_confidence = Column(String, nullable=True)
    classification_method = Column(String, nullable=True)
    classification_evidence = Column(Text, nullable=True)
    classification_needs_review = Column(Integer, default=0)
    structured_extraction = Column(Text, nullable=True)
    extraction_needs_review = Column(Integer, default=1)
    extraction_method = Column(String, nullable=True)
    verification_status = Column(String, default="Pending")
    verified_data = Column(Text, nullable=True)
    verification_notes = Column(Text, nullable=True)
    verified_by = Column(Integer, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    status = Column(String, default="Processed")
    created_at = Column(DateTime, default=utc_now)


class AyushAssessment(Base):
    __tablename__ = "ayush_assessments"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    system = Column(String, default="Ayurveda")
    assessment_type = Column(String, default="Dashavidha Pariksha")
    responses = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    status = Column(String, default="Completed")
    created_at = Column(DateTime, default=utc_now)


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    consent_type = Column(String, nullable=False, default="Clinical case-taking")
    version = Column(String, nullable=False, default="5B.1")
    language = Column(String, nullable=False, default="en-IN")
    granted = Column(Integer, default=0)
    audio_explained = Column(Integer, default=0)
    scope = Column(Text, nullable=False, default="AI-assisted case taking, document processing, AYUSH intake, physician review")
    created_at = Column(DateTime, default=utc_now)
    revoked_at = Column(DateTime, nullable=True)


class FHIRExportRecord(Base):
    __tablename__ = "fhir_export_records"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    exported_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resource_type = Column(String, nullable=False, default="Bundle")
    bundle_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=utc_now)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    last_seen_at = Column(DateTime, default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    role = Column(String, nullable=True)
    action = Column(String, nullable=False)
    resource = Column(String, nullable=True)
    request_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class InterviewState(Base):
    """Persistent state for one AI clinical-intake encounter.

    AI-1A makes the conversation state server-owned instead of trusting the
    browser to resend the complete history on every answer. This is an
    encounter/session memory layer, not a diagnostic model.
    """
    __tablename__ = "interview_states"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=True, index=True)
    session_id = Column(String, unique=True, nullable=False, index=True)
    language = Column(String, nullable=False, default="en-IN")
    pathway = Column(String, nullable=True)
    current_question_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    structured_data = Column(Text, nullable=False, default="{}")
    answered_question_ids = Column(Text, nullable=False, default="[]")
    conversation = Column(Text, nullable=False, default="[]")
    risk_level = Column(String, nullable=False, default="none")
    red_flags = Column(Text, nullable=False, default="[]")
    version = Column(String, nullable=False, default="AI-2.1")
    repair_count = Column(Integer, nullable=False, default=0)
    voice_failure_count = Column(Integer, nullable=False, default=0)
    last_input_mode = Column(String, nullable=True, default="text")
    last_repair_action = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now)


class VoiceTurn(Base):
    """Metadata for one voice interaction. Raw patient audio is not persisted by default."""
    __tablename__ = "voice_turns"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    language = Column(String, nullable=False, default="en-IN")
    direction = Column(String, nullable=False, default="input")
    transcript = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="completed")
    provider = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class AccessibilityPreference(Base):
    """Per-patient kiosk accessibility preferences. No clinical data is stored here."""
    __tablename__ = "accessibility_preferences"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    language = Column(String, nullable=False, default="en-IN")
    input_mode = Column(String, nullable=False, default="touch")
    font_scale = Column(String, nullable=False, default="1.0")
    high_contrast = Column(Integer, nullable=False, default=0)
    reduced_motion = Column(Integer, nullable=False, default=0)
    captions = Column(Integer, nullable=False, default=1)
    audio_enabled = Column(Integer, nullable=False, default=1)
    audio_speed = Column(String, nullable=False, default="1.0")
    assisted_mode = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=utc_now)


class Encounter(Base):
    """One hospital visit/OPD episode. Queue state is operational, not clinical."""
    __tablename__ = "encounters"
    __table_args__ = (UniqueConstraint("visit_date", "department", "token_number", name="uq_encounter_daily_department_token"),)
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    department = Column(String, nullable=False, default="General Medicine", index=True)
    language = Column(String, nullable=False, default="en-IN", index=True)
    visit_date = Column(String, nullable=False, index=True)
    token_number = Column(Integer, nullable=False)
    priority = Column(String, nullable=False, default="normal", index=True)
    status = Column(String, nullable=False, default="waiting", index=True)
    reason = Column(String, nullable=True)
    care_type = Column(String, nullable=False, default="allopathy", index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    called_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    triage_status = Column(String, nullable=False, default="unreviewed", index=True)
    triage_notes = Column(Text, nullable=True)
    triage_updated_by = Column(Integer, nullable=True)
    triage_updated_at = Column(DateTime, nullable=True)


class Consultation(Base):
    __tablename__ = "consultations"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    status = Column(String, default="Completed")
    risk_level = Column(String, default="none")
    red_flags = Column(Text, nullable=True)
    doctor_review = Column(String, default="Pending")
    doctor_notes = Column(Text, nullable=True)
    structured_data = Column(Text, nullable=True)
    nlp_data = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_summary_generated_at = Column(DateTime, nullable=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=True, index=True)
    consultation_status = Column(String, default="draft", index=True)
    consultation_type = Column(String, nullable=False, default="handoff", index=True)
    updated_at = Column(DateTime, default=utc_now)
    created_at = Column(DateTime, default=utc_now)
    patient = relationship("User", back_populates="consultations")


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    specialty = Column(String, nullable=False, default="General Medicine")
    active = Column(Integer, nullable=False, default=1, index=True)
    created_at = Column(DateTime, default=utc_now)


class DoctorProfile(Base):
    __tablename__ = "doctor_profiles"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    specialty = Column(String, nullable=False, default="General Medicine")
    department = Column(String, nullable=False, default="General Medicine", index=True)
    registration_number = Column(String, nullable=True)
    room_number = Column(String, nullable=True, default="Not assigned")
    active = Column(Integer, nullable=False, default=1, index=True)
    created_at = Column(DateTime, default=utc_now)
    user = relationship("User", back_populates="doctor_profile", foreign_keys=[user_id])


class OPDConfiguration(Base):
    __tablename__ = "opd_configurations"
    id = Column(Integer, primary_key=True, index=True)
    department = Column(String, nullable=False, unique=True, index=True)
    working_days = Column(String, nullable=False, default="Mon,Tue,Wed,Thu,Fri")
    start_time = Column(String, nullable=False, default="09:00")
    end_time = Column(String, nullable=False, default="17:00")
    active = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=utc_now)


class DoctorAvailability(Base):
    __tablename__ = "doctor_availability"
    __table_args__ = (UniqueConstraint("doctor_id", "day_of_week", "start_time", "end_time", name="uq_doctor_availability_window"),)
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    day_of_week = Column(String, nullable=False)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    active = Column(Integer, nullable=False, default=1, index=True)
    created_at = Column(DateTime, default=utc_now)


class RoutingRule(Base):
    __tablename__ = "routing_rules"
    id = Column(Integer, primary_key=True, index=True)
    department = Column(String, nullable=False, index=True)
    specialty = Column(String, nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    priority = Column(Integer, nullable=False, default=100)
    active = Column(Integer, nullable=False, default=1, index=True)
    created_at = Column(DateTime, default=utc_now)


class HospitalConfiguration(Base):
    __tablename__ = "hospital_configuration"
    id = Column(Integer, primary_key=True, index=True)
    hospital_name = Column(String, nullable=False, default="AarogyaSaar District Hospital")
    facility_code = Column(String, nullable=False, default="AS-DH-26047")
    timezone = Column(String, nullable=False, default="Asia/Kolkata")
    default_department = Column(String, nullable=False, default="General Medicine")
    active = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=utc_now)


Base.metadata.create_all(bind=engine)

# Lightweight schema migration so Phase 4B works with the existing Phase 3 SQLite DB.
def ensure_task3_relationship_columns():
    """Add explicit encounter ownership to the patient interview handoff.

    The original prototype keyed interview state only by patient/session and
    persisted encounter language inside the consultation payload. Task 3 needs
    the handoff boundary to be explicit and queryable without changing the
    existing clinical workflow.
    """
    with engine.begin() as conn:
        encounter_columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(encounters)"))}
        if "language" not in encounter_columns:
            conn.execute(sql_text("ALTER TABLE encounters ADD COLUMN language VARCHAR DEFAULT 'en-IN'"))
        interview_columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(interview_states)"))}
        if "encounter_id" not in interview_columns:
            conn.execute(sql_text("ALTER TABLE interview_states ADD COLUMN encounter_id INTEGER"))

ensure_task3_relationship_columns()

def ensure_phase4b_columns():
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(consultations)"))}
        if "risk_level" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN risk_level VARCHAR DEFAULT 'none'"))
        if "red_flags" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN red_flags TEXT"))
        if "doctor_review" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN doctor_review VARCHAR DEFAULT 'Pending'"))
        if "doctor_notes" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN doctor_notes TEXT"))
        if "consultation_type" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN consultation_type VARCHAR DEFAULT 'handoff'"))
            conn.execute(sql_text("UPDATE consultations SET consultation_type = 'clinician' WHERE title = 'Clinical consultation'"))
            conn.execute(sql_text("UPDATE consultations SET consultation_type = 'ayush' WHERE title = 'AYUSH / Ayurveda intake'"))
        if "structured_data" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN structured_data TEXT"))
        if "nlp_data" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN nlp_data TEXT"))
        encounter_columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(encounters)"))}
        if "care_type" not in encounter_columns:
            conn.execute(sql_text("ALTER TABLE encounters ADD COLUMN care_type VARCHAR DEFAULT 'allopathy'"))
        doctor_columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(doctor_profiles)"))}
        if "room_number" not in doctor_columns:
            conn.execute(sql_text("ALTER TABLE doctor_profiles ADD COLUMN room_number VARCHAR DEFAULT 'Not assigned'"))
        document_columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(medical_documents)"))}
        if "encounter_id" not in document_columns:
            conn.execute(sql_text("ALTER TABLE medical_documents ADD COLUMN encounter_id INTEGER"))
        conn.execute(sql_text("UPDATE doctor_profiles SET room_number='Room 12' WHERE (room_number IS NULL OR room_number='' OR room_number='Not assigned') AND user_id=(SELECT id FROM users WHERE email='doctor@sih26047.local' LIMIT 1)"))
        if "ai_summary" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN ai_summary TEXT"))
        if "ai_summary_generated_at" not in columns:
            conn.execute(sql_text("ALTER TABLE consultations ADD COLUMN ai_summary_generated_at DATETIME"))

ensure_phase4b_columns()


def ensure_ai5d_columns():
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(consultations)"))}
        additions = {
            "encounter_id": "INTEGER",
            "consultation_status": "VARCHAR DEFAULT 'draft'",
            "updated_at": "DATETIME",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(sql_text(f"ALTER TABLE consultations ADD COLUMN {name} {ddl}"))

ensure_ai5d_columns()

def ensure_ai5e_columns():
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(encounters)"))}
        additions = {
            "triage_status": "VARCHAR DEFAULT 'unreviewed'",
            "triage_notes": "TEXT",
            "triage_updated_by": "INTEGER",
            "triage_updated_at": "DATETIME",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(sql_text(f"ALTER TABLE encounters ADD COLUMN {name} {ddl}"))

ensure_ai5e_columns()


def ensure_final_department_seed():
    """Ensure the patient-facing department catalogue has the final demo set.

    These are hospital configuration values, not clinical/mock patient data.
    Existing department records are preserved.
    """
    with engine.begin() as conn:
        existing = {row[0] for row in conn.execute(sql_text("SELECT name FROM departments"))}
        seeds = [
            ("General Medicine", "General Medicine"),
            ("Cardiology", "Cardiology"),
            ("Orthopedics", "Orthopedics"),
            ("Pediatrics", "Pediatrics"),
            ("Gynecology", "Gynecology"),
        ]
        for name, specialty in seeds:
            if name not in existing:
                conn.execute(sql_text("INSERT INTO departments (name, specialty, active, created_at) VALUES (:name, :specialty, 1, :created_at)"), {"name": name, "specialty": specialty, "created_at": utc_now()})

ensure_final_department_seed()

def ensure_ai3c_columns():
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(medical_documents)"))}
        additions = {
            "classification": "VARCHAR",
            "classification_confidence": "VARCHAR",
            "classification_method": "VARCHAR",
            "classification_evidence": "TEXT",
            "classification_needs_review": "INTEGER DEFAULT 0",
            "structured_extraction": "TEXT",
            "extraction_needs_review": "INTEGER DEFAULT 0",
            "extraction_method": "VARCHAR",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(sql_text(f"ALTER TABLE medical_documents ADD COLUMN {name} {ddl}"))

ensure_ai3c_columns()

def ensure_ai3e_columns():
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(medical_documents)"))}
        additions = {
            "verification_status": "VARCHAR DEFAULT 'Pending'",
            "verified_data": "TEXT",
            "verification_notes": "TEXT",
            "verified_by": "INTEGER",
            "verified_at": "DATETIME",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(sql_text(f"ALTER TABLE medical_documents ADD COLUMN {name} {ddl}"))

ensure_ai3e_columns()

def ensure_phase1e_columns():
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(interview_states)"))}
        additions = {
            "repair_count": "INTEGER DEFAULT 0",
            "voice_failure_count": "INTEGER DEFAULT 0",
            "last_input_mode": "VARCHAR",
            "last_repair_action": "VARCHAR",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(sql_text(f"ALTER TABLE interview_states ADD COLUMN {name} {ddl}"))

ensure_phase1e_columns()


# Phase 5A/5B tables are created alongside the existing Phase 3-4 schema.
Base.metadata.create_all(bind=engine)

def ensure_phase5b_indexes():
    with engine.begin() as conn:
        # Existing databases created before AI-5B need the same token uniqueness guarantee.
        conn.execute(sql_text("CREATE UNIQUE INDEX IF NOT EXISTS uq_encounter_daily_department_token ON encounters (visit_date, department, token_number)"))

ensure_phase5b_indexes()


# FIX 3 — Authentication/session security
# Passwords use a password-specific KDF. Legacy SHA-256 demo hashes are still
# accepted once and transparently upgraded at successful login.
PASSWORD_KDF = "pbkdf2_sha256"
PASSWORD_KDF_ITERATIONS = int(os.getenv("SIH_PASSWORD_KDF_ITERATIONS", "210000"))
PASSWORD_SALT_BYTES = 16
DUMMY_PASSWORD_HASH = "pbkdf2_sha256$210000$00000000000000000000000000000000$" + "0" * 64

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_KDF_ITERATIONS)
    return f"{PASSWORD_KDF}${PASSWORD_KDF_ITERATIONS}${salt.hex()}${digest.hex()}"

def _verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """Return (valid, needs_upgrade). Supports legacy SHA-256 migration."""
    if not stored_hash:
        return False, False
    if stored_hash.startswith(PASSWORD_KDF + "$"):
        try:
            scheme, iterations_s, salt_hex, digest_hex = stored_hash.split("$", 3)
            iterations = int(iterations_s)
            if scheme != PASSWORD_KDF or iterations < 100000 or len(salt_hex) < 16:
                return False, False
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected), False
        except (ValueError, TypeError):
            return False, False

    # Legacy prototype accounts used unsalted SHA-256. Verify once, then upgrade.
    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, stored_hash), True


def make_profile(db, user, age=None, gender=None, phone=None):
    profile = PatientProfile(
        user_id=user.id, age=age, gender=gender, phone=phone,
        blood_group="", allergies="", conditions="", medications="", address=""
    )
    db.add(profile)
    return profile


DEMO_PATIENT_EMAIL = os.getenv("SIH_DEMO_PATIENT_EMAIL", "patient@sih26047.local").strip().lower()
DEMO_PATIENT_PASSWORD = os.getenv("SIH_DEMO_PATIENT_PASSWORD", "patient123")
DEMO_DOCTOR_EMAIL = os.getenv("SIH_DEMO_DOCTOR_EMAIL", "doctor@sih26047.local").strip().lower()
DEMO_DOCTOR_PASSWORD = os.getenv("SIH_DEMO_DOCTOR_PASSWORD", "doctor123")
DEMO_ADMIN_EMAIL = os.getenv("SIH_DEMO_ADMIN_EMAIL", "admin@sih26047.local").strip().lower()
DEMO_ADMIN_PASSWORD = os.getenv("SIH_DEMO_ADMIN_PASSWORD", "admin123")

# Patient-facing departments are a controlled hospital catalogue. Internal test
# department names must never leak into the patient workflow.
PATIENT_DEPARTMENT_CATALOG = (
    ("General Medicine", "General Medicine"),
    ("Cardiology", "Cardiology & Heart"),
    ("Orthopedics", "Orthopedics"),
    ("Pediatrics", "Pediatrics"),
    ("Gynecology", "Gynecology"),
)
PATIENT_DEPARTMENT_NAMES = {name for name, _specialty in PATIENT_DEPARTMENT_CATALOG}


def seed_demo_data():
    if not DEMO_MODE:
        return
    if min(len(DEMO_PATIENT_PASSWORD), len(DEMO_DOCTOR_PASSWORD), len(DEMO_ADMIN_PASSWORD)) < 8:
        raise RuntimeError("Demo passwords must be at least 8 characters.")
    db = SessionLocal()
    try:
        # Startup seeding is only a bootstrap for an empty development/demo DB.
        # Once a database has been intentionally reset/seeded, startup must not
        # re-create hidden legacy clinicians or patients.
        if db.query(User).count() > 0:
            return
        patient = db.query(User).filter(User.email == DEMO_PATIENT_EMAIL).first()
        if not patient:
            patient = User(
                name="Priya Sharma", email=DEMO_PATIENT_EMAIL,
                password_hash=hash_password(DEMO_PATIENT_PASSWORD), role="patient"
            )
            db.add(patient)
            db.flush()
            make_profile(db, patient, 42, "Female", "+91 90000 00000")

        doctor = db.query(User).filter(User.email == DEMO_DOCTOR_EMAIL).first()
        if not doctor:
            doctor = User(
                name="Dr. Ananya Verma", email=DEMO_DOCTOR_EMAIL,
                password_hash=hash_password(DEMO_DOCTOR_PASSWORD), role="doctor"
            )
            db.add(doctor)
            db.flush()
        admin = db.query(User).filter(User.email == DEMO_ADMIN_EMAIL).first()
        if not admin:
            admin = User(
                name="Neha Kapoor", email=DEMO_ADMIN_EMAIL,
                password_hash=hash_password(DEMO_ADMIN_PASSWORD), role="admin"
            )
            db.add(admin)
            db.flush()
        # The configured demo doctor is the single deterministic clinician for
        # the presentation dataset. Additional clinicians can still be created
        # through the existing hospital administration workflow.
        demo_department_doctors = [
            (doctor, "General Medicine", "General Medicine", "UP-MED-20481", "Room 12"),
        ]

        for department_name, specialty in PATIENT_DEPARTMENT_CATALOG:
            dept = db.query(Department).filter(Department.name == department_name).first()
            if not dept:
                db.add(Department(name=department_name, specialty=specialty, active=1))
            else:
                dept.active = 1
                dept.specialty = specialty
        opd = db.query(OPDConfiguration).filter(OPDConfiguration.department == "General Medicine").first()
        if not opd:
            db.add(OPDConfiguration(department="General Medicine", working_days="Mon,Tue,Wed,Thu,Fri", start_time="09:00", end_time="17:00", active=1))
        hospital = db.query(HospitalConfiguration).first()
        if not hospital:
            db.add(HospitalConfiguration())
        db.commit()
    finally:
        db.close()


seed_demo_data()


def ensure_user_facing_demo_names():
    """Normalize legacy internal/test names in persisted demo records.

    IDs and relationships are deliberately preserved. Names are deterministic
    so the same patient/doctor keeps the same identity across every screen.
    This migration only targets known internal labels; ordinary registered
    users are never renamed.
    """
    forbidden = re.compile(r"(?:AI5F|AI5H|Final Handoff|Test Patient|Test Doctor|Demo Patient|Demo Doctor|Debug)", re.IGNORECASE)
    patient_names = ["Priya Singh", "Vikram Patel", "Sneha Gupta", "Rohit Mehta", "Neha Joshi", "Arjun Kapoor"]
    doctor_names = ["Dr. Kavita Sharma", "Dr. Rohan Mehta", "Dr. Meera Iyer", "Dr. Arjun Kapoor"]
    with engine.begin() as conn:
        rows = conn.execute(sql_text("SELECT id, name, role FROM users WHERE name IS NOT NULL")).fetchall()
        for user_id, name, role in rows:
            if not forbidden.search(str(name)):
                continue
            pool = doctor_names if role == "doctor" else patient_names
            replacement = pool[(int(user_id) - 1) % len(pool)]
            conn.execute(sql_text("UPDATE users SET name=:name WHERE id=:id"), {"name": replacement, "id": user_id})

        # Clean the legacy internal department/registration labels attached to
        # the old demo cardiology doctor. Keep the doctor ID and all encounter
        # relationships intact.
        conn.execute(sql_text("""
            UPDATE doctor_profiles
            SET department='Cardiology', registration_number='UP-MED-20481'
            WHERE department LIKE '%AI5F%' OR registration_number LIKE 'AI5F%'
        """))


ensure_user_facing_demo_names()


def ensure_demo_identity() -> None:
    """Keep the three prototype login identities presentation-ready.

    This only targets the configured demo emails, preserving every other
    registered user's identity and all existing encounter relationships.
    """
    if not DEMO_MODE:
        return
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.email == DEMO_PATIENT_EMAIL).first()
        if patient:
            patient.name = "Priya Sharma"
            profile = db.query(PatientProfile).filter(PatientProfile.user_id == patient.id).first()
            if profile:
                profile.age = profile.age or 42
                profile.gender = "Female"
                profile.phone = profile.phone or "+91 90000 00000"
        doctor = db.query(User).filter(User.email == DEMO_DOCTOR_EMAIL).first()
        if doctor:
            doctor.name = "Dr. Ananya Verma"
            dp = db.query(DoctorProfile).filter(DoctorProfile.user_id == doctor.id).first()
            if dp:
                dp.specialty = "General Medicine"
                dp.department = "General Medicine"
                dp.registration_number = dp.registration_number or "UP-MED-20481"
                dp.room_number = dp.room_number or "Room 12"
                dp.active = 1
        admin = db.query(User).filter(User.email == DEMO_ADMIN_EMAIL).first()
        if admin:
            admin.name = "Neha Kapoor"

        # Remove only legacy prototype accounts whose identifiers are known to be
        # internal/test artifacts. This keeps demo login data and clinician
        # assignment deterministic without touching ordinary registered users.
        legacy_emails = ["final-handoff-00f0549fe0@example.local",
                         "ai5h-fe2ee2d5@example.local", "ai5h-00390218@example.local",
                         "ai5h-70e362f5@example.local"]
        legacy_ids = [r[0] for r in db.query(User.id).filter(User.email.in_(legacy_emails)).all()]
        if legacy_ids:
            db.query(MedicalDocument).filter(MedicalDocument.patient_id.in_(legacy_ids)).delete(synchronize_session=False)
            db.query(Consultation).filter(Consultation.patient_id.in_(legacy_ids)).delete(synchronize_session=False)
            db.query(Encounter).filter(Encounter.patient_id.in_(legacy_ids)).delete(synchronize_session=False)
            db.query(PatientProfile).filter(PatientProfile.user_id.in_(legacy_ids)).delete(synchronize_session=False)
            db.query(DoctorProfile).filter(DoctorProfile.user_id.in_(legacy_ids)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_(legacy_ids)).delete(synchronize_session=False)

        # Remove known internal department artifacts while preserving the public
        # department catalogue.
        db.query(Department).filter(~Department.name.in_(PATIENT_DEPARTMENT_NAMES)).delete(synchronize_session=False)

        # Remove known internal Phase/AI test encounters before normalizing the
        # demo patient. These records are development artifacts, not clinical
        # history, and can otherwise collide with the daily token uniqueness
        # constraint when their department is normalized to General Medicine.
        internal_encounter_ids = [r[0] for r in db.query(Encounter.id).filter(Encounter.department.ilike("%AI5%" )).all()]
        if internal_encounter_ids:
            db.query(MedicalDocument).filter(MedicalDocument.encounter_id.in_(internal_encounter_ids)).delete(synchronize_session=False)
            db.query(Consultation).filter(Consultation.encounter_id.in_(internal_encounter_ids)).delete(synchronize_session=False)
            db.query(InterviewState).filter(InterviewState.encounter_id.in_(internal_encounter_ids)).delete(synchronize_session=False)
            db.query(Encounter).filter(Encounter.id.in_(internal_encounter_ids)).delete(synchronize_session=False)

        # Normalize any existing encounter for the configured demo patient to the
        # real demo clinician/department and keep its room derived from the doctor.
        demo_encounters = db.query(Encounter).filter(Encounter.patient_id == patient.id).all()
        general_demo_doctor = db.query(User).filter(User.email == DEMO_DOCTOR_EMAIL).first()
        for enc in demo_encounters:
            enc.doctor_id = general_demo_doctor.id if general_demo_doctor else enc.doctor_id
            enc.department = "General Medicine"
            enc.visit_date = date.today().isoformat()
            enc.status = enc.status if enc.status in {"waiting", "called", "in_consultation", "completed"} else "waiting"
            if enc.token_number is None or enc.token_number < 1:
                enc.token_number = 1

        hospital = db.query(HospitalConfiguration).first()
        if hospital and (not hospital.hospital_name or "Demo Hospital" in hospital.hospital_name):
            hospital.hospital_name = "AarogyaSaar District Hospital"
            hospital.facility_code = hospital.facility_code if hospital.facility_code and "AI5F" not in hospital.facility_code else "AS-DH-26047"
        db.commit()
    finally:
        db.close()


ensure_demo_identity()

# Phase 5H / Final MVP security foundation. Demo sessions are short-lived bearer
# tokens stored only as hashes; the client never sends the raw token to the DB.
SESSION_MINUTES = int(os.getenv("SIH_SESSION_MINUTES", "120"))
SESSION_IDLE_MINUTES = int(os.getenv("SIH_SESSION_IDLE_MINUTES", "60"))
LOGIN_WINDOW_SECONDS = int(os.getenv("SIH_LOGIN_WINDOW_SECONDS", "60"))
LOGIN_MAX_FAILURES = int(os.getenv("SIH_LOGIN_MAX_FAILURES", "10"))
_login_failures: dict[str, list[float]] = {}
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/register", "/api/auth/demo-accounts"}
if not IS_PRODUCTION:
    PUBLIC_PATHS.update({"/docs", "/openapi.json", "/redoc"})

def _resource_rate_limit_key(request: Request, actor: Optional[dict]) -> str:
    identity = f"user:{actor['id']}" if actor else f"ip:{(request.client.host if request.client else 'unknown')}"
    return f"{identity}|{request.url.path}"


def _resource_rate_limit_config(path: str):
    if path == "/api/voice/transcribe":
        return VOICE_TRANSCRIBE_RATE_MAX
    if path == "/api/voice/speak":
        return VOICE_TTS_RATE_MAX
    if path.startswith("/api/documents/") or path == "/api/documents/upload":
        return DOCUMENT_AI_RATE_MAX
    if path.startswith("/api/ai/") or path.startswith("/api/interview"):
        return AI_RATE_MAX_REQUESTS
    return None


def enforce_resource_rate_limit(request: Request, actor: Optional[dict]):
    """Small process-local limiter for expensive endpoints. Production should use shared infrastructure."""
    limit = _resource_rate_limit_config(request.url.path)
    if not limit:
        return
    key = _resource_rate_limit_key(request, actor)
    now = time.monotonic()
    with _ai_rate_lock:
        values = [t for t in _ai_rate_failures.get(key, []) if now - t < AI_RATE_WINDOW_SECONDS]
        if len(values) >= limit:
            _ai_rate_failures[key] = values
            raise HTTPException(status_code=429, detail="Too many requests for this resource. Please wait and try again.", headers={"Retry-After": str(AI_RATE_WINDOW_SECONDS)})
        values.append(now)
        _ai_rate_failures[key] = values


def _bounded_text(text: str, maximum: int = 1000) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) > maximum:
        raise HTTPException(status_code=413, detail=f"Input exceeds the {maximum} character limit.")
    return clean


def _hash_token(token: str) -> str:
    # Session tokens are already generated from high-entropy random bytes; a fast
    # hash is appropriate here because the token itself is not password-derived.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def _login_key(request: Request | None, email: str) -> str:
    # Rate-limit by both normalized account and client address. This is an
    # in-memory prototype control; production should use a shared limiter.
    host = "unknown"
    if request is not None and request.client is not None:
        host = request.client.host or "unknown"
    return f"{host.lower()}|{email.strip().lower()}"

def _prune_login_failures(key: str, now: float | None = None) -> list[float]:
    now = time.monotonic() if now is None else now
    values = [t for t in _login_failures.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    if values:
        _login_failures[key] = values
    else:
        _login_failures.pop(key, None)
    return values

def _login_allowed(key: str) -> bool:
    return len(_prune_login_failures(key)) < LOGIN_MAX_FAILURES

def _record_login_failure(key: str) -> None:
    values = _prune_login_failures(key)
    values.append(time.monotonic())
    _login_failures[key] = values

def _clear_login_failures(key: str) -> None:
    _login_failures.pop(key, None)

def create_session(db, user_id: int):
    now = utc_now()
    # Remove already-expired sessions for this account without touching active devices.
    db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.expires_at <= now).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    rec = UserSession(
        user_id=user_id,
        token_hash=_hash_token(token),
        expires_at=now + timedelta(minutes=SESSION_MINUTES),
        created_at=now,
        last_seen_at=now,
    )
    db.add(rec)
    return token

def audit(db, user_id, role, action, resource, request_id=None):
    db.add(AuditEvent(user_id=user_id, role=role, action=action, resource=resource, request_id=request_id))

def authenticate_request(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in again.")
    token = auth[7:].strip()
    if not token or len(token) < 40:
        raise HTTPException(status_code=401, detail="User session is invalid.")
    db = SessionLocal()
    try:
        now = utc_now()
        rec = db.query(UserSession).filter(
            UserSession.token_hash == _hash_token(token),
            UserSession.revoked_at.is_(None),
        ).first()
        if not rec:
            raise HTTPException(status_code=401, detail="User session is invalid.")
        if rec.expires_at <= now:
            raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
        if rec.last_seen_at and rec.last_seen_at < now - timedelta(minutes=SESSION_IDLE_MINUTES):
            rec.revoked_at = now
            db.commit()
            raise HTTPException(status_code=401, detail="Session expired due to inactivity. Please sign in again.")
        user = db.query(User).filter(User.id == rec.user_id).first()
        if not user:
            rec.revoked_at = now
            db.commit()
            raise HTTPException(status_code=401, detail="User session is invalid.")
        rec.last_seen_at = now
        db.commit()
        return {"id": user.id, "role": user.role}
    finally:
        db.close()

# ---------------------------------------------------------------------------
# FIX 1 — Resource-level authorization
# Authentication proves who the caller is; these helpers prove what they may access.
# ---------------------------------------------------------------------------
PATIENT_DATA_STAFF_ROLES = {"doctor", "triage", "admin"}
CLINICAL_ROLES = {"doctor", "triage", "admin"}

def require_roles(actor: dict, roles: set[str], detail: str = "Not authorized for this resource."):
    if actor["role"] not in roles:
        raise HTTPException(status_code=403, detail=detail)
    return actor

def doctor_has_patient_access(db, doctor_id: int, patient_id: int) -> bool:
    """Return True only when the doctor is explicitly assigned to an encounter for the patient.

    We intentionally use the existing Encounter.doctor_id relationship rather than
    adding a new permission table/column. Historical encounters count as a valid
    clinical relationship for this prototype, so doctors can still review the
    longitudinal record of patients they have previously treated.
    """
    return db.query(Encounter.id).filter(
        Encounter.patient_id == patient_id,
        Encounter.doctor_id == doctor_id,
    ).first() is not None


def authorize_doctor_patient(actor: dict, patient_id: int, db=None):
    """Enforce patient-level access for doctors without changing triage/admin access.

    Patients may access only themselves. Doctors must have an explicit Encounter
    assignment to the patient. Triage/admin retain their existing hospital-wide
    clinical access. No new schema or client-side property is required.
    """
    if actor["role"] == "patient":
        if actor["id"] != patient_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this patient's data.")
        return actor
    if actor["role"] == "doctor":
        own_db = db is None
        check_db = db or SessionLocal()
        try:
            if not doctor_has_patient_access(check_db, actor["id"], patient_id):
                raise HTTPException(status_code=403, detail="This doctor is not assigned to this patient.")
            return actor
        finally:
            if own_db:
                check_db.close()
    if actor["role"] in {"triage", "admin"}:
        return actor
    raise HTTPException(status_code=403, detail="Not authorized to access patient data.")


def authorize_patient(actor: dict, patient_id: int, *, allow_patient: bool = True, db=None):
    """Backward-compatible patient authorization with doctor-to-patient scoping.

    Existing call sites keep working. The optional DB session avoids opening a
    second connection in endpoints that already have one.
    """
    if actor["role"] == "patient":
        if not allow_patient or actor["id"] != patient_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this patient's data.")
        return actor
    return authorize_doctor_patient(actor, patient_id, db=db)

def authorize_interoperability_patient(actor: dict, patient_id: int, db):
    """Authorize FHIR/ABDM access to one patient's interoperability resources.

    FHIR/ABDM endpoints are patient-level clinical-data endpoints, so they use
    the same doctor-to-patient relationship rule as the rest of the clinical
    API. Triage/admin retain hospital-wide access. Consent is checked separately
    by operations that actually build an ABDM exchange package.
    """
    require_roles(actor, CLINICAL_ROLES, "FHIR/ABDM access is restricted to authorized clinical staff.")
    authorize_patient(actor, patient_id, db=db)
    patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient

def authorize_encounter(actor: dict, encounter):
    if actor["role"] == "patient":
        if actor["id"] != encounter.patient_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this encounter.")
        return actor
    if actor["role"] not in CLINICAL_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to access encounters.")
    if actor["role"] == "doctor" and encounter.doctor_id != actor["id"]:
        raise HTTPException(status_code=403, detail="This encounter is not assigned to this doctor.")
    return actor

def authorize_consultation(actor: dict, consultation, db):
    if actor["role"] == "patient":
        if actor["id"] != consultation.patient_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this consultation.")
        return actor
    if actor["role"] not in CLINICAL_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to access consultations.")
    if actor["role"] == "doctor":
        if not consultation.encounter_id:
            raise HTTPException(status_code=403, detail="This consultation is not linked to an assigned encounter.")
        encounter = db.query(Encounter).filter(Encounter.id == consultation.encounter_id).first()
        if not encounter or encounter.doctor_id != actor["id"]:
            raise HTTPException(status_code=403, detail="This consultation is not assigned to this doctor.")
    return actor

def authorize_document(actor: dict, document, db=None, *, write: bool = False):
    """Authorize access to a stored medical document using patient/encounter scope."""
    if actor["role"] == "patient":
        if actor["id"] != document.patient_id:
            raise HTTPException(status_code=403, detail="You are not authorized to access this document.")
        if write:
            raise HTTPException(status_code=403, detail="Patients cannot modify clinical document processing or verification.")
        return actor
    if actor["role"] not in CLINICAL_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to access clinical documents.")
    if actor["role"] == "doctor":
        if db is None:
            raise HTTPException(status_code=500, detail="Document authorization requires database context.")
        authorize_doctor_patient(actor, document.patient_id, db)
    return actor

def authorize_medical_document_intake_document(actor: dict, patient_id: str, encounter_id: str, action: str):
    """DB-backed authorization for the AI-3A namespaced document store.

    AI-3A receives patient/encounter identifiers from multipart form data, so
    those identifiers are checked against the authenticated actor and the real
    Encounter row rather than trusted as client claims.
    """
    try:
        pid = int(patient_id)
        eid = int(encounter_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid patient or encounter identifier.")

    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == eid).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        if encounter.patient_id != pid:
            raise HTTPException(status_code=403, detail="The document does not belong to this encounter.")

        if actor["role"] == "patient":
            if actor["id"] != pid:
                raise HTTPException(status_code=403, detail="Patients can access documents only for themselves.")
            return actor

        if actor["role"] not in CLINICAL_ROLES:
            raise HTTPException(status_code=403, detail="Not authorized to access clinical documents.")

        if actor["role"] == "doctor" and encounter.doctor_id != actor["id"]:
            raise HTTPException(status_code=403, detail="This encounter is assigned to another doctor.")
        return actor
    finally:
        db.close()

def authorize_interview_patient(actor: dict, patient_id: int):
    if actor["role"] != "patient" or actor["id"] != patient_id:
        raise HTTPException(status_code=403, detail="Interview data can only be accessed by the owning patient.")
    return actor

def require_active_consent(db, patient_id: int):
    """Require current patient consent before creating, continuing, or completing clinical history."""
    active = (db.query(ConsentRecord)
              .filter(ConsentRecord.patient_id == patient_id,
                      ConsentRecord.granted == 1,
                      ConsentRecord.revoked_at.is_(None))
              .order_by(ConsentRecord.created_at.desc())
              .first())
    if not active:
        raise HTTPException(
            status_code=403,
            detail="Active patient consent is required before starting or continuing the clinical interview."
        )
    return active

def _csv_env(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

CORS_ORIGINS = _csv_env("SIH_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
TRUSTED_HOSTS = _csv_env("SIH_TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
REQUIRE_HTTPS = os.getenv("SIH_REQUIRE_HTTPS", "1" if IS_PRODUCTION else "0").strip().lower() in {"1", "true", "yes", "on"}
MAX_REQUEST_BODY_BYTES = int(os.getenv("SIH_MAX_REQUEST_BODY_MB", "32")) * 1024 * 1024

if IS_PRODUCTION:
    if any(origin == "*" for origin in CORS_ORIGINS):
        raise RuntimeError("Wildcard CORS is forbidden in production.")
    if any(origin.lower().startswith(("http://localhost", "http://127.0.0.1")) for origin in CORS_ORIGINS):
        raise RuntimeError("Localhost CORS origins are forbidden in production.")
    if not TRUSTED_HOSTS or "*" in TRUSTED_HOSTS:
        raise RuntimeError("Explicit SIH_TRUSTED_HOSTS are required in production.")
    if not os.getenv("SIH_DATABASE_URL", "").strip():
        raise RuntimeError("SIH_DATABASE_URL must be explicitly configured in production.")
    if DEMO_MODE:
        raise RuntimeError("SIH_DEMO_MODE must be disabled in production.")

app = FastAPI(
    title="SIH26047 Clinical AI API",
    version="8.0.0",
    description="SIH26047 Phase 5B: cumulative clinical prototype with validation, physician AI synthesis with local AI/NLP symptom understanding, consent, AYUSH, documents, and FHIR-ready interoperability, including AI-3C document classification.",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=TRUSTED_HOSTS,
)
if REQUIRE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
    max_age=600,
)

# AI-3A unified document-intake module.
register_medical_document_intake(app, storage_dir=str(BASE_DIR / "data" / "documents"), authorize=authorize_medical_document_intake_document, enforce_auth=True)

def _request_id(request: Request) -> str:
    # Client supplied IDs are accepted only as bounded opaque trace values.
    # We never log request bodies, query strings, bearer tokens, or other PHI.
    supplied = request.headers.get("X-Request-ID", "").strip()
    if supplied and len(supplied) <= 80 and all(ch.isalnum() or ch in "-_." for ch in supplied):
        return supplied
    return uuid.uuid4().hex[:16]


def _audit_request_event(request: Request, response_status: int) -> None:
    actor = getattr(request.state, "actor", None)
    if not actor:
        return
    path = request.url.path
    # Avoid self-referential/noisy audit reads and endpoints already represented
    # by explicit security events. Other authenticated reads/writes are traced.
    if path in {"/api/audit/me", "/api/security/status", "/api/auth/logout"}:
        return
    db = SessionLocal()
    try:
        action = f"request_{request.method.lower()}_{response_status}"
        audit(
            db,
            actor["id"],
            actor["role"],
            action,
            path,
            getattr(request.state, "request_id", None),
        )
        db.commit()
    except Exception:
        # Audit failure must never turn a successful clinical operation into a
        # 500 response. The primary endpoint already owns its transaction.
        db.rollback()
    finally:
        db.close()


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # CORS preflight must remain public. All application APIs except auth/health
    # require a valid short-lived bearer session.
    request.state.request_id = _request_id(request)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                from starlette.responses import JSONResponse
                response = JSONResponse({"detail": "Request body is too large."}, status_code=413)
                response.headers["Retry-After"] = "0"
                response.headers["X-Request-ID"] = request.state.request_id
                return response
        except ValueError:
            from starlette.responses import JSONResponse
            response = JSONResponse({"detail": "Invalid Content-Length header."}, status_code=400)
            response.headers["X-Request-ID"] = request.state.request_id
            return response
    if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS or not request.url.path.startswith("/api/"):
        response = await call_next(request)
    else:
        try:
            actor = authenticate_request(request)
            request.state.actor = actor
            enforce_resource_rate_limit(request, actor)
            response = await call_next(request)
        except HTTPException as exc:
            from starlette.responses import JSONResponse
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":
        _audit_request_event(request, response.status_code)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else response.headers.get("Cache-Control", "")
    response.headers["X-Request-ID"] = request.state.request_id
    if "server" in response.headers:
        del response.headers["server"]
    if IS_PRODUCTION and REQUIRE_HTTPS:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2)
    email: str
    password: str = Field(min_length=8)
    age: int = Field(ge=1, le=120)
    gender: str
    phone: str = ""


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2)
    age: int = Field(ge=1, le=120)
    gender: str = ""
    phone: str = ""
    blood_group: str = ""
    allergies: str = ""
    conditions: str = ""
    medications: str = ""
    address: str = ""


class InterviewAnswer(BaseModel):
    patient_id: int
    session_id: str
    question_id: str
    answer: str = Field(default="", max_length=5000)
    skipped: bool = False
    answers: dict = Field(default_factory=dict)
    language: str = "en-IN"
    input_mode: str = "text"


class ClinicalNLURequest(BaseModel):
    text: str = Field(min_length=1)
    language: str = "en-IN"
    question_id: Optional[str] = None


class ConversationRepairRequest(BaseModel):
    patient_id: int
    session_id: str
    text: str = ""
    event: str = "answer"
    attempt: int = Field(default=0, ge=0, le=10)
    language: str = "en-IN"
    input_mode: str = "voice"


class InterviewComplete(BaseModel):
    patient_id: int
    session_id: str
    title: str
    answers: dict
    structured: dict


class ConsentRequest(BaseModel):
    patient_id: int
    language: str = "en-IN"
    audio_explained: bool = False
    consent_type: str = "Clinical case-taking"
    granted: bool = True


class AccessibilityPreferenceRequest(BaseModel):
    language: str = "en-IN"
    input_mode: str = "touch"
    font_scale: str = "1.0"
    high_contrast: bool = False
    reduced_motion: bool = False
    captions: bool = True
    audio_enabled: bool = True
    audio_speed: str = "1.0"
    assisted_mode: bool = False


class ClinicalQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class FHIRExportRequest(BaseModel):
    patient_id: int
    exported_by: Optional[int] = None
    abha_address: Optional[str] = None

class ABDMExportRequest(BaseModel):
    patient_id: int
    exported_by: Optional[int] = None
    abha_address: Optional[str] = None
    facility_id: str = "SIH26047-DEMO-FACILITY"
    practitioner_id: str = "SIH26047-DEMO-HPR"
    consent_reference: Optional[str] = None

class EncounterCreateRequest(BaseModel):
    patient_id: int
    department: str = Field(default="General Medicine", min_length=1, max_length=80)
    priority: str = Field(default="normal", min_length=1, max_length=20)
    reason: str = Field(default="", max_length=500)
    care_type: str = Field(default="allopathy", min_length=3, max_length=30)
    doctor_id: Optional[int] = None


class EncounterIntakeUpdateRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
    care_type: str = Field(default="allopathy", min_length=3, max_length=30)


class EncounterStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=30)
    doctor_id: Optional[int] = None


class TriageActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=30)
    notes: str = Field(default="", max_length=3000)
    priority: Optional[str] = Field(default=None, max_length=20)


class ConsultationStartRequest(BaseModel):
    encounter_id: int
    title: str = Field(default="Clinical consultation", min_length=1, max_length=120)


class ConsultationUpdateRequest(BaseModel):
    sections: dict = Field(default_factory=dict)
    doctor_notes: str = Field(default="", max_length=5000)


class ConsultationCompleteRequest(BaseModel):
    sections: dict = Field(default_factory=dict)
    doctor_notes: str = Field(default="", max_length=5000)
    doctor_review: str = Field(default="Completed", min_length=1, max_length=40)



class AdminDepartmentRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    specialty: str = Field(default="General Medicine", min_length=2, max_length=100)
    active: bool = True


class AdminDoctorRequest(BaseModel):
    user_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    email: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=200)
    specialty: str = Field(default="General Medicine", min_length=2, max_length=100)
    department: str = Field(default="General Medicine", min_length=2, max_length=100)
    registration_number: str = Field(default="", max_length=100)
    room_number: str = Field(default="Not assigned", max_length=80)
    active: bool = True


class AdminOPDRequest(BaseModel):
    department: str = Field(min_length=2, max_length=100)
    working_days: List[str] = Field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])
    start_time: str = Field(default="09:00", min_length=5, max_length=5)
    end_time: str = Field(default="17:00", min_length=5, max_length=5)
    active: bool = True


class AdminAvailabilityRequest(BaseModel):
    doctor_id: int
    day_of_week: str = Field(min_length=3, max_length=9)
    start_time: str = Field(min_length=5, max_length=5)
    end_time: str = Field(min_length=5, max_length=5)
    active: bool = True


class AdminRoutingRequest(BaseModel):
    department: str = Field(min_length=2, max_length=100)
    specialty: str = Field(min_length=2, max_length=100)
    doctor_id: Optional[int] = None
    priority: int = Field(default=100, ge=0, le=10000)
    active: bool = True


class AdminHospitalRequest(BaseModel):
    hospital_name: str = Field(min_length=2, max_length=200)
    facility_code: str = Field(min_length=2, max_length=100)
    timezone: str = Field(default="Asia/Kolkata", min_length=3, max_length=80)
    default_department: str = Field(default="General Medicine", min_length=2, max_length=100)
    active: bool = True


def user_response(user):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


def profile_response(user):
    p = user.profile
    return {
        "id": user.id, "name": user.name, "email": user.email, "role": user.role,
        "age": p.age if p else None, "gender": p.gender if p else "",
        "phone": p.phone if p else "", "blood_group": p.blood_group if p else "",
        "allergies": p.allergies if p else "", "conditions": p.conditions if p else "",
        "medications": p.medications if p else "", "address": p.address if p else "",
    }


@app.get("/")
def root():
    return {"project": "AarogyaSaar", "status": "running"}


@app.get("/api/health")
def health():
    return {"status": "ok", "message": "SIH26047 Final MVP backend is running", "version": "8.7.0"}


@app.get("/api/auth/demo-accounts")
def demo_accounts():
    if IS_PRODUCTION or not DEMO_MODE:
        return {"enabled": False, "accounts": []}
    return {"enabled": True, "accounts": [
        {"role": "patient", "label": "Patient demo", "email": DEMO_PATIENT_EMAIL, "password": DEMO_PATIENT_PASSWORD},
        {"role": "doctor", "label": "Doctor demo", "email": DEMO_DOCTOR_EMAIL, "password": DEMO_DOCTOR_PASSWORD},
        {"role": "admin", "label": "Hospital admin demo", "email": DEMO_ADMIN_EMAIL, "password": DEMO_ADMIN_PASSWORD},
    ]}

@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request):
    email = payload.email.strip().lower()
    key = _login_key(request, email)
    if not _login_allowed(key):
        # Do not reveal whether the account exists or why the attempt was blocked.
        raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Please try again later.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        stored_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
        valid, needs_upgrade = _verify_password(payload.password, stored_hash)
        if not user or not valid:
            _record_login_failure(key)
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        if needs_upgrade:
            user.password_hash = hash_password(payload.password)
        _clear_login_failures(key)
        token = create_session(db, user.id)
        audit(db, user.id, user.role, "login", "auth")
        db.commit()
        return {"message": "Login successful", "user": user_response(user), "access_token": token, "token_type": "bearer", "expires_in_minutes": SESSION_MINUTES}
    finally:
        db.close()


@app.post("/api/auth/register")
def register(payload: RegisterRequest):
    db = SessionLocal()
    try:
        email = payload.email.strip().lower()
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        user = User(
            name=payload.name.strip(), email=email,
            password_hash=hash_password(payload.password), role="patient"
        )
        db.add(user)
        db.flush()
        make_profile(db, user, payload.age, payload.gender, payload.phone)
        token = create_session(db, user.id)
        audit(db, user.id, user.role, "register", "auth")
        db.commit()
        db.refresh(user)
        return {"message": "Patient account created", "user": user_response(user), "access_token": token, "token_type": "bearer", "expires_in_minutes": SESSION_MINUTES}
    finally:
        db.close()


@app.post("/api/auth/logout")
def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not auth[7:].strip():
        return {"message": "Signed out securely."}
    token_hash = _hash_token(auth[7:].strip())
    db = SessionLocal()
    try:
        rec = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
        if rec and rec.revoked_at is None:
            rec.revoked_at = utc_now()
            audit(db, rec.user_id, None, "logout", "auth")
            db.commit()
        return {"message": "Signed out securely."}
    finally:
        db.close()

@app.get("/api/system/integration-audit")
def integration_audit(request: Request):
    user = authenticate_request(request)
    if user["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Integration audit is restricted to authorized clinical/administrative roles.")
    result = build_integration_audit(app, engine, BASE_DIR)
    db = SessionLocal()
    try:
        audit(db, user["id"], user["role"], "integration_audit", "system")
        db.commit()
    finally:
        db.close()
    return result


@app.get("/api/security/status")
def security_status(request: Request):
    user = authenticate_request(request)
    db = SessionLocal()
    try:
        user_id = user["id"]
        user_role = user["role"]
        active = db.query(UserSession).filter(UserSession.user_id==user_id, UserSession.revoked_at.is_(None), UserSession.expires_at>utc_now()).count()
        audits = db.query(AuditEvent).filter(AuditEvent.user_id==user_id).count()
        return {"role":user_role,"session_active":True,"active_sessions":active,"audit_events":audits,"controls":["Bearer session authentication","Short-lived sessions","Idle session timeout","Password KDF hashing","Login rate limiting","Role-aware accounts","Consent gate for ABDM export","Audit logging","Security response headers","Environment-driven database/upload paths","Explicit CORS allowlist","Demo seeding disabled in production"],"environment":APP_ENV,"demo_mode":DEMO_MODE,"cors_origins":CORS_ORIGINS,"production_note":"Production still requires HTTPS, managed secrets, hardened identity provider, encryption/key management and formal security assessment."}
    finally:
        db.close()

@app.get("/api/audit/me")
def audit_me(request: Request):
    user = authenticate_request(request)
    db=SessionLocal()
    try:
        rows=db.query(AuditEvent).filter(AuditEvent.user_id==user["id"]).order_by(AuditEvent.created_at.desc()).limit(50).all()
        return {"events":[{"id":r.id,"action":r.action,"resource":r.resource,"created_at":r.created_at.isoformat()} for r in rows]}
    finally: db.close()

@app.get("/api/patients")
def get_patients(request: Request):
    actor = authenticate_request(request)
    require_roles(actor, PATIENT_DATA_STAFF_ROLES, "Patient directory is restricted to authorized clinical/administrative staff.")
    db = SessionLocal()
    try:
        query = db.query(User).filter(User.role == "patient").order_by(User.id)
        patients = query.all()
        if actor["role"] == "doctor":
            assigned_ids = {row[0] for row in db.query(Encounter.patient_id).filter(Encounter.doctor_id == actor["id"]).distinct().all()}
            patients = [p for p in patients if p.id in assigned_ids]

        result = []
        for p in patients:
            encounter_query = db.query(Encounter).filter(Encounter.patient_id == p.id)
            if actor["role"] == "doctor":
                encounter_query = encounter_query.filter(Encounter.doctor_id == actor["id"])
            encounter = encounter_query.order_by(Encounter.created_at.desc()).first()
            result.append({
                "id": p.id, "name": p.name, "email": p.email,
                "age": p.profile.age if p.profile else None,
                "gender": p.profile.gender if p.profile else "",
                "encounter_id": encounter.id if encounter else None,
            })
        return {"patients": result}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not user:
            raise HTTPException(status_code=404, detail="Patient not found.")
        return profile_response(user)
    finally:
        db.close()


@app.put("/api/patients/{patient_id}")
def update_patient(patient_id: int, payload: ProfileUpdate, request: Request):
    actor = authenticate_request(request)
    if actor["role"] != "patient" or actor["id"] != patient_id:
        raise HTTPException(status_code=403, detail="Only the patient can update their own profile.")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not user:
            raise HTTPException(status_code=404, detail="Patient not found.")
        user.name = payload.name.strip()
        p = user.profile
        if not p:
            p = PatientProfile(user_id=user.id)
            db.add(p)
        p.age, p.gender, p.phone = payload.age, payload.gender, payload.phone
        p.blood_group, p.allergies = payload.blood_group, payload.allergies
        p.conditions, p.medications, p.address = payload.conditions, payload.medications, payload.address
        db.commit()
        db.refresh(user)
        return {"message": "Profile updated successfully", "patient": profile_response(user)}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/consultations")
def get_consultations(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.id == patient_id, User.role == "patient").first():
            raise HTTPException(status_code=404, detail="Patient not found.")
        items = db.query(Consultation).filter(
            Consultation.patient_id == patient_id
        ).order_by(Consultation.created_at.desc()).all()
        result = []
        for i in items:
            structured = _json_loads(i.structured_data, {})
            consultation = structured.get("consultation", structured) if isinstance(structured, dict) else {}
            encounter = db.query(Encounter).filter(Encounter.id == i.encounter_id).first() if i.encounter_id else None
            doctor = db.query(User).filter(User.id == encounter.doctor_id).first() if encounter and encounter.doctor_id else None
            result.append({
                "id": i.id, "title": i.title, "summary": i.summary,
                "consultation_type": getattr(i, "consultation_type", None) or ("clinician" if i.title == "Clinical consultation" else "ayush" if i.title == "AYUSH / Ayurveda intake" else "handoff"),
                "status": i.status, "consultation_status": i.consultation_status or "draft",
                "risk_level": i.risk_level or "none",
                "red_flags": json.loads(i.red_flags) if i.red_flags else [],
                "doctor_name": doctor.name if doctor else None,
                "department": encounter.department if encounter else None,
                "encounter_id": i.encounter_id,
                "encounter_status": encounter.status if encounter else None,
                "visit_date": encounter.visit_date if encounter else None,
                "token_number": encounter.token_number if encounter else None,
                "sections": consultation if isinstance(consultation, dict) else {},
                "created_at": i.created_at.isoformat()
            })
        return {"consultations": result}
    finally:
        db.close()


# ---------- Phase 5B: Encounter + Queue workflow ----------
@app.get("/api/doctor/encounters/{encounter_id}/workspace")
def get_doctor_workspace(encounter_id: int, request: Request):
    """AI-5C: read-only clinician workspace assembled from persisted data and existing AI layers."""
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Doctor workspace is restricted to clinical staff.")
    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        authorize_encounter(actor, encounter)
        patient = db.query(User).filter(User.id == encounter.patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient.id, MedicalDocument.encounter_id == encounter.id).order_by(MedicalDocument.created_at.desc()).all()
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient.id, Consultation.encounter_id == encounter.id).order_by(Consultation.created_at.desc()).all()
        # Rebuild the clinician-facing handoff from the current persisted
        # interview so older cached summaries cannot leak generic multilingual
        # placeholders into the doctor workspace. The editable clinician record
        # created by Start Consultation is deliberately excluded: it is not the
        # patient history source.
        for consultation in consultations:
            consultation_type = getattr(consultation, "consultation_type", None) or ("clinician" if consultation.title == "Clinical consultation" else "ayush" if consultation.title == "AYUSH / Ayurveda intake" else "handoff")
            if consultation_type == "clinician":
                continue
            structured = _json_loads(consultation.structured_data, {})
            if structured.get("care_type", "allopathy") == "allopathy" and consultation.title != "AYUSH / Ayurveda intake":
                source_language = str(structured.get("language") or getattr(encounter, "language", None) or "en-IN")
                combined_source = " ".join(str(v) for v in structured.values() if v not in (None, "", [], {}))
                summary_nlu = extract_clinical_entities(combined_source, source_language) if combined_source else {}
                consultation.ai_summary = json.dumps(
                    generate_physician_summary(
                        structured, consultation.risk_level or "none",
                        _json_loads(consultation.red_flags, []), summary_nlu,
                        patient=patient, encounter=encounter, documents=[]
                    ), ensure_ascii=False
                )
                consultation.ai_summary_generated_at = utc_now()
        # Keep the doctor view scoped to the current encounter. AYUSH intake is
        # separately linked and shown as supporting handoff evidence.
        ayush_assessments = db.query(AyushAssessment).filter(AyushAssessment.patient_id == patient.id).order_by(AyushAssessment.created_at.desc()).all()
        timeline = build_timeline(consultations, documents)
        # Clinical consultation notes are clinician-authored documentation, not
        # a replacement for the patient-reported handoff. Keep them available
        # in the workspace, but build the patient story from handoff records.
        handoff_consultations = [c for c in consultations if (getattr(c, "consultation_type", None) or ("clinician" if c.title == "Clinical consultation" else "ayush" if c.title == "AYUSH / Ayurveda intake" else "handoff")) != "clinician"]
        summary = build_clinical_summary(patient, handoff_consultations, documents, timeline)
        risk = build_risk_assessment(patient, handoff_consultations, documents, summary)
        decision_support = build_decision_support(patient, handoff_consultations, documents, summary, risk)
        medication = build_medication_intelligence(patient, documents, handoff_consultations)
        investigations = build_investigation_intelligence(patient, documents)
        copilot = {}
        clinical_gate = {}
        if consultations:
            latest = consultations[0]
            copilot = build_consultation_copilot(patient, latest, documents, summary, risk, medication, investigations)
            clinical_gate = build_final_clinical_gate(patient, latest, summary, risk, decision_support, medication, investigations, copilot)
        workspace = build_doctor_workspace(patient, encounter, documents, consultations, summary, risk, decision_support, medication, investigations, copilot, clinical_gate, timeline, ayush_assessments)
        audit(db, actor["id"], actor["role"], "doctor_workspace_viewed", f"encounter:{encounter.id}")
        db.commit()
        return {"patient_id": patient.id, "encounter_id": encounter.id, "workspace": workspace}
    finally:
        db.close()


ALLOWED_CARE_TYPES = {"allopathy", "ayush"}

def normalize_care_type(value: str) -> str:
    normalized = (value or "allopathy").strip().lower()
    aliases = {"general": "allopathy", "general_doctor": "allopathy", "allopathy": "allopathy", "ayush": "ayush", "ayurveda": "ayush"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in ALLOWED_CARE_TYPES:
        raise ValueError("care_type must be allopathy or ayush.")
    return normalized

@app.post("/api/encounters")
def create_encounter(payload: EncounterCreateRequest, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.id == payload.patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        if actor["role"] == "patient" and actor["id"] != payload.patient_id:
            raise HTTPException(status_code=403, detail="Patients can create encounters only for themselves.")
        if actor["role"] not in ({"patient"} | ROLE_CAN_MANAGE_QUEUE):
            raise HTTPException(status_code=403, detail="Not authorized to create encounters.")
        # A doctor cannot create an encounter for an arbitrary patient or use
        # encounter creation as a way to grant themselves access. Assignment
        # of a new patient is an operational action for triage/admin; a doctor
        # may create only an encounter explicitly assigned to themselves for a
        # patient they already have a clinical relationship with.
        if actor["role"] == "doctor":
            if payload.doctor_id not in (None, actor["id"]):
                raise HTTPException(status_code=403, detail="Doctors can create encounters only for themselves.")
            if not doctor_has_patient_access(db, actor["id"], payload.patient_id):
                raise HTTPException(status_code=403, detail="This doctor is not assigned to this patient.")
        try:
            department = normalize_department(payload.department)
            priority = normalize_priority(payload.priority)
            care_type = normalize_care_type(payload.care_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if payload.doctor_id is not None:
            doctor = db.query(User).filter(User.id == payload.doctor_id, User.role == "doctor").first()
            if not doctor:
                raise HTTPException(status_code=404, detail="Doctor not found.")
        else:
            doctor = (db.query(User).join(DoctorProfile, DoctorProfile.user_id == User.id)
                      .filter(User.role == "doctor", DoctorProfile.active == 1, DoctorProfile.department == department)
                      .order_by(User.id).first())
            # Final prototype policy: every patient-facing department must have
            # exactly one active clinician. Never silently route a patient to a
            # doctor from another department.
            if doctor is None:
                raise HTTPException(status_code=503, detail="No clinician is configured for this department.")
        today = date.today().isoformat()
        active = db.query(Encounter).filter(Encounter.patient_id == payload.patient_id, Encounter.visit_date == today, Encounter.status.in_(["waiting", "called", "in_consultation"])).first()
        if active:
            raise HTTPException(status_code=409, detail="Patient already has an active encounter for today.")
        # SQLite serializes writes; the transaction prevents two committed tokens
        # from being generated from the same observed maximum.
        max_token = db.query(Encounter).filter(Encounter.visit_date == today, Encounter.department == department).order_by(Encounter.token_number.desc()).first()
        token = (max_token.token_number + 1) if max_token else 1
        assigned_doctor_id = doctor.id if doctor is not None else payload.doctor_id
        encounter = Encounter(patient_id=payload.patient_id, doctor_id=assigned_doctor_id, department=department, visit_date=today, token_number=token, priority=priority, status="waiting", reason=payload.reason.strip(), care_type=care_type)
        db.add(encounter)
        audit(db, actor["id"], actor["role"], "encounter_created", f"encounter:{payload.patient_id}")
        db.commit(); db.refresh(encounter)
        return {"message": "Encounter created", "encounter": serialize_encounter(encounter, patient, doctor)}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/active-encounter")
def get_active_patient_encounter(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db = SessionLocal()
    try:
        encounter = (db.query(Encounter)
                     .filter(Encounter.patient_id == patient_id, Encounter.status.in_(["waiting", "called", "in_consultation"]))
                     .order_by(Encounter.created_at.desc()).first())
        if not encounter:
            return {"encounter": None}
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        doctor = db.query(User).filter(User.id == encounter.doctor_id).first() if encounter.doctor_id else None
        return {"encounter": serialize_encounter(encounter, patient, doctor)}
    finally:
        db.close()

@app.put("/api/encounters/{encounter_id}/intake")
def update_encounter_intake(encounter_id: int, payload: EncounterIntakeUpdateRequest, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        if actor["role"] != "patient" or actor["id"] != encounter.patient_id:
            raise HTTPException(status_code=403, detail="Only the patient can update intake details for this encounter.")
        if encounter.status not in {"waiting", "called"}:
            raise HTTPException(status_code=409, detail="Intake can only be changed before consultation starts.")
        try:
            encounter.care_type = normalize_care_type(payload.care_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        encounter.reason = payload.reason.strip()[:500]
        db.commit(); db.refresh(encounter)
        patient = db.query(User).filter(User.id == encounter.patient_id).first()
        doctor = db.query(User).filter(User.id == encounter.doctor_id).first() if encounter.doctor_id else None
        return {"message": "Visit details updated", "encounter": serialize_encounter(encounter, patient, doctor)}
    finally:
        db.close()


@app.get("/api/encounters/{encounter_id}")
def get_encounter(encounter_id: int, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        authorize_encounter(actor, encounter)
        patient = db.query(User).filter(User.id == encounter.patient_id).first()
        doctor = db.query(User).filter(User.id == encounter.doctor_id).first() if encounter.doctor_id else None
        return {"encounter": serialize_encounter(encounter, patient, doctor)}
    finally:
        db.close()


@app.get("/api/queue")
def get_queue(request: Request, department: Optional[str] = None, visit_date: Optional[str] = None, status: str = "waiting,called,in_consultation"):
    actor = authenticate_request(request)
    if actor["role"] not in ROLE_CAN_MANAGE_QUEUE:
        raise HTTPException(status_code=403, detail="Queue access is restricted to clinical/administrative roles.")
    db = SessionLocal()
    try:
        try:
            if department:
                department = normalize_department(department)
            statuses = [normalize_status(x) for x in status.split(",") if x.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if not statuses:
            raise HTTPException(status_code=422, detail="At least one queue status is required.")
        target_date = visit_date or date.today().isoformat()
        query = db.query(Encounter).filter(
            Encounter.visit_date == target_date,
            Encounter.status.in_(statuses),
        )
        # A doctor's workspace is assignment-based, not department-query-based.
        # This matters when a hospital has not yet configured a dedicated doctor
        # for every patient-facing department.
        if actor["role"] == "doctor":
            query = query.filter(Encounter.doctor_id == actor["id"])
        elif department:
            query = query.filter(Encounter.department == department)
        rows = query.all()
        rows.sort(key=queue_sort_key)
        items=[]
        for e in rows:
            patient=db.query(User).filter(User.id==e.patient_id).first()
            doctor=db.query(User).filter(User.id==e.doctor_id).first() if e.doctor_id else None
            item=serialize_encounter(e, patient, doctor)
            item["queue_position"] = len(items)+1
            items.append(item)
        return {"department": department or "Assigned encounters", "visit_date": target_date, "count": len(items), "queue": items}
    finally:
        db.close()


@app.get("/api/encounters/{encounter_id}/eligible-doctors")
def eligible_doctors(encounter_id: int, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        authorize_encounter(actor, encounter)
        profiles = (db.query(User, DoctorProfile)
                    .join(DoctorProfile, DoctorProfile.user_id == User.id)
                    .filter(User.role == "doctor", DoctorProfile.active == 1, DoctorProfile.department == encounter.department)
                    .order_by(User.name.asc()).all())
        return {"doctors": [{"id": u.id, "name": u.name, "specialty": p.specialty, "department": p.department, "registration_number": p.registration_number or "", "room_number": p.room_number or "Not assigned", "active": bool(p.active)} for u,p in profiles]}
    finally:
        db.close()

class EncounterDoctorAssignmentRequest(BaseModel):
    doctor_id: int

@app.post("/api/encounters/{encounter_id}/assign-doctor")
def assign_encounter_doctor(encounter_id: int, payload: EncounterDoctorAssignmentRequest, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        if actor["role"] == "patient" and actor["id"] != encounter.patient_id:
            raise HTTPException(status_code=403, detail="You can only change your own encounter assignment.")
        if actor["role"] not in {"patient", "admin", "triage"}:
            raise HTTPException(status_code=403, detail="Doctors cannot reassign encounters from the patient queue.")
        if encounter.status not in {"waiting", "called"}:
            raise HTTPException(status_code=409, detail="Doctor selection is only available while the encounter is waiting or called.")
        doctor = (db.query(User, DoctorProfile).join(DoctorProfile, DoctorProfile.user_id == User.id)
                  .filter(User.id == payload.doctor_id, User.role == "doctor", DoctorProfile.active == 1, DoctorProfile.department == encounter.department).first())
        if not doctor:
            raise HTTPException(status_code=422, detail="That doctor is not eligible for this encounter.")
        encounter.doctor_id = doctor[0].id
        audit(db, actor["id"], actor["role"], "encounter_doctor_assigned", f"encounter:{encounter.id}:doctor:{doctor[0].id}")
        db.commit(); db.refresh(encounter)
        return {"message": "Doctor assignment updated", "encounter": serialize_encounter(encounter, db.query(User).filter(User.id == encounter.patient_id).first(), doctor[0]), "doctor": {"id": doctor[0].id, "name": doctor[0].name, "specialty": doctor[1].specialty, "department": doctor[1].department, "registration_number": doctor[1].registration_number or "", "room_number": doctor[1].room_number or "Not assigned"}}
    finally:
        db.close()

@app.post("/api/encounters/{encounter_id}/status")
def update_encounter_status(encounter_id: int, payload: EncounterStatusRequest, request: Request):
    actor = authenticate_request(request)
    if actor["role"] not in ROLE_CAN_MANAGE_QUEUE:
        raise HTTPException(status_code=403, detail="Only clinical/administrative staff can change queue status.")
    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        try:
            target = normalize_status(payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        # Resource authorization must happen before any state transition or
        # reassignment. A doctor may operate only on their own encounter.
        authorize_encounter(actor, encounter)
        if target == encounter.status:
            raise HTTPException(status_code=409, detail="Encounter is already in that status.")
        if not can_transition(encounter.status, target):
            raise HTTPException(status_code=409, detail=f"Invalid status transition: {encounter.status} -> {target}.")
        if target in {"in_consultation", "completed"} and actor["role"] not in {"doctor", "triage", "admin"}:
            raise HTTPException(status_code=403, detail="Not authorized for consultation status changes.")
        if payload.doctor_id is not None:
            if actor["role"] == "doctor" and payload.doctor_id != actor["id"]:
                raise HTTPException(status_code=403, detail="Doctors cannot reassign encounters to another doctor.")
            doctor = db.query(User).filter(User.id == payload.doctor_id, User.role == "doctor").first()
            if not doctor:
                raise HTTPException(status_code=404, detail="Doctor not found.")
            encounter.doctor_id = payload.doctor_id
        now = utc_now()
        encounter.status = target
        if target == "called":
            encounter.called_at = now
        if target == "completed":
            encounter.completed_at = now
        audit(db, actor["id"], actor["role"], "encounter_status_changed", f"encounter:{encounter.id}")
        db.commit(); db.refresh(encounter)
        patient=db.query(User).filter(User.id==encounter.patient_id).first()
        doctor=db.query(User).filter(User.id==encounter.doctor_id).first() if encounter.doctor_id else None
        return {"message":"Encounter status updated", "encounter":serialize_encounter(encounter, patient, doctor)}
    finally:
        db.close()


# ---------- Phase 4E: Medical document intelligence ----------
ALLOWED_DOC_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt"}
DOCUMENT_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
}

def _safe_original_filename(filename: str) -> str:
    """Return a display-only filename; never use user input as a filesystem path."""
    name = Path(filename or "document").name.replace("\x00", "")
    name = "".join(ch if ch.isprintable() and ch not in "\r\n\t" else "_" for ch in name)
    name = name.strip(" .") or "document"
    return name[:255]


def _sniff_document_type(data: bytes) -> str | None:
    """Detect the small set of supported document formats from file signatures."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    # Plain text has no reliable magic number. Reject NUL bytes and require UTF-8.
    if b"\x00" not in data:
        try:
            data.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    return None


def _validate_document_bytes(filename: str, declared_mime: str, data: bytes) -> tuple[str, str]:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_DOC_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported document type. Use PDF, PNG, JPG, JPEG, WEBP or TXT.")
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded document is empty.")
    if len(data) > MAX_DOCUMENT_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Document exceeds the {MAX_DOCUMENT_UPLOAD_BYTES // (1024 * 1024)} MB size limit.")
    expected = DOCUMENT_MIME_BY_EXT[ext]
    detected = _sniff_document_type(data)
    if detected != expected:
        raise HTTPException(status_code=415, detail="File contents do not match the declared document type.")
    if declared_mime and declared_mime != expected and not (expected == "text/plain" and declared_mime in {"text/plain", "application/octet-stream"}):
        raise HTTPException(status_code=415, detail="The uploaded MIME type does not match the file extension.")
    return ext, expected


def _atomic_private_write(target: Path, data: bytes) -> None:
    """Write clinical content atomically and avoid predictable/partial files."""
    fd, tmp_name = tempfile.mkstemp(prefix=".upload-", dir=str(target.parent))
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

DOCUMENT_TYPES = ["Prescription", "Lab Report", "Discharge Summary", "Imaging Report", "Other"]


def detect_document_type(filename: str, text: str, requested: str = "Other") -> str:
    if requested in DOCUMENT_TYPES and requested != "Other":
        return requested
    t = (filename + " " + text[:4000]).lower()
    if any(x in t for x in ["prescription", "rx", "tablet", "capsule", "dose", "mg"]): return "Prescription"
    if any(x in t for x in ["laboratory", "lab report", "haemoglobin", "hemoglobin", "glucose", "creatinine", "cbc"]): return "Lab Report"
    if any(x in t for x in ["discharge summary", "discharged", "admission", "hospital course"]): return "Discharge Summary"
    if any(x in t for x in ["x-ray", "xray", "ct scan", "mri", "ultrasound", "impression:"]): return "Imaging Report"
    return "Other"


def extract_document_text(path: Path, mime_type: str) -> str:
    ext = path.suffix.lower()
    if ext == ".txt":
        return path.read_text(errors="ignore")[:100000]
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)[:100000]
        except Exception:
            return ""
    if ext in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            import pytesseract
            from PIL import Image
            return pytesseract.image_to_string(Image.open(path))[:100000]
        except Exception:
            return ""
    return ""


def extract_medical_entities(text: str, document_type: str):
    raw = text or ""
    findings = []
    patterns = [
        ("Hemoglobin", r"(?:ha?emoglobin|hb)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:g/?dl)?"),
        ("Blood glucose", r"(?:blood glucose|glucose|blood sugar)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:mg/?dl)?"),
        ("Creatinine", r"creatinine\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:mg/?dl)?"),
        ("Blood pressure", r"(?:blood pressure|bp)\s*[:=]?\s*(\d{2,3}\s*/\s*\d{2,3})"),
        ("Temperature", r"(?:temperature|temp)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:°?c|f)?"),
        ("Pulse", r"(?:pulse|heart rate|hr)\s*[:=]?\s*(\d{2,3})\s*(?:bpm)?"),
    ]
    for label, pattern in patterns:
        m = re.search(pattern, raw, re.I)
        if m:
            findings.append({"type": "measurement", "label": label, "value": m.group(1).strip(), "source": "OCR/text extraction"})
    # Simple medication candidates from common prescription lines.
    for line in raw.splitlines():
        line=line.strip()
        if re.search(r"\b\d+\s*(?:mg|mcg|ml)\b", line, re.I) and len(line) < 180:
            findings.append({"type": "medication_candidate", "label": "Medication", "value": line, "source": "OCR/text extraction"})
    # Date candidates help create a timeline without inventing a date.
    dates = re.findall(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b", raw)
    if dates:
        findings.append({"type": "date", "label": "Document date", "value": dates[0], "source": "Text extraction"})
    return findings


@app.post("/api/documents/upload")
async def upload_document(patient_id: int = Form(...), document_type: str = Form("Other"), file: UploadFile = File(...), encounter_id: Optional[int] = Form(None), request: Request = None):
    actor = authenticate_request(request) if request is not None else None
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    authorize_patient(actor, patient_id)
    if actor["role"] != "patient":
        require_roles(actor, CLINICAL_ROLES, "Only patients or authorized clinical staff can upload documents.")
    if document_type not in DOCUMENT_TYPES:
        document_type = "Other"
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        if encounter_id is not None:
            encounter = db.query(Encounter).filter(Encounter.id == encounter_id, Encounter.patient_id == patient_id).first()
            if not encounter:
                raise HTTPException(status_code=404, detail="Encounter not found for this patient.")
            authorize_encounter(actor, encounter)
        original_name = _safe_original_filename(file.filename or "document")
        data = await file.read(MAX_DOCUMENT_UPLOAD_BYTES + 1)
        if len(data) > MAX_DOCUMENT_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Document exceeds the {MAX_DOCUMENT_UPLOAD_BYTES // (1024 * 1024)} MB size limit.")
        ext, canonical_mime = _validate_document_bytes(original_name, file.content_type or "", data)
        safe_name = f"{uuid.uuid4().hex}{ext}"
        target = UPLOAD_DIR / safe_name
        _atomic_private_write(target, data)
        text = extract_document_text(target, canonical_mime)
        classification = classify_document(text, original_name, document_type)
        # Preserve the old document_type contract while allowing AI-3C to correct
        # an inaccurate user-selected/legacy label when evidence is strong.
        dtype = classification.document_class if classification.document_class != "Other" else detect_document_type(original_name, text, document_type)
        extraction = extract_structured_medical_data(text, dtype)
        findings = extract_medical_entities(text, dtype)
        # Keep legacy findings for frontend compatibility and expose AI-3D structured items alongside them.
        findings = findings + extraction.get("items", [])
        status = "Processed" if text.strip() else "Uploaded — OCR unavailable or no readable text"
        doc = MedicalDocument(patient_id=patient_id, encounter_id=encounter_id, filename=original_name, document_type=dtype,
                              mime_type=canonical_mime, stored_path=str(target), extracted_text=text,
                              extracted_data=json.dumps(findings),
                              classification=classification.document_class,
                              classification_confidence=str(classification.confidence),
                              classification_method=classification.method,
                              classification_evidence=json.dumps(classification.evidence),
                              classification_needs_review=int(classification.needs_review),
                              structured_extraction=json.dumps(extraction),
                              extraction_needs_review=int(extraction.get("needs_review", True)),
                              extraction_method="AI-3D explainable local extractor",
                              verification_status="Pending",
                              status=status)
        db.add(doc); db.commit(); db.refresh(doc)
        return {"message":"Document processed", "document": {"id":doc.id,"filename":doc.filename,"document_type":doc.document_type,
                "status":doc.status,"encounter_id":doc.encounter_id,"created_at":doc.created_at.isoformat(),"findings":findings,
                "classification": {"document_class": classification.document_class, "confidence": classification.confidence,
                                   "confidence_semantics": classification.confidence_semantics,
                                   "needs_review": classification.needs_review, "method": classification.method,
                                   "evidence": classification.evidence, "scores": classification.scores},
                "extraction": extraction,
                "text_preview":(text[:1000] if text else "No text could be extracted. You can still keep the document for practitioner review.")}}
    finally:
        db.close()


class DocumentClassificationRequest(BaseModel):
    text: str = Field(default="", max_length=100000)
    filename: str = Field(default="document", max_length=255)
    requested_type: str = Field(default="Other", max_length=80)


@app.post("/api/documents/classify")
def classify_document_text(payload: DocumentClassificationRequest, request: Request):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Document classification is restricted to authorized clinical staff.")
    result = classify_document(payload.text, payload.filename, payload.requested_type)
    return {"classification": {
        "document_class": result.document_class, "confidence": result.confidence,
        "confidence_semantics": result.confidence_semantics,
        "needs_review": result.needs_review, "method": result.method,
        "evidence": result.evidence, "scores": result.scores
    }}


@app.post("/api/documents/{document_id}/classify")
def classify_stored_document(document_id: int, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_document(actor, doc, db, write=True)
        result = classify_document(doc.extracted_text or "", doc.filename or "document", doc.document_type or "Other")
        doc.classification = result.document_class
        doc.classification_confidence = str(result.confidence)
        doc.classification_method = result.method
        doc.classification_evidence = json.dumps(result.evidence)
        doc.classification_needs_review = int(result.needs_review)
        if result.document_class != "Other" and result.confidence >= 0.72:
            doc.document_type = result.document_class
        extraction = extract_structured_medical_data(doc.extracted_text or "", doc.document_type or result.document_class)
        doc.structured_extraction = json.dumps(extraction)
        doc.extraction_needs_review = int(extraction.get("needs_review", True))
        doc.extraction_method = "AI-3D explainable local extractor"
        db.commit()
        return {"message": "Document classified", "classification": {
            "document_class": result.document_class, "confidence": result.confidence,
            "needs_review": result.needs_review, "method": result.method,
            "evidence": result.evidence, "scores": result.scores
        }}
    finally:
        db.close()


class DocumentExtractionRequest(BaseModel):
    text: str = Field(default="", max_length=100000)
    document_type: str = Field(default="Other", max_length=80)


@app.post("/api/documents/extract")
def extract_document_text_data(payload: DocumentExtractionRequest, request: Request):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Document extraction is restricted to authorized clinical staff.")
    extraction = extract_structured_medical_data(payload.text, payload.document_type)
    return {"extraction": extraction}


@app.post("/api/documents/{document_id}/extract")
def extract_stored_document(document_id: int, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_document(actor, doc, db, write=True)
        extraction = extract_structured_medical_data(doc.extracted_text or "", doc.document_type or "Other")
        doc.structured_extraction = json.dumps(extraction)
        doc.extraction_needs_review = int(extraction.get("needs_review", True))
        doc.extraction_method = "AI-3D explainable local extractor"
        legacy = json.loads(doc.extracted_data or "[]")
        doc.extracted_data = json.dumps(legacy + extraction.get("items", []))
        db.commit()
        return {"message": "Document structured data extracted", "extraction": extraction}
    finally:
        db.close()


class DocumentVerificationRequest(BaseModel):
    verified_items: List[Dict[str, Any]] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)
    verified_by: Optional[int] = None


@app.get("/api/documents/{document_id}/verification")
def get_document_verification(document_id: int, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_document(actor, doc, db, write=False)
        extraction = json.loads(doc.structured_extraction or "{}")
        summary = build_verification_summary(extraction)
        return {
            "document_id": doc.id,
            "verification_status": doc.verification_status or "Pending",
            "summary": summary,
            "verified_data": json.loads(doc.verified_data or "null"),
            "verification_notes": doc.verification_notes or "",
            "verified_by": doc.verified_by,
            "verified_at": doc.verified_at.isoformat() if doc.verified_at else None,
        }
    finally:
        db.close()


@app.post("/api/documents/{document_id}/verify")
def verify_stored_document(document_id: int, payload: DocumentVerificationRequest, request: Request):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Only authorized clinical staff can verify medical documents.")
    db = SessionLocal()
    try:
        doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_document(actor, doc, db, write=True)
        extraction = json.loads(doc.structured_extraction or "{}")
        if not extraction:
            raise HTTPException(status_code=400, detail="No AI-3D extraction is available to verify.")
        try:
            verified = apply_document_verification(extraction, payload.verified_items)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        doc.verified_data = json.dumps(verified)
        doc.verification_notes = payload.notes.strip() or None
        doc.verified_by = actor["id"]
        doc.verified_at = utc_now()
        doc.verification_status = verified.get("verification_status", "Pending")
        db.commit()
        return {
            "message": "Document extraction verified",
            "document_id": doc.id,
            "verification_status": doc.verification_status,
            "verified_data": verified,
            "verification_notes": doc.verification_notes or "",
            "verified_by": doc.verified_by,
            "verified_at": doc.verified_at.isoformat(),
        }
    finally:
        db.close()


@app.get("/api/documents/{document_id}/explainability")
def get_document_explainability(document_id: int, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_document(actor, doc, db, write=False)
        return {"document_id": doc.id, "explainability": explain_document(doc)}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/timeline")
def get_patient_timeline(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient_id).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).all()
        timeline = build_timeline(consultations, documents)
        return {"patient_id": patient_id, "timeline": timeline}
    finally:
        db.close()


@app.get("/api/documents/{document_id}/timeline-context")
def get_document_timeline_context(document_id: int, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_document(actor, doc, db, write=False)
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == doc.patient_id).all()
        consultations = db.query(Consultation).filter(Consultation.patient_id == doc.patient_id).all()
        timeline = build_timeline(consultations, documents)
        return {"document_id": document_id, "patient_id": doc.patient_id, "timeline": timeline, "explainability": explain_timeline(timeline)}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/clinical-summary")
def get_clinical_summary(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    """AI-4A: consolidated clinician-facing summary from stored, traceable data."""
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient_id).order_by(Consultation.created_at.desc()).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.created_at.desc()).all()
        timeline = build_timeline(consultations, documents)
        return {"patient_id": patient_id, "clinical_summary": build_clinical_summary(patient, consultations, documents, timeline)}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/risk-assessment")
def get_ai4b_risk_assessment(patient_id: int, request: Request):
    """AI-4B: clinician-facing conservative risk/red-flag assessment."""
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Clinical risk assessment is restricted to clinical staff.")
    db = SessionLocal()
    try:
        authorize_patient(actor, patient_id, db=db)
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient_id).order_by(Consultation.created_at.desc()).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.created_at.desc()).all()
        timeline = build_timeline(consultations, documents)
        summary = build_clinical_summary(patient, consultations, documents, timeline)
        return {"patient_id": patient_id, "risk_assessment": build_risk_assessment(patient, consultations, documents, summary)}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/decision-support")
def get_ai4c_decision_support(patient_id: int, request: Request):
    """AI-4C: conservative clinician decision-support prompts and record checks."""
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Decision support is restricted to clinical staff.")
    db = SessionLocal()
    try:
        authorize_patient(actor, patient_id, db=db)
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient_id).order_by(Consultation.created_at.desc()).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.created_at.desc()).all()
        timeline = build_timeline(consultations, documents)
        summary = build_clinical_summary(patient, consultations, documents, timeline)
        risk = build_risk_assessment(patient, consultations, documents, summary)
        support = build_decision_support(patient, consultations, documents, summary, risk)
        return {"patient_id": patient_id, "decision_support": support}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/medication-intelligence")
def get_medication_reconciliation(patient_id: int, request: Request):
    """AI-4D: conservative medication reconciliation for clinical staff."""
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Medication intelligence is restricted to clinical staff.")
    db = SessionLocal()
    try:
        authorize_patient(actor, patient_id, db=db)
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient_id).order_by(Consultation.created_at.desc()).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.created_at.desc()).all()
        return {"patient_id": patient_id, "medication_intelligence": build_medication_intelligence(patient, documents, consultations)}
    finally:
        db.close()


@app.get("/api/doctor/consultations/{consultation_id}/copilot")
def get_consultation_copilot(consultation_id: int, request: Request):
    """AI-4G: clinician-only consultation copilot; read-only draft assistance."""
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Consultation copilot is restricted to clinical staff.")
    db = SessionLocal()
    try:
        consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
        if not consultation:
            raise HTTPException(status_code=404, detail="Consultation not found.")
        authorize_consultation(actor, consultation, db)
        patient = db.query(User).filter(User.id == consultation.patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient.id).order_by(Consultation.created_at.desc()).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient.id).order_by(MedicalDocument.created_at.desc()).all()
        timeline = build_timeline(consultations, documents)
        summary = build_clinical_summary(patient, consultations, documents, timeline)
        risk = build_risk_assessment(patient, consultations, documents, summary)
        medication = build_medication_intelligence(patient, documents, consultations)
        investigations = build_investigation_intelligence(patient, documents)
        copilot = build_consultation_copilot(patient, consultation, documents, summary, risk, medication, investigations)
        return {"patient_id": patient.id, "consultation_id": consultation.id, "consultation_copilot": copilot}
    finally:
        db.close()


@app.post("/api/patients/{patient_id}/clinical-question")
def post_ai4f_clinical_question(patient_id: int, payload: ClinicalQuestionRequest, request: Request):
    """AI-4F: source-grounded clinical question answering for clinical staff."""
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Clinical question assistant is restricted to clinical staff.")
    db = SessionLocal()
    try:
        authorize_patient(actor, patient_id, db=db)
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient_id).order_by(Consultation.created_at.desc()).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.created_at.desc()).all()
        return {"patient_id": patient_id, "clinical_question": answer_clinical_question(patient, consultations, documents, payload.question)}
    finally:
        db.close()


@app.get("/api/doctor/consultations/{consultation_id}/clinical-gate")
def get_ai4h_clinical_gate(consultation_id: int, request: Request):
    """AI-4H: final clinician-facing safety/readiness gate; read-only."""
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Final clinical gate is restricted to clinical staff.")
    db = SessionLocal()
    try:
        consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
        if not consultation:
            raise HTTPException(status_code=404, detail="Consultation not found.")
        authorize_consultation(actor, consultation, db)
        patient = db.query(User).filter(User.id == consultation.patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient.id).order_by(Consultation.created_at.desc()).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient.id).order_by(MedicalDocument.created_at.desc()).all()
        timeline = build_timeline(consultations, documents)
        summary = build_clinical_summary(patient, consultations, documents, timeline)
        risk = build_risk_assessment(patient, consultations, documents, summary)
        support = build_decision_support(patient, consultations, documents, summary, risk)
        medication = build_medication_intelligence(patient, documents, consultations)
        investigations = build_investigation_intelligence(patient, documents)
        copilot = build_consultation_copilot(patient, consultation, documents, summary, risk, medication, investigations)
        gate = build_final_clinical_gate(patient, consultation, summary, risk, support, medication, investigations, copilot)
        return {"patient_id": patient.id, "consultation_id": consultation.id, "clinical_gate": gate}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/investigation-intelligence")
def get_investigation_intelligence(patient_id: int, request: Request):
    """AI-4E: conservative longitudinal investigation intelligence for clinical staff."""
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Investigation intelligence is restricted to clinical staff.")
    db = SessionLocal()
    try:
        authorize_patient(actor, patient_id, db=db)
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.created_at.asc()).all()
        return {"patient_id": patient_id, "investigation_intelligence": build_investigation_intelligence(patient, documents)}
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/clinical-handoff")
def get_patient_clinical_handoff(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        consultations = db.query(Consultation).filter(Consultation.patient_id == patient_id).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).all()
        return {"patient_id": patient_id, "clinical_handoff": build_clinical_handoff(patient_id, consultations, documents)}
    finally:
        db.close()


@app.get("/api/documents/{document_id}/clinical-handoff")
def get_document_clinical_handoff(document_id: int, request: Request):
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_document(actor, doc, db, write=False)
        consultations = db.query(Consultation).filter(Consultation.patient_id == doc.patient_id).all()
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == doc.patient_id).all()
        return {"document_id": document_id, "patient_id": doc.patient_id, "clinical_handoff": build_clinical_handoff(doc.patient_id, consultations, documents)}
    finally:
        db.close()


@app.get("/api/documents/{document_id}/content")
def get_document_content(document_id: int, request: Request):
    """Return the original stored medical document after resource authorization."""
    actor = authenticate_request(request)
    db = SessionLocal()
    try:
        doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_document(actor, doc, db, write=False)
        if not doc.stored_path:
            raise HTTPException(status_code=404, detail="This document has no stored file.")
        raw_path = Path(doc.stored_path)
        if raw_path.is_absolute():
            path = raw_path.resolve()
            # Demo bundles may have been extracted to a different machine/path.
            # If the recorded absolute path is stale, resolve the same safe file
            # name inside the application's private upload directory.
            if not path.is_file():
                candidate = (UPLOAD_DIR / raw_path.name).resolve()
                if candidate.is_file():
                    path = candidate
        else:
            path = (UPLOAD_DIR / raw_path).resolve()
        try:
            path.relative_to(UPLOAD_DIR)
        except ValueError:
            raise HTTPException(status_code=404, detail="Stored document is unavailable.")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Stored document is unavailable.")
        media_type = doc.mime_type or "application/octet-stream"
        return FileResponse(path=str(path), media_type=media_type, filename=doc.filename)
    finally:
        db.close()


@app.get("/api/patients/{patient_id}/documents")
def get_patient_documents(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db=SessionLocal()
    try:
        if not db.query(User).filter(User.id==patient_id, User.role=="patient").first(): raise HTTPException(status_code=404, detail="Patient not found.")
        docs=db.query(MedicalDocument).filter(MedicalDocument.patient_id==patient_id).order_by(MedicalDocument.created_at.desc()).all()
        return {"documents":[{"id":d.id,"filename":d.filename,"document_type":d.document_type,"encounter_id":d.encounter_id,"status":d.status,"mime_type":d.mime_type,
                "created_at":d.created_at.isoformat(),"findings":json.loads(d.extracted_data or "[]"),
                "classification":{"document_class":d.classification or d.document_type,"confidence":float(d.classification_confidence or 0),"confidence_semantics":confidence_semantics("document_classification_score"),"needs_review":bool(d.classification_needs_review),"method":d.classification_method,"evidence":json.loads(d.classification_evidence or "[]")},"extraction":json.loads(d.structured_extraction or "{}"),"verification":{"status":d.verification_status or "Pending","verified_data":json.loads(d.verified_data or "null"),"notes":d.verification_notes or "","verified_by":d.verified_by,"verified_at":d.verified_at.isoformat() if d.verified_at else None},
                "text_preview":(d.extracted_text or "")[:800]} for d in docs]}
    finally: db.close()


@app.get("/api/doctor/patients/{patient_id}/workspace")
def doctor_patient_workspace(patient_id: int, request: Request, encounter_id: Optional[int] = None):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Doctor workspace is restricted to authorized clinical staff.")
    db=SessionLocal()
    try:
        authorize_patient(actor, patient_id, db=db)
        patient=db.query(User).filter(User.id==patient_id,User.role=="patient").first()
        if not patient: raise HTTPException(status_code=404, detail="Patient not found.")

        if encounter_id is not None:
            encounter = db.query(Encounter).filter(Encounter.id == encounter_id, Encounter.patient_id == patient_id).first()
            if not encounter:
                raise HTTPException(status_code=404, detail="Encounter not found for this patient.")
            authorize_encounter(actor, encounter)
        else:
            encounter_query = db.query(Encounter).filter(Encounter.patient_id == patient_id)
            if actor["role"] == "doctor":
                encounter_query = encounter_query.filter(Encounter.doctor_id == actor["id"])
            encounter = encounter_query.order_by(Encounter.created_at.desc()).first()
            if not encounter:
                raise HTTPException(status_code=409, detail="No encounter is available for this patient.")
            authorize_encounter(actor, encounter)

        # The physician workspace is encounter-scoped. This prevents a doctor
        # from opening a patient's unrelated consultation history from another
        # visit/doctor while still preserving the existing patient-level API.
        consultations=db.query(Consultation).filter(Consultation.patient_id==patient_id, Consultation.encounter_id==encounter.id).order_by(Consultation.created_at.desc()).all()
        docs=db.query(MedicalDocument).filter(MedicalDocument.patient_id==patient_id, MedicalDocument.encounter_id==encounter.id).order_by(MedicalDocument.created_at.desc()).all()
        timeline=[]
        for c in consultations:
            timeline.append({"date":c.created_at.isoformat(),"type":"Consultation","title":c.title,"detail":c.summary,"risk_level":c.risk_level or "none"})
        for d in docs:
            timeline.append({"date":d.created_at.isoformat(),"type":"Document","title":d.filename,"detail":d.document_type,"risk_level":"none"})
        timeline.sort(key=lambda x:x["date"], reverse=True)
        return {"patient":profile_response(patient),
                "encounter": {"id": encounter.id, "department": encounter.department, "language": getattr(encounter, "language", None) or "en-IN", "visit_date": encounter.visit_date, "token_number": encounter.token_number, "priority": encounter.priority, "status": encounter.status, "reason": encounter.reason or "", "care_type": encounter.care_type or "allopathy", "doctor_id": encounter.doctor_id},
                "consultations":[{"id":c.id,"encounter_id":c.encounter_id,"title":c.title,"summary":c.summary,"status":c.status,"risk_level":c.risk_level or "none",
                  "red_flags":_json_loads(c.red_flags, []),"doctor_review":c.doctor_review or "Pending","doctor_notes":c.doctor_notes or "","ai_summary":_json_loads(c.ai_summary, None),"ai_summary_generated_at":c.ai_summary_generated_at.isoformat() if c.ai_summary_generated_at else None,"structured":_json_loads(c.structured_data, {}),"nlp":_json_loads(c.nlp_data, {}),"created_at":c.created_at.isoformat()} for c in consultations],
                "documents":[{"id":d.id,"filename":d.filename,"document_type":d.document_type,"encounter_id":d.encounter_id,"status":d.status,"mime_type":d.mime_type,"created_at":d.created_at.isoformat(),"findings":json.loads(d.extracted_data or "[]"),"classification":{"document_class":d.classification or d.document_type,"confidence":float(d.classification_confidence or 0),"confidence_semantics":confidence_semantics("document_classification_score"),"needs_review":bool(d.classification_needs_review),"method":d.classification_method,"evidence":json.loads(d.classification_evidence or "[]")},"extraction":json.loads(d.structured_extraction or "{}"),"text_preview":(d.extracted_text or "")[:1200]} for d in docs],
                "timeline":timeline}
    finally: db.close()


class DoctorReviewUpdate(BaseModel):
    doctor_review: str = "Reviewed"
    doctor_notes: str = ""


@app.put("/api/doctor/consultations/{consultation_id}/review")
def review_consultation(consultation_id: int, payload: DoctorReviewUpdate, request: Request):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Only authorized clinical staff can review consultations.")
    db=SessionLocal()
    try:
        c=db.query(Consultation).filter(Consultation.id==consultation_id).first()
        if not c: raise HTTPException(status_code=404, detail="Consultation not found.")
        authorize_consultation(actor, c, db)
        c.doctor_review=payload.doctor_review[:40]
        c.doctor_notes=payload.doctor_notes[:5000]
        db.commit(); db.refresh(c)
        return {"message":"Doctor review saved","consultation_id":c.id,"doctor_review":c.doctor_review,"doctor_notes":c.doctor_notes}
    finally: db.close()


# ---------- Phase 5E: triage dashboard and human-controlled actions ----------
@app.get("/api/triage/dashboard")
def get_clinical_triage_workflow_dashboard(request: Request, department: str = "General Medicine", visit_date: Optional[str] = None):
    """AI-5E: operational triage view with AI-4B signals surfaced for human review."""
    actor = authenticate_request(request)
    if actor["role"] not in TRIAGE_ROLES:
        raise HTTPException(status_code=403, detail="Triage dashboard is restricted to clinical/administrative roles.")
    db = SessionLocal()
    try:
        try:
            department = normalize_department(department)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        target_date = visit_date or date.today().isoformat()
        rows = db.query(Encounter).filter(
            Encounter.department == department,
            Encounter.visit_date == target_date,
            Encounter.status.in_(["waiting", "called", "in_consultation"]),
        ).all()
        items = []
        for encounter in rows:
            patient = db.query(User).filter(User.id == encounter.patient_id, User.role == "patient").first()
            if not patient:
                continue
            doctor = db.query(User).filter(User.id == encounter.doctor_id).first() if encounter.doctor_id else None
            consultations = db.query(Consultation).filter(Consultation.patient_id == patient.id).order_by(Consultation.created_at.desc()).all()
            documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient.id).order_by(MedicalDocument.created_at.desc()).all()
            timeline = build_timeline(consultations, documents)
            summary = build_clinical_summary(patient, consultations, documents, timeline)
            risk = build_risk_assessment(patient, consultations, documents, summary)
            items.append(serialize_triage_item(encounter, patient, doctor, risk))
        return {"patient_scope": "current operational queue", "triage_dashboard": build_triage_dashboard(items, department, target_date)}
    finally:
        db.close()


@app.post("/api/triage/encounters/{encounter_id}/action")
def act_on_clinical_triage_workflow(encounter_id: int, payload: TriageActionRequest, request: Request):
    """AI-5E: acknowledgement/escalation/resolution is always a human action."""
    actor = authenticate_request(request)
    if actor["role"] not in TRIAGE_ROLES:
        raise HTTPException(status_code=403, detail="Only triage/clinical administrative staff can act on triage items.")
    try:
        action = normalize_triage_action(payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        if encounter.status in {"completed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Completed or cancelled encounters cannot be triaged.")
        if payload.priority is not None:
            try:
                encounter.priority = normalize_priority(payload.priority)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        target = triage_action_status(action)
        encounter.triage_status = target
        encounter.triage_notes = payload.notes.strip()
        encounter.triage_updated_by = actor["id"]
        encounter.triage_updated_at = utc_now()
        audit(db, actor["id"], actor["role"], f"triage_{action}", f"encounter:{encounter.id}")
        db.commit(); db.refresh(encounter)
        patient = db.query(User).filter(User.id == encounter.patient_id).first()
        doctor = db.query(User).filter(User.id == encounter.doctor_id).first() if encounter.doctor_id else None
        return {
            "message": f"Triage action '{action}' recorded",
            "encounter_id": encounter.id,
            "triage_status": encounter.triage_status,
            "priority": encounter.priority,
            "triage_notes": encounter.triage_notes or "",
            "human_action": True,
            "actor_role": actor["role"],
            "encounter": serialize_encounter(encounter, patient, doctor),
        }
    finally:
        db.close()


# ---------- Phase 5D: clinician-owned consultation workflow ----------
@app.post("/api/doctor/encounters/{encounter_id}/consultation")
def start_consultation_workflow(encounter_id: int, payload: ConsultationStartRequest, request: Request):
    actor = authenticate_request(request)
    if actor["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can start a consultation.")
    if payload.encounter_id != encounter_id:
        raise HTTPException(status_code=400, detail="Encounter ID mismatch.")
    db = SessionLocal()
    try:
        encounter = db.query(Encounter).filter(Encounter.id == encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=404, detail="Encounter not found.")
        # A consultation inherits the encounter's ownership. Authorize the
        # selected encounter before checking workflow state so a doctor cannot
        # probe another doctor's encounter by observing its status.
        authorize_encounter(actor, encounter)
        if encounter.status not in {"called", "in_consultation"}:
            raise HTTPException(status_code=409, detail="Encounter must be called or in consultation before starting.")
        if encounter.status == "called":
            encounter.status = "in_consultation"
            encounter.called_at = encounter.called_at or utc_now()

        # Patient history and optional AYUSH are handoff records, not the
        # physician's editable consultation record. Only resume a consultation
        # explicitly created for clinician documentation.
        existing = (db.query(Consultation)
                    .filter(Consultation.encounter_id == encounter_id)
                    .filter((Consultation.consultation_type == "clinician") | (Consultation.consultation_type.is_(None) & (Consultation.title == "Clinical consultation")))
                    .order_by(Consultation.created_at.desc()).first())
        if existing and (existing.consultation_status or "draft") != "completed":
            return {"consultation": build_consultation_payload(existing, encounter), "created": False}

        record = Consultation(
            patient_id=encounter.patient_id,
            encounter_id=encounter.id,
            title=payload.title.strip() or "Clinical consultation",
            consultation_type="clinician",
            summary="Consultation draft.",
            status="In Consultation",
            consultation_status="in_progress",
            doctor_review="Pending",
            structured_data=json.dumps({"consultation": {}}, ensure_ascii=False),
            updated_at=utc_now(),
        )
        db.add(record)
        audit(db, actor["id"], actor["role"], "consultation_started", f"encounter:{encounter.id}")
        db.commit(); db.refresh(record)
        return {"consultation": build_consultation_payload(record, encounter), "created": True}
    finally:
        db.close()


@app.get("/api/doctor/consultations/{consultation_id}/record")
def get_consultation_workflow(consultation_id: int, request: Request):
    actor = authenticate_request(request)
    if actor["role"] not in {"doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Consultation record is restricted to clinical staff.")
    db = SessionLocal()
    try:
        record = db.query(Consultation).filter(Consultation.id == consultation_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Consultation not found.")
        authorize_consultation(actor, record, db)
        encounter = db.query(Encounter).filter(Encounter.id == record.encounter_id).first() if record.encounter_id else None
        return {"consultation": build_consultation_payload(record, encounter)}
    finally:
        db.close()


@app.put("/api/doctor/consultations/{consultation_id}/record")
def update_consultation_workflow(consultation_id: int, payload: ConsultationUpdateRequest, request: Request):
    actor = authenticate_request(request)
    if actor["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can edit consultation records.")
    db = SessionLocal()
    try:
        record = db.query(Consultation).filter(Consultation.id == consultation_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Consultation not found.")
        if record.consultation_status == "completed":
            raise HTTPException(status_code=409, detail="Completed consultations are locked for this prototype.")
        if not record.encounter_id:
            raise HTTPException(status_code=403, detail="This consultation is not linked to an assigned encounter.")
        encounter = db.query(Encounter).filter(Encounter.id == record.encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=403, detail="This consultation is linked to an unavailable encounter.")
        authorize_encounter(actor, encounter)
        authorize_consultation(actor, record, db)
        try:
            sections = normalize_sections(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        record.structured_data = json.dumps({"consultation": sections}, ensure_ascii=False)
        record.summary = consultation_summary(sections)
        record.doctor_notes = payload.doctor_notes
        record.status = "In Consultation"
        record.consultation_status = "in_progress"
        record.updated_at = utc_now()
        audit(db, actor["id"], actor["role"], "consultation_draft_saved", f"consultation:{record.id}")
        db.commit(); db.refresh(record)
        return {"message": "Consultation draft saved", "consultation": build_consultation_payload(record, encounter)}
    finally:
        db.close()


@app.post("/api/doctor/consultations/{consultation_id}/complete")
def complete_consultation_workflow(consultation_id: int, payload: ConsultationCompleteRequest, request: Request):
    actor = authenticate_request(request)
    if actor["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can complete a consultation.")
    db = SessionLocal()
    try:
        record = db.query(Consultation).filter(Consultation.id == consultation_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Consultation not found.")
        if record.consultation_status == "completed":
            raise HTTPException(status_code=409, detail="Consultation is already completed.")
        if not record.encounter_id:
            raise HTTPException(status_code=403, detail="This consultation is not linked to an assigned encounter.")
        encounter = db.query(Encounter).filter(Encounter.id == record.encounter_id).first()
        if not encounter:
            raise HTTPException(status_code=403, detail="This consultation is linked to an unavailable encounter.")
        authorize_encounter(actor, encounter)
        authorize_consultation(actor, record, db)
        try:
            sections = normalize_sections(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        # Completing a consultation is a clinician action. We store exactly what
        # the doctor submitted; nothing here derives a diagnosis or treatment.
        record.structured_data = json.dumps({"consultation": sections}, ensure_ascii=False)
        record.summary = consultation_summary(sections)
        record.doctor_notes = payload.doctor_notes
        record.doctor_review = payload.doctor_review[:40]
        record.status = "Completed"
        record.consultation_status = "completed"
        record.updated_at = utc_now()
        if encounter:
            if encounter.status == "in_consultation":
                encounter.status = "completed"
            encounter.completed_at = encounter.completed_at or utc_now()
        audit(db, actor["id"], actor["role"], "consultation_completed", f"consultation:{record.id}")
        db.commit(); db.refresh(record)
        return {
            "message": "Consultation completed",
            "consultation": build_consultation_payload(record, encounter),
            "clinical_decision_source": "doctor_entered",
        }
    finally:
        db.close()


# ---------- Phase 5A AYUSH / Ayurveda assessment ----------
AYUSH_DASHAVIDHA = [
    {"id":"prakriti","title":"Prakriti (constitution)","question":"What is your usual body and temperament pattern? If known, describe your predominant constitution (Vata, Pitta, Kapha or combination).","hint":"Self-reported or practitioner-informed; do not force a constitution if unknown.","type":"single","options":["Vata","Pitta","Kapha","Vata-Pitta","Pitta-Kapha","Vata-Kapha","Tridoshic / balanced","Not sure"]},
    {"id":"vikriti","title":"Vikriti (current imbalance)","question":"Compared with your usual state, what has changed recently? Select the patterns you notice most.","hint":"This records the patient's reported current state; it is not an AI diagnosis.","type":"multi","options":["Dryness / irregularity","Heat / acidity","Heaviness / congestion","Sleep disturbance","Appetite change","Bowel change","Stress / restlessness","No major change","Not sure"]},
    {"id":"sara","title":"Sara (tissue quality)","question":"How would you describe the general strength and quality of your body tissues, as far as you know?","hint":"For prototype intake only; clinician assessment may be needed.","type":"single","options":["Strong / well nourished","Average","Low / easily fatigued","Not sure"]},
    {"id":"samhanana","title":"Samhanana (body build)","question":"How would you describe your overall body build and physical development?","hint":"Choose the closest self-description.","type":"single","options":["Well proportioned / strong","Average build","Thin / delicate","Heavy / broad","Not sure"]},
    {"id":"pramana","title":"Pramana (body measurements)","question":"Do you have recent height, weight, waist measurement or other body measurements you would like to record?","hint":"Use known measurements where available.","type":"measurements","units":{"height":"cm","weight":"kg"},"min":{"height":50,"weight":10},"max":{"height":250,"weight":300},"step":{"height":1,"weight":0.5}},
    {"id":"satmya","title":"Satmya (adaptability / suitability)","question":"Which foods, routines, climate or daily habits generally suit you well, and which tend to cause discomfort?","hint":"Select all patterns that match your usual tolerance and preferences.","type":"multi","options":["Most foods suit me","Spicy or acidic foods cause discomfort","Heavy foods cause discomfort","Regular routines suit me","Irregular routines cause discomfort","Hot weather causes discomfort","Cold weather causes discomfort","Not sure"]},
    {"id":"satva","title":"Satva (mental resilience)","question":"How would you describe your usual mental resilience and ability to cope with stress?","hint":"This is a self-reported wellbeing context, not a psychiatric assessment.","type":"single","options":["Generally resilient","Usually okay with some stress","Often overwhelmed","Prefer not to say"]},
    {"id":"ahara_shakti","title":"Ahara Shakti (digestive / food capacity)","question":"How is your appetite and digestion generally?","hint":"Consider appetite, meal tolerance and digestive comfort.","type":"single","options":["Good and regular","Variable","Low appetite","Heavy / slow digestion","Not sure"]},
    {"id":"vyayama_shakti","title":"Vyayama Shakti (exercise capacity)","question":"How much physical activity can you comfortably do in your usual day?","hint":"Choose your usual capacity, not your best day.","type":"single","options":["High","Moderate","Low","Very low / easily fatigued","Not sure"]},
    {"id":"vaya","title":"Vaya (age / life stage)","question":"Your age is already available in your patient profile. Which life stage best describes you?","hint":"Choose the closest life stage. Your recorded age remains part of your patient profile.","type":"single","options":["Childhood","Adolescence","Young adulthood","Middle adulthood","Older adulthood","Prefer not to say"]},
]

AYUSH_INTRO = "Welcome to the AYUSH / Ayurveda intake. This guided module records Dashavidha Pariksha-related information for practitioner review. It does not diagnose or determine a dosha on its own."
AYUSH_HI = {
 "prakriti":("प्रकृति (constitution)","आपके शरीर और स्वभाव का सामान्य पैटर्न कैसा है? यदि आपको पता हो, तो अपनी प्रमुख प्रकृति बताएं (वात, पित्त, कफ या मिश्रित)।"),
 "vikriti":("विकृति (वर्तमान असंतुलन)","आपकी सामान्य स्थिति की तुलना में हाल में क्या बदलाव आया है? जो पैटर्न महसूस हों उन्हें चुनें।"),
 "sara":("सार (धातु/ऊतक गुणवत्ता)","जहाँ तक आपको पता हो, अपने शरीर की सामान्य ताकत और पोषण की स्थिति कैसी है?"),
 "samhanana":("संहनन (शारीरिक बनावट)","आप अपनी सामान्य शारीरिक बनावट और विकास का वर्णन कैसे करेंगे?"),
 "pramana":("प्रमाण (शारीरिक माप)","क्या आपके पास हाल का कद, वजन, कमर का माप या अन्य शारीरिक माप हैं जिन्हें दर्ज करना चाहेंगे?"),
 "satmya":("सात्म्य (अनुकूलता)","कौन से भोजन, दिनचर्या, मौसम या आदतें आपको सामान्यतः अनुकूल रहती हैं और किनसे परेशानी होती है?"),
 "satva":("सत्त्व (मानसिक दृढ़ता)","तनाव से निपटने और मानसिक रूप से संभलने की आपकी सामान्य क्षमता कैसी है?"),
 "ahara_shakti":("आहार शक्ति (भोजन/पाचन क्षमता)","आपकी भूख और पाचन सामान्यतः कैसा रहता है?"),
 "vyayama_shakti":("व्यायाम शक्ति (शारीरिक क्षमता)","आप अपनी सामान्य दिनचर्या में कितनी शारीरिक गतिविधि आराम से कर सकते हैं?"),
 "vaya":("वय (आयु/जीवन अवस्था)","आपकी आयु क्या है और यदि चाहें तो कौन-सी जीवन अवस्था आपको सबसे अधिक उपयुक्त लगती है?"),
}

AYUSH_TRANSLATIONS = {
 "hi-IN": {
  "prakriti": ("प्रकृति (constitution)", "आपके शरीर और स्वभाव का सामान्य पैटर्न कैसा है? यदि आपको पता हो, तो अपनी प्रमुख प्रकृति बताएं (वात, पित्त, कफ या मिश्रित)।", "यदि पता न हो तो 'पता नहीं' चुनें।", ["वात","पित्त","कफ","वात-पित्त","पित्त-कफ","वात-कफ","त्रिदोषिक / संतुलित","पता नहीं"]),
  "vikriti": ("विकृति (वर्तमान बदलाव)", "आपकी सामान्य स्थिति की तुलना में हाल में क्या बदलाव आया है? जो पैटर्न महसूस हों उन्हें चुनें।", "जो बातें आपको सच लगती हैं उन्हें चुनें।", ["रूखापन / अनियमितता","गर्मी / अम्लता","भारीपन / जकड़न","नींद में बदलाव","भूख में बदलाव","मल त्याग में बदलाव","तनाव / बेचैनी","कोई बड़ा बदलाव नहीं","पता नहीं"]),
  "sara": ("सार (ऊतक गुणवत्ता)", "जहाँ तक आपको पता हो, अपने शरीर की सामान्य ताकत और पोषण की स्थिति कैसी है?", "यह केवल आपकी बताई हुई जानकारी है।", ["मजबूत / अच्छी तरह पोषित","सामान्य","कमज़ोर / जल्दी थकने वाला","पता नहीं"]),
  "samhanana": ("संहनन (शारीरिक बनावट)", "आप अपनी सामान्य शारीरिक बनावट और विकास का वर्णन कैसे करेंगे?", "सबसे करीब वाला विकल्प चुनें।", ["अच्छी बनावट / मजबूत","सामान्य बनावट","पतली / नाज़ुक","भारी / चौड़ी","पता नहीं"]),
  "pramana": ("प्रमाण (शारीरिक माप)", "क्या आपके पास हाल का कद, वजन, कमर का माप या अन्य शारीरिक माप हैं जिन्हें दर्ज करना चाहेंगे?", "जो माप पता हों, लिखें।", None),
  "satmya": ("सात्म्य (अनुकूलता)", "कौन से भोजन, दिनचर्या, मौसम या आदतें आपको सामान्यतः अनुकूल रहती हैं और किनसे परेशानी होती है?", "जो बातें आपके सामान्य अनुभव से मेल खाती हैं उन्हें चुनें।", ["अधिकांश भोजन अनुकूल हैं","तीखा या खट्टा भोजन परेशानी करता है","भारी भोजन परेशानी करता है","नियमित दिनचर्या अनुकूल है","अनियमित दिनचर्या परेशानी करती है","गर्म मौसम परेशानी करता है","ठंडा मौसम परेशानी करता है","पता नहीं"]),
  "satva": ("सत्त्व (मानसिक दृढ़ता)", "तनाव से निपटने और मानसिक रूप से संभलने की आपकी सामान्य क्षमता कैसी है?", "यह स्वयं बताई गई जानकारी है, निदान नहीं।", ["आम तौर पर संभाल लेता/लेती हूँ","कुछ तनाव के साथ ठीक रहता/रहती हूँ","अक्सर बहुत दबाव महसूस होता है","बताना नहीं चाहता/चाहती"]),
  "ahara_shakti": ("आहार शक्ति (भूख और पाचन)", "आपकी भूख और पाचन सामान्यतः कैसा रहता है?", "अपने सामान्य अनुभव के अनुसार चुनें।", ["अच्छा और नियमित","बदलता रहता है","भूख कम","भारी / धीमा पाचन","पता नहीं"]),
  "vyayama_shakti": ("व्यायाम शक्ति (शारीरिक क्षमता)", "आप अपनी सामान्य दिनचर्या में कितनी शारीरिक गतिविधि आराम से कर सकते हैं?", "अपने सामान्य दिन की क्षमता बताएं।", ["अधिक","मध्यम","कम","बहुत कम / जल्दी थकता हूँ","पता नहीं"]),
  "vaya": ("वय (आयु / जीवन अवस्था)", "आपकी आयु आपके मरीज प्रोफ़ाइल में दर्ज है। कौन-सी जीवन अवस्था आपको सबसे अधिक उपयुक्त लगती है?", "सबसे करीब वाली जीवन अवस्था चुनें।", ["बचपन","किशोरावस्था","युवा वयस्क","मध्य वयस्क","वृद्ध वयस्क","बताना नहीं चाहते/चाहती"]),
 },
 "bn-IN": {
  "prakriti": ("প্রকৃতি (constitution)", "আপনার শরীর ও স্বভাবের সাধারণ ধরন কেমন? জানা থাকলে আপনার প্রধান প্রকৃতি বলুন (বাত, পিত্ত, কফ বা মিশ্রণ)।", "না জানলে ‘জানি না’ নির্বাচন করুন।", ["বাত","পিত্ত","কফ","বাত-পিত্ত","পিত্ত-কফ","বাত-কফ","ত্রিদোষিক / ভারসাম্যপূর্ণ","জানি না"]),
  "vikriti": ("বিকৃতি (বর্তমান পরিবর্তন)", "আপনার স্বাভাবিক অবস্থার তুলনায় সম্প্রতি কী পরিবর্তন হয়েছে? যে ধরনগুলো অনুভব করেন সেগুলো নির্বাচন করুন।", "যা প্রযোজ্য সেগুলো নির্বাচন করুন।", ["শুষ্কতা / অনিয়ম","গরম / অম্লতা","ভারীভাব / congestion","ঘুমের পরিবর্তন","ক্ষুধার পরিবর্তন","পায়খানার পরিবর্তন","স্ট্রেস / অস্থিরতা","বড় কোনো পরিবর্তন নেই","জানি না"]),
  "sara": ("সার (টিস্যুর গুণমান)", "যতদূর জানেন, আপনার শরীরের সাধারণ শক্তি ও পুষ্টির অবস্থা কেমন?", "এটি আপনার নিজের দেওয়া তথ্য।", ["শক্তিশালী / ভালো পুষ্টি","স্বাভাবিক","কম / সহজে ক্লান্ত","জানি না"]),
  "samhanana": ("সংহনন (শরীরের গঠন)", "আপনার সামগ্রিক শরীরের গঠন ও শারীরিক বিকাশ কেমন বলে মনে হয়?", "সবচেয়ে কাছের বিকল্পটি বেছে নিন।", ["সুসম / শক্তিশালী","মাঝারি গঠন","পাতলা / নাজুক","ভারী / প্রশস্ত","জানি না"]),
  "pramana": ("প্রমাণ (শারীরিক মাপ)", "আপনার কি সাম্প্রতিক উচ্চতা, ওজন, কোমরের মাপ বা অন্য কোনো শারীরিক মাপ আছে যা নথিভুক্ত করতে চান?", "যে মাপগুলো জানেন লিখুন।", None),
  "satmya": ("সাত্ম্য (উপযোগিতা)", "কোন খাবার, দৈনন্দিন অভ্যাস, আবহাওয়া বা রুটিন আপনার জন্য ভালো, আর কোনগুলো অস্বস্তি তৈরি করে?", "আপনার সাধারণ অভিজ্ঞতার সঙ্গে মেলে এমন সবকটি বেছে নিন।", ["বেশিরভাগ খাবার মানিয়ে যায়","ঝাল বা টক খাবারে অস্বস্তি হয়","ভারী খাবারে অস্বস্তি হয়","নিয়মিত রুটিন ভালো লাগে","অনিয়মিত রুটিনে অস্বস্তি হয়","গরম আবহাওয়ায় অস্বস্তি হয়","ঠান্ডা আবহাওয়ায় অস্বস্তি হয়","জানি না"]),
  "satva": ("সত্ত্ব (মানসিক সহনশীলতা)", "স্ট্রেস সামলানো ও মানসিকভাবে স্থির থাকার আপনার সাধারণ ক্ষমতা কেমন?", "এটি স্ব-প্রতিবেদিত তথ্য, মানসিক রোগ নির্ণয় নয়।", ["সাধারণত সামলে নিতে পারি","কিছু স্ট্রেসে মোটামুটি ঠিক","প্রায়ই খুব চাপ অনুভব করি","বলতে চাই না"]),
  "ahara_shakti": ("আহার শক্তি (ক্ষুধা ও হজম)", "আপনার ক্ষুধা ও হজম সাধারণত কেমন?", "আপনার সাধারণ অভিজ্ঞতা অনুযায়ী বেছে নিন।", ["ভালো ও নিয়মিত","পরিবর্তনশীল","ক্ষুধা কম","ভারী / ধীর হজম","জানি না"]),
  "vyayama_shakti": ("ব্যায়াম শক্তি (শারীরিক সক্ষমতা)", "আপনার সাধারণ দিনে কতটা শারীরিক কাজ আরাম করে করতে পারেন?", "সাধারণ দিনের সক্ষমতা অনুযায়ী বলুন।", ["বেশি","মাঝারি","কম","খুব কম / সহজে ক্লান্ত","জানি না"]),
  "vaya": ("বয় (বয়স / জীবনপর্যায়)", "আপনার বয়স রোগী প্রোফাইলে সংরক্ষিত আছে। কোন জীবনপর্যায় আপনার সঙ্গে সবচেয়ে বেশি মেলে?", "সবচেয়ে কাছের জীবনপর্যায়টি বেছে নিন।", ["শৈশব","কৈশোর","তরুণ প্রাপ্তবয়স্ক","মধ্য প্রাপ্তবয়স্ক","বয়স্ক প্রাপ্তবয়স্ক","বলতে চাই না"]),
 },
 "gu-IN": {
  "prakriti": ("પ્રકૃતિ (constitution)", "તમારા શરીર અને સ્વભાવનો સામાન્ય પ્રકાર કેવો છે? ખબર હોય તો તમારી મુખ્ય પ્રકૃતિ જણાવો (વાત, પિત્ત, કફ અથવા મિશ્રણ).", "ખબર ન હોય તો ‘ખબર નથી’ પસંદ કરો.", ["વાત","પિત્ત","કફ","વાત-પિત્ત","પિત્ત-કફ","વાત-કફ","ત્રિદોષિક / સંતુલિત","ખબર નથી"]),
  "vikriti": ("વિકૃતિ (હાલના ફેરફાર)", "તમારી સામાન્ય સ્થિતિની સરખામણીમાં તાજેતરમાં શું બદલાયું છે? જે બાબતો અનુભવાય તે પસંદ કરો.", "લાગુ પડતી બધી બાબતો પસંદ કરો.", ["સૂકાપણું / અનિયમિતતા","ગરમી / એસિડિટી","ભારેપણું / congestion","ઊંઘમાં ફેરફાર","ભૂખમાં ફેરફાર","મળમાં ફેરફાર","તણાવ / બેચેની","મોટો ફેરફાર નથી","ખબર નથી"]),
  "sara": ("સાર (ટિશ્યૂ ગુણવત્તા)", "જેટલી તમને જાણ હોય, તમારા શરીરની સામાન્ય તાકાત અને પોષણની સ્થિતિ કેવી છે?", "આ તમારી પોતાની જણાવેલી માહિતી છે.", ["મજબૂત / સારી રીતે પોષાયેલ","સામાન્ય","ઓછી / સરળતાથી થાક","ખબર નથી"]),
  "samhanana": ("સંહનન (શારીરિક બંધારણ)", "તમારા શરીરના સામાન્ય બંધારણ અને વિકાસને તમે કેવી રીતે વર્ણવશો?", "સૌથી નજીકનો વિકલ્પ પસંદ કરો.", ["સુસંગત / મજબૂત","સરેરાશ બંધારણ","પાતળું / નાજુક","ભારે / પહોળું","ખબર નથી"]),
  "pramana": ("પ્રમાણ (શારીરિક માપ)", "શું તમારી પાસે તાજેતરની ઊંચાઈ, વજન, કમરનું માપ અથવા અન્ય શારીરિક માપ છે જે નોંધવા માંગો છો?", "જાણતા હો તે માપ લખો.", None),
  "satmya": ("સાત્મ્ય (અનુકૂળતા)", "કયા ખોરાક, દિનચર્યા, હવામાન અથવા આદતો તમને સામાન્ય રીતે અનુકૂળ આવે છે અને કઈ અસ્વસ્થતા કરે છે?", "તમારા અનુભવ પ્રમાણે જણાવો.", None),
  "satva": ("સત્વ (માનસિક સ્થિરતા)", "તણાવ સંભાળવાની અને માનસિક રીતે સ્થિર રહેવાની તમારી સામાન્ય ક્ષમતા કેવી છે?", "આ સ્વ-રિપોર્ટેડ માહિતી છે, નિદાન નથી.", ["સામાન્ય રીતે સારી રીતે સંભાળી લઉં છું","થોડા તણાવ સાથે ઠીક","ઘણી વાર ખૂબ દબાણ લાગે છે","કહેવું નથી"]),
  "ahara_shakti": ("આહાર શક્તિ (ભૂખ અને પાચન)", "તમારી ભૂખ અને પાચન સામાન્ય રીતે કેવું રહે છે?", "તમારા સામાન્ય અનુભવ પ્રમાણે પસંદ કરો.", ["સારું અને નિયમિત","બદલાતું રહે છે","ભૂખ ઓછી","ભારે / ધીમું પાચન","ખબર નથી"]),
  "vyayama_shakti": ("વ્યાયામ શક્તિ (શારીરિક ક્ષમતા)", "તમારી સામાન્ય દિનચર્યામાં તમે કેટલી શારીરિક પ્રવૃત્તિ આરામથી કરી શકો છો?", "તમારા સામાન્ય દિવસની ક્ષમતા જણાવો.", ["વધુ","મધ્યમ","ઓછી","ખૂબ ઓછી / સરળતાથી થાકી જાઉં છું","ખબર નથી"]),
  "vaya": ("વય (ઉંમર / જીવન તબક્કો)", "તમારી ઉંમર કેટલી છે? ઇચ્છો તો કયો જીવન તબક્કો તમને સૌથી વધુ યોગ્ય લાગે છે તે પણ કહો.", "તમારી ઉંમર લખો.", None),
 },
}

# Add compact, readable translations for the remaining Indian languages. Question text is
# localized while clinical field IDs remain stable. Options are intentionally kept simple
# where a full translation would reduce clarity for the prototype.
AYUSH_TRANSLATIONS.update({
 "ta-IN": {k:(v[0],v[1],v[2],v[3]) for k,v in {
  "prakriti":("பிரகிருதி (constitution)","உங்கள் உடல் மற்றும் இயல்பின் பொதுவான தன்மை எப்படி உள்ளது? தெரிந்தால் உங்கள் முக்கிய பிரகிருதியை கூறுங்கள் (வாதம், பித்தம், கபம் அல்லது கலவை).","தெரியாவிட்டால் ‘தெரியாது’ என்பதைத் தேர்வு செய்யுங்கள்.",["வாதம்","பித்தம்","கபம்","வாத-பித்தம்","பித்த-கபம்","வாத-கபம்","மூன்று தோஷ சமநிலை","தெரியாது"]),
  "vikriti":("விகிருதி (தற்போதைய மாற்றங்கள்)","உங்கள் வழக்கமான நிலையை ஒப்பிடும்போது சமீபத்தில் என்ன மாற்றம் ஏற்பட்டுள்ளது? நீங்கள் உணரும் அம்சங்களைத் தேர்வு செய்யுங்கள்.","பொருந்துவதைத் தேர்வு செய்யுங்கள்.",["வறட்சி / ஒழுங்கின்மை","சூடு / அமிலத்தன்மை","கனத்தன்மை / அடைப்பு","தூக்க மாற்றம்","பசியின் மாற்றம்","மல மாற்றம்","மன அழுத்தம் / அமைதியின்மை","முக்கிய மாற்றம் இல்லை","தெரியாது"]),
  "sara":("சார (திசு தரம்)","உங்கள் உடலின் பொதுவான வலிமை மற்றும் ஊட்டநிலை எப்படி உள்ளது?","இது நீங்கள் கூறும் தகவல் மட்டுமே.",["வலிமையான / நல்ல ஊட்டம்","சராசரி","குறைவு / எளிதில் சோர்வு","தெரியாது"]),
  "samhanana":("சம்ஹனன (உடல் அமைப்பு)","உங்கள் உடல் அமைப்பு மற்றும் வளர்ச்சியை எப்படி விவரிப்பீர்கள்?","மிகவும் பொருந்தும் விருப்பத்தைத் தேர்வு செய்யுங்கள்.",["சீரான / வலிமையான","சராசரி அமைப்பு","மெலிந்த / நுட்பமான","கனமான / அகலமான","தெரியாது"]),
  "pramana":("பிரமாண (உடல் அளவுகள்)","சமீபத்திய உயரம், எடை, இடுப்பு அளவு அல்லது வேறு உடல் அளவுகள் உள்ளனவா?","தெரிந்த அளவுகளை எழுதுங்கள்.",None),
  "satmya":("சாத்ம்ய (ஒத்துப்போகும் தன்மை)","எந்த உணவு, பழக்கம், காலநிலை அல்லது தினசரி நடைமுறை உங்களுக்கு ஏற்றது? எவை அசௌகரியம் தருகின்றன?","உங்கள் அனுபவத்தைப் பகிருங்கள்.",None),
  "satva":("சத்த்வ (மன உறுதி)","மன அழுத்தத்தை சமாளிக்கும் மற்றும் மனநிலையை சமநிலையில் வைத்திருக்கும் உங்கள் வழக்கமான திறன் எப்படி?","இது சுயமாக கூறிய தகவல்; நோயறிதல் அல்ல.",["பொதுவாக சமாளிக்க முடியும்","சில அழுத்தத்துடன் பரவாயில்லை","அடிக்கடி அதிக அழுத்தம்","சொல்ல விரும்பவில்லை"]),
  "ahara_shakti":("ஆஹார சக்தி (பசி / செரிமானம்)","உங்கள் பசி மற்றும் செரிமானம் பொதுவாக எப்படி உள்ளது?","உங்கள் வழக்கமான அனுபவத்தைத் தேர்வு செய்யுங்கள்.",["நல்லது மற்றும் ஒழுங்கானது","மாறுபடும்","பசி குறைவு","கனமான / மெதுவான செரிமானம்","தெரியாது"]),
  "vyayama_shakti":("வ்யாயாம சக்தி (உடல் திறன்)","உங்கள் வழக்கமான நாளில் எவ்வளவு உடல் செயல்பாட்டை வசதியாக செய்ய முடியும்?","உங்கள் வழக்கமான நாளை அடிப்படையாகக் கொள்ளுங்கள்.",["அதிகம்","மிதமானது","குறைவு","மிகக் குறைவு / எளிதில் சோர்வு","தெரியாது"]),
  "vaya":("வய (வயது / வாழ்க்கை நிலை)","உங்கள் வயது என்ன? விரும்பினால் எந்த வாழ்க்கை நிலையுடன் நீங்கள் அதிகம் பொருந்துகிறீர்கள் என்றும் கூறலாம்.","உங்கள் வயதை எழுதுங்கள்.",None),
 }.items()},
 "te-IN": {k:(v[0],v[1],v[2],v[3]) for k,v in {
  "prakriti":("ప్రకృతి (constitution)","మీ శరీరం మరియు స్వభావం సాధారణంగా ఎలా ఉంటాయి? తెలిసి ఉంటే మీ ప్రధాన ప్రకృతిని చెప్పండి (వాత, పిత్త, కఫ లేదా కలయిక).","తెలియకపోతే ‘తెలియదు’ ఎంచుకోండి.",["వాత","పిత్త","కఫ","వాత-పిత్త","పిత్త-కఫ","వాత-కఫ","త్రిదోష సమతుల్యం","తెలియదు"]),
  "vikriti":("వికృతి (ప్రస్తుత మార్పులు)","మీ సాధారణ స్థితితో పోలిస్తే ఇటీవల ఏమి మారింది? మీరు గమనించిన వాటిని ఎంచుకోండి.","వర్తించేవాటిని ఎంచుకోండి.",["పొడిబారడం / అసమానత","వేడి / ఆమ్లత్వం","భారంగా / congestion","నిద్రలో మార్పు","ఆకలిలో మార్పు","మల విసర్జనలో మార్పు","ఒత్తిడి / అస్థిరత","పెద్ద మార్పు లేదు","తెలియదు"]),
  "sara":("సార (కణజాల నాణ్యత)","మీకు తెలిసినంతవరకు, మీ శరీర సాధారణ బలం మరియు పోషక స్థితి ఎలా ఉంది?","ఇది మీరు చెప్పిన సమాచారం మాత్రమే.",["బలంగా / మంచి పోషణ","సగటు","తక్కువ / త్వరగా అలసిపోతాను","తెలియదు"]),
  "samhanana":("సంహనన (శరీర నిర్మాణం)","మీ శరీర నిర్మాణం మరియు శారీరక అభివృద్ధిని ఎలా వివరిస్తారు?","దగ్గరగా ఉన్న ఎంపికను ఎంచుకోండి.",["సమతుల్య / బలమైన","సగటు నిర్మాణం","సన్నగా / సున్నితంగా","భారీ / వెడల్పుగా","తెలియదు"]),
  "pramana":("ప్రమాణ (శరీర కొలతలు)","ఇటీవలి ఎత్తు, బరువు, నడుము కొలత లేదా ఇతర శరీర కొలతలు నమోదు చేయాలనుకుంటున్నారా?","తెలిసిన కొలతలను రాయండి.",None),
  "satmya":("సాత్మ్య (అనుకూలత)","ఏ ఆహారం, అలవాట్లు, వాతావరణం లేదా దినచర్య మీకు బాగా సరిపోతాయి? ఏవి అసౌకర్యం కలిగిస్తాయి?","మీ అనుభవం ప్రకారం చెప్పండి.",None),
  "satva":("సత్వ (మానసిక స్థైర్యం)","ఒత్తిడిని ఎదుర్కోవడం మరియు మానసికంగా స్థిరంగా ఉండటం మీ సాధారణ సామర్థ్యం ఎలా ఉంది?","ఇది స్వయంగా చెప్పిన సమాచారం; నిర్ధారణ కాదు.",["సాధారణంగా ఎదుర్కోగలను","కొంత ఒత్తిడితో బాగానే ఉంటాను","తరచుగా ఎక్కువ ఒత్తిడి","చెప్పదలుచుకోలేదు"]),
  "ahara_shakti":("ఆహార శక్తి (ఆకలి / జీర్ణం)","మీ ఆకలి మరియు జీర్ణక్రియ సాధారణంగా ఎలా ఉంటాయి?","మీ సాధారణ అనుభవం ప్రకారం ఎంచుకోండి.",["మంచిది మరియు క్రమబద్ధం","మారుతూ ఉంటుంది","ఆకలి తక్కువ","భారం / నెమ్మదిగా జీర్ణం","తెలియదు"]),
  "vyayama_shakti":("వ్యాయామ శక్తి (శారీరక సామర్థ్యం)","మీ సాధారణ రోజులో ఎంత శారీరక కార్యకలాపం సౌకర్యంగా చేయగలరు?","మీ సాధారణ రోజు సామర్థ్యాన్ని చెప్పండి.",["ఎక్కువ","మధ్యస్థం","తక్కువ","చాలా తక్కువ / త్వరగా అలసిపోతాను","తెలియదు"]),
  "vaya":("వయ (వయస్సు / జీవన దశ)","మీ వయస్సు ఎంత? కావాలంటే మీకు సరిపోయే జీవన దశను కూడా చెప్పవచ్చు.","మీ వయస్సు రాయండి.",None),
 }.items()},
 "mr-IN": {k:(v[0],v[1],v[2],v[3]) for k,v in {
  "prakriti":("प्रकृती (constitution)","तुमच्या शरीराचा आणि स्वभावाचा सामान्य प्रकार कसा आहे? माहिती असल्यास तुमची प्रमुख प्रकृती सांगा (वात, पित्त, कफ किंवा मिश्र).","माहिती नसेल तर ‘माहित नाही’ निवडा.",["वात","पित्त","कफ","वात-पित्त","पित्त-कफ","वात-कफ","त्रिदोषिक / संतुलित","माहित नाही"]),
  "vikriti":("विकृती (सध्यातील बदल)","तुमच्या नेहमीच्या स्थितीच्या तुलनेत अलीकडे काय बदलले आहे? जाणवणारे बदल निवडा.","लागू असलेले पर्याय निवडा.",["कोरडेपणा / अनियमितता","उष्णता / आम्लता","जडपणा / कोंडी","झोपेतील बदल","भुकेतील बदल","शौचातील बदल","ताण / अस्वस्थता","मोठा बदल नाही","माहित नाही"]),
  "sara":("सार (ऊतक गुणवत्ता)","तुम्हाला माहिती आहे त्यानुसार शरीराची सामान्य ताकद आणि पोषणाची स्थिती कशी आहे?","ही तुमची स्वतःची माहिती आहे.",["मजबूत / चांगले पोषण","सामान्य","कमी / लवकर थकतो","माहित नाही"]),
  "samhanana":("संहनन (शरीराची बांधणी)","तुमची एकूण शरीरबांधणी आणि शारीरिक विकास कसा आहे असे तुम्ही सांगाल?","सर्वात जवळचा पर्याय निवडा.",["सुदृढ / मजबूत","सरासरी बांधणी","बारीक / नाजूक","जड / रुंद","माहित नाही"]),
  "pramana":("प्रमाण (शारीरिक मोजमाप)","तुमच्याकडे अलीकडील उंची, वजन, कंबर किंवा इतर शारीरिक मोजमाप आहेत का?","माहित असलेली मोजमापे लिहा.",None),
  "satmya":("सात्म्य (अनुकूलता)","कोणते अन्न, दिनचर्या, हवामान किंवा सवयी तुम्हाला अनुकूल असतात आणि कोणत्यामुळे त्रास होतो?","तुमच्या अनुभवाप्रमाणे सांगा.",None),
  "satva":("सत्त्व (मानसिक स्थैर्य)","ताण हाताळण्याची आणि मानसिकदृष्ट्या स्थिर राहण्याची तुमची सामान्य क्षमता कशी आहे?","ही स्वतः सांगितलेली माहिती आहे; निदान नाही.",["सामान्यतः सांभाळू शकतो","काही ताण असूनही ठीक","अनेकदा खूप ताण जाणवतो","सांगू इच्छित नाही"]),
  "ahara_shakti":("आहार शक्ती (भूक / पचन)","तुमची भूक आणि पचन साधारणपणे कसे असते?","तुमच्या नेहमीच्या अनुभवाप्रमाणे निवडा.",["चांगले आणि नियमित","बदलते","भूक कमी","जड / मंद पचन","माहित नाही"]),
  "vyayama_shakti":("व्यायाम शक्ती (शारीरिक क्षमता)","तुमच्या नेहमीच्या दिवसात किती शारीरिक हालचाल आरामात करू शकता?","तुमच्या नेहमीच्या क्षमतेनुसार सांगा.",["जास्त","मध्यम","कमी","खूप कमी / लवकर थकतो","माहित नाही"]),
  "vaya":("वय (वय / जीवन टप्पा)","तुमचे वय किती आहे? इच्छित असल्यास कोणता जीवन टप्पा तुमच्याशी जास्त जुळतो ते सांगा.","तुमचे वय लिहा.",None),
 }.items()},
 "kn-IN": {k:(v[0],v[1],v[2],v[3]) for k,v in {
  "prakriti":("ಪ್ರಕೃತಿ (constitution)","ನಿಮ್ಮ ದೇಹ ಮತ್ತು ಸ್ವಭಾವದ ಸಾಮಾನ್ಯ ರೀತಿಯು ಹೇಗಿದೆ? ತಿಳಿದಿದ್ದರೆ ನಿಮ್ಮ ಪ್ರಮುಖ ಪ್ರಕೃತಿಯನ್ನು ಹೇಳಿ (ವಾತ, ಪಿತ್ತ, ಕಫ ಅಥವಾ ಮಿಶ್ರಣ).","ತಿಳಿದಿಲ್ಲದಿದ್ದರೆ ‘ತಿಳಿದಿಲ್ಲ’ ಆಯ್ಕೆಮಾಡಿ.",["ವಾತ","ಪಿತ್ತ","ಕಫ","ವಾತ-ಪಿತ್ತ","ಪಿತ್ತ-ಕಫ","ವಾತ-ಕಫ","ತ್ರಿದೋಷ / ಸಮತೋಲನ","ತಿಳಿದಿಲ್ಲ"]),
  "vikriti":("ವಿಕೃತಿ (ಪ್ರಸ್ತುತ ಬದಲಾವಣೆ)","ನಿಮ್ಮ ಸಾಮಾನ್ಯ ಸ್ಥಿತಿಗೆ ಹೋಲಿಸಿದರೆ ಇತ್ತೀಚೆಗೆ ಏನು ಬದಲಾಗಿದೆ? ನೀವು ಗಮನಿಸಿದವುಗಳನ್ನು ಆಯ್ಕೆಮಾಡಿ.","ಅನ್ವಯಿಸುವವುಗಳನ್ನು ಆಯ್ಕೆಮಾಡಿ.",["ಒಣತನ / ಅಸಮರ್ಪಕತೆ","ಬಿಸಿ / ಆಮ್ಲತೆ","ಭಾರ / congestion","ನಿದ್ರೆಯಲ್ಲಿ ಬದಲಾವಣೆ","ಹಸಿವಿನಲ್ಲಿ ಬದಲಾವಣೆ","ಮಲದಲ್ಲಿ ಬದಲಾವಣೆ","ಒತ್ತಡ / ಅಶಾಂತಿ","ದೊಡ್ಡ ಬದಲಾವಣೆ ಇಲ್ಲ","ತಿಳಿದಿಲ್ಲ"]),
  "sara":("ಸಾರ (ಕಣಜ ಗುಣಮಟ್ಟ)","ನಿಮಗೆ ತಿಳಿದಿರುವ ಮಟ್ಟಿಗೆ ನಿಮ್ಮ ದೇಹದ ಸಾಮಾನ್ಯ ಬಲ ಮತ್ತು ಪೋಷಣೆಯ ಸ್ಥಿತಿ ಹೇಗಿದೆ?","ಇದು ನೀವು ನೀಡಿದ ಮಾಹಿತಿ ಮಾತ್ರ.",["ಬಲವಾದ / ಉತ್ತಮ ಪೋಷಣೆ","ಸರಾಸರಿ","ಕಡಿಮೆ / ಬೇಗ ದಣಿವು","ತಿಳಿದಿಲ್ಲ"]),
  "samhanana":("ಸಂಹನನ (ದೇಹದ ಕಟ್ಟಳೆ)","ನಿಮ್ಮ ದೇಹದ ಒಟ್ಟಾರೆ ಕಟ್ಟಳೆ ಮತ್ತು ದೈಹಿಕ ಬೆಳವಣಿಗೆಯನ್ನು ಹೇಗೆ ವಿವರಿಸುತ್ತೀರಿ?","ಹತ್ತಿರವಾದ ಆಯ್ಕೆಯನ್ನು ಆರಿಸಿ.",["ಸಮಪ್ರಮಾಣ / ಬಲವಾದ","ಸರಾಸರಿ ಕಟ್ಟಳೆ","ಸಣ್ಣ / ಸೂಕ್ಷ್ಮ","ಭಾರವಾದ / ಅಗಲವಾದ","ತಿಳಿದಿಲ್ಲ"]),
  "pramana":("ಪ್ರಮಾಣ (ದೇಹದ ಅಳತೆ)","ಇತ್ತೀಚಿನ ಎತ್ತರ, ತೂಕ, ಸೊಂಟದ ಅಳತೆ ಅಥವಾ ಇತರ ದೇಹದ ಅಳತೆಗಳನ್ನು ದಾಖಲಿಸಲು ಬಯಸುವಿರಾ?","ತಿಳಿದಿರುವ ಅಳತೆಗಳನ್ನು ಬರೆಯಿರಿ.",None),
  "satmya":("ಸಾತ್ಮ್ಯ (ಹೊಂದಾಣಿಕೆ)","ಯಾವ ಆಹಾರ, ದಿನಚರಿ, ಹವಾಮಾನ ಅಥವಾ ಅಭ್ಯಾಸಗಳು ನಿಮಗೆ ಸಾಮಾನ್ಯವಾಗಿ ಹೊಂದಿಕೊಳ್ಳುತ್ತವೆ ಮತ್ತು ಯಾವವು ಅಸೌಕರ್ಯ ಉಂಟುಮಾಡುತ್ತವೆ?","ನಿಮ್ಮ ಅನುಭವದಂತೆ ಹೇಳಿ.",None),
  "satva":("ಸತ್ವ (ಮಾನಸಿಕ ಸ್ಥೈರ್ಯ)","ಒತ್ತಡವನ್ನು ನಿಭಾಯಿಸುವ ಮತ್ತು ಮಾನಸಿಕವಾಗಿ ಸ್ಥಿರವಾಗಿರುವ ನಿಮ್ಮ ಸಾಮಾನ್ಯ ಸಾಮರ್ಥ್ಯ ಹೇಗಿದೆ?","ಇದು ಸ್ವಯಂ ವರದಿ; ರೋಗನಿರ್ಣಯವಲ್ಲ.",["ಸಾಮಾನ್ಯವಾಗಿ ನಿಭಾಯಿಸಬಲ್ಲೆ","ಸ್ವಲ್ಪ ಒತ್ತಡದೊಂದಿಗೆ ಸರಿ","ಆಗಾಗ್ಗೆ ತುಂಬಾ ಒತ್ತಡ","ಹೇಳಲು ಇಷ್ಟವಿಲ್ಲ"]),
  "ahara_shakti":("ಆಹಾರ ಶಕ್ತಿ (ಹಸಿವು / ಜೀರ್ಣಕ್ರಿಯೆ)","ನಿಮ್ಮ ಹಸಿವು ಮತ್ತು ಜೀರ್ಣಕ್ರಿಯೆ ಸಾಮಾನ್ಯವಾಗಿ ಹೇಗಿರುತ್ತದೆ?","ನಿಮ್ಮ ಸಾಮಾನ್ಯ ಅನುಭವದಂತೆ ಆಯ್ಕೆಮಾಡಿ.",["ಉತ್ತಮ ಮತ್ತು ನಿಯಮಿತ","ಬದಲಾಗುತ್ತದೆ","ಹಸಿವು ಕಡಿಮೆ","ಭಾರ / ನಿಧಾನ ಜೀರ್ಣಕ್ರಿಯೆ","ತಿಳಿದಿಲ್ಲ"]),
  "vyayama_shakti":("ವ್ಯಾಯಾಮ ಶಕ್ತಿ (ದೈಹಿಕ ಸಾಮರ್ಥ್ಯ)","ನಿಮ್ಮ ಸಾಮಾನ್ಯ ದಿನದಲ್ಲಿ ಎಷ್ಟು ದೈಹಿಕ ಚಟುವಟಿಕೆಯನ್ನು ಆರಾಮವಾಗಿ ಮಾಡಬಹುದು?","ನಿಮ್ಮ ಸಾಮಾನ್ಯ ದಿನದ ಸಾಮರ್ಥ್ಯವನ್ನು ಹೇಳಿ.",["ಹೆಚ್ಚು","ಮಧ್ಯಮ","ಕಡಿಮೆ","ತುಂಬಾ ಕಡಿಮೆ / ಬೇಗ ದಣಿವು","ತಿಳಿದಿಲ್ಲ"]),
  "vaya":("ವಯ (ವಯಸ್ಸು / ಜೀವನ ಹಂತ)","ನಿಮ್ಮ ವಯಸ್ಸು ಎಷ್ಟು? ಬಯಸಿದರೆ ನಿಮಗೆ ಹೊಂದುವ ಜೀವನ ಹಂತವನ್ನೂ ಹೇಳಬಹುದು.","ನಿಮ್ಮ ವಯಸ್ಸನ್ನು ಬರೆಯಿರಿ.",None),
 }.items()},
})

def localized_ayush_questions(language):
    lang = language if language in AYUSH_TRANSLATIONS else "en-IN"
    translations = AYUSH_TRANSLATIONS.get(lang, {})
    out=[]
    for q in AYUSH_DASHAVIDHA:
        x=dict(q)
        if q["id"] in translations:
            title,text,hint,options=translations[q["id"]]
            x.update(title=title, question=text, hint=hint)
            if options is not None: x["options"]=options
        out.append(x)
    return out

class AyushAnswer(BaseModel):
    patient_id: int
    session_id: str
    question_id: str
    answer: str = ""
    skipped: bool = False
    answers: dict = Field(default_factory=dict)
    language: str = "en-IN"

class AyushComplete(BaseModel):
    patient_id: int
    session_id: str
    responses: dict
    language: str = "en-IN"

@app.get("/api/ayush/questions")
def ayush_questions(language: str = "en-IN"):
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language. Choose one of: {', '.join(SUPPORTED_LANGUAGES)}")
    intro = "यह आयुष/आयुर्वेद मॉड्यूल दशविध परीक्षा से संबंधित जानकारी दर्ज करता है। यह स्वयं निदान या दोष निर्धारण नहीं करता।" if language == "hi-IN" else AYUSH_INTRO
    return {"intro": intro, "system":"Ayurveda", "assessment_type":"Dashavidha Pariksha", "questions": localized_ayush_questions(language), "language":language}

@app.post("/api/ayush/answer")
def ayush_answer(payload: AyushAnswer, request: Request):
    actor = authenticate_request(request)
    authorize_interview_patient(actor, payload.patient_id)
    if not payload.skipped and not payload.answer.strip():
        raise HTTPException(status_code=400, detail="Please provide an answer or skip this question.")
    answered=dict(payload.answers or {})
    skipped_ids = answered.get("__skipped_questions", [])
    if not isinstance(skipped_ids, list): skipped_ids = []
    if payload.skipped and payload.question_id not in skipped_ids: skipped_ids.append(payload.question_id)
    answered["__skipped_questions"] = skipped_ids[-100:]
    answered[payload.question_id] = "" if payload.skipped else payload.answer.strip()
    ids=[q["id"] for q in AYUSH_DASHAVIDHA]
    idx=ids.index(payload.question_id) if payload.question_id in ids else -1
    next_q=AYUSH_DASHAVIDHA[idx+1] if idx>=0 and idx+1<len(AYUSH_DASHAVIDHA) else None
    return {"message":"AYUSH response received","next_question":(localized_ayush_questions(payload.language)[idx+1] if next_q is not None else None),"completed":next_q is None,"progress":round(len(answered)/len(ids)*100),"question_number":len(answered)+(0 if next_q is None else 1),"total_questions":len(ids),"responses":answered,"language":payload.language}

@app.post("/api/ayush/complete")
def ayush_complete(payload: AyushComplete, request: Request):
    actor = authenticate_request(request)
    authorize_interview_patient(actor, payload.patient_id)
    db=SessionLocal()
    try:
        patient=db.query(User).filter(User.id==payload.patient_id, User.role=="patient").first()
        if not patient: raise HTTPException(status_code=404, detail="Patient not found.")
        lines=[]
        for q in AYUSH_DASHAVIDHA:
            val=payload.responses.get(q["id"])
            if val not in (None, ""): lines.append(f'{q["title"]}: {val}')
        summary=" | ".join(lines) if lines else "AYUSH assessment completed with no additional responses."
        rec=AyushAssessment(patient_id=patient.id,responses=json.dumps(payload.responses,ensure_ascii=False),summary=summary)
        db.add(rec)
        encounter = get_or_create_handoff_encounter(db, patient.id)
        # AYUSH is an optional assessment attached to the same hospital encounter.
        # It must never replace the completed General Doctor pathway or overwrite
        # the encounter's department/reason/care type.
        structured = {"ayush_assessment": payload.responses, "chief_complaint": encounter.reason or "General Doctor assessment", "language": payload.language, "care_type": "ayush", "encounter_id": encounter.id}
        physician_summary = generate_physician_summary(structured, "none", [], {"positive_symptoms":[],"negated_symptoms":[]}, patient=patient, encounter=encounter, documents=db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient.id).order_by(MedicalDocument.created_at.desc()).all())
        existing = (db.query(Consultation).filter(Consultation.patient_id==patient.id, Consultation.encounter_id==encounter.id, Consultation.title=="AYUSH / Ayurveda intake").order_by(Consultation.created_at.desc()).first())
        if existing and (existing.consultation_status or "draft") != "completed":
            existing.summary = summary
            existing.status = "AYUSH History — Physician Review Ready"
            existing.structured_data = json.dumps(structured, ensure_ascii=False)
            existing.ai_summary = json.dumps(physician_summary, ensure_ascii=False)
            existing.ai_summary_generated_at = utc_now()
        else:
            existing = Consultation(patient_id=patient.id, encounter_id=encounter.id, title="AYUSH / Ayurveda intake", consultation_type="ayush", summary=summary, status="AYUSH assessment — summary ready", risk_level="none", red_flags="[]", structured_data=json.dumps(structured,ensure_ascii=False), nlp_data=json.dumps({},ensure_ascii=False), ai_summary=json.dumps(physician_summary,ensure_ascii=False), ai_summary_generated_at=utc_now(), consultation_status="draft")
            db.add(existing)
        db.commit(); db.refresh(rec); db.refresh(existing)
        return {"message":"AYUSH assessment saved","assessment_id":rec.id,"consultation_id":existing.id,"summary":summary,"ai_summary":physician_summary,"responses":payload.responses}
    finally: db.close()

@app.get("/api/patients/{patient_id}/ayush")
def patient_ayush(patient_id:int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db=SessionLocal()
    try:
        rows=db.query(AyushAssessment).filter(AyushAssessment.patient_id==patient_id).order_by(AyushAssessment.created_at.desc()).all()
        return {"assessments":[{"id":r.id,"system":r.system,"assessment_type":r.assessment_type,"summary":r.summary,"responses":json.loads(r.responses or "{}"),"created_at":r.created_at.isoformat()} for r in rows]}
    finally: db.close()

# ---------- Phase 5B: consent + identity + FHIR-ready interoperability ----------
CONSENT_SCOPE = "AI-assisted case taking, document processing, AYUSH intake, physician review"

@app.get("/api/patients/{patient_id}/consent")
def get_consent(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db = SessionLocal()
    try:
        rows = db.query(ConsentRecord).filter(ConsentRecord.patient_id == patient_id).order_by(ConsentRecord.created_at.desc()).all()
        active = next((r for r in rows if r.granted and r.revoked_at is None), None)
        return {"active": bool(active), "consent": ({"id": active.id, "type": active.consent_type, "version": active.version, "language": active.language, "audio_explained": bool(active.audio_explained), "scope": active.scope, "created_at": active.created_at.isoformat()} if active else None), "history": [{"id":r.id,"granted":bool(r.granted),"revoked":bool(r.revoked_at),"created_at":r.created_at.isoformat()} for r in rows]}
    finally:
        db.close()

@app.post("/api/patients/{patient_id}/consent")
def save_consent(patient_id: int, payload: ConsentRequest, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient: raise HTTPException(status_code=404, detail="Patient not found.")
        current = db.query(ConsentRecord).filter(ConsentRecord.patient_id == patient_id, ConsentRecord.revoked_at.is_(None), ConsentRecord.granted == 1).all()
        for c in current: c.revoked_at = utc_now()
        rec = ConsentRecord(patient_id=patient_id, consent_type=payload.consent_type, language=payload.language, granted=1 if payload.granted else 0, audio_explained=1 if payload.audio_explained else 0, scope=CONSENT_SCOPE)
        db.add(rec); db.commit(); db.refresh(rec)
        return {"message":"Consent recorded","active":bool(rec.granted),"consent_id":rec.id,"version":rec.version}
    finally:
        db.close()

@app.post("/api/patients/{patient_id}/consent/revoke")
def revoke_consent(patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, patient_id)
    db = SessionLocal()
    try:
        rows = db.query(ConsentRecord).filter(ConsentRecord.patient_id == patient_id, ConsentRecord.granted == 1, ConsentRecord.revoked_at.is_(None)).all()
        for r in rows: r.revoked_at = utc_now()
        db.commit()
        return {"message":"Consent revoked","active":False}
    finally:
        db.close()

def fhir_reference(resource_type, resource_id):
    return {"reference": f"{resource_type}/{resource_id}"}

def build_fhir_bundle(db, patient_id: int):
    patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
    if not patient: raise HTTPException(status_code=404, detail="Patient not found.")
    profile = patient.profile
    consultations = db.query(Consultation).filter(Consultation.patient_id == patient_id).order_by(Consultation.created_at.desc()).all()
    docs = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.created_at.desc()).all()
    ayush = db.query(AyushAssessment).filter(AyushAssessment.patient_id == patient_id).order_by(AyushAssessment.created_at.desc()).all()
    entries=[]
    patient_resource={"resourceType":"Patient","id":f"sih-{patient.id}","identifier":[{"system":"https://sih26047.local/patient-id","value":str(patient.id)}],"name":[{"text":patient.name}],"gender":(profile.gender.lower() if profile and profile.gender and profile.gender.lower() in ["male","female","other","unknown"] else "unknown") }
    if profile and profile.age:
        patient_resource["extension"]=[{"url":"https://sih26047.local/fhir/age","valueInteger":profile.age}]
    entries.append({"fullUrl":f"urn:uuid:{patient_resource['id']}","resource":patient_resource})
    for c in consultations:
        entries.append({"fullUrl":f"urn:uuid:consultation-{c.id}","resource":{"resourceType":"DocumentReference","id":f"consultation-{c.id}","status":"current","subject":fhir_reference("Patient",patient_resource["id"]),"description":c.title,"date":c.created_at.isoformat(),"content":[{"attachment":{"contentType":"text/plain","title":"AI-assisted clinical history","data":c.summary.encode().hex()}}],"extension":[{"url":"https://sih26047.local/fhir/risk-level","valueString":c.risk_level or "none"},{"url":"https://sih26047.local/fhir/doctor-review","valueString":c.doctor_review or "Pending"}]}})
    for d in docs:
        entries.append({"fullUrl":f"urn:uuid:document-{d.id}","resource":{"resourceType":"DocumentReference","id":f"document-{d.id}","status":"current","subject":fhir_reference("Patient",patient_resource["id"]),"description":f"{d.document_type}: {d.filename}","date":d.created_at.isoformat(),"content":[{"attachment":{"title":d.filename,"contentType":d.mime_type or "application/octet-stream"}}]}})
    for a in ayush:
        entries.append({"fullUrl":f"urn:uuid:ayush-{a.id}","resource":{"resourceType":"QuestionnaireResponse","id":f"ayush-{a.id}","status":"completed","subject":fhir_reference("Patient",patient_resource["id"]),"authored":a.created_at.isoformat(),"questionnaire":"https://sih26047.local/fhir/Questionnaire/dashavidha-pariksha","item":[{"linkId":k,"text":k,"answer":[{"valueString":str(v)}]} for k,v in json.loads(a.responses or "{}").items()]}})
    return {"resourceType":"Bundle","id":f"sih26047-{patient.id}-{uuid.uuid4().hex[:10]}","type":"collection","timestamp":utc_now().isoformat(),"meta":{"profile":["http://hl7.org/fhir/StructureDefinition/Bundle"],"tag":[{"system":"https://sih26047.local","code":"SIH26047-PHASE5B","display":"Prototype FHIR-ready export"}]},"entry":entries}

@app.get("/api/doctor/patients/{patient_id}/fhir-preview")
def fhir_preview(patient_id: int, request: Request):
    actor = authenticate_request(request)
    db=SessionLocal()
    try:
        authorize_interoperability_patient(actor, patient_id, db)
        return build_fhir_bundle(db, patient_id)
    finally: db.close()

@app.get("/api/doctor/patients/{patient_id}/abdm-readiness")
def abdm_readiness(patient_id: int, request: Request):
    actor = authenticate_request(request)
    db=SessionLocal()
    try:
        authorize_interoperability_patient(actor, patient_id, db)
        patient=db.query(User).filter(User.id==patient_id, User.role=="patient").first()
        if not patient: raise HTTPException(status_code=404, detail="Patient not found.")
        consent=db.query(ConsentRecord).filter(ConsentRecord.patient_id==patient_id, ConsentRecord.granted==1, ConsentRecord.revoked_at.is_(None)).order_by(ConsentRecord.created_at.desc()).first()
        consultations=db.query(Consultation).filter(Consultation.patient_id==patient_id).count()
        docs=db.query(MedicalDocument).filter(MedicalDocument.patient_id==patient_id).count()
        ayush=db.query(AyushAssessment).filter(AyushAssessment.patient_id==patient_id).count()
        return {"patient_id":patient_id,"abha_status":"demo-not-linked","consent_active":bool(consent),"consent_id":consent.id if consent else None,"care_context_count":consultations+ayush,"document_count":docs,"facility_registry":"demo","hpr_registry":"demo","network_status":"sandbox-ready","production_connection":False,"checks":{"fhir_bundle":True,"consent_gate":bool(consent),"care_context":(consultations+ayush)>0,"abha_link":False,"hfr_link":False,"hpr_link":False}}
    finally: db.close()

def build_abdm_package(db, patient_id: int, abha_address: Optional[str] = None, facility_id: str = "SIH26047-DEMO-FACILITY", practitioner_id: str = "SIH26047-DEMO-HPR", consent_reference: Optional[str] = None):
    bundle=build_fhir_bundle(db, patient_id)
    patient=db.query(User).filter(User.id==patient_id, User.role=="patient").first()
    consent=db.query(ConsentRecord).filter(ConsentRecord.patient_id==patient_id, ConsentRecord.granted==1, ConsentRecord.revoked_at.is_(None)).order_by(ConsentRecord.created_at.desc()).first()
    if not consent: raise HTTPException(status_code=403, detail="Active patient consent is required for an ABDM package.")
    care_contexts=[]
    for e in bundle.get("entry",[]):
        r=e.get("resource",{})
        if r.get("resourceType") in ("DocumentReference","QuestionnaireResponse"):
            care_contexts.append({"reference":r.get("id"),"display":r.get("description") or r.get("resourceType")})
    package={"package_type":"ABDM sandbox-ready health record package","standard":"FHIR R4 / ABDM-aligned prototype","generated_at":utc_now().isoformat(),"abha":{"address":abha_address,"linked":bool(abha_address)},"patient":{"local_id":f"SIH26047-P-{patient.id:04d}","fhir_id":f"sih-{patient.id}"},"care_contexts":care_contexts,"consent":{"active":True,"record_id":consent.id,"reference":consent_reference or f"Consent/{consent.id}","version":consent.version},"facility":{"hfr_id":facility_id,"status":"demo"},"practitioner":{"hpr_id":practitioner_id,"status":"demo"},"exchange":{"mode":"sandbox-ready simulation","network_endpoint":None,"sent_to_abdm":False},"fhir_bundle":bundle,"limitations":["This prototype does not connect to the live ABDM network.","ABHA, HFR and HPR identifiers shown here are demo placeholders unless explicitly linked.","A production integration requires ABDM sandbox onboarding, authentication, consent workflows, security assessment and approved network endpoints."]}
    return package

@app.get("/api/doctor/patients/{patient_id}/abdm-package")
def abdm_package_preview(patient_id: int, request: Request):
    actor = authenticate_request(request)
    db=SessionLocal()
    try:
        authorize_interoperability_patient(actor, patient_id, db)
        return build_abdm_package(db, patient_id)
    finally: db.close()

@app.post("/api/doctor/patients/{patient_id}/abdm-package")
def abdm_package_export(patient_id: int, payload: ABDMExportRequest, request: Request):
    actor = authenticate_request(request)
    db=SessionLocal()
    try:
        authorize_interoperability_patient(actor, patient_id, db)
        package=build_abdm_package(db, patient_id, payload.abha_address, payload.facility_id, payload.practitioner_id, payload.consent_reference)
        rec=FHIRExportRecord(patient_id=patient_id, exported_by=actor["id"], resource_type="ABDM-Package", bundle_id=package["fhir_bundle"]["id"])
        db.add(rec); db.commit(); db.refresh(rec)
        return {"message":"ABDM sandbox-ready package generated","export_id":rec.id,"package":package}
    finally: db.close()

@app.post("/api/doctor/patients/{patient_id}/fhir-validate")
def validate_fhir(patient_id: int, request: Request):
    actor = authenticate_request(request)
    db=SessionLocal()
    try:
        authorize_interoperability_patient(actor, patient_id, db)
        b=build_fhir_bundle(db, patient_id)
        errors=[]
        if b.get("resourceType")!="Bundle": errors.append("Bundle.resourceType must be Bundle")
        if b.get("type") not in ("collection","document","message"): errors.append("Bundle.type is missing or unsupported")
        for e in b.get("entry",[]):
            r=e.get("resource",{})
            if not r.get("resourceType"): errors.append("Entry resourceType is missing")
            if not r.get("id"): errors.append(f"{r.get('resourceType','Resource')} id is missing")
        return {"valid":not errors,"resource_count":len(b.get("entry",[])),"errors":errors,"profile":"FHIR R4 baseline / ABDM-aligned prototype","checked_at":utc_now().isoformat()}
    finally: db.close()

@app.post("/api/doctor/patients/{patient_id}/fhir-export")
def fhir_export(patient_id: int, payload: FHIRExportRequest, request: Request):
    actor = authenticate_request(request)
    db=SessionLocal()
    try:
        authorize_interoperability_patient(actor, patient_id, db)
        bundle=build_fhir_bundle(db, patient_id)
        if payload.abha_address:
            bundle.setdefault("meta", {}).setdefault("tag", []).append({"system":"https://abdm.gov.in/abha-address","code":"linked-demo","display":payload.abha_address})
        rec=FHIRExportRecord(patient_id=patient_id, exported_by=actor["id"], resource_type="Bundle", bundle_id=bundle["id"])
        db.add(rec); db.commit(); db.refresh(rec)
        return {"message":"FHIR-ready bundle generated","export_id":rec.id,"bundle":bundle}
    finally: db.close()

# ---------- Phase 4A adaptive clinical interview engine ----------

COMMON_QUESTIONS = [
    {"id": "chief_complaint", "section": "Presenting complaint", "text": "What is the main problem or symptom that brought you here today? Please describe it in your own words."},
    {"id": "onset", "section": "History of present illness", "text": "When did this problem start? Did it begin suddenly or gradually?"},
    {"id": "location", "section": "History of present illness", "text": "Where exactly do you feel the problem or symptom? Does it spread anywhere else?"},
    {"id": "severity", "section": "History of present illness", "text": "How severe is it right now on a scale from 0 to 10, where 0 is no discomfort and 10 is the worst you can imagine?"},
    {"id": "character", "section": "History of present illness", "text": "How would you describe the symptom—for example sharp, dull, burning, throbbing, tight, heavy, or something else?"},
]

PATHWAYS = {
    "chest_pain": {
        "label": "Chest discomfort pathway",
        "keywords": ["chest pain", "chest discomfort", "chest pressure", "chest tightness", "pain in chest"],
        "questions": [
            {"id": "chest_radiation", "section": "Focused chest history", "text": "Does the discomfort spread to your arm, shoulder, jaw, back, or neck?"},
            {"id": "chest_exertion", "section": "Focused chest history", "text": "Does it get worse with walking, climbing stairs, or other physical activity? Does it improve with rest?"},
            {"id": "chest_breathlessness", "section": "Focused chest history", "text": "Are you having breathlessness, unusual sweating, dizziness, fainting, or a feeling that your heart is racing?"},
        ],
    },
    "headache": {
        "label": "Headache pathway",
        "keywords": ["headache", "head pain", "migraine", "pain in my head"],
        "questions": [
            {"id": "headache_visual", "section": "Focused headache history", "text": "Have you had blurred vision, flashing lights, weakness, numbness, difficulty speaking, or trouble walking with the headache?"},
            {"id": "headache_nausea", "section": "Focused headache history", "text": "Have you had nausea, vomiting, sensitivity to light or sound, or a similar headache before?"},
            {"id": "headache_trigger", "section": "Focused headache history", "text": "Did anything trigger or worsen the headache, such as exertion, coughing, lack of sleep, stress, or a recent injury?"},
        ],
    },
    "abdominal_pain": {
        "label": "Abdominal pain pathway",
        "keywords": ["stomach pain", "abdominal pain", "belly pain", "abdomen pain", "pain in my stomach"],
        "questions": [
            {"id": "abdominal_food", "section": "Focused abdominal history", "text": "Does the pain change after eating, passing stool, or taking any medicine?"},
            {"id": "abdominal_bowel", "section": "Focused abdominal history", "text": "Have you had vomiting, diarrhea, constipation, blood or black stool, or a change in your usual bowel habits?"},
            {"id": "abdominal_urinary", "section": "Focused abdominal history", "text": "Have you had pain or burning while urinating, blood in the urine, or pain going toward your back or groin?"},
        ],
    },
    "fever": {
        "label": "Fever pathway",
        "keywords": ["fever", "high temperature", "temperature", "feverish", "chills"],
        "questions": [
            {"id": "fever_pattern", "section": "Focused fever history", "text": "When you have checked your temperature, what was the highest reading? Does the fever come and go or stay present?"},
            {"id": "fever_infection", "section": "Focused fever history", "text": "Have you had cough, sore throat, breathing difficulty, vomiting, diarrhea, burning urine, rash, or any other signs of infection?"},
            {"id": "fever_exposure", "section": "Focused fever history", "text": "Have you recently travelled, eaten unusual food, been around someone who was ill, or had an insect or animal exposure?"},
        ],
    },
    "respiratory": {
        "label": "Breathing symptom pathway",
        "keywords": ["cough", "breathlessness", "shortness of breath", "difficulty breathing", "breathing problem", "wheezing"],
        "questions": [
            {"id": "respiratory_cough", "section": "Focused respiratory history", "text": "If you have a cough, is it dry or with phlegm? If there is phlegm, what colour is it? Have you noticed blood?"},
            {"id": "respiratory_activity", "section": "Focused respiratory history", "text": "Is the breathing difficulty worse with activity, when lying down, or at night? Does it happen suddenly or gradually?"},
            {"id": "respiratory_wheeze", "section": "Focused respiratory history", "text": "Have you had wheezing, chest tightness, fever, or known asthma or other lung problems?"},
        ],
    },
    "general": {
        "label": "General symptom pathway",
        "keywords": [],
        "questions": [
            {"id": "general_change", "section": "Focused symptom history", "text": "What makes the symptom better or worse? Have you tried anything for it, and did that help?"},
            {"id": "general_impact", "section": "Focused symptom history", "text": "How is this problem affecting your sleep, eating, work, movement, or normal daily activities?"},
        ],
    },
}

CLOSING_QUESTIONS = [
    {"id": "associated", "section": "Associated symptoms", "text": "Have you noticed any other symptoms along with this problem? Please mention anything that feels relevant."},
    {"id": "past_history", "section": "Past history", "text": "Do you have any existing medical conditions or have you had any important illnesses or surgeries in the past?"},
    {"id": "medications", "section": "Drug history", "text": "Are you currently taking any medicines, supplements, or other treatments?"},
    {"id": "allergies", "section": "Allergy history", "text": "Do you have any known medicine, food, or other allergies? If yes, what happens when you are exposed to them?"},
    {"id": "family_history", "section": "Family history", "text": "Does anyone in your close family have important medical conditions such as diabetes, high blood pressure, heart disease, asthma, or similar problems?"},
    {"id": "personal_history", "section": "Personal history", "text": "Is there anything about your daily habits that may be relevant, such as sleep, diet, exercise, tobacco, alcohol, occupation, or stress?"},
    {"id": "review_systems", "section": "Review of systems", "text": "Before we finish, have you recently had fever, unusual weight change, breathing difficulty, chest discomfort, vomiting, bowel or urinary changes, dizziness, or any other new symptom?"},
]



# ---------- Phase 4C.1 multilingual clinical interview layer ----------
SUPPORTED_LANGUAGES = {
    "en-IN": {"label": "English", "short": "English"},
    "hi-IN": {"label": "हिन्दी", "short": "हिन्दी"},
    "bn-IN": {"label": "বাংলা", "short": "বাংলা"},
}

# UI question translations. Clinical field IDs remain language-neutral so the
# physician-facing record stays standardized.
QUESTION_TRANSLATIONS = {
    "hi-IN": {
        "chief_complaint": "आज आपको यहां आने की मुख्य समस्या या तकलीफ़ क्या है? अपने शब्दों में बताएं।",
        "onset": "यह समस्या कब शुरू हुई? क्या यह अचानक शुरू हुई या धीरे-धीरे?",
        "location": "यह समस्या या तकलीफ़ आपको ठीक कहां महसूस होती है? क्या यह कहीं और फैलती है?",
        "severity": "अभी यह तकलीफ़ 0 से 10 में कितनी है, जहां 0 का मतलब कोई तकलीफ़ नहीं और 10 सबसे ज्यादा है?",
        "character": "आप इस तकलीफ़ को कैसे बताएंगे—जैसे तेज़, जलन, धड़कन जैसी, जकड़न, भारीपन या कुछ और?",
        "chest_radiation": "क्या यह तकलीफ़ हाथ, कंधे, जबड़े, पीठ या गर्दन तक फैलती है?",
        "chest_exertion": "क्या चलने, सीढ़ियां चढ़ने या मेहनत करने पर यह बढ़ती है? क्या आराम करने पर कम होती है?",
        "chest_breathlessness": "क्या सांस फूलना, असामान्य पसीना, चक्कर, बेहोशी या दिल तेजी से धड़कने जैसा महसूस हो रहा है?",
        "associated": "क्या इस समस्या के साथ कोई और लक्षण भी हैं? जो भी महत्वपूर्ण लगे, बताएं।",
        "past_history": "क्या आपको कोई पुरानी बीमारी है या पहले कोई महत्वपूर्ण बीमारी या ऑपरेशन हुआ है?",
        "medications": "क्या आप अभी कोई दवा, सप्लीमेंट या अन्य उपचार ले रहे हैं?",
        "allergies": "क्या आपको किसी दवा, भोजन या अन्य चीज़ से एलर्जी है? अगर हां, तो क्या होता है?",
        "family_history": "क्या आपके करीबी परिवार में मधुमेह, हाई ब्लड प्रेशर, हृदय रोग, अस्थमा या ऐसी कोई बीमारी है?",
        "personal_history": "आपकी रोज़मर्रा की आदतों में ऐसी कोई बात है जो महत्वपूर्ण हो सकती है—जैसे नींद, भोजन, व्यायाम, तंबाकू, शराब, काम या तनाव?",
        "review_systems": "अंत में, क्या हाल में बुखार, वजन में बदलाव, सांस लेने में तकलीफ़, सीने में परेशानी, उल्टी, मल या पेशाब में बदलाव, चक्कर या कोई नया लक्षण हुआ है?",
        "headache_visual": "क्या सिरदर्द के साथ धुंधला दिखना, चमकती रोशनी, कमजोरी, सुन्नपन, बोलने या चलने में परेशानी हुई है?",
        "headache_nausea": "क्या मितली, उल्टी, रोशनी या आवाज़ से परेशानी, या पहले ऐसा ही सिरदर्द हुआ है?",
        "headache_trigger": "क्या मेहनत, खांसी, नींद की कमी, तनाव या हाल की चोट से सिरदर्द शुरू या बढ़ा?",
        "abdominal_food": "क्या खाना खाने, मल त्यागने या कोई दवा लेने के बाद दर्द बदलता है?",
        "abdominal_bowel": "क्या उल्टी, दस्त, कब्ज, मल में खून या काला मल, या मल त्याग की आदत में बदलाव हुआ है?",
        "abdominal_urinary": "क्या पेशाब करते समय दर्द या जलन, पेशाब में खून, या दर्द पीठ या जांघ के बीच की ओर जाता है?",
        "fever_pattern": "तापमान नापने पर सबसे अधिक कितना आया? बुखार आता-जाता है या लगातार रहता है?",
        "fever_infection": "क्या खांसी, गले में दर्द, सांस लेने में परेशानी, उल्टी, दस्त, पेशाब में जलन, दाने या संक्रमण के अन्य लक्षण हैं?",
        "fever_exposure": "क्या हाल में यात्रा की, कोई असामान्य भोजन खाया, किसी बीमार व्यक्ति के संपर्क में आए या कीड़े/जानवर के संपर्क में आए?",
        "respiratory_cough": "अगर खांसी है, तो सूखी है या बलगम के साथ? बलगम हो तो उसका रंग क्या है? क्या उसमें खून दिखा?",
        "respiratory_activity": "सांस लेने में परेशानी मेहनत, लेटने या रात में बढ़ती है? यह अचानक होती है या धीरे-धीरे?",
        "respiratory_wheeze": "क्या घरघराहट, सीने में जकड़न, बुखार, अस्थमा या फेफड़ों की कोई बीमारी रही है?",
        "general_change": "इस लक्षण को क्या बेहतर या बदतर करता है? आपने इसके लिए कुछ किया या दवा ली? उससे फायदा हुआ?",
        "general_impact": "यह समस्या आपकी नींद, भोजन, काम, चलने-फिरने या रोज़मर्रा की गतिविधियों को कैसे प्रभावित कर रही है?",
    },
}

# Additional UI translations for the clinical interview. The backend keeps the IDs in
# English so analytics/doctor review remain language-neutral.
QUESTION_TRANSLATIONS.update({
 "bn-IN": {
  "chief_complaint":"আজ আপনাকে এখানে আসার প্রধান সমস্যা বা উপসর্গ কী? নিজের ভাষায় বলুন।","onset":"এই সমস্যা কবে শুরু হয়েছে? হঠাৎ নাকি ধীরে ধীরে শুরু হয়েছিল?","location":"সমস্যা বা উপসর্গটি ঠিক কোথায় অনুভব করেন? অন্য কোথাও ছড়িয়ে যায় কি?","severity":"এখন অস্বস্তি ০ থেকে ১০-এর মধ্যে কত, যেখানে ০ মানে নেই এবং ১০ সবচেয়ে বেশি?","character":"উপসর্গটি কেমন—তীক্ষ্ণ, মৃদু, জ্বালাপোড়া, ধুকপুক, চাপ বা অন্য কিছু?","associated":"এই সমস্যার সঙ্গে আর কোনো উপসর্গ হয়েছে কি? গুরুত্বপূর্ণ মনে হলে বলুন।","past_history":"আপনার কোনো পুরনো রোগ আছে, বা আগে গুরুত্বপূর্ণ অসুখ/অপারেশন হয়েছে কি?","medications":"আপনি কি এখন কোনো ওষুধ, সাপ্লিমেন্ট বা অন্য চিকিৎসা নিচ্ছেন?","allergies":"কোনো ওষুধ, খাবার বা অন্য কিছুর অ্যালার্জি আছে কি? থাকলে কী হয়?","family_history":"পরিবারের কাছের কারও ডায়াবেটিস, উচ্চ রক্তচাপ, হৃদরোগ, হাঁপানি বা অন্য গুরুত্বপূর্ণ রোগ আছে কি?","personal_history":"ঘুম, খাবার, ব্যায়াম, তামাক, অ্যালকোহল, কাজ বা স্ট্রেসের মতো দৈনন্দিন অভ্যাসে গুরুত্বপূর্ণ কিছু আছে কি?","review_systems":"শেষে, সম্প্রতি জ্বর, ওজনের পরিবর্তন, শ্বাসকষ্ট, বুকের অস্বস্তি, বমি, পায়খানা/প্রস্রাবে পরিবর্তন, মাথা ঘোরা বা অন্য নতুন উপসর্গ হয়েছে কি?"
 },
 "gu-IN": {
  "chief_complaint":"આજે અહીં આવવાનું મુખ્ય કારણ અથવા તકલીફ શું છે? તમારા પોતાના શબ્દોમાં જણાવો.","onset":"આ તકલીફ ક્યારે શરૂ થઈ? અચાનક કે ધીમે ધીમે?","location":"તકલીફ તમને ચોક્કસ ક્યાં થાય છે? તે બીજી જગ્યાએ ફેલાય છે?","severity":"હમણાં તકલીફ ૦ થી ૧૦માં કેટલી છે, જ્યાં ૦ એટલે કશું નહીં અને ૧૦ સૌથી વધારે?","character":"તકલીફ કેવી લાગે છે—તીક્ષ્ણ, ધીમી, બળતરા, ધબકારા, જકડાણ, ભારેપણું કે કંઈક બીજું?","associated":"આ તકલીફ સાથે બીજાં કોઈ લક્ષણો છે? મહત્વનું લાગે તે જણાવો.","past_history":"તમને કોઈ જૂની બીમારી છે અથવા પહેલાં કોઈ ગંભીર બીમારી/ઓપરેશન થયું છે?","medications":"તમે હાલમાં કોઈ દવા, સપ્લિમેન્ટ અથવા બીજી સારવાર લો છો?","allergies":"કોઈ દવા, ખોરાક અથવા અન્ય વસ્તુથી એલર્જી છે? હોય તો શું થાય છે?","family_history":"નજીકના પરિવારમાં ડાયાબિટીસ, હાઈ બ્લડ પ્રેશર, હૃદયરોગ, દમ અથવા બીજી મહત્વની બીમારી છે?","personal_history":"ઊંઘ, ખોરાક, કસરત, તમાકુ, દારૂ, કામ અથવા તણાવ જેવી દૈનિક આદતોમાં કંઈ મહત્વનું છે?","review_systems":"અંતમાં, તાજેતરમાં તાવ, વજનમાં ફેરફાર, શ્વાસની તકલીફ, છાતીમાં અસ્વસ્થતા, ઉલટી, મળ/પેશાબમાં ફેરફાર, ચક્કર અથવા બીજું નવું લક્ષણ થયું છે?"
 },
 "ta-IN": {
  "chief_complaint":"இன்று இங்கு வருவதற்கான முக்கிய பிரச்சனை அல்லது அறிகுறி என்ன? உங்கள் சொந்த வார்த்தைகளில் கூறுங்கள்.","onset":"இந்த பிரச்சனை எப்போது தொடங்கியது? திடீரென்று அல்லது மெதுவாக?","location":"இந்த பிரச்சனை அல்லது அறிகுறி சரியாக எங்கு உணரப்படுகிறது? வேறு இடத்துக்கு பரவுகிறதா?","severity":"இப்போது இந்த அசௌகரியம் 0 முதல் 10 வரை எவ்வளவு? 0 என்றால் இல்லை, 10 என்றால் மிகவும் அதிகம்.","character":"இந்த அறிகுறியை எப்படி விவரிப்பீர்கள்—கூர்மையானது, மந்தமானது, எரிச்சல், துடிப்பு, இறுக்கம், கனத்தது அல்லது வேறு ஏதாவது?","associated":"இந்த பிரச்சனையுடன் வேறு அறிகுறிகள் உள்ளனவா? முக்கியமாகத் தோன்றுவதைச் சொல்லுங்கள்.","past_history":"உங்களுக்கு ஏதேனும் பழைய நோய் உள்ளதா அல்லது முன்பு முக்கியமான நோய்/அறுவை சிகிச்சை நடந்ததா?","medications":"தற்போது ஏதேனும் மருந்து, சப்ப்ளிமென்ட் அல்லது வேறு சிகிச்சை எடுத்துக்கொள்கிறீர்களா?","allergies":"மருந்து, உணவு அல்லது வேறு ஏதாவது பொருளுக்கு ஒவ்வாமை உள்ளதா? இருந்தால் என்ன ஆகிறது?","family_history":"உங்கள் நெருங்கிய குடும்பத்தில் சர்க்கரை நோய், உயர் இரத்த அழுத்தம், இதய நோய், ஆஸ்துமா அல்லது வேறு முக்கிய நோய் உள்ளதா?","personal_history":"தூக்கம், உணவு, உடற்பயிற்சி, புகையிலை, மது, வேலை அல்லது மன அழுத்தம் போன்ற தினசரி பழக்கங்களில் முக்கியமான ஏதாவது உள்ளதா?","review_systems":"முடிப்பதற்கு முன், சமீபத்தில் காய்ச்சல், எடை மாற்றம், மூச்சுத்திணறல், மார்பு அசௌகரியம், வாந்தி, மலம்/சிறுநீர் மாற்றம், தலைசுற்றல் அல்லது வேறு புதிய அறிகுறி இருந்ததா?"
 },
 "te-IN": {
  "chief_complaint":"ఈరోజు ఇక్కడికి రావడానికి ప్రధాన సమస్య లేదా లక్షణం ఏమిటి? మీ మాటల్లో చెప్పండి.","onset":"ఈ సమస్య ఎప్పుడు మొదలైంది? అకస్మాత్తుగా లేదా క్రమంగా?","location":"ఈ సమస్య లేదా లక్షణం మీకు ఖచ్చితంగా ఎక్కడ అనిపిస్తుంది? మరెక్కడికైనా వ్యాపిస్తుందా?","severity":"ప్రస్తుతం ఈ అసౌకర్యం 0 నుంచి 10లో ఎంత? 0 అంటే లేదు, 10 అంటే చాలా ఎక్కువ.","character":"ఈ లక్షణాన్ని ఎలా వివరిస్తారు—తీవ్రంగా, మెల్లగా, మంటగా, కొట్టుకుంటున్నట్టు, బిగుతుగా, భారంగా లేదా వేరేలా?","associated":"ఈ సమస్యతో పాటు మరే ఇతర లక్షణాలు ఉన్నాయా? ముఖ్యంగా అనిపించినవి చెప్పండి.","past_history":"మీకు ఏదైనా పాత వ్యాధి ఉందా లేదా గతంలో ముఖ్యమైన అనారోగ్యం/ఆపరేషన్ జరిగిందా?","medications":"మీరు ప్రస్తుతం ఏదైనా మందులు, సప్లిమెంట్లు లేదా ఇతర చికిత్స తీసుకుంటున్నారా?","allergies":"ఏదైనా మందు, ఆహారం లేదా ఇతర వస్తువుకు అలర్జీ ఉందా? ఉంటే ఏమవుతుంది?","family_history":"మీ దగ్గరి కుటుంబంలో మధుమేహం, అధిక రక్తపోటు, గుండె జబ్బు, ఆస్తమా లేదా ఇతర ముఖ్యమైన వ్యాధి ఉందా?","personal_history":"నిద్ర, ఆహారం, వ్యాయామం, పొగాకు, మద్యం, పని లేదా ఒత్తిడి వంటి రోజువారీ అలవాట్లలో ముఖ్యమైన విషయం ఏదైనా ఉందా?","review_systems":"చివరగా, ఇటీవల జ్వరం, బరువు మార్పు, శ్వాస ఇబ్బంది, ఛాతి అసౌకర్యం, వాంతులు, మలం/మూత్ర మార్పులు, తల తిరగడం లేదా కొత్త లక్షణం ఏదైనా ఉందా?"
 },
 "mr-IN": {
  "chief_complaint":"आज येथे येण्याचे मुख्य कारण किंवा त्रास काय आहे? तुमच्या शब्दांत सांगा.","onset":"हा त्रास कधी सुरू झाला? अचानक की हळूहळू?","location":"हा त्रास किंवा लक्षण नेमके कुठे जाणवते? दुसरीकडे पसरते का?","severity":"सध्या हा त्रास 0 ते 10 मध्ये किती आहे? 0 म्हणजे नाही आणि 10 म्हणजे सर्वाधिक.","character":"हा त्रास कसा वाटतो—तीव्र, बोथट, जळजळ, ठणका, घट्टपणा, जडपणा किंवा काही वेगळा?","associated":"या त्रासासोबत आणखी काही लक्षणे आहेत का? महत्त्वाचे वाटत असल्यास सांगा.","past_history":"तुम्हाला कोणता जुना आजार आहे का किंवा पूर्वी महत्त्वाचा आजार/शस्त्रक्रिया झाली आहे का?","medications":"तुम्ही सध्या कोणती औषधे, सप्लिमेंट्स किंवा इतर उपचार घेत आहात का?","allergies":"औषध, अन्न किंवा इतर कशाची अॅलर्जी आहे का? असल्यास काय होते?","family_history":"जवळच्या कुटुंबात मधुमेह, उच्च रक्तदाब, हृदयरोग, दमा किंवा इतर महत्त्वाचा आजार आहे का?","personal_history":"झोप, आहार, व्यायाम, तंबाखू, दारू, काम किंवा ताण यांसारख्या दैनंदिन सवयींबद्दल काही महत्त्वाचे आहे का?","review_systems":"शेवटी, अलीकडे ताप, वजनातील बदल, श्वास घेण्यास त्रास, छातीत अस्वस्थता, उलटी, शौच/लघवीतील बदल, चक्कर किंवा इतर नवीन लक्षण झाले आहे का?"
 },
 "kn-IN": {
  "chief_complaint":"ಇಂದು ಇಲ್ಲಿಗೆ ಬರಲು ಮುಖ್ಯ ಕಾರಣವಾದ ಸಮಸ್ಯೆ ಅಥವಾ ಲಕ್ಷಣ ಏನು? ನಿಮ್ಮದೇ ಮಾತಿನಲ್ಲಿ ಹೇಳಿ.","onset":"ಈ ಸಮಸ್ಯೆ ಯಾವಾಗ ಆರಂಭವಾಯಿತು? ಏಕಾಏಕಿ ಅಥವಾ ನಿಧಾನವಾಗಿ?","location":"ಈ ಸಮಸ್ಯೆ ಅಥವಾ ಲಕ್ಷಣ ನಿಮಗೆ ನಿಖರವಾಗಿ ಎಲ್ಲಿ ಅನುಭವವಾಗುತ್ತದೆ? ಬೇರೆಡೆಗೆ ಹರಡುತ್ತದೆಯೇ?","severity":"ಈಗ ಅಸೌಕರ್ಯ 0 ರಿಂದ 10ರಲ್ಲಿ ಎಷ್ಟು? 0 ಎಂದರೆ ಇಲ್ಲ, 10 ಎಂದರೆ ಅತ್ಯಂತ ಹೆಚ್ಚು.","character":"ಈ ಲಕ್ಷಣವನ್ನು ಹೇಗೆ ವಿವರಿಸುತ್ತೀರಿ—ತೀಕ್ಷ್ಣ, ಮಂದ, ಉರಿ, ಬಡಿತದಂತೆ, ಬಿಗಿತ, ಭಾರ ಅಥವಾ ಬೇರೆ ರೀತಿಯಲ್ಲಿ?","associated":"ಈ ಸಮಸ್ಯೆಯ ಜೊತೆಗೆ ಬೇರೆ ಯಾವುದೇ ಲಕ್ಷಣಗಳಿವೆಯೇ? ಮುಖ್ಯವೆನಿಸಿದುದನ್ನು ಹೇಳಿ.","past_history":"ನಿಮಗೆ ಯಾವುದೇ ಹಳೆಯ ಕಾಯಿಲೆ ಇದೆಯೇ ಅಥವಾ ಹಿಂದೆ ಪ್ರಮುಖ ಕಾಯಿಲೆ/ಶಸ್ತ್ರಚಿಕಿತ್ಸೆ ಆಗಿದೆಯೇ?","medications":"ನೀವು ಈಗ ಯಾವುದೇ ಔಷಧಿ, ಸಪ್ಲಿಮೆಂಟ್ ಅಥವಾ ಬೇರೆ ಚಿಕಿತ್ಸೆ ಪಡೆಯುತ್ತಿದ್ದೀರಾ?","allergies":"ಯಾವುದೇ ಔಷಧಿ, ಆಹಾರ ಅಥವಾ ಬೇರೆ ವಸ್ತುವಿಗೆ ಅಲರ್ಜಿ ಇದೆಯೇ? ಇದ್ದರೆ ಏನಾಗುತ್ತದೆ?","family_history":"ನಿಮ್ಮ ಹತ್ತಿರದ ಕುಟುಂಬದಲ್ಲಿ ಮಧುಮೇಹ, ಅಧಿಕ ರಕ್ತದೊತ್ತಡ, ಹೃದಯ ಕಾಯಿಲೆ, ಆಸ್ತಮಾ ಅಥವಾ ಬೇರೆ ಪ್ರಮುಖ ಕಾಯಿಲೆ ಇದೆಯೇ?","personal_history":"ನಿದ್ರೆ, ಆಹಾರ, ವ್ಯಾಯಾಮ, ತಂಬಾಕು, ಮದ್ಯ, ಕೆಲಸ ಅಥವಾ ಒತ್ತಡದಂತಹ ದೈನಂದಿನ ಅಭ್ಯಾಸಗಳಲ್ಲಿ ಮುಖ್ಯವಾದ ಏನಾದರೂ ಇದೆಯೇ?","review_systems":"ಕೊನೆಯಲ್ಲಿ, ಇತ್ತೀಚೆಗೆ ಜ್ವರ, ತೂಕದ ಬದಲಾವಣೆ, ಉಸಿರಾಟದ ತೊಂದರೆ, ಎದೆ ಅಸೌಕರ್ಯ, ವಾಂತಿ, ಮಲ/ಮೂತ್ರ ಬದಲಾವಣೆ, ತಲೆಸುತ್ತು ಅಥವಾ ಬೇರೆ ಹೊಸ ಲಕ್ಷಣ ಇದೆಯೇ?"
 }
})

QUESTION_TRANSLATIONS["bn-IN"] = {
    "chief_complaint": "আজ এখানে আসার প্রধান সমস্যা বা উপসর্গ কী? নিজের ভাষায় বলুন।",
    "onset": "এই সমস্যা কবে শুরু হয়েছে? হঠাৎ নাকি ধীরে ধীরে শুরু হয়েছিল?",
    "location": "সমস্যা বা উপসর্গটি ঠিক কোথায় অনুভব করছেন? অন্য কোথাও ছড়ায় কি?",
    "severity": "এখন এই সমস্যা ০ থেকে ১০-এর মধ্যে কতটা তীব্র? ০ মানে কোনো অস্বস্তি নেই এবং ১০ মানে সবচেয়ে বেশি।",
    "character": "এই সমস্যাটি কেমন লাগে—তীক্ষ্ণ, মৃদু, জ্বালা, ধুকপুক, চাপ বা ভারী, নাকি অন্যরকম?",
    "chest_radiation": "অস্বস্তি কি হাত, কাঁধ, চোয়াল, পিঠ বা ঘাড়ে ছড়িয়ে পড়ে?",
    "chest_exertion": "হাঁটা, সিঁড়ি ওঠা বা পরিশ্রমে কি এটি বাড়ে? বিশ্রাম নিলে কি কমে?",
    "chest_breathlessness": "শ্বাসকষ্ট, অস্বাভাবিক ঘাম, মাথা ঘোরা, অজ্ঞান হওয়া বা হৃদস্পন্দন খুব দ্রুত হওয়ার অনুভূতি কি হচ্ছে?",
    "associated": "এই সমস্যার সঙ্গে আর কোনো উপসর্গ আছে কি? গুরুত্বপূর্ণ মনে হলে বলুন।",
    "past_history": "আপনার কি কোনো পুরনো রোগ আছে বা আগে গুরুত্বপূর্ণ কোনো অসুস্থতা বা অস্ত্রোপচার হয়েছিল?",
    "medications": "আপনি কি বর্তমানে কোনো ওষুধ, সাপ্লিমেন্ট বা অন্য চিকিৎসা নিচ্ছেন?",
    "allergies": "কোনো ওষুধ, খাবার বা অন্য কিছুর প্রতি অ্যালার্জি আছে কি? থাকলে কী হয়?",
    "family_history": "আপনার কাছের পরিবারের কারও ডায়াবেটিস, উচ্চ রক্তচাপ, হৃদরোগ, হাঁপানি বা অন্য গুরুত্বপূর্ণ রোগ আছে কি?",
    "personal_history": "ঘুম, খাবার, ব্যায়াম, তামাক, মদ্যপান, কাজ বা মানসিক চাপের মতো দৈনন্দিন অভ্যাসে গুরুত্বপূর্ণ কিছু আছে কি?",
    "review_systems": "শেষে, সম্প্রতি জ্বর, ওজনের পরিবর্তন, শ্বাসকষ্ট, বুকে অস্বস্তি, বমি, পায়খানা বা প্রস্রাবে পরিবর্তন, মাথা ঘোরা বা অন্য নতুন উপসর্গ হয়েছে কি?",
    "headache_visual": "মাথাব্যথার সঙ্গে ঝাপসা দেখা, আলো ঝলকানো, দুর্বলতা, অসাড়তা, কথা বলা বা হাঁটতে সমস্যা হয়েছে কি?",
    "headache_nausea": "বমি বমি ভাব, বমি, আলো বা শব্দে অস্বস্তি, অথবা আগে একই ধরনের মাথাব্যথা হয়েছে কি?",
    "headache_trigger": "পরিশ্রম, কাশি, ঘুমের অভাব, মানসিক চাপ বা সাম্প্রতিক আঘাতে মাথাব্যথা শুরু বা বেড়েছে কি?",
    "abdominal_food": "খাওয়ার পরে, পায়খানা করার পরে বা কোনো ওষুধ নিলে ব্যথা কি বদলে যায়?",
    "abdominal_bowel": "বমি, ডায়রিয়া, কোষ্ঠকাঠিন্য, পায়খানায় রক্ত বা কালো পায়খানা, অথবা পায়খানার অভ্যাসে পরিবর্তন হয়েছে কি?",
    "abdominal_urinary": "প্রস্রাবের সময় ব্যথা বা জ্বালা, প্রস্রাবে রক্ত, অথবা ব্যথা পিঠ বা কুঁচকির দিকে যায় কি?",
    "fever_pattern": "তাপমাত্রা মাপলে সর্বোচ্চ কত ছিল? জ্বর আসে-যায় নাকি সব সময় থাকে?",
    "fever_infection": "কাশি, গলা ব্যথা, শ্বাসকষ্ট, বমি, ডায়রিয়া, প্রস্রাবে জ্বালা, র‍্যাশ বা সংক্রমণের অন্য লক্ষণ আছে কি?",
    "fever_exposure": "সম্প্রতি কোথাও ভ্রমণ করেছেন, অস্বাভাবিক খাবার খেয়েছেন, অসুস্থ কারও কাছে ছিলেন বা পোকা/পশুর সংস্পর্শে এসেছেন কি?",
    "respiratory_cough": "কাশি থাকলে সেটি শুকনো নাকি কফসহ? কফ থাকলে কী রঙের? কফে রক্ত দেখেছেন কি?",
    "respiratory_activity": "শ্বাসকষ্ট কি পরিশ্রমে, শুয়ে থাকলে বা রাতে বেশি হয়? হঠাৎ নাকি ধীরে ধীরে হয়?",
    "respiratory_wheeze": "শ্বাসে সাঁই সাঁই শব্দ, বুকে চাপ, জ্বর, হাঁপানি বা অন্য ফুসফুসের সমস্যা হয়েছে কি?",
    "general_change": "কী করলে এই উপসর্গ কমে বা বাড়ে? কিছু চেষ্টা করেছেন কি, এবং তাতে উপকার হয়েছে কি?",
    "general_impact": "এই সমস্যা আপনার ঘুম, খাওয়া, কাজ, চলাফেরা বা দৈনন্দিন কাজে কীভাবে প্রভাব ফেলছে?",
}

# Common clinical keywords in major Indian languages, including common Hinglish.
PATHWAY_KEYWORDS_MULTI = {
    "chest_pain": ["सीने में दर्द", "सीने में तकलीफ", "छाती में दर्द", "छाती में तकलीफ़", "বুকে ব্যথা", "மார்பு வலி", "ఛాతి నొప్పి", "छातीत दुखणे", "છાતીમાં દુખાવો", "ಎದೆ ನೋವು", "chest me dard", "seene mein dard", "seene me dard"],
    "headache": ["सिरदर्द", "सिर में दर्द", "মাথাব্যথা", "মাথায় ব্যথা", "தலைவலி", "తలనొప్పి", "डोकेदुखी", "માથાનો દુખાવો", "ತಲೆನೋವು", "sir dard", "sar dard"],
    "abdominal_pain": ["पेट में दर्द", "पेट दर्द", "पेट की तकलीफ", "পেটে ব্যথা", "வயிற்று வலி", "కడుపు నొప్పి", "पोटदुखी", "પેટમાં દુખાવો", "ಹೊಟ್ಟೆ ನೋವು", "pet me dard", "stomach me dard"],
    "fever": ["बुखार", "तेज बुखार", "तापमान", "জ্বর", "জ্বর আসছে", "காய்ச்சல்", "జ్వరం", "ताप", "ताप येणे", "તાવ", "ಜ್ವರ", "bukhar", "fever"],
    "respiratory": ["खांसी", "सांस फूलना", "सांस लेने में दिक्कत", "सांस की तकलीफ", "কাশি", "শ্বাসকষ্ট", "இருமல்", "மூச்சுத்திணறல்", "దగ్గు", "శ్వాస తీసుకోవడంలో ఇబ్బంది", "खोकला", "श्वास घेण्यास त्रास", "ઉધરસ", "શ્વાસ લેવામાં તકલીફ", "ಕೆಮ್ಮು", "ಉಸಿರಾಟದ ತೊಂದರೆ", "khansi", "saans phoolna", "saans lene me dikkat"],
}

NEGATION_MULTI = ["no ", "not ", "without ", "नहीं", "नही", "कोई नहीं", "नहीं है", "नाही", "नाही आहे", "নেই", "না ", "இல்லை", "కాదు", "లేదు", "नसणे", "નથી", "ಇಲ್ಲ"]

def localize_question(question: dict, language: str):
    q = dict(question)
    if language in QUESTION_TRANSLATIONS and q["id"] in QUESTION_TRANSLATIONS[language]:
        q["text"] = QUESTION_TRANSLATIONS[language][q["id"]]
    return q


def classify_pathway(text: str) -> str:
    lowered = text.lower().strip()
    for name, pathway in PATHWAYS.items():
        if any(keyword in lowered for keyword in pathway["keywords"]):
            return name
    for name, keywords in PATHWAY_KEYWORDS_MULTI.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return name
    return "general"


def build_question_flow(pathway_name: str):
    pathway = PATHWAYS.get(pathway_name, PATHWAYS["general"])
    return COMMON_QUESTIONS + pathway["questions"] + CLOSING_QUESTIONS


def extract_structured(question_id, answer, language='en-IN'):
    """Lightweight Phase 4A extraction. A model can replace this function later."""
    text = answer.strip()
    result = {"raw": text}
    direct_map = {
        "chief_complaint": "chief_complaint", "onset": "onset", "location": "location",
        "character": "character", "associated": "associated", "past_history": "past_history",
        "medications": "medications", "allergies": "allergies", "family_history": "family_history",
        "personal_history": "personal_history", "review_systems": "review_systems",
        "chest_radiation": "chest_radiation", "chest_exertion": "chest_exertion",
        "chest_breathlessness": "chest_breathlessness", "headache_visual": "headache_visual",
        "headache_nausea": "headache_nausea", "headache_trigger": "headache_trigger",
        "abdominal_food": "abdominal_food", "abdominal_bowel": "abdominal_bowel",
        "abdominal_urinary": "abdominal_urinary", "fever_pattern": "fever_pattern",
        "fever_infection": "fever_infection", "fever_exposure": "fever_exposure",
        "respiratory_cough": "respiratory_cough", "respiratory_activity": "respiratory_activity",
        "respiratory_wheeze": "respiratory_wheeze", "general_change": "general_change",
        "general_impact": "general_impact",
    }
    if question_id == "severity":
        nums = re.findall(r"\b(?:10|[0-9])\b", text)
        result["severity"] = int(nums[0]) if nums else text
    elif question_id in direct_map:
        result[direct_map[question_id]] = text

    # AI-1B: add conservative semantic evidence without overwriting explicit
    # question answers. The raw answer remains available for verification.
    semantic = extract_clinical_entities(text, language=language)
    if semantic.get("positive_symptoms"):
        result["detected_symptoms"] = semantic["positive_symptoms"]
    if semantic.get("negated_symptoms"):
        result["negated_symptoms"] = semantic["negated_symptoms"]
    if semantic.get("duration_mentions"):
        result["duration_mentions"] = semantic["duration_mentions"]
    if semantic.get("severity") is not None and "severity" not in result:
        result["severity_label"] = semantic["severity"]
    result["nlu"] = {
        "intent": semantic.get("intent", "general"),
        "evidence": semantic.get("evidence", []),
        "engine": semantic.get("engine"),
    }
    return result


# ---------- Phase 4B red-flag safety engine ----------
# This is a triage-support prototype, not a diagnostic system. Rules intentionally
# produce review alerts rather than diagnoses.

RED_FLAG_RULES = [
    {
        "id": "severe_breathing_difficulty",
        "level": "emergency",
        "label": "Severe breathing difficulty",
        "questions": {"chief_complaint", "chest_breathlessness", "respiratory_activity", "respiratory_wheeze", "review_systems"},
        "keywords": ["cannot breathe", "can't breathe", "unable to breathe", "struggling to breathe", "severe shortness of breath", "severe breathlessness"],
        "message": "The response describes severe breathing difficulty and should be reviewed urgently by clinical staff."
    },
    {
        "id": "chest_pain_radiation",
        "level": "urgent",
        "label": "Chest discomfort with possible radiation",
        "questions": {"chest_radiation"},
        "keywords": ["left arm", "right arm", "both arms", "jaw", "neck", "back", "shoulder"],
        "message": "Chest discomfort with reported spread to another area warrants prompt clinical review."
    },
    {
        "id": "chest_pain_associated_symptoms",
        "level": "urgent",
        "label": "Chest discomfort with concerning associated symptoms",
        "questions": {"chest_breathlessness", "review_systems"},
        "keywords": ["sweating", "cold sweat", "fainting", "passed out", "shortness of breath", "breathless", "difficulty breathing", "racing heart"],
        "message": "Chest-related symptoms with breathlessness, fainting, marked sweating, or palpitations warrant prompt clinical review."
    },
    {
        "id": "neurological_deficit",
        "level": "urgent",
        "label": "New neurological symptoms",
        "questions": {"headache_visual", "review_systems"},
        "keywords": ["weakness on one side", "one sided weakness", "one-sided weakness", "numbness on one side", "difficulty speaking", "cannot speak", "trouble speaking", "trouble walking", "new weakness", "new numbness"],
        "message": "New neurological symptoms should be reviewed promptly by clinical staff."
    },
    {
        "id": "sudden_severe_headache",
        "level": "urgent",
        "label": "Sudden severe headache",
        "questions": {"onset", "headache_trigger", "chief_complaint"},
        "keywords": ["worst headache", "worst ever", "sudden severe headache", "thunderclap", "explosive headache"],
        "message": "A sudden or exceptionally severe headache warrants prompt clinical assessment."
    },
    {
        "id": "gi_bleeding",
        "level": "urgent",
        "label": "Possible gastrointestinal bleeding",
        "questions": {"abdominal_bowel", "review_systems"},
        "keywords": ["vomiting blood", "blood in vomit", "black stool", "black stools", "blood in stool", "bloody stool"],
        "message": "Reported gastrointestinal bleeding requires prompt clinical review."
    },
    {
        "id": "severe_abdominal_symptoms",
        "level": "urgent",
        "label": "Severe abdominal symptoms",
        "questions": {"abdominal_bowel", "abdominal_urinary", "chief_complaint"},
        "keywords": ["severe abdominal pain", "severe stomach pain", "fainting with abdominal pain", "rigid abdomen"],
        "message": "Severe abdominal symptoms warrant prompt clinical assessment."
    },
    {
        "id": "persistent_high_fever",
        "level": "urgent",
        "label": "High or persistent fever",
        "questions": {"fever_pattern"},
        "keywords": ["very high fever", "persistent high fever", "104", "105", "106"],
        "message": "The reported fever pattern may require prompt clinical review, especially if the patient is very unwell."
    },
]


# Add common Hindi/Hinglish expressions to the safety layer without changing
# the rule IDs or clinical thresholds.
for _rule in RED_FLAG_RULES:
    _extra = {
        "severe_breathing_difficulty": ["सांस नहीं आ रही", "सांस लेने में बहुत दिक्कत", "बहुत ज्यादा सांस फूलना", "saans nahi aa rahi", "saans lene me bahut dikkat"],
        "chest_pain_radiation": ["बाएं हाथ", "बांह", "जबड़े", "गर्दन", "पीठ", "कंधे", "baaye haath", "baazu"],
        "chest_pain_associated_symptoms": ["पसीना", "बेहोशी", "सांस फूलना", "दिल तेज धड़कना", "pasina", "behoshi", "saans phoolna", "dil tez dhadakna"],
        "neurological_deficit": ["एक तरफ कमजोरी", "एक तरफ सुन्न", "बोलने में दिक्कत", "चलने में दिक्कत", "एक तरफ कमजोरी", "ek taraf kamzori", "bolne me dikkat"],
        "sudden_severe_headache": ["जिंदगी का सबसे तेज सिरदर्द", "अचानक बहुत तेज सिरदर्द", "achanak bahut tez sir dard"],
        "gi_bleeding": ["खून की उल्टी", "उल्टी में खून", "काला मल", "मल में खून", "khoon ki ulti", "kaala mal"],
        "severe_abdominal_symptoms": ["बहुत तेज पेट दर्द", "पेट में बहुत तेज दर्द", "bahut tez pet dard"],
        "persistent_high_fever": ["बहुत तेज बुखार", "लगातार तेज बुखार", "bahut tez bukhar", "lagatar tez bukhar"],
    }.get(_rule["id"], [])
    _rule["keywords"].extend(_extra)


def _is_negated(text: str, start: int) -> bool:
    """Simple local negation guard for phrases such as 'no chest pain' or 'not breathless'."""
    prefix = text[max(0, start - 60):start]
    return bool(re.search(r"\b(no|not|without|denies|deny|never|neither)\b|नहीं|नही|कोई नहीं|नाही|নেই|না|இல்லை|కాదు|లేదు|નથી|ಇಲ್ಲ", prefix))


def _keyword_hit(text: str, keyword: str):
    for match in re.finditer(re.escape(keyword), text):
        if not _is_negated(text, match.start()):
            return True
    return False


def detect_red_flags(question_id: str, answer: str, structured: dict):
    """Evaluate the current answer plus already collected answers.

    Returns unique, explainable alerts. Severity is deliberately limited to
    none / watch / urgent / emergency and does not represent a diagnosis.
    """
    all_text = " ".join(str(v) for v in structured.values() if v not in (None, ""))
    all_text += " " + answer
    all_text = re.sub(r"\s+", " ", all_text.lower()).strip()

    alerts = []
    for rule in RED_FLAG_RULES:
        if question_id not in rule["questions"] and not (rule["questions"] & set(structured.keys())):
            continue
        for keyword in rule["keywords"]:
            if _keyword_hit(all_text, keyword.lower()):
                alerts.append({
                    "id": rule["id"],
                    "level": rule["level"],
                    "label": rule["label"],
                    "message": rule["message"],
                })
                break

    # Cross-answer patterns: a single answer may be mild, but combinations can
    # justify a higher-priority review alert.
    chest = " ".join(str(structured.get(k, "")) for k in ("chief_complaint", "chest_radiation", "chest_breathlessness", "chest_exertion"))
    chest = (chest + " " + answer).lower()
    has_chest = any(_keyword_hit(chest, x) for x in ("chest pain", "chest discomfort", "chest pressure", "chest tightness"))
    has_breath = any(_keyword_hit(chest, x) for x in ("shortness of breath", "breathless", "difficulty breathing", "breathlessness"))
    has_sweat = any(_keyword_hit(chest, x) for x in ("sweating", "cold sweat"))
    has_radiation = any(_keyword_hit(chest, x) for x in ("left arm", "right arm", "both arms", "jaw", "back", "neck"))
    if has_chest and (has_breath and (has_sweat or has_radiation)):
        alerts.append({
            "id": "chest_multi_symptom_pattern",
            "level": "emergency",
            "label": "Chest symptoms with multiple concerning features",
            "message": "The combination of chest symptoms and multiple concerning features should be reviewed urgently by clinical/triage staff."
        })

    priority = {"none": 0, "watch": 1, "urgent": 2, "emergency": 3}
    alerts = {a["id"]: a for a in alerts}
    ordered = sorted(alerts.values(), key=lambda x: priority[x["level"]], reverse=True)
    level = ordered[0]["level"] if ordered else "none"
    return level, ordered


def _adaptive_known_slots(answered: dict) -> set:
    known = set()
    for key, value in answered.items():
        if key in {
            "chief_complaint","onset","location","severity","character",
            "chest_radiation","chest_exertion","chest_breathlessness",
            "headache_visual","headache_nausea","headache_trigger",
            "abdominal_food","abdominal_bowel","abdominal_urinary",
            "fever_pattern","fever_infection","fever_exposure",
            "respiratory_cough","respiratory_activity","respiratory_wheeze",
            "general_change","general_impact","associated","past_history",
            "medications","allergies","family_history","personal_history","review_systems"
        } and value not in (None, "", [], {}):
            known.add(key)
    evidence = answered.get("clinical_evidence", [])
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                if item.get("duration_mentions"): known.add("onset")
                if item.get("severity") is not None: known.add("severity")
    return known

QUESTION_PRIORITY = {
    "chief_complaint": 100, "onset": 90, "location": 88, "severity": 86, "character": 84,
    "chest_breathlessness": 99, "chest_radiation": 96, "chest_exertion": 94,
    "headache_visual": 98, "headache_trigger": 84, "headache_nausea": 82,
    "abdominal_bowel": 88, "abdominal_urinary": 80, "abdominal_food": 78,
    "fever_infection": 92, "fever_pattern": 90, "fever_exposure": 70,
    "respiratory_activity": 92, "respiratory_cough": 88, "respiratory_wheeze": 84,
    "general_change": 76, "general_impact": 68, "allergies": 65, "associated": 62,
    "medications": 60, "past_history": 58, "family_history": 42, "personal_history": 38, "review_systems": 30,
}

def adaptive_next_question(pathway_name: str, answered: dict):
    flow = build_question_flow(pathway_name)
    known = _adaptive_known_slots(answered)
    skipped = set(answered.get("__skipped_questions", []) or [])
    candidates = []
    focused_ids = {q["id"] for q in PATHWAYS.get(pathway_name, {}).get("questions", [])}
    for index, question in enumerate(flow):
        qid = question["id"]
        if qid in answered or qid in known or qid in skipped:
            continue
        score = QUESTION_PRIORITY.get(qid, 20)
        if qid in focused_ids:
            score += 12
        if qid == "chief_complaint" and "chief_complaint" not in known:
            score += 1000
        candidates.append((score, -index, question))
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if not candidates:
        return None, flow, {"adaptive": True, "known_slots": sorted(known), "reason": "sufficient_information_for_current_flow"}
    score, _, question = candidates[0]
    return question, flow, {
        "adaptive": True,
        "known_slots": sorted(known),
        "selected_score": score,
        "candidate_count": len(candidates),
        "reason": "highest_priority_unanswered_information",
    }

def next_question_for(pathway_name: str, answered: dict):
    question, flow, _meta = adaptive_next_question(pathway_name, answered)
    return question, flow


def _json_loads(value, default):
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def get_or_create_handoff_encounter(db, patient_id: int, language: str | None = None):
    """Return today's active encounter and ensure it is routed to a clinician.

    The prototype uses the existing Encounter relationship as the handoff
    boundary. If the patient has no active encounter today, the first active
    General Medicine doctor is used for deterministic demo routing. Production
    deployments should replace this with hospital triage/assignment logic.
    """
    today = date.today().isoformat()
    encounter = (db.query(Encounter)
                 .filter(Encounter.patient_id == patient_id,
                         Encounter.visit_date == today,
                         Encounter.status.in_(["waiting", "called", "in_consultation"]))
                 .order_by(Encounter.created_at.desc())
                 .first())
    if encounter:
        if language in SUPPORTED_LANGUAGES:
            encounter.language = language
        if encounter.doctor_id is None:
            doctor = (db.query(User).join(DoctorProfile, DoctorProfile.user_id == User.id)
                     .filter(User.role == "doctor", DoctorProfile.active == 1, DoctorProfile.department == encounter.department)
                     .order_by(User.id).first())
            if doctor is None:
                doctor = (db.query(User).join(DoctorProfile, DoctorProfile.user_id == User.id)
                         .filter(User.role == "doctor", DoctorProfile.active == 1)
                         .order_by(User.id).first())
            if doctor:
                encounter.doctor_id = doctor.id
        if encounter.doctor_id is None:
            raise HTTPException(status_code=409, detail="No active clinician is available to receive this clinical history.")
        return encounter

    doctor = (db.query(User).join(DoctorProfile, DoctorProfile.user_id == User.id)
             .filter(User.role == "doctor", DoctorProfile.active == 1)
             .order_by(User.id).first())
    if not doctor:
        raise HTTPException(status_code=409, detail="No active clinician is available to receive this clinical history.")

    department = "General Medicine"
    profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == doctor.id).first()
    if profile and profile.department:
        department = profile.department
    max_token = (db.query(Encounter)
                 .filter(Encounter.visit_date == today, Encounter.department == department)
                 .order_by(Encounter.token_number.desc()).first())
    token = (max_token.token_number + 1) if max_token else 1
    encounter = Encounter(
        patient_id=patient_id, doctor_id=doctor.id, department=department,
        language=language if language in SUPPORTED_LANGUAGES else "en-IN",
        visit_date=today, token_number=token, priority="normal",
        status="waiting", reason="AI-assisted clinical history"
    )
    db.add(encounter)
    db.flush()
    return encounter


def get_or_create_interview_state(db, patient_id: int, session_id: str, language: str = "en-IN", encounter_id: int | None = None):
    state = db.query(InterviewState).filter(InterviewState.session_id == session_id).first()
    if state:
        if state.patient_id != patient_id:
            raise HTTPException(status_code=403, detail="Interview session does not belong to this patient.")
        if encounter_id is not None and state.encounter_id not in (None, encounter_id):
            raise HTTPException(status_code=403, detail="Interview session does not belong to this encounter.")
        if encounter_id is not None and state.encounter_id is None:
            state.encounter_id = encounter_id
        if language in SUPPORTED_LANGUAGES and state.language != language and state.status == "active":
            state.language = language
        return state
    patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    state = InterviewState(
        patient_id=patient_id, encounter_id=encounter_id, session_id=session_id,
        language=language if language in SUPPORTED_LANGUAGES else "en-IN",
        structured_data=json.dumps({}, ensure_ascii=False),
        answered_question_ids=json.dumps([]), conversation=json.dumps([]),
        red_flags=json.dumps([]),
    )
    # The session_id is UNIQUE. Do the insert inside a savepoint so a
    # concurrent request that wins the race does not poison the outer
    # transaction. After the IntegrityError, read the row created by the
    # concurrent transaction and continue using that same state.
    try:
        with db.begin_nested():
            db.add(state)
            db.flush()
    except IntegrityError:
        state = db.query(InterviewState).filter(
            InterviewState.session_id == session_id
        ).first()
        if not state:
            # The conflicting row should be visible once the concurrent
            # transaction has committed. Re-raise rather than creating a
            # different session or duplicate state.
            raise
        if state.patient_id != patient_id:
            raise HTTPException(
                status_code=403,
                detail="Interview session does not belong to this patient.",
            )
        if (
            language in SUPPORTED_LANGUAGES
            and state.language != language
            and state.status == "active"
        ):
            state.language = language
    return state


def interview_state_response(state: InterviewState):
    current_question = None
    if state.current_question_id:
        flow = build_question_flow(state.pathway or "general")
        current_question = next((q for q in flow if q.get("id") == state.current_question_id), None)
        if current_question:
            current_question = localize_question(current_question, state.language or "en-IN")
    return {
        "session_id": state.session_id,
        "patient_id": state.patient_id,
        "encounter_id": state.encounter_id,
        "language": state.language,
        "pathway": state.pathway,
        "current_question_id": state.current_question_id,
        "current_question": current_question,
        "status": state.status,
        "structured": _json_loads(state.structured_data, {}),
        "answered_question_ids": _json_loads(state.answered_question_ids, []),
        "conversation": _json_loads(state.conversation, []),
        "risk_level": state.risk_level or "none",
        "red_flags": _json_loads(state.red_flags, []),
        "version": state.version,
        "repair_count": state.repair_count or 0,
        "voice_failure_count": state.voice_failure_count or 0,
        "last_input_mode": state.last_input_mode or "text",
        "last_repair_action": state.last_repair_action,
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }



# ---------- Phase 5C: Real AI / NLP layer ----------
# A small locally trained text classifier is bundled for the hackathon demo.
# It is deliberately used for complaint/pathway understanding, not diagnosis.
NLP_TRAIN_TEXTS = [
    "chest pain pressure tightness discomfort heart pain", "pain in chest while walking", "chest pain sweating",
    "headache migraine head pain dizziness", "severe headache with nausea", "pain behind eyes",
    "stomach pain abdominal pain bloating gas", "abdominal discomfort after food", "loose motions stomach cramps",
    "fever temperature chills body ache", "high fever and chills", "feeling feverish",
    "cough cold sore throat breathing difficulty", "shortness of breath wheezing cough", "phlegm congestion",
    "back pain joint pain muscle ache", "knee pain shoulder pain", "body pain after activity",
    "tired fatigue weakness low energy", "poor sleep insomnia stress", "loss of appetite weakness",
    "skin itching rash redness", "acne skin irritation", "itchy patches",
    "urine burning frequent urination", "pain while passing urine", "urinary discomfort",
    "anxiety worry nervousness", "feeling stressed unable to relax", "low mood emotional distress",
]
NLP_TRAIN_LABELS = [
    "chest","chest","chest","headache","headache","headache","abdominal","abdominal","abdominal",
    "fever","fever","fever","respiratory","respiratory","respiratory","pain","pain","pain",
    "general","general","general","skin","skin","skin","urinary","urinary","urinary","mental_wellbeing","mental_wellbeing","mental_wellbeing"
]
NLP_MODEL = None
if SKLEARN_AVAILABLE:
    try:
        NLP_MODEL = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1,2), lowercase=True, sublinear_tf=True)),
            ("clf", LogisticRegression(max_iter=1000, random_state=42)),
        ])
        NLP_MODEL.fit(NLP_TRAIN_TEXTS, NLP_TRAIN_LABELS)
    except Exception:
        NLP_MODEL = None

NLP_SYMPTOMS = {
    "chest pain": ["chest pain", "chest discomfort", "chest pressure", "chest tightness"],
    "headache": ["headache", "head pain", "migraine"],
    "dizziness": ["dizziness", "dizzy", "lightheaded", "light headed"],
    "nausea": ["nausea", "nauseous", "vomiting", "vomit"],
    "abdominal pain": ["stomach pain", "abdominal pain", "belly pain", "abdominal discomfort"],
    "bloating": ["bloating", "bloated", "gas"],
    "fever": ["fever", "feverish", "high temperature", "temperature"],
    "cough": ["cough", "coughing"],
    "shortness of breath": ["shortness of breath", "breathless", "difficulty breathing", "breathing difficulty"],
    "wheeze": ["wheeze", "wheezing"],
    "sore throat": ["sore throat", "throat pain"],
    "fatigue": ["fatigue", "tired", "tiredness", "low energy", "weakness"],
    "sleep disturbance": ["poor sleep", "insomnia", "cannot sleep", "can't sleep", "sleep disturbance"],
    "anxiety/stress": ["anxiety", "anxious", "stress", "stressed", "worry", "nervous"],
    "skin rash/itching": ["rash", "itching", "itchy", "skin irritation"],
    "urinary symptoms": ["burning urination", "burning while urinating", "frequent urination", "urine burning"],
    "back/joint pain": ["back pain", "joint pain", "knee pain", "shoulder pain", "muscle ache"],
    "diarrhea": ["diarrhea", "loose motions", "loose stools"],
    "appetite change": ["loss of appetite", "poor appetite", "increased appetite"],
}
NLP_NEGATIONS = ["no ", "not ", "without ", "never ", "don't ", "do not ", "didn't ", "did not ", "nahi ", "nahin ", "नहीं "]

def _normalize_nlp_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def _negated(text: str, start: int) -> bool:
    window = text[max(0, start-35):start]
    return any(n in window for n in NLP_NEGATIONS)

def analyze_nlp_text(text: str, language: str = "en-IN"):
    raw = text or ""
    normalized = _normalize_nlp_text(raw)
    symptoms=[]
    for canonical, variants in NLP_SYMPTOMS.items():
        for term in variants:
            pos=normalized.find(term)
            if pos >= 0:
                if not _negated(normalized, pos):
                    symptoms.append({"term": canonical, "mention": term, "negated": False})
                else:
                    symptoms.append({"term": canonical, "mention": term, "negated": True})
                break
    # temporal expressions are extracted as evidence, not interpreted as diagnosis.
    durations=[]
    duration_patterns=[
        r"\b(?:for|since)\s+((?:\d+|one|two|three|four|five|six|seven|a|an))\s*(day|days|week|weeks|month|months|year|years)\b",
        r"\b(\d+)\s*(day|days|week|weeks|month|months|year|years)\s*(?:ago|se pehle)\b",
        r"\b(since yesterday|since last night|since morning|for a long time)\b",
    ]
    for pat in duration_patterns:
        durations.extend(m.group(0) for m in re.finditer(pat, normalized, re.I))
    severity=None
    sev_map={"mild":["mild","slight","little"],"moderate":["moderate","medium"],"severe":["severe","very painful","worst","extreme","unbearable"]}
    for level, terms in sev_map.items():
        if any(t in normalized for t in terms): severity=level; break
    if NLP_MODEL:
        try:
            probs=NLP_MODEL.predict_proba([normalized])[0]
            classes=NLP_MODEL.classes_
            idx=probs.argmax()
            model_intent=str(classes[idx]); confidence=round(float(probs[idx]),3)
        except Exception:
            model_intent,confidence="general",0.0
    else:
        model_intent,confidence="general",0.0
    # Resolve an explicit symptom cluster into the nearest history pathway, while
    # preserving the raw ML prediction so the demo can show both signals.
    symptom_to_pathway={
        "chest pain":"chest","headache":"headache","dizziness":"headache","nausea":"abdominal",
        "abdominal pain":"abdominal","bloating":"abdominal","fever":"fever","cough":"respiratory",
        "shortness of breath":"respiratory","wheeze":"respiratory","sore throat":"respiratory",
        "fatigue":"general","sleep disturbance":"general","anxiety/stress":"mental_wellbeing",
        "skin rash/itching":"skin","urinary symptoms":"urinary","back/joint pain":"pain",
        "diarrhea":"abdominal","appetite change":"general"
    }
    positive=[x["term"] for x in symptoms if not x["negated"]]
    resolved=intent = symptom_to_pathway.get(positive[0], model_intent) if positive else model_intent
    return {
        "engine": "TF-IDF + Logistic Regression + clinical NLP rules",
        "model_available": bool(NLP_MODEL),
        "intent": intent,
        "model_intent": model_intent,
        "confidence": confidence,
        "confidence_semantics": confidence_semantics("classifier_score"),
        "symptoms": symptoms,
        "positive_symptoms": [x["term"] for x in symptoms if not x["negated"]],
        "negated_symptoms": [x["term"] for x in symptoms if x["negated"]],
        "duration_mentions": durations,
        "severity": severity,
        "language": language,
        "text_normalized": normalized,
        "disclaimer": "AI/NLP extraction supports clinical history organization; it is not a diagnosis or treatment recommendation."
    }

@app.post("/api/nlp/analyze")
def nlp_analyze(payload: dict):
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required for NLP analysis.")
    return analyze_nlp_text(text, str(payload.get("language", "en-IN")))


# -----------------------------------------------------------------------------
# Phase AI-1B: conservative clinical language understanding
# -----------------------------------------------------------------------------
@app.post("/api/ai/clinical-understand")
def clinical_understand(payload: ClinicalNLURequest):
    if payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language. Choose one of: {', '.join(SUPPORTED_LANGUAGES)}")
    return extract_clinical_entities(payload.text, payload.language)


# -----------------------------------------------------------------------------
# Phase 5F: Validation
# A small, transparent, versioned benchmark for the prototype NLP layer.
# These are synthetic test cases for engineering/demo validation, not clinical
# ground truth and not a substitute for prospective clinical validation.
# -----------------------------------------------------------------------------
VALIDATION_DATASET_VERSION = "5F.1"
VALIDATION_CASES = [
    {"id":"V01","text":"I have a headache and feel dizzy.","intent":"headache","symptoms":["headache","dizziness"]},
    {"id":"V02","text":"My chest hurts and I have chest pain.","intent":"chest","symptoms":["chest pain"]},
    {"id":"V03","text":"I have been coughing for three days.","intent":"respiratory","symptoms":["cough"]},
    {"id":"V04","text":"I feel short of breath and wheezy.","intent":"respiratory","symptoms":["shortness of breath","wheeze"]},
    {"id":"V05","text":"I have nausea and abdominal pain.","intent":"abdominal","symptoms":["nausea","abdominal pain"]},
    {"id":"V06","text":"I have bloating after meals.","intent":"abdominal","symptoms":["bloating"]},
    {"id":"V07","text":"I have had a fever since yesterday.","intent":"fever","symptoms":["fever"]},
    {"id":"V08","text":"I feel tired and exhausted all day.","intent":"general","symptoms":["fatigue"]},
    {"id":"V09","text":"My sleep has been disturbed for two weeks.","intent":"general","symptoms":["sleep disturbance"]},
    {"id":"V10","text":"I am feeling anxious and stressed lately.","intent":"mental_wellbeing","symptoms":["anxiety/stress"]},
    {"id":"V11","text":"I have an itchy skin rash.","intent":"skin","symptoms":["skin rash/itching"]},
    {"id":"V12","text":"I have burning and urinary symptoms.","intent":"urinary","symptoms":["urinary symptoms"]},
    {"id":"V13","text":"My back and joints hurt.","intent":"pain","symptoms":["back/joint pain"]},
    {"id":"V14","text":"I have diarrhea and nausea.","intent":"abdominal","symptoms":["diarrhea","nausea"]},
    {"id":"V15","text":"I do not have chest pain or shortness of breath.","intent":"general","symptoms":["chest pain","shortness of breath"],"negated":["chest pain","shortness of breath"]},
    {"id":"V16","text":"No headache today, but I feel fatigued.","intent":"general","symptoms":["headache","fatigue"],"negated":["headache"]},
    {"id":"V17","text":"I have a severe headache.","intent":"headache","symptoms":["headache"],"severity":"severe"},
    {"id":"V18","text":"Mild cough for one week.","intent":"respiratory","symptoms":["cough"],"severity":"mild"},
    {"id":"V19","text":"Moderate abdominal pain for five days.","intent":"abdominal","symptoms":["abdominal pain"],"severity":"moderate"},
    {"id":"V20","text":"My appetite has changed recently.","intent":"general","symptoms":["appetite change"]},
]

def _f1(p, r):
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)

def run_validation_suite():
    rows=[]
    tp=fp=fn=0
    intent_correct=0
    neg_correct=0
    neg_total=0
    severity_correct=0
    severity_total=0
    duration_total=0
    duration_found=0
    for case in VALIDATION_CASES:
        pred=analyze_nlp_text(case["text"], "en-IN")
        predicted=set(pred.get("positive_symptoms",[]))
        expected=set(case.get("symptoms",[])) - set(case.get("negated",[]))
        tp_i=len(predicted & expected); fp_i=len(predicted-expected); fn_i=len(expected-predicted)
        tp+=tp_i; fp+=fp_i; fn+=fn_i
        intent_ok=pred.get("intent")==case["intent"]
        intent_correct += int(intent_ok)
        expected_neg=set(case.get("negated",[])); predicted_neg=set(pred.get("negated_symptoms",[]))
        neg_correct += len(expected_neg & predicted_neg)
        neg_total += len(expected_neg)
        if "severity" in case:
            severity_total+=1; severity_correct+=int(pred.get("severity")==case["severity"])
        if "for " in case["text"].lower() or "since " in case["text"].lower():
            duration_total+=1; duration_found+=int(bool(pred.get("duration_mentions")))
        rows.append({"id":case["id"],"expected_intent":case["intent"],"predicted_intent":pred.get("intent"),"intent_correct":intent_ok,"expected_symptoms":sorted(expected),"predicted_symptoms":sorted(predicted),"expected_negated":sorted(expected_neg),"predicted_negated":sorted(predicted_neg),"confidence":round(float(pred.get("confidence",0)),4),"severity_expected":case.get("severity"),"severity_predicted":pred.get("severity"),"duration_detected":bool(pred.get("duration_mentions")),"pass": bool(intent_ok and predicted==expected and expected_neg.issubset(predicted_neg) and ("severity" not in case or pred.get("severity")==case["severity"]))})
    precision=tp/(tp+fp) if tp+fp else 0
    recall=tp/(tp+fn) if tp+fn else 0
    f1=_f1(precision,recall)
    return {"version":VALIDATION_DATASET_VERSION,"dataset_size":len(VALIDATION_CASES),"metrics":{"symptom_precision":round(precision,4),"symptom_recall":round(recall,4),"symptom_f1":round(f1,4),"intent_accuracy":round(intent_correct/len(VALIDATION_CASES),4),"negation_recall":round(neg_correct/neg_total,4) if neg_total else None,"severity_accuracy":round(severity_correct/severity_total,4) if severity_total else None,"duration_detection_rate":round(duration_found/duration_total,4) if duration_total else None},"counts":{"tp":tp,"fp":fp,"fn":fn,"intent_correct":intent_correct,"negation_correct":neg_correct,"negation_total":neg_total},"cases_passed":sum(1 for r in rows if r["pass"]),"cases_failed":sum(1 for r in rows if not r["pass"]),"cases":rows,"limitations":["Synthetic, hand-labelled engineering benchmark.","Not a clinical validation study and not diagnostic evidence.","Metrics measure this prototype's current rule/model behavior on this fixed dataset; new data is required for unbiased evaluation."]}

@app.get("/api/validation/summary")
def validation_summary():
    return run_validation_suite()

@app.post("/api/ai/safety-evaluate")
def ai_safety_evaluate(payload: dict):
    """AI-2: evaluate patient-reported information for prototype triage flags."""
    answer = str(payload.get("answer") or payload.get("text") or "").strip()
    if not answer:
        raise HTTPException(status_code=400, detail="answer or text is required")
    structured = payload.get("structured") or {}
    if not isinstance(structured, dict):
        raise HTTPException(status_code=400, detail="structured must be an object")
    return evaluate_safety(answer, structured)


@app.post("/api/validation/run")
def validation_run():
    return run_validation_suite()


@app.post("/api/ai/next-question")
def ai_next_question(payload: dict):
    answered = payload.get("structured") or payload.get("answered") or {}
    if not isinstance(answered, dict):
        raise HTTPException(status_code=400, detail="structured/answered must be an object.")
    pathway = str(payload.get("pathway") or classify_pathway(str(answered.get("chief_complaint", ""))))
    if pathway not in PATHWAYS:
        pathway = "general"
    language = str(payload.get("language", "en-IN"))
    if language not in SUPPORTED_LANGUAGES:
        language = "en-IN"
    question, flow, meta = adaptive_next_question(pathway, answered)
    return {
        "adaptive": True, "pathway": pathway,
        "pathway_label": PATHWAYS[pathway]["label"],
        "question": localize_question(question, language) if question else None,
        "completed": question is None, "meta": meta,
        "total_questions": len(flow),
        "answered_question_ids": [q["id"] for q in flow if q["id"] in answered],
        "disclaimer": "Question selection organizes clinical history; it is not diagnosis or treatment advice.",
    }


@app.post("/api/ai/orchestrate-turn")
def ai_orchestrate_turn(payload: dict, request: Request):
    actor = authenticate_request(request)
    authorize_patient(actor, int(payload.get("patient_id"))) if payload.get("patient_id") is not None else None
    """Run one complete AI-1F turn: repair -> clinical understanding -> state -> safety -> next question."""
    patient_id = payload.get("patient_id")
    session_id = str(payload.get("session_id", "")).strip()
    if not patient_id or not session_id:
        raise HTTPException(status_code=400, detail="patient_id and session_id are required.")
    language = str(payload.get("language", "en-IN"))
    if language not in SUPPORTED_LANGUAGES:
        language = "en-IN"
    text = str(payload.get("text", ""))
    event = str(payload.get("event", "answer"))
    attempt = int(payload.get("attempt", 0) or 0)
    question_id = str(payload.get("question_id", ""))

    db = SessionLocal()
    try:
        state = db.query(InterviewState).filter(InterviewState.session_id == session_id, InterviewState.patient_id == int(patient_id)).first()
        if state and state.encounter_id:
            encounter = db.query(Encounter).filter(Encounter.id == state.encounter_id, Encounter.patient_id == int(patient_id)).first()
            if not encounter:
                raise HTTPException(status_code=409, detail="Interview is linked to an unavailable encounter.")
            encounter.language = language
        else:
            encounter = get_or_create_handoff_encounter(db, int(patient_id), language)
        state = get_or_create_interview_state(db, int(patient_id), session_id, language, encounter.id)
        if state.status == "completed":
            raise HTTPException(status_code=409, detail="This interview has already been completed.")

        repair = analyze_repair(text, event=event, attempt=attempt, current_language=state.language)
        state.last_input_mode = str(payload.get("input_mode", "voice" if event != "answer" else "text"))

        # Repair actions do not mutate clinical meaning.
        if repair.get("action") != "accept_answer":
            if repair.get("action") == "switch_language" and repair.get("requested_language") in SUPPORTED_LANGUAGES:
                state.language = repair["requested_language"]
            state.repair_count = (state.repair_count or 0) + 1
            if repair.get("action") in {"voice_retry", "touch_fallback"}:
                state.voice_failure_count = (state.voice_failure_count or 0) + 1
            state.last_repair_action = repair.get("action")
            state.updated_at = utc_now()
            db.commit()
            next_q = None
            if state.current_question_id:
                flow = build_question_flow(state.pathway or "general")
                q = next((q for q in flow if q.get("id") == state.current_question_id), None)
                if q:
                    next_q = localize_question(q, state.language)
            response = build_turn_response(
                state=interview_state_response(state), repair=repair,
                next_question=next_q, risk_level=state.risk_level,
                red_flags=_json_loads(state.red_flags, []),
                localized_repair_message=localized_response(repair, state.language),
            )
            return response

        if not text.strip():
            raise HTTPException(status_code=400, detail="Answer text is required when accepting an answer.")

        answered = _json_loads(state.structured_data, {})
        extracted = extract_structured(question_id, text)
        for key, value in extracted.items():
            if key not in ("raw", "nlu") and value not in (None, ""):
                answered[key] = value
        semantic = extract_clinical_entities(text, state.language)
        ledger = answered.get("clinical_evidence", [])
        if not isinstance(ledger, list): ledger = []
        ledger.append({"question_id": question_id, "text": text.strip(),
                       "positive_symptoms": semantic.get("positive_symptoms", []),
                       "negated_symptoms": semantic.get("negated_symptoms", []),
                       "duration_mentions": semantic.get("duration_mentions", []),
                       "severity": semantic.get("severity"), "intent": semantic.get("intent", "general")})
        answered["clinical_evidence"] = ledger[-50:]

        if not state.pathway and answered.get("chief_complaint"):
            state.pathway = classify_pathway(answered["chief_complaint"])
        pathway = state.pathway or "general"
        risk_level, red_flags = detect_red_flags(question_id, text, answered)
        priority = {"none": 0, "watch": 1, "urgent": 2, "emergency": 3}
        if priority.get(state.risk_level or "none", 0) > priority.get(risk_level, 0):
            risk_level = state.risk_level
        old_flags = _json_loads(state.red_flags, [])
        merged = {x.get("id"): x for x in old_flags if x.get("id")}
        for flag in red_flags: merged[flag.get("id")] = flag
        red_flags = sorted(merged.values(), key=lambda x: priority.get(x.get("level", "none"), 0), reverse=True)
        state.risk_level = risk_level
        state.red_flags = json.dumps(red_flags, ensure_ascii=False)

        answered_ids = _json_loads(state.answered_question_ids, [])
        if question_id and question_id not in answered_ids: answered_ids.append(question_id)
        conversation = _json_loads(state.conversation, [])
        conversation.append({"question_id": question_id, "answer": text.strip(),
                             "extracted": {k:v for k,v in extracted.items() if k != "raw"}})
        next_q, flow = next_question_for(pathway, answered)
        state.current_question_id = next_q["id"] if next_q else None
        state.status = "completed" if next_q is None else "active"
        state.structured_data = json.dumps(answered, ensure_ascii=False)
        state.answered_question_ids = json.dumps(answered_ids, ensure_ascii=False)
        state.conversation = json.dumps(conversation, ensure_ascii=False)
        state.last_repair_action = None
        state.updated_at = utc_now()
        db.commit()

        localized_q = localize_question(next_q, state.language) if next_q else None
        return build_turn_response(
            state=interview_state_response(state),
            next_question=localized_q,
            risk_level=risk_level,
            red_flags=red_flags,
        )
    finally:
        db.close()


@app.get("/api/interview/questions")
def interview_questions(request: Request, patient_id: int, language: str = "en-IN", session_id: str = ""):
    if not request or patient_id is None:
        raise HTTPException(status_code=401, detail="Authenticated patient context is required to start the clinical interview.")
    actor = authenticate_request(request)
    authorize_interview_patient(actor, patient_id)
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language. Choose one of: {', '.join(SUPPORTED_LANGUAGES)}")
    db = SessionLocal()
    try:
        require_active_consent(db, patient_id)
        state = db.query(InterviewState).filter(InterviewState.session_id == session_id, InterviewState.patient_id == patient_id).first() if session_id else None
        if state and state.encounter_id:
            encounter = db.query(Encounter).filter(Encounter.id == state.encounter_id, Encounter.patient_id == patient_id).first()
            if not encounter:
                raise HTTPException(status_code=409, detail="Interview is linked to an unavailable encounter.")
            encounter.language = language
            state = get_or_create_interview_state(db, patient_id, session_id, language, encounter.id)
        else:
            encounter = get_or_create_handoff_encounter(db, patient_id, language)
            state = get_or_create_interview_state(db, patient_id, session_id, language, encounter.id) if session_id else None
        if state and not state.current_question_id:
            state.current_question_id = COMMON_QUESTIONS[0]["id"]
        db.commit()
        # SQLAlchemy expires ORM attributes on commit. Capture the small amount
        # of state needed for the response while the session is still open;
        # otherwise a brand-new interview can raise DetachedInstanceError after
        # the session closes.
        state_status = state.status if state else None
        state_question_id = state.current_question_id if state else None
        state_pathway = state.pathway if state else None
        state_language = state.language if state else language
    finally:
        db.close()
    first = localize_question(COMMON_QUESTIONS[0], language)
    if state and state_status == "active" and state_question_id:
        flow = build_question_flow(state_pathway or "general")
        resumed = next((q for q in flow if q.get("id") == state_question_id), None)
        if resumed:
            first = localize_question(resumed, state_language or language)
    intro = "I will first understand your main concern. Based on your answer, I will ask relevant follow-up questions and then collect the standard clinical history. This prototype supports text, voice and guided answers and does not diagnose disease."
    if language == "hi-IN":
        intro = "मैं पहले आपकी मुख्य समस्या समझूंगा। आपके जवाब के आधार पर मैं संबंधित सवाल पूछूंगा और फिर सामान्य क्लिनिकल इतिहास लूंगा। यह प्रोटोटाइप टेक्स्ट, आवाज़ और टैप करके जवाब देने की सुविधा देता है और बीमारी का निदान नहीं करता।"
    elif language == "bn-IN":
        intro = "প্রথমে আমরা আপনার প্রধান সমস্যাটি বুঝব। আপনার উত্তরের ভিত্তিতে প্রাসঙ্গিক প্রশ্ন করা হবে এবং তারপর সাধারণ চিকিৎসার ইতিহাস নেওয়া হবে। এই প্রোটোটাইপ রোগ নির্ণয় করে না।"
    return {"intro": intro, "question": first, "pathway": None, "adaptive": True, "language": language, "supported_languages": SUPPORTED_LANGUAGES, "message": "The next questions will adapt to your main complaint."}



@app.get("/api/interview/state/{session_id}")
def interview_state(session_id: str, patient_id: int, request: Request):
    actor = authenticate_request(request)
    authorize_interview_patient(actor, patient_id)
    """Resume an active AI-1A encounter from server-owned state."""
    db = SessionLocal()
    try:
        require_active_consent(db, patient_id)
        state = db.query(InterviewState).filter(InterviewState.session_id == session_id, InterviewState.patient_id == patient_id).first()
        if not state:
            raise HTTPException(status_code=404, detail="Interview session not found.")
        return interview_state_response(state)
    finally:
        db.close()



def _persist_completed_interview(db, patient, state):
    """Persist the completed patient interview as the clinician handoff record.

    This is intentionally idempotent for a session: completing the same interview
    twice updates/reuses the handoff consultation instead of creating duplicates.
    """
    structured = _json_loads(state.structured_data, {})
    usable = {
        k: v for k, v in structured.items()
        if not str(k).startswith("__") and k != "clinical_evidence" and v not in (None, "", [], {})
    }
    if not usable:
        raise HTTPException(status_code=400, detail="Please answer at least one question before completing the interview.")
    complaint = str(structured.get("chief_complaint") or "Clinical history").strip()[:120]
    combined = " ".join(str(v) for v in usable.values())
    nlp = analyze_nlp_text(combined, state.language or "en-IN") if combined else {}
    risk_level = state.risk_level or "none"
    red_flags = _json_loads(state.red_flags, [])
    if state.encounter_id:
        encounter = db.query(Encounter).filter(Encounter.id == state.encounter_id, Encounter.patient_id == patient.id).first()
        if not encounter:
            raise HTTPException(status_code=409, detail="Interview is linked to an unavailable encounter.")
        if encounter.language != (state.language or "en-IN"):
            encounter.language = state.language or "en-IN"
    else:
        encounter = get_or_create_handoff_encounter(db, patient.id, state.language or "en-IN")
        state.encounter_id = encounter.id
    structured.setdefault("language", state.language or "en-IN")
    structured.setdefault("care_type", encounter.care_type or "allopathy")
    physician_summary = generate_physician_summary(structured, risk_level, red_flags, nlp, patient=patient, encounter=encounter, documents=db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient.id).order_by(MedicalDocument.created_at.desc()).all())
    encounter.reason = complaint[:500]
    if risk_level == "emergency": encounter.priority = "emergency"
    elif risk_level == "urgent": encounter.priority = "urgent"
    existing = (db.query(Consultation)
                .filter(Consultation.patient_id == patient.id, Consultation.encounter_id == encounter.id)
                .order_by(Consultation.created_at.desc()).first())
    summary_parts = [f"Main complaint: {complaint}"]
    for key, label in (("onset","Onset"),("location","Location"),("severity","Severity"),("character","Character"),("associated","Associated symptoms"),("past_history","Past history"),("medications","Medications"),("allergies","Allergies")):
        value = structured.get(key)
        if value not in (None, "", [], {}): summary_parts.append(f"{label}: {value}")
    summary = " | ".join(summary_parts)
    if existing and (existing.consultation_status or "draft") != "completed":
        record = existing
        record.title = complaint or "Clinical history"
        record.consultation_type = "handoff"
        record.summary = summary
        record.status = "AI History — Physician Summary Ready"
        record.risk_level = risk_level
        record.red_flags = json.dumps(red_flags, ensure_ascii=False)
        record.structured_data = json.dumps(structured, ensure_ascii=False)
        record.nlp_data = json.dumps(nlp, ensure_ascii=False)
        record.ai_summary = json.dumps(physician_summary, ensure_ascii=False)
        record.ai_summary_generated_at = utc_now()
        record.updated_at = utc_now()
    else:
        record = Consultation(
            patient_id=patient.id, encounter_id=encounter.id,
            title=complaint or "Clinical history", consultation_type="handoff", summary=summary,
            status="Health history — summary ready", risk_level=risk_level,
            red_flags=json.dumps(red_flags, ensure_ascii=False),
            structured_data=json.dumps(structured, ensure_ascii=False),
            nlp_data=json.dumps(nlp, ensure_ascii=False),
            ai_summary=json.dumps(physician_summary, ensure_ascii=False),
            ai_summary_generated_at=utc_now(), consultation_status="draft",
        )
        db.add(record)
    db.commit(); db.refresh(record)
    return record, physician_summary


@app.post("/api/interview/answer")
def interview_answer(payload: InterviewAnswer, request: Request):
    actor = authenticate_request(request)
    authorize_interview_patient(actor, payload.patient_id)
    if not payload.skipped and not payload.answer.strip():
        raise HTTPException(status_code=400, detail="Please provide an answer or skip this question.")
    if payload.language not in SUPPORTED_LANGUAGES:
        payload.language = "en-IN"

    db = SessionLocal()
    try:
        require_active_consent(db, payload.patient_id)
        state = db.query(InterviewState).filter(InterviewState.session_id == payload.session_id, InterviewState.patient_id == payload.patient_id).first()
        if state and state.encounter_id:
            encounter = db.query(Encounter).filter(Encounter.id == state.encounter_id, Encounter.patient_id == payload.patient_id).first()
            if not encounter:
                raise HTTPException(status_code=409, detail="Interview is linked to an unavailable encounter.")
            encounter.language = payload.language
        else:
            encounter = get_or_create_handoff_encounter(db, payload.patient_id, payload.language)
        state = get_or_create_interview_state(db, payload.patient_id, payload.session_id, payload.language, encounter.id)
        if state.status == "completed":
            raise HTTPException(status_code=409, detail="This interview has already been completed.")

        # Server-owned memory is the source of truth. The browser's `answers`
        # payload is accepted only as a backward-compatible fallback for older
        # sessions; it is never allowed to overwrite stored fields silently.
        answered = _json_loads(state.structured_data, {})
        if not answered and payload.answers:
            answered.update(payload.answers)
        skipped_ids = answered.get("__skipped_questions", [])
        if not isinstance(skipped_ids, list):
            skipped_ids = []
        if payload.skipped and payload.question_id not in skipped_ids:
            skipped_ids.append(payload.question_id)
        answered["__skipped_questions"] = skipped_ids[-100:]

        extracted = {} if payload.skipped else extract_structured(payload.question_id, payload.answer, payload.language)
        for key, value in extracted.items():
            if key not in ("raw", "nlu") and value not in (None, ""):
                answered[key] = value

        # Keep a compact encounter-level evidence ledger for AI-1B. This is
        # additive and never replaces the patient's original wording.
        semantic = extract_clinical_entities(payload.answer, payload.language) if not payload.skipped else {"positive_symptoms": [], "negated_symptoms": [], "duration_mentions": [], "severity": None, "intent": "skipped"}
        evidence_ledger = answered.get("clinical_evidence", [])
        if not isinstance(evidence_ledger, list):
            evidence_ledger = []
        evidence_ledger.append({
            "question_id": payload.question_id,
            "question": next((q.get("text") for q in build_question_flow(state.pathway or classify_pathway(answered.get("chief_complaint", ""))) if q.get("id") == payload.question_id), ""),
            "text": payload.answer.strip(),
            "skipped": bool(payload.skipped),
            "input_mode": payload.input_mode if payload.input_mode in {"voice", "text", "card", "skipped", "hybrid"} else ("skipped" if payload.skipped else "text"),
            "positive_symptoms": semantic.get("positive_symptoms", []),
            "negated_symptoms": semantic.get("negated_symptoms", []),
            "duration_mentions": semantic.get("duration_mentions", []),
            "severity": semantic.get("severity"),
            "intent": semantic.get("intent", "general"),
        })
        # Determine the pathway before enriching the evidence ledger so the
        # stored question text is always the actual question asked.
        pathway_name = state.pathway or classify_pathway(answered.get("chief_complaint", ""))
        state.pathway = pathway_name
        evidence_ledger[-1]["question"] = next((q.get("text") for q in build_question_flow(pathway_name) if q.get("id") == payload.question_id), "")
        answered["clinical_evidence"] = evidence_ledger[-50:]

        # The complaint determines the pathway once it is known. We do not
        # change an established pathway on every subsequent answer.
        if not state.pathway:
            complaint = answered.get("chief_complaint", "")
            if complaint:
                state.pathway = classify_pathway(complaint)
        pathway_name = state.pathway or classify_pathway(answered.get("chief_complaint", ""))
        state.pathway = pathway_name

        nlp = analyze_nlp_text(payload.answer, payload.language)
        safety = evaluate_safety(payload.answer, answered)
        risk_level = safety["risk_level"]
        red_flags = safety["alerts"]

        # Preserve the highest risk already seen in this encounter.
        priority = {"none": 0, "watch": 1, "urgent": 2, "emergency": 3}
        if priority.get(state.risk_level or "none", 0) > priority.get(risk_level, 0):
            risk_level = state.risk_level
        else:
            state.risk_level = risk_level
        old_flags = _json_loads(state.red_flags, [])
        merged_flags = {x.get("id"): x for x in old_flags if x.get("id")}
        for flag in red_flags:
            merged_flags[flag.get("id")] = flag
        red_flags = sorted(merged_flags.values(), key=lambda x: priority.get(x.get("level", "none"), 0), reverse=True)
        state.red_flags = json.dumps(red_flags, ensure_ascii=False)

        answered_ids = _json_loads(state.answered_question_ids, [])
        if payload.question_id not in answered_ids:
            answered_ids.append(payload.question_id)

        conversation = _json_loads(state.conversation, [])
        conversation.append({
            "question_id": payload.question_id,
            "question": next((q.get("text") for q in build_question_flow(pathway_name) if q.get("id") == payload.question_id), ""),
            "answer": payload.answer.strip() if not payload.skipped else "",
            "skipped": bool(payload.skipped),
            "extracted": {k: v for k, v in extracted.items() if k != "raw"},
        })

        next_question, flow = next_question_for(pathway_name, answered)
        completed = next_question is None
        state.status = "completed" if completed else "active"
        state.current_question_id = next_question["id"] if next_question else None
        state.structured_data = json.dumps(answered, ensure_ascii=False)
        state.answered_question_ids = json.dumps(answered_ids, ensure_ascii=False)
        state.conversation = json.dumps(conversation, ensure_ascii=False)
        state.updated_at = utc_now()
        db.commit()

        completed_count = len(answered_ids)
        handoff = None
        handoff_summary = None
        if completed:
            # Completion must cross the persistence boundary here. The patient
            # should never reach Documents with a completed interview that the
            # doctor workspace cannot see.
            patient = db.query(User).filter(User.id == payload.patient_id, User.role == "patient").first()
            if not patient:
                raise HTTPException(status_code=404, detail="Patient not found.")
            handoff, handoff_summary = _persist_completed_interview(db, patient, state)
            state.status = "completed"
            db.commit()

        return {
            "message": "Answer received",
            "question_id": payload.question_id,
            "extracted": extracted,
            "nlp": nlp,
            "pathway": pathway_name,
            "pathway_label": PATHWAYS[pathway_name]["label"],
            "next_question": localize_question(next_question, payload.language) if next_question else None,
            "completed": completed,
            "language": payload.language,
            "progress": round((completed_count / len(flow)) * 100),
            "question_number": completed_count + (0 if completed else 1),
            "total_questions": len(flow),
            "risk_level": risk_level,
            "red_flags": red_flags,
            "safety": safety,
            "consultation_id": handoff.id if handoff else None,
            "ai_summary": handoff_summary,
            "state": interview_state_response(state),
            "safety_message": (
                "Urgent clinical review is recommended based on the responses so far."
                if risk_level in ("urgent", "emergency") else
                "No safety rule matched the information collected so far. This does not mean the patient is medically safe; clinical review remains required."
            ),
        }
    finally:
        db.close()


def _get_whisper_model():
    global _whisper_model
    if not FASTER_WHISPER_AVAILABLE:
        raise RuntimeError("Voice transcription is not installed. Install faster-whisper first.")
    if _whisper_model is None:
        device = WHISPER_DEVICE
        compute = WHISPER_COMPUTE_TYPE
        if device == "auto":
            # faster-whisper accepts cpu/cuda; CPU int8 is the safest default.
            device = "cpu"
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device=device, compute_type=compute)
    return _whisper_model


def _normalize_voice_language(language: str) -> str:
    value = (language or "en-IN").strip()
    aliases = {
        "en": "en-IN", "hi": "hi-IN", "bn": "bn-IN", "ta": "ta-IN",
        "te": "te-IN", "mr": "mr-IN", "gu": "gu-IN", "kn": "kn-IN",
        "english": "en-IN", "hindi": "hi-IN", "bengali": "bn-IN",
        "tamil": "ta-IN", "telugu": "te-IN", "marathi": "mr-IN",
        "gujarati": "gu-IN", "kannada": "kn-IN",
    }
    return aliases.get(value.lower(), value)


def _voice_language_code(language: str) -> str:
    normalized = _normalize_voice_language(language)
    return WHISPER_LANGUAGE_CODES.get(normalized, normalized.split("-")[0].lower())


def _transcribe_audio(path: str, language: str):
    model = _get_whisper_model()
    lang = _voice_language_code(language)
    segments, info = model.transcribe(
        path,
        # Force the requested language for every supported locale. This avoids
        # language drift caused by automatic detection, especially for short
        # Indian-language answers and mixed-accent speech.
        language=lang if _normalize_voice_language(language) in WHISPER_LANGUAGE_CODES else None,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=False,
    )
    text_value = " ".join(segment.text.strip() for segment in segments).strip()
    detected = getattr(info, "language", None) or lang
    return text_value, detected


ACCESSIBILITY_INPUT_MODES = {"touch", "voice", "hybrid"}
ACCESSIBILITY_FONT_SCALES = {"0.9", "1.0", "1.15", "1.3", "1.5", "1.75", "2.0"}
ACCESSIBILITY_AUDIO_SPEEDS = {"0.75", "1.0", "1.25", "1.5"}

def _accessibility_defaults(patient_id: int):
    return {
        "patient_id": patient_id,
        "language": "en-IN",
        "input_mode": "touch",
        "font_scale": "1.0",
        "high_contrast": False,
        "reduced_motion": False,
        "captions": True,
        "audio_enabled": True,
        "audio_speed": "1.0",
        "assisted_mode": False,
    }

def _serialize_accessibility(row):
    return {
        "patient_id": row.patient_id, "language": row.language, "input_mode": row.input_mode,
        "font_scale": row.font_scale, "high_contrast": bool(row.high_contrast),
        "reduced_motion": bool(row.reduced_motion), "captions": bool(row.captions),
        "audio_enabled": bool(row.audio_enabled), "audio_speed": row.audio_speed,
        "assisted_mode": bool(row.assisted_mode), "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }

def _can_access_patient_preferences(actor, patient_id: int):
    if actor["role"] == "patient" and actor["id"] != patient_id:
        raise HTTPException(status_code=403, detail="You can only manage your own accessibility preferences.")
    if actor["role"] not in {"patient", "doctor", "triage", "admin"}:
        raise HTTPException(status_code=403, detail="Not authorized to access accessibility preferences.")


@app.get("/api/accessibility/capabilities")
def accessibility_capabilities():
    return {
        "phase": "AI-5H",
        "supported_languages": SUPPORTED_LANGUAGES,
        "input_modes": sorted(ACCESSIBILITY_INPUT_MODES),
        "font_scales": sorted(ACCESSIBILITY_FONT_SCALES, key=float),
        "audio_speeds": sorted(ACCESSIBILITY_AUDIO_SPEEDS, key=float),
        "features": {
            "voice_input": True,
            "touch_fallback": True,
            "captions": True,
            "high_contrast": True,
            "reduced_motion": True,
            "assisted_mode": True,
            "server_tts": EDGE_TTS_AVAILABLE,
            "server_stt": FASTER_WHISPER_AVAILABLE,
        },
        "tts_languages": [lang for lang in SUPPORTED_LANGUAGES if lang in TTS_VOICE_MAP],
        "notes": [
            "Voice transcription availability depends on faster-whisper and its configured model.",
            "Server text-to-speech currently exposes configured voices only; touch/text fallback remains available for every supported UI language.",
        ],
    }


@app.get("/api/patients/{patient_id}/accessibility")
def get_accessibility_preferences(patient_id: int, request: Request):
    actor = authenticate_request(request)
    _can_access_patient_preferences(actor, patient_id)
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        row = db.query(AccessibilityPreference).filter(AccessibilityPreference.patient_id == patient_id).first()
        return {"preferences": _serialize_accessibility(row) if row else _accessibility_defaults(patient_id)}
    finally:
        db.close()


@app.put("/api/patients/{patient_id}/accessibility")
def update_accessibility_preferences(patient_id: int, payload: AccessibilityPreferenceRequest, request: Request):
    actor = authenticate_request(request)
    _can_access_patient_preferences(actor, patient_id)
    language = _normalize_voice_language(payload.language)
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language. Choose one of: {', '.join(SUPPORTED_LANGUAGES)}")
    if payload.input_mode not in ACCESSIBILITY_INPUT_MODES:
        raise HTTPException(status_code=422, detail="input_mode must be touch, voice, or hybrid.")
    if payload.font_scale not in ACCESSIBILITY_FONT_SCALES:
        raise HTTPException(status_code=422, detail="font_scale is not supported.")
    if payload.audio_speed not in ACCESSIBILITY_AUDIO_SPEEDS:
        raise HTTPException(status_code=422, detail="audio_speed is not supported.")
    db = SessionLocal()
    try:
        patient = db.query(User).filter(User.id == patient_id, User.role == "patient").first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        row = db.query(AccessibilityPreference).filter(AccessibilityPreference.patient_id == patient_id).first()
        if not row:
            row = AccessibilityPreference(patient_id=patient_id)
            db.add(row)
        row.language = language
        row.input_mode = payload.input_mode
        row.font_scale = payload.font_scale
        row.high_contrast = int(payload.high_contrast)
        row.reduced_motion = int(payload.reduced_motion)
        row.captions = int(payload.captions)
        row.audio_enabled = int(payload.audio_enabled)
        row.audio_speed = payload.audio_speed
        row.assisted_mode = int(payload.assisted_mode)
        row.updated_at = utc_now()
        audit(db, actor["id"], actor["role"], "accessibility_preferences_updated", f"patient:{patient_id}")
        db.commit(); db.refresh(row)
        return {"message": "Accessibility preferences saved", "preferences": _serialize_accessibility(row)}
    finally:
        db.close()


@app.get("/api/voice/status")
def voice_status():
    return {
        "phase": "AI-5H",
        "transcription": {
            "available": FASTER_WHISPER_AVAILABLE,
            "provider": "faster-whisper" if FASTER_WHISPER_AVAILABLE else None,
            "model": WHISPER_MODEL_SIZE if FASTER_WHISPER_AVAILABLE else None,
        },
        "tts": {
            "available": EDGE_TTS_AVAILABLE,
            "provider": "edge-tts" if EDGE_TTS_AVAILABLE else None,
        },
        "languages": list(SUPPORTED_LANGUAGES.keys()),
        "tts_languages": [lang for lang in SUPPORTED_LANGUAGES if lang in TTS_VOICE_MAP],
        "raw_audio_persistence": False,
        "diagnostic": False,
    }


@app.post("/api/voice/transcribe")
async def voice_transcribe(
    audio: UploadFile = File(...),
    patient_id: int = Form(...),
    session_id: str = Form(""),
    language: str = Form("en-IN"),
    request: Request = None,
):
    actor = authenticate_request(request) if request is not None else None
    if actor and actor["role"] == "patient" and actor["id"] != patient_id:
        raise HTTPException(status_code=403, detail="You can only submit voice input for your own patient account.")
    language = _normalize_voice_language(language)
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language. Choose one of: {', '.join(SUPPORTED_LANGUAGES)}")
    if not FASTER_WHISPER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Voice transcription is not configured. Install faster-whisper and download/use the configured model.")
    suffix = Path(_safe_original_filename(audio.filename or "audio.webm")).suffix.lower() or ".webm"
    allowed = {".webm", ".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".flac"}
    if suffix not in allowed:
        raise HTTPException(status_code=415, detail="Unsupported audio format. Use webm, wav, mp3, m4a, ogg, or flac.")
    temp_path = None
    db = SessionLocal()
    try:
        state = db.query(InterviewState).filter(InterviewState.session_id == session_id).first() if session_id else None
        if session_id and (not state or state.patient_id != patient_id):
            raise HTTPException(status_code=403, detail="Voice session does not belong to the specified patient.")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=VOICE_TMP_DIR) as tmp:
            temp_path = tmp.name
            while True:
                chunk = await audio.read(min(1024 * 1024, MAX_VOICE_UPLOAD_BYTES + 1))
                if not chunk:
                    break
                tmp.write(chunk)
                if tmp.tell() > MAX_VOICE_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"Audio exceeds the {MAX_VOICE_UPLOAD_BYTES // (1024 * 1024)} MB size limit.")
        size = os.path.getsize(temp_path)
        if size == 0:
            raise HTTPException(status_code=400, detail="Audio upload is empty.")
        async with _transcription_semaphore:
            transcript, detected = await asyncio.to_thread(_transcribe_audio, temp_path, language)
        if not transcript:
            repair = analyze_repair("", event="no_speech", attempt=0, current_language=language)
            return {
                "transcript": "",
                "detected_language": detected,
                "language": language,
                "nlu": None,
                "voice_turn_id": None,
                "repair": {**repair, "response_text": localized_response(repair, language)},
                "fallback": {"available": True, "mode": "touch"},
            }
        turn = VoiceTurn(patient_id=patient_id, session_id=session_id, language=language, direction="input", transcript=transcript, status="completed", provider="faster-whisper")
        db.add(turn)
        db.commit()
        # Feed the same conservative clinical understanding layer used by text input.
        nlu = extract_clinical_entities(transcript, language=language)
        repair = analyze_repair(transcript, event="answer", attempt=0, current_language=language)
        return {
            "transcript": transcript,
            "detected_language": detected,
            "language": language,
            "nlu": nlu,
            "voice_turn_id": turn.id,
            "repair": {**repair, "response_text": localized_response(repair, language)},
            "fallback": {"available": True, "mode": "touch"},
        }
    finally:
        db.close()
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


@app.post("/api/voice/speak")
async def voice_speak(text: str = Form(...), language: str = Form("en-IN")):
    language = _normalize_voice_language(language)
    if not EDGE_TTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Text-to-speech is not configured. Install edge-tts first.")
    clean = _bounded_text(text, 1000)
    if not clean:
        raise HTTPException(status_code=400, detail="Text is required.")
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language. Choose one of: {', '.join(SUPPORTED_LANGUAGES)}")
    voice = TTS_VOICE_MAP.get(language)
    if not voice:
        raise HTTPException(status_code=503, detail=f"Text-to-speech voice is not configured for {language}.")
    output_path = VOICE_TMP_DIR / f"tts_{uuid.uuid4().hex}.mp3"
    try:
        communicate = edge_tts.Communicate(clean, voice)
        async with _tts_semaphore:
            await communicate.save(str(output_path))
        from starlette.background import BackgroundTask
        return FileResponse(
            str(output_path),
            media_type="audio/mpeg",
            filename="medikiosk_prompt.mp3",
            background=BackgroundTask(lambda: output_path.unlink(missing_ok=True)),
        )
    except Exception as exc:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=502, detail=f"TTS generation failed: {exc}")


@app.post("/api/ai/conversation-repair")
def conversation_repair(payload: ConversationRepairRequest, request: Request):
    actor = authenticate_request(request)
    authorize_interview_patient(actor, payload.patient_id)
    """AI-1E: classify conversational repair needs without changing clinical meaning."""
    language = payload.language if payload.language in SUPPORTED_LANGUAGES else "en-IN"
    db = SessionLocal()
    try:
        state = get_or_create_interview_state(db, payload.patient_id, payload.session_id, language)
        repair = analyze_repair(payload.text, event=payload.event, attempt=payload.attempt, current_language=state.language)
        if repair.get("requested_language") in SUPPORTED_LANGUAGES:
            state.language = repair["requested_language"]
            language = state.language
        action = repair.get("action")
        if action in {"repeat_question", "simplify_question", "request_correction", "voice_retry", "touch_fallback", "switch_language"}:
            state.repair_count = (state.repair_count or 0) + 1
        if action in {"voice_retry", "touch_fallback"}:
            state.voice_failure_count = (state.voice_failure_count or 0) + 1
        state.last_input_mode = payload.input_mode
        state.last_repair_action = action
        state.updated_at = utc_now()
        db.commit()
        repair["response_text"] = localized_response(repair, language)
        repair["language"] = language
        repair["state"] = interview_state_response(state)
        return repair
    finally:
        db.close()


def generate_physician_summary(
    structured: dict,
    risk_level: str,
    red_flags: list,
    nlp: Optional[dict] = None,
    patient: Any = None,
    encounter: Any = None,
    documents: Optional[list] = None,
):
    """Build a deterministic, clinician-facing handoff from persisted facts only."""
    s = structured or {}
    nlp = nlp or {}
    documents = documents or []

    def val(key):
        value = s.get(key)
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    profile = getattr(patient, "profile", None) if patient else None
    language = getattr(encounter, "language", None) or s.get("language") or (getattr(patient, "preferred_language", None) if patient else None) or "en-IN"
    care_type = getattr(encounter, "care_type", None) or s.get("care_type") or "allopathy"
    department = getattr(encounter, "department", None) or "Not available"
    source_language = language if language in SUPPORTED_LANGUAGES else "en-IN"

    def english_value(value, field=""):
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        return canonicalize_clinical_text(str(value), source_language, field=field)

    complaint_raw = val("chief_complaint") or (getattr(encounter, "reason", "") if encounter else "")
    complaint = english_value(complaint_raw, "chief_complaint")
    if not complaint or "requires clinician review" in complaint:
        complaint = "Patient-reported concern; see interview evidence."
    department = getattr(encounter, "department", None) or "Not available"
    visit_date = getattr(encounter, "visit_date", None) or "Not available"

    symptom_items = []
    for key in ("associated", "associated_symptoms", "chest_breathlessness", "headache_nausea", "abdominal_bowel", "fever_infection", "respiratory_cough", "respiratory_wheeze", "review_systems"):
        value = val(key)
        if value:
            rendered = english_value(value, key)
            if rendered and "requires clinician review" not in rendered:
                symptom_items.append({"field": key, "value": rendered})
    # Re-run the language-aware clinical NLU at handoff time. The older
    # summary path could receive an English-only NLP payload even when the
    # patient answered in Hindi/Bangla, which produced generic review text.
    combined_source = " ".join(str(v) for v in s.values() if v not in (None, "", [], {}))
    multilingual_nlu = extract_clinical_entities(combined_source, source_language) if combined_source else {}
    positives = list(dict.fromkeys(
        list(multilingual_nlu.get("positive_symptoms") or []) +
        [str(x) for x in (nlp.get("positive_symptoms") or [])]
    ))
    negatives = list(dict.fromkeys(
        list(multilingual_nlu.get("negated_symptoms") or []) +
        [str(x) for x in (nlp.get("negated_symptoms") or [])]
    ))

    history = []
    for key, label in (("onset", "Onset"), ("location", "Location"), ("severity", "Severity reported"), ("character", "Character"), ("general_change", "Aggravating/relieving factors"), ("general_impact", "Daily impact")):
        value = val(key)
        if value:
            rendered = english_value(value, key)
            if rendered and "requires clinician review" not in rendered:
                history.append({"label": label, "value": rendered})

    background = []
    for key, label in (("past_history", "Past history"), ("medications", "Medications"), ("allergies", "Allergies"), ("family_history", "Family history"), ("personal_history", "Personal history")):
        value = val(key)
        if value:
            rendered = english_value(value, key)
            if rendered and "requires clinician review" not in rendered:
                background.append({"label": label, "value": rendered})

    missing = []
    for key, label in (("onset", "onset"), ("severity", "severity"), ("medications", "current medications"), ("allergies", "allergies")):
        if not val(key):
            missing.append(label)

    safety_status = "Assessment complete" if s or red_flags else "Safety assessment incomplete"
    # Safety-language contract: absence of a rule match is never a clearance.
    safety_language_contract = "This does not establish clinical safety; clinician review remains required."
    safety_message = (
        "Potential emergency information requires immediate human triage."
        if risk_level == "emergency" else
        "Potential warning information requires prompt clinician review."
        if risk_level == "urgent" else
        "No configured red-flag pattern was identified in the available information. This does not establish clinical safety; clinician review remains required."
        if safety_status == "Assessment complete" else
        "Safety assessment incomplete — clinician review recommended."
    )

    severity_level = "urgent" if risk_level in ("urgent", "emergency") else str(s.get("severity_level") or "not_assessed")
    if severity_level == "not_assessed":
        raw_severity = val("severity").lower()
        if re.search(r"\b(?:severe|9|10)\b|तेज़|बहुत तेज|तीव्र|তীব্র", raw_severity):
            severity_level = "high"
        elif re.search(r"\b(?:moderate|4|5|6|7|8)\b|मध्यम|মাঝারি", raw_severity):
            severity_level = "moderate"
        elif re.search(r"\b(?:mild|1|2|3)\b|हल्का|হালকা", raw_severity):
            severity_level = "low"

    ayush = s.get("ayush_assessment") if care_type == "ayush" else None
    doc_index = []
    for d in documents:
        doc_index.append({
            "document_id": getattr(d, "id", None),
            "filename": getattr(d, "filename", None),
            "document_type": getattr(d, "document_type", None),
            "date": d.created_at.isoformat() if getattr(d, "created_at", None) else None,
            "verification_status": getattr(d, "verification_status", None) or "Pending",
            "encounter_id": getattr(d, "encounter_id", None),
        })

    patient_overview = {
        "patient": getattr(patient, "name", None) if patient else None,
        "age": getattr(profile, "age", None) if profile else None,
        "gender": getattr(profile, "gender", None) if profile else None,
        "language": language,
        "care_type": care_type,
        "department": department,
        "encounter_date": visit_date,
    }

    history_narrative = []
    for item in history:
        history_narrative.append(f"{item['label']}: {item['value']}")
    if symptom_items:
        history_narrative.append("Associated information: " + "; ".join(x["value"] for x in symptom_items))

    # Keep the spoken/readable handoff genuinely brief: a doctor should be able
    # to scan it in roughly 30 seconds. Build it only from persisted patient
    # responses and explicit safety signals; never infer a diagnosis.
    thirty_parts = [f"Patient presents with {complaint.rstrip('.')}."]
    if history:
        compact_history = "; ".join(f"{x['label'].lower()}: {x['value']}" for x in history[:2])
        thirty_parts.append(compact_history + ".")
    if positives:
        thirty_parts.append("Key reported symptoms: " + ", ".join(positives[:3]) + ".")
    if red_flags:
        thirty_parts.append("Safety alert: " + ", ".join(str(x.get("label", "Alert")) for x in red_flags[:2]) + "; clinician review required.")
    else:
        thirty_parts.append("Safety: no configured red-flag pattern identified; this is not a clearance of clinical risk.")
    if missing:
        thirty_parts.append("Verify: " + ", ".join(missing[:2]) + ".")
    thirty_parts.append("Review the source history, records and examination before clinical decisions.")
    thirty_second_summary = " ".join(thirty_parts)
    if len(thirty_second_summary) > 520:
        thirty_second_summary = thirty_second_summary[:517].rsplit(" ", 1)[0] + "..."

    # Structured 30-second brief: keep the API source-of-truth and expose
    # presentation-ready sections without moving clinical reasoning into the UI.
    def brief_english_text(value):
        rendered = str(value or "").strip()
        if rendered.isascii():
            return rendered
        # Keep the brief English-readable without translating or inventing a
        # clinical fact. If a multilingual duration contains a recoverable
        # English duration token, retain only that verified token.
        match = re.search(r"(?<!\w)(?:\d+\s+(?:days?|weeks?|months?|years?)(?=\s|$|[^\x00-\x7F])|since (?:yesterday|last night|this morning))", rendered, flags=re.I)
        return match.group(0) if match else ""

    symptom_candidates = [
        x for x in (brief_english_text(x["value"]) for x in symptom_items) if x
    ]
    brief_symptoms = list(dict.fromkeys(symptom_candidates))[:6]
    if not brief_symptoms:
        brief_symptoms = ["Not reported"]
    brief_history = []
    for item in history[:3]:
        rendered = brief_english_text(item["value"])
        if rendered:
            brief_history.append(f"{item['label']}: {rendered}")
    if not brief_history:
        brief_history = ["Not reported"]
    background_items = [f"{x['label']}: {x['value']}" for x in background[:5]]
    if not background_items:
        profile_values = []
        if profile:
            for key, label in (("conditions", "Known conditions"), ("medications", "Medications"), ("allergies", "Allergies")):
                value = getattr(profile, key, None)
                if value not in (None, "", [], {}):
                    rendered = english_value(value, key)
                    if rendered:
                        profile_values.append(f"{label}: {rendered}")
        background_items = profile_values or ["Not reported"]
    if red_flags:
        safety_brief = {
            "status": "review_required",
            "label": "Review required",
            "message": safety_message,
            "alerts": red_flags[:4],
            "provenance": "AI-structured from patient-reported intake and existing safety signals",
        }
    elif s:
        safety_brief = {
            "status": "no_alert_identified",
            "label": "No configured red-flag pattern identified",
            "message": "This does not establish clinical safety; clinician review remains required.",
            "alerts": [],
            "provenance": "AI-structured from available intake data",
        }
    else:
        safety_brief = {
            "status": "not_available",
            "label": "Not available",
            "message": "Safety information was not available in the intake data.",
            "alerts": [],
            "provenance": "Not available",
        }
    brief_complaint = complaint if complaint and complaint != "Patient-reported concern; see interview evidence." else "Not reported"
    brief_sections = {
        "presenting_concern": {"value": brief_complaint, "provenance": "patient_reported"},
        "history": {"items": brief_history, "provenance": "patient_reported"},
        "reported_symptoms": {"items": brief_symptoms, "provenance": "patient_reported"},
        "safety": safety_brief,
        "important_background": {"items": background_items, "provenance": "patient_reported"},
        "verify": {
            "items": list(dict.fromkeys(missing[:5] + (["Review source history and examination"] if not missing else []))),
            "provenance": "AI-structured review prompts; not clinician-confirmed",
        },
        "documents": {"count": len(documents)},
        "provenance": {
            "patient_reported": "Directly collected or persisted from the patient intake.",
            "ai_structured": "Organized from persisted intake and existing safety/NLU outputs.",
            "clinician_verified": "Only clinician-entered information is clinician-verified; none is added here.",
        },
    }

    return {
        "schema_version": "AI-4A.4",
        "headline": f"Physician handoff — {complaint[:100]}",
        "patient_overview": patient_overview,
        "chief_complaint": complaint,
        "key_symptoms": list(dict.fromkeys([x["value"] for x in symptom_items] + positives)),
        "history_of_present_illness": history_narrative,
        "important_positive_findings": positives,
        "important_negative_findings": negatives,
        "history_points": [f"{x['label']}: {x['value']}" for x in history],
        "background": [f"{x['label']}: {x['value']}" for x in background],
        "medical_history": {x["label"]: x["value"] for x in background if x["label"] in {"Past history", "Family history", "Personal history"}},
        "medications": next((x["value"] for x in background if x["label"] == "Medications"), "Not available"),
        "allergies": next((x["value"] for x in background if x["label"] == "Allergies"), "Not available"),
        "safety": {"status": safety_status, "level": risk_level, "severity": severity_level, "alerts": red_flags, "message": safety_message, "requires_clinician_review": True},
        "documents": doc_index,
        "ayush": ayush,
        "physician_focus": (["Review safety alerts before routine history interpretation."] if risk_level in ("urgent", "emergency") else []) + (["Clarify missing history: " + ", ".join(missing) + "."] if missing else []) + ["Verify patient-reported history against examination and records."],
        "data_gaps": missing,
        "thirty_second_summary": thirty_second_summary,
        "brief_sections": brief_sections,
        "clinical_summary": " ".join(history_narrative) or complaint,
        "key_findings": list(dict.fromkeys(positives + [x["value"] for x in symptom_items])),
        "reported_negatives": negatives,
        "priority": risk_level,
        "engine": "Structured clinical synthesis + NLP evidence",
        "disclaimer": "AI-assisted handoff of patient-reported information only. It is not a diagnosis, treatment recommendation, or substitute for physician judgment.",
    }


# ---------- Phase 5E: Explainability / Sources ----------
# Explainability is deliberately provenance-first: every displayed AI finding is
# tied to either patient text/structured answers, a transparent local NLP rule,
# the local ML classifier, or an authoritative reference page. It never presents
# a source as proof of a diagnosis.
EXPLAINABILITY_SOURCES = [
    {
        "id": "who-icd11",
        "title": "WHO ICD-11",
        "publisher": "World Health Organization",
        "url": "https://www.who.int/standards/classifications/classification-of-diseases",
        "use": "Reference for standardized health terminology and clinical documentation context.",
    },
    {
        "id": "ministry-ayush",
        "title": "Ministry of Ayush",
        "publisher": "Government of India",
        "url": "https://ayush.gov.in/",
        "use": "Official context for AYUSH systems, policy, education and research resources.",
    },
    {
        "id": "ayush-research-portal",
        "title": "AYUSH Research Portal",
        "publisher": "Ministry of Ayush, Government of India",
        "url": "https://arp.ayush.gov.in/",
        "use": "Evidence-based AYUSH research discovery; used as a reference library, not as an automatic treatment recommender.",
    },
]

def _sentence_for_term(text: str, term: str):
    if not text or not term:
        return ""
    for sentence in re.split(r"(?<=[.!?])\\s+|\\n+", text.strip()):
        if term.lower() in sentence.lower():
            return sentence.strip()
    return text.strip()[:240]

def generate_explainability(structured: dict, nlp: dict, summary: dict, risk_level: str, red_flags: list):
    nlp = nlp or {}
    structured = structured or {}
    summary = summary or {}
    raw_text = str(nlp.get("text_normalized") or structured.get("chief_complaint") or "")
    evidence = []
    for item in nlp.get("symptoms") or []:
        mention = item.get("mention") or item.get("term")
        evidence.append({
            "type": "nlp_extraction",
            "finding": item.get("term"),
            "status": "negated" if item.get("negated") else "present",
            "evidence": _sentence_for_term(raw_text, mention),
            "method": "Clinical phrase matching + local negation window",
            "confidence": "high" if mention and mention.lower() in raw_text.lower() else "moderate",
        })

    intent = nlp.get("intent") or "general"
    model_intent = nlp.get("model_intent") or intent
    confidence = float(nlp.get("confidence") or 0)
    evidence.append({
        "type": "intent_classification",
        "finding": intent,
        "status": "selected pathway",
        "evidence": raw_text[:300] or "No free-text evidence available",
        "method": "Local TF-IDF + Logistic Regression; symptom pathway resolution",
        "confidence": f"{round(confidence*100)}% model probability" if confidence else "rule-resolved",
        "details": {"model_intent": model_intent, "resolved_intent": intent},
    })

    for duration in nlp.get("duration_mentions") or []:
        evidence.append({
            "type": "temporal_extraction",
            "finding": duration,
            "status": "reported",
            "evidence": _sentence_for_term(raw_text, duration),
            "method": "Transparent temporal-expression pattern",
            "confidence": "high",
        })
    if nlp.get("severity"):
        evidence.append({
            "type": "severity_extraction",
            "finding": nlp.get("severity"),
            "status": "reported",
            "evidence": raw_text[:300],
            "method": "Transparent severity phrase matching",
            "confidence": "moderate",
        })

    for alert in red_flags or []:
        evidence.append({
            "type": "safety_rule",
            "finding": alert.get("label", "Safety alert"),
            "status": alert.get("level", risk_level),
            "evidence": alert.get("message", "Triggered by the prototype safety rules."),
            "method": "Deterministic red-flag rule engine",
            "confidence": "rule match",
        })

    summary_trace = []
    for finding in summary.get("key_findings") or []:
        matching = [e for e in evidence if e.get("finding") == finding]
        summary_trace.append({
            "summary_item": finding,
            "supported_by": matching[0]["type"] if matching else "structured_history",
            "evidence": matching[0]["evidence"] if matching else str(structured.get("chief_complaint") or "Structured patient history"),
        })

    return {
        "version": "5E.1",
        "headline": "Why the AI produced this handoff",
        "evidence": evidence,
        "summary_trace": summary_trace,
        "sources": EXPLAINABILITY_SOURCES,
        "model": {
            "engine": nlp.get("engine", "Phase 5C NLP"),
            "model_intent": model_intent,
            "resolved_intent": intent,
            "confidence": confidence,
            "confidence_semantics": confidence_semantics("classifier_score"),
            "limitations": [
                "The classifier is a small local prototype trained on a limited synthetic demonstration set.",
                "Phrase extraction can miss synonyms, context or sarcasm and is not a diagnostic model.",
                "External sources provide reference context; they are not used to automatically diagnose or prescribe treatment.",
            ],
        },
        "safety": {
            "level": risk_level or "none",
            "rule_count": len(red_flags or []),
        },
        "disclaimer": "Explainability shows provenance and evidence for the prototype's outputs. It does not establish a diagnosis, treatment plan, or clinical truth; the physician remains responsible for interpretation.",
    }

@app.get("/api/doctor/consultations/{consultation_id}/explainability")
def get_explainability(consultation_id: int, request: Request):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Authorized clinical staff only.")
    db = SessionLocal()
    try:
        c = db.query(Consultation).filter(Consultation.id == consultation_id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Consultation not found.")
        authorize_consultation(actor, c, db)
        structured = json.loads(c.structured_data or "{}")
        nlp = json.loads(c.nlp_data or "{}") if c.nlp_data else {}
        summary = json.loads(c.ai_summary) if c.ai_summary else None
        if not isinstance(summary, dict) or summary.get("schema_version") != "AI-4A.2":
            patient = db.query(User).filter(User.id == c.patient_id, User.role == "patient").first()
            encounter = db.query(Encounter).filter(Encounter.id == c.encounter_id).first() if c.encounter_id else None
            documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == c.patient_id).order_by(MedicalDocument.created_at.desc()).all()
            summary = generate_physician_summary(structured, c.risk_level or "none", json.loads(c.red_flags or "[]"), nlp, patient=patient, encounter=encounter, documents=documents)
        return {"consultation_id": c.id, "explainability": generate_explainability(structured, nlp, summary, c.risk_level or "none", json.loads(c.red_flags or "[]"))}
    finally:
        db.close()


@app.post("/api/doctor/consultations/{consultation_id}/ai-summary")
def create_ai_summary(consultation_id: int, request: Request):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Authorized clinical staff only.")
    db = SessionLocal()
    try:
        c = db.query(Consultation).filter(Consultation.id == consultation_id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Consultation not found.")
        authorize_consultation(actor, c, db)
        structured = json.loads(c.structured_data or "{}")
        nlp = json.loads(c.nlp_data or "{}") if c.nlp_data else {}
        patient = db.query(User).filter(User.id == c.patient_id, User.role == "patient").first()
        encounter = db.query(Encounter).filter(Encounter.id == c.encounter_id).first() if c.encounter_id else None
        documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == c.patient_id).order_by(MedicalDocument.created_at.desc()).all()
        summary = generate_physician_summary(structured, c.risk_level or "none", json.loads(c.red_flags or "[]"), nlp, patient=patient, encounter=encounter, documents=documents)
        c.ai_summary = json.dumps(summary, ensure_ascii=False)
        c.ai_summary_generated_at = utc_now()
        db.commit()
        return {"consultation_id": c.id, "ai_summary": summary, "generated_at": c.ai_summary_generated_at.isoformat()}
    finally:
        db.close()


@app.get("/api/doctor/consultations/{consultation_id}/ai-summary")
def get_ai_summary(consultation_id: int, request: Request):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Authorized clinical staff only.")
    db = SessionLocal()
    try:
        c = db.query(Consultation).filter(Consultation.id == consultation_id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Consultation not found.")
        authorize_consultation(actor, c, db)
        existing_summary = _json_loads(c.ai_summary, None)
        if not isinstance(existing_summary, dict) or existing_summary.get("schema_version") != "AI-4A.3":
            structured = _json_loads(c.structured_data, {})
            nlp = _json_loads(c.nlp_data, {})
            patient = db.query(User).filter(User.id == c.patient_id, User.role == "patient").first()
            encounter = db.query(Encounter).filter(Encounter.id == c.encounter_id).first() if c.encounter_id else None
            documents = db.query(MedicalDocument).filter(MedicalDocument.patient_id == c.patient_id).order_by(MedicalDocument.created_at.desc()).all()
            summary = generate_physician_summary(
                structured, c.risk_level or "none", _json_loads(c.red_flags, []), nlp,
                patient=patient, encounter=encounter, documents=documents
            )
            c.ai_summary = json.dumps(summary, ensure_ascii=False)
            c.ai_summary_generated_at = utc_now()
            db.commit()
            existing_summary = summary
        return {"consultation_id": c.id, "ai_summary": existing_summary, "generated_at": c.ai_summary_generated_at.isoformat() if c.ai_summary_generated_at else None}
    finally:
        db.close()


@app.post("/api/interview/back")
def interview_back(payload: dict, request: Request):
    patient_id = int(payload.get("patient_id") or 0)
    session_id = str(payload.get("session_id") or "").strip()
    if not patient_id or not session_id:
        raise HTTPException(status_code=400, detail="patient_id and session_id are required.")
    actor = authenticate_request(request)
    authorize_interview_patient(actor, patient_id)
    db = SessionLocal()
    try:
        require_active_consent(db, patient_id)
        state = db.query(InterviewState).filter(InterviewState.session_id == session_id, InterviewState.patient_id == patient_id).first()
        if not state:
            raise HTTPException(status_code=404, detail="Interview session not found.")
        conversation = _json_loads(state.conversation, [])
        answered_ids = _json_loads(state.answered_question_ids, [])
        if not conversation or not answered_ids:
            raise HTTPException(status_code=409, detail="There is no earlier interview question to return to.")
        conversation.pop(); answered_ids.pop()
        structured = {}
        for item in conversation:
            if not isinstance(item, dict): continue
            qid, answer = str(item.get("question_id") or ""), str(item.get("answer") or "")
            if not answer or not qid: continue
            extracted = extract_structured(qid, answer)
            for key, value in extracted.items():
                if key not in ("raw", "nlu") and value not in (None, ""): structured[key] = value
        pathway = classify_pathway(structured.get("chief_complaint", "")) if structured.get("chief_complaint") else "general"
        structured["clinical_evidence"] = [{"question_id": x.get("question_id"), "text": x.get("answer", ""), "skipped": bool(x.get("skipped"))} for x in conversation[-50:] if isinstance(x, dict)]
        risk_level, flags = detect_red_flags("back", "", structured)
        state.pathway = pathway; state.structured_data = json.dumps(structured, ensure_ascii=False)
        state.answered_question_ids = json.dumps(answered_ids, ensure_ascii=False); state.conversation = json.dumps(conversation, ensure_ascii=False)
        state.risk_level = risk_level; state.red_flags = json.dumps(flags, ensure_ascii=False); state.status = "active"
        flow = build_question_flow(pathway); current_id = answered_ids[-1] if answered_ids else flow[0]["id"]; state.current_question_id = current_id; state.updated_at = utc_now()
        db.commit()
        current = next((q for q in flow if q.get("id") == current_id), flow[0])
        return {"message": "Returned to the previous question", **interview_state_response(state), "current_question": localize_question(current, state.language)}
    finally: db.close()

@app.post("/api/interview/complete")
def interview_complete(payload: InterviewComplete, request: Request):
    actor = authenticate_request(request)
    authorize_interview_patient(actor, payload.patient_id)
    db = SessionLocal()
    try:
        require_active_consent(db, payload.patient_id)
        patient = db.query(User).filter(
            User.id == payload.patient_id, User.role == "patient"
        ).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")

        state = db.query(InterviewState).filter(InterviewState.session_id == payload.session_id, InterviewState.patient_id == patient.id).first() if payload.session_id else None
        if state:
            structured = _json_loads(state.structured_data, {})
            if not structured:
                raise HTTPException(status_code=400, detail="No server-owned interview answers are available to complete.")
        else:
            # Backward-compatible completion for older clients that have no
            # server-owned state. New sessions always use InterviewState.
            structured = payload.structured
        complaint = structured.get("chief_complaint", "Clinical history")
        summary_parts = []

        labels = [
            ("chief_complaint", "Main complaint"), ("onset", "Onset"), ("location", "Location"),
            ("severity", "Severity"), ("character", "Character"), ("associated_symptoms", "Associated symptoms"),
            ("chest_radiation", "Chest radiation"), ("chest_exertion", "Chest/exertion pattern"),
            ("chest_breathlessness", "Chest associated symptoms"), ("headache_visual", "Headache neurological/visual symptoms"),
            ("headache_nausea", "Headache associated symptoms"), ("headache_trigger", "Headache triggers"),
            ("abdominal_food", "Abdominal food/relief pattern"), ("abdominal_bowel", "Bowel symptoms"),
            ("abdominal_urinary", "Urinary symptoms"), ("fever_pattern", "Fever pattern"),
            ("fever_infection", "Infection symptoms"), ("fever_exposure", "Exposure history"),
            ("respiratory_cough", "Cough details"), ("respiratory_activity", "Breathing pattern"),
            ("respiratory_wheeze", "Wheeze/lung history"), ("general_change", "Aggravating/relieving factors"),
            ("general_impact", "Daily impact"), ("past_history", "Past history"), ("medications", "Medications"),
            ("allergies", "Allergies"), ("family_history", "Family history"),
            ("personal_history", "Personal history"), ("review_of_systems", "Review of systems"),
        ]
        for key, label in labels:
            if key in structured and structured[key] not in ("", None):
                summary_parts.append(f"{label}: {structured[key]}")

        summary = " | ".join(summary_parts) if summary_parts else "Interview completed."
        risk_level, red_flags = detect_red_flags("completion", "", structured)
        if red_flags:
            summary += " | Safety alerts: " + "; ".join(flag["label"] for flag in red_flags)
        combined_text = " ".join(str(v) for v in structured.values() if v not in (None, ""))
        completion_language = str(structured.get("language") or "en-IN")
        completion_nlp = analyze_nlp_text(combined_text, completion_language) if combined_text else {}
        physician_summary = generate_physician_summary(structured, risk_level, red_flags, completion_nlp)
        state = db.query(InterviewState).filter(InterviewState.session_id == payload.session_id, InterviewState.patient_id == patient.id).first() if payload.session_id else None
        if state and state.encounter_id:
            encounter = db.query(Encounter).filter(Encounter.id == state.encounter_id, Encounter.patient_id == patient.id).first()
            if not encounter:
                raise HTTPException(status_code=409, detail="Interview is linked to an unavailable encounter.")
        else:
            encounter = get_or_create_handoff_encounter(db, patient.id, completion_language)
            if state:
                state.encounter_id = encounter.id
        encounter.language = completion_language if completion_language in SUPPORTED_LANGUAGES else (encounter.language or "en-IN")
        encounter.reason = str(structured.get("chief_complaint") or encounter.reason or "Clinical history").strip()[:500]
        if risk_level == "emergency":
            encounter.priority = "emergency"
        elif risk_level == "urgent":
            encounter.priority = "urgent"
        record = Consultation(
            patient_id=patient.id,
            encounter_id=encounter.id,
            title=payload.title or str(complaint)[:80],
            summary=summary,
            status="AI History — Phase 5D Physician Summary Ready",
            risk_level=risk_level,
            red_flags=json.dumps(red_flags),
            structured_data=json.dumps(structured, ensure_ascii=False),
            nlp_data=json.dumps(completion_nlp, ensure_ascii=False),
            ai_summary=json.dumps(physician_summary, ensure_ascii=False),
            ai_summary_generated_at=utc_now()
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Clinical history saved",
            "consultation_id": record.id,
            "title": record.title,
            "summary": summary,
            "structured": structured,
            "risk_level": risk_level,
            "red_flags": red_flags,
            "ai_summary": physician_summary
        }
    finally:
        db.close()


# Patient-safe department discovery uses the same Department table as administration.
@app.get("/api/departments")
def list_patient_departments(request: Request):
    actor = authenticate_request(request)
    if actor["role"] != "patient":
        raise HTTPException(status_code=403, detail="Department selection is available to patient accounts.")
    db = SessionLocal()
    try:
        rows = (db.query(Department)
                .filter(Department.active == 1, Department.name.in_(PATIENT_DEPARTMENT_NAMES))
                .all())
        by_name = {d.name: d for d in rows}
        ordered = []
        for name, specialty in PATIENT_DEPARTMENT_CATALOG:
            d = by_name.get(name)
            if d:
                ordered.append({"id": d.id, "name": d.name, "specialty": d.specialty or specialty})
        return {"departments": ordered}
    finally:
        db.close()


# ---------- AI-5F: Hospital Administration ----------
ADMIN_ROLES = {"admin"}
VALID_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}

def require_admin(request: Request):
    actor = authenticate_request(request)
    if actor["role"] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Hospital administration is restricted to admin users.")
    return actor


def validate_time_range(start_time: str, end_time: str):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start_time) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", end_time):
        raise HTTPException(status_code=422, detail="Times must use HH:MM 24-hour format.")
    if start_time >= end_time:
        raise HTTPException(status_code=422, detail="Start time must be earlier than end time.")


def serialize_department(d):
    return {"id": d.id, "name": d.name, "specialty": d.specialty, "active": bool(d.active), "created_at": d.created_at.isoformat() if d.created_at else None}


@app.get("/api/admin/departments")
def admin_list_departments(request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        rows = db.query(Department).order_by(Department.name.asc()).all()
        return {"departments": [serialize_department(d) for d in rows]}
    finally:
        db.close()


@app.post("/api/admin/departments")
def admin_create_department(payload: AdminDepartmentRequest, request: Request):
    actor = require_admin(request)
    db = SessionLocal()
    try:
        name = payload.name.strip()
        if db.query(Department).filter(Department.name == name).first():
            raise HTTPException(status_code=409, detail="Department already exists.")
        d = Department(name=name, specialty=payload.specialty.strip(), active=int(payload.active))
        db.add(d); db.flush()
        audit(db, actor["id"], actor["role"], "admin_department_create", f"department:{d.id}")
        db.commit(); db.refresh(d)
        return {"message": "Department created", "department": serialize_department(d)}
    finally:
        db.close()


@app.put("/api/admin/departments/{department_id}")
def admin_update_department(department_id: int, payload: AdminDepartmentRequest, request: Request):
    actor = require_admin(request)
    db = SessionLocal()
    try:
        d = db.query(Department).filter(Department.id == department_id).first()
        if not d: raise HTTPException(status_code=404, detail="Department not found.")
        name = payload.name.strip()
        duplicate = db.query(Department).filter(Department.name == name, Department.id != d.id).first()
        if duplicate: raise HTTPException(status_code=409, detail="Another department already uses this name.")
        old_name = d.name
        d.name, d.specialty, d.active = name, payload.specialty.strip(), int(payload.active)
        # Keep dependent configuration references consistent when an admin renames a department.
        db.query(OPDConfiguration).filter(OPDConfiguration.department == old_name).update({"department": name}, synchronize_session=False)
        db.query(DoctorProfile).filter(DoctorProfile.department == old_name).update({"department": name}, synchronize_session=False)
        db.query(RoutingRule).filter(RoutingRule.department == old_name).update({"department": name}, synchronize_session=False)
        hospital = db.query(HospitalConfiguration).first()
        if hospital and hospital.default_department == old_name:
            hospital.default_department = name
        audit(db, actor["id"], actor["role"], "admin_department_update", f"department:{d.id}:{old_name}->{d.name}")
        db.commit(); db.refresh(d)
        return {"message": "Department updated", "department": serialize_department(d)}
    finally:
        db.close()


@app.get("/api/admin/doctors")
def admin_list_doctors(request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        rows = db.query(User, DoctorProfile).join(DoctorProfile, DoctorProfile.user_id == User.id).filter(User.role == "doctor").order_by(User.name.asc()).all()
        return {"doctors": [{"id": u.id, "name": u.name, "email": u.email, "specialty": p.specialty, "department": p.department, "registration_number": p.registration_number or "", "room_number": p.room_number or "Not assigned", "active": bool(p.active)} for u,p in rows]}
    finally:
        db.close()


@app.post("/api/admin/doctors")
def admin_create_doctor(payload: AdminDoctorRequest, request: Request):
    actor = require_admin(request)
    db = SessionLocal()
    try:
        if payload.user_id:
            user = db.query(User).filter(User.id == payload.user_id).first()
            if not user: raise HTTPException(status_code=404, detail="User not found.")
            if user.role != "doctor": raise HTTPException(status_code=422, detail="Selected user is not a doctor.")
            if db.query(DoctorProfile).filter(DoctorProfile.user_id == user.id).first(): raise HTTPException(status_code=409, detail="Doctor profile already exists.")
        else:
            if not payload.name or not payload.email or not payload.password:
                raise HTTPException(status_code=422, detail="name, email and password are required for a new doctor.")
            email = payload.email.strip().lower()
            if db.query(User).filter(User.email == email).first(): raise HTTPException(status_code=409, detail="Email is already registered.")
            user = User(name=payload.name.strip(), email=email, password_hash=hash_password(payload.password), role="doctor")
            db.add(user); db.flush()
        profile = DoctorProfile(user_id=user.id, specialty=payload.specialty.strip(), department=payload.department.strip(), registration_number=payload.registration_number.strip(), room_number=payload.room_number.strip() or "Not assigned", active=int(payload.active))
        db.add(profile); db.flush()
        audit(db, actor["id"], actor["role"], "admin_doctor_create", f"doctor:{user.id}")
        db.commit()
        return {"message": "Doctor created", "doctor": {"id": user.id, "name": user.name, "email": user.email, "specialty": profile.specialty, "department": profile.department, "registration_number": profile.registration_number or "", "room_number": profile.room_number or "Not assigned", "active": bool(profile.active)}}
    finally:
        db.close()


@app.put("/api/admin/doctors/{doctor_id}")
def admin_update_doctor(doctor_id: int, payload: AdminDoctorRequest, request: Request):
    actor = require_admin(request)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == doctor_id, User.role == "doctor").first()
        if not user: raise HTTPException(status_code=404, detail="Doctor not found.")
        profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == doctor_id).first()
        if not profile:
            profile = DoctorProfile(user_id=doctor_id); db.add(profile)
        if payload.name: user.name = payload.name.strip()
        if payload.email:
            email = payload.email.strip().lower()
            dup = db.query(User).filter(User.email == email, User.id != doctor_id).first()
            if dup: raise HTTPException(status_code=409, detail="Email is already registered.")
            user.email = email
        if payload.password: user.password_hash = hash_password(payload.password)
        profile.specialty, profile.department = payload.specialty.strip(), payload.department.strip()
        profile.registration_number, profile.room_number, profile.active = payload.registration_number.strip(), payload.room_number.strip() or "Not assigned", int(payload.active)
        audit(db, actor["id"], actor["role"], "admin_doctor_update", f"doctor:{doctor_id}")
        db.commit()
        return {"message": "Doctor updated", "doctor_id": doctor_id, "active": bool(profile.active)}
    finally:
        db.close()


@app.get("/api/admin/opd-config")
def admin_list_opd(request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        rows = db.query(OPDConfiguration).order_by(OPDConfiguration.department.asc()).all()
        return {"opd_configurations": [{"id": r.id, "department": r.department, "working_days": r.working_days.split(",") if r.working_days else [], "start_time": r.start_time, "end_time": r.end_time, "active": bool(r.active)} for r in rows]}
    finally: db.close()


@app.post("/api/admin/opd-config")
def admin_upsert_opd(payload: AdminOPDRequest, request: Request):
    actor = require_admin(request)
    if any(day not in VALID_DAYS for day in payload.working_days): raise HTTPException(status_code=422, detail="working_days contains an invalid day.")
    validate_time_range(payload.start_time, payload.end_time)
    db = SessionLocal()
    try:
        row = db.query(OPDConfiguration).filter(OPDConfiguration.department == payload.department.strip()).first()
        if not row: row = OPDConfiguration(department=payload.department.strip()); db.add(row)
        row.working_days = ",".join(dict.fromkeys(payload.working_days)); row.start_time = payload.start_time; row.end_time = payload.end_time; row.active = int(payload.active); row.updated_at = utc_now()
        audit(db, actor["id"], actor["role"], "admin_opd_config_update", f"department:{row.department}")
        db.commit(); db.refresh(row)
        return {"message": "OPD configuration saved", "id": row.id, "department": row.department, "working_days": row.working_days.split(","), "start_time": row.start_time, "end_time": row.end_time, "active": bool(row.active)}
    finally: db.close()


@app.get("/api/admin/availability")
def admin_list_availability(request: Request, doctor_id: Optional[int] = None):
    require_admin(request)
    db = SessionLocal()
    try:
        q = db.query(DoctorAvailability)
        if doctor_id: q = q.filter(DoctorAvailability.doctor_id == doctor_id)
        rows = q.order_by(DoctorAvailability.doctor_id, DoctorAvailability.day_of_week, DoctorAvailability.start_time).all()
        return {"availability": [{"id": r.id, "doctor_id": r.doctor_id, "day_of_week": r.day_of_week, "start_time": r.start_time, "end_time": r.end_time, "active": bool(r.active)} for r in rows]}
    finally: db.close()


@app.post("/api/admin/availability")
def admin_create_availability(payload: AdminAvailabilityRequest, request: Request):
    actor = require_admin(request)
    if payload.day_of_week not in VALID_DAYS: raise HTTPException(status_code=422, detail="Invalid day_of_week.")
    validate_time_range(payload.start_time, payload.end_time)
    db = SessionLocal()
    try:
        doctor = db.query(User).filter(User.id == payload.doctor_id, User.role == "doctor").first()
        if not doctor: raise HTTPException(status_code=404, detail="Doctor not found.")
        if db.query(DoctorAvailability).filter(DoctorAvailability.doctor_id == payload.doctor_id, DoctorAvailability.day_of_week == payload.day_of_week, DoctorAvailability.start_time == payload.start_time, DoctorAvailability.end_time == payload.end_time).first(): raise HTTPException(status_code=409, detail="Availability window already exists.")
        row = DoctorAvailability(doctor_id=payload.doctor_id, day_of_week=payload.day_of_week, start_time=payload.start_time, end_time=payload.end_time, active=int(payload.active))
        db.add(row); db.flush(); audit(db, actor["id"], actor["role"], "admin_availability_create", f"availability:{row.id}"); db.commit()
        return {"message": "Doctor availability created", "availability_id": row.id}
    finally: db.close()


@app.put("/api/admin/availability/{availability_id}")
def admin_update_availability(availability_id: int, payload: AdminAvailabilityRequest, request: Request):
    actor = require_admin(request)
    if payload.day_of_week not in VALID_DAYS: raise HTTPException(status_code=422, detail="Invalid day_of_week.")
    validate_time_range(payload.start_time, payload.end_time)
    db = SessionLocal()
    try:
        row = db.query(DoctorAvailability).filter(DoctorAvailability.id == availability_id).first()
        if not row: raise HTTPException(status_code=404, detail="Availability not found.")
        doctor = db.query(User).filter(User.id == payload.doctor_id, User.role == "doctor").first()
        if not doctor: raise HTTPException(status_code=404, detail="Doctor not found.")
        duplicate = db.query(DoctorAvailability).filter(DoctorAvailability.doctor_id == payload.doctor_id, DoctorAvailability.day_of_week == payload.day_of_week, DoctorAvailability.start_time == payload.start_time, DoctorAvailability.end_time == payload.end_time, DoctorAvailability.id != row.id).first()
        if duplicate: raise HTTPException(status_code=409, detail="Availability window already exists.")
        row.doctor_id, row.day_of_week, row.start_time, row.end_time, row.active = payload.doctor_id, payload.day_of_week, payload.start_time, payload.end_time, int(payload.active)
        audit(db, actor["id"], actor["role"], "admin_availability_update", f"availability:{row.id}"); db.commit()
        return {"message": "Doctor availability updated", "availability_id": row.id}
    finally: db.close()


@app.get("/api/admin/routing")
def admin_list_routing(request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        rows = db.query(RoutingRule).order_by(RoutingRule.department, RoutingRule.priority, RoutingRule.id).all()
        return {"routing_rules": [{"id": r.id, "department": r.department, "specialty": r.specialty, "doctor_id": r.doctor_id, "priority": r.priority, "active": bool(r.active)} for r in rows]}
    finally: db.close()


@app.post("/api/admin/routing")
def admin_create_routing(payload: AdminRoutingRequest, request: Request):
    actor = require_admin(request)
    db = SessionLocal()
    try:
        if payload.doctor_id and not db.query(User).filter(User.id == payload.doctor_id, User.role == "doctor").first(): raise HTTPException(status_code=404, detail="Doctor not found.")
        row = RoutingRule(department=payload.department.strip(), specialty=payload.specialty.strip(), doctor_id=payload.doctor_id, priority=payload.priority, active=int(payload.active))
        db.add(row); db.flush(); audit(db, actor["id"], actor["role"], "admin_routing_create", f"routing:{row.id}"); db.commit()
        return {"message": "Routing rule created", "routing_rule_id": row.id}
    finally: db.close()


@app.put("/api/admin/routing/{routing_id}")
def admin_update_routing(routing_id: int, payload: AdminRoutingRequest, request: Request):
    actor = require_admin(request)
    db = SessionLocal()
    try:
        row = db.query(RoutingRule).filter(RoutingRule.id == routing_id).first()
        if not row: raise HTTPException(status_code=404, detail="Routing rule not found.")
        if payload.doctor_id and not db.query(User).filter(User.id == payload.doctor_id, User.role == "doctor").first(): raise HTTPException(status_code=404, detail="Doctor not found.")
        row.department, row.specialty, row.doctor_id, row.priority, row.active = payload.department.strip(), payload.specialty.strip(), payload.doctor_id, payload.priority, int(payload.active)
        audit(db, actor["id"], actor["role"], "admin_routing_update", f"routing:{row.id}"); db.commit()
        return {"message": "Routing rule updated", "routing_rule_id": row.id}
    finally: db.close()


@app.get("/api/admin/hospital")
def admin_get_hospital(request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        row = db.query(HospitalConfiguration).first()
        if not row: row = HospitalConfiguration(); db.add(row); db.commit(); db.refresh(row)
        return {"hospital": {"id": row.id, "hospital_name": row.hospital_name, "facility_code": row.facility_code, "timezone": row.timezone, "default_department": row.default_department, "active": bool(row.active)}}
    finally: db.close()


@app.put("/api/admin/hospital")
def admin_update_hospital(payload: AdminHospitalRequest, request: Request):
    actor = require_admin(request)
    db = SessionLocal()
    try:
        row = db.query(HospitalConfiguration).first()
        if not row: row = HospitalConfiguration(); db.add(row)
        row.hospital_name, row.facility_code, row.timezone, row.default_department, row.active = payload.hospital_name.strip(), payload.facility_code.strip(), payload.timezone.strip(), payload.default_department.strip(), int(payload.active)
        row.updated_at = utc_now()
        audit(db, actor["id"], actor["role"], "admin_hospital_update", "hospital_configuration")
        db.commit(); db.refresh(row)
        return {"message": "Hospital configuration saved", "hospital": {"id": row.id, "hospital_name": row.hospital_name, "facility_code": row.facility_code, "timezone": row.timezone, "default_department": row.default_department, "active": bool(row.active)}}
    finally: db.close()


@app.get("/api/admin/analytics")
def admin_analytics(request: Request, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Aggregate operational analytics for hospital administrators.

    Metrics are read-only and intentionally aggregate; this endpoint does not
    expose individual patient records or make clinical decisions.
    """
    require_admin(request)
    db = SessionLocal()
    try:
        try:
            return build_analytics_dashboard(
                db,
                Encounter=Encounter,
                Consultation=Consultation,
                MedicalDocument=MedicalDocument,
                AuditEvent=AuditEvent,
                User=User,
                Department=Department,
                start_date=start_date,
                end_date=end_date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    finally:
        db.close()


@app.get("/api/doctor/consultations")
def doctor_consultations(request: Request):
    actor = authenticate_request(request)
    require_roles(actor, CLINICAL_ROLES, "Doctor consultation list is restricted to authorized clinical staff.")
    db = SessionLocal()
    try:
        items = db.query(Consultation).order_by(Consultation.created_at.desc()).all()
        if actor["role"] == "doctor":
            # Scope by the consultation's own encounter, not merely by patient.
            # A patient may have encounters with multiple doctors; sharing one
            # patient must not expose the other doctor's consultation records.
            assigned_encounter_ids = {row[0] for row in db.query(Encounter.id).filter(Encounter.doctor_id == actor["id"]).all()}
            items = [item for item in items if item.encounter_id in assigned_encounter_ids]
        result = []
        for item in items:
            patient = db.query(User).filter(User.id == item.patient_id).first()
            document_count = db.query(MedicalDocument).filter(MedicalDocument.patient_id == item.patient_id, MedicalDocument.encounter_id == item.encounter_id).count()
            result.append({
                "id": item.id,
                "patient_id": item.patient_id,
                "encounter_id": item.encounter_id,
                "patient_name": patient.name if patient else "Unknown",
                "title": item.title,
                "summary": item.summary,
                "status": item.status,
                "risk_level": item.risk_level or "none",
                "red_flags": json.loads(item.red_flags) if item.red_flags else [],
                "doctor_review": item.doctor_review or "Pending",
                "doctor_notes": item.doctor_notes or "",
                "ai_summary": json.loads(item.ai_summary) if item.ai_summary else None,
                "ai_summary_generated_at": item.ai_summary_generated_at.isoformat() if item.ai_summary_generated_at else None,
                "document_count": document_count,
                "created_at": item.created_at.isoformat()
            })
        return {"consultations": result}
    finally:
        db.close()
