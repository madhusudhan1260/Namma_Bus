"""Identity verification (consent → provider → callback) and face verification for travellers."""

import hashlib
import html
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..eligibility import current_identity_verification, load_policy
from ..documents import read_document, read_limited, store_bytes
from ..models import Document, FaceVerificationAttempt, Gender, IdentityVerification, User, VerificationStatus
from ..providers.aadhaar_ekyc import EkycError, identity_fingerprint, name_letters, names_match, verify_ekyc
from ..providers.eaadhaar_pdf import load_anchors, verify_eaadhaar_pdf
from ..providers.biometric import DEV_LABEL as BIO_DEV_LABEL, get_biometric_provider
from ..providers.identity import DEV_LABEL, IdentityProviderUnavailable, get_identity_provider
from ..rbac import TRAVELLER_ROLES, require_roles
from ..security import client_ip, rate_limiter, sha256_hex

router = APIRouter(tags=["Access: Identity & Face Verification"])

UNAVAILABLE_MSG = "Identity verification is temporarily unavailable."
NO_AADHAAR_MSG = "Identity eligibility could not be verified. You can still travel by purchasing a regular ticket."
APP_RETURN_URL = os.getenv("ACCESS_APP_RETURN_URL", "http://localhost:8082/access/passenger")
MAX_CAPTURE_BYTES = 3 * 1024 * 1024


class AadhaarAnswer(BaseModel):
    has_aadhaar: bool


class StartRequest(BaseModel):
    consent: bool


@router.post("/identity/aadhaar-answer")
def aadhaar_answer(req: AadhaarAnswer, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)),
                   db: Session = Depends(get_db, scope="function")):
    profile = user.passenger_profile
    if not profile:
        raise HTTPException(status_code=400, detail="Passenger profile missing.")
    profile.has_aadhaar_answer = req.has_aadhaar
    if not req.has_aadhaar and profile.identity_status != VerificationStatus.VERIFIED:
        profile.identity_status = VerificationStatus.DECLINED
    audit(db, "IDENTITY_AADHAAR_ANSWER", user, "user", user.id, {"has_aadhaar": req.has_aadhaar}, client_ip(request))
    return {
        "has_aadhaar": req.has_aadhaar,
        "identity_status": profile.identity_status.value,
        "message": None if req.has_aadhaar else NO_AADHAAR_MSG,
        "next_step": "IDENTITY_CONSENT" if req.has_aadhaar else "DASHBOARD",
    }


@router.post("/identity/start")
def identity_start(req: StartRequest, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)),
                   db: Session = Depends(get_db, scope="function")):
    if not req.consent:
        raise HTTPException(status_code=400, detail="Explicit consent is required before identity verification.")
    rate_limiter.check(f"identity-start:{user.id}", limit=5)
    provider = get_identity_provider()
    if not provider.available():
        raise HTTPException(status_code=503, detail=UNAVAILABLE_MSG)
    state = secrets.token_urlsafe(32)
    api_base = str(request.url).split("/identity/start")[0]
    try:
        url = provider.authorization_url(state, api_base)
    except IdentityProviderUnavailable:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_MSG)
    now = datetime.now(timezone.utc)
    iv = IdentityVerification(
        user_id=user.id,
        provider=provider.name,
        verification_status=VerificationStatus.PENDING,
        consent_given_at=now,
        state_hash=sha256_hex(state),
        is_development=provider.is_development,
    )
    db.add(iv)
    if user.passenger_profile:
        user.passenger_profile.has_aadhaar_answer = True
        if user.passenger_profile.identity_status != VerificationStatus.VERIFIED:
            user.passenger_profile.identity_status = VerificationStatus.PENDING
    audit(db, "IDENTITY_VERIFICATION_STARTED", user, "identity_verification", iv.id, {"provider": provider.name}, client_ip(request))
    return {
        "verification_id": iv.id,
        "authorization_url": url,
        "provider": provider.name,
        "is_development": provider.is_development,
        "label": DEV_LABEL if provider.is_development else None,
    }


EKYC_PROVIDER = "UIDAI_OFFLINE_EKYC"
PDF_PROVIDER = "UIDAI_EAADHAAR_PDF"
EKYC_STATUS_FOR_ERROR = {"UNAVAILABLE": 503, "BAD_SHARE_CODE": 400, "BAD_PASSWORD": 400, "BAD_FILE": 400, "TOO_OLD": 400,
                         "BAD_SIGNATURE": 422, "NOT_SIGNED": 422}


def _fingerprint_key() -> bytes:
    return hashlib.sha256(b"namma-bus-ekyc-fingerprint|" + settings.ticket_signing_secret.encode()).digest()


@router.get("/identity/aadhaar-ekyc/info")
def ekyc_info():
    """Whether UIDAI Offline e-KYC verification is configured, and what the passenger needs to do."""
    zip_ok = bool(settings.uidai_cert_path) and os.path.exists(settings.uidai_cert_path)
    pdf_ok = bool(load_anchors(settings.trusted_ca_dir)) or zip_ok
    configured = zip_ok or pdf_ok
    return {
        "available": configured,
        "zip_available": zip_ok,
        "pdf_available": pdf_ok,
        "max_age_hours": settings.ekyc_max_age_hours,
        "download_url": "https://myaadhaar.uidai.gov.in/offline-ekyc",
        "message": None if configured else "Aadhaar e-KYC verification is not configured on this server yet.",
    }


@router.post("/identity/aadhaar")
@router.post("/identity/aadhaar-ekyc")
async def aadhaar_ekyc(
    request: Request,
    consent: bool = Form(...),
    share_code: Optional[str] = Form(default=None, max_length=4),
    pdf_password: Optional[str] = Form(default=None, max_length=12),
    ekyc_file: UploadFile = File(...),
    user: User = Depends(require_roles(*TRAVELLER_ROLES)),
    db: Session = Depends(get_db, scope="function"),
):
    """
    Verify a UIDAI-signed Aadhaar document: the e-Aadhaar PDF (with its password) or the Paperless Offline e-KYC
    ZIP (with its share code). Real verification: UIDAI's digital signature must be valid. Kept: name match flag,
    DOB, gender and the UIDAI photo (encrypted). Never kept: Aadhaar number, address, password / share code, the file.
    """
    if not consent:
        raise HTTPException(status_code=400, detail="Consent is required before verifying your Aadhaar e-KYC.")
    rate_limiter.check(f"ekyc:{user.id}", limit=5)
    data = await read_limited(ekyc_file)
    ip = client_ip(request)
    is_pdf = data[:5] == b"%PDF-"
    provider_name = PDF_PROVIDER if is_pdf else EKYC_PROVIDER
    try:
        if is_pdf:
            result = verify_eaadhaar_pdf(data, pdf_password or "", settings.trusted_ca_dir, pinned_cert_path=settings.uidai_cert_path)
        else:
            result = verify_ekyc(data, (share_code or "").strip(), settings.uidai_cert_path, settings.ekyc_max_age_hours)
    except EkycError as e:
        audit(db, "AADHAAR_EKYC_FAILED", user, "user", user.id, {"reason": e.code}, ip, result="FAILURE")
        if e.code == "BAD_SIGNATURE" and user.passenger_profile:
            user.passenger_profile.identity_status = VerificationStatus.FAILED
        db.commit()
        raise HTTPException(status_code=EKYC_STATUS_FOR_ERROR.get(e.code, 400), detail={"code": e.code, "message": e.message})
    finally:
        del data
    if not result.photo_jpeg:
        raise HTTPException(status_code=400, detail={"code": "NO_PHOTO", "message": "No photo could be found in this file, so face verification is not possible."})

    fingerprint = identity_fingerprint(_fingerprint_key(), result)
    other = db.scalars(select(IdentityVerification).where(IdentityVerification.identity_fingerprint == fingerprint,
                                                          IdentityVerification.user_id != user.id,
                                                          IdentityVerification.verification_status == VerificationStatus.VERIFIED)).first()
    if other:
        audit(db, "AADHAAR_EKYC_DUPLICATE", user, "user", user.id, {"other_account": other.user_id}, ip, result="DENIED")
        db.commit()
        raise HTTPException(status_code=409, detail={"code": "ALREADY_USED",
                                                     "message": "This Aadhaar is already verified on another Namma Bus account. Contact support if this is a mistake."})

    now = datetime.now(timezone.utc)
    # Any earlier verification of this account is superseded
    for old in db.scalars(select(IdentityVerification).where(IdentityVerification.user_id == user.id,
                                                             IdentityVerification.verification_status == VerificationStatus.VERIFIED)).all():
        old.verification_status = VerificationStatus.REVOKED
    photo = store_bytes(db, user.id, "AADHAAR_EKYC_PHOTO", result.photo_jpeg)
    name_ok = names_match(result.name, user.name) if result.name else name_letters(user.name) == result.name4
    iv = IdentityVerification(
        user_id=user.id, provider=provider_name, verification_status=VerificationStatus.VERIFIED,
        verification_reference=f"EKYC-{secrets.token_hex(8).upper()}", consent_given_at=now,
        attributes={"gender": result.gender, "name_matches_account": name_ok}, is_development=False,
        verified_at=now, expires_at=now + timedelta(days=settings.identity_verification_valid_days),
        reference_photo_document_id=photo.id, identity_fingerprint=fingerprint,
    )
    db.add(iv)
    if result.date_of_birth:
        user.date_of_birth = result.date_of_birth  # UIDAI-verified DOB replaces the self-declared one
    profile = user.passenger_profile
    if profile:
        profile.has_aadhaar_answer = True
        profile.identity_status = VerificationStatus.VERIFIED
    db.flush()
    audit(db, "AADHAAR_EKYC_VERIFIED", user, "identity_verification", iv.id,
          {"gender": result.gender, "name_matches_account": name_ok, "source": provider_name}, ip)
    return {
        "identity_status": "VERIFIED",
        "provider": provider_name,
        "verification_reference": iv.verification_reference,
        "gender_attested": result.gender,
        "name_matches_account": name_ok,
        "date_of_birth": result.date_of_birth.isoformat() if result.date_of_birth else None,
        "expires_at": iv.expires_at.isoformat(),
        "message": "Aadhaar verified with UIDAI's digital signature. Your face will be checked against the Aadhaar photo when you take a free ticket.",
    }


@router.get("/identity/mock-consent", response_class=HTMLResponse, include_in_schema=False)
def mock_consent_page(state: str):
    provider = get_identity_provider()
    if not provider.is_development:
        raise HTTPException(status_code=404)
    s = html.escape(state)
    return HTMLResponse(f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Development verification</title>
<style>body{{font-family:system-ui;margin:0;background:#FFF7E6;color:#3a2a00}}main{{max-width:560px;margin:24px auto;padding:16px}}
.banner{{background:#B45309;color:#fff;padding:12px;border-radius:8px;font-weight:800}}a{{display:block;margin:12px 0;padding:14px;border-radius:8px;
text-align:center;font-weight:700;text-decoration:none;border:2px solid #92400E;color:#92400E}}</style></head><body><main>
<div class="banner">{html.escape(DEV_LABEL)}</div>
<h1>Namma Bus development identity simulator</h1>
<p>This page is part of the Namma Bus development setup. It is <b>not</b> DigiLocker, it does not verify Aadhaar,
and it never asks for any password or document. Choose the result to simulate:</p>
<a href="callback?state={s}&code=mock-verified-female">Simulate verified identity (attested female)</a>
<a href="callback?state={s}&code=mock-verified-male">Simulate verified identity (attested male)</a>
<a href="callback?state={s}&code=mock-failed">Simulate failed verification</a>
</main></body></html>""")


def _complete(db: Session, state: str, code: str, ip: Optional[str]) -> IdentityVerification:
    iv = db.scalars(
        select(IdentityVerification).where(
            IdentityVerification.state_hash == sha256_hex(state),
            IdentityVerification.verification_status == VerificationStatus.PENDING,
        )
    ).first()
    if not iv:
        raise HTTPException(status_code=400, detail="Verification session not found or already completed.")
    provider = get_identity_provider()
    result = provider.complete(code)
    now = datetime.now(timezone.utc)
    iv.state_hash = None  # single use
    user = db.get(User, iv.user_id)
    if result.status == "VERIFIED":
        iv.verification_status = VerificationStatus.VERIFIED
        iv.verification_reference = result.reference
        iv.attributes = {k: v for k, v in result.attributes.items() if k in {"gender"}}  # data minimisation
        iv.verified_at = now
        iv.expires_at = now + timedelta(days=settings.identity_verification_valid_days)
    elif result.status == "UNAVAILABLE":
        iv.verification_status = VerificationStatus.UNAVAILABLE
    else:
        iv.verification_status = VerificationStatus.FAILED
    if user and user.passenger_profile:
        user.passenger_profile.identity_status = (
            VerificationStatus.VERIFIED if current_identity_verification(db, user.id) or iv.verification_status == VerificationStatus.VERIFIED
            else iv.verification_status
        )
    audit(db, "IDENTITY_VERIFICATION_COMPLETED", user, "identity_verification", iv.id,
          {"status": iv.verification_status.value, "provider": iv.provider, "development": iv.is_development}, ip)
    return iv


@router.get("/identity/callback", include_in_schema=False)
def identity_callback_redirect(state: str, code: str, request: Request, db: Session = Depends(get_db, scope="function")):
    iv = _complete(db, state, code, client_ip(request))
    return RedirectResponse(f"{APP_RETURN_URL}?identity={iv.verification_status.value}", status_code=303)


class CallbackRequest(BaseModel):
    state: str
    code: str


@router.post("/identity/callback")
def identity_callback(req: CallbackRequest, request: Request, db: Session = Depends(get_db, scope="function")):
    iv = _complete(db, req.state, req.code, client_ip(request))
    return {"status": iv.verification_status.value, "is_development": iv.is_development}


@router.get("/identity/status")
def identity_status(user: User = Depends(require_roles(*TRAVELLER_ROLES)), db: Session = Depends(get_db, scope="function")):
    iv = current_identity_verification(db, user.id)
    latest = db.scalars(select(IdentityVerification).where(IdentityVerification.user_id == user.id)
                        .order_by(IdentityVerification.created_at.desc())).first()
    provider = get_identity_provider()
    profile = user.passenger_profile
    status = "VERIFIED" if iv else (latest.verification_status.value if latest else (profile.identity_status.value if profile else "NOT_STARTED"))
    return {
        "identity_status": status,
        "provider": (iv or latest).provider if (iv or latest) else None,
        "verification_reference": iv.verification_reference if iv else None,
        "verified_at": iv.verified_at.isoformat() if iv and iv.verified_at else None,
        "expires_at": iv.expires_at.isoformat() if iv and iv.expires_at else None,
        "is_development": bool((iv or latest) and (iv or latest).is_development),
        "label": DEV_LABEL if (iv or latest) and (iv or latest).is_development else None,
        "service_available": provider.available(),
        "message": None if provider.available() else UNAVAILABLE_MSG,
    }


def purge_expired_face_attempts(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.biometric_audit_retention_days)
    res = db.execute(delete(FaceVerificationAttempt).where(FaceVerificationAttempt.created_at < cutoff))
    return res.rowcount or 0


@router.post("/face/verify")
@router.post("/biometric/verify")
async def biometric_verify(
    request: Request,
    consent: bool = Form(...),
    image: UploadFile = File(...),
    mock_outcome: Optional[str] = Form(default=None),
    user: User = Depends(require_roles(*TRAVELLER_ROLES)),
    db: Session = Depends(get_db, scope="function"),
):
    if not consent:
        raise HTTPException(status_code=400, detail="Consent is required before using the camera for face verification.")
    rate_limiter.check(f"face:{user.id}", limit=5)
    iv = current_identity_verification(db, user.id)
    if not iv:
        raise HTTPException(status_code=409, detail="Verify your identity first.")
    capture = await image.read(MAX_CAPTURE_BYTES + 1)
    if len(capture) > MAX_CAPTURE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large.")
    provider = get_biometric_provider()
    reference_image = None
    if provider.needs_reference_image and iv.reference_photo_document_id:
        doc = db.get(Document, iv.reference_photo_document_id)
        reference_image = read_document(doc) if doc else None
    if not provider.available():
        result = None
        outcome, reference, detail = "UNAVAILABLE", None, "Face verification is temporarily unavailable."
    else:
        result = provider.verify(capture, iv.verification_reference or "", mock_outcome=mock_outcome if provider.is_development else None,
                                 reference_image=reference_image)
        outcome, reference, detail = result.result, result.reference, result.detail
    del reference_image
    del capture  # never persisted
    now = datetime.now(timezone.utc)
    valid_seconds = int(load_policy().get("face_verification_valid_seconds", 600))
    attempt = FaceVerificationAttempt(
        user_id=user.id, identity_verification_id=iv.id, provider=provider.name, result=outcome,
        verification_reference=reference, consent_given_at=now, is_development=provider.is_development,
        match_score=result.score if result else None,
        expires_at=now + timedelta(seconds=valid_seconds),
    )
    db.add(attempt)
    purge_expired_face_attempts(db)
    db.flush()
    audit(db, "FACE_VERIFICATION", user, "face_verification", attempt.id, {"result": outcome, "provider": provider.name}, client_ip(request))
    messages = {
        "MATCH": "Identity verified successfully.",
        "NO_MATCH": "Identity verification could not be completed. You can purchase a regular ticket instead.",
        "UNAVAILABLE": "Face verification is temporarily unavailable. You can purchase a regular ticket instead.",
        "ERROR": detail or "Face verification could not be completed. You can purchase a regular ticket instead.",
    }
    return {
        "face_verification_id": attempt.id,
        "result": outcome,
        "message": messages.get(outcome, messages["ERROR"]),
        "expires_at": attempt.expires_at.isoformat(),
        "is_development": provider.is_development,
        "label": BIO_DEV_LABEL if provider.is_development else None,
    }


@router.post("/face/start")
def face_start(req: StartRequest, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)), db: Session = Depends(get_db, scope="function")):
    """Consent step before the camera opens. Nothing is captured here."""
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent is required before using the camera for face verification.")
    if not current_identity_verification(db, user.id):
        raise HTTPException(status_code=409, detail="Verify your identity first.")
    provider = get_biometric_provider()
    audit(db, "FACE_CONSENT_GIVEN", user, "user", user.id, {"provider": provider.name}, client_ip(request))
    return {"ready": provider.available(), "provider": provider.name, "is_development": provider.is_development,
            "label": BIO_DEV_LABEL if provider.is_development else None,
            "message": None if provider.available() else "Face verification is temporarily unavailable."}


@router.get("/face/status")
def face_status(user: User = Depends(require_roles(*TRAVELLER_ROLES)), db: Session = Depends(get_db, scope="function")):
    last = db.scalars(select(FaceVerificationAttempt).where(FaceVerificationAttempt.user_id == user.id)
                      .order_by(FaceVerificationAttempt.created_at.desc())).first()
    now = datetime.now(timezone.utc)
    exp = last.expires_at if last and last.expires_at and last.expires_at.tzinfo else (last.expires_at.replace(tzinfo=timezone.utc) if last and last.expires_at else None)
    return {
        "last_result": last.result if last else None,
        "last_attempt_at": last.created_at.isoformat() if last and last.created_at else None,
        "valid_now": bool(last and last.result == "MATCH" and exp and exp > now),
        "expires_at": exp.isoformat() if exp else None,
        "is_development": bool(last and last.is_development),
        "service_available": get_biometric_provider().available(),
    }
