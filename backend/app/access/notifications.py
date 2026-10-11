"""
In-app notifications (no paid SMS). Stored in PostgreSQL, pushed live to the user's own WebSocket topic
(user:<id>) after the transaction commits, and de-duplicated with a per-user key so nothing is sent twice.

Each notification carries a `kind` and a few ids/values in `data`; the app renders the text in the user's
language from the kind. `title`/`body` hold the English text as a fallback. No personal data of anyone else.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Notification, Role, StudentPass, StudentStatus, StudentVerification, User
from .realtime import publish_after_commit

PASS_EXPIRY_WARNING_DAYS = 7


def notification_view(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "data": n.data or {},
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "read": n.read_at is not None}


def notify(db: Session, user_id: Optional[str], kind: str, title: str, body: str, data: Optional[dict] = None,
           dedupe_key: Optional[str] = None) -> Optional[Notification]:
    if not user_id:
        return None
    if dedupe_key and db.scalars(select(Notification.id).where(Notification.user_id == user_id,
                                                               Notification.dedupe_key == dedupe_key)).first():
        return None
    n = Notification(user_id=user_id, kind=kind, title=title[:140], body=body[:400], data=data or None, dedupe_key=dedupe_key,
                     created_at=datetime.now(timezone.utc))
    try:
        with db.begin_nested():
            db.add(n)
            db.flush()
    except IntegrityError:
        return None  # a concurrent request created the same notification
    publish_after_commit(db, f"notification:{n.id}", lambda: ([f"user:{user_id}"], {"type": "NOTIFICATION", "notification": notification_view(n)}))
    return n


def generate_due(db: Session, user: User) -> None:
    """Notifications that depend on time rather than an action: bus pass about to expire (students) and the
    college's waiting queue (college verifiers, at most once a day)."""
    today = datetime.now(timezone.utc).date()
    if user.role == Role.STUDENT:
        sp = db.scalars(select(StudentPass).where(StudentPass.student_id == user.id, StudentPass.status == StudentStatus.APPROVED)
                        .order_by(StudentPass.created_at.desc())).first()
        if sp and sp.expiry_date and today <= sp.expiry_date <= today + timedelta(days=PASS_EXPIRY_WARNING_DAYS):
            days = (sp.expiry_date - today).days
            notify(db, user.id, "PASS_EXPIRING", "Your bus pass expires soon",
                   f"Your student bus pass expires in {days} day(s) ({sp.expiry_date.isoformat()}).",
                   {"days": days, "expiry_date": sp.expiry_date.isoformat()}, f"pass-expiring-{sp.id}")
    if user.role == Role.COLLEGE_ADMIN:
        from .rbac import college_scope

        try:
            college_id = college_scope(user, db)
        except Exception:
            return
        waiting = db.scalar(select(func.count()).select_from(StudentVerification)
                            .where(StudentVerification.college_id == college_id, StudentVerification.status == StudentStatus.PENDING)) or 0
        if waiting:
            notify(db, user.id, "COLLEGE_QUEUE", "Student applications waiting",
                   f"{waiting} student application(s) are waiting for verification.", {"count": waiting},
                   f"college-queue-{today.isoformat()}")
