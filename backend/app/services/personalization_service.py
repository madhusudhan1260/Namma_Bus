from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional
import uuid

from ..models.personalization import (
    CommuterPreferencesDto,
    SavedJourneyDto,
    SavedJourneyCreateDto,
    FavoriteRouteDto,
    FavoriteRouteCreateDto,
    ArrivalReminderDto,
    ArrivalReminderCreateDto,
    NotificationItemDto,
)
from .incident_impact_service import incident_impact_service
from .notification_center_service import notification_center_service


class PersonalizationService:
    """
    Manages commuter personalization, saved journeys, favorite routes, arrival reminders,
    and in-app notification center state.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        """Restores default seed state for deterministic demo scenarios."""
        with getattr(self, "_lock", threading.Lock()):
            self._preferences = CommuterPreferencesDto(
                language="EN",
                bus_preference="All",
                accessibility_priority=False,
                wheelchair_required=False,
                low_floor_preferred=False,
                reduced_walking_preferred=False,
                senior_friendly_preferred=False,
                audio_guidance_enabled=False,
                high_contrast_enabled=False,
                large_text_enabled=False,
                frequent_routes_enabled=True,
                arrival_notifications_enabled=True,
                service_alerts_enabled=True,
                saved_journeys_enabled=True,
            )

            now_iso = datetime.now(timezone.utc).isoformat()

            self._saved_journeys: Dict[str, SavedJourneyDto] = {
                "journey-1": SavedJourneyDto(
                    id="journey-1",
                    name="Home → Majestic",
                    origin="Central Silk Board Junction",
                    destination="Majestic (Kempegowda Bus Station)",
                    preferred_bus_type="All",
                    preferred_departure_time="08:30 AM",
                    notifications_enabled=True,
                    created_at=now_iso,
                ),
                "journey-2": SavedJourneyDto(
                    id="journey-2",
                    name="Home → Silk Board",
                    origin="HSR Layout Sector 2",
                    destination="Central Silk Board Junction",
                    preferred_bus_type="BMTC Ordinary",
                    preferred_departure_time="09:15 AM",
                    notifications_enabled=True,
                    created_at=now_iso,
                ),
                "journey-3": SavedJourneyDto(
                    id="journey-3",
                    name="Office → Majestic",
                    origin="Ecospace Bellandur",
                    destination="Majestic (Kempegowda Bus Station)",
                    preferred_bus_type="Vajra Electric",
                    preferred_departure_time="06:00 PM",
                    notifications_enabled=False,
                    created_at=now_iso,
                ),
            }

            self._favorite_routes: Dict[str, FavoriteRouteDto] = {
                "500D": FavoriteRouteDto(
                    route_number="500D",
                    destination="Hebbal",
                    bus_type="Vajra Electric",
                    is_favorite=True,
                    created_at=now_iso,
                ),
                "356": FavoriteRouteDto(
                    route_number="356",
                    destination="Electronic City Wipro Gate",
                    bus_type="BMTC Ordinary",
                    is_favorite=True,
                    created_at=now_iso,
                ),
            }

            self._reminders: Dict[str, ArrivalReminderDto] = {}

            seed_notifications: List[NotificationItemDto] = [
                NotificationItemDto(
                    id="notif-1",
                    timestamp=now_iso,
                    category="ARRIVALS",
                    title="Bus 500D Approaching",
                    description="500D is estimated to arrive in 8 minutes at Silk Board Junction.",
                    read=False,
                    route_number="500D",
                    severity="INFO",
                ),
                NotificationItemDto(
                    id="notif-2",
                    timestamp=now_iso,
                    category="SERVICE ALERTS",
                    title="Service Alert: Route 500D",
                    description="Metro construction near Silk Board may cause 8-12 min delays on Route 500D.",
                    read=False,
                    route_number="500D",
                    severity="WARNING",
                ),
                NotificationItemDto(
                    id="notif-3",
                    timestamp=now_iso,
                    category="SYSTEM",
                    title="Transit Telemetry Status",
                    description="Transit feed is currently simulated. Authorized BMTC feed ready for configuration.",
                    read=True,
                    severity="INFO",
                ),
                NotificationItemDto(
                    id="notif-4",
                    timestamp=now_iso,
                    category="TICKETS",
                    title="Digital Demo Pass Active",
                    description="Your demo ticket has been verified by the conductor handheld scanner.",
                    read=True,
                    severity="INFO",
                ),
            ]
            # Demo seed items come from the simulated corridor, so they are labelled SIMULATED.
            for item in seed_notifications:
                item.source = "SIMULATED" if item.category != "SYSTEM" else "SYSTEM"
            notification_center_service.reset(seed_notifications)

    # --- Preferences ---
    def get_preferences(self) -> CommuterPreferencesDto:
        with self._lock:
            return self._preferences.model_copy()

    def update_preferences(self, prefs: CommuterPreferencesDto) -> CommuterPreferencesDto:
        with self._lock:
            self._preferences = prefs.model_copy()
            return self._preferences.model_copy()

    # --- Saved Journeys ---
    def get_saved_journeys(self) -> List[SavedJourneyDto]:
        with self._lock:
            result = []
            for j in self._saved_journeys.values():
                j_copy = j.model_copy()
                is_aff, adv = incident_impact_service.assess_saved_journey(j_copy)
                j_copy.has_active_incident = is_aff
                j_copy.incident_advisory = adv
                result.append(j_copy)
            return result

    def create_saved_journey(self, req: SavedJourneyCreateDto) -> SavedJourneyDto:
        with self._lock:
            jid = f"journey-{uuid.uuid4().hex[:6]}"
            name = req.name or f"{req.origin.split(',')[0]} → {req.destination.split(',')[0]}"
            journey = SavedJourneyDto(
                id=jid,
                name=name,
                origin=req.origin,
                destination=req.destination,
                preferred_bus_type=req.preferred_bus_type or "All",
                preferred_departure_time=req.preferred_departure_time,
                notifications_enabled=req.notifications_enabled,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            is_aff, adv = incident_impact_service.assess_saved_journey(journey)
            journey.has_active_incident = is_aff
            journey.incident_advisory = adv
            self._saved_journeys[jid] = journey
            return journey

    def delete_saved_journey(self, journey_id: str) -> bool:
        with self._lock:
            if journey_id in self._saved_journeys:
                del self._saved_journeys[journey_id]
                return True
            return False

    # --- Favorite Routes ---
    def get_favorite_routes(self) -> List[FavoriteRouteDto]:
        with self._lock:
            result = []
            for r in self._favorite_routes.values():
                r_copy = r.model_copy()
                is_aff, adv, _ = incident_impact_service.assess_favorite_route(r_copy.route_number)
                r_copy.has_active_incident = is_aff
                r_copy.incident_advisory = adv
                result.append(r_copy)
            return result

    def add_favorite_route(self, req: FavoriteRouteCreateDto) -> FavoriteRouteDto:
        with self._lock:
            rnum = req.route_number.strip().upper()
            fav = FavoriteRouteDto(
                route_number=rnum,
                destination=req.destination or "Bengaluru Corridor",
                bus_type=req.bus_type or "BMTC Ordinary",
                is_favorite=True,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._favorite_routes[rnum] = fav
            return fav

    def remove_favorite_route(self, route_number: str) -> bool:
        with self._lock:
            rnum = route_number.strip().upper()
            if rnum in self._favorite_routes:
                del self._favorite_routes[rnum]
                return True
            return False

    # --- Arrival Reminders ---
    def create_reminder(self, req: ArrivalReminderCreateDto) -> ArrivalReminderDto:
        with self._lock:
            rid = f"rem-{uuid.uuid4().hex[:6]}"
            reminder = ArrivalReminderDto(
                id=rid,
                route_number=req.route_number.strip().upper(),
                stop_name=req.stop_name,
                minutes_before=req.minutes_before,
                target_eta_minutes=req.target_eta_minutes,
                created_at=datetime.now(timezone.utc).isoformat(),
                active=True,
            )
            self._reminders[rid] = reminder

            # Also generate a corresponding notification item
            notif = NotificationItemDto(
                id=f"notif-{uuid.uuid4().hex[:6]}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                category="ARRIVALS",
                title=f"Reminder Set for {reminder.route_number}",
                description=f"You will be alerted {reminder.minutes_before} min before arrival at {reminder.stop_name}.",
                read=False,
                route_number=reminder.route_number,
                severity="INFO",
            )
            notification_center_service.insert_raw(notif)
            return reminder

    def get_reminders(self) -> List[ArrivalReminderDto]:
        with self._lock:
            return list(self._reminders.values())

    # --- Notification Center ---
    def get_notifications(self, category: Optional[str] = None) -> List[NotificationItemDto]:
        return notification_center_service.list(category=category)

    def add_notification(self, category: str, title: str, description: str, severity: str = "INFO") -> NotificationItemDto:
        """Adds a notification center item for a real state transition (Phase 41 identity events)."""
        priority = {"WARNING": "HIGH", "SEVERE": "CRITICAL"}.get(severity, "NORMAL")
        item, _ = notification_center_service.publish(
            "IDENTITY", title, description, category=category, priority=priority, source="SYSTEM",
        )
        return item

    def mark_notification_read(self, notif_id: str) -> bool:
        return notification_center_service.mark_read(notif_id)

personalization_service = PersonalizationService()
