"""Passenger self-service: profile (name, DOB, photo) and a plain-language eligibility summary."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..documents import store_document
from ..eligibility import current_identity_verification, effective_student_status, evaluate
from ..models import Document, PassengerProfile, Ticket, User
from ..rbac import TRAVELLER_ROLES, require_roles
from ..security import client_ip
from ..config import settings
from ..security import sign_document_token
from .auth import passenger_category, validate_dob

router = APIRouter(tags=["Access: Passenger"])
traveller = require_roles(*TRAVELLER_ROLES)

REASON_TEXT = {
    "ELIGIBLE_FREE": "You are eligible for a free ticket.",
    "NOT_ELIGIBLE": "You are not eligible for a free ticket. Regular fare applies.",
    "VERIFICATION_REQUIRED": "Verification is required before a free ticket can be issued.",
    "VERIFICATION_EXPIRED": "Your verification has expired. Please verify again.",
    "VERIFICATION_FAILED": "Verification could not be completed. You can buy a regular ticket.",
}


def _profile_view(db: Session, user: User) -> dict:
    profile = db.get(PassengerProfile, user.id)
    photo_url = None
    if user.profile_photo_document_id:
        token = sign_document_token(user.profile_photo_document_id, user.id, settings.document_url_ttl_seconds)
        photo_url = f"documents/{user.profile_photo_document_id}/content?token={token}"
    return {
        "name": user.name,
        "email": user.email,
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "gender": profile.gender.value if profile else None,
        "category": passenger_category(db, user),
        "has_bus_pass_answer": profile.has_bus_pass_answer if profile else None,
        "has_aadhaar_answer": profile.has_aadhaar_answer if profile else None,
        "profile_photo_url": photo_url,
    }


@router.get("/passenger/profile")
def get_profile(user: User = Depends(traveller), db: Session = Depends(get_db, scope="function")):
    return _profile_view(db, user)


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    date_of_birth: Optional[date] = None


@router.put("/passenger/profile")
def update_profile(req: ProfileUpdate, request: Request, user: User = Depends(traveller), db: Session = Depends(get_db, scope="function")):
    """Only name and DOB are editable. Gender / category answers are fixed after registration (they drive eligibility)."""
    changed = []
    if req.name is not None:
        user.name = " ".join(req.name.split())
        changed.append("name")
    if req.date_of_birth is not None:
        validate_dob(req.date_of_birth)
        user.date_of_birth = req.date_of_birth
        changed.append("date_of_birth")
    if changed:
        audit(db, "PROFILE_UPDATED", user, "user", user.id, {"fields": changed}, client_ip(request))
    return _profile_view(db, user)


@router.post("/passenger/profile/photo")
async def upload_photo(request: Request, photo: UploadFile = File(...), user: User = Depends(traveller), db: Session = Depends(get_db, scope="function")):
    """Optional profile photo. Stored encrypted and private; it is NOT used for face verification."""
    doc = await store_document(db, user.id, "PROFILE_PHOTO", photo)
    if doc.mime_type == "application/pdf":
        raise HTTPException(status_code=415, detail="The profile photo must be a JPEG or PNG image.")
    old = db.get(Document, user.profile_photo_document_id) if user.profile_photo_document_id else None
    user.profile_photo_document_id = doc.id
    if old:
        db.delete(old)
    audit(db, "PROFILE_PHOTO_UPDATED", user, "user", user.id, None, client_ip(request))
    return _profile_view(db, user)


@router.get("/passenger/eligibility")
def eligibility(user: User = Depends(traveller), db: Session = Depends(get_db, scope="function")):
    """The same server-side evaluation used when a ticket is issued; the app only displays it."""
    d = evaluate(db, user)
    iv = current_identity_verification(db, user.id)
    status, ver, sp = effective_student_status(db, user.id)
    profile = db.get(PassengerProfile, user.id)
    recent = db.scalars(select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.created_at.desc()).limit(5)).all()
    return {
        "eligibility": d.eligibility,
        "reason_code": d.reason_code,
        "message": REASON_TEXT.get(d.reason_code),
        "reasons": d.reasons,
        "category": passenger_category(db, user),
        "identity_status": "VERIFIED" if iv else (profile.identity_status.value if profile else "NOT_STARTED"),
        "identity_is_development": bool(iv and iv.is_development),
        "bus_pass_status": status,
        "bus_pass_rejection_reason": ver.rejection_reason if ver else None,
        "bus_pass_expiry_date": sp.expiry_date.isoformat() if sp and sp.expiry_date else None,
        "eligibility_suspended": bool(profile and profile.eligibility_suspended),
        "needs_face_verification": d.needs_face_verification,
        "recent_tickets": [{"id": t.id, "route": t.route, "status": t.status.value, "fare": t.fare, "eligibility": t.eligibility_type or "REGULAR_PAID",
                            "created_at": t.created_at.isoformat() if t.created_at else None} for t in recent],
    }
