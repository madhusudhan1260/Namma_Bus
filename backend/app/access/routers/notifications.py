"""In-app notifications for the signed-in user (any role)."""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Notification, User
from ..notifications import generate_due, notification_view
from ..rbac import get_current_user

router = APIRouter(tags=["Access: Notifications"])


@router.get("/notifications")
def my_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    generate_due(db, user)
    db.flush()
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id)
                      .order_by(Notification.created_at.desc()).limit(50)).all()
    unread = db.scalar(select(func.count()).select_from(Notification)
                       .where(Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    return {"notifications": [notification_view(n) for n in rows], "unread": unread}


class MarkRead(BaseModel):
    ids: Optional[List[str]] = Field(default=None, max_length=100)
    all: bool = False


@router.post("/notifications/read")
def mark_read(req: MarkRead, user: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    q = select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if not req.all:
        q = q.where(Notification.id.in_(req.ids or []))
    now = datetime.now(timezone.utc)
    rows = db.scalars(q).all()
    for n in rows:
        n.read_at = now
    return {"marked": len(rows)}
