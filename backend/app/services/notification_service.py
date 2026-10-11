from datetime import datetime, timezone
from typing import List, Optional
import uuid

from ..models.transit import NotificationEvent
from .alert_service import alert_service


class NotificationService:
    """
    Local notification event abstraction for NammaBlr.
    Prepared for future Expo Notifications integration without generating unsolicited push events.
    Supports event types: approaching_bus, service_alert, journey_update, feed_recovery.
    """

    def __init__(self):
        self._events: List[NotificationEvent] = [
            NotificationEvent(
                id="notif-1",
                event_type="service_alert",
                title="ORR Metro Construction Slowdown",
                message="8-12 min delay projected near Silk Board on 500D corridor.",
                route_number="500D",
                stop_name="Central Silk Board Junction",
                severity="WARNING",
            ),
            NotificationEvent(
                id="notif-2",
                event_type="approaching_bus",
                title="Bus 500D Approaching",
                message="Bus 500D is 2 stops away (~4 min ETA) from Silk Board.",
                route_number="500D",
                stop_name="Central Silk Board Junction",
                severity="INFO",
            ),
        ]

    def create_event(
        self,
        event_type: str,
        title: str,
        message: str,
        route_number: Optional[str] = None,
        stop_name: Optional[str] = None,
        severity: str = "INFO",
    ) -> NotificationEvent:
        event = NotificationEvent(
            id=f"notif-{uuid.uuid4().hex[:8]}",
            event_type=event_type,
            title=title,
            message=message,
            route_number=route_number,
            stop_name=stop_name,
            severity=severity,
            timestamp=datetime.now(timezone.utc),
        )
        self._events.insert(0, event)
        # Keep maximum 50 events in memory
        if len(self._events) > 50:
            self._events = self._events[:50]
        return event

    def create_crowd_alert(
        self,
        route_number: str,
        crowd_level: str,
        is_simulated: bool = True,
    ) -> Optional[NotificationEvent]:
        """Creates a crowd level change notification with deduplication."""
        # Deduplication: check if an alert for this route and crowd_level was recently created
        now = datetime.now(timezone.utc)
        for existing in self._events:
            if (
                existing.event_type == "crowd_alert"
                and existing.route_number
                and existing.route_number.upper() == route_number.upper()
                and (now - existing.timestamp).total_seconds() < 300  # 5 min window
            ):
                return None

        label = "SIMULATED CROWD DATA: " if is_simulated else ""
        event = self.create_event(
            event_type="crowd_alert",
            title=f"Crowd Alert: Route {route_number}",
            message=f"{label}Crowd level increased to {crowd_level.capitalize()} on your corridor.",
            route_number=route_number,
            severity="WARNING" if crowd_level.upper() in ["HIGH", "VERY_HIGH"] else "INFO",
        )
        from .metrics_service import metrics_service
        metrics_service.crowd_alerts += 1
        return event

    def create_incident_alert(
        self,
        route_number: str,
        incident_title: str,
        description: Optional[str] = None,
        severity: str = "WARNING",
        is_simulated: bool = True,
        stop_name: Optional[str] = None,
    ) -> Optional[NotificationEvent]:
        """Creates an incident notification with 5-minute deduplication window."""
        now = datetime.now(timezone.utc)
        for existing in self._events:
            if (
                existing.event_type == "incident_alert"
                and existing.route_number
                and existing.route_number.upper() == route_number.upper()
                and (now - existing.timestamp).total_seconds() < 300  # 5 min window
            ):
                return None

        label = "SIMULATED TRANSIT ALERT: " if is_simulated else ""
        event = self.create_event(
            event_type="incident_alert",
            title=f"Service Advisory: Route {route_number}",
            message=f"{label}{description or incident_title}",
            route_number=route_number,
            stop_name=stop_name,
            severity=severity,
        )
        from .metrics_service import metrics_service
        metrics_service.incident_alerts += 1
        return event

    def get_events(
        self,
        route_number: Optional[str] = None,
        limit: int = 20,
    ) -> List[NotificationEvent]:
        events = self._events
        if route_number:
            events = [e for e in events if e.route_number and e.route_number.upper() == route_number.upper()]
        return events[:limit]

    def reset(self):
        self.__init__()


notification_service = NotificationService()
