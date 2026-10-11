from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class SafetyStatus(str, Enum):
    NORMAL = "NORMAL"
    ATTENTION = "ATTENTION"
    ASSISTANCE_NEEDED = "ASSISTANCE_NEEDED"
    OFFLINE = "OFFLINE"


class SafetyEventType(str, Enum):
    JOURNEY_STARTED = "JOURNEY_STARTED"
    JOURNEY_DELAYED = "JOURNEY_DELAYED"
    TRANSFER_MISSED = "TRANSFER_MISSED"
    DESTINATION_APPROACHING = "DESTINATION_APPROACHING"
    DESTINATION_PASSED = "DESTINATION_PASSED"
    VEHICLE_TELEMETRY_LOST = "VEHICLE_TELEMETRY_LOST"
    ROUTE_DISRUPTION = "ROUTE_DISRUPTION"
    USER_REQUESTED_ASSISTANCE = "USER_REQUESTED_ASSISTANCE"
    JOURNEY_COMPLETED = "JOURNEY_COMPLETED"
    SAFETY_CHECK = "SAFETY_CHECK"


class ShareState(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SafetyEvent(BaseModel):
    event_id: str
    journey_id: str
    event_type: str
    status: str
    route_number: Optional[str] = None
    current_stop: Optional[str] = None
    next_stop: Optional[str] = None
    destination: Optional[str] = None
    source: str = "simulated"
    disclosure: str = "Safety status is based on the available transit data."
    created_at: datetime = Field(default_factory=datetime.utcnow)
    details: Optional[str] = None


class SafetyContact(BaseModel):
    contact_id: str
    display_name: str
    masked_contact: str
    relationship: str
    enabled: bool = True


class SafetyAssessment(BaseModel):
    journey_id: str
    safety_status: str = "NORMAL"
    safety_message: str = "Journey progressing normally"
    route_number: Optional[str] = None
    current_stop: Optional[str] = None
    next_stop: Optional[str] = None
    destination: Optional[str] = None
    eta_minutes: Optional[int] = None
    assistance_requested: bool = False
    assistance_requested_at: Optional[datetime] = None
    telemetry_health: str = "HEALTHY"
    data_source: str = "simulated"
    disruption_active: bool = False
    transfer_attention: bool = False
    last_safety_check_at: Optional[datetime] = None
    disclosure: str = "Safety status is based on the available transit data."
    safety_events_count: int = 0
    is_sharing_active: bool = False


class AssistanceRequest(BaseModel):
    journey_id: str
    reason: Optional[str] = "User requested assistance"
    current_stop: Optional[str] = None


class AssistanceResponse(BaseModel):
    success: bool
    journey_id: str
    safety_status: str
    message: str
    assistance_requested_at: datetime = Field(default_factory=datetime.utcnow)
    disclosure: str = "Emergency assistance information is for guidance only."


class SafetyCheckRequest(BaseModel):
    journey_id: str


class SafetyCheckResponse(BaseModel):
    success: bool
    journey_id: str
    checked_at: datetime = Field(default_factory=datetime.utcnow)
    safety_status: str
    message: str
    disclosure: str = "Safety status is based on the available transit data."


class JourneyShareStartRequest(BaseModel):
    journey_id: str
    duration_minutes: int = 30  # 15, 30, 60


class JourneyShareStopRequest(BaseModel):
    journey_id: str


class JourneyShareResponse(BaseModel):
    journey_id: str
    share_token: str
    share_state: str
    duration_minutes: int
    expires_at: datetime
    route_number: Optional[str] = None
    destination: Optional[str] = None
    data_source: str = "simulated"
    disclosure: str = "Your journey location is not shared automatically."
    confirmation_text: str = "Journey sharing is active only after explicit user confirmation."


class JourneyShareStatusResponse(BaseModel):
    journey_id: str
    share_state: str
    share_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    remaining_minutes: Optional[int] = None
    route_number: Optional[str] = None
    current_stop: Optional[str] = None
    destination: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    data_source: str = "simulated"
    disclosure: str = "Your journey location is not shared automatically."


class NearbySafetyTransitItem(BaseModel):
    item_type: str  # stop | route | transfer_hub | accessible_stop
    name: str
    distance_meters: int
    details: str
    route_numbers: List[str] = Field(default_factory=list)


class NearbySafetyResponse(BaseModel):
    nearby_items: List[NearbySafetyTransitItem]
    emergency_service_disclosure: str = "Live emergency service availability is unavailable."
    source_disclosure: str = "Safety status is based on the available transit data."


class SafetyDemoOverrideRequest(BaseModel):
    scenario: str  # normal_journey | telemetry_lost | missed_destination | missed_transfer | disruption_attention | assistance_requested | journey_share_active | journey_share_expired
    journey_id: Optional[str] = None
