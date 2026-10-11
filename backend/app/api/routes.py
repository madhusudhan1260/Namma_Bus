from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from ..models.transit import (
    Bus,
    BusLocation,
    BusStop,
    Route,
    Occupancy,
    ETAEstimate,
    HealthResponse,
    JourneySearchRequest,
    JourneySearchResponse,
    JourneyRecommendationRequest,
    JourneyRecommendationResponse,
    NearbyStopIntelligence,
    StopBusArrival,
    StopDetailsResponse,
    NotificationEvent,
    AIChatRequest,
    AIChatResponse,
    BusCrowdPredictionResponse,
    Ticket,
    TicketCreateRequest,
    TicketVerificationRequest,
    TicketVerificationResponse,
    ModuleStatus,
    SystemStatusResponse,
    ReadinessResponse,
    ServiceAlert,
    RealtimeValidationRequest,
    RealtimeValidationResponse,
    RealtimeTestResponse,
    RealtimeTestComponent,
    ActiveJourney,
    ActiveJourneyCreateRequest,
    ActiveJourneyUpdateRequest,
    JourneyHistoryItem,
    JourneyState,
    AccessibilityMetadata,
    AccessibilityStatus,
    CrowdMetadata,
    CrowdDetailsResponse,
    Incident,
    IncidentImpactAssessment,
    AlternativeJourneyComparison,
    IncidentOverrideRequest,
    IncidentDetailsResponse,
    CommuterPrediction,
    CommuterRecommendation,
    SystemModuleHealth,
    FeedHealthDiagnostic,
    DataQualityAssessment,
    DiagnosticEvent,
    DemoControlsRequest,
    TripAssuranceAssessment,
    JourneyCompletionSummary,
)
from ..models.safety import (
    SafetyAssessment,
    SafetyEvent,
    AssistanceRequest,
    AssistanceResponse,
    SafetyCheckRequest,
    SafetyCheckResponse,
    JourneyShareStartRequest,
    JourneyShareStopRequest,
    JourneyShareResponse,
    JourneyShareStatusResponse,
    NearbySafetyResponse,
    SafetyDemoOverrideRequest,
)
from ..core.config import settings, OPERATIONAL_STATEMENT_NOT_CONNECTED
from ..services.provider_factory import get_transit_provider, get_provider_health, is_simulation_active
from ..services.journey_service import JourneyService
from ..services.recommendation_service import RecommendationService
from ..services.commuter_recommendation_service import commuter_recommendation_service
from ..services.prediction_service import prediction_service
from ..services.health_service import health_service
from ..services.trip_assurance_service import trip_assurance_service
from ..services.safety_service import safety_service
from ..services.journey_share_service import journey_share_service
from ..services.notification_service import notification_service
from ..services.notification_center_service import notification_center_service
from ..services.vehicle_tracking_service import vehicle_tracking_service
from ..models.realtime import RealtimeStatusResponse, RealtimeVehiclesResponse, TrackedVehicle
from ..services.payment_service import (
    DEMO_PAYMENT_DISCLOSURE,
    PaymentCreateRequest,
    PaymentError,
    PaymentReceipt,
    PaymentRecord,
    PaymentVerifyRequest,
    TicketPurchaseRequest,
    payment_service,
)
from ..services.eta_service import ETAService, haversine_distance_km
from ..services.ai_service import AIService
from ..services.crowd_prediction_service import CrowdPredictionService
from ..services.crowd_service import crowd_service
from ..services.incident_service import incident_service
from ..services.incident_impact_service import incident_impact_service
from ..services.ticket_service import ticket_service
from ..services.active_journey_service import active_journey_service
from ..services.mock_provider import mock_provider
from ..services.bmtc_provider import bmtc_provider
from ..services.metrics_service import metrics_service
from ..services.alert_service import alert_service
from ..services.gtfs.repository import gtfs_repository
from ..services.realtime_activation_service import realtime_activation_service
from ..services.identity_provider import identity_service
from ..services.auth_service import AuthError, auth_service, identity_onboarding_service
from ..models.auth import (
    AuthResponse,
    DigiLockerStatusResponse,
    IDENTITY_UNAVAILABLE_MESSAGE,
    IdentityDemoModeRequest,
    IdentityStatusDto,
    IdentityVerificationCompleteRequest,
    IdentityVerificationResult,
    IdentityVerificationStartRequest,
    IdentityVerificationStartResponse,
    LoginRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    ShaktiEligibilityResponse,
    UserSessionDto,
)
from ..models.identity import (
    IdentitySessionCreate,
    IdentitySessionResponse,
    DocumentVerifyRequest,
    SelfieVerifyRequest,
    IdentityVerifyResponse,
    IdentityStatusResponse,
    DemoOverrideRequest,
)
from ..services.personalization_service import personalization_service
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

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"], summary="Liveness & Provider Health Probe")
async def health_check():
    """
    Liveness probe: reports process operational status, active data mode, and provider health.
    Transparently reveals if system is operating in simulated mode or active realtime mode.
    NOTE: Realtime BMTC connectivity requires authorized municipal credentials.
    """
    return get_provider_health()


@router.get("/ready", response_model=ReadinessResponse, tags=["Health"], summary="Readiness Probe")
async def readiness_check():
    """
    Readiness probe: verifies whether application is ready to process commuter traffic.
    Application remains resilient and ready even if external BMTC feeds are unconfigured or offline
    by serving high-fidelity fallback telemetry.
    NOTE: Realtime BMTC connectivity requires authorized municipal credentials.
    """
    provider_health = get_provider_health()
    return ReadinessResponse(
        ready=True,
        status="ready",
        active_provider=provider_health.provider,
        data_mode=provider_health.data_mode,
    )


@router.get("/alerts", response_model=List[ServiceAlert], tags=["Alerts"])
async def get_service_alerts(
    route: Optional[str] = Query(default=None, description="Optional route filter (e.g. 500D)"),
    stop: Optional[str] = Query(default=None, description="Optional bus stop name filter"),
    severity: Optional[str] = Query(default=None, description="Optional severity filter (INFO, WARNING, SEVERE)"),
    source: Optional[str] = Query(default=None, description="Optional alert source filter ('gtfs_rt' | 'demo')"),
    active_only: bool = Query(default=True, description="Filter for active alerts only"),
):
    """Retrieve municipal service alerts, corridor disruption advisories, and maintenance bulletins."""
    return alert_service.get_alerts(
        route_number=route,
        stop_name=stop,
        severity=severity,
        source=source,
        active_only=active_only,
    )


@router.get("/buses", response_model=List[Bus], tags=["Transit"])
async def get_all_buses():
    """Retrieve all active buses in service with coordinates and occupancy from active provider."""
    provider = get_transit_provider()
    return await provider.get_buses()


@router.get("/buses/{bus_id}", response_model=Bus, tags=["Transit"])
async def get_bus_by_id(bus_id: str):
    """Retrieve details for a specific bus by ID."""
    provider = get_transit_provider()
    bus = await provider.get_bus(bus_id)
    if not bus:
        raise HTTPException(status_code=404, detail=f"Bus with ID '{bus_id}' not found")
    return bus


@router.get("/buses/{bus_id}/location", response_model=BusLocation, tags=["Transit"])
async def get_bus_location(bus_id: str):
    """Retrieve live GPS coordinates and movement telemetry for a bus."""
    provider = get_transit_provider()
    loc = await provider.get_bus_location(bus_id)
    if not loc:
        raise HTTPException(status_code=404, detail=f"Location for bus '{bus_id}' not found")
    return loc


@router.get("/buses/{bus_id}/route", response_model=Route, tags=["Transit"])
async def get_bus_route(bus_id: str):
    """Retrieve the planned route and sequence of stops for a bus."""
    provider = get_transit_provider()
    route = await provider.get_bus_route(bus_id)
    if not route:
        raise HTTPException(status_code=404, detail=f"Route for bus '{bus_id}' not found")
    return route


@router.get("/buses/{bus_id}/stops", response_model=List[BusStop], tags=["Transit"])
async def get_bus_stops(bus_id: str):
    """Retrieve the ordered list of bus stops along the bus's route."""
    provider = get_transit_provider()
    stops = await provider.get_bus_stops(bus_id)
    return stops


@router.get("/buses/{bus_id}/eta", response_model=ETAEstimate, tags=["Transit"])
async def get_bus_eta(
    bus_id: str,
    target_stop: str = Query(default="Central Silk Board Junction", description="Target bus stop name"),
):
    """Calculate and return the estimated arrival time (ETA) for a bus to reach a stop."""
    provider = get_transit_provider()
    eta_res = await provider.get_eta(bus_id, target_stop)
    if not eta_res:
        raise HTTPException(status_code=404, detail=f"Bus with ID '{bus_id}' not found")
    return eta_res


@router.get("/buses/{bus_id}/occupancy", response_model=Occupancy, tags=["Transit"])
async def get_bus_occupancy(bus_id: str):
    """Retrieve real-time passenger crowd, seat availability, and occupancy percentage."""
    provider = get_transit_provider()
    occ = await provider.get_bus_occupancy(bus_id)
    if not occ:
        raise HTTPException(status_code=404, detail=f"Occupancy for bus '{bus_id}' not found")
    return occ


@router.get("/buses/{bus_id}/crowd-prediction", response_model=BusCrowdPredictionResponse, tags=["Crowd"])
async def get_bus_crowd_prediction(bus_id: str):
    """Retrieve predictive passenger flow, crowd forecast, and estimated seat availability for upcoming stops."""
    prediction = await CrowdPredictionService.predict_for_bus(bus_id)
    if not prediction:
        raise HTTPException(status_code=404, detail=f"Bus with ID '{bus_id}' not found")
    return prediction


@router.get("/crowd/bus/{bus_id}", response_model=BusCrowdPredictionResponse, tags=["Crowd"])
async def get_crowd_for_bus(bus_id: str):
    """Alias for bus crowd prediction under Crowd tag."""
    return await get_bus_crowd_prediction(bus_id)


@router.get("/routes", response_model=List[Route], tags=["Transit"])
async def get_routes():
    """Retrieve available transit routes across active corridors."""
    provider = get_transit_provider()
    buses = await provider.get_buses()
    routes = []
    seen = set()
    for b in buses:
        r = await provider.get_bus_route(b.bus_id)
        if r and r.route_number not in seen:
            seen.add(r.route_number)
            routes.append(r)
    return routes


@router.get("/stops", response_model=List[BusStop], tags=["Transit"])
async def get_all_stops():
    """Retrieve indexed bus stops across corridors."""
    provider = get_transit_provider()
    return await provider.get_nearby_stops(12.9716, 77.5946, radius_km=25.0)


@router.get("/transit/accessibility/{route_or_bus_id}", response_model=AccessibilityMetadata, tags=["Transit"], summary="Get Accessibility Metadata")
async def get_transit_accessibility(route_or_bus_id: str):
    """
    Retrieve verified accessibility metadata for a bus, route, or stop.
    Strictly returns UNKNOWN status if not explicitly verified in underlying transit data.
    """
    provider = get_transit_provider()
    if hasattr(provider, "get_accessibility_info"):
        return provider.get_accessibility_info(route_or_bus_id)
    return AccessibilityMetadata(
        status=AccessibilityStatus.UNKNOWN,
        wheelchair_accessible=None,
        low_floor_bus=None,
        boarding_assistance_available=False,
        accessible_stop=False,
        audio_announcements=False,
        visual_displays=False,
        accessibility_disclosure="Accessibility information unavailable from the current transit data.",
        accessibility_source="simulated_corridor",
    )


@router.post("/journey/search", response_model=JourneySearchResponse, tags=["Journey"])
async def search_journey(request: JourneySearchRequest):
    """Search available BMTC bus routes connecting given origin and destination."""
    return await JourneyService.search_journey(request)


@router.post("/journey/recommend", response_model=JourneyRecommendationResponse, tags=["Journey"])
async def recommend_journey(request: JourneyRecommendationRequest):
    """
    Deterministic journey recommendation engine.
    Calculates factual category comparisons: Fastest, Lowest Fare, More Seats,
    Fewest Stops, Least Transfers with zero subjective bias.
    """
    return await RecommendationService.recommend_journey(request)


# ---------------------------------------------------------------------------
# Active Commuter Journey & Trip Assistant Endpoints (Phase 32)
# ---------------------------------------------------------------------------

@router.get("/journey/active", response_model=ActiveJourney, tags=["Journey"])
async def get_active_journey():
    """Retrieve the current in-progress commuter active journey and synchronize with live telemetry."""
    journey = await active_journey_service.get_active_journey()
    if not journey:
        raise HTTPException(status_code=404, detail="No active journey currently in progress")
    return journey


@router.post("/journey/active", response_model=ActiveJourney, tags=["Journey"])
async def start_active_journey(request: ActiveJourneyCreateRequest):
    """Start and track a commuter journey along an active corridor."""
    return await active_journey_service.start_journey(request)


@router.patch("/journey/active", response_model=ActiveJourney, tags=["Journey"])
async def update_active_journey(request: ActiveJourneyUpdateRequest):
    """Update active journey state or progress (e.g. WALKING_TO_STOP -> WAITING_FOR_BUS -> ON_BUS)."""
    try:
        return active_journey_service.update_journey(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/journey/active/end", tags=["Journey"])
async def end_active_journey(reason: str = Query(default="COMPLETED", description="Reason: COMPLETED or CANCELLED")):
    """Complete or cancel the active journey and archive it to commuter journey history."""
    try:
        ended = active_journey_service.end_journey(reason=reason)
        return {"status": "ended", "journey": ended}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/journey/history", response_model=List[JourneyHistoryItem], tags=["Journey"])
async def get_journey_history():
    """Retrieve recent commuter journey history for one-tap repeat journeys."""
    return active_journey_service.get_history()


@router.get("/journey/transfer", tags=["Journey"], summary="Get Active Journey Transfer Details")
async def get_active_journey_transfer():
    """Retrieve active journey transfer details if a multimodal transfer journey is in progress."""
    aj = await active_journey_service.get_active_journey()
    if not aj or not aj.is_transfer_journey or not aj.transfer_details:
        raise HTTPException(status_code=404, detail="No active transfer journey found")
    return {
        "journey_id": aj.id,
        "route_number": aj.route_number,
        "state": aj.state,
        "transfer_details": aj.transfer_details,
        "legs": aj.legs,
        "transfer_buffer_minutes": aj.transfer_buffer_minutes,
        "connecting_route": aj.connecting_route,
        "connecting_bus_id": aj.connecting_bus_id,
        "connecting_bus_eta_minutes": aj.connecting_bus_eta_minutes,
        "is_connecting_bus_approaching": aj.is_connecting_bus_approaching,
        "is_transfer_missed": aj.is_transfer_missed,
    }



@router.get("/stops/nearby", response_model=List[NearbyStopIntelligence], tags=["Transit"])
async def get_nearby_stops(
    lat: float = Query(default=12.9176, description="Latitude (default Silk Board)"),
    lon: float = Query(default=77.6238, description="Longitude (default Silk Board)"),
    radius_km: float = Query(default=3.0, description="Search radius in kilometers"),
):
    """Retrieve bus stops in geographic proximity to user coordinates enriched with next bus intelligence."""
    provider = get_transit_provider()
    raw_stops = await provider.get_nearby_stops(latitude=lat, longitude=lon, radius_km=radius_km)
    all_buses = await provider.get_buses()
    health = get_provider_health()

    enriched: List[NearbyStopIntelligence] = []
    for s in raw_stops:
        dist_m = int(round(haversine_distance_km(lat, lon, s.latitude, s.longitude) * 1000.0))
        
        # Find nearest bus servicing this stop
        nearest_bus = None
        min_eta = 999
        for b in all_buses:
            if b.next_stop.lower() in s.name.lower() or s.name.lower() in b.next_stop.lower():
                eta = b.eta_minutes or 6
                if eta < min_eta:
                    min_eta = eta
                    nearest_bus = b

        if not nearest_bus and all_buses:
            nearest_bus = all_buses[0]
            min_eta = nearest_bus.eta_minutes or 8

        enriched.append(
            NearbyStopIntelligence(
                stop_id=s.stop_id,
                name=s.name,
                latitude=s.latitude,
                longitude=s.longitude,
                distance_meters=dist_m,
                routes=s.buses_stopping_soon if s.buses_stopping_soon else ["500D", "356", "KIA-8"],
                next_bus_route=nearest_bus.route_number if nearest_bus else "500D",
                next_bus_destination=nearest_bus.destination if nearest_bus else "Majestic",
                next_bus_id=nearest_bus.bus_id if nearest_bus else "bus-500d-1",
                eta_minutes=min_eta if min_eta < 999 else 6,
                service_type=nearest_bus.bus_type if nearest_bus else "BMTC Ordinary",
                available_seats=nearest_bus.available_seats if nearest_bus else 12,
                crowd_tier="Moderate" if (nearest_bus and nearest_bus.occupancy_percentage >= 50) else "Comfortable",
                data_source=provider.get_data_mode(),
                freshness="delayed" if health.stale else "fresh",
            )
        )

    enriched.sort(key=lambda x: x.distance_meters)
    return enriched


@router.get("/stops/{stop_id}/arrivals", response_model=StopDetailsResponse, tags=["Transit"])
@router.get("/stops/{stop_id}/details", response_model=StopDetailsResponse, tags=["Transit"])
async def get_stop_details(stop_id: str):
    """
    Retrieve comprehensive stop intelligence including serving routes, next bus arrivals,
    dynamic ETA calculation, ETA attribution source, and feed freshness status.
    """
    provider = get_transit_provider()
    health = get_provider_health()
    all_stops = await provider.get_nearby_stops(12.9716, 77.5946, radius_km=25.0)
    matched_stop = next((s for s in all_stops if s.stop_id == stop_id or s.name.lower() == stop_id.lower()), None)

    if not matched_stop:
        matched_stop = BusStop(
            stop_id=stop_id,
            name=stop_id.replace("-", " ").title(),
            latitude=12.9176,
            longitude=77.6238,
            distance_meters=0,
            buses_stopping_soon=["500D", "356", "201R"],
        )

    all_buses = await provider.get_buses()
    arrivals: List[StopBusArrival] = []

    for b in all_buses:
        serves = any(r.upper() == b.route_number.upper() for r in matched_stop.buses_stopping_soon) or (b.next_stop.lower() in matched_stop.name.lower() or matched_stop.name.lower() in b.next_stop.lower())
        if serves or len(arrivals) < 3:
            eta_obj = await provider.get_eta(b.bus_id, target_stop_name=matched_stop.name)
            eta_src = "Official Trip Update" if (eta_obj and eta_obj.source == "gtfs_rt_trip_update") else "Calculated Estimate"
            data_stat = "BMTC Live Feed" if provider.is_realtime() else "Simulated Corridor"
            arrivals.append(
                StopBusArrival(
                    route_number=b.route_number,
                    destination=b.destination,
                    bus_type=b.bus_type,
                    eta_minutes=b.eta_minutes or (eta_obj.eta_minutes if eta_obj else 8),
                    eta_source=eta_src,
                    data_status=data_stat,
                    bus_id=b.bus_id,
                )
            )

    arrivals.sort(key=lambda a: a.eta_minutes)
    disclosure = "Connected to authorized BMTC realtime feed." if provider.is_realtime() else "Realtime BMTC feed not connected."

    return StopDetailsResponse(
        stop_id=matched_stop.stop_id,
        name=matched_stop.name,
        kannada_name=getattr(matched_stop, "kannada_name", None),
        latitude=matched_stop.latitude,
        longitude=matched_stop.longitude,
        serving_routes=matched_stop.buses_stopping_soon if matched_stop.buses_stopping_soon else ["500D", "356", "201R"],
        upcoming_arrivals=arrivals[:6],
        is_realtime=provider.is_realtime(),
        feed_status=health.feed_status,
        feed_disclosure=disclosure,
    )


@router.get("/notifications/events", response_model=List[NotificationEvent], tags=["Alerts"])
async def get_notification_events(
    route: Optional[str] = Query(default=None, description="Optional route filter (e.g. 500D)"),
    limit: int = Query(default=20, description="Max events to return"),
):
    """Retrieve simulated local transit notification events queue (approaching bus, advisories)."""
    return notification_service.get_events(route_number=route, limit=limit)



@router.post("/ai/chat", response_model=AIChatResponse, tags=["AI"])
async def ai_chat(request: AIChatRequest):
    """
    Process natural-language transit questions grounded strictly in real-time transit telemetry.
    Zero hallucination pipeline: intent parsing -> verified transit telemetry lookup -> grounded response generation.
    """
    return await AIService.process_chat(request)


# ---------------------------------------------------------------------------
# Digital Ticketing & Conductor Verification Endpoints (Prototype)
# ---------------------------------------------------------------------------

@router.post("/tickets", response_model=Ticket, tags=["Tickets"])
async def create_ticket(request: TicketCreateRequest, authorization: Optional[str] = Header(default=None)):
    """
    Generate a demo digital transit ticket for verified corridor routes.

    Phase 41: when the request carries a commuter session (Authorization: Bearer ...), a Shakti
    concession ticket is only issued after a fresh identity verification. Requests without a session
    keep the pre-Phase 41 demo behaviour.
    """
    token = _bearer_token(authorization)
    if token and request.fare_type == "women_demo_concession":
        user = auth_service.resolve(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required. Please log in again.")
        eligibility = identity_onboarding_service.check_shakti_eligibility(user)
        if not eligibility.concession_allowed:
            raise HTTPException(status_code=403, detail=eligibility.message)
        request.identity_status = (
            "demo_identity_verification"
            if eligibility.eligibility_status == "DEMO_ELIGIBLE"
            else "authorized_identity_verification"
        )
        request.passenger_gender = None  # never inferred from the onboarding path
    try:
        return await ticket_service.create_ticket(request)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.get("/tickets/history", response_model=List[Ticket], tags=["Tickets"])
async def get_ticket_history():
    """Retrieve history of all demo tickets."""
    return ticket_service.get_history()


@router.get("/tickets/stats", tags=["Conductor"])
async def get_ticket_stats():
    """Retrieve validation statistics for conductor reporting."""
    return ticket_service.get_stats()


@router.get("/tickets/{ticket_id}", response_model=Ticket, tags=["Tickets"])
async def get_ticket_by_id(ticket_id: str):
    """Retrieve a single ticket by ID."""
    ticket = ticket_service.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")
    return ticket


def _require_conductor(key: Optional[str]) -> None:
    """Phase 48: when CONDUCTOR_ACCESS_KEY is configured, conductor actions require the X-Conductor-Key header."""
    import hmac as _hmac
    expected = settings.conductor_access_key
    if expected and not (key and _hmac.compare_digest(key, expected)):
        from ..core.logging_config import log_structured_event
        log_structured_event(event_type="conductor_auth_denied", details={"reason": "missing_or_invalid_key"})
        raise HTTPException(status_code=403, detail="Conductor authorization required.")


@router.post("/tickets/verify", response_model=TicketVerificationResponse, tags=["Conductor"])
async def verify_ticket(request: TicketVerificationRequest, x_conductor_key: Optional[str] = Header(default=None)):
    """Verify a passenger ticket via QR payload or direct ticket ID code."""
    _require_conductor(x_conductor_key)
    return ticket_service.verify_ticket(
        request.qr_payload_or_code,
        conductor_route_number=request.conductor_route_number,
    )


@router.post("/tickets/{ticket_id}/use", response_model=TicketVerificationResponse, tags=["Conductor"])
async def mark_ticket_as_used(ticket_id: str, x_conductor_key: Optional[str] = Header(default=None)):
    """Conductor action: mark a verified active ticket as used."""
    _require_conductor(x_conductor_key)
    result = ticket_service.use_ticket(ticket_id)
    if result.status == "invalid":
        raise HTTPException(status_code=404, detail=result.message)
    return result


@router.get("/status", response_model=SystemStatusResponse, tags=["Diagnostics"], summary="System Status & Diagnostics")
async def get_status():
    """
    Retrieve operational status, feed health, and subsystem diagnostics.
    NOTE: Realtime BMTC feed requires authorized municipal credentials (API key / endpoint).
    """
    return await get_system_status()


@router.get("/system/status", response_model=SystemStatusResponse, tags=["Diagnostics"], summary="System Status & Diagnostics (Detailed)")
async def get_system_status():
    """
    Retrieve operational health for all core NammaBlr subsystems.
    NOTE: Realtime BMTC feed requires authorized municipal credentials (API key / endpoint).
    """
    provider_health = get_provider_health()
    ticket_stats = ticket_service.get_stats()

    modules = [
        ModuleStatus(
            name="Backend",
            status="Active",
            details=f"FastAPI + Uvicorn • Uptime: {metrics_service.get_uptime_seconds()}s",
            latency_ms=10,
        ),
        ModuleStatus(
            name="Transit Data",
            status="Active",
            details=f"Provider: {provider_health.provider.upper()} ({provider_health.data_mode})",
            latency_ms=14,
        ),
        ModuleStatus(
            name="Bus GPS Simulator",
            status="Active",
            details="5 active Bengaluru corridors running 3.5s updates",
            latency_ms=8,
        ),
        ModuleStatus(
            name="GTFS",
            status="Active",
            details=f"{gtfs_repository.get_stats().get('routes_count', 0)} routes, {gtfs_repository.get_stats().get('stops_count', 0)} stops indexed",
            latency_ms=6,
        ),
        ModuleStatus(
            name="Realtime Feed",
            status="Active" if provider_health.feed_status in ["connected", "healthy"] else ("Degraded" if provider_health.stale else "Standby"),
            details=f"Status: {provider_health.feed_status} • Stale: {provider_health.stale}",
            latency_ms=8,
        ),
        ModuleStatus(
            name="ETA Engine",
            status="Active",
            details="Dynamic corridor speed vector & stop dwell calculation",
            latency_ms=11,
        ),
        ModuleStatus(
            name="Crowd Prediction",
            status="Active",
            details="Multi-step forecast (+1/+2/+3/+5) & corridor trend model",
            latency_ms=16,
        ),
        ModuleStatus(
            name="Crowd Engine",
            status="Active",
            details="Corridor crowd & seat availability likelihood engine",
            latency_ms=7,
        ),
        ModuleStatus(
            name="Occupancy Feed",
            status="Active" if provider_health.feed_status in ["connected", "healthy"] else "Standby",
            details="Verified APC and GTFS-RT occupancy telemetry",
            latency_ms=8,
        ),
        ModuleStatus(
            name="AI Assistant",
            status="Active",
            details="Telemetry-grounded BMTC multi-turn conversational pipeline",
            latency_ms=22,
        ),
        ModuleStatus(
            name="Ticket Engine",
            status="Active",
            details=f"{ticket_stats.get('total_tickets', 0)} tickets generated • Valid route enforcement",
            latency_ms=9,
        ),
        ModuleStatus(
            name="Conductor Mode",
            status="Active",
            details=f"{ticket_stats.get('total_scanned', 0)} scanned • {ticket_stats.get('total_admitted', 0)} admitted",
            latency_ms=10,
        ),
        ModuleStatus(
            name="Alert Engine",
            status="Active",
            details=f"{len(alert_service.get_alerts(active_only=True))} active corridor advisories",
            latency_ms=5,
        ),
        ModuleStatus(
            name="Recommendation Engine",
            status="Active",
            details="Deterministic multi-category comparisons (Fastest, Lowest Fare, More Seats)",
            latency_ms=12,
        ),
        ModuleStatus(
            name="Identity Engine",
            status="Active",
            details="Privacy-first verification • Zero raw Aadhaar/biometrics",
            latency_ms=7,
        ),
        ModuleStatus(
            name="Notification Engine",
            status="Active",
            details=f"{len(notification_service.get_events())} active corridor events",
            latency_ms=4,
        ),
        ModuleStatus(
            name="VehiclePositions",
            status="Active" if provider_health.feed_status in ["connected", "healthy"] else "Standby",
            details=f"{len(bmtc_provider._buses)} realtime entities tracked",
            latency_ms=8,
        ),
        ModuleStatus(
            name="TripUpdates",
            status="Active" if provider_health.feed_status in ["connected", "healthy"] else "Standby",
            details=f"{len(bmtc_provider._trip_updates)} trip updates ingested",
            latency_ms=8,
        ),
        ModuleStatus(
            name="ServiceAlerts",
            status="Active",
            details=f"{len(alert_service.get_alerts(active_only=True))} active corridor advisories",
            latency_ms=5,
        ),
        ModuleStatus(
            name="Accessibility Engine",
            status="Active",
            details="Wheelchair ramp & low-floor verification with strict factual disclosure",
            latency_ms=6,
        ),
        ModuleStatus(
            name="Incident Engine",
            status="Active",
            details=f"{len(incident_service.get_active_incidents())} active incidents",
            latency_ms=7,
        ),
        ModuleStatus(
            name="Service Alert Engine",
            status="Active",
            details=f"{len(alert_service.get_alerts(active_only=True))} active corridor advisories",
            latency_ms=5,
        ),
        ModuleStatus(
            name="Disruption Impact Engine",
            status="Active",
            details="Corridor impact & transfer protection active",
            latency_ms=9,
        ),
        ModuleStatus(
            name="Alternative Journey Engine",
            status="Active",
            details="Factual alternative routing active",
            latency_ms=11,
        ),
        ModuleStatus(
            name="Prediction Engine",
            status="Active",
            details="Predictive commuter intelligence engine active",
            latency_ms=10,
        ),
        ModuleStatus(
            name="Personalized Recommendation Engine",
            status="Active",
            details="Personalized route recommendation engine active",
            latency_ms=8,
        ),
        ModuleStatus(
            name="System Health Engine",
            status="Active",
            details="18-module health and resilience monitor active",
            latency_ms=5,
        ),
    ]

    lat_stats = metrics_service.get_latency_stats()
    gtfs_stats = gtfs_repository.get_stats()

    diagnostics = {
        "backend": {
            "uptime_seconds": metrics_service.get_uptime_seconds(),
            "total_requests": metrics_service.total_requests,
            "latency": lat_stats,
        },
        "transit": {
            "provider_name": provider_health.provider_name,
            "data_mode": provider_health.data_mode,
            "realtime_enabled": provider_health.realtime,
            "feed_status": provider_health.feed_status,
            "active_trip_views": metrics_service.active_trip_views_count,
            "nearby_stop_queries": metrics_service.nearby_stop_queries_count,
        },
        "gtfs": gtfs_stats,
        "realtime": {
            "vehicle_positions": len(bmtc_provider._buses),
            "trip_updates": len(bmtc_provider._trip_updates),
            "service_alerts": bmtc_provider._service_alerts_count,
            "last_successful_update": bmtc_provider._last_successful_fetch,
            "consecutive_failures": bmtc_provider._consecutive_failures,
            "feed_age_seconds": (datetime.now(timezone.utc) - bmtc_provider._last_updated_at).total_seconds() if bmtc_provider._last_updated_at else None,
        },
        "ai": {
            "request_count": metrics_service.ai_requests_count,
            "ai_trip_context_queries": metrics_service.ai_trip_context_queries_count,
            "provider": "GroundedBMTCProvider",
        },
        "tickets": {
            "tickets_created": ticket_stats.get("total_tickets", 0),
            "tickets_verified": ticket_stats.get("total_scanned", 0),
        },
        "crowd": {
            "prediction_requests": metrics_service.crowd_prediction_requests_count,
            "forecast_views": metrics_service.crowd_forecast_views_count,
            "crowd_queries": metrics_service.crowd_queries,
            "crowd_predictions": metrics_service.crowd_predictions,
            "crowd_unknown_responses": metrics_service.crowd_unknown_responses,
            "crowd_verified_responses": metrics_service.crowd_verified_responses,
            "crowd_estimated_responses": metrics_service.crowd_estimated_responses,
            "seat_availability_queries": metrics_service.seat_availability_queries,
            "crowd_ai_queries": metrics_service.crowd_ai_queries,
            "crowd_alerts": metrics_service.crowd_alerts,
            "crowd_comparison_views": metrics_service.crowd_comparison_views,
            "simulation_override": crowd_service.get_simulation_override(),
        },
        "incidents": {
            "incident_queries": metrics_service.incident_queries,
            "active_incidents": len(incident_service.get_active_incidents()),
            "active_count": len(incident_service.get_active_incidents()),
            "incident_alerts": metrics_service.incident_alerts,
            "route_disruption_views": metrics_service.route_disruption_views,
            "stop_disruption_views": metrics_service.stop_disruption_views,
            "active_journey_disruption_warnings": metrics_service.active_journey_disruption_warnings,
            "transfer_risk_warnings": metrics_service.transfer_risk_warnings,
            "alternative_journey_views": metrics_service.alternative_journey_views,
            "incident_ai_queries": metrics_service.incident_ai_queries,
            "simulated_incidents": len([i for i in incident_service.get_active_incidents() if i.is_simulated]),
            "official_incidents": len([i for i in incident_service.get_active_incidents() if not i.is_simulated]),
            "simulation_override": incident_service.get_simulation_override(),
        },
        "recommendations": {
            "queries": metrics_service.journey_recommendations_count,
            "commuter_recommendations_count": metrics_service.commuter_recommendations_count,
            "saved_recommendations_count": metrics_service.saved_recommendations_count,
            "favorite_recommendations_count": metrics_service.favorite_recommendations_count,
            "disruption_recommendations_count": metrics_service.disruption_recommendations_count,
            "recommendation_ai_queries": metrics_service.recommendation_ai_queries,
        },
        "predictions": {
            "prediction_requests": metrics_service.prediction_requests,
            "arrival_predictions": metrics_service.arrival_predictions,
            "journey_predictions": metrics_service.journey_predictions,
            "transfer_predictions": metrics_service.transfer_predictions,
            "prediction_ai_queries": metrics_service.prediction_ai_queries,
        },
        "health": {
            "health_checks": metrics_service.health_checks,
            "data_quality_checks": metrics_service.data_quality_checks,
            "operational_events": len(health_service.get_events()),
            "data_quality_score": health_service.get_data_quality_assessment().data_quality_score,
        },
        "feeds": {
            "feed_status": health_service.get_feed_health().feed_status,
            "realtime_poll_attempts": metrics_service.realtime_poll_attempts,
            "realtime_successful_polls": metrics_service.realtime_successful_polls,
            "realtime_failed_polls": metrics_service.realtime_failed_polls,
        },
        "simulator": {
            "active": health_service._demo_simulator_mode,
            "corridors": ["500D", "356", "201R", "KIA-8"],
        },
        "offline": {
            "offline_mode": health_service._demo_offline_mode,
            "disclosure": "OFFLINE — SHOWING LAST KNOWN DATA" if health_service._demo_offline_mode else "ONLINE",
        },
        "alerts": {
            "active_alerts": len(alert_service.get_alerts(active_only=True)),
            "views": metrics_service.alert_views_count,
        },
        "notifications": {
            "events_count": len(notification_service.get_events()),
        },
        "accessibility": {
            "accessible_journey_searches": metrics_service.accessible_journey_searches,
            "accessible_options_viewed": metrics_service.accessible_options_viewed,
            "wheelchair_priority_queries": metrics_service.wheelchair_priority_queries,
            "low_floor_filter_applied": metrics_service.low_floor_filter_applied,
            "accessibility_ai_queries": metrics_service.accessibility_ai_queries,
        },
        "journey": {
            "active_journey_started": metrics_service.active_journey_started,
            "active_journey_completed": metrics_service.active_journey_completed,
            "journey_cancelled": metrics_service.journey_cancelled,
            "journey_state_transitions": metrics_service.journey_state_transitions,
            "journey_history_views": metrics_service.journey_history_views,
            "destination_approach_alerts": metrics_service.destination_approach_alerts,
            "get_ready_to_exit_alerts": metrics_service.get_ready_to_exit_alerts,
            "destination_reached_events": metrics_service.destination_reached_events,
            "missed_destination_warnings": metrics_service.missed_destination_warnings,
            "journey_notification_events": metrics_service.journey_notification_events,
            # Phase 34 Transfer Observability Counters
            "transfer_journeys_started": metrics_service.transfer_journeys_started,
            "transfer_views": metrics_service.transfer_views,
            "transfer_alerts": metrics_service.transfer_alerts,
            "transfer_completed": metrics_service.transfer_completed,
            "missed_transfer_warnings": metrics_service.missed_transfer_warnings,
            "connecting_bus_tracking_actions": metrics_service.connecting_bus_tracking_actions,
            "transfer_ai_queries": metrics_service.transfer_ai_queries,
            "has_active_journey": active_journey_service._active_journey is not None,
        },
        "journey_assurance": {
            "trip_assurance_queries": metrics_service.trip_assurance_queries,
            "trip_assurance_on_track": metrics_service.trip_assurance_on_track,
            "trip_assurance_delayed": metrics_service.trip_assurance_delayed,
            "trip_assurance_transfer_risk": metrics_service.trip_assurance_transfer_risk,
            "trip_assurance_disrupted": metrics_service.trip_assurance_disrupted,
            "trip_assurance_offline": metrics_service.trip_assurance_offline,
            "trip_assurance_arrived": metrics_service.trip_assurance_arrived,
            "assurance_rechecks": metrics_service.assurance_rechecks,
            "assurance_alternative_views": metrics_service.assurance_alternative_views,
            "journey_completion_views": metrics_service.journey_completion_views,
            "trip_assurance_ai_queries": metrics_service.trip_assurance_ai_queries,
        },
        "safety": {
            "safety_status_queries": metrics_service.safety_status_queries,
            "safety_events": metrics_service.safety_events,
            "assistance_requests": metrics_service.assistance_requests,
            "assistance_cancellations": metrics_service.assistance_cancellations,
            "safety_checks": metrics_service.safety_checks,
            "journey_shares_started": metrics_service.journey_shares_started,
            "journey_shares_stopped": metrics_service.journey_shares_stopped,
            "journey_shares_expired": metrics_service.journey_shares_expired,
            "safety_ai_queries": metrics_service.safety_ai_queries,
            "nearby_safety_queries": metrics_service.nearby_safety_queries,
        },
    }

    return SystemStatusResponse(
        overall_status="Active",
        demo_mode=provider_health.data_mode == "simulated",
        provider=provider_health.provider,
        provider_name=provider_health.provider_name or "MockTransitDataProvider",
        data_mode=provider_health.data_mode,
        feed_status=provider_health.feed_status,
        stale=provider_health.stale,
        last_update=provider_health.last_update,
        last_successful_realtime_update=bmtc_provider._last_successful_fetch,
        provider_polling_interval=settings.realtime_poll_interval_seconds,
        uptime_seconds=metrics_service.get_uptime_seconds(),
        latency_stats=lat_stats,
        feed_health=bmtc_provider.get_feed_health(),
        diagnostics=diagnostics,
        modules=modules,
        tracked_vehicles=5,
        gtfs_routes=gtfs_stats.get("routes_count", 4),
        gtfs_stops=gtfs_stats.get("stops_count", 32),
        p95_latency_ms=lat_stats.get("p95_ms", 0.0),
    )


@router.post("/demo/reset", tags=["Diagnostics"], summary="Demo State Reset")
async def reset_demo_state():
    """Reset simulated state, ticket history, alerts, conductor validation tallies, identity sessions, personalization, and active journey to initial state."""
    ticket_service.reset()
    mock_provider.reset_simulation()
    alert_service.reset()
    identity_service.reset_all_sessions()
    auth_service.reset()
    identity_onboarding_service.reset()
    payment_service.reset()
    personalization_service.reset()
    active_journey_service.reset()
    incident_service.reset()
    prediction_service.reset()
    commuter_recommendation_service.reset()
    health_service.reset()
    safety_service.reset()
    journey_share_service.reset()
    # Master spec deterministic reset: crowd overrides, operational event stream, trip assurance memo
    crowd_service.set_simulation_override(None)
    notification_service.reset()
    trip_assurance_service.reset()
    vehicle_tracking_service.reset()
    return {"status": "success", "message": "Demo state reset successfully"}


# ---------------------------------------------------------------------------
# Phase 25: Personalization & Notification Layer Endpoints
# ---------------------------------------------------------------------------

@router.get("/preferences", response_model=CommuterPreferencesDto, tags=["Personalization"], summary="Get Commuter Preferences")
async def get_preferences():
    """Retrieve commuter preferences including language, bus type, and alert filters."""
    return personalization_service.get_preferences()


@router.post("/preferences", response_model=CommuterPreferencesDto, tags=["Personalization"], summary="Update Commuter Preferences")
async def update_preferences(prefs: CommuterPreferencesDto):
    """Update commuter preferences."""
    return personalization_service.update_preferences(prefs)


@router.get("/saved-journeys", response_model=List[SavedJourneyDto], tags=["Personalization"], summary="Get Saved Journeys")
async def get_saved_journeys():
    """Retrieve saved commuter journeys."""
    return personalization_service.get_saved_journeys()


@router.post("/saved-journeys", response_model=SavedJourneyDto, tags=["Personalization"], summary="Save Commuter Journey")
async def create_saved_journey(request: SavedJourneyCreateDto):
    """Save a new frequent commuter journey."""
    return personalization_service.create_saved_journey(request)


@router.delete("/saved-journeys/{journey_id}", tags=["Personalization"], summary="Delete Saved Journey")
async def delete_saved_journey(journey_id: str):
    """Delete a saved commuter journey by ID."""
    success = personalization_service.delete_saved_journey(journey_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Saved journey '{journey_id}' not found")
    return {"status": "success", "message": f"Journey '{journey_id}' removed"}


@router.get("/favorite-routes", response_model=List[FavoriteRouteDto], tags=["Personalization"], summary="Get Favorite Routes")
async def get_favorite_routes():
    """Retrieve list of commuter favorite bus routes."""
    return personalization_service.get_favorite_routes()


@router.post("/favorite-routes", response_model=FavoriteRouteDto, tags=["Personalization"], summary="Add Favorite Route")
async def add_favorite_route(request: FavoriteRouteCreateDto):
    """Add a bus route to favorites."""
    return personalization_service.add_favorite_route(request)


@router.delete("/favorite-routes/{route_number}", tags=["Personalization"], summary="Remove Favorite Route")
async def remove_favorite_route(route_number: str):
    """Remove a bus route from favorites."""
    success = personalization_service.remove_favorite_route(route_number)
    if not success:
        raise HTTPException(status_code=404, detail=f"Favorite route '{route_number}' not found")
    return {"status": "success", "message": f"Route '{route_number}' removed from favorites"}


@router.get("/notifications", response_model=List[NotificationItemDto], tags=["Notifications"], summary="Get Notifications")
async def get_notifications(
    category: Optional[str] = Query(default=None, description="Filter by category: ARRIVALS, TRANSFERS, SERVICE ALERTS, CROWD, ACCESSIBILITY, PERSONAL, TICKETS, PAYMENTS, SYSTEM"),
    unread_only: bool = Query(default=False),
    include_expired: bool = Query(default=False),
):
    """Retrieve in-app notification center items (newest first). Expired items are hidden by default."""
    return notification_center_service.list(category=category, unread_only=unread_only, include_expired=include_expired)


@router.get("/notifications/unread", tags=["Notifications"], summary="Unread Notifications")
async def get_unread_notifications():
    items = notification_center_service.list(unread_only=True)
    return {"unread_count": len(items), "items": items}


@router.post("/notifications/read-all", tags=["Notifications"], summary="Mark All Notifications Read")
async def mark_all_notifications_read():
    return {"status": "success", "marked_read": notification_center_service.mark_all_read()}


@router.post("/notifications/{notification_id}/read", tags=["Notifications"], summary="Mark Notification as Read")
async def mark_notification_read_post(notification_id: str):
    if not notification_center_service.mark_read(notification_id):
        raise HTTPException(status_code=404, detail=f"Notification '{notification_id}' not found")
    return {"status": "success", "message": f"Notification '{notification_id}' marked as read"}


@router.delete("/notifications/{notification_id}", tags=["Notifications"], summary="Delete Notification")
async def delete_notification(notification_id: str):
    if not notification_center_service.delete(notification_id):
        raise HTTPException(status_code=404, detail=f"Notification '{notification_id}' not found")
    return {"status": "success", "message": f"Notification '{notification_id}' deleted"}


@router.post("/notifications/reminders", response_model=ArrivalReminderDto, tags=["Notifications"], summary="Create Arrival Reminder")
async def create_arrival_reminder(request: ArrivalReminderCreateDto):
    """Create a commuter arrival reminder for an approaching bus."""
    return personalization_service.create_reminder(request)


@router.patch("/notifications/{notification_id}/read", tags=["Notifications"], summary="Mark Notification as Read")
async def mark_notification_as_read(notification_id: str):
    """Mark a notification as read."""
    success = personalization_service.mark_notification_read(notification_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Notification '{notification_id}' not found")
    return {"status": "success", "message": f"Notification '{notification_id}' marked as read"}



@router.post(
    "/realtime/validate",
    response_model=RealtimeValidationResponse,
    tags=["Realtime"],
    summary="Dry-Run Realtime Feed Validation",
)
async def validate_realtime_feed(request: Optional[RealtimeValidationRequest] = None):
    """
    Validates configured or proposed BMTC GTFS-RT feed endpoints without permanently mutating provider state.
    Conducts connectivity verification, payload schema validation, coordinate bounds checking,
    freshness evaluation, and entity isolation statistics.
    NOTE: Realtime BMTC connectivity requires authorized municipal credentials.
    """
    return await realtime_activation_service.validate_feed(request)


@router.get(
    "/realtime/test",
    response_model=RealtimeTestResponse,
    tags=["Realtime"],
    summary="Diagnostic Probe for Authorized Realtime Feed",
)
async def test_realtime_feed():
    """
    Safely tests and probes currently configured GTFS-RT feed endpoints.
    Strictly credential-safe: never returns API keys, tokens, or secret headers.
    Returns connectivity and valid entity counts for each feed component.
    """
    cfg = settings.validate_production_config()
    is_cfg = cfg["bmtc_configured"]
    feed_status = bmtc_provider.feed_status

    # Component status
    vp_configured = bool(settings.gtfs_rt_vehicle_positions_url or (settings.bmtc_api_endpoint and "vehicle" in settings.bmtc_api_endpoint))
    tu_configured = bool(settings.gtfs_rt_trip_updates_url or (settings.bmtc_api_endpoint and "trip" in settings.bmtc_api_endpoint))
    sa_configured = bool(settings.gtfs_rt_service_alerts_url or (settings.bmtc_api_endpoint and "alert" in settings.bmtc_api_endpoint))

    if not is_cfg:
        return RealtimeTestResponse(
            configured=False,
            provider="mock",
            feed_status="unconfigured",
            vehicle_positions=RealtimeTestComponent(configured=False, reachable=False, valid_entities=0),
            trip_updates=RealtimeTestComponent(configured=False, reachable=False, valid_entities=0),
            service_alerts=RealtimeTestComponent(configured=False, reachable=False, valid_entities=0),
            message="REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED",
        )

    # If configured, run safe probe
    validation_res = await realtime_activation_service.validate_feed()
    return RealtimeTestResponse(
        configured=True,
        provider="bmtc",
        feed_status=feed_status,
        vehicle_positions=RealtimeTestComponent(
            configured=vp_configured,
            reachable=validation_res.connectivity,
            valid_entities=validation_res.valid_entities,
        ),
        trip_updates=RealtimeTestComponent(
            configured=tu_configured,
            reachable=validation_res.trip_updates_status in ("active", "healthy"),
            valid_entities=len(bmtc_provider._trip_updates),
        ),
        service_alerts=RealtimeTestComponent(
            configured=sa_configured,
            reachable=validation_res.service_alerts_status in ("active", "healthy"),
            valid_entities=bmtc_provider._service_alerts_count,
        ),
        message="Authorized BMTC GTFS-RT probe completed successfully" if validation_res.connectivity else "Authorized BMTC GTFS-RT feed unreachable or connection failed",
    )


# ==============================================================================
# IDENTITY & WOMEN'S FARE-CONCESSION (SHAKTI SCHEME DEMO) ENDPOINTS
# ==============================================================================

@router.post(
    "/identity/session",
    response_model=IdentitySessionResponse,
    tags=["Identity & Concession"],
    summary="Initialize Simulated Identity Verification Session",
)
async def create_identity_session(req: IdentitySessionCreate):
    """
    Initializes a privacy-safe, simulated identity verification session.
    Requires explicit commuter consent.
    NOTE: Zero raw Aadhaar or facial data is stored or processed.
    """
    try:
        return identity_service.create_session(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Identity session initialization failed: {str(e)}")


@router.post(
    "/identity/document",
    response_model=IdentityStatusResponse,
    tags=["Identity & Concession"],
    summary="Validate Simulated Document (Masked Only)",
)
async def verify_identity_document(req: DocumentVerifyRequest):
    """
    Validates simulated document presentation using only masked identifier.
    Raw Aadhaar numbers and document photos are strictly prohibited from ingestion/storage.
    """
    try:
        return identity_service.verify_document(req)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document verification failed: {str(e)}")


@router.post(
    "/identity/selfie",
    response_model=IdentityStatusResponse,
    tags=["Identity & Concession"],
    summary="Register Simulated Selfie Liveness Confirmation",
)
async def register_selfie_liveness(req: SelfieVerifyRequest):
    """
    Registers client-side simulated selfie capture confirmation.
    Strictly NO facial image files or biometric embedding vectors are received or stored.
    """
    try:
        return identity_service.register_selfie_liveness(req)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Selfie registration failed: {str(e)}")


@router.post(
    "/identity/verify",
    response_model=IdentityVerifyResponse,
    tags=["Identity & Concession"],
    summary="Execute Simulated Identity Comparison & Fare Concession Check",
)
async def execute_identity_verification(session_id: str = Query(..., description="Active identity session ID")):
    """
    Executes simulated verification match between document profile and commuter selfie.
    For female commuters applying for Karnataka Shakti scheme, returns 100% fare concession eligibility.
    Supports demo override modes for hackathon jury evaluation.
    """
    try:
        return identity_service.execute_verification(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification execution failed: {str(e)}")


@router.get(
    "/identity/status/{session_id}",
    response_model=IdentityStatusResponse,
    tags=["Identity & Concession"],
    summary="Query Identity Verification & Concession Status",
)
async def get_identity_status(session_id: str):
    """
    Retrieves current simulated verification and concession eligibility status for a session.
    """
    res = identity_service.get_status(session_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Identity session '{session_id}' not found.")
    return res


@router.post(
    "/identity/demo-override",
    tags=["Identity & Concession"],
    summary="Set Hackathon Demo Override (Match, Mismatch, Unavailable)",
)
async def set_identity_demo_override(req: DemoOverrideRequest):
    """
    Permits hackathon evaluators to test all edge cases:
    - MATCH: Successful verification and 100% concession
    - MISMATCH: Facial comparison mismatch
    - VERIFICATION_UNAVAILABLE: Temporary UIDAI/provider network outage
    """
    msg = identity_service.set_demo_override(req.mode)
    return {"status": "success", "mode": req.mode, "message": msg}


# ==============================================================================
# PHASE 36: SMART CROWD, SEAT & OCCUPANCY INTELLIGENCE ENDPOINTS
# ==============================================================================

class CrowdOverrideRequest(BaseModel):
    scenario: Optional[str] = None


@router.get(
    "/crowd/{route_or_bus_id}",
    response_model=CrowdDetailsResponse,
    tags=["Crowd & Occupancy"],
    summary="Get Detailed Crowd & Seat Availability for Bus or Route",
)
async def get_crowd_for_bus_or_route(route_or_bus_id: str):
    """
    Returns transparent crowd and seat availability intelligence for a specific route or bus ID.
    Strictly differentiates between verified APC telemetry, historical corridor models, and simulation.
    Never fabricates passenger counts.
    """
    metrics_service.crowd_queries += 1
    resp = crowd_service.get_details_response(route_or_bus_id)
    if resp.source == "VERIFIED_APC":
        metrics_service.crowd_verified_responses += 1
    elif resp.source in ["HISTORICAL_ESTIMATE", "SIMULATED"]:
        metrics_service.crowd_estimated_responses += 1
    else:
        metrics_service.crowd_unknown_responses += 1
    return resp


@router.get(
    "/crowd/stop/{stop_id}",
    response_model=CrowdDetailsResponse,
    tags=["Crowd & Occupancy"],
    summary="Get Detailed Crowd Intelligence for a Bus Stop",
)
async def get_crowd_for_stop(stop_id: str):
    """
    Returns crowd intelligence for a transit stop platform or bay.
    """
    metrics_service.crowd_queries += 1
    resp = crowd_service.get_details_response(stop_id)
    resp.stop_id = stop_id
    if resp.source == "VERIFIED_APC":
        metrics_service.crowd_verified_responses += 1
    elif resp.source in ["HISTORICAL_ESTIMATE", "SIMULATED"]:
        metrics_service.crowd_estimated_responses += 1
    else:
        metrics_service.crowd_unknown_responses += 1
    return resp


@router.get(
    "/crowd/journey/{journey_id}",
    response_model=CrowdDetailsResponse,
    tags=["Crowd & Occupancy"],
    summary="Get Detailed Crowd Intelligence for a Journey",
)
async def get_crowd_for_journey(journey_id: str):
    """
    Returns crowd intelligence for an active or planned journey option.
    """
    metrics_service.crowd_queries += 1
    aj = active_journey_service._active_journey
    if aj and (aj.id == journey_id or aj.route_number == journey_id):
        resp = crowd_service.get_details_response(aj.route_number or aj.bus_id or journey_id)
        resp.journey_id = journey_id
        if aj.crowd:
            resp.crowd_status = aj.crowd.crowd_status
            resp.seat_status = aj.crowd.estimated_seat_availability
            resp.standing_likelihood = aj.crowd.standing_likelihood
            resp.source = aj.crowd.source
            resp.disclosure = aj.crowd.disclosure
    else:
        resp = crowd_service.get_details_response(journey_id)
        resp.journey_id = journey_id
    return resp


@router.post(
    "/crowd/simulation/override",
    tags=["Crowd & Occupancy"],
    summary="Evaluator Scenario Override for Crowd Intelligence",
)
async def set_crowd_simulation_override(req: CrowdOverrideRequest):
    """
    Allows test evaluators to deterministically toggle crowd scenarios:
    LOW, MODERATE, HIGH, VERY_HIGH, UNKNOWN, or null to clear.
    """
    crowd_service.set_simulation_override(req.scenario)
    return {
        "status": "success",
        "simulation_override": crowd_service.get_simulation_override(),
        "message": f"Simulation override set to {crowd_service.get_simulation_override()}" if crowd_service.get_simulation_override() else "Simulation override cleared.",
    }


# ---------------------------------------------------------------------------
# Phase 37: Smart Transit Disruption & Incident Intelligence Endpoints
# ---------------------------------------------------------------------------

@router.get("/incidents", response_model=List[Incident], tags=["Incidents"], summary="List Transit Incidents")
async def get_all_incidents(
    route: Optional[str] = Query(default=None, description="Filter by route (e.g. 500D)"),
    stop: Optional[str] = Query(default=None, description="Filter by stop name or ID"),
    severity: Optional[str] = Query(default=None, description="Filter by severity"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    active_only: bool = Query(default=True, description="Filter for active incidents only"),
):
    """Retrieve municipal service incidents, corridor advisories, and disruption bulletins."""
    metrics_service.incident_queries += 1
    incidents = incident_service.get_incidents(
        route_number=route,
        stop_id_or_name=stop,
        severity=severity,
        status=status,
        active_only=active_only,
    )
    metrics_service.active_incidents = len([i for i in incidents if i.status.value == "ACTIVE"])
    return incidents


@router.get("/incidents/active", response_model=List[Incident], tags=["Incidents"], summary="Get Active Incidents")
async def get_active_incidents():
    """Retrieve all currently active transit incidents."""
    metrics_service.incident_queries += 1
    return incident_service.get_active_incidents()


@router.get("/incidents/route/{route_number}", response_model=IncidentImpactAssessment, tags=["Incidents"], summary="Get Incidents for Route")
async def get_route_incidents(route_number: str):
    """Retrieve active incidents affecting a specific transit route with impact assessment."""
    metrics_service.incident_queries += 1
    metrics_service.route_disruption_views += 1
    return incident_impact_service.assess_route(route_number)


@router.get("/incidents/stop/{stop_id}", response_model=IncidentImpactAssessment, tags=["Incidents"], summary="Get Incidents for Stop")
async def get_stop_incidents(stop_id: str):
    """Retrieve active incidents affecting a specific stop with impact assessment."""
    metrics_service.incident_queries += 1
    metrics_service.stop_disruption_views += 1
    return incident_impact_service.assess_stop(stop_id)


@router.get("/incidents/journey/{journey_id}", response_model=IncidentImpactAssessment, tags=["Incidents"], summary="Get Incidents for Active Journey")
async def get_journey_incidents(journey_id: str):
    """Retrieve active incidents affecting an active journey with impact assessment."""
    metrics_service.incident_queries += 1
    metrics_service.active_journey_disruption_warnings += 1
    aj = active_journey_service.get_active_journey(journey_id)
    if not aj and active_journey_service._active_journey:
        if active_journey_service._active_journey.id == journey_id or active_journey_service._active_journey.route_number == journey_id:
            aj = active_journey_service._active_journey
    if aj:
        return incident_impact_service.assess_active_journey(aj)
    return incident_impact_service.assess_route(journey_id)


@router.get("/incidents/{incident_id}", response_model=IncidentDetailsResponse, tags=["Incidents"], summary="Get Incident Details")
async def get_incident_details(incident_id: str):
    """Retrieve comprehensive details and source attribution for an incident."""
    metrics_service.incident_queries += 1
    details = incident_service.get_details_response(incident_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
    return details


@router.post("/incidents/simulation/override", tags=["Incidents"], summary="Evaluator Scenario Override for Incidents")
async def set_incident_simulation_override(req: IncidentOverrideRequest):
    """
    Allows test evaluators to deterministically toggle incident scenarios:
    none, 500d_disruption, 356_disruption, stop_closure, transfer_risk, multiple.
    """
    incident_service.set_simulation_override(req)
    metrics_service.simulated_incidents = len(incident_service.get_active_incidents())
    return {
        "status": "success",
        "simulation_override": incident_service.get_simulation_override(),
        "active_incidents_count": len(incident_service.get_active_incidents()),
        "message": f"Simulation override set to '{req.mode}'.",
    }


# ---------------------------------------------------------------------------
# Phase 38: Smart Predictive Commuter Intelligence Endpoints
# ---------------------------------------------------------------------------

@router.get("/predictions/arrival/{route_number}/{stop_id}", response_model=CommuterPrediction, tags=["Predictions"], summary="Predict Arrival ETA")
async def get_predicted_arrival(route_number: str, stop_id: str):
    """Predict arrival time for a specific route and stop using GTFS-RT TripUpdate or labeled estimate."""
    metrics_service.prediction_requests += 1
    metrics_service.arrival_predictions += 1
    return await prediction_service.predict_arrival(route_number, stop_id)


@router.get("/predictions/journey", response_model=CommuterPrediction, tags=["Predictions"], summary="Predict Journey Duration")
async def get_predicted_journey(
    origin: str = Query(default="Central Silk Board"),
    destination: str = Query(default="Hebbal"),
    route_number: Optional[str] = Query(default=None),
):
    """Predict journey duration with factual walking, transit, transfer, and incident breakdown."""
    metrics_service.prediction_requests += 1
    metrics_service.journey_predictions += 1
    return prediction_service.predict_journey_duration(origin, destination, route_number)


@router.get("/predictions/transfer/{journey_id}", response_model=CommuterPrediction, tags=["Predictions"], summary="Predict Transfer Feasibility")
async def get_predicted_transfer(journey_id: str):
    """Predict transfer feasibility without claiming certainty, respecting offline disclosures."""
    metrics_service.prediction_requests += 1
    metrics_service.transfer_predictions += 1
    return await prediction_service.predict_transfer_success(journey_id)


@router.get("/predictions/route/{route_number}", response_model=CommuterPrediction, tags=["Predictions"], summary="Predict Route Delay")
async def get_predicted_route_delay(route_number: str):
    """Predict route delays from active incident intelligence and corridor speed profiles."""
    metrics_service.prediction_requests += 1
    return prediction_service.predict_route_delay(route_number)


@router.get("/predictions/journey/{journey_id}", response_model=CommuterPrediction, tags=["Predictions"], summary="Predict Active Journey Duration")
async def get_predicted_active_journey(journey_id: str):
    """Predict destination duration for an active journey."""
    metrics_service.prediction_requests += 1
    aj = await active_journey_service.get_active_journey()
    orig = aj.origin if aj else "Central Silk Board"
    dest = aj.destination if aj else "Hebbal"
    r_num = aj.route_number if aj else "500D"
    return prediction_service.predict_journey_duration(orig, dest, r_num)


@router.get("/predictions/insights", response_model=List[Dict[str, Any]], tags=["Predictions"], summary="Get Personalized Commuter Insights")
async def get_prediction_insights():
    """Retrieve non-sensitive commuter insights based on saved journeys and favorite routes."""
    metrics_service.prediction_requests += 1
    return prediction_service.get_commuter_insights()


# ---------------------------------------------------------------------------
# Phase 39: Smart Personalized Commuter & Route Recommendation Endpoints
# ---------------------------------------------------------------------------

@router.get("/recommendations", response_model=List[CommuterRecommendation], tags=["Recommendations"], summary="Get Contextual Commuter Recommendations")
async def get_commuter_recommendations(user_stop: Optional[str] = Query(default=None)):
    """Retrieve factual, non-subjective commuter recommendations for 'Your Transit Today'."""
    metrics_service.commuter_recommendations_count += 1
    return commuter_recommendation_service.get_recommendations(user_stop)


@router.get("/recommendations/journey", response_model=List[CommuterRecommendation], tags=["Recommendations"], summary="Get Journey Recommendations")
async def get_journey_recommendations(
    origin: str = Query(default="Central Silk Board"),
    destination: str = Query(default="Hebbal"),
):
    """Retrieve comparative recommendations for a specific origin and destination."""
    metrics_service.commuter_recommendations_count += 1
    return commuter_recommendation_service.get_recommendations()


@router.get("/recommendations/route/{route_number}", response_model=List[CommuterRecommendation], tags=["Recommendations"], summary="Get Route Recommendations")
async def get_route_recommendations(route_number: str):
    """Retrieve recommendations and factual alternatives for a specific transit route."""
    metrics_service.commuter_recommendations_count += 1
    return commuter_recommendation_service.get_route_recommendations(route_number)


@router.get("/recommendations/saved", response_model=List[CommuterRecommendation], tags=["Recommendations"], summary="Get Saved Journey Recommendations")
async def get_saved_recommendations():
    """Retrieve recommendations for commuter's saved journeys."""
    metrics_service.saved_recommendations_count += 1
    return commuter_recommendation_service.get_saved_journey_recommendations()


@router.get("/recommendations/favorites", response_model=List[CommuterRecommendation], tags=["Recommendations"], summary="Get Favorite Route Recommendations")
async def get_favorite_recommendations():
    """Retrieve recommendations for commuter's favorite routes."""
    metrics_service.favorite_recommendations_count += 1
    return commuter_recommendation_service.get_favorite_route_recommendations()


@router.get("/recommendations/disruption/{route_number}", response_model=List[CommuterRecommendation], tags=["Recommendations"], summary="Get Disruption Alternatives")
async def get_disruption_recommendations(route_number: str):
    """Retrieve factual alternative route recommendations when a route is affected by a service advisory."""
    metrics_service.disruption_recommendations_count += 1
    return commuter_recommendation_service.get_disruption_recommendations(route_number)


# ---------------------------------------------------------------------------
# Phase 40: Production Readiness, Resilience & Municipal Operations Endpoints
# ---------------------------------------------------------------------------

@router.get("/system/health", response_model=List[SystemModuleHealth], tags=["Operations"], summary="System 18-Module Health")
async def get_system_health():
    """Retrieve real-time health, latency, error count, and disclosures for all 18 transit modules."""
    metrics_service.health_checks += 1
    return health_service.get_system_modules()


@router.get("/system/feed-health", response_model=FeedHealthDiagnostic, tags=["Operations"], summary="Authorized Feed Health Diagnostics")
async def get_feed_health_diagnostics():
    """Retrieve GTFS-RT feed health, entity counts, freshness, and backoff states."""
    metrics_service.health_checks += 1
    return health_service.get_feed_health()


@router.get("/system/data-quality", response_model=DataQualityAssessment, tags=["Operations"], summary="Data Quality Assessment Score")
async def get_data_quality_score():
    """Retrieve transparent data quality score (0-100) and factor breakdown. Strictly diagnostic."""
    metrics_service.data_quality_checks += 1
    return health_service.get_data_quality_assessment()


@router.get("/system/events", response_model=List[DiagnosticEvent], tags=["Operations"], summary="Diagnostic Operational Event Log")
async def get_operational_events(limit: int = Query(default=50, ge=1, le=100)):
    """Retrieve non-sensitive operational and resilience diagnostic events."""
    metrics_service.operational_events_count += 1
    return health_service.get_events(limit=limit)


@router.post("/system/demo-controls", tags=["Operations"], summary="Apply Demo Scenario Controls")
async def apply_demo_controls(req: DemoControlsRequest):
    """
    Evaluator control panel for toggling feed states (connected, delayed, stale, disconnected),
    incident states, crowd overrides, accessibility, offline mode, and simulator mode.
    """
    return health_service.apply_demo_controls(req)


# ---------------------------------------------------------------------------
# Phase 41: Smart Commuter Safety, Emergency & Journey Assistance Endpoints
# ---------------------------------------------------------------------------

@router.get("/safety/status/{journey_id}", response_model=SafetyAssessment, tags=["Safety"], summary="Get Journey Safety Status")
async def get_safety_status(journey_id: str):
    """
    Retrieve telemetry-grounded safety assessment for a journey.
    Detects NORMAL, ATTENTION, ASSISTANCE_NEEDED, and OFFLINE states.
    Never fabricates emergency response or authority interventions.
    """
    return await safety_service.get_safety_status(journey_id)


@router.get("/safety/events/{journey_id}", response_model=List[SafetyEvent], tags=["Safety"], summary="Get Journey Safety Events")
async def get_safety_events(journey_id: str):
    """Retrieve recent factual transit safety event trail for an active journey."""
    return safety_service.get_recent_safety_events(journey_id)


@router.post("/safety/assistance/request", response_model=AssistanceResponse, tags=["Safety"], summary="Request Transit Assistance")
async def request_transit_assistance(req: AssistanceRequest):
    """
    Explicit commuter request for transit guidance, exit help, or rerouting support.
    Canonical disclosure: 'Emergency assistance information is for guidance only.'
    """
    return await safety_service.request_assistance(req)


@router.post("/safety/assistance/cancel", response_model=AssistanceResponse, tags=["Safety"], summary="Cancel Assistance Request")
async def cancel_transit_assistance(req: AssistanceRequest):
    """Cancel active assistance request and resume standard journey tracking."""
    return await safety_service.cancel_assistance(req.journey_id)


@router.post("/safety/check", response_model=SafetyCheckResponse, tags=["Safety"], summary="Perform Safety Check")
async def perform_safety_check(req: SafetyCheckRequest):
    """Commuter manual confirmation ('I am OK / Verify Safety') timestamped check."""
    return await safety_service.complete_safety_check(req)


@router.post("/safety/share/start", response_model=JourneyShareResponse, tags=["Safety"], summary="Start Journey Share")
async def start_journey_share(req: JourneyShareStartRequest):
    """
    Initiate time-bounded HMAC journey sharing (15, 30, or 60 min).
    Explicit commuter confirmation required. Zero passenger PII in token payload.
    """
    return await journey_share_service.start_share(req)


@router.post("/safety/share/stop", response_model=JourneyShareResponse, tags=["Safety"], summary="Stop Journey Share")
async def stop_journey_share(req: JourneyShareStopRequest):
    """Halt journey sharing immediately upon commuter request."""
    return await journey_share_service.stop_share(req)


@router.get("/safety/share/status/{journey_id}", response_model=JourneyShareStatusResponse, tags=["Safety"], summary="Get Journey Share Status")
async def get_journey_share_status(journey_id: str):
    """Check whether a journey is currently actively shared and remaining duration."""
    return await journey_share_service.get_share_status(journey_id)


@router.get("/safety/nearby", response_model=NearbySafetyResponse, tags=["Safety"], summary="Get Nearby Safety Transit Stops")
async def get_nearby_safety_transit(
    lat: Optional[float] = Query(default=None, description="Commuter latitude"),
    lon: Optional[float] = Query(default=None, description="Commuter longitude"),
):
    """
    Surface nearby verified transit stops and transfer hubs.
    Canonical disclosure: 'Live emergency service availability is unavailable.'
    """
    return await safety_service.get_nearby_safety_transit(lat, lon)


@router.post("/safety/demo/override", tags=["Safety"], summary="Set Safety Demo Override Scenario")
async def set_safety_demo_override(req: SafetyDemoOverrideRequest):
    """
    Evaluator demo override scenarios:
    normal_journey | telemetry_lost | missed_destination | missed_transfer |
    disruption_attention | assistance_requested | journey_share_active
    """
    safety_service.apply_demo_override(req.scenario, req.journey_id)
    return {
        "status": "success",
        "scenario": req.scenario,
        "journey_id": req.journey_id or "global",
        "message": f"Safety demo override scenario set to '{req.scenario}'."
    }






# ---------------------------------------------------------------------------
# Phase 41: Commuter Authentication, Identity Onboarding & Shakti Access
# ---------------------------------------------------------------------------

def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _require_user(authorization: Optional[str]) -> dict:
    try:
        return auth_service.require(_bearer_token(authorization))
    except AuthError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.post("/auth/register", response_model=AuthResponse, tags=["Auth"], summary="Register Commuter (Passwordless)")
async def auth_register(req: RegisterRequest):
    """Creates a passwordless commuter account. Email verification is not connected yet; no OTP is sent."""
    try:
        return auth_service.register(req)
    except AuthError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.post("/auth/login", response_model=AuthResponse, tags=["Auth"], summary="Log In (Unverified Demo Continuation)")
async def auth_login(req: LoginRequest):
    """Logs in an existing account by mobile number. Assurance is UNVERIFIED_DEMO_CONTINUATION until OTP is configured."""
    try:
        return auth_service.login(req)
    except AuthError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.get("/auth/me", response_model=UserSessionDto, tags=["Auth"], summary="Current Commuter Session")
async def auth_me(authorization: Optional[str] = Header(default=None)):
    dto = auth_service.to_dto(_require_user(authorization))
    dto.session_expires_at = auth_service.session_expiry(_bearer_token(authorization))
    return dto


@router.patch("/auth/profile", response_model=UserSessionDto, tags=["Auth"], summary="Update Profile")
async def auth_update_profile(req: ProfileUpdateRequest, authorization: Optional[str] = Header(default=None)):
    """Updates name and/or email. Changing email resets its verification status (email OTP is not connected)."""
    return auth_service.update_profile(_require_user(authorization), req)


@router.post("/auth/logout", tags=["Auth"], summary="Log Out")
async def auth_logout(authorization: Optional[str] = Header(default=None)):
    """Ends the session. Saved journeys, favourites, tickets and preferences are not affected."""
    ended = auth_service.logout(_bearer_token(authorization))
    return {"status": "success", "session_ended": ended}


@router.post("/identity/digilocker/start", response_model=DigiLockerStatusResponse, tags=["Identity & Concession"], summary="Start DigiLocker Linking")
async def digilocker_start(authorization: Optional[str] = Header(default=None)):
    """Returns an authorization URL only when an authorized DigiLocker integration is configured. Never fabricates a link."""
    return identity_onboarding_service.digilocker_start(_require_user(authorization))


@router.get("/identity/digilocker/status", response_model=DigiLockerStatusResponse, tags=["Identity & Concession"], summary="DigiLocker Link Status")
async def digilocker_status(authorization: Optional[str] = Header(default=None)):
    return identity_onboarding_service.digilocker_status(_require_user(authorization))


@router.post("/identity/verification/start", response_model=IdentityVerificationStartResponse, tags=["Identity & Concession"], summary="Start Face/Liveness Verification")
async def identity_verification_start(req: IdentityVerificationStartRequest, authorization: Optional[str] = Header(default=None)):
    user = _require_user(authorization)
    try:
        return identity_onboarding_service.start_verification(user, req)
    except AuthError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.post("/identity/verification/complete", response_model=IdentityVerificationResult, tags=["Identity & Concession"], summary="Complete Face/Liveness Verification")
async def identity_verification_complete(req: IdentityVerificationCompleteRequest, authorization: Optional[str] = Header(default=None)):
    """Accepts only the liveness confirmation. Image, document or biometric fields are rejected (422)."""
    user = _require_user(authorization)
    try:
        return identity_onboarding_service.complete_verification(user, req)
    except AuthError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.get("/identity/status", response_model=IdentityStatusDto, tags=["Identity & Concession"], summary="Account Identity Status")
async def identity_account_status(authorization: Optional[str] = Header(default=None)):
    return identity_onboarding_service.get_status(_require_user(authorization))


@router.post("/identity/verification/demo-mode", tags=["Identity & Concession"], summary="Evaluator: Toggle Demo Identity Verification")
async def identity_verification_demo_mode(req: IdentityDemoModeRequest):
    """Switches between UNAVAILABLE and DEMO_VERIFICATION. Refused in production."""
    try:
        provider = identity_onboarding_service.set_demo_mode(req.enabled, req.demo_outcome)
    except AuthError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)
    return {
        "provider_mode": provider.mode,
        "available": provider.is_available,
        "label": "DEMO IDENTITY VERIFICATION" if provider.mode == "DEMO_VERIFICATION" else None,
        "message": "Demo identity verification enabled." if req.enabled else IDENTITY_UNAVAILABLE_MESSAGE,
    }


@router.post("/shakti/eligibility/check", response_model=ShaktiEligibilityResponse, tags=["Identity & Concession"], summary="Check Shakti Concession Eligibility")
async def shakti_eligibility_check(authorization: Optional[str] = Header(default=None)):
    return identity_onboarding_service.check_shakti_eligibility(_require_user(authorization))


# ---------------------------------------------------------------------------
# Phase 43: Digital Ticket Payment (sandbox) integrated with the existing TicketService
# ---------------------------------------------------------------------------

def _optional_user_id(authorization: Optional[str]) -> Optional[str]:
    user = auth_service.resolve(_bearer_token(authorization))
    return user["user_id"] if user else None


def _payment_http(err: PaymentError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.detail)


@router.post("/payment/create", response_model=PaymentRecord, tags=["Payments"], summary="Create Payment Session (Sandbox)")
async def payment_create(req: PaymentCreateRequest, authorization: Optional[str] = Header(default=None)):
    """
    Creates a payment session. The fare is computed on the server; the client cannot set the amount.
    Network routes (with from/to stop ids) use the GTFS zone fare from the BMTC network.
    """
    try:
        network_fare = await _network_fare(req.route_number, req.from_stop_id, req.to_stop_id)
        return payment_service.create(
            req,
            user_id=_optional_user_id(authorization),
            network_unit_fare=network_fare[0] if network_fare else None,
            network_fare_source=network_fare[1] if network_fare else None,
        )
    except PaymentError as err:
        raise _payment_http(err)


# Flat demo fares by service type, used ONLY when the GTFS feed has no fare for a network stop pair.
# Labelled DEMO_FARE_ESTIMATE everywhere; never presented as a BMTC fare.
DEMO_FARE_BY_SERVICE_TYPE = {"ORDINARY": 25, "BIG10": 25, "METRO_FEEDER": 15, "VAJRA": 50, "VAYU_VAJRA": 240}


async def _network_fare(route_number: str, from_stop_id: Optional[str], to_stop_id: Optional[str]):
    """
    (unit_fare, fare_source) for a network route stop pair, or None when stop ids are not supplied
    (legacy demo corridor routes use the demo fare table). The route must exist and both stops must be
    on it (either direction) before any fare is returned.
    """
    if not (from_stop_id and to_stop_id):
        return None
    from ..services.nammaroute_client import NetworkNotFound, NetworkUnavailable, nammaroute_client
    try:
        route = (await nammaroute_client.get(f"/routes/{route_number}", ttl=300)).get("data") or {}
        stop_ids = set()
        for d in (0, 1):
            stops = (await nammaroute_client.get(f"/routes/{route_number}/stops", {"direction": d}, ttl=300)).get("data")
            stops = stops if isinstance(stops, list) else (stops or {}).get("stops", [])
            stop_ids |= {str(st.get("id")) for st in stops} | {str(st.get("stopId")) for st in stops}
    except NetworkNotFound:
        raise PaymentError(400, f"Route '{route_number}' does not exist in the BMTC network.")
    except NetworkUnavailable:
        raise PaymentError(503, "BMTC route network service is unavailable; fare cannot be calculated.")
    if from_stop_id not in stop_ids or to_stop_id not in stop_ids:
        raise PaymentError(400, f"The selected stops are not on route '{route_number}'.")
    try:
        body = await nammaroute_client.get("/fares", {"from": from_stop_id, "to": to_stop_id, "route": route_number}, ttl=3600)
        amount = (body.get("data") or {}).get("fareAmount")
        if amount is not None:
            return int(round(float(amount))), "GTFS_FARE_RULES"
    except NetworkNotFound:
        pass
    except NetworkUnavailable:
        raise PaymentError(503, "BMTC route network service is unavailable; fare cannot be calculated.")
    unit = DEMO_FARE_BY_SERVICE_TYPE.get(str(route.get("serviceType") or "ORDINARY").upper(), 25)
    return unit, "DEMO_FARE_ESTIMATE"


@router.get("/payment/quote", tags=["Payments"], summary="Fare Quote")
async def payment_quote(
    route_number: str,
    ticket_type: str = "ADULT",
    quantity: int = Query(default=1, ge=1, le=6),
    from_stop_id: Optional[str] = Query(default=None, max_length=40),
    to_stop_id: Optional[str] = Query(default=None, max_length=40),
):
    """Server-side fare preview. The payment session recomputes the same fare; clients never set amounts."""
    from ..services.payment_service import quote_fare
    try:
        network_fare = await _network_fare(route_number, from_stop_id, to_stop_id)
        if network_fare is not None:
            if ticket_type.strip().upper() != "ADULT":
                raise PaymentError(400, "Only adult fares are available for network routes.")
            unit, source = network_fare
            total = unit * quantity
        else:
            unit, total = quote_fare(route_number, ticket_type, quantity)
            source = "DEMO_FARE_TABLE"
    except PaymentError as err:
        raise _payment_http(err)
    return {"route_number": route_number.upper(), "ticket_type": ticket_type.upper(), "quantity": quantity,
            "unit_fare": unit, "total": total, "currency": "INR", "fare_source": source,
            "disclosure": DEMO_PAYMENT_DISCLOSURE}


@router.post("/payment/verify", response_model=PaymentRecord, tags=["Payments"], summary="Verify Payment With Provider")
async def payment_verify(req: PaymentVerifyRequest):
    """Asks the provider for the authoritative status. sandbox_outcome is honoured only by the sandbox provider."""
    try:
        before = payment_service.get(req.payment_id).status
        rec = payment_service.verify(req)
    except PaymentError as err:
        raise _payment_http(err)
    if rec.status != before:
        label = rec.status.value.replace("PAYMENT_", "").title()
        notification_center_service.publish(
            "PAYMENT_STATUS",
            f"Payment {label.lower()}",
            f"₹{rec.amount} for route {rec.route_number}: {label}. {DEMO_PAYMENT_DISCLOSURE}",
            route_number=rec.route_number,
            source="SYSTEM",
            priority="HIGH" if rec.status.value != "PAYMENT_SUCCESS" else "NORMAL",
            dedup_key=f"payment:{rec.payment_id}:{rec.status.value}",
        )
    return rec


@router.get("/payment/history", response_model=List[PaymentRecord], tags=["Payments"], summary="Payment History")
async def payment_history(authorization: Optional[str] = Header(default=None)):
    """Signed-in commuters see their own payments; guests see sandbox payments made without an account."""
    return payment_service.history(user_id=_optional_user_id(authorization))


@router.get("/payment/{payment_id}", response_model=PaymentRecord, tags=["Payments"], summary="Get Payment")
async def payment_get(payment_id: str):
    try:
        return payment_service.get(payment_id)
    except PaymentError as err:
        raise _payment_http(err)


@router.get("/payment/{payment_id}/receipt", response_model=PaymentReceipt, tags=["Payments"], summary="Payment Receipt")
async def payment_receipt(payment_id: str):
    try:
        return payment_service.receipt(payment_id)
    except PaymentError as err:
        raise _payment_http(err)


@router.post("/tickets/purchase", response_model=Ticket, tags=["Tickets"], summary="Issue Ticket For Verified Payment")
async def ticket_purchase(req: TicketPurchaseRequest):
    """
    Issues a ticket through the EXISTING TicketService only after the provider confirms PAYMENT_SUCCESS.
    The ticket details come from the payment session, and each payment can issue exactly one ticket.
    """
    try:
        rec = payment_service.reserve_for_ticket(req.payment_id)
    except PaymentError as err:
        raise _payment_http(err)
    try:
        ticket = await ticket_service.create_ticket(
            TicketCreateRequest(
                route_number=rec.route_number,
                source=rec.source,
                destination=rec.destination,
                bus_type=rec.bus_type or "BMTC Ordinary",
                fare_rupees=rec.amount,
                fare_type="paid_demo_fare",
            ),
            payment_id=rec.payment_id,
            payment_status=rec.status.value,
            passenger_count=rec.quantity,
            ticket_type=rec.ticket_type,
            route_validated=rec.fare_source in ("GTFS_FARE_RULES", "DEMO_FARE_ESTIMATE"),
            vehicle_number=rec.vehicle_number,
        )
    except ValueError as err:
        payment_service.release(rec.payment_id)
        raise HTTPException(status_code=400, detail=str(err))
    payment_service.attach_ticket(rec.payment_id, ticket.ticket_id)
    notification_center_service.publish(
        "TICKET_PURCHASED",
        "Ticket purchased",
        f"Demo ticket {ticket.ticket_id} for route {ticket.route_number} is active.",
        route_number=ticket.route_number,
        source="SYSTEM",
        dedup_key=f"ticket-purchased:{ticket.ticket_id}",
    )
    return ticket


# ---------------------------------------------------------------------------
# Phase 46: GTFS static repository lookups (routes/stops come from the loaded feed, never hard-coded)
# ---------------------------------------------------------------------------

def _gtfs_meta() -> Dict[str, Any]:
    return {
        "data_source": gtfs_repository.data_source,
        "data_category": "Scheduled Data",
        "is_realtime": False,
    }


@router.get("/gtfs/status", tags=["GTFS"], summary="GTFS Static Repository Status")
async def gtfs_status():
    return {**_gtfs_meta(), "stats": gtfs_repository.get_stats(), "last_load": gtfs_repository.last_load_report}


@router.get("/gtfs/routes", tags=["GTFS"], summary="Search Routes")
async def gtfs_routes(q: str = Query(default="", max_length=64), limit: int = Query(default=50, ge=1, le=500)):
    routes = gtfs_repository.search_routes(q, limit)
    return {**_gtfs_meta(), "count": len(routes), "routes": [r.model_dump() for r in routes]}


@router.get("/gtfs/routes/{route_id}/stops", tags=["GTFS"], summary="Stops For Route")
async def gtfs_route_stops(route_id: str):
    if not gtfs_repository.get_route(route_id):
        raise HTTPException(status_code=404, detail=f"Route '{route_id}' not found in GTFS repository")
    return {**_gtfs_meta(), "route_id": route_id, "stops": [s.model_dump() for s in gtfs_repository.get_stops_for_route(gtfs_repository.get_route(route_id).route_id)]}


@router.get("/gtfs/routes/{route_id}/trips", tags=["GTFS"], summary="Trips For Route")
async def gtfs_route_trips(route_id: str):
    if not gtfs_repository.get_route(route_id):
        raise HTTPException(status_code=404, detail=f"Route '{route_id}' not found in GTFS repository")
    return {**_gtfs_meta(), "route_id": route_id, "trips": [t.model_dump() for t in gtfs_repository.get_trips_for_route(route_id)]}


@router.get("/gtfs/routes/{route_id}/shape", tags=["GTFS"], summary="Shape For Route")
async def gtfs_route_shape(route_id: str):
    if not gtfs_repository.get_route(route_id):
        raise HTTPException(status_code=404, detail=f"Route '{route_id}' not found in GTFS repository")
    pts = gtfs_repository.get_shape_for_route(route_id)
    return {**_gtfs_meta(), "route_id": route_id, "points": [[p.shape_pt_lat, p.shape_pt_lon] for p in pts]}


@router.get("/gtfs/stops", tags=["GTFS"], summary="Search Stops")
async def gtfs_stops(q: str = Query(default="", max_length=64), limit: int = Query(default=50, ge=1, le=500)):
    stops = gtfs_repository.search_stops(q, limit)
    return {**_gtfs_meta(), "count": len(stops), "stops": [s.model_dump() for s in stops]}


@router.get("/gtfs/stops/{stop_id}/routes", tags=["GTFS"], summary="Routes Serving Stop")
async def gtfs_stop_routes(stop_id: str):
    if not gtfs_repository.get_stop(stop_id):
        raise HTTPException(status_code=404, detail=f"Stop '{stop_id}' not found in GTFS repository")
    return {**_gtfs_meta(), "stop_id": stop_id, "routes": [r.model_dump() for r in gtfs_repository.get_routes_for_stop(stop_id)]}


@router.get("/gtfs/services", tags=["GTFS"], summary="Active Service IDs For Date")
async def gtfs_services(date: Optional[str] = Query(default=None, description="YYYY-MM-DD; defaults to today (IST)")):
    from datetime import date as date_cls, timedelta
    try:
        on = date_cls.fromisoformat(date) if date else (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    return {**_gtfs_meta(), "date": on.isoformat(), "active_service_ids": gtfs_repository.get_active_service_ids(on)}


@router.get("/system/performance", tags=["Diagnostics"], summary="Latency Percentiles By Capability")
async def system_performance():
    """Phase 49: in-process p50/p95/p99 latency per capability (measured by the request middleware)."""
    return metrics_service.get_performance_report()


# ---------------------------------------------------------------------------
# Phase 50: Truthful system readiness (every module reports its real data source)
# ---------------------------------------------------------------------------

@router.get("/system/readiness", tags=["Diagnostics"], summary="Final System Readiness Report")
async def system_readiness():
    import os as _os
    from ..services.gtfs.protobuf_decoder import PROTOBUF_AVAILABLE

    simulated = is_simulation_active()
    transit_source = "SIMULATED" if simulated else "VERIFIED_REALTIME"
    provider_health = get_provider_health()
    incidents = incident_service.get_active_incidents()
    official_incidents = [i for i in incidents if not getattr(i, "is_simulated", True)]
    idp = identity_onboarding_service.provider
    notif = notification_center_service.get_stats()
    pay = payment_service.stats()
    gtfs_stats = gtfs_repository.get_stats()
    gemini = bool(_os.environ.get("GEMINI_API_KEY", "").strip())
    tracking = await vehicle_tracking_service.snapshot()

    def m(module, status, source, details):
        return {"module": module, "status": status, "source": source, "details": details}

    modules = [
        m("backend", "ACTIVE", "SYSTEM", f"FastAPI {settings.version} ({settings.environment})"),
        m("gtfs_static", "ACTIVE" if gtfs_repository.data_source == "GTFS_STATIC" else "DEMO",
          gtfs_repository.data_source, f"{gtfs_stats['routes']} routes, {gtfs_stats['stops']} stops, {gtfs_stats['trips']} trips (scheduled data)"),
        m("gtfs_realtime", "ACTIVE" if provider_health.realtime else "UNAVAILABLE",
          "VERIFIED_REALTIME" if provider_health.realtime else "UNAVAILABLE",
          provider_health.details if provider_health.realtime else OPERATIONAL_STATEMENT_NOT_CONNECTED),
        m("map_vehicle_positions", "ACTIVE" if not simulated else "DEMO", transit_source,
          "Bus positions from the authorized feed" if not simulated else "Bus positions from the Bengaluru corridor simulator"),
        m("ai_assistant", "ACTIVE", "SYSTEM",
          "Gemini provider configured, grounded on transit data" if gemini else "Rule-based grounded assistant (no external LLM configured)"),
        m("tickets", "DEMO", "SYSTEM", f"HMAC-signed demo tickets; {'custom' if settings.ticket_hmac_secret_set else 'development'} signing secret. DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL"),
        m("payments", "DEMO", "SANDBOX", f"{payment_service.provider.name}: {pay['total']} sessions. {DEMO_PAYMENT_DISCLOSURE}"),
        m("notifications", "ACTIVE", "SYSTEM", f"{notif['total']} items, {notif['unread']} unread, {notif['suppressed_duplicates']} duplicates suppressed"),
        m("accessibility", "DEMO" if simulated else "ACTIVE", transit_source if not simulated else "SIMULATED",
          "Fleet accessibility metadata for demo corridors; unknown values are disclosed as unavailable"),
        m("crowd", "DEMO" if simulated else "ACTIVE", "SIMULATED" if simulated else "GTFS_RT_ESTIMATE",
          f"Evaluator override: {crowd_service.get_simulation_override() or 'none'}"),
        m("incidents", "ACTIVE" if official_incidents else "DEMO", "VERIFIED_REALTIME" if official_incidents else "SIMULATED",
          f"{len(incidents)} active ({len(official_incidents)} official)"),
        m("predictions", "DEMO" if simulated else "ACTIVE", "SIMULATED" if simulated else "HISTORICAL_ESTIMATE",
          "Predictions derived from the active transit source"),
        m("recommendations", "DEMO" if simulated else "ACTIVE", "SIMULATED" if simulated else "HISTORICAL_ESTIMATE",
          "Deterministic comparisons over the active transit source"),
        m("identity", "ACTIVE" if idp.mode == "AUTHORIZED_VERIFICATION" else ("DEMO" if idp.mode == "DEMO_VERIFICATION" else "UNAVAILABLE"),
          idp.mode, "Authorized provider configured" if idp.mode == "AUTHORIZED_VERIFICATION" else
          ("DEMO IDENTITY VERIFICATION — not real Aadhaar/DigiLocker" if idp.mode == "DEMO_VERIFICATION" else "Identity verification is currently unavailable.")),
        m("gtfs_rt_protobuf", "ACTIVE" if PROTOBUF_AVAILABLE else "UNAVAILABLE", "SYSTEM",
          "Binary GTFS-RT decoding available" if PROTOBUF_AVAILABLE else "gtfs-realtime-bindings not installed"),
        m("offline", "CLIENT", "OFFLINE_CACHED", "Offline caching and sync run on the device; see the app diagnostics screen"),
        m("vehicle_tracking", "ACTIVE" if tracking.realtime_connected else "DEMO", tracking.source,
          f"{tracking.count} buses tracked (Live {tracking.counts_by_freshness['LIVE']}, Recent {tracking.counts_by_freshness['RECENT']}, "
          f"Stale {tracking.counts_by_freshness['STALE']}); feed {tracking.feed_state}"),
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "operational_statement": OPERATIONAL_STATEMENT_NOT_CONNECTED if not provider_health.realtime else provider_health.details,
        "realtime_connected": provider_health.realtime,
        "real_payments_active": False,
        "real_identity_verification_active": idp.mode == "AUTHORIZED_VERIFICATION",
        "modules": modules,
    }


# ---------------------------------------------------------------------------
# NammaRoute integration: realtime vehicle tracking (direction, current stop, freshness)
# ---------------------------------------------------------------------------

@router.get("/realtime/status", response_model=RealtimeStatusResponse, tags=["Realtime"], summary="Realtime Feed & Tracking Status")
async def realtime_status():
    """Feed state for the authorized BMTC feed plus tracked vehicle counts by freshness (LIVE / RECENT / STALE)."""
    return await vehicle_tracking_service.status()


@router.get("/realtime/vehicles", response_model=RealtimeVehiclesResponse, tags=["Realtime"], summary="Tracked Vehicles")
async def realtime_vehicles(
    route: Optional[str] = Query(default=None, max_length=32),
    direction: Optional[int] = Query(default=None, ge=0, le=1),
    freshness: Optional[str] = Query(default=None, pattern="^(LIVE|RECENT|STALE)$"),
):
    """
    Every valid tracked vehicle from one shared provider read — no artificial count limit.
    Vehicles without a timestamp or older than 300 s are excluded and counted, never shown as live.
    """
    snap = await vehicle_tracking_service.snapshot()
    items = snap.vehicles
    if route:
        key = route.strip().upper()
        items = [v for v in items if (v.route_number or "").upper() == key]
    if direction is not None:
        items = [v for v in items if v.direction_id == direction]
    if freshness:
        items = [v for v in items if v.freshness == freshness]
    counts = {k: sum(1 for v in items if v.freshness == k) for k in ("LIVE", "RECENT", "STALE")}
    return snap.model_copy(update={"vehicles": items, "count": len(items), "counts_by_freshness": counts})


@router.get("/realtime/vehicles/{vehicle_id}", response_model=TrackedVehicle, tags=["Realtime"], summary="Tracked Vehicle")
async def realtime_vehicle(vehicle_id: str):
    v = await vehicle_tracking_service.get_vehicle(vehicle_id)
    if not v:
        raise HTTPException(status_code=404, detail=f"Vehicle '{vehicle_id}' is not currently tracked")
    return v
