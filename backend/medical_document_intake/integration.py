"""AI-3A document-intake integration helper."""

from fastapi import FastAPI
from typing import Optional
from .router import build_router, AuthorizationCallback
from .service import DocumentIntakeService


def register_medical_document_intake(
    app: FastAPI,
    storage_dir: str = "./data/documents",
    *,
    authorize: Optional[AuthorizationCallback] = None,
    enforce_auth: bool = True,
):
    """
    Register the AI-3A document intake routes.

    The production/unified backend should leave ``enforce_auth=True`` and pass
    a DB-backed ``authorize`` callback. ``enforce_auth=False`` exists only for
    isolated module tests that do not have the application's authentication
    middleware or database available.
    """
    service = DocumentIntakeService(storage_dir=storage_dir)
    app.include_router(build_router(service, authorize=authorize, enforce_auth=enforce_auth))
    app.state.medical_document_intake_document_service = service
    return service
