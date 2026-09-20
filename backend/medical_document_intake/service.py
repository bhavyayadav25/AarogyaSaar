from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import hashlib
import mimetypes
import os
import uuid
import stat
import tempfile

from .models import DocumentRecord, DocumentStatus, new_document_id, utc_now

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_MIME_TYPES = {"application/pdf", "image/png", "image/jpeg"}
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB

class DocumentIntakeService:
    """
    AI-3A foundation only.
    It validates, stores metadata, creates a document record, and moves the
    document into READY_FOR_OCR. It deliberately does NOT perform OCR or
    medical interpretation.
    """

    def __init__(self, storage_dir: str = "./data/documents"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, DocumentRecord] = {}

    def _validate(self, filename: str, content_type: str, content: bytes):
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {ext or 'unknown'}. Allowed: PDF, PNG, JPG, JPEG.")
        if content_type not in ALLOWED_MIME_TYPES:
            raise ValueError(f"Unsupported MIME type: {content_type}.")
        size = len(content)
        if size <= 0:
            raise ValueError("The uploaded document is empty.")
        if size > MAX_FILE_SIZE:
            raise ValueError("Document exceeds the 15 MB size limit.")
        signatures = {
            ".pdf": content.startswith(b"%PDF-"),
            ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            ".jpg": content.startswith(b"\xff\xd8\xff"),
            ".jpeg": content.startswith(b"\xff\xd8\xff"),
        }
        if not signatures.get(ext, False):
            raise ValueError("File contents do not match the document extension.")
        expected_mime = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[ext]
        if content_type != expected_mime:
            raise ValueError("The uploaded MIME type does not match the file extension.")
        return ext

    def create(
        self,
        patient_id: str,
        encounter_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> DocumentRecord:
        ext = self._validate(filename, content_type, content)
        doc_id = new_document_id()
        safe_name = f"{doc_id}{ext}"
        target = self.storage_dir / safe_name

        now = utc_now()
        record = DocumentRecord(
            document_id=doc_id,
            encounter_id=encounter_id,
            patient_id=patient_id,
            original_filename=Path(filename).name,
            stored_filename=safe_name,
            mime_type=content_type,
            extension=ext,
            file_size=len(content),
            status=DocumentStatus.VALIDATING,
            created_at=now,
            updated_at=now,
        )
        self._records[doc_id] = record

        tmp_name = None
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=".upload-", dir=str(self.storage_dir))
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
            try:
                target.chmod(0o600)
            except OSError:
                pass
            record.status = DocumentStatus.QUEUED
            record.updated_at = utc_now()

            # AI-3A ends at the OCR boundary.
            record.status = DocumentStatus.READY_FOR_OCR
            record.updated_at = utc_now()
            return record
        except Exception as exc:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
            record.status = DocumentStatus.FAILED
            record.error = "Document could not be stored."
            record.updated_at = utc_now()
            raise RuntimeError("Document intake failed.") from exc

    def get(self, document_id: str) -> Optional[DocumentRecord]:
        return self._records.get(document_id)

    def list_for_encounter(self, encounter_id: str) -> List[DocumentRecord]:
        return [r for r in self._records.values() if r.encounter_id == encounter_id]

    def content_path(self, document_id: str) -> Path:
        record = self._records.get(document_id)
        if not record:
            raise KeyError("Document not found.")
        path = self.storage_dir / record.stored_filename
        if not path.exists():
            raise FileNotFoundError("Stored document is unavailable.")
        return path

    def sha256(self, document_id: str) -> str:
        path = self.content_path(document_id)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def delete(self, document_id: str) -> bool:
        record = self._records.pop(document_id, None)
        if not record:
            return False
        path = self.storage_dir / record.stored_filename
        try:
            path.unlink(missing_ok=True)
        finally:
            return True
