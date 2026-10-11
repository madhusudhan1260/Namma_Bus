"""Help & feedback, account deletion (privacy), and admin exports."""

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..models import (
    Document,
    FaceVerificationAttempt,
    Feedback,
    IdentityVerification,
    OtpChallenge,
    PassengerProfile,
    RefreshToken,
    Role,
    StudentPass,
    StudentProfile,
    StudentVerification,
    Ticket,
    User,
)
from ..rbac import TRAVELLER_ROLES, require_roles
from ..security import client_ip, decode_access_token, rate_limiter, verify_password

router = APIRouter(tags=["Access: Help, Privacy & Exports"])


class FeedbackRequest(BaseModel):
    category: Literal["BUS_LOCATION", "TICKET", "PAYMENT", "VERIFICATION", "APP_PROBLEM", "COMPLAINT", "OTHER"] = "OTHER"
    message: str = Field(min_length=5, max_length=2000)
    screen: Optional[str] = Field(default=None, max_length=80)


@router.post("/feedback", status_code=201)
def submit_feedback(req: FeedbackRequest, request: Request, db: Session = Depends(get_db, scope="function")):
    """Anyone can report a problem; a signed-in user is linked when a valid token is sent."""
    rate_limiter.check(f"feedback:{client_ip(request)}", limit=5)
    user_id = None
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            user_id = decode_access_token(header.split(" ", 1)[1].strip()).get("sub")
        except HTTPException:
            user_id = None
    fb = Feedback(user_id=user_id, category=req.category, message=req.message.strip(), screen=req.screen)
    db.add(fb)
    db.flush()
    audit(db, "FEEDBACK_SUBMITTED", db.get(User, user_id) if user_id else None, "feedback", fb.id, {"category": req.category}, client_ip(request))
    return {"id": fb.id, "message": "Thank you. Your report has been sent to the Namma Bus team."}


@router.get("/admin/feedback")
def admin_feedback(admin: User = Depends(require_roles(Role.SUPER_ADMIN)), db: Session = Depends(get_db, scope="function")):
    rows = db.scalars(select(Feedback).order_by(Feedback.created_at.desc()).limit(200)).all()
    return {"feedback": [{"id": f.id, "category": f.category, "message": f.message, "screen": f.screen, "status": f.status,
                          "signed_in": bool(f.user_id), "created_at": f.created_at.isoformat()} for f in rows]}


def _csv_safe(value) -> str:
    """Prevent spreadsheet formula injection in exported cells."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@router.get("/admin/tickets.csv")
def admin_tickets_csv(request: Request, admin: User = Depends(require_roles(Role.SUPER_ADMIN)), db: Session = Depends(get_db, scope="function")):
    rows = db.scalars(select(Ticket).order_by(Ticket.created_at.desc()).limit(10000)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["reference", "created_at", "route", "from_stop", "to_stop", "passengers", "normal_fare", "fare", "ticket_type",
                "eligibility_type", "payment_status", "status", "used_at"])
    for t in rows:
        w.writerow([_csv_safe(v) for v in (t.reference, t.created_at.isoformat(), t.route, t.from_stop, t.to_stop, t.passenger_count,
                                           t.normal_fare, t.fare, t.ticket_type, t.eligibility_type, t.payment_status, t.status.value,
                                           t.used_at.isoformat() if t.used_at else "")])
    audit(db, "ADMIN_EXPORT_TICKETS", admin, "ticket", None, {"rows": len(rows)}, client_ip(request))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="namma-bus-tickets-{stamp}.csv"', "Cache-Control": "no-store"})


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    confirm: Literal["DELETE"]


@router.post("/me/delete")
def delete_my_account(req: DeleteAccountRequest, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)),
                      db: Session = Depends(get_db, scope="function")):
    """
    Passenger/student self-service deletion. Removes identity & face verification records, student
    documents (files and metadata), sessions and personal contact data. Tickets are kept, anonymised,
    as the transaction/audit record.
    """
    rate_limiter.check(f"delete:{user.id}", limit=5)
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    uid = user.id
    docs = db.scalars(select(Document).where(Document.owner_id == uid)).all()
    for d in docs:
        try:
            (Path(settings.upload_dir) / d.storage_reference).unlink(missing_ok=True)
        except OSError:
            pass
    db.execute(delete(FaceVerificationAttempt).where(FaceVerificationAttempt.user_id == uid))
    db.execute(delete(IdentityVerification).where(IdentityVerification.user_id == uid))
    db.execute(delete(StudentVerification).where(StudentVerification.student_id == uid))
    db.execute(delete(StudentPass).where(StudentPass.student_id == uid))
    db.execute(delete(Document).where(Document.owner_id == uid))
    db.execute(delete(StudentProfile).where(StudentProfile.user_id == uid))
    db.execute(delete(PassengerProfile).where(PassengerProfile.user_id == uid))
    db.execute(delete(OtpChallenge).where(OtpChallenge.user_id == uid))
    db.execute(delete(RefreshToken).where(RefreshToken.user_id == uid))
    user.name, user.email, user.phone, user.password_hash, user.totp_secret_encrypted = "Deleted account", None, None, None, None
    user.is_active = False
    audit(db, "ACCOUNT_DELETED", None, "user", uid, {"documents_removed": len(docs)}, client_ip(request))
    return {"message": "Your account and verification data have been deleted."}
