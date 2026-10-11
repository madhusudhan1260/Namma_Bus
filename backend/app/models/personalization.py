from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class CommuterPreferencesDto(BaseModel):
    language: str = "EN"
    bus_preference: str = "All"
    accessibility_priority: bool = False
    wheelchair_required: bool = False
    low_floor_preferred: bool = False
    reduced_walking_preferred: bool = False
    senior_friendly_preferred: bool = False
    audio_guidance_enabled: bool = False
    high_contrast_enabled: bool = False
    large_text_enabled: bool = False
    frequent_routes_enabled: bool = True
    arrival_notifications_enabled: bool = True
    service_alerts_enabled: bool = True
    saved_journeys_enabled: bool = True


class SavedJourneyDto(BaseModel):
    id: str
    name: Optional[str] = None
    origin: str
    destination: str
    preferred_bus_type: Optional[str] = "All"
    preferred_departure_time: Optional[str] = None
    notifications_enabled: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    has_active_incident: bool = False
    incident_advisory: Optional[str] = None


class SavedJourneyCreateDto(BaseModel):
    name: Optional[str] = None
    origin: str
    destination: str
    preferred_bus_type: Optional[str] = "All"
    preferred_departure_time: Optional[str] = None
    notifications_enabled: bool = True


class FavoriteRouteDto(BaseModel):
    route_number: str
    destination: Optional[str] = None
    bus_type: Optional[str] = "BMTC Ordinary"
    is_favorite: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    has_active_incident: bool = False
    incident_advisory: Optional[str] = None


class FavoriteRouteCreateDto(BaseModel):
    route_number: str
    destination: Optional[str] = None
    bus_type: Optional[str] = "BMTC Ordinary"


class ArrivalReminderDto(BaseModel):
    id: str
    route_number: str
    stop_name: str
    minutes_before: int = 10  # 5, 10, or 15
    target_eta_minutes: int
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active: bool = True
    disclosure: str = "Arrival reminders use available transit data and may be unavailable when realtime telemetry is not connected."


class ArrivalReminderCreateDto(BaseModel):
    route_number: str
    stop_name: str
    minutes_before: int = 10
    target_eta_minutes: int = 15


class NotificationItemDto(BaseModel):
    id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    category: str  # ARRIVALS, SERVICE ALERTS, SYSTEM, TICKETS
    title: str
    description: str
    read: bool = False
    route_number: Optional[str] = None
    severity: Optional[str] = "INFO"  # INFO, WARNING, SEVERE
    # Phase 41 (master spec) notification center metadata — all optional for backward compatibility
    event_type: Optional[str] = None
    priority: Optional[str] = "NORMAL"  # LOW | NORMAL | HIGH | CRITICAL
    source: Optional[str] = "SYSTEM"  # VERIFIED_REALTIME | GTFS_RT_ESTIMATE | HISTORICAL_ESTIMATE | SIMULATED | UNAVAILABLE | OFFLINE_CACHED | SYSTEM
    dedup_key: Optional[str] = None
    expires_at: Optional[str] = None
