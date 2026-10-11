"""Registration, login (password / OTP / staff portals with optional TOTP), token refresh, logout, /me."""

import hmac
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..eligibility import current_identity_verification, effective_student_status
from ..models import (
    College,
    CollegeAdmin,
    CollegeStatus,
    PasswordReset,
    Conductor,
    Gender,
    OtpChallenge,
    PassengerProfile,
    RefreshToken,
    Role,
    User,
    VerificationStatus,
)
from ..providers.biometric import get_biometric_provider
from ..providers.identity import DEV_LABEL, get_identity_provider
from ..providers.otp import DEV_NOTICE, OtpDeliveryError, get_otp_delivery, mask_email
from ..rbac import get_current_user
from ..security import (
    client_ip,
    create_access_token,
    decrypt_text,
    hash_password,
    new_csrf_token,
    new_refresh_token,
    password_policy_error,
    rate_limiter,
    sha256_hex,
    verify_password,
    verify_totp,
)

router = APIRouter(tags=["Access: Auth"])

PORTAL_ROLES = {
    "passenger": {Role.PASSENGER, Role.STUDENT},
    "conductor": {Role.CONDUCTOR},
    "college": {Role.COLLEGE_ADMIN},
    "admin": {Role.SUPER_ADMIN},
}
REFRESH_COOKIE = "nb_refresh"
CSRF_COOKIE = "nb_csrf"
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def normalize_phone(raw: str) -> Optional[str]:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(max_length=20)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    gender: Literal["MALE", "FEMALE"]
    date_of_birth: Optional[date] = None
    # "Do you have a valid Bus Pass?" (male flow) — a YES creates a student account whose pass must be college-verified
    has_bus_pass: Optional[bool] = None
    # "Do you have an Aadhaar card?" (female flow)
    has_aadhaar: Optional[bool] = None
    is_student: bool = False  # legacy alias of has_bus_pass

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not re.fullmatch(r"[A-Za-zಀ-೿ .'-]{2,120}", v):
            raise ValueError("Name may contain letters, spaces, dots, apostrophes and hyphens only.")
        return v


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    portal: Literal["passenger", "conductor", "college", "admin"] = "passenger"
    college_code: Optional[str] = Field(default=None, max_length=32)
    totp_code: Optional[str] = Field(default=None, max_length=8)


class OtpRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)


class OtpVerify(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=6, max_length=6)


class LoginCodeVerify(BaseModel):
    challenge_id: str = Field(min_length=8, max_length=32)
    code: str = Field(min_length=6, max_length=6)


class LoginCodeResend(BaseModel):
    challenge_id: str = Field(min_length=8, max_length=32)


class RefreshRequest(BaseModel):
    refresh_token: Optional[str] = None


def validate_dob(dob: date) -> None:
    today = date.today()
    if dob > today or dob.year < today.year - 110:
        raise HTTPException(status_code=422, detail="Enter a valid date of birth.")


def _find_user(db: Session, identifier: str) -> Optional[User]:
    ident = identifier.strip().lower()
    phone = normalize_phone(ident)
    conds = [User.email == ident]
    if phone:
        conds.append(User.phone == phone)
    user = db.scalars(select(User).where(or_(*conds))).first()
    if user is None:
        # Conductors can sign in with their employee ID
        conductor = db.scalars(select(Conductor).where(Conductor.employee_id == identifier.strip().upper())).first()
        if conductor:
            user = db.get(User, conductor.user_id)
    return user


def portal_for(role: Role) -> str:
    return next(p for p, roles in PORTAL_ROLES.items() if role in roles)


def issue_session(db: Session, user: User, response: Response, request: Optional[Request] = None) -> dict:
    token, token_hash = new_refresh_token()
    now = datetime.now(timezone.utc)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
            user_agent=(request.headers.get("user-agent", "")[:200] if request else None) or None,
            ip_address=client_ip(request) if request else None,
            last_used_at=now,
        )
    )
    csrf = new_csrf_token()
    # Web: refresh token in an HttpOnly cookie (+ double-submit CSRF cookie). Native apps use the body value.
    response.set_cookie(REFRESH_COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="strict",
                        max_age=settings.refresh_token_ttl_seconds, path="/api/access/auth")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=settings.cookie_secure, samesite="strict",
                        max_age=settings.refresh_token_ttl_seconds, path="/")
    return {
        "access_token": create_access_token(user.id, user.role.value),
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl_seconds,
        "refresh_token": token,
        "csrf_token": csrf,
        "role": user.role.value,
        "portal": portal_for(user.role),
    }


def next_step_for(db: Session, user: User) -> str:
    if user.role == Role.STUDENT:
        status, _, _ = effective_student_status(db, user.id)
        if status == "NOT_SUBMITTED":
            return "STUDENT_VERIFICATION"
    profile = user.passenger_profile
    if profile and profile.gender == Gender.FEMALE:
        if profile.has_aadhaar_answer is None:
            return "AADHAAR_QUESTION"
        if profile.has_aadhaar_answer and profile.identity_status == VerificationStatus.NOT_STARTED:
            return "IDENTITY_CONSENT"
    return "DASHBOARD"


def passenger_category(db: Session, user: User) -> Optional[str]:
    """Plain summary for the dashboard, e.g. MALE · REGULAR or FEMALE · IDENTITY_VERIFIED."""
    profile = user.passenger_profile
    if not profile:
        return None
    if user.role == Role.STUDENT:
        status, _, _ = effective_student_status(db, user.id)
        tail = {"APPROVED": "BUS_PASS_VERIFIED", "REJECTED": "BUS_PASS_REJECTED", "REVOKED": "BUS_PASS_REVOKED",
                "EXPIRED": "BUS_PASS_EXPIRED", "PENDING": "BUS_PASS_PENDING"}.get(status, "BUS_PASS_NOT_SUBMITTED")
    elif profile.gender == Gender.FEMALE:
        tail = "IDENTITY_VERIFIED" if current_identity_verification(db, user.id) else (
            "AADHAAR_NOT_VERIFIED" if profile.has_aadhaar_answer is False else "IDENTITY_NOT_VERIFIED")
    else:
        tail = "REGULAR"
    return f"{profile.gender.value}_{tail}"


@router.post("/auth/register", status_code=201)
def register(req: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    rate_limiter.check(f"register:{client_ip(request)}", limit=10)
    phone = normalize_phone(req.phone)
    if not phone:
        raise HTTPException(status_code=422, detail="Enter a valid 10-digit Indian mobile number.")
    policy_error = password_policy_error(req.password)
    if policy_error:
        raise HTTPException(status_code=422, detail=policy_error)
    email = req.email.lower()
    if req.date_of_birth:
        validate_dob(req.date_of_birth)
    if db.scalars(select(User).where(or_(User.email == email, User.phone == phone))).first():
        raise HTTPException(status_code=409, detail="An account with this email or mobile number already exists.")
    # Role is derived server-side; clients cannot register staff roles
    student = bool(req.has_bus_pass or req.is_student)
    user = User(name=req.name, email=email, phone=phone, password_hash=hash_password(req.password),
                role=Role.STUDENT if student else Role.PASSENGER, date_of_birth=req.date_of_birth)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="An account with this email or mobile number already exists.")
    profile = PassengerProfile(user_id=user.id, gender=Gender(req.gender), has_bus_pass_answer=student,
                               has_aadhaar_answer=req.has_aadhaar if req.gender == "FEMALE" else None)
    if req.gender == "FEMALE" and req.has_aadhaar is False:
        profile.identity_status = VerificationStatus.DECLINED
    db.add(profile)
    db.flush()
    db.refresh(user)
    audit(db, "USER_REGISTERED", user, "user", user.id, {"role": user.role.value, "gender": req.gender}, client_ip(request),
          user_agent=request.headers.get("user-agent"))
    session = issue_session(db, user, response, request)
    return {**session, "user_id": user.id, "next_step": next_step_for(db, user)}


def _check_lockout(user: Optional[User]) -> None:
    if user and user.locked_until and user.locked_until.replace(tzinfo=user.locked_until.tzinfo or timezone.utc) > datetime.now(timezone.utc):
        raise HTTPException(status_code=423, detail="Account temporarily locked after repeated failed sign-ins. Try again later.")


@router.post("/auth/login")
def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    ip = client_ip(request)
    rate_limiter.check(f"login:{ip}", limit=settings.login_rate_limit_per_minute)
    user = _find_user(db, req.identifier)
    _check_lockout(user)
    if not user or not verify_password(req.password, user.password_hash) or not user.is_active:
        if user:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_logins = 0
        audit(db, "LOGIN_FAILED", None, "user", user.id if user else None, {"portal": req.portal}, ip)
        db.commit()  # keep the failure counter / audit row even though the request is rejected
        raise HTTPException(status_code=401, detail="Incorrect sign-in details.")
    if user.role not in PORTAL_ROLES[req.portal]:
        audit(db, "LOGIN_WRONG_PORTAL", user, "user", user.id, {"portal": req.portal}, ip)
        db.commit()
        raise HTTPException(status_code=403, detail=f"This account cannot sign in to the {req.portal} portal.")
    if user.role == Role.COLLEGE_ADMIN:
        binding = db.get(CollegeAdmin, user.id)
        college = db.get(College, binding.college_id) if binding else None
        if not college or (req.college_code and college.code.upper() != req.college_code.strip().upper()):
            raise HTTPException(status_code=401, detail="Incorrect sign-in details.")
        if college.status != CollegeStatus.APPROVED or not college.is_active:
            messages = {CollegeStatus.PENDING: "Your college registration is pending Super Admin approval.",
                        CollegeStatus.REJECTED: "Your college registration was not approved.",
                        CollegeStatus.SUSPENDED: "Your college account is suspended. Contact the Namma Bus administrator."}
            raise HTTPException(status_code=403, detail=messages.get(college.status, "Your college account is not active."))
    if user.totp_secret_encrypted:
        if not req.totp_code:
            raise HTTPException(status_code=401, detail="Two-factor code required.", headers={"X-2FA-Required": "totp"})
        if not verify_totp(decrypt_text(user.totp_secret_encrypted), req.totp_code):
            audit(db, "LOGIN_2FA_FAILED", user, "user", user.id, None, ip)
            db.commit()
            raise HTTPException(status_code=401, detail="Invalid two-factor code.")
    user.failed_logins = 0
    user.locked_until = None
    # Second step: email a one-time code (accounts with TOTP already completed a stronger second factor;
    # conductors sign in with Conductor ID + password/PIN on shared handheld devices, per the spec)
    if settings.login_email_code and not user.totp_secret_encrypted and user.email and user.role != Role.CONDUCTOR:
        return _send_login_code(db, user, req.portal, ip)
    audit(db, "LOGIN_SUCCESS", user, "user", user.id, {"portal": req.portal}, ip, user_agent=request.headers.get("user-agent"))
    return {**issue_session(db, user, response, request), "user_id": user.id, "next_step": next_step_for(db, user)}


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _deliver(user: User, code: str) -> dict:
    """Send the code; returns extra response fields (development code only in development mode)."""
    delivery = get_otp_delivery()
    try:
        dev_code = delivery.send(user.email or "", code, name=user.name, minutes=settings.email_code_ttl_minutes)
    except OtpDeliveryError:
        raise HTTPException(status_code=503, detail="We couldn't send the sign-in code by email. Please try again shortly.")
    return {"development_code": dev_code, "development_notice": DEV_NOTICE} if dev_code and delivery.is_development else {}


def _send_login_code(db: Session, user: User, portal: str, ip: str) -> dict:
    now = datetime.now(timezone.utc)
    code = _new_code()
    ch = OtpChallenge(user_id=user.id, code_hash="", purpose="LOGIN_EMAIL", sent_at=now,
                      expires_at=now + timedelta(minutes=settings.email_code_ttl_minutes))
    db.add(ch)
    db.flush()
    ch.code_hash = sha256_hex(f"{ch.id}:{user.id}:{code}")
    extra = _deliver(user, code)
    audit(db, "LOGIN_CODE_SENT", user, "user", user.id, {"portal": portal, "channel": "email"}, ip)
    return {
        "status": "EMAIL_CODE_SENT",
        "challenge_id": ch.id,
        "email_hint": mask_email(user.email or ""),
        "expires_in": settings.email_code_ttl_minutes * 60,
        "resend_after": RESEND_COOLDOWN_SECONDS,
        **extra,
    }


RESEND_COOLDOWN_SECONDS = 60
MAX_RESENDS = 3
MAX_CODE_ATTEMPTS = 5


def _open_challenge(db: Session, challenge_id: str) -> OtpChallenge:
    ch = db.get(OtpChallenge, challenge_id)
    now = datetime.now(timezone.utc)
    if (not ch or ch.purpose != "LOGIN_EMAIL" or ch.consumed_at is not None
            or ch.expires_at.replace(tzinfo=ch.expires_at.tzinfo or timezone.utc) < now or ch.attempts >= MAX_CODE_ATTEMPTS):
        raise HTTPException(status_code=401, detail="This code has expired. Please sign in again.")
    return ch


@router.post("/auth/login/verify")
def login_verify(req: LoginCodeVerify, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    """Second sign-in step: the code that was emailed after a correct password."""
    ip = client_ip(request)
    rate_limiter.check(f"login-code:{ip}", limit=15)
    ch = _open_challenge(db, req.challenge_id)
    user = db.get(User, ch.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="This code has expired. Please sign in again.")
    ch.attempts += 1
    if not hmac.compare_digest(ch.code_hash, sha256_hex(f"{ch.id}:{user.id}:{req.code.strip()}")):
        audit(db, "LOGIN_CODE_FAILED", user, "user", user.id, {"attempt": ch.attempts}, ip)
        db.commit()
        left = MAX_CODE_ATTEMPTS - ch.attempts
        raise HTTPException(status_code=401, detail=f"Incorrect code. {left} attempt(s) left." if left > 0 else "Too many incorrect codes. Please sign in again.")
    ch.consumed_at = datetime.now(timezone.utc)
    audit(db, "LOGIN_SUCCESS", user, "user", user.id, {"method": "password+email_code"}, ip, user_agent=request.headers.get("user-agent"))
    return {**issue_session(db, user, response, request), "user_id": user.id, "next_step": next_step_for(db, user)}


@router.post("/auth/login/resend")
def login_resend(req: LoginCodeResend, request: Request, db: Session = Depends(get_db, scope="function")):
    ip = client_ip(request)
    rate_limiter.check(f"login-resend:{ip}", limit=5)
    ch = _open_challenge(db, req.challenge_id)
    user = db.get(User, ch.user_id)
    now = datetime.now(timezone.utc)
    sent = (ch.sent_at or now).replace(tzinfo=(ch.sent_at or now).tzinfo or timezone.utc)
    wait = RESEND_COOLDOWN_SECONDS - int((now - sent).total_seconds())
    if wait > 0:
        raise HTTPException(status_code=429, detail=f"Please wait {wait} seconds before requesting a new code.", headers={"Retry-After": str(wait)})
    if ch.resend_count >= MAX_RESENDS:
        raise HTTPException(status_code=429, detail="Too many codes requested. Please sign in again.")
    code = _new_code()
    ch.code_hash = sha256_hex(f"{ch.id}:{user.id}:{code}")
    ch.resend_count += 1
    ch.attempts = 0
    ch.sent_at = now
    ch.expires_at = now + timedelta(minutes=settings.email_code_ttl_minutes)
    extra = _deliver(user, code)
    audit(db, "LOGIN_CODE_RESENT", user, "user", user.id, {"resend": ch.resend_count}, ip)
    return {"status": "EMAIL_CODE_SENT", "challenge_id": ch.id, "email_hint": mask_email(user.email or ""),
            "expires_in": settings.email_code_ttl_minutes * 60, "resend_after": RESEND_COOLDOWN_SECONDS, **extra}


@router.post("/auth/otp/request")
def otp_request(req: OtpRequest, request: Request, db: Session = Depends(get_db, scope="function")):
    """Passwordless sign-in for passengers/students. Always answers the same way to avoid account probing."""
    rate_limiter.check(f"otp:{client_ip(request)}", limit=5)
    user = _find_user(db, req.identifier)
    body = {"message": "If the account exists, a one-time code has been sent."}
    if not user or user.role not in PORTAL_ROLES["passenger"]:
        return body
    if not user.email:
        return body
    code = _new_code()
    db.add(OtpChallenge(user_id=user.id, code_hash=sha256_hex(f"{user.id}:{code}"), purpose="LOGIN",
                        sent_at=datetime.now(timezone.utc),
                        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.email_code_ttl_minutes)))
    try:
        extra = _deliver(user, code)
    except HTTPException:
        # Same answer as for unknown accounts, so delivery problems don't reveal who has an account
        return body
    if extra:
        body.update({"development_otp": extra["development_code"], "development_notice": extra["development_notice"]})
    body["message"] = "If the account exists, a one-time code has been sent to its email."
    return body


@router.post("/auth/otp/verify")
def otp_verify(req: OtpVerify, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    rate_limiter.check(f"otp-verify:{client_ip(request)}", limit=10)
    user = _find_user(db, req.identifier)
    if not user or user.role not in PORTAL_ROLES["passenger"]:
        raise HTTPException(status_code=401, detail="Invalid or expired code.")
    challenge = db.scalars(
        select(OtpChallenge)
        .where(OtpChallenge.user_id == user.id, OtpChallenge.purpose == "LOGIN", OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.expires_at.desc())
    ).first()
    now = datetime.now(timezone.utc)
    if not challenge or challenge.expires_at.replace(tzinfo=challenge.expires_at.tzinfo or timezone.utc) < now or challenge.attempts >= 5:
        raise HTTPException(status_code=401, detail="Invalid or expired code.")
    challenge.attempts += 1
    if challenge.code_hash != sha256_hex(f"{user.id}:{req.code}"):
        db.commit()  # count the wrong attempt
        raise HTTPException(status_code=401, detail="Invalid or expired code.")
    challenge.consumed_at = now
    audit(db, "LOGIN_SUCCESS", user, "user", user.id, {"method": "otp"}, client_ip(request))
    return {**issue_session(db, user, response, request), "user_id": user.id, "next_step": next_step_for(db, user)}


@router.post("/auth/refresh")
def refresh(req: RefreshRequest, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    token = req.refresh_token
    if not token:
        # Cookie-based refresh (web) requires the double-submit CSRF header
        token = request.cookies.get(REFRESH_COOKIE)
        csrf_cookie = request.cookies.get(CSRF_COOKIE)
        if not token or not csrf_cookie or request.headers.get("x-csrf-token") != csrf_cookie:
            raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    row = db.scalars(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(token))).first()
    now = datetime.now(timezone.utc)
    if not row or row.revoked_at or row.expires_at.replace(tzinfo=row.expires_at.tzinfo or timezone.utc) < now:
        if row and row.revoked_at:
            # Reuse of a rotated token: revoke every session of this user
            for other in db.scalars(select(RefreshToken).where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))):
                other.revoked_at = now
            audit(db, "REFRESH_TOKEN_REUSE", None, "user", row.user_id, None, client_ip(request))
            db.commit()
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    row.revoked_at = now  # rotation
    return {**issue_session(db, user, response, request), "user_id": user.id}


@router.post("/auth/logout")
def logout(req: RefreshRequest, request: Request, response: Response, user: User = Depends(get_current_user),
           db: Session = Depends(get_db, scope="function")):
    token = req.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if token:
        row = db.scalars(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(token), RefreshToken.user_id == user.id)).first()
        if row and not row.revoked_at:
            row.revoked_at = datetime.now(timezone.utc)
    response.delete_cookie(REFRESH_COOKIE, path="/api/access/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")
    audit(db, "LOGOUT", user, "user", user.id, None, client_ip(request))
    return {"message": "Signed out."}


@router.get("/auth/me", include_in_schema=False)
@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    profile = user.passenger_profile
    body = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": f"******{user.phone[-4:]}" if user.phone else None,
        "role": user.role.value,
        "portal": portal_for(user.role),
        "two_factor_enabled": bool(user.totp_secret_encrypted),
        "next_step": next_step_for(db, user),
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "has_profile_photo": bool(user.profile_photo_document_id),
        "passenger_category": passenger_category(db, user),
    }
    if profile:
        iv = current_identity_verification(db, user.id)
        identity_provider = get_identity_provider()
        body["passenger"] = {
            "gender": profile.gender.value,
            "has_aadhaar_answer": profile.has_aadhaar_answer,
            "identity_status": (VerificationStatus.VERIFIED.value if iv else profile.identity_status.value),
            "identity_provider": iv.provider if iv else None,
            "identity_verified_at": iv.verified_at.isoformat() if iv and iv.verified_at else None,
            "identity_expires_at": iv.expires_at.isoformat() if iv and iv.expires_at else None,
            "identity_is_development": bool(iv and iv.is_development),
            "identity_label": DEV_LABEL if iv and iv.is_development else None,
            "identity_service_available": identity_provider.available(),
            "identity_service_is_development": identity_provider.is_development,
            "face_service_available": get_biometric_provider().available(),
        }
    if user.role == Role.STUDENT:
        status, ver, sp = effective_student_status(db, user.id)
        body["student"] = {
            "status": status,
            "rejection_reason": ver.rejection_reason if ver else None,
            "pass_number": sp.pass_number if sp else None,
            "pass_expiry_date": sp.expiry_date.isoformat() if sp and sp.expiry_date else None,
        }
    if user.role == Role.CONDUCTOR:
        c = db.get(Conductor, user.id)
        body["conductor"] = {"employee_id": c.employee_id, "assigned_bus": c.assigned_bus, "assigned_route": c.assigned_route} if c else None
    if user.role == Role.COLLEGE_ADMIN:
        b = db.get(CollegeAdmin, user.id)
        college = db.get(College, b.college_id) if b else None
        body["college"] = {"id": college.id, "code": college.code, "name": college.name} if college else None
    return body


# ---------------------------------------------------------------------------
# Account recovery (forgot password) and device/session management
# ---------------------------------------------------------------------------

class ForgotPassword(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)


class ResetPassword(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/password/forgot")
def password_forgot(req: ForgotPassword, request: Request, db: Session = Depends(get_db, scope="function")):
    """Emails a 6-digit reset code. Same answer whether or not the account exists."""
    rate_limiter.check(f"pw-forgot:{client_ip(request)}", limit=5)
    body = {"message": "If the account exists, a reset code has been sent to its email."}
    user = _find_user(db, req.identifier)
    if not user or not user.is_active or not user.email:
        return body
    code = _new_code()
    db.add(PasswordReset(user_id=user.id, code_hash=sha256_hex(f"reset:{user.id}:{code}"),
                         expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)))
    try:
        extra = _deliver(user, code)
    except HTTPException:
        return body
    audit(db, "PASSWORD_RESET_REQUESTED", user, "user", user.id, None, client_ip(request))
    if extra:
        body.update({"development_code": extra["development_code"], "development_notice": extra["development_notice"]})
    return body


@router.post("/auth/password/reset")
def password_reset(req: ResetPassword, request: Request, db: Session = Depends(get_db, scope="function")):
    rate_limiter.check(f"pw-reset:{client_ip(request)}", limit=10)
    user = _find_user(db, req.identifier)
    invalid = HTTPException(status_code=400, detail="Invalid or expired reset code.")
    if not user:
        raise invalid
    row = db.scalars(select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
                     .order_by(PasswordReset.created_at.desc())).first()
    now = datetime.now(timezone.utc)
    if not row or row.expires_at.replace(tzinfo=row.expires_at.tzinfo or timezone.utc) < now or row.attempts >= 5:
        raise invalid
    row.attempts += 1
    if not hmac.compare_digest(row.code_hash, sha256_hex(f"reset:{user.id}:{req.code.strip()}")):
        db.commit()
        raise invalid
    err = password_policy_error(req.new_password)
    if err:
        raise HTTPException(status_code=422, detail=err)
    user.password_hash = hash_password(req.new_password)
    user.failed_logins, user.locked_until = 0, None
    row.used_at = now
    for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))):
        t.revoked_at = now  # sign out everywhere
    audit(db, "PASSWORD_RESET", user, "user", user.id, None, client_ip(request))
    return {"message": "Password changed. Please sign in with your new password."}


@router.get("/auth/sessions")
def list_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
                      .order_by(RefreshToken.created_at.desc())).all()
    current = sha256_hex(request.cookies.get(REFRESH_COOKIE, "")) if request.cookies.get(REFRESH_COOKIE) else None
    return {"sessions": [{"id": r.id, "device": r.user_agent or "Unknown device", "ip": r.ip_address,
                          "signed_in_at": r.created_at.isoformat(), "last_used_at": (r.last_used_at or r.created_at).isoformat(),
                          "current": r.token_hash == current}
                         for r in rows if r.expires_at.replace(tzinfo=r.expires_at.tzinfo or timezone.utc) > now]}


@router.delete("/auth/sessions/{session_id}")
def revoke_session(session_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    row = db.get(RefreshToken, session_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found.")
    row.revoked_at = datetime.now(timezone.utc)
    audit(db, "SESSION_REVOKED", user, "session", session_id, None, client_ip(request))
    return {"message": "Signed out on that device."}
