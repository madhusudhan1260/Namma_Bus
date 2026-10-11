"""Student pass submission, college verification portal and authorized document access."""

import secrets
import re
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..notifications import notify
from ..config import settings
from ..db import get_db
from ..documents import read_document, store_document
from ..eligibility import effective_student_status, today_ist
from ..models import (
    College,
    CollegeStatus,
    CollegeAdmin,
    Document,
    Role,
    StudentPass,
    StudentProfile,
    StudentStatus,
    StudentVerification,
    User,
)
from ..rbac import college_scope, get_current_user, require_roles
from ..security import client_ip, hash_password, password_policy_error, rate_limiter, sign_document_token, verify_document_token

router = APIRouter(tags=["Access: Students & Colleges"])


def _parse_date(value: Optional[str], field: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} must be a date in YYYY-MM-DD format.")


# ---------------------------------------------------------------------------
# Student portal
# ---------------------------------------------------------------------------

def approved_colleges(db: Session):
    return db.scalars(select(College).where(College.status == CollegeStatus.APPROVED, College.is_active.is_(True))
                      .order_by(College.name)).all()


@router.get("/colleges/approved")
@router.get("/colleges")
def list_colleges(db: Session = Depends(get_db, scope="function")):
    """Colleges offered to students: only those APPROVED by the Super Admin (never a hard-coded list)."""
    return {"colleges": [{"id": c.id, "code": c.code, "name": c.name, "city": c.city} for c in approved_colleges(db)]}


@router.post("/bus-pass", status_code=201)
@router.post("/students/pass/upload", status_code=201)
async def upload_student_pass(
    request: Request,
    student_name: str = Form(..., min_length=2, max_length=120),
    phone: str = Form(..., max_length=20),
    student_id_number: str = Form(..., min_length=1, max_length=64),
    pass_expiry_date: str = Form(...),
    college_id: Optional[str] = Form(default=None, max_length=32),
    college_code: Optional[str] = Form(default=None, max_length=32),
    email: Optional[str] = Form(default=None, max_length=254),
    college_email: Optional[str] = Form(default=None, max_length=254),
    course: Optional[str] = Form(default=None, max_length=80),
    branch: Optional[str] = Form(default=None, max_length=80),
    year: Optional[int] = Form(default=None, ge=1, le=8),
    semester: Optional[int] = Form(default=None, ge=1, le=16),
    date_of_birth: Optional[str] = Form(default=None),
    pass_number: Optional[str] = Form(default=None, max_length=64),
    pass_issue_date: Optional[str] = Form(default=None),
    bus_pass: UploadFile = File(...),
    college_id_card: Optional[UploadFile] = File(default=None),
    supporting_document: Optional[UploadFile] = File(default=None),
    user: User = Depends(require_roles(Role.STUDENT)),
    db: Session = Depends(get_db, scope="function"),
):
    """Bus pass for college verification. Uploading never makes anyone eligible by itself."""
    rate_limiter.check(f"student-upload:{user.id}", limit=5)
    college = None
    if college_id:
        college = db.get(College, college_id)
    elif college_code:
        college = db.scalars(select(College).where(College.code == college_code.strip().upper())).first()
    if not college or college.status != CollegeStatus.APPROVED or not college.is_active:
        raise HTTPException(status_code=404, detail="Choose a college from the approved list.")
    contact_email = (college_email or email or "").strip().lower()
    if contact_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact_email):
        raise HTTPException(status_code=422, detail="Enter a valid email.")
    if college_email and college.email_domain and not contact_email.endswith("@" + college.email_domain.lower()):
        raise HTTPException(status_code=422, detail=f"Use your official college email (@{college.email_domain}).")
    if not re.sub(r"\D", "", phone)[-10:] or len(re.sub(r"\D", "", phone)) < 10:
        raise HTTPException(status_code=422, detail="Enter a valid mobile number.")
    status, _, _ = effective_student_status(db, user.id)
    if status == StudentStatus.PENDING.value:
        raise HTTPException(status_code=409, detail="A verification request is already pending with your college.")
    issue = _parse_date(pass_issue_date, "Pass issue date")
    expiry = _parse_date(pass_expiry_date, "Pass validity date")
    if not expiry:
        raise HTTPException(status_code=422, detail="Enter the pass validity (expiry) date.")
    if issue and expiry and expiry < issue:
        raise HTTPException(status_code=422, detail="Pass expiry date must be after the issue date.")

    pass_doc = await store_document(db, user.id, "STUDENT_BUS_PASS", bus_pass)
    id_doc = await store_document(db, user.id, "COLLEGE_ID", college_id_card) if college_id_card and college_id_card.filename else None
    extra_doc = await store_document(db, user.id, "SUPPORTING", supporting_document) if supporting_document and supporting_document.filename else None

    profile = db.get(StudentProfile, user.id) or StudentProfile(user_id=user.id)
    profile.college_id = college.id
    profile.student_name = " ".join(student_name.split())
    profile.college_email = contact_email or None
    profile.student_id_number = student_id_number.strip()
    profile.course, profile.branch = (course or "").strip() or None, (branch or "").strip() or None
    profile.year, profile.semester = year, semester
    profile.phone = re.sub(r"\D", "", phone)[-10:]
    profile.date_of_birth = _parse_date(date_of_birth, "Date of birth")
    db.add(profile)
    if user.passenger_profile:
        user.passenger_profile.has_bus_pass_answer = True
    sp = StudentPass(student_id=user.id, pass_number=(pass_number or "").strip() or None, issue_date=issue,
                     expiry_date=expiry, document_id=pass_doc.id, status=StudentStatus.PENDING)
    db.add(sp)
    db.flush()
    ver = StudentVerification(student_id=user.id, college_id=college.id, student_pass_id=sp.id,
                              college_id_document_id=id_doc.id if id_doc else None, supporting_document_id=extra_doc.id if extra_doc else None,
                              status=StudentStatus.PENDING)
    db.add(ver)
    db.flush()
    audit(db, "STUDENT_PASS_SUBMITTED", user, "student_verification", ver.id, {"college": college.code}, client_ip(request))
    return {
        "verification_id": ver.id,
        "status": ver.status.value,
        "message": "Submitted. Your college will review your documents. Uploading documents does not by itself make you eligible.",
        "documents": [{"id": d.id, "type": d.document_type, "scan_status": d.scan_status} for d in (pass_doc, id_doc, extra_doc) if d],
    }


@router.get("/bus-pass/status")
@router.get("/students/pass/status")
def student_pass_status(user: User = Depends(require_roles(Role.STUDENT, Role.PASSENGER)), db: Session = Depends(get_db, scope="function")):
    status, ver, sp = effective_student_status(db, user.id)
    college = db.get(College, ver.college_id) if ver else None
    return {
        "status": status,
        "college": {"code": college.code, "name": college.name} if college else None,
        "submitted_at": ver.submitted_at.isoformat() if ver else None,
        "reviewed_at": ver.reviewed_at.isoformat() if ver and ver.reviewed_at else None,
        "rejection_reason": ver.rejection_reason if ver else None,
        "pass": {
            "pass_number": sp.pass_number,
            "issue_date": sp.issue_date.isoformat() if sp.issue_date else None,
            "expiry_date": sp.expiry_date.isoformat() if sp.expiry_date else None,
            "status": status,
        } if sp else None,
    }


# ---------------------------------------------------------------------------
# College portal (strictly scoped to the admin's own college)
# ---------------------------------------------------------------------------

def _scoped_verification(db: Session, admin: User, verification_id: str) -> StudentVerification:
    college_id = college_scope(admin, db)
    ver = db.get(StudentVerification, verification_id)
    if not ver or ver.college_id != college_id:
        # Same answer for "missing" and "other college" so existence is not leaked
        raise HTTPException(status_code=404, detail="Student verification not found.")
    return ver


def _verification_view(db: Session, ver: StudentVerification, viewer: User) -> dict:
    student = db.get(User, ver.student_id)
    profile = db.get(StudentProfile, ver.student_id)
    sp = db.get(StudentPass, ver.student_pass_id) if ver.student_pass_id else None
    college = db.get(College, ver.college_id)

    def doc(doc_id: Optional[str]):
        if not doc_id:
            return None
        d = db.get(Document, doc_id)
        return {
            "id": d.id, "type": d.document_type, "mime_type": d.mime_type, "size_bytes": d.size_bytes,
            "scan_status": d.scan_status, "uploaded_at": d.uploaded_at.isoformat(),
            "view_url": f"documents/{d.id}/content?token={sign_document_token(d.id, viewer.id, settings.document_url_ttl_seconds)}",
        } if d else None

    status = ver.status.value
    if ver.status == StudentStatus.APPROVED and sp and sp.expiry_date and sp.expiry_date < today_ist():
        status = StudentStatus.EXPIRED.value
    return {
        "id": ver.id,
        "status": status,
        "student_user_id": ver.student_id,
        "student_name": profile.student_name if profile else (student.name if student else None),
        "student_id_number": profile.student_id_number if profile else None,
        "course": profile.course if profile else None,
        "branch": profile.branch if profile else None,
        "year": profile.year if profile else None,
        "semester": profile.semester if profile else None,
        "college_email": profile.college_email if profile else None,
        "college": {"code": college.code, "name": college.name} if college else None,
        "pass_number": sp.pass_number if sp else None,
        "pass_issue_date": sp.issue_date.isoformat() if sp and sp.issue_date else None,
        "pass_expiry_date": sp.expiry_date.isoformat() if sp and sp.expiry_date else None,
        "bus_pass_document": doc(sp.document_id if sp else None),
        "college_id_document": doc(ver.college_id_document_id),
        "supporting_document": doc(ver.supporting_document_id),
        "submitted_at": ver.submitted_at.isoformat(),
        "reviewed_at": ver.reviewed_at.isoformat() if ver.reviewed_at else None,
        "rejection_reason": ver.rejection_reason,
    }


@router.get("/college/dashboard")
def college_dashboard(admin: User = Depends(require_roles(Role.COLLEGE_ADMIN)), db: Session = Depends(get_db, scope="function")):
    college_id = college_scope(admin, db)
    college = db.get(College, college_id)
    counts = dict(db.execute(select(StudentVerification.status, func.count()).where(StudentVerification.college_id == college_id)
                             .group_by(StudentVerification.status)).all())
    approved = db.scalars(select(StudentVerification).where(StudentVerification.college_id == college_id,
                                                            StudentVerification.status == StudentStatus.APPROVED)).all()
    today = today_ist()
    active = expired = 0
    for v in approved:
        sp = db.get(StudentPass, v.student_pass_id) if v.student_pass_id else None
        if sp and sp.expiry_date and sp.expiry_date >= today:
            active += 1
        else:
            expired += 1
    students = db.scalar(select(func.count(func.distinct(StudentVerification.student_id))).where(StudentVerification.college_id == college_id))
    return {
        "college": {"code": college.code, "name": college.name},
        "students": students or 0,
        "pending": counts.get(StudentStatus.PENDING, 0),
        "approved": counts.get(StudentStatus.APPROVED, 0),
        "rejected": counts.get(StudentStatus.REJECTED, 0),
        "active_passes": active,
        "expired_passes": expired,
    }


@router.get("/college/requests")
@router.get("/college/students")
def college_students(status: Optional[str] = Query(default=None), q: Optional[str] = Query(default=None, max_length=80),
                     admin: User = Depends(require_roles(Role.COLLEGE_ADMIN)), db: Session = Depends(get_db, scope="function")):
    college_id = college_scope(admin, db)
    stmt = select(StudentVerification).where(StudentVerification.college_id == college_id).order_by(StudentVerification.submitted_at.desc())
    if status and status.upper() in StudentStatus.__members__ and status.upper() != "EXPIRED":
        stmt = stmt.where(StudentVerification.status == StudentStatus(status.upper()))
    rows = [_verification_view(db, v, admin) for v in db.scalars(stmt).all()]
    if status and status.upper() == "EXPIRED":
        rows = [r for r in rows if r["status"] == "EXPIRED"]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if any(needle in str(r.get(k) or "").lower() for k in ("student_name", "student_id_number", "pass_number", "college_email"))]
    return {"count": len(rows), "students": rows}


@router.get("/college/students/pending")
def college_pending(admin: User = Depends(require_roles(Role.COLLEGE_ADMIN)), db: Session = Depends(get_db, scope="function")):
    return college_students(status="PENDING", q=None, admin=admin, db=db)


@router.get("/college/students/{verification_id}")
def college_student_detail(verification_id: str, admin: User = Depends(require_roles(Role.COLLEGE_ADMIN)), db: Session = Depends(get_db, scope="function")):
    return _verification_view(db, _scoped_verification(db, admin, verification_id), admin)


class ApproveRequest(BaseModel):
    pass_expiry_date: Optional[str] = None  # college may confirm/correct validity


class RejectRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/college/requests/{verification_id}/approve")
@router.post("/college/students/{verification_id}/approve")
def college_approve(verification_id: str, req: ApproveRequest, request: Request,
                    admin: User = Depends(require_roles(Role.COLLEGE_ADMIN)), db: Session = Depends(get_db, scope="function")):
    ver = _scoped_verification(db, admin, verification_id)
    if ver.status != StudentStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Verification is already {ver.status.value}.")
    sp = db.get(StudentPass, ver.student_pass_id) if ver.student_pass_id else None
    if not sp:
        raise HTTPException(status_code=409, detail="No bus pass attached to this request.")
    if req.pass_expiry_date:
        sp.expiry_date = _parse_date(req.pass_expiry_date, "Pass expiry date")
    if not sp.expiry_date:
        raise HTTPException(status_code=422, detail="Confirm the bus pass expiry date before approving.")
    now = datetime.now(timezone.utc)
    ver.status = sp.status = StudentStatus.APPROVED
    ver.reviewed_by, ver.reviewed_at, ver.rejection_reason = admin.id, now, None
    for doc_id in (sp.document_id, ver.college_id_document_id, ver.supporting_document_id):
        if doc_id:
            db.get(Document, doc_id).verification_status = StudentStatus.APPROVED
    audit(db, "STUDENT_APPROVED", admin, "student_verification", ver.id,
          {"student": ver.student_id, "pass_expiry": sp.expiry_date.isoformat()}, client_ip(request))
    notify(db, ver.student_id, "PASS_APPROVED", "Bus pass approved",
           f"Your college approved your bus pass. Free travel is available until {sp.expiry_date.isoformat()}.",
           {"expiry_date": sp.expiry_date.isoformat()}, f"pass-approved-{ver.id}")
    return _verification_view(db, ver, admin)


@router.post("/college/requests/{verification_id}/reject")
@router.post("/college/students/{verification_id}/reject")
def college_reject(verification_id: str, req: RejectRequest, request: Request,
                   admin: User = Depends(require_roles(Role.COLLEGE_ADMIN)), db: Session = Depends(get_db, scope="function")):
    ver = _scoped_verification(db, admin, verification_id)
    if ver.status != StudentStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Verification is already {ver.status.value}.")
    now = datetime.now(timezone.utc)
    ver.status = StudentStatus.REJECTED
    ver.reviewed_by, ver.reviewed_at, ver.rejection_reason = admin.id, now, req.reason.strip()
    sp = db.get(StudentPass, ver.student_pass_id) if ver.student_pass_id else None
    if sp:
        sp.status = StudentStatus.REJECTED
    for doc_id in ((sp.document_id if sp else None), ver.college_id_document_id, ver.supporting_document_id):
        if doc_id:
            db.get(Document, doc_id).verification_status = StudentStatus.REJECTED
    audit(db, "STUDENT_REJECTED", admin, "student_verification", ver.id, {"student": ver.student_id, "reason": req.reason.strip()},
          client_ip(request))
    notify(db, ver.student_id, "PASS_REJECTED", "Bus pass rejected", f"Your college rejected your bus pass: {req.reason.strip()}",
           {"reason": req.reason.strip()}, f"pass-rejected-{ver.id}")
    return _verification_view(db, ver, admin)


class RevokeRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/college/requests/{verification_id}/revoke")
@router.post("/college/students/{verification_id}/revoke")
def college_revoke(verification_id: str, req: RevokeRequest, request: Request,
                   admin: User = Depends(require_roles(Role.COLLEGE_ADMIN)), db: Session = Depends(get_db, scope="function")):
    """Withdraw an approved pass (e.g. student left the college). Free tickets stop immediately."""
    ver = _scoped_verification(db, admin, verification_id)
    if ver.status != StudentStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Only approved passes can be revoked.")
    now = datetime.now(timezone.utc)
    ver.status = StudentStatus.REVOKED
    ver.reviewed_by, ver.reviewed_at, ver.rejection_reason = admin.id, now, req.reason.strip()
    sp = db.get(StudentPass, ver.student_pass_id) if ver.student_pass_id else None
    if sp:
        sp.status = StudentStatus.REVOKED
    audit(db, "STUDENT_PASS_REVOKED", admin, "student_verification", ver.id, {"student": ver.student_id, "reason": req.reason.strip()},
          client_ip(request))
    notify(db, ver.student_id, "PASS_REVOKED", "Bus pass withdrawn", f"Your college withdrew your bus pass: {req.reason.strip()}",
           {"reason": req.reason.strip()}, f"pass-revoked-{ver.id}")
    return _verification_view(db, ver, admin)


# ---------------------------------------------------------------------------
# College self-registration (reviewed by the Super Admin before going live)
# ---------------------------------------------------------------------------

def _college_code(db: Session, name: str) -> str:
    letters = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in {"of", "and", "the"})[:6].upper() or "COL"
    for _ in range(20):
        code = f"{letters}-{secrets.randbelow(9000) + 1000}"
        if not db.scalars(select(College).where(College.code == code)).first():
            return code
    raise HTTPException(status_code=500, detail="Could not allocate a college ID.")


@router.post("/colleges/register", status_code=201)
async def college_register(
    request: Request,
    college_name: str = Form(..., min_length=3, max_length=200),
    affiliation: str = Form(..., min_length=2, max_length=200),
    address: str = Form(..., min_length=5, max_length=500),
    city: str = Form(..., min_length=2, max_length=80),
    state: str = Form(..., min_length=2, max_length=80),
    official_email: str = Form(..., max_length=254),
    phone: str = Form(..., max_length=20),
    officer_name: str = Form(..., min_length=2, max_length=120),
    officer_designation: str = Form(..., min_length=2, max_length=120),
    password: str = Form(..., min_length=8, max_length=128),
    website: Optional[str] = Form(default=None, max_length=200),
    document: UploadFile = File(...),
    db: Session = Depends(get_db, scope="function"),
):
    """Public: a college registers with an authorized officer. Starts as PENDING admin approval and is not
    offered to students until a Super Admin approves it."""
    rate_limiter.check(f"college-register:{client_ip(request)}", limit=5)
    email = official_email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid official email.")
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        raise HTTPException(status_code=422, detail="Enter a valid phone number.")
    err = password_policy_error(password)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    if website and not re.fullmatch(r"(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?", website.strip(), re.I):
        raise HTTPException(status_code=422, detail="Enter a valid website address.")
    officer = User(name=" ".join(officer_name.split()), email=email, phone=None, password_hash=hash_password(password), role=Role.COLLEGE_ADMIN)
    db.add(officer)
    db.flush()
    doc = await store_document(db, officer.id, "COLLEGE_REGISTRATION", document)
    college = College(code=_college_code(db, college_name), name=" ".join(college_name.split()), email_domain=email.split("@")[1],
                      status=CollegeStatus.PENDING, affiliation=affiliation.strip(), address=address.strip(), city=city.strip(),
                      state=state.strip(), official_email=email, phone=digits[-10:], website=(website or "").strip() or None,
                      officer_name=officer.name, officer_designation=officer_designation.strip(), document_id=doc.id)
    db.add(college)
    db.flush()
    db.add(CollegeAdmin(user_id=officer.id, college_id=college.id))
    audit(db, "COLLEGE_REGISTERED", officer, "college", college.id, {"code": college.code}, client_ip(request))
    return {"college_id": college.code, "status": college.status.value,
            "message": "Registration received. Your college will be available to students after Super Admin approval."}


# ---------------------------------------------------------------------------
# Documents: authorized viewing only (owner, the student's college admin, super admin)
# ---------------------------------------------------------------------------

def _can_view(db: Session, viewer: User, doc: Document) -> bool:
    if viewer.role == Role.SUPER_ADMIN or viewer.id == doc.owner_id:
        return True
    if viewer.role == Role.COLLEGE_ADMIN and doc.document_type in ("STUDENT_BUS_PASS", "COLLEGE_ID", "SUPPORTING"):
        binding = db.get(CollegeAdmin, viewer.id)
        ver = db.scalars(select(StudentVerification).where(StudentVerification.student_id == doc.owner_id)
                         .order_by(StudentVerification.submitted_at.desc())).first()
        return bool(binding and ver and ver.college_id == binding.college_id)
    return False


@router.get("/documents/{document_id}/url")
def document_url(document_id: str, viewer: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    doc = db.get(Document, document_id)
    if not doc or not _can_view(db, viewer, doc):
        raise HTTPException(status_code=404, detail="Document not found.")
    token = sign_document_token(doc.id, viewer.id, settings.document_url_ttl_seconds)
    return {"url": f"documents/{doc.id}/content?token={token}", "expires_in": settings.document_url_ttl_seconds}


@router.get("/documents/{document_id}/content")
def document_content(document_id: str, token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    viewer_id = verify_document_token(token, document_id)
    doc = db.get(Document, document_id)
    viewer = db.get(User, viewer_id) if viewer_id else None
    # Re-check authorization at access time (a revoked admin cannot use an earlier link)
    if not doc or not viewer or not viewer.is_active or not _can_view(db, viewer, doc):
        raise HTTPException(status_code=404, detail="Document not found or link expired.")
    audit(db, "DOCUMENT_VIEWED", viewer, "document", doc.id, {"type": doc.document_type}, client_ip(request))
    return Response(
        content=read_document(doc),
        media_type=doc.mime_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
    )
