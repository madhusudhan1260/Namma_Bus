"""Audit logging. Details must never contain passwords, OTPs, tokens, Aadhaar data or biometrics."""

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .models import AuditLog, User

_FORBIDDEN_KEYS = {"password", "otp", "code", "token", "refresh_token", "aadhaar", "image", "face", "secret", "pin"}


def audit(
    db: Session,
    action: str,
    actor: Optional[User] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
    result: str = "SUCCESS",
    user_agent: Optional[str] = None,
) -> None:
    """Record who did what to which resource, and the outcome (SUCCESS | FAILURE | DENIED)."""
    safe = {k: v for k, v in (details or {}).items() if k.lower() not in _FORBIDDEN_KEYS}
    if result == "SUCCESS" and any(w in action for w in ("FAILED", "DENIED", "WRONG", "REUSE")):
        result = "FAILURE"
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_role=actor.role.value if actor else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=safe or None,
            ip_address=ip,
            result=result,
            user_agent=(user_agent or "")[:200] or None,
        )
    )
