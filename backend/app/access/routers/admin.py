"""Super Admin portal: oversight, reports, audit logs, and staff/college management."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..eligibility import IST
from ..models import (
    AuditLog,
    Bus,
    BusStatus,
    College,
    CollegeStatus,
    Document,
    FaceVerificationAttempt,
    Gender,
    PassengerProfile,
    StudentPass,
    Trip,
    VerificationStatus,
    CollegeAdmin,
    Conductor,
    IdentityVerification,
    Role,
    StudentStatus,
    StudentVerification,
    Ticket,
    TicketStatus,
    TicketVerification,
    User,
)
from ..rbac import require_roles
from ..security import client_ip, encrypt_text, hash_password, new_totp_secret, password_policy_error, sign_document_token
from ..config import settings
from .tickets import ticket_view
from ..trips import active_trips, public_trip_view, release_from_trip
from .conductor import bus_realtime

router = APIRouter(tags=["Access: Super Admin"])
admin_only = require_roles(Role.SUPER_ADMIN)


def _user_view(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "phone": f"******{u.phone[-4:]}" if u.phone else None,
            "role": u.role.value, "is_active": u.is_active, "two_factor": bool(u.totp_secret_encrypted),
            "created_at": u.created_at.isoformat()}


def _today_stats(db: Session) -> dict:
    """Today (IST) from issued tickets: passengers, tickets, paid/free and revenue; plus running trips."""
    start_ist = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    counted = (TicketStatus.ISSUED, TicketStatus.USED)
    rows = db.execute(select(Ticket.ticket_type, func.count(Ticket.id), func.coalesce(func.sum(Ticket.passenger_count), 0),
                             func.coalesce(func.sum(Ticket.fare), 0))
                      .where(Ticket.status.in_(counted), Ticket.issued_at >= start_ist).group_by(Ticket.ticket_type)).all()
    by = {r[0]: r for r in rows}
    paid, free = by.get("PAID"), by.get("ELIGIBLE_FREE")
    return {
        "active_trips": db.scalar(select(func.count()).select_from(Trip).where(Trip.status == "ACTIVE")) or 0,
        "passengers_today": sum(int(r[2]) for r in rows),
        "tickets_today": sum(int(r[1]) for r in rows),
        "paid_tickets_today": int(paid[1]) if paid else 0,
        "free_tickets_today": int(free[1]) if free else 0,
        "revenue_today": int(paid[3]) if paid else 0,
    }


async def _transport_snapshot() -> dict:
    """Live-bus/network figures from the existing Namma Bus → NammaRoute integration (best effort)."""
    try:
        from ...services.nammaroute_client import nammaroute_client

        status = await nammaroute_client.get("/data/stats", ttl=60)
        vehicles = await nammaroute_client.get("/realtime/vehicles", ttl=15)
        data = status.get("data") or status
        return {
            "available": True,
            "routes": data.get("routes") or data.get("routeCount"),
            "stops": data.get("stops") or data.get("stopCount"),
            "live_buses": vehicles.get("vehicleCount", 0),
            "realtime_status": vehicles.get("status"),
        }
    except Exception:
        return {"available": False, "message": "Transport network service unavailable."}


@router.get("/admin/dashboard")
async def admin_dashboard(admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    users_by_role = {r.value: c for r, c in db.execute(select(User.role, func.count()).group_by(User.role)).all()}
    students = {s.value: c for s, c in db.execute(select(StudentVerification.status, func.count()).group_by(StudentVerification.status)).all()}
    identity = {s.value: c for s, c in db.execute(select(IdentityVerification.verification_status, func.count())
                                                  .group_by(IdentityVerification.verification_status)).all()}
    tickets_by_type = dict(db.execute(select(Ticket.ticket_type, func.count()).group_by(Ticket.ticket_type)).all())
    tickets_by_status = {s.value: c for s, c in db.execute(select(Ticket.status, func.count()).group_by(Ticket.status)).all()}
    invalid_scans = db.scalar(select(func.count()).select_from(TicketVerification).where(TicketVerification.result != "VALID")) or 0
    return {
        "users": {"passengers": users_by_role.get("PASSENGER", 0), "students": users_by_role.get("STUDENT", 0),
                  "conductors": users_by_role.get("CONDUCTOR", 0), "college_admins": users_by_role.get("COLLEGE_ADMIN", 0),
                  "super_admins": users_by_role.get("SUPER_ADMIN", 0)},
        "verification": {"students_pending": students.get("PENDING", 0), "students_approved": students.get("APPROVED", 0),
                         "students_rejected": students.get("REJECTED", 0), "identity": identity},
        "tickets": {"total": sum(tickets_by_type.values()), "paid": tickets_by_type.get("PAID", 0),
                    "eligible_free": tickets_by_type.get("ELIGIBLE_FREE", 0), "by_status": tickets_by_status,
                    "cancelled": tickets_by_status.get("CANCELLED", 0), "invalid_scans": invalid_scans},
        "colleges": db.scalar(select(func.count()).select_from(College)) or 0,
        "stats": _spec_stats(db),
        "transport": await _transport_snapshot(),
    }


def _spec_stats(db: Session) -> dict:
    """The Super Admin dashboard figures. All counted from stored records; nothing estimated."""
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    genders = {g.value: c for g, c in db.execute(select(PassengerProfile.gender, func.count()).group_by(PassengerProfile.gender)).all()}
    colleges = {s.value: c for s, c in db.execute(select(College.status, func.count()).group_by(College.status)).all()}
    tickets = dict(db.execute(select(Ticket.ticket_type, func.count()).group_by(Ticket.ticket_type)).all())
    from ..db import engine
    from sqlalchemy import text
    from ..providers.biometric import get_biometric_provider
    from ..providers.identity import get_identity_provider

    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    idp, bio = get_identity_provider(), get_biometric_provider()
    return {
        "male_passengers": genders.get("MALE", 0),
        "female_passengers": genders.get("FEMALE", 0),
        "verified_identities": count(select(func.count(func.distinct(IdentityVerification.user_id)))
                                     .where(IdentityVerification.verification_status == VerificationStatus.VERIFIED)),
        "bus_pass_students": count(select(func.count()).select_from(User).where(User.role == Role.STUDENT)),
        "pending_colleges": colleges.get("PENDING", 0),
        "approved_colleges": colleges.get("APPROVED", 0),
        "suspended_colleges": colleges.get("SUSPENDED", 0),
        "pending_student_verifications": count(select(func.count()).select_from(StudentVerification)
                                               .where(StudentVerification.status == StudentStatus.PENDING)),
        "active_conductors": count(select(func.count()).select_from(Conductor).join(User, User.id == Conductor.user_id)
                                   .where(User.is_active.is_(True))),
        "active_buses": count(select(func.count()).select_from(Bus).where(Bus.operational_status == BusStatus.IN_SERVICE)),
        "tickets_free": tickets.get("ELIGIBLE_FREE", 0),
        "tickets_paid": tickets.get("PAID", 0),
        **_today_stats(db),
        "failed_verification_attempts": count(select(func.count()).select_from(FaceVerificationAttempt).where(FaceVerificationAttempt.result != "MATCH"))
        + count(select(func.count()).select_from(IdentityVerification).where(IdentityVerification.verification_status == VerificationStatus.FAILED)),
        "system_health": {"database": "OK" if db_ok else "UNAVAILABLE",
                          "identity_provider": idp.name, "identity_available": idp.available(), "identity_is_development": idp.is_development,
                          "face_provider": bio.name, "face_available": bio.available(), "face_is_development": bio.is_development},
    }


@router.get("/admin/users")
def admin_users(role: Optional[str] = None, q: Optional[str] = Query(default=None, max_length=80), limit: int = Query(default=100, le=500),
                admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    if role and role.upper() in Role.__members__:
        stmt = stmt.where(User.role == Role(role.upper()))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like)))
    return {"users": [_user_view(u) for u in db.scalars(stmt).all()]}


@router.get("/admin/verifications")
def admin_verifications(status: Optional[str] = None, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    stmt = select(StudentVerification).order_by(StudentVerification.submitted_at.desc()).limit(200)
    if status and status.upper() in StudentStatus.__members__:
        stmt = stmt.where(StudentVerification.status == StudentStatus(status.upper()))
    rows = []
    for v in db.scalars(stmt).all():
        college = db.get(College, v.college_id)
        student = db.get(User, v.student_id)
        rows.append({"id": v.id, "student": student.name if student else None, "college": college.name if college else None,
                     "status": v.status.value, "submitted_at": v.submitted_at.isoformat(),
                     "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None, "rejection_reason": v.rejection_reason})
    identity = [{"user_id": iv.user_id, "provider": iv.provider, "status": iv.verification_status.value, "development": iv.is_development,
                 "verified_at": iv.verified_at.isoformat() if iv.verified_at else None}
                for iv in db.scalars(select(IdentityVerification).order_by(IdentityVerification.created_at.desc()).limit(200)).all()]
    return {"student_verifications": rows, "identity_verifications": identity}


@router.get("/admin/tickets")
def admin_tickets(kind: Optional[str] = Query(default=None, description="PAID | ELIGIBLE_FREE | CANCELLED | USED | ISSUED"),
                  admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    stmt = select(Ticket).order_by(Ticket.created_at.desc()).limit(200)
    if kind in ("PAID", "ELIGIBLE_FREE"):
        stmt = stmt.where(Ticket.ticket_type == kind)
    elif kind and kind in TicketStatus.__members__:
        stmt = stmt.where(Ticket.status == TicketStatus(kind))
    invalid = db.scalars(select(TicketVerification).where(TicketVerification.result != "VALID")
                         .order_by(TicketVerification.created_at.desc()).limit(100)).all()
    return {"tickets": [ticket_view(t, include_qr=False) for t in db.scalars(stmt).all()],
            "invalid_scans": [{"result": v.result, "detail": v.detail, "route": v.route, "at": v.created_at.isoformat()} for v in invalid]}


@router.get("/admin/audit-logs")
def admin_audit_logs(action: Optional[str] = Query(default=None, max_length=60), limit: int = Query(default=200, le=1000),
                     admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action.upper())
    return {"logs": [{"at": a.created_at.isoformat(), "action": a.action, "actor_id": a.actor_id, "actor_role": a.actor_role,
                      "target_type": a.target_type, "target_id": a.target_id, "details": a.details, "ip": a.ip_address}
                     for a in db.scalars(stmt).all()]}


@router.get("/admin/reports")
def admin_reports(days: int = Query(default=7, ge=1, le=90), admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    tickets = db.scalars(select(Ticket).where(Ticket.created_at >= since)).all()
    daily = {}
    for t in tickets:
        day = t.created_at.astimezone(IST).date().isoformat()
        d = daily.setdefault(day, {"date": day, "total": 0, "paid": 0, "eligible_free": 0, "student_pass": 0, "female_verified": 0})
        d["total"] += 1
        d["paid" if t.ticket_type == "PAID" else "eligible_free"] += 1
        if t.eligibility_type in ("STUDENT_FREE", "STUDENT_PASS"):
            d["student_pass"] += 1
        if t.eligibility_type in ("FEMALE_IDENTITY_VERIFIED_FREE", "FEMALE_VERIFIED_IDENTITY"):
            d["female_verified"] += 1
    reviews = db.scalars(select(StudentVerification).where(StudentVerification.submitted_at >= since)).all()
    return {
        "days": days,
        "daily_tickets": sorted(daily.values(), key=lambda x: x["date"]),
        "verification_stats": {
            "student_submissions": len(reviews),
            "approved": sum(1 for r in reviews if r.status == StudentStatus.APPROVED),
            "rejected": sum(1 for r in reviews if r.status == StudentStatus.REJECTED),
            "pending": sum(1 for r in reviews if r.status == StudentStatus.PENDING),
        },
    }


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------

class CollegeCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=3, max_length=200)
    email_domain: Optional[str] = Field(default=None, max_length=120)


class StaffCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=128)


class CollegeAdminCreate(StaffCreate):
    college_code: str = Field(min_length=2, max_length=32)


class ConductorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    employee_id: str = Field(min_length=2, max_length=32)
    bus_id: Optional[str] = Field(default=None, max_length=32)
    assigned_bus: Optional[str] = Field(default=None, max_length=20)
    assigned_route: Optional[str] = Field(default=None, max_length=40)


class ConductorAssign(BaseModel):
    bus_id: Optional[str] = Field(default=None, max_length=32)
    assigned_bus: Optional[str] = Field(default=None, max_length=20)
    assigned_route: Optional[str] = Field(default=None, max_length=40)
    current_trip_id: Optional[str] = Field(default=None, max_length=64)


def _college_view(db: Session, c: College, viewer: Optional[User] = None, detail: bool = False) -> dict:
    admins = db.scalars(select(CollegeAdmin).where(CollegeAdmin.college_id == c.id)).all()
    activity = db.scalar(select(func.count()).select_from(StudentVerification).where(StudentVerification.college_id == c.id)) or 0
    body = {"id": c.id, "code": c.code, "name": c.name, "email_domain": c.email_domain, "is_active": c.is_active,
            "status": c.status.value, "city": c.city, "state": c.state, "affiliation": c.affiliation,
            "officer_name": c.officer_name, "officer_designation": c.officer_designation, "official_email": c.official_email,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None, "review_reason": c.review_reason,
            "administrators": [_user_view(u) for u in (db.get(User, a.user_id) for a in admins) if u], "verification_requests": activity}
    if detail:
        body.update({"address": c.address, "phone": c.phone, "website": c.website})
        doc = db.get(Document, c.document_id) if c.document_id else None
        body["document"] = ({"id": doc.id, "mime_type": doc.mime_type, "scan_status": doc.scan_status,
                             "view_url": f"documents/{doc.id}/content?token={sign_document_token(doc.id, viewer.id, settings.document_url_ttl_seconds)}"}
                            if doc and viewer else None)
        body["recent_activity"] = [{"at": a.created_at.isoformat(), "action": a.action, "actor_role": a.actor_role, "result": a.result}
                                   for a in db.scalars(select(AuditLog).where(AuditLog.target_id == c.id)
                                                       .order_by(AuditLog.created_at.desc()).limit(30)).all()]
    return body


@router.get("/admin/colleges")
def admin_colleges(status: Optional[str] = Query(default=None, description="PENDING | APPROVED | REJECTED | SUSPENDED"),
                   q: Optional[str] = Query(default=None, max_length=80), admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    stmt = select(College).order_by(College.created_at.desc())
    if status and status.upper() in CollegeStatus.__members__:
        stmt = stmt.where(College.status == CollegeStatus(status.upper()))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(College.name).like(like), func.lower(College.code).like(like), func.lower(College.city).like(like)))
    return {"colleges": [_college_view(db, c) for c in db.scalars(stmt).all()]}


@router.get("/admin/colleges/{college_id}")
def admin_college_detail(college_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    c = db.get(College, college_id)
    if not c:
        raise HTTPException(status_code=404, detail="College not found.")
    return _college_view(db, c, admin, detail=True)


class ReasonBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


# action → (allowed current statuses, new status, reason required)
_COLLEGE_TRANSITIONS = {
    "approve": ({CollegeStatus.PENDING, CollegeStatus.REJECTED}, CollegeStatus.APPROVED, False),
    "reject": ({CollegeStatus.PENDING}, CollegeStatus.REJECTED, True),
    "suspend": ({CollegeStatus.APPROVED}, CollegeStatus.SUSPENDED, True),
    "reactivate": ({CollegeStatus.SUSPENDED}, CollegeStatus.APPROVED, False),
}


@router.post("/admin/colleges/{college_id}/{action}")
def admin_college_review(college_id: str, action: str, request: Request, req: Optional[ReasonBody] = None,
                         admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    if action not in _COLLEGE_TRANSITIONS:
        raise HTTPException(status_code=404, detail="Unknown action.")
    allowed, new_status, needs_reason = _COLLEGE_TRANSITIONS[action]
    c = db.get(College, college_id)
    if not c:
        raise HTTPException(status_code=404, detail="College not found.")
    if c.status not in allowed:
        raise HTTPException(status_code=409, detail=f"A {c.status.value.lower()} college cannot be {action}d.")
    reason = (req.reason or "").strip() if req else ""
    if needs_reason and len(reason) < 5:
        raise HTTPException(status_code=422, detail="Please give a reason (at least 5 characters).")
    c.status = new_status
    c.is_active = new_status == CollegeStatus.APPROVED
    c.reviewed_by, c.reviewed_at, c.review_reason = admin.id, datetime.now(timezone.utc), reason or None
    audit(db, f"COLLEGE_{action.upper()}D", admin, "college", c.id, {"code": c.code, "reason": reason or None}, client_ip(request),
          user_agent=request.headers.get("user-agent"))
    return _college_view(db, c, admin, detail=True)


@router.post("/admin/colleges", status_code=201)
def admin_create_college(req: CollegeCreate, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    code = req.code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9-]{2,32}", code):
        raise HTTPException(status_code=422, detail="College code may contain letters, digits and hyphens.")
    if db.scalars(select(College).where(College.code == code)).first():
        raise HTTPException(status_code=409, detail="College code already exists.")
    c = College(code=code, name=req.name.strip(), email_domain=(req.email_domain or "").strip().lower() or None)
    db.add(c)
    db.flush()
    audit(db, "COLLEGE_CREATED", admin, "college", c.id, {"code": code}, client_ip(request))
    return {"id": c.id, "code": c.code, "name": c.name}


def _create_staff(db: Session, req, role: Role) -> User:
    err = password_policy_error(req.password)
    if err:
        raise HTTPException(status_code=422, detail=err)
    email = req.email.lower() if req.email else None
    phone = re.sub(r"\D", "", req.phone or "")[-10:] or None
    clauses = [c for c in ((User.email == email) if email else None, (User.phone == phone) if phone else None) if c is not None]
    if clauses and db.scalars(select(User).where(or_(*clauses))).first():
        raise HTTPException(status_code=409, detail="A user with this email or phone already exists.")
    u = User(name=req.name.strip(), email=email, phone=phone, password_hash=hash_password(req.password), role=role)
    db.add(u)
    db.flush()
    return u


@router.post("/admin/college-admins", status_code=201)
def admin_create_college_admin(req: CollegeAdminCreate, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    college = db.scalars(select(College).where(College.code == req.college_code.strip().upper())).first()
    if not college:
        raise HTTPException(status_code=404, detail="College not found.")
    u = _create_staff(db, req, Role.COLLEGE_ADMIN)
    db.add(CollegeAdmin(user_id=u.id, college_id=college.id))
    audit(db, "COLLEGE_ADMIN_CREATED", admin, "user", u.id, {"college": college.code}, client_ip(request))
    return _user_view(u)


@router.post("/admin/conductors", status_code=201)
def admin_create_conductor(req: ConductorCreate, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    emp = req.employee_id.strip().upper()
    if db.scalars(select(Conductor).where(Conductor.employee_id == emp)).first():
        raise HTTPException(status_code=409, detail="Employee ID already exists.")
    bus = _get_bus(db, req.bus_id) if req.bus_id else None
    u = _create_staff(db, req, Role.CONDUCTOR)
    c = Conductor(user_id=u.id, employee_id=emp, assigned_bus=(req.assigned_bus or "").upper() or None,
                  assigned_route=(req.assigned_route or "").strip() or None)
    db.add(c)
    if bus:
        _bind_bus(db, c, bus)
    audit(db, "CONDUCTOR_CREATED", admin, "user", u.id, {"employee_id": emp, "bus": bus.fleet_label if bus else None}, client_ip(request))
    return {**_user_view(u), "employee_id": emp}


def _get_bus(db: Session, bus_id: str) -> Bus:
    bus = db.get(Bus, bus_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found.")
    return bus


def _bind_bus(db: Session, c: Conductor, bus: Optional[Bus]) -> None:
    """One conductor per bus: assigning a bus moves it away from any other conductor."""
    if bus:
        for other in db.scalars(select(Conductor).where(Conductor.bus_id == bus.id, Conductor.user_id != c.user_id)).all():
            other.bus_id = None
    c.bus_id = bus.id if bus else None
    c.assigned_bus = bus.registration_number if bus else None
    c.assigned_route = bus.route if bus else c.assigned_route


@router.patch("/admin/conductors/{user_id}")
def admin_assign_conductor(user_id: str, req: ConductorAssign, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    c = db.get(Conductor, user_id)
    if not c:
        raise HTTPException(status_code=404, detail="Conductor not found.")
    if req.bus_id is not None:
        _bind_bus(db, c, _get_bus(db, req.bus_id) if req.bus_id else None)
    for f in ("assigned_bus", "assigned_route", "current_trip_id"):
        v = getattr(req, f)
        if v is not None:
            setattr(c, f, v.strip() or None)
    audit(db, "CONDUCTOR_ASSIGNED", admin, "user", user_id, {"bus": c.assigned_bus, "route": c.assigned_route}, client_ip(request))
    return {"employee_id": c.employee_id, "assigned_bus": c.assigned_bus, "assigned_route": c.assigned_route, "current_trip_id": c.current_trip_id}


@router.post("/admin/users/{user_id}/two-factor")
def admin_enable_2fa(user_id: str, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    """Enable TOTP for a staff account. The secret is returned once, to be added to an authenticator app."""
    u = db.get(User, user_id)
    if not u or u.role not in (Role.CONDUCTOR, Role.COLLEGE_ADMIN, Role.SUPER_ADMIN):
        raise HTTPException(status_code=404, detail="Staff user not found.")
    secret = new_totp_secret()
    u.totp_secret_encrypted = encrypt_text(secret)
    audit(db, "TWO_FACTOR_ENABLED", admin, "user", u.id, None, client_ip(request))
    return {"totp_secret": secret, "otpauth_uri": f"otpauth://totp/NammaBus:{u.email}?secret={secret}&issuer=NammaBus"}


@router.post("/admin/users/{user_id}/deactivate")
def admin_deactivate(user_id: str, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    u.is_active = False
    audit(db, "USER_DEACTIVATED", admin, "user", u.id, None, client_ip(request))
    return _user_view(u)


@router.post("/admin/users/{user_id}/activate")
def admin_activate(user_id: str, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    u.is_active, u.failed_logins, u.locked_until = True, 0, None
    audit(db, "USER_ACTIVATED", admin, "user", u.id, None, client_ip(request))
    return _user_view(u)


# ---------------------------------------------------------------------------
# Students (bus-pass holders)
# ---------------------------------------------------------------------------

def _student_row(db: Session, u: User) -> dict:
    from ..eligibility import effective_student_status

    status, ver, sp = effective_student_status(db, u.id)
    college = db.get(College, ver.college_id) if ver else None
    profile = db.get(PassengerProfile, u.id)
    return {**_user_view(u), "bus_pass_status": status, "college": college.name if college else None,
            "college_status": college.status.value if college else None, "verification_id": ver.id if ver else None,
            "pass_number": sp.pass_number if sp else None, "pass_expiry_date": sp.expiry_date.isoformat() if sp and sp.expiry_date else None,
            "eligibility_suspended": bool(profile and profile.eligibility_suspended),
            "eligibility_suspended_reason": profile.eligibility_suspended_reason if profile else None}


@router.get("/admin/students")
def admin_students(q: Optional[str] = Query(default=None, max_length=80), status: Optional[str] = None,
                   admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    stmt = select(User).where(User.role == Role.STUDENT).order_by(User.created_at.desc()).limit(300)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like)))
    rows = [_student_row(db, u) for u in db.scalars(stmt).all()]
    if status:
        rows = [r for r in rows if r["bus_pass_status"] == status.upper()]
    return {"count": len(rows), "students": rows}


@router.get("/admin/students/{user_id}")
def admin_student_detail(user_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    u = db.get(User, user_id)
    if not u or u.role not in (Role.STUDENT, Role.PASSENGER):
        raise HTTPException(status_code=404, detail="Student not found.")
    history = db.scalars(select(StudentVerification).where(StudentVerification.student_id == u.id)
                         .order_by(StudentVerification.submitted_at.desc())).all()
    tickets = db.scalars(select(Ticket).where(Ticket.user_id == u.id).order_by(Ticket.created_at.desc()).limit(20)).all()
    return {**_student_row(db, u),
            "history": [{"id": v.id, "status": v.status.value, "submitted_at": v.submitted_at.isoformat(),
                         "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None, "reason": v.rejection_reason} for v in history],
            "tickets": [ticket_view(t, include_qr=False) for t in tickets]}


@router.post("/admin/passengers/{user_id}/suspend-eligibility")
@router.post("/admin/students/{user_id}/suspend-eligibility")
def admin_suspend_eligibility(user_id: str, req: ReasonBody, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    profile = db.get(PassengerProfile, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Passenger not found.")
    reason = (req.reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(status_code=422, detail="Please give a reason (at least 5 characters).")
    profile.eligibility_suspended, profile.eligibility_suspended_reason = True, reason
    audit(db, "ELIGIBILITY_SUSPENDED", admin, "user", user_id, {"reason": reason}, client_ip(request))
    return {"user_id": user_id, "eligibility_suspended": True, "reason": reason}


@router.post("/admin/passengers/{user_id}/reinstate-eligibility")
@router.post("/admin/students/{user_id}/reinstate-eligibility")
def admin_reinstate_eligibility(user_id: str, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    profile = db.get(PassengerProfile, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Passenger not found.")
    profile.eligibility_suspended, profile.eligibility_suspended_reason = False, None
    audit(db, "ELIGIBILITY_REINSTATED", admin, "user", user_id, None, client_ip(request))
    return {"user_id": user_id, "eligibility_suspended": False}


# ---------------------------------------------------------------------------
# Conductors and buses
# ---------------------------------------------------------------------------

def _conductor_row(db: Session, c: Conductor) -> dict:
    from .conductor import bus_view

    u = db.get(User, c.user_id)
    trip = db.scalars(select(Trip).where(Trip.conductor_id == c.user_id, Trip.status == "ACTIVE")).first()
    scans = db.scalar(select(func.count()).select_from(TicketVerification).where(TicketVerification.conductor_id == c.user_id)) or 0
    return {**(_user_view(u) if u else {}), "user_id": c.user_id, "employee_id": c.employee_id,
            "bus": bus_view(db.get(Bus, c.bus_id) if c.bus_id else None), "assigned_route": c.assigned_route,
            "active_trip_id": trip.id if trip else None, "tickets_scanned": scans}


@router.get("/admin/conductors")
def admin_conductors(admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    return {"conductors": [_conductor_row(db, c) for c in db.scalars(select(Conductor).order_by(Conductor.employee_id)).all()]}


@router.get("/admin/conductors/{user_id}/activity")
def admin_conductor_activity(user_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    c = db.get(Conductor, user_id)
    if not c:
        raise HTTPException(status_code=404, detail="Conductor not found.")
    scans = db.scalars(select(TicketVerification).where(TicketVerification.conductor_id == user_id)
                       .order_by(TicketVerification.created_at.desc()).limit(100)).all()
    trips = db.scalars(select(Trip).where(Trip.conductor_id == user_id).order_by(Trip.started_at.desc()).limit(30)).all()
    logs = db.scalars(select(AuditLog).where(or_(AuditLog.actor_id == user_id, AuditLog.target_id == user_id))
                      .order_by(AuditLog.created_at.desc()).limit(50)).all()
    return {**_conductor_row(db, c),
            "scans": [{"result": s.result, "route": s.route, "at": s.created_at.isoformat()} for s in scans],
            "trips": [{"id": t.id, "route": t.route, "direction": t.direction, "status": t.status, "started_at": t.started_at.isoformat(),
                       "ended_at": t.ended_at.isoformat() if t.ended_at else None} for t in trips],
            "log": [{"at": a.created_at.isoformat(), "action": a.action, "result": a.result} for a in logs]}


@router.post("/admin/conductors/{user_id}/reset-credentials")
def admin_reset_conductor(user_id: str, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    """Issues a new random password, shown ONCE to the Super Admin to hand over in person. All sessions are revoked."""
    import secrets as _secrets

    from ..models import RefreshToken

    c = db.get(Conductor, user_id)
    u = db.get(User, user_id) if c else None
    if not u:
        raise HTTPException(status_code=404, detail="Conductor not found.")
    new_password = "Cd-" + _secrets.token_urlsafe(9)
    u.password_hash = hash_password(new_password)
    u.failed_logins, u.locked_until = 0, None
    for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == u.id, RefreshToken.revoked_at.is_(None))).all():
        t.revoked_at = datetime.now(timezone.utc)
    audit(db, "CONDUCTOR_CREDENTIALS_RESET", admin, "user", u.id, {"employee_id": c.employee_id}, client_ip(request))
    return {"employee_id": c.employee_id, "temporary_password": new_password,
            "message": "Shown once. Hand it to the conductor privately; it is not stored in readable form."}


class BusCreate(BaseModel):
    fleet_label: str = Field(min_length=1, max_length=40)
    registration_number: Optional[str] = Field(default=None, max_length=20)
    route: Optional[str] = Field(default=None, max_length=40)
    operational_status: Optional[str] = None
    max_capacity: int = Field(default=50, ge=1, le=200)


class BusUpdate(BaseModel):
    registration_number: Optional[str] = Field(default=None, max_length=20)
    route: Optional[str] = Field(default=None, max_length=40)
    operational_status: Optional[str] = None
    max_capacity: Optional[int] = Field(default=None, ge=1, le=200)
    conductor_user_id: Optional[str] = Field(default=None, max_length=32)


def _clean_reg(value: Optional[str]) -> Optional[str]:
    reg = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    if reg and not re.fullmatch(r"KA\d{1,2}[A-Z]{0,3}\d{1,4}", reg):
        raise HTTPException(status_code=422, detail="Registration number should look like KA57F4578.")
    return reg or None


def _bus_status(value: Optional[str]) -> Optional[BusStatus]:
    if value is None:
        return None
    if value.upper() not in BusStatus.__members__:
        raise HTTPException(status_code=422, detail="Status must be IN_SERVICE, OUT_OF_SERVICE or MAINTENANCE.")
    return BusStatus(value.upper())


async def _bus_row(db: Session, bus: Bus, realtime: bool) -> dict:
    from .conductor import bus_realtime, bus_view

    c = db.scalars(select(Conductor).where(Conductor.bus_id == bus.id)).first()
    row = {**bus_view(bus), "conductor": {"user_id": c.user_id, "employee_id": c.employee_id} if c else None}
    if realtime:
        row["realtime"] = await bus_realtime(bus)
    return row


@router.get("/admin/buses")
async def admin_buses(realtime: bool = True, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    buses = db.scalars(select(Bus).order_by(Bus.fleet_label)).all()
    return {"buses": [await _bus_row(db, b, realtime) for b in buses]}


@router.post("/admin/buses", status_code=201)
async def admin_create_bus(req: BusCreate, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    label = " ".join(req.fleet_label.split()).upper()
    if db.scalars(select(Bus).where(Bus.fleet_label == label)).first():
        raise HTTPException(status_code=409, detail="A bus with this label already exists.")
    reg = _clean_reg(req.registration_number)
    if reg and db.scalars(select(Bus).where(Bus.registration_number == reg)).first():
        raise HTTPException(status_code=409, detail="This registration number is already assigned to another bus.")
    bus = Bus(fleet_label=label, registration_number=reg, route=(req.route or "").strip().upper() or None,
              operational_status=_bus_status(req.operational_status) or BusStatus.IN_SERVICE, max_capacity=req.max_capacity)
    db.add(bus)
    db.flush()
    audit(db, "BUS_CREATED", admin, "bus", bus.id, {"label": label, "route": bus.route}, client_ip(request))
    return await _bus_row(db, bus, realtime=False)


@router.patch("/admin/buses/{bus_id}")
async def admin_update_bus(bus_id: str, req: BusUpdate, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    bus = _get_bus(db, bus_id)
    changed = {}
    if req.registration_number is not None:
        reg = _clean_reg(req.registration_number)
        if reg and db.scalars(select(Bus).where(Bus.registration_number == reg, Bus.id != bus.id)).first():
            raise HTTPException(status_code=409, detail="This registration number is already assigned to another bus.")
        bus.registration_number = changed["registration_number"] = reg
    if req.route is not None:
        bus.route = changed["route"] = req.route.strip().upper() or None
    if req.operational_status is not None:
        bus.operational_status = _bus_status(req.operational_status)
        changed["operational_status"] = bus.operational_status.value
    if req.max_capacity is not None:
        # applies from the next trip; a running trip keeps the capacity it started with
        bus.max_capacity = changed["max_capacity"] = req.max_capacity
    if req.conductor_user_id is not None:
        if req.conductor_user_id:
            c = db.get(Conductor, req.conductor_user_id)
            if not c:
                raise HTTPException(status_code=404, detail="Conductor not found.")
            _bind_bus(db, c, bus)
        else:
            for c in db.scalars(select(Conductor).where(Conductor.bus_id == bus.id)).all():
                c.bus_id = None
        changed["conductor"] = req.conductor_user_id or None
    # keep the bound conductor's cached route/registration in step with the bus
    for c in db.scalars(select(Conductor).where(Conductor.bus_id == bus.id)).all():
        c.assigned_bus, c.assigned_route = bus.registration_number, bus.route
    audit(db, "BUS_UPDATED", admin, "bus", bus.id, changed, client_ip(request))
    db.flush()
    return await _bus_row(db, bus, realtime=False)


@router.post("/admin/tickets/{ticket_id}/revoke")
def admin_revoke_ticket(ticket_id: str, req: ReasonBody, request: Request, admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    t = db.get(Ticket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    if t.status not in (TicketStatus.ISSUED,):
        raise HTTPException(status_code=409, detail=f"A {t.status.value.lower()} ticket cannot be revoked.")
    t.status = TicketStatus.REVOKED
    audit(db, "TICKET_REVOKED", admin, "ticket", t.id, {"reason": (req.reason or "").strip() or None}, client_ip(request))
    # Give the seats back exactly once (only ISSUED tickets get here, so a ticket can't be released twice)
    trip = release_from_trip(db, t)
    if trip:
        audit(db, "PASSENGER_COUNT_UPDATED", admin, "trip", trip.id,
              {"delta": -t.passenger_count, "passenger_count": trip.passenger_count, "ticket": t.id}, client_ip(request))
    return ticket_view(t, include_qr=False)


@router.get("/admin/payments")
def admin_payments(admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    """Payment outcomes (today, IST) and the latest 50 payments. Ticket references only — no passenger details."""
    from ..config import settings as cfg

    start_ist = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    paid_like = Ticket.ticket_type == "PAID"
    rows = db.execute(select(Ticket.payment_status, func.count(Ticket.id), func.coalesce(func.sum(Ticket.fare), 0))
                      .where(paid_like, Ticket.created_at >= start_ist).group_by(Ticket.payment_status)).all()
    recent = db.scalars(select(Ticket).where(paid_like).order_by(Ticket.created_at.desc()).limit(50)).all()
    provider = cfg.payment_provider
    configured = provider == "test" or bool(cfg.razorpay_key_id and cfg.razorpay_key_secret)
    return {
        "provider": provider, "configured": configured, "is_test": provider == "test",
        "webhook_configured": bool(cfg.razorpay_webhook_secret),
        "today": [{"payment_status": r[0], "count": int(r[1]), "amount": int(r[2])} for r in rows],
        "recent": [{"reference": t.reference, "route": t.route, "fare": t.fare, "payment_status": t.payment_status,
                    "provider": t.payment_provider, "status": t.status.value, "created_at": t.created_at.isoformat()} for t in recent],
    }


@router.get("/admin/trips/live")
async def admin_trips_live(admin: User = Depends(admin_only), db: Session = Depends(get_db, scope="function")):
    """Running trips with authoritative counts, plus paid/free split and revenue per trip and per route (today, IST)."""
    trips = active_trips(db)
    ids = [t.id for t in trips]
    counted = (TicketStatus.ISSUED, TicketStatus.USED)
    stats = {}
    if ids:
        rows = db.execute(select(Ticket.trip_id, Ticket.ticket_type, func.count(Ticket.id), func.coalesce(func.sum(Ticket.passenger_count), 0),
                                 func.coalesce(func.sum(Ticket.fare), 0))
                          .where(Ticket.trip_id.in_(ids), Ticket.status.in_(counted))
                          .group_by(Ticket.trip_id, Ticket.ticket_type)).all()
        for trip_id, ttype, n, pax, revenue in rows:
            s_ = stats.setdefault(trip_id, {"paid_tickets": 0, "free_tickets": 0, "paid_passengers": 0, "free_passengers": 0, "revenue": 0})
            key = "free" if ttype == "ELIGIBLE_FREE" else "paid"
            s_[f"{key}_tickets"] += int(n)
            s_[f"{key}_passengers"] += int(pax)
            s_["revenue"] += int(revenue)
    empty = {"paid_tickets": 0, "free_tickets": 0, "paid_passengers": 0, "free_passengers": 0, "revenue": 0}
    out, routes = [], {}
    for t in trips:
        bus = db.get(Bus, t.bus_id) if t.bus_id else None
        row = {**public_trip_view(t, bus), **stats.get(t.id, empty)}
        crew = db.get(Conductor, t.conductor_id)
        row["conductor_id"] = crew.employee_id if crew else None
        # current / next stop only from the real BMTC feed (needs the bus registration); never invented
        live = await bus_realtime(bus) if bus and bus.registration_number else None
        row["current_stop"] = live.get("current_stop") if live and live.get("available") else None
        row["next_stop"] = live.get("next_stop") if live and live.get("available") else None
        row["realtime_status"] = live.get("status") if live else "REALTIME DATA UNAVAILABLE"
        out.append(row)
        r = routes.setdefault(t.route or "—", {"route": t.route, "active_trips": 0, "passengers": 0, "capacity": 0, "revenue": 0,
                                              "paid_passengers": 0, "free_passengers": 0})
        r["active_trips"] += 1
        r["passengers"] += row["passenger_count"]
        r["capacity"] += row["max_capacity"]
        r["revenue"] += row["revenue"]
        r["paid_passengers"] += row["paid_passengers"]
        r["free_passengers"] += row["free_passengers"]
    return {"trips": out, "routes": sorted(routes.values(), key=lambda r: -r["passengers"]),
            "totals": {"active_trips": len(out), "passengers": sum(r["passenger_count"] for r in out),
                       "revenue": sum(r["revenue"] for r in out)},
            "at": datetime.now(timezone.utc).isoformat()}
