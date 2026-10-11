"""
Role-based access control.

Authorization never trusts role data from the client: the bearer token only identifies the user, and the
user's role, active flag and college/conductor bindings are re-read from the database on every request.
Access tokens are sent as `Authorization: Bearer ...` (not cookies), so API calls are not CSRF-exposed;
the cookie-based refresh endpoint is protected with a double-submit CSRF token.
"""

from typing import Callable, Iterable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import CollegeAdmin, Conductor, Role, User
from .security import decode_access_token

# What each role may do (documentation + enforced through require_roles on every route)
PERMISSIONS = {
    Role.PASSENGER: {"search_buses", "view_routes", "plan_journey", "buy_ticket", "view_own_tickets", "identity_verification"},
    Role.STUDENT: {"search_buses", "view_routes", "plan_journey", "buy_ticket", "view_own_tickets", "identity_verification",
                   "upload_pass", "view_verification_status", "use_student_eligibility"},
    Role.CONDUCTOR: {"scan_tickets", "validate_tickets", "view_assignment", "view_trip"},
    Role.COLLEGE_ADMIN: {"verify_own_college_students", "approve_reject_passes", "view_own_college_documents"},
    Role.SUPER_ADMIN: {"*"},
}

TRAVELLER_ROLES = (Role.PASSENGER, Role.STUDENT)


def get_current_user(request: Request, db: Session = Depends(get_db, scope="function")) -> User:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    payload = decode_access_token(header.split(" ", 1)[1].strip())
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account not found or disabled.")
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    allowed = set(roles)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
        return user

    return dependency


def college_scope(user: User, db: Session) -> str:
    """College id the admin is bound to. College admins can only ever act inside this college."""
    binding = db.get(CollegeAdmin, user.id)
    if not binding:
        raise HTTPException(status_code=403, detail="College administrator is not bound to a college.")
    from .models import College, CollegeStatus

    college = db.get(College, binding.college_id)
    if not college or college.status != CollegeStatus.APPROVED or not college.is_active:
        raise HTTPException(status_code=403, detail="Your college is not currently approved on Namma Bus.")
    return binding.college_id


def conductor_record(user: User, db: Session) -> Conductor:
    rec = db.get(Conductor, user.id)
    if not rec:
        raise HTTPException(status_code=403, detail="Conductor profile not found.")
    return rec


def has_permission(role: Role, permission: str) -> bool:
    perms: Iterable[str] = PERMISSIONS.get(role, set())
    return "*" in perms or permission in perms
