"""AI-5C: doctor workspace aggregation.

Read-only orchestration layer for the clinician workstation. It assembles
already persisted patient/encounter information and existing AI outputs. It
never diagnoses, prescribes, edits records, or treats absence of data as a
negative clinical finding.
"""
from __future__ import annotations
import json
from typing import Any, Dict, Iterable

CLINICAL_ROLES = {"doctor", "triage", "admin"}


def _json_load(value, default):
    import json
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _patient_snapshot(patient: Any) -> Dict[str, Any]:
    profile = getattr(patient, "profile", None)
    return {
        "id": patient.id,
        "name": patient.name,
        "age": getattr(profile, "age", None) if profile else None,
        "gender": getattr(profile, "gender", None) if profile else None,
        "blood_group": getattr(profile, "blood_group", None) if profile else None,
        "allergies": getattr(profile, "allergies", None) if profile else None,
        "conditions": getattr(profile, "conditions", None) if profile else None,
        "medications": getattr(profile, "medications", None) if profile else None,
    }


def _document_summary(documents: Iterable[Any]) -> list[Dict[str, Any]]:
    result = []
    for doc in documents:
        result.append({
            "id": doc.id,
            "filename": doc.filename,
            "document_type": doc.document_type,
            "encounter_id": getattr(doc, "encounter_id", None),
            "patient_id": getattr(doc, "patient_id", None),
            "classification": doc.classification or doc.document_type,
            "classification_confidence": float(doc.classification_confidence or 0),
            "classification_needs_review": bool(doc.classification_needs_review),
            "verification_status": doc.verification_status or "Pending",
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "verified_at": doc.verified_at.isoformat() if doc.verified_at else None,
        })
    return result


def build_doctor_workspace(patient: Any, encounter: Any, documents: Iterable[Any],
                           consultations: Iterable[Any], summary: Dict[str, Any],
                           risk: Dict[str, Any], decision_support: Dict[str, Any],
                           medication: Dict[str, Any], investigations: Dict[str, Any],
                           copilot: Dict[str, Any], clinical_gate: Dict[str, Any],
                           timeline: list, ayush_assessments: Iterable[Any] = ()) -> Dict[str, Any]:
    pending_documents = [d.id for d in documents if (d.verification_status or "Pending") != "Verified"]
    consultations_list = list(consultations)
    latest_consultation = consultations_list[0] if consultations_list else None
    risk_level = (risk or {}).get("risk_level", "none")
    # Keep the General Doctor evidence independent from the optional AYUSH record.
    consultation_records = [(c, _json_load(c.structured_data, {})) for c in consultations_list]
    # The clinician-owned consultation is an editable documentation record. It
    # must never become the source for the patient history just because it was
    # created after the handoff record. Otherwise clicking "Start consultation"
    # would make the previously visible interview/summary appear empty.
    handoff_records = [
        (c, structured) for c, structured in consultation_records
        if getattr(c, "consultation_type", None) != "clinician" and c.title != "Clinical consultation"
    ]
    general_consultation = next((
        c for c, structured in handoff_records
        if (getattr(c, "consultation_type", None) or ("ayush" if c.title == "AYUSH / Ayurveda intake" else "handoff")) == "handoff"
        and structured.get("care_type", "allopathy") == "allopathy"
    ), None)
    ayush_consultation = next((
        c for c, structured in handoff_records
        if getattr(c, "consultation_type", None) == "ayush" or structured.get("care_type") == "ayush" or c.title == "AYUSH / Ayurveda intake"
    ), None)
    evidence_source = general_consultation or latest_consultation
    interview = []
    if evidence_source:
        structured = _json_load(evidence_source.structured_data, {})
        evidence = structured.get("clinical_evidence", []) if isinstance(structured, dict) else []
        for item in evidence if isinstance(evidence, list) else []:
            interview.append({
                "question_id": item.get("question_id"),
                "question": item.get("question") or item.get("question_id") or "Interview question",
                "answer": item.get("text", ""),
                "skipped": bool(item.get("skipped")),
                "input_mode": item.get("input_mode") or ("skipped" if item.get("skipped") else "text"),
            })
    ayush_list = []
    for row in ayush_assessments or []:
        ayush_list.append({
            "id": row.id, "system": row.system, "assessment_type": row.assessment_type,
            "summary": row.summary, "responses": _json_load(row.responses, {}),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return {
        "workspace_version": "AI-5C.1",
        "read_only": True,
        "patient": _patient_snapshot(patient),
        "encounter": {
            "id": encounter.id,
            "department": encounter.department,
            "language": getattr(encounter, "language", None) or "en-IN",
            "visit_date": encounter.visit_date,
            "token_number": encounter.token_number,
            "priority": encounter.priority,
            "status": encounter.status,
            "reason": encounter.reason or "",
            "care_type": getattr(encounter, "care_type", None) or "allopathy",
            "doctor_id": encounter.doctor_id,
        },
        "overview": {
            "latest_consultation_id": latest_consultation.id if latest_consultation else None,
            "document_count": len(_document_summary(documents)),
            "timeline_event_count": len(timeline),
            "pending_document_verifications": pending_documents,
            "risk_level": risk_level,
        },
        "clinical_summary": summary,
        "risk_assessment": risk,
        "decision_support": decision_support,
        "medication_intelligence": medication,
        "investigation_intelligence": investigations,
        "timeline": timeline,
        "documents": _document_summary(documents),
        "interview": interview,
        "ayush_assessments": ayush_list,
        "general_consultation": ({
            "id": general_consultation.id,
            "title": general_consultation.title,
            "consultation_type": getattr(general_consultation, "consultation_type", None) or "handoff",
            "summary": general_consultation.summary,
            "ai_summary": _json_load(general_consultation.ai_summary, None),
            "structured": _json_load(general_consultation.structured_data, {}),
            "nlp": _json_load(general_consultation.nlp_data, {}),
            "red_flags": _json_load(general_consultation.red_flags, []),
            "doctor_review": general_consultation.doctor_review,
        } if general_consultation else None),
        "ayush_consultation": ({
            "id": ayush_consultation.id,
            "consultation_type": getattr(ayush_consultation, "consultation_type", None) or "ayush",
            "title": ayush_consultation.title,
            "summary": ayush_consultation.summary,
            "ai_summary": _json_load(ayush_consultation.ai_summary, None),
            "structured": _json_load(ayush_consultation.structured_data, {}),
            "red_flags": _json_load(ayush_consultation.red_flags, []),
        } if ayush_consultation else None),
        "consultations": [
            {
                "id": c.id, "encounter_id": getattr(c, "encounter_id", None), "patient_id": getattr(c, "patient_id", None), "title": c.title, "summary": c.summary,
                "consultation_type": getattr(c, "consultation_type", None) or ("clinician" if c.title == "Clinical consultation" else "ayush" if c.title == "AYUSH / Ayurveda intake" else "handoff"),
                "care_type": (_json_load(c.structured_data, {}).get("care_type") or ("ayush" if c.title == "AYUSH / Ayurveda intake" else "allopathy")),
                "status": c.status, "risk_level": c.risk_level,
                "red_flags": _json_load(c.red_flags, []),
                "ai_summary": _json_load(c.ai_summary, None),
                "structured": _json_load(c.structured_data, {}),
                "nlp": _json_load(c.nlp_data, {}),
                "doctor_review": c.doctor_review,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            } for c in consultations_list
        ],
        "consultation_copilot": copilot,
        "clinical_gate": clinical_gate,
        "safety": {
            "diagnosis_generated": False,
            "prescription_generated": False,
            "autonomous_clinical_decision": False,
            "unverified_document_data_used_as_verified_evidence": False,
            "clinician_decision_required": True,
        },
    }
