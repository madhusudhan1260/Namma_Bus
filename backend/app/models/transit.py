from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .realtime import TrackedVehicle


class Coordinate(BaseModel):
    latitude: float
    longitude: float


class AccessibilityStatus(str, Enum):
    ACCESSIBLE = "ACCESSIBLE"
    NOT_ACCESSIBLE = "NOT_ACCESSIBLE"
    UNKNOWN = "UNKNOWN"


class AccessibilityMetadata(BaseModel):
    status: str = "UNKNOWN"  # "ACCESSIBLE" | "NOT_ACCESSIBLE" | "UNKNOWN"
    wheelchair_accessible: Optional[bool] = None
    low_floor_bus: Optional[bool] = None
    boarding_assistance_available: bool = False
    accessible_stop: bool = False
    audio_announcements: bool = False
    visual_displays: bool = False
    accessibility_disclosure: str = "Accessibility information unavailable from the current transit data."
    accessibility_source: str = "simulated_corridor"


class CrowdStatus(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"
    UNKNOWN = "UNKNOWN"


class CrowdDataSource(str, Enum):
    VERIFIED_APC = "VERIFIED_APC"
    GTFS_RT_ESTIMATE = "GTFS_RT_ESTIMATE"
    HISTORICAL_ESTIMATE = "HISTORICAL_ESTIMATE"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


class SeatAvailabilityStatus(str, Enum):
    SEATS_LIKELY_AVAILABLE = "SEATS LIKELY AVAILABLE"
    LIMITED_SEATS = "LIMITED SEATS"
    STANDING_LIKELY = "STANDING LIKELY"
    VERY_CROWDED = "VERY CROWDED"
    UNKNOWN = "UNKNOWN"


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    DISRUPTION = "DISRUPTION"
    CRITICAL = "CRITICAL"


class IncidentType(str, Enum):
    SERVICE_DELAY = "SERVICE_DELAY"
    SERVICE_CANCELLATION = "SERVICE_CANCELLATION"
    ROUTE_DIVERSION = "ROUTE_DIVERSION"
    STOP_CLOSURE = "STOP_CLOSURE"
    STOP_RELOCATION = "STOP_RELOCATION"
    ROAD_INCIDENT = "ROAD_INCIDENT"
    TRAFFIC_DISRUPTION = "TRAFFIC_DISRUPTION"
    TRAFFIC_CONGESTION = "TRAFFIC_CONGESTION"
    WATERLOGGING = "WATERLOGGING"
    ROAD_WORK = "ROAD_WORK"
    BREAKDOWN = "BREAKDOWN"
    VIP_MOVEMENT = "VIP_MOVEMENT"
    WEATHER = "WEATHER"
    WEATHER_IMPACT = "WEATHER_IMPACT"
    VEHICLE_BREAKDOWN = "VEHICLE_BREAKDOWN"
    TRANSFER_RISK = "TRANSFER_RISK"
    GENERAL_ADVISORY = "GENERAL_ADVISORY"
    UNKNOWN = "UNKNOWN"


class IncidentSource(str, Enum):
    OFFICIAL_BMTC_ALERT = "OFFICIAL_BMTC_ALERT"
    AUTHORIZED_GTFS_RT = "AUTHORIZED_GTFS_RT"
    VERIFIED_SYSTEM = "VERIFIED_SYSTEM"
    SIMULATED = "SIMULATED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


class IncidentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    SCHEDULED = "SCHEDULED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class CrowdMetadata(BaseModel):
    crowd_status: str = "UNKNOWN"  # "LOW" | "MODERATE" | "HIGH" | "VERY_HIGH" | "UNKNOWN"
    occupancy_percentage: Optional[int] = None  # Strictly null when not legitimately available
    estimated_seat_availability: Optional[str] = "UNKNOWN"  # "SEATS LIKELY AVAILABLE" | "LIMITED SEATS" | "STANDING LIKELY" | "VERY CROWDED" | "UNKNOWN"
    standing_likelihood: Optional[str] = "UNKNOWN"  # "LOW" | "MODERATE" | "HIGH" | "UNKNOWN"
    source: str = "UNAVAILABLE"  # "VERIFIED_APC" | "GTFS_RT_ESTIMATE" | "HISTORICAL_ESTIMATE" | "SIMULATED" | "UNAVAILABLE"
    confidence: Optional[str] = "MEDIUM"  # "HIGH" | "MEDIUM" | "LOW"
    disclosure: str = "Passenger occupancy data is unavailable from the current feed."
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CrowdDetailsResponse(BaseModel):
    identifier: Optional[str] = None
    route_or_bus_id: Optional[str] = None
    stop_id: Optional[str] = None
    journey_id: Optional[str] = None
    crowd_status: str = "UNKNOWN"
    seat_status: str = "UNKNOWN"
    standing_likelihood: str = "UNKNOWN"
    occupancy_percentage: Optional[int] = None
    source: str = "UNAVAILABLE"
    confidence: str = "MEDIUM"
    disclosure: str = "Passenger occupancy data is unavailable from the current feed."
    explanation: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Incident(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    incident_type: IncidentType = IncidentType.SERVICE_DELAY
    severity: IncidentSeverity = IncidentSeverity.INFO
    status: IncidentStatus = IncidentStatus.ACTIVE
    source: IncidentSource = IncidentSource.SIMULATED
    affected_routes: List[str] = Field(default_factory=list)
    affected_route_numbers: List[str] = Field(default_factory=list)
    affected_stops: List[str] = Field(default_factory=list)
    affected_stop_names: List[str] = Field(default_factory=list)
    affected_bus_ids: List[str] = Field(default_factory=list)
    affected_corridors: List[str] = Field(default_factory=list)
    corridor: Optional[str] = None
    start_time: Optional[datetime] = None
    started_at: Optional[datetime] = None
    expected_end_time: Optional[datetime] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_simulated: bool = True
    disclosure: str = "SIMULATED CORRIDOR ADVISORY"
    source_attribution_badge: str = "SIMULATED CORRIDOR ADVISORY"
    impact_level: str = "MODERATE"  # LOW | MODERATE | HIGH | CRITICAL
    expected_delay_minutes: int = 0
    alternative_route_advice: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def __init__(self, **data):
        # Sync route aliases
        if "affected_routes" in data and "affected_route_numbers" not in data:
            data["affected_route_numbers"] = data["affected_routes"]
        elif "affected_route_numbers" in data and "affected_routes" not in data:
            data["affected_routes"] = data["affected_route_numbers"]
        # Sync stop aliases
        if "affected_stops" in data and "affected_stop_names" not in data:
            data["affected_stop_names"] = data["affected_stops"]
        elif "affected_stop_names" in data and "affected_stops" not in data:
            data["affected_stops"] = data["affected_stop_names"]
        # Sync disclosure / badge
        if "disclosure" in data and "source_attribution_badge" not in data:
            data["source_attribution_badge"] = data["disclosure"]
        elif "source_attribution_badge" in data and "disclosure" not in data:
            data["disclosure"] = data["source_attribution_badge"]
        # Sync corridor
        if "affected_corridors" in data and data["affected_corridors"] and "corridor" not in data:
            data["corridor"] = data["affected_corridors"][0]
        elif "corridor" in data and "affected_corridors" not in data:
            data["affected_corridors"] = [data["corridor"]] if data["corridor"] else []
        super().__init__(**data)


class AlternativeJourneyComparison(BaseModel):
    route_number: str
    alternative_route: Optional[str] = None
    destination: str = ""
    additional_walking_meters: int = 0
    additional_walk_meters: int = 0
    additional_duration_minutes: int = 0
    additional_travel_time_minutes: int = 0
    transfers: int = 0
    transfers_required: int = 0
    fare_rupees: int = 0
    estimated_fare: int = 0
    crowd_status: str = "LOW"
    accessibility_status: str = "UNKNOWN"
    label: str = "Alternative available"
    recommendation_label: str = "Alternative available"
    summary: str = ""
    disclosure: str = "SIMULATED ALTERNATIVE ROUTE"

    def __init__(self, **data):
        if "route_number" in data and "alternative_route" not in data:
            data["alternative_route"] = data["route_number"]
        if "additional_walking_meters" in data and "additional_walk_meters" not in data:
            data["additional_walk_meters"] = data["additional_walking_meters"]
        if "additional_duration_minutes" in data and "additional_travel_time_minutes" not in data:
            data["additional_travel_time_minutes"] = data["additional_duration_minutes"]
        if "transfers" in data and "transfers_required" not in data:
            data["transfers_required"] = data["transfers"]
        if "fare_rupees" in data and "estimated_fare" not in data:
            data["estimated_fare"] = data["fare_rupees"]
        if "label" in data and "recommendation_label" not in data:
            data["recommendation_label"] = data["label"]
        super().__init__(**data)


class IncidentImpactAssessment(BaseModel):
    is_affected: bool = False
    has_disruption: bool = False
    incident_id: Optional[str] = None
    title: Optional[str] = None
    severity: Optional[str] = None
    source: Optional[str] = None
    message: Optional[str] = None
    disruption_summary: Optional[str] = None
    delay_estimate_minutes: int = 0
    advisory_label: Optional[str] = None
    source_attribution_badge: Optional[str] = None
    affected_entity: Optional[str] = None
    alternative_available: bool = False
    alternatives: List[AlternativeJourneyComparison] = Field(default_factory=list)
    incidents: List[Incident] = Field(default_factory=list)

    def __init__(self, **data):
        if "is_affected" in data and "has_disruption" not in data:
            data["has_disruption"] = data["is_affected"]
        elif "has_disruption" in data and "is_affected" not in data:
            data["is_affected"] = data["has_disruption"]
        if "message" in data and "disruption_summary" not in data:
            data["disruption_summary"] = data["message"]
        if "advisory_label" in data and "source_attribution_badge" not in data:
            data["source_attribution_badge"] = data["advisory_label"]
        super().__init__(**data)


class IncidentOverrideRequest(BaseModel):
    mode: str = "500d_disruption"  # none | 500d_disruption | 356_disruption | stop_closure | transfer_risk | multiple
    corridor: Optional[str] = None
    route_number: Optional[str] = None
    incident_type: Optional[str] = None
    severity: Optional[str] = None
    delay_minutes: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    clear: Optional[bool] = False


class IncidentDetailsResponse(BaseModel):
    incident: Incident
    affected_routes_count: int = 0
    affected_stops_count: int = 0
    source_attribution_label: str
    is_simulated: bool
    can_track_bus: bool = True
    can_view_route: bool = True
    disclosure: str


# ---------------------------------------------------------------------------
# Phase 38: Smart Predictive Commuter Intelligence Models
# ---------------------------------------------------------------------------

class PredictionDataSource(str, Enum):
    VERIFIED_REALTIME = "VERIFIED_REALTIME"
    GTFS_RT_ESTIMATE = "GTFS_RT_ESTIMATE"
    HISTORICAL_ESTIMATE = "HISTORICAL_ESTIMATE"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


class PredictionConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class PredictionType(str, Enum):
    ARRIVAL = "ARRIVAL"
    JOURNEY_DURATION = "JOURNEY_DURATION"
    CROWD = "CROWD"
    DELAY = "DELAY"
    TRANSFER_SUCCESS = "TRANSFER_SUCCESS"
    DESTINATION_ARRIVAL = "DESTINATION_ARRIVAL"


class CommuterPrediction(BaseModel):
    prediction_id: str
    prediction_type: str = "ARRIVAL"
    route_number: Optional[str] = None
    bus_id: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    predicted_eta_minutes: Optional[int] = None
    predicted_duration_minutes: Optional[int] = None
    predicted_crowd_status: Optional[str] = None
    predicted_seat_status: Optional[str] = None
    predicted_delay_minutes: Optional[int] = None
    confidence: str = "MEDIUM"  # HIGH | MEDIUM | LOW | UNKNOWN
    data_source: str = "HISTORICAL_ESTIMATE"  # VERIFIED_REALTIME | GTFS_RT_ESTIMATE | HISTORICAL_ESTIMATE | SIMULATED | UNAVAILABLE
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    valid_until: Optional[datetime] = None
    disclosure: str = "Estimated transit prediction based on Bengaluru corridor travel patterns."
    factors: List[str] = Field(default_factory=list)
    breakdown: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Phase 39: Smart Personalized Commuter & Route Recommendation Models
# ---------------------------------------------------------------------------

class RecommendationType(str, Enum):
    SAVED_JOURNEY = "SAVED_JOURNEY"
    FAVORITE_ROUTE = "FAVORITE_ROUTE"
    LOW_CROWD = "LOW_CROWD"
    ACCESSIBLE = "ACCESSIBLE"
    LOW_FARE = "LOW_FARE"
    FASTEST_ESTIMATE = "FASTEST_ESTIMATE"
    FEWER_TRANSFERS = "FEWER_TRANSFERS"
    SERVICE_ALTERNATIVE = "SERVICE_ALTERNATIVE"
    ARRIVAL_REMINDER = "ARRIVAL_REMINDER"
    DISRUPTION_RECOVERY = "DISRUPTION_RECOVERY"


class CommuterRecommendation(BaseModel):
    id: str
    type: str = "FASTEST_ESTIMATE"  # RecommendationType
    title: str
    description: str
    route_number: Optional[str] = None
    destination: Optional[str] = None
    reason: str
    comparison_factors: Dict[str, Any] = Field(default_factory=dict)
    data_source: str = "HISTORICAL_ESTIMATE"
    confidence: str = "MEDIUM"
    disclosure: str = "Factual comparative assessment avoiding subjective ranking."
    created_at: datetime = Field(default_factory=datetime.utcnow)
    action_route: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 40: Production Readiness, Resilience & Municipal Operations Models
# ---------------------------------------------------------------------------

class ModuleHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    OFFLINE = "OFFLINE"
    UNAVAILABLE = "UNAVAILABLE"
    STANDBY = "STANDBY"


class SystemModuleHealth(BaseModel):
    name: str
    status: str = "HEALTHY"
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: int = 10
    error_count: int = 0
    data_source: str = "simulated"
    disclosure: str


class FeedHealthDiagnostic(BaseModel):
    vehicle_positions_freshness_seconds: Optional[float] = None
    trip_updates_freshness_seconds: Optional[float] = None
    service_alerts_freshness_seconds: Optional[float] = None
    parser_errors: int = 0
    malformed_entities: int = 0
    duplicate_entities: int = 0
    rejected_coordinates: int = 0
    connection_failures: int = 0
    retry_count: int = 0
    backoff_state: str = "IDLE"  # IDLE | RETRYING | BACKOFF | SUSPENDED
    feed_status: str = "READY_NOT_CONFIGURED"


class DataQualityAssessment(BaseModel):
    data_quality_score: int = 85  # 0 to 100
    feed_freshness_score: int = 90
    source_authorization_score: int = 80
    telemetry_availability_score: int = 85
    schema_validity_score: int = 100
    missing_fields_count: int = 0
    parser_errors_count: int = 0
    last_known_good_age_seconds: Optional[float] = 0
    diagnostic_statement: str = "Diagnostic assessment score only — never used to rank commuter routes."
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DiagnosticEvent(BaseModel):
    id: str
    event_type: str
    title: str
    details: str
    severity: str = "INFO"  # INFO | WARNING | ERROR
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DemoControlsRequest(BaseModel):
    feed_mode: Optional[str] = None  # connected | delayed | stale | disconnected | unconfigured
    incident_mode: Optional[str] = None  # none | waterlogging | breakdown | stop_closure
    crowd_mode: Optional[str] = None  # low | moderate | high | very_high
    accessibility_mode: Optional[str] = None  # low_floor | standard | unknown
    offline_mode: Optional[bool] = None
    simulator_mode: Optional[bool] = None
    prediction_source: Optional[str] = None  # verified | gtfs_rt | historical | simulated
    recommendation_scenario: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 41: Smart Transit Trip Assurance & Commuter Safety Models
# ---------------------------------------------------------------------------

class TripAssuranceStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    RUNNING_LATE = "RUNNING_LATE"
    TRANSFER_AT_RISK = "TRANSFER_AT_RISK"
    DISRUPTED = "DISRUPTED"
    OFFLINE = "OFFLINE"
    DESTINATION_APPROACHING = "DESTINATION_APPROACHING"
    ARRIVED = "ARRIVED"
    UNKNOWN = "UNKNOWN"


class TripAssuranceActionType(str, Enum):
    CONTINUE_TRIP = "CONTINUE_TRIP"
    VIEW_TRANSFER = "VIEW_TRANSFER"
    VIEW_ALTERNATIVE = "VIEW_ALTERNATIVE"
    TRACK_BUS = "TRACK_BUS"
    VIEW_INCIDENT = "VIEW_INCIDENT"
    VIEW_CROWD = "VIEW_CROWD"
    VIEW_ACCESSIBILITY = "VIEW_ACCESSIBILITY"
    RECHECK_DATA = "RECHECK_DATA"
    END_JOURNEY = "END_JOURNEY"


class TripAssuranceAction(BaseModel):
    action_id: str
    label: str
    action_type: str = "CONTINUE_TRIP"  # TripAssuranceActionType
    enabled: bool = True
    explanation: str = ""


class TripAssuranceAssessment(BaseModel):
    journey_id: str
    status: str = "ON_TRACK"  # TripAssuranceStatus
    status_label: str = "ON TRACK"
    current_route: Optional[str] = None
    current_stop: Optional[str] = None
    next_stop: Optional[str] = None
    destination: Optional[str] = None
    destination_eta_minutes: Optional[int] = None
    scheduled_destination_eta: Optional[str] = None
    delay_minutes: int = 0
    transfer_at_risk: bool = False
    transfer_buffer_minutes: Optional[int] = None
    disruption_detected: bool = False
    accessibility_considerations: Optional[str] = None
    crowd_considerations: Optional[str] = None
    data_source: str = "HISTORICAL_ESTIMATE"
    confidence: str = "MEDIUM"
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    disclosure: str = "Trip assurance information is based on available transit telemetry."
    recommended_actions: List[TripAssuranceAction] = Field(default_factory=list)


class JourneyCompletionSummary(BaseModel):
    journey_id: str
    origin: str
    destination: str
    route_number: Optional[str] = None
    routes: List[str] = Field(default_factory=list)
    total_duration_minutes: int = 0
    walking_distance_meters: int = 0
    transfers_count: int = 0
    fare_paid: float = 0.0
    crowd_status: Optional[str] = None
    accessibility_info: Optional[str] = None
    incidents_encountered: List[str] = Field(default_factory=list)
    data_source: str = "HISTORICAL_ESTIMATE"
    offline_periods_count: int = 0
    arrived_at: datetime = Field(default_factory=datetime.utcnow)
    disclosure: str = "Factual post-trip summary grounded in recorded journey telemetry."


class BusStop(BaseModel):
    stop_id: str
    name: str
    latitude: float
    longitude: float
    kannada_name: Optional[str] = None
    buses_stopping_soon: List[str] = []
    nearest_eta_minutes: Optional[int] = None
    accessibility: Optional[AccessibilityMetadata] = None
    crowd: Optional[CrowdMetadata] = None
    has_incident: bool = False
    incident_id: Optional[str] = None


class Route(BaseModel):
    route_id: str
    route_number: str
    source: str
    destination: str
    stops: List[str]
    estimated_duration: int  # minutes
    is_ac: bool = False
    bus_type: str = "BMTC Ordinary"
    waypoints: List[Coordinate] = []



class Bus(BaseModel):
    bus_id: str
    route_number: str
    bus_type: str
    destination: str
    latitude: float
    longitude: float
    speed: float  # km/h
    direction: float  # heading in degrees 0-360
    capacity: int
    current_passengers: int
    occupancy_percentage: int
    status: str = "IN_SERVICE"
    next_stop: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    plate_number: Optional[str] = None
    eta_minutes: Optional[int] = None
    available_seats: Optional[int] = None
    following_stop: Optional[str] = None
    distance_to_next_stop_km: Optional[float] = None
    accessibility: Optional[AccessibilityMetadata] = None
    crowd: Optional[CrowdMetadata] = None


class BusLocation(BaseModel):
    bus_id: str
    route_number: str
    latitude: float
    longitude: float
    speed: float
    direction: float
    heading: Optional[float] = None  # Standardized alias for direction
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    timestamp: Optional[datetime] = None  # Standardized alias for updated_at

    def __init__(self, **data):
        super().__init__(**data)
        if self.heading is None:
            self.heading = self.direction
        if self.timestamp is None:
            self.timestamp = self.updated_at


class Occupancy(BaseModel):
    bus_id: str
    capacity: int = 50
    total_capacity: Optional[int] = None  # Standardized alias for capacity
    current_passengers: Optional[int] = 0
    passengers: Optional[int] = None  # Standardized alias for current_passengers
    available_seats: Optional[int] = 0
    occupancy_percentage: Optional[int] = 0
    occupancy_percent: Optional[int] = None  # Standardized alias for occupancy_percentage
    occupancy_level: Optional[str] = "low"  # low | medium | high
    crowd_level: Optional[str] = None  # Standardized alias for occupancy_level
    occupancy_available: bool = True
    note: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def __init__(self, **data):
        if "total_capacity" in data and "capacity" not in data:
            data["capacity"] = data["total_capacity"]
        super().__init__(**data)
        if self.total_capacity is None:
            self.total_capacity = self.capacity
        if self.passengers is None:
            self.passengers = self.current_passengers
        if self.occupancy_percent is None:
            self.occupancy_percent = self.occupancy_percentage
        if self.crowd_level is None:
            self.crowd_level = self.occupancy_level


class HealthResponse(BaseModel):
    status: str = "healthy"
    provider: str = "mock"
    provider_name: Optional[str] = "MockTransitDataProvider"
    data_mode: str = "simulated"  # "simulated" | "realtime"
    realtime: bool = False
    service: str = "NammaBlr - BMTC Transit Backend"
    configured: bool = True
    details: Optional[str] = None
    feed_status: Optional[str] = "unconfigured"  # "connected" | "stale" | "unconfigured" | "offline"
    stale: bool = False
    last_update: Optional[datetime] = None
    feed_health: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ETAEstimate(BaseModel):
    bus_id: str
    route_number: str
    target_stop: str
    eta_minutes: int
    distance_km: float
    current_speed_kmh: float
    source: str = "geometric_estimate"  # "gtfs_rt_trip_update" | "scheduled_stop_time" | "geometric_estimate"
    confidence: str = "high"  # "high" | "moderate" | "low"
    is_stale: bool = False
    last_updated: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LegType(str, Enum):
    WALK = "WALK"
    BUS = "BUS"
    TRANSFER = "TRANSFER"


class JourneyLeg(BaseModel):
    leg_type: str = "BUS"  # "WALK" | "BUS" | "TRANSFER"
    sequence: int = 0
    origin_name: Optional[str] = None
    destination_name: Optional[str] = None
    distance_meters: Optional[int] = None
    duration_minutes: Optional[int] = None
    # Bus specific
    route_number: Optional[str] = None
    bus_id: Optional[str] = None
    bus_type: Optional[str] = None
    boarding_stop: Optional[str] = None
    alighting_stop: Optional[str] = None
    fare: Optional[int] = None
    eta: Optional[int] = None
    eta_source: Optional[str] = None
    data_source: Optional[str] = None
    # Transfer specific
    transfer_stop: Optional[str] = None
    walking_distance_meters: Optional[int] = None
    walking_duration_minutes: Optional[int] = None
    transfer_buffer_minutes: Optional[int] = None
    connecting_route: Optional[str] = None
    connecting_bus_id: Optional[str] = None
    connecting_bus_eta: Optional[int] = None
    connecting_bus_eta_source: Optional[str] = None
    accessibility: Optional[AccessibilityMetadata] = None
    crowd: Optional[CrowdMetadata] = None


class TransferDetails(BaseModel):
    transfer_stop: str
    walking_distance_meters: int = 250
    walking_duration_minutes: int = 3
    transfer_buffer_minutes: int = 3
    connecting_route: str
    connecting_bus_id: Optional[str] = None
    connecting_bus_eta_minutes: Optional[int] = None
    connecting_bus_eta_source: Optional[str] = "geometric_estimate"
    connecting_bus_status: Optional[str] = "approaching"
    has_alert: bool = False
    alert_message: Optional[str] = None
    is_missed: bool = False


class JourneySearchRequest(BaseModel):
    origin: str
    destination: str


class JourneyOption(BaseModel):
    route_number: str
    destination: str
    bus_id: str
    bus_type: str
    eta_minutes: int
    journey_duration_minutes: int
    occupancy_percentage: int
    available_seats: int
    number_of_stops: int
    origin_stop: str
    destination_stop: str
    fare_rupees: int
    predicted_occupancy_percent: Optional[int] = None
    predicted_seats: Optional[int] = None
    data_source: str = "simulated_corridor"
    transfers: int = 0
    eta_source: str = "geometric_estimate"  # "gtfs_rt_trip_update" | "geometric_estimate"
    freshness: str = "fresh"  # "fresh" | "delayed" | "stale" | "simulated"
    walking_distance_meters: Optional[int] = None
    walking_duration_minutes: Optional[int] = None
    service_alerts_count: int = 0
    walk_to_stop_meters: Optional[int] = None
    walk_to_stop_minutes: Optional[int] = None
    bus_ride_minutes: Optional[int] = None
    walk_from_stop_meters: Optional[int] = None
    walk_from_stop_minutes: Optional[int] = None
    has_disruption: bool = False
    disruption_alert_id: Optional[str] = None
    # Phase 34 Multi-Leg & Transfer extensions
    legs: Optional[List[JourneyLeg]] = None
    transfer_details: Optional[TransferDetails] = None
    is_multimodal: bool = False
    # Phase 35 Accessibility extensions
    accessibility: Optional[AccessibilityMetadata] = None
    accessibility_score: Optional[int] = None
    # Phase 36 Smart Crowd & Occupancy extensions
    crowd: Optional[CrowdMetadata] = None
    crowd_status: Optional[str] = None
    estimated_seat_availability: Optional[str] = None
    standing_likelihood: Optional[str] = None
    # Phase 37 Incident & Disruption extensions
    incident_impact: Optional[IncidentImpactAssessment] = None
    alternative_options: Optional[List[AlternativeJourneyComparison]] = None


class JourneySearchResponse(BaseModel):
    origin: str
    destination: str
    options: List[JourneyOption]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class JourneyRecommendationRequest(BaseModel):
    origin: str
    destination: str


class RecommendationWinner(BaseModel):
    category: str  # "Fastest" | "Lowest Fare" | "More Seats" | "Fewest Stops" | "Least Transfers"
    icon: str
    metric_label: str
    metric_value: str
    route_number: str
    bus_id: str


class JourneyRecommendationResponse(BaseModel):
    origin: str
    destination: str
    options: List[JourneyOption]
    winners: List[RecommendationWinner]
    factual_comparison: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class JourneyState(str, Enum):
    PLANNING = "PLANNING"
    WALKING_TO_STOP = "WALKING_TO_STOP"
    WAITING_FOR_BUS = "WAITING_FOR_BUS"
    BUS_APPROACHING = "BUS_APPROACHING"
    ON_BUS = "ON_BUS"
    NEAR_DESTINATION = "NEAR_DESTINATION"
    DESTINATION_APPROACHING = "DESTINATION_APPROACHING"
    GET_READY_TO_EXIT = "GET_READY_TO_EXIT"
    DESTINATION_REACHED = "DESTINATION_REACHED"
    DESTINATION_PASSED = "DESTINATION_PASSED"
    # Phase 34 Transfer Lifecycle States
    TRANSFER_APPROACHING = "TRANSFER_APPROACHING"
    TRANSFER_READY = "TRANSFER_READY"
    WALKING_TO_CONNECTION = "WALKING_TO_CONNECTION"
    WAITING_FOR_CONNECTION = "WAITING_FOR_CONNECTION"
    CONNECTING_BUS_APPROACHING = "CONNECTING_BUS_APPROACHING"
    TRANSFER_COMPLETED = "TRANSFER_COMPLETED"
    TRANSFER_MISSED = "TRANSFER_MISSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    OFFLINE = "OFFLINE"


class ActiveJourney(BaseModel):
    id: str
    route_number: str
    bus_id: str
    bus_type: str = "BMTC Ordinary"
    origin: str
    destination: str
    current_stop: str
    next_stop: str
    following_stop: Optional[str] = None
    remaining_stops: int = 4
    eta_minutes: int = 18
    destination_eta_str: Optional[str] = None
    stops: List[str] = []
    passed_stops: List[str] = []
    walking_distance_meters: int = 350
    walking_duration_minutes: int = 4
    bus_distance_km: Optional[float] = 1.8
    state: JourneyState = JourneyState.WAITING_FOR_BUS
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    actual_duration_minutes: Optional[int] = None
    data_source: str = "simulated_corridor"
    feed_status: str = "connected"
    fare: int = 20
    fare_type: str = "standard_demo_fare"
    ticket_id: Optional[str] = None
    ticket_status: Optional[str] = "active"
    has_disruption: bool = False
    disruption_message: Optional[str] = None
    # Phase 33 Smart Arrival Intelligence Fields
    is_destination_reached: bool = False
    is_destination_passed: bool = False
    is_get_ready_to_exit: bool = False
    telemetry_reliable: bool = True
    telemetry_disclosure: Optional[str] = None
    data_transparency_label: str = "SIMULATED TRANSIT DATA"
    last_telemetry_sync: Optional[datetime] = None
    # Phase 34 Smart Transfers & Multimodal Fields
    legs: Optional[List[JourneyLeg]] = None
    transfer_details: Optional[TransferDetails] = None
    is_transfer_journey: bool = False
    current_leg_index: int = 0
    transfer_buffer_minutes: Optional[int] = None
    connecting_route: Optional[str] = None
    connecting_bus_id: Optional[str] = None
    connecting_bus_eta_minutes: Optional[int] = None
    connecting_bus_eta_source: Optional[str] = None
    is_connecting_bus_approaching: bool = False
    is_transfer_missed: bool = False
    transfer_alert_message: Optional[str] = None
    # Phase 36 Smart Crowd & Occupancy extensions
    crowd: Optional[CrowdMetadata] = None
    crowd_status: Optional[str] = None
    estimated_seat_availability: Optional[str] = None
    standing_likelihood: Optional[str] = None
    occupancy_disclosure: Optional[str] = None
    # Phase 37 Incident & Disruption extensions
    incident_impact: Optional[IncidentImpactAssessment] = None
    is_transfer_at_risk: bool = False
    transfer_risk_warning: Optional[str] = None
    # Phase 41 Smart Commuter Safety & Emergency Assistance Fields
    safety_status: str = "NORMAL"
    safety_message: str = "Journey progressing normally"
    last_safety_check_at: Optional[datetime] = None
    telemetry_health: str = "HEALTHY"
    assistance_requested: bool = False
    assistance_requested_at: Optional[datetime] = None
    safety_event_count: int = 0
    # NammaRoute integration: tracked telemetry for this journey's bus (freshness, direction, stops, source)
    vehicle_telemetry: Optional[TrackedVehicle] = None


class ActiveJourneyCreateRequest(BaseModel):
    route_number: str
    bus_id: str
    origin: str
    destination: str
    bus_type: Optional[str] = "BMTC Ordinary"
    fare: Optional[int] = 20
    fare_type: Optional[str] = "standard_demo_fare"
    ticket_id: Optional[str] = None
    walking_distance_meters: Optional[int] = 350
    walking_duration_minutes: Optional[int] = 4
    initial_state: Optional[JourneyState] = JourneyState.WAITING_FOR_BUS
    # Phase 34 Multi-leg transfer parameters
    is_transfer_journey: Optional[bool] = False
    transfer_details: Optional[TransferDetails] = None
    legs: Optional[List[JourneyLeg]] = None
    connecting_route: Optional[str] = None
    connecting_bus_id: Optional[str] = None


class ActiveJourneyUpdateRequest(BaseModel):
    state: Optional[JourneyState] = None
    current_stop: Optional[str] = None
    next_stop: Optional[str] = None
    eta_minutes: Optional[int] = None
    ticket_id: Optional[str] = None
    current_leg_index: Optional[int] = None
    transfer_buffer_minutes: Optional[int] = None
    is_transfer_missed: Optional[bool] = None


class JourneyHistoryItem(BaseModel):
    id: str
    route_number: str
    origin: str
    destination: str
    bus_type: str = "BMTC Ordinary"
    fare: int = 20
    fare_type: str = "standard_demo_fare"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    status: str = "COMPLETED"  # "COMPLETED" | "CANCELLED"
    duration_minutes: Optional[int] = None
    ticket_id: Optional[str] = None


class StopCrowdPrediction(BaseModel):
    stop_name: str
    stops_ahead: int
    occupancy_percent: int
    estimated_passengers: int
    estimated_seats: int
    estimated_boarding: int
    estimated_alighting: int
    crowd_tier: str  # "Comfortable" | "Moderate" | "Crowded" | "Very Crowded"
    confidence: float = 0.85


class BusCrowdPredictionResponse(BaseModel):
    bus_id: str
    route_number: str
    bus_type: str
    capacity: int
    current_passengers: int
    current_occupancy_percent: int
    current_crowd_tier: str
    available_seats: int
    trend: str = "stable"  # "increasing" | "stable" | "decreasing"
    explanation: Optional[str] = None
    predictions: List[StopCrowdPrediction]
    disclaimer: str = "Prediction only — actual passenger levels may vary."
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class NearbyStopIntelligence(BaseModel):
    stop_id: str
    name: str
    latitude: float
    longitude: float
    distance_meters: int
    routes: List[str]
    next_bus_route: Optional[str] = None
    next_bus_destination: Optional[str] = None
    next_bus_id: Optional[str] = None
    eta_minutes: Optional[int] = None
    service_type: Optional[str] = None
    available_seats: Optional[int] = None
    crowd_tier: Optional[str] = None
    data_source: str = "simulated_corridor"
    freshness: str = "fresh"  # "fresh" | "delayed" | "stale"
    accessibility: Optional[AccessibilityMetadata] = None
    crowd: Optional[CrowdMetadata] = None


class StopBusArrival(BaseModel):
    route_number: str
    destination: str
    bus_type: str
    eta_minutes: int
    eta_source: str = "Calculated Estimate"  # "Official Trip Update" | "Calculated Estimate"
    data_status: str = "Simulated Corridor"
    bus_id: Optional[str] = None
    accessibility: Optional[AccessibilityMetadata] = None
    crowd: Optional[CrowdMetadata] = None


class StopDetailsResponse(BaseModel):
    stop_id: str
    name: str
    kannada_name: Optional[str] = None
    latitude: float
    longitude: float
    serving_routes: List[str]
    upcoming_arrivals: List[StopBusArrival]
    is_realtime: bool = True
    feed_status: str = "SIMULATED_FEED"
    feed_disclosure: str = "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    accessibility: Optional[AccessibilityMetadata] = None
    crowd: Optional[CrowdMetadata] = None


class NotificationEvent(BaseModel):
    id: str
    event_type: str  # "approaching_bus" | "service_alert" | "journey_update" | "feed_recovery"
    title: str
    message: str
    route_number: Optional[str] = None
    stop_name: Optional[str] = None
    severity: str = "INFO"  # "INFO" | "WARNING" | "SEVERE"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AIChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_stop: Optional[str] = "Central Silk Board Junction"
    transit_context: Optional[Dict[str, Any]] = None


class AIChatResponse(BaseModel):
    answer: str
    intent: str
    bus_id: Optional[str] = None
    route_number: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    prediction: Optional[Dict[str, Any]] = None
    provider: str = "MockAIProvider"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FeedComponentDiagnostic(BaseModel):
    configured: bool = False
    reachable: bool = False
    valid: bool = False
    last_update: Optional[datetime] = None
    entity_count: int = 0
    details: Optional[str] = None


class Ticket(BaseModel):
    ticket_id: str
    route_number: str
    source: str
    destination: str
    fare_rupees: int
    bus_type: str = "BMTC Ordinary"
    issued_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    passenger_id: str = "PASS-84920"
    qr_payload: str
    status: str = "active"  # active | used | expired | invalid | mismatch
    used_at: Optional[datetime] = None
    disclaimer: str = "DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL"
    fare_type: str = "standard_demo_fare"  # standard_demo_fare | women_demo_concession
    passenger_gender: Optional[str] = None  # female | male
    identity_status: Optional[str] = None  # demo_verified | standard_commuter
    # Phase 43: paid tickets (payment reference is part of the HMAC-signed payload)
    payment_id: Optional[str] = None
    payment_status: Optional[str] = None
    passenger_count: int = 1
    ticket_type: Optional[str] = None
    vehicle_number: Optional[str] = None  # bus boarded (network routes)


class TicketCreateRequest(BaseModel):
    route_number: str
    source: str
    destination: str
    bus_type: Optional[str] = "BMTC Ordinary"
    fare_rupees: Optional[int] = 25
    fare_type: Optional[str] = "standard_demo_fare"
    passenger_gender: Optional[str] = None
    identity_status: Optional[str] = None


class TicketVerificationRequest(BaseModel):
    qr_payload_or_code: str
    conductor_route_number: Optional[str] = None


class TicketVerificationResponse(BaseModel):
    valid: bool
    status: str  # active | used | expired | invalid | mismatch
    message: str
    ticket: Optional[Ticket] = None
    validation_timestamp: datetime = Field(default_factory=datetime.utcnow)


class FeedHealth(BaseModel):
    status: str = "unavailable"  # healthy | delayed | stale | unavailable
    last_update: Optional[datetime] = None
    vehicle_positions: int = 0
    trip_updates: int = 0
    service_alerts: int = 0
    valid_entities: int = 0
    invalid_entities: int = 0
    ignored_entities: int = 0
    consecutive_failures: int = 0
    freshness_percentage: float = 0.0
    last_successful_fetch: Optional[datetime] = None
    last_failed_fetch: Optional[datetime] = None
    vehicle_positions_feed: Optional[FeedComponentDiagnostic] = None
    trip_updates_feed: Optional[FeedComponentDiagnostic] = None
    service_alerts_feed: Optional[FeedComponentDiagnostic] = None


class ServiceAlert(BaseModel):
    id: str
    route_number: Optional[str] = None
    stop_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    severity: str = "INFO"  # INFO | WARNING | SEVERE
    source: str = "demo"  # "gtfs_rt" | "demo"
    is_active: bool = True
    active_period_start: Optional[datetime] = None
    active_period_end: Optional[datetime] = None
    affected_entities: List[str] = Field(default_factory=list)
    is_official_realtime: bool = False
    data_mode: str = "simulated"  # "simulated" | "realtime"
    source_type: str = "demo_advisory"  # "official_gtfs_rt" | "demo_advisory"


class ReadinessResponse(BaseModel):
    ready: bool = True
    status: str = "ready"
    active_provider: str = "mock"
    data_mode: str = "simulated"
    feed_status: str = "unconfigured"
    uptime_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ModuleStatus(BaseModel):
    name: str
    status: str = "Active"
    details: str
    latency_ms: Optional[int] = 12


class SystemStatusResponse(BaseModel):
    overall_status: str = "Active"
    demo_mode: bool = True
    provider: str = "mock"
    provider_name: Optional[str] = "MockTransitDataProvider"
    data_mode: str = "simulated"
    feed_status: Optional[str] = "unconfigured"
    stale: bool = False
    last_update: Optional[datetime] = None
    last_successful_realtime_update: Optional[datetime] = None
    provider_polling_interval: float = 10.0
    uptime_seconds: Optional[float] = 0.0
    latency_stats: Optional[Dict[str, float]] = None
    feed_health: Optional[FeedHealth] = None
    diagnostics: Optional[Dict[str, Any]] = None
    modules: List[ModuleStatus]
    tracked_vehicles: Optional[int] = 5
    gtfs_routes: Optional[int] = 4
    gtfs_stops: Optional[int] = 32
    p95_latency_ms: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EntityValidationStats(BaseModel):
    valid_entities: int = 0
    invalid_entities: int = 0
    ignored_entities: int = 0
    total_entities: int = 0
    validation_details: List[str] = Field(default_factory=list)


class RealtimeActivationDiagnostics(BaseModel):
    configured: bool = False
    configuration_valid: bool = False
    feed_reachable: bool = False
    feed_valid: bool = False
    activated: bool = False
    provider: str = "mock"
    reason: str = "Authorized realtime BMTC feed not configured"
    entity_count: int = 0
    valid_entities: int = 0
    invalid_entities: int = 0
    ignored_entities: int = 0
    occupancy_available: bool = False
    timestamp_freshness_seconds: Optional[float] = None
    vehicle_positions_status: str = "unconfigured"
    trip_updates_status: str = "unconfigured"
    service_alerts_status: str = "unconfigured"
    validation_errors: List[str] = Field(default_factory=list)


class RealtimeValidationRequest(BaseModel):
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    vehicle_positions_url: Optional[str] = None
    trip_updates_url: Optional[str] = None
    service_alerts_url: Optional[str] = None
    timeout_seconds: Optional[float] = None


class RealtimeValidationResponse(BaseModel):
    success: bool
    endpoint_configuration: Dict[str, Any]
    connectivity: bool
    response_validity: bool
    entity_count: int
    valid_entities: int
    invalid_entities: int
    ignored_entities: int
    timestamp_freshness_seconds: Optional[float] = None
    vehicle_positions_status: str
    trip_updates_status: str
    service_alerts_status: str
    occupancy_availability: bool
    operational_statement: str
    validation_errors: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RealtimeTestComponent(BaseModel):
    configured: bool = False
    reachable: bool = False
    valid_entities: int = 0


class RealtimeTestResponse(BaseModel):
    configured: bool
    provider: str
    feed_status: str
    vehicle_positions: RealtimeTestComponent
    trip_updates: RealtimeTestComponent
    service_alerts: RealtimeTestComponent
    message: str
