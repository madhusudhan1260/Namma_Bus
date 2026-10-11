"""
Backend eligibility engine. The frontend can only *request* eligibility; this module decides it.

Rules come from a JSON policy (ELIGIBILITY_POLICY_PATH) so they can change without code changes. Each rule
lists requirement checks; a rule grants its fare only when every check passes. Self-declared gender never
grants anything: the female rule requires the identity provider's attested attribute plus a fresh,
single-use face-verification match bound to that identity verification.

Every decision returns:
  eligibility  REGULAR_PAID | STUDENT_FREE | FEMALE_IDENTITY_VERIFIED_FREE
  reason_code  ELIGIBLE_FREE | NOT_ELIGIBLE | VERIFICATION_REQUIRED | VERIFICATION_EXPIRED | VERIFICATION_FAILED
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    College,
    CollegeStatus,
    FaceVerificationAttempt,
    IdentityVerification,
    PassengerProfile,
    StudentPass,
    StudentStatus,
    StudentVerification,
    User,
    VerificationStatus,
)

IST = timezone(timedelta(hours=5, minutes=30))

REGULAR_PAID = "REGULAR_PAID"
ELIGIBLE_FREE = "ELIGIBLE_FREE"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
VERIFICATION_EXPIRED = "VERIFICATION_EXPIRED"
VERIFICATION_FAILED = "VERIFICATION_FAILED"
# When several rules fail, the most actionable reason is reported
REASON_PRIORITY = [VERIFICATION_REQUIRED, VERIFICATION_EXPIRED, VERIFICATION_FAILED, NOT_ELIGIBLE]


def today_ist():
    return datetime.now(IST).date()


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@lru_cache(maxsize=4)
def _load_policy(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_policy() -> dict:
    return _load_policy(settings.eligibility_policy_path)


def reload_policy() -> dict:
    _load_policy.cache_clear()
    return load_policy()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def current_identity_verification(db: Session, user_id: str) -> Optional[IdentityVerification]:
    """Latest VERIFIED, unexpired, unrevoked identity verification."""
    rows = db.scalars(
        select(IdentityVerification)
        .where(IdentityVerification.user_id == user_id, IdentityVerification.verification_status == VerificationStatus.VERIFIED)
        .order_by(IdentityVerification.verified_at.desc())
    ).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.expires_at is None or _aware(row.expires_at) > now:
            return row
    return None


def latest_identity_attempt(db: Session, user_id: str) -> Optional[IdentityVerification]:
    return db.scalars(select(IdentityVerification).where(IdentityVerification.user_id == user_id)
                      .order_by(IdentityVerification.created_at.desc())).first()


def latest_student_verification(db: Session, user_id: str) -> Optional[StudentVerification]:
    return db.scalars(
        select(StudentVerification).where(StudentVerification.student_id == user_id).order_by(StudentVerification.submitted_at.desc())
    ).first()


def effective_student_status(db: Session, user_id: str) -> Tuple[str, Optional[StudentVerification], Optional[StudentPass]]:
    """NOT_SUBMITTED / PENDING / APPROVED / REJECTED / REVOKED / EXPIRED, with expiry computed from the pass dates."""
    ver = latest_student_verification(db, user_id)
    if not ver:
        return StudentStatus.NOT_SUBMITTED.value, None, None
    sp = db.get(StudentPass, ver.student_pass_id) if ver.student_pass_id else None
    if ver.status == StudentStatus.APPROVED and sp and sp.expiry_date and sp.expiry_date < today_ist():
        return StudentStatus.EXPIRED.value, ver, sp
    return ver.status.value, ver, sp


# ---------------------------------------------------------------------------
# Requirement checks: (db, user, ctx) -> (ok, reason_text, reference, reason_code)
# ---------------------------------------------------------------------------
Check = Callable[[Session, User, dict], Tuple[bool, str, Optional[str], str]]


def _eligibility_not_suspended(db, user, ctx):
    profile = db.get(PassengerProfile, user.id)
    if profile and profile.eligibility_suspended:
        return False, "Free-ticket eligibility is suspended on this account. Please contact Namma Bus support.", None, NOT_ELIGIBLE
    return True, "", None, ELIGIBLE_FREE


def _identity_verified(db, user, ctx):
    iv = current_identity_verification(db, user.id)
    ctx["identity"] = iv
    if iv:
        return True, "", iv.verification_reference, ELIGIBLE_FREE
    latest = latest_identity_attempt(db, user.id)
    if latest and latest.verification_status == VerificationStatus.VERIFIED:
        return False, "Your identity verification has expired. Please verify again.", None, VERIFICATION_EXPIRED
    if latest and latest.verification_status == VerificationStatus.FAILED:
        return False, "Identity verification failed. You can try again or buy a regular ticket.", None, VERIFICATION_FAILED
    return False, "Identity verification is required for this benefit.", None, VERIFICATION_REQUIRED


def _identity_attested_female(db, user, ctx):
    iv = ctx.get("identity") or current_identity_verification(db, user.id)
    if not iv or (iv.attributes or {}).get("gender") != "F":
        return False, "The identity provider has not attested eligibility for this benefit.", None, NOT_ELIGIBLE
    return True, "", iv.verification_reference, ELIGIBLE_FREE


def _face_verified_recent(db, user, ctx):
    iv = ctx.get("identity") or current_identity_verification(db, user.id)
    attempt_id = ctx.get("face_verification_id")
    if not iv:
        return False, "Identity is not verified.", None, VERIFICATION_REQUIRED
    if not attempt_id:
        ctx["needs_face_verification"] = True
        return False, "Face verification is required to use this eligibility.", None, VERIFICATION_REQUIRED
    attempt = db.get(FaceVerificationAttempt, attempt_id)
    now = datetime.now(timezone.utc)
    if not attempt or attempt.user_id != user.id or attempt.identity_verification_id != iv.id or attempt.consumed_by_ticket_id is not None:
        ctx["needs_face_verification"] = True
        return False, "Face verification is required to use this eligibility.", None, VERIFICATION_REQUIRED
    if attempt.result == "NO_MATCH":
        ctx["needs_face_verification"] = True
        return False, "Identity verification failed. Please try again or purchase a regular ticket.", None, VERIFICATION_FAILED
    if attempt.result != "MATCH":
        ctx["needs_face_verification"] = True
        return False, "Identity verification is temporarily unavailable.", None, VERIFICATION_REQUIRED
    if _aware(attempt.expires_at) <= now:
        ctx["needs_face_verification"] = True
        return False, "Face verification has expired. Please verify again.", None, VERIFICATION_EXPIRED
    ctx["face_attempt"] = attempt
    return True, "", attempt.verification_reference, ELIGIBLE_FREE


def _student_college_approved(db, user, ctx):
    status, ver, sp = effective_student_status(db, user.id)
    ctx["student"] = (status, ver, sp)
    if not ver or status in ("NOT_SUBMITTED", "PENDING"):
        return False, "Your bus pass must be verified by your college before you can receive an eligible free ticket.", None, VERIFICATION_REQUIRED
    if status in ("REJECTED", "REVOKED"):
        return False, f"Your bus pass was {status.lower()} by the college.", None, VERIFICATION_FAILED
    if status == "EXPIRED":
        return False, "Your bus pass has expired. Submit a new valid pass.", None, VERIFICATION_EXPIRED
    college = db.get(College, ver.college_id)
    if not college or college.status != CollegeStatus.APPROVED or not college.is_active:
        return False, "Your college is not currently approved on Namma Bus.", None, NOT_ELIGIBLE
    return True, "", f"STUDENT-VER-{ver.id[:12].upper()}", ELIGIBLE_FREE


def _student_pass_approved(db, user, ctx):
    status, ver, sp = ctx.get("student") or effective_student_status(db, user.id)
    if not sp or sp.status != StudentStatus.APPROVED:
        return False, "No approved student bus pass.", None, VERIFICATION_REQUIRED
    return True, "", None, ELIGIBLE_FREE


def _student_pass_valid_today(db, user, ctx):
    status, ver, sp = ctx.get("student") or effective_student_status(db, user.id)
    today = today_ist()
    if not sp or not sp.expiry_date or sp.expiry_date < today:
        return False, "The student bus pass has expired.", None, VERIFICATION_EXPIRED
    if sp.issue_date and sp.issue_date > today:
        return False, "The student bus pass is not valid yet.", None, NOT_ELIGIBLE
    return True, "", f"PASS-{(sp.pass_number or sp.id)[:20]}", ELIGIBLE_FREE


CHECKS: Dict[str, Check] = {
    "eligibility_not_suspended": _eligibility_not_suspended,
    "identity_verified": _identity_verified,
    "identity_attested_female": _identity_attested_female,
    "face_verified_recent": _face_verified_recent,
    "student_college_approved": _student_college_approved,
    "student_pass_approved": _student_pass_approved,
    "student_pass_valid_today": _student_pass_valid_today,
}


@dataclass
class EligibilityDecision:
    eligible: bool
    eligibility_type: Optional[str] = None  # STUDENT_FREE | FEMALE_IDENTITY_VERIFIED_FREE when eligible
    rule_id: Optional[str] = None
    fare_percent: int = 100
    verification_reference: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    reason_code: str = NOT_ELIGIBLE
    needs_face_verification: bool = False
    face_attempt: Optional[FaceVerificationAttempt] = None
    is_development: bool = False

    @property
    def eligibility(self) -> str:
        return self.eligibility_type if self.eligible and self.eligibility_type else REGULAR_PAID


def evaluate(db: Session, user: User, passenger_count: int = 1, face_verification_id: Optional[str] = None,
             use_eligibility: bool = True) -> EligibilityDecision:
    if not use_eligibility:
        return EligibilityDecision(eligible=False, reasons=["Regular ticket requested."], reason_code=NOT_ELIGIBLE)
    policy = load_policy()
    reasons: List[str] = []
    codes: List[str] = []
    needs_face = False
    for rule in policy.get("rules", []):
        if not rule.get("enabled", True):
            continue
        if user.role.value not in rule.get("applies_to", {}).get("roles", []):
            continue
        ctx: dict = {"face_verification_id": face_verification_id}
        refs: List[str] = []
        ok_all = True
        for req in rule.get("requires", []):
            check = CHECKS.get(req)
            if check is None:
                ok_all = False
                reasons.append(f"Unknown policy requirement '{req}'.")
                codes.append(NOT_ELIGIBLE)
                break
            ok, reason, ref, code = check(db, user, ctx)
            if not ok:
                ok_all = False
                reasons.append(reason)
                codes.append(code)
                break
            if ref and ref not in refs:
                refs.append(ref)
        # The female rule only "applies" to people who have engaged with identity verification;
        # a male / unverified passenger simply isn't eligible rather than "verification required".
        if not ok_all and rule["id"] == "female_identity_verified" and not ctx.get("identity") and codes and codes[-1] == VERIFICATION_REQUIRED:
            profile = db.get(PassengerProfile, user.id)
            if not profile or profile.gender.value != "FEMALE" or profile.has_aadhaar_answer is False:
                reasons.pop()
                codes.pop()
                continue
        needs_face = needs_face or bool(ctx.get("needs_face_verification"))
        if not ok_all:
            continue
        if passenger_count > int(rule.get("max_passengers", 1)):
            reasons.append(f"This eligibility covers at most {rule.get('max_passengers', 1)} passenger(s).")
            codes.append(NOT_ELIGIBLE)
            continue
        iv = ctx.get("identity")
        return EligibilityDecision(
            eligible=True,
            eligibility_type=rule["eligibility_type"],
            rule_id=rule["id"],
            fare_percent=int(rule.get("fare_percent", 0)),
            verification_reference=" | ".join(refs) or None,
            reason_code=ELIGIBLE_FREE,
            face_attempt=ctx.get("face_attempt"),
            is_development=bool(iv and iv.is_development) or bool(ctx.get("face_attempt") and ctx["face_attempt"].is_development),
        )
    if not reasons:
        reasons.append("No free-ticket eligibility applies to this account; the regular fare is charged.")
        codes.append(NOT_ELIGIBLE)
    reason_code = next((c for c in REASON_PRIORITY if c in codes), NOT_ELIGIBLE)
    return EligibilityDecision(eligible=False, reasons=reasons, reason_code=reason_code, needs_face_verification=needs_face)
