"""
Phase 41 (master spec): Smart Notification Center.

Single store for in-app notification center items (the list served by GET /api/notifications).
PersonalizationService delegates its notification storage here so older endpoints keep working.

Features: categories, priority, source disclosure, timestamps, read/unread, expiration,
sliding-window deduplication and a burst cap to prevent notification spam.
Notifications are only published for real state transitions detected by the backend; this
service never invents transit events.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from ..models.personalization import NotificationItemDto

# event_type -> (category, default priority, dedup window seconds)
EVENT_TYPES: Dict[str, Tuple[str, str, int]] = {
    "BUS_APPROACHING": ("ARRIVALS", "HIGH", 300),
    "GET_READY_TO_EXIT": ("ARRIVALS", "HIGH", 300),
    "DESTINATION_APPROACHING": ("ARRIVALS", "NORMAL", 300),
    "DESTINATION_REACHED": ("ARRIVALS", "NORMAL", 600),
    "DESTINATION_PASSED": ("ARRIVALS", "CRITICAL", 600),
    "TRANSFER_APPROACHING": ("TRANSFERS", "NORMAL", 300),
    "TRANSFER_READY": ("TRANSFERS", "HIGH", 300),
    "CONNECTING_BUS_APPROACHING": ("TRANSFERS", "HIGH", 300),
    "TRANSFER_MISSED": ("TRANSFERS", "CRITICAL", 600),
    "SERVICE_DISRUPTION": ("SERVICE ALERTS", "HIGH", 900),
    "ROUTE_DELAY": ("SERVICE ALERTS", "NORMAL", 900),
    "CROWD_CHANGE": ("CROWD", "LOW", 900),
    "ACCESSIBILITY_CHANGE": ("ACCESSIBILITY", "HIGH", 900),
    "SAVED_JOURNEY_CHANGE": ("PERSONAL", "LOW", 120),
    "FAVORITE_ROUTE_CHANGE": ("PERSONAL", "LOW", 120),
    "TICKET_PURCHASED": ("TICKETS", "NORMAL", 5),
    "TICKET_EXPIRED": ("TICKETS", "NORMAL", 3600),
    "PAYMENT_STATUS": ("PAYMENTS", "NORMAL", 5),
    "IDENTITY": ("SYSTEM", "NORMAL", 5),
    "SYSTEM": ("SYSTEM", "LOW", 60),
    "REMINDER": ("ARRIVALS", "NORMAL", 5),
}

PRIORITY_TO_SEVERITY = {"LOW": "INFO", "NORMAL": "INFO", "HIGH": "WARNING", "CRITICAL": "SEVERE"}

SOURCES = {
    "VERIFIED_REALTIME",
    "GTFS_RT_ESTIMATE",
    "HISTORICAL_ESTIMATE",
    "SIMULATED",
    "UNAVAILABLE",
    "OFFLINE_CACHED",
    "SYSTEM",
}

MAX_ITEMS = 200
BURST_WINDOW = timedelta(seconds=60)
BURST_LIMIT = 30  # max new notifications per minute across all categories


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NotificationCenterService:
    def __init__(self):
        self._lock = threading.RLock()
        self._items: List[NotificationItemDto] = []
        self._last_seen: Dict[str, datetime] = {}
        self._recent_publish: List[datetime] = []
        self.stats = {"published": 0, "suppressed_duplicates": 0, "suppressed_burst": 0, "expired_hidden": 0, "deleted": 0}

    # -- lifecycle ---------------------------------------------------------

    def reset(self, seed: Optional[List[NotificationItemDto]] = None):
        with self._lock:
            self._items = list(seed or [])
            self._last_seen.clear()
            self._recent_publish.clear()
            for k in self.stats:
                self.stats[k] = 0

    # -- publishing ----------------------------------------------------------

    def publish(
        self,
        event_type: str,
        title: str,
        description: str,
        *,
        source: str = "SYSTEM",
        priority: Optional[str] = None,
        category: Optional[str] = None,
        route_number: Optional[str] = None,
        dedup_key: Optional[str] = None,
        dedup_window_seconds: Optional[int] = None,
        ttl_minutes: Optional[int] = 24 * 60,
    ) -> Tuple[Optional[NotificationItemDto], bool]:
        """
        Returns (item, created). created=False means the event was suppressed as a duplicate
        (sliding window: every repeat within the window extends it) or by the burst cap.
        """
        default_cat, default_prio, default_window = EVENT_TYPES.get(event_type, ("SYSTEM", "NORMAL", 60))
        prio = priority or default_prio
        src = source if source in SOURCES else "SYSTEM"
        key = dedup_key or f"{event_type}:{route_number or ''}:{title}"
        window = timedelta(seconds=dedup_window_seconds if dedup_window_seconds is not None else default_window)
        now = _now()

        with self._lock:
            last = self._last_seen.get(key)
            if last is not None and now - last < window:
                self._last_seen[key] = now  # sliding window
                self.stats["suppressed_duplicates"] += 1
                return None, False

            self._recent_publish = [t for t in self._recent_publish if now - t < BURST_WINDOW]
            if len(self._recent_publish) >= BURST_LIMIT and prio != "CRITICAL":
                self.stats["suppressed_burst"] += 1
                return None, False

            item = NotificationItemDto(
                id=f"notif-{uuid.uuid4().hex[:10]}",
                timestamp=now.isoformat(),
                category=category or default_cat,
                title=title,
                description=description,
                read=False,
                route_number=route_number,
                severity=PRIORITY_TO_SEVERITY.get(prio, "INFO"),
                event_type=event_type,
                priority=prio,
                source=src,
                dedup_key=key,
                expires_at=(now + timedelta(minutes=ttl_minutes)).isoformat() if ttl_minutes else None,
            )
            self._items.insert(0, item)
            del self._items[MAX_ITEMS:]
            self._last_seen[key] = now
            self._recent_publish.append(now)
            self.stats["published"] += 1
            return item, True

    def insert_raw(self, item: NotificationItemDto) -> NotificationItemDto:
        """Legacy insertion path (arrival reminders) — keeps the item exactly as built by the caller."""
        with self._lock:
            self._items.insert(0, item)
            del self._items[MAX_ITEMS:]
            return item

    # -- queries -------------------------------------------------------------

    @staticmethod
    def _expired(item: NotificationItemDto, now: datetime) -> bool:
        if not item.expires_at:
            return False
        try:
            return datetime.fromisoformat(item.expires_at) <= now
        except ValueError:
            return False

    def list(self, category: Optional[str] = None, unread_only: bool = False, include_expired: bool = False) -> List[NotificationItemDto]:
        now = _now()
        with self._lock:
            items = list(self._items)
        if not include_expired:
            items = [n for n in items if not self._expired(n, now)]
        if category:
            cat = category.strip().upper()
            items = [n for n in items if n.category.upper() == cat]
        if unread_only:
            items = [n for n in items if not n.read]
        return items

    def unread_count(self) -> int:
        return len(self.list(unread_only=True))

    def mark_read(self, notif_id: str) -> bool:
        with self._lock:
            for n in self._items:
                if n.id == notif_id:
                    n.read = True
                    return True
        return False

    def mark_all_read(self) -> int:
        with self._lock:
            count = 0
            for n in self._items:
                if not n.read:
                    n.read = True
                    count += 1
            return count

    def delete(self, notif_id: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [n for n in self._items if n.id != notif_id]
            deleted = len(self._items) < before
            if deleted:
                self.stats["deleted"] += 1
            return deleted

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return {**self.stats, "total": len(self._items), "unread": sum(1 for n in self._items if not n.read)}


notification_center_service = NotificationCenterService()
