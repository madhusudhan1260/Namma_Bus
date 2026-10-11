"""
Private document storage for student verification uploads.

- Type is decided from the file's magic bytes (PDF/JPEG/PNG), not the client-supplied content type.
- Size limit enforced while reading. Malware scan hook runs before anything is stored.
- Files are encrypted (Fernet) and written under a random storage key in ACCESS_UPLOAD_DIR, which is not
  web-served. The database stores metadata only; viewing goes through an authorized, short-lived signed URL.
"""

import hashlib
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from .config import settings
from .models import Document, StudentStatus
from .providers.scanner import get_scanner
from .security import decrypt_bytes, encrypt_bytes

ALLOWED_TYPES = {
    b"%PDF-": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}
DOCUMENT_TYPES = {"STUDENT_BUS_PASS", "COLLEGE_ID", "SUPPORTING", "COLLEGE_REGISTRATION", "PROFILE_PHOTO", "AADHAAR_EKYC_PHOTO"}


def sniff_mime(data: bytes) -> Optional[str]:
    for magic, mime in ALLOWED_TYPES.items():
        if data.startswith(magic):
            return mime
    return None


def _storage_dir() -> Path:
    path = Path(settings.upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


async def read_limited(upload: UploadFile) -> bytes:
    limit = settings.max_upload_bytes
    chunks = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=f"File too large (max {limit // (1024 * 1024)} MB).")
        chunks.append(chunk)
    return b"".join(chunks)


async def store_document(db: Session, owner_id: str, document_type: str, upload: UploadFile) -> Document:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unknown document type.")
    return store_bytes(db, owner_id, document_type, await read_limited(upload))


def store_bytes(db: Session, owner_id: str, document_type: str, data: bytes) -> Document:
    """Encrypt and store bytes produced server-side (e.g. the photo inside a verified e-KYC file)."""
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unknown document type.")
    if not data:
        raise HTTPException(status_code=400, detail=f"{document_type}: the file is empty.")
    mime = sniff_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail=f"{document_type}: only PDF, JPEG or PNG files are accepted.")
    scan = get_scanner().scan(data)
    if scan == "INFECTED":
        raise HTTPException(status_code=422, detail=f"{document_type}: the file failed the security scan and was rejected.")
    storage_reference = secrets.token_hex(24)
    (_storage_dir() / storage_reference).write_bytes(encrypt_bytes(data))
    doc = Document(
        owner_id=owner_id,
        document_type=document_type,
        storage_reference=storage_reference,
        mime_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        scan_status=scan,
        verification_status=StudentStatus.PENDING,
    )
    db.add(doc)
    db.flush()
    return doc


def read_document(doc: Document) -> bytes:
    path = _storage_dir() / doc.storage_reference
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document not found.")
    return decrypt_bytes(path.read_bytes())
