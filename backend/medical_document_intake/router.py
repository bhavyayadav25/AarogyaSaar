from __future__ import annotations
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Request
from typing import Callable, Optional

from .service import DocumentIntakeService

CLINICAL_ROLES = {"doctor", "triage", "admin"}
ALL_DOCUMENT_ROLES = {"patient", "doctor", "triage", "admin"}

# Callback signature: (actor, patient_id, encounter_id, action) -> None.
# The integrated backend supplies a DB-backed implementation so AI-3A cannot
# trust client-supplied patient/encounter identifiers.
AuthorizationCallback = Callable[[dict, str, str, str], None]


def build_router(
    service: DocumentIntakeService,
    *,
    authorize: Optional[AuthorizationCallback] = None,
    enforce_auth: bool = True,
) -> APIRouter:
    # Namespaced to avoid colliding with the legacy /api/documents routes in the existing backend.
    router = APIRouter(prefix="/api/documents/intake", tags=["AI-3A Documents"])

    def actor_for(request: Request) -> dict:
        actor = getattr(request.state, "actor", None)
        if enforce_auth and not actor:
            raise HTTPException(status_code=401, detail="Authentication required.")
        if actor and actor.get("role") not in ALL_DOCUMENT_ROLES:
            raise HTTPException(status_code=403, detail="Not authorized to access clinical documents.")
        return actor

    def authorize_record(actor: dict, record, action: str):
        if not actor:
            # Only permitted for explicitly isolated legacy/standalone tests.
            return
        if authorize:
            authorize(actor, str(record.patient_id), str(record.encounter_id), action)
            return
        # Safe fallback when this router is mounted without a DB-backed callback:
        # patients may only touch their own records; clinical staff may read/write.
        if actor["role"] == "patient" and str(actor["id"]) != str(record.patient_id):
            raise HTTPException(status_code=403, detail="You are not authorized to access this document.")
        if action in {"list", "get", "delete"} and actor["role"] not in ALL_DOCUMENT_ROLES:
            raise HTTPException(status_code=403, detail="Not authorized to access clinical documents.")

    @router.post("/upload")
    async def upload_document(
        request: Request,
        patient_id: str = Form(...),
        encounter_id: str = Form(...),
        document: UploadFile = File(...),
    ):
        actor = actor_for(request)
        if actor and authorize:
            authorize(actor, patient_id, encounter_id, "upload")
        elif actor and actor["role"] == "patient" and str(actor["id"]) != str(patient_id):
            raise HTTPException(status_code=403, detail="Patients can upload documents only for themselves.")

        try:
            content = await document.read()
            record = service.create(
                patient_id=patient_id,
                encounter_id=encounter_id,
                filename=document.filename or "document",
                content_type=document.content_type or "application/octet-stream",
                content=content,
            )
            return {
                "success": True,
                "document": record.to_dict(),
                "next_stage": "OCR",
                "message": "Document accepted and ready for OCR.",
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/encounter/{encounter_id}")
    async def list_documents(encounter_id: str, request: Request):
        actor = actor_for(request)
        if actor and authorize:
            # Patient identity is resolved from the stored records by the callback.
            records = service.list_for_encounter(encounter_id)
            if not records:
                # Avoid leaking whether an encounter exists to an unauthorized caller.
                raise HTTPException(status_code=404, detail="No documents found for this encounter.")
            authorize_record(actor, records[0], "list")
        elif actor and actor["role"] == "patient":
            records = service.list_for_encounter(encounter_id)
            if any(str(r.patient_id) != str(actor["id"]) for r in records):
                raise HTTPException(status_code=403, detail="You are not authorized to access this encounter's documents.")
        else:
            records = service.list_for_encounter(encounter_id)
        return {"documents": [r.to_dict() for r in records]}

    @router.get("/{document_id}")
    async def get_document(document_id: str, request: Request):
        actor = actor_for(request)
        record = service.get(document_id)
        if not record:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_record(actor, record, "get")
        return {"document": record.to_dict()}

    @router.delete("/{document_id}")
    async def delete_document(document_id: str, request: Request):
        actor = actor_for(request)
        record = service.get(document_id)
        if not record:
            raise HTTPException(status_code=404, detail="Document not found.")
        authorize_record(actor, record, "delete")
        if not service.delete(document_id):
            raise HTTPException(status_code=404, detail="Document not found.")
        return {"success": True, "document_id": document_id}

    return router
