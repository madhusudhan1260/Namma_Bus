import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..models.safety import (
    AssistanceRequest,
    AssistanceResponse,
    NearbySafetyResponse,
    NearbySafetyTransitItem,
    SafetyAssessment,
    SafetyCheckRequest,
    SafetyCheckResponse,
    SafetyEvent,
    SafetyEventType,
    SafetyStatus,
)
from ..models.transit import ActiveJourney, JourneyState
from .active_journey_service import active_journey_service
from .alert_service import alert_service
from .gtfs.repository import gtfs_repository
from .incident_impact_service import incident_impact_service
from .journey_share_service import journey_share_service
from .metrics_service import metrics_service
from .provider_factory import get_transit_provider

logger = logging.getLogger("nammablr.safety_service")


class SafetyService:
    """
    Phase 41 Smart Commuter Safety, Emergency & Journey Assistance Service.
    Monitors transit journeys, identifies conditions requiring commuter attention
    (missed transfer, telemetry loss, disruptions, destination approaching),
    manages explicit commuter assistance requests, and surfaces verified nearby transit stops.
    Strictly avoids fabricating emergency services, police responses, or medical arrivals.
    """

    DEFAULT_DISCLOSURE = "Safety status is based on the available transit data."
    EMERGENCY_DISCLOSURE = "Emergency assistance information is for guidance only."
    LIVE_EMERGENCY_UNAVAILABLE_DISCLOSURE = "Live emergency service availability is unavailable."

    def __init__(self):
        # journey_id -> list of SafetyEvent
        self._events: Dict[str, List[SafetyEvent]] = {}
        # journey_id -> bool (flag for explicit assistance requested)
        self._assistance_requests: Dict[str, dict] = {}
        # journey_id -> datetime of last safety check
        self._last_safety_checks: Dict[str, datetime] = {}
        # Demo scenario override: journey_id -> scenario name
        self._demo_overrides: Dict[str, str] = {}

    def record_safety_event(
        self,
        journey_id: str,
        event_type: str,
        status: str,
        route_number: Optional[str] = None,
        current_stop: Optional[str] = None,
        next_stop: Optional[str] = None,
        destination: Optional[str] = None,
        details: Optional[str] = None,
        source: str = "simulated",
    ) -> SafetyEvent:
        event = SafetyEvent(
            event_id=f"safe-evt-{uuid.uuid4().hex[:8]}",
            journey_id=journey_id,
            event_type=event_type,
            status=status,
            route_number=route_number,
            current_stop=current_stop,
            next_stop=next_stop,
            destination=destination,
            source=source,
            disclosure=self.DEFAULT_DISCLOSURE,
            created_at=datetime.now(timezone.utc),
            details=details,
        )
        if journey_id not in self._events:
            self._events[journey_id] = []
        self._events[journey_id].insert(0, event)
        if len(self._events[journey_id]) > 50:
            self._events[journey_id] = self._events[journey_id][:50]

        metrics_service.safety_events += 1
        return event

    def get_recent_safety_events(self, journey_id: str) -> List[SafetyEvent]:
        return self._events.get(journey_id, [])

    async def get_safety_status(self, journey_id: Optional[str] = None) -> SafetyAssessment:
        """
        Evaluates commuter safety state for the active journey or designated journey ID.
        """
        metrics_service.safety_status_queries += 1

        active = await active_journey_service.get_active_journey()
        if not active:
            active = active_journey_service._active_journey

        target_id = journey_id or (active.id if active else "no-active-journey")

        # Check demo scenario override first
        override_scenario = self._demo_overrides.get(target_id) or self._demo_overrides.get("global")
        if override_scenario:
            return self._build_demo_override_assessment(target_id, active, override_scenario)

        if not active or (journey_id and active.id != journey_id):
            is_assist = target_id in self._assistance_requests
            assist_meta = self._assistance_requests.get(target_id)
            status_val = SafetyStatus.ASSISTANCE_NEEDED.value if is_assist else SafetyStatus.NORMAL.value
            msg_val = (
                f"Assistance requested ({assist_meta.get('reason', 'User requested assistance')})"
                if is_assist
                else "No active journey in progress"
            )
            disc_val = self.EMERGENCY_DISCLOSURE if is_assist else self.DEFAULT_DISCLOSURE
            return SafetyAssessment(
                journey_id=target_id,
                safety_status=status_val,
                safety_message=msg_val,
                route_number=None,
                current_stop=assist_meta.get("current_stop") if assist_meta else None,
                next_stop=None,
                destination=None,
                eta_minutes=None,
                assistance_requested=is_assist,
                assistance_requested_at=assist_meta.get("requested_at") if assist_meta else None,
                telemetry_health="UNAVAILABLE",
                data_source="simulated",
                disruption_active=False,
                transfer_attention=False,
                disclosure=disc_val,
                safety_events_count=len(self._events.get(target_id, [])),
                is_sharing_active=journey_share_service.is_share_active(target_id),
            )

        return self.evaluate_journey_safety(active)

    def evaluate_journey_safety(self, active: ActiveJourney) -> SafetyAssessment:
        jid = active.id
        now = datetime.now(timezone.utc)
        provider = get_transit_provider()

        # Check explicit assistance request
        is_assistance = jid in self._assistance_requests
        assistance_meta = self._assistance_requests.get(jid)
        assistance_req_at = assistance_meta.get("requested_at") if assistance_meta else None

        # Check telemetry health
        is_offline = (
            active.state == JourneyState.OFFLINE
            or not active.telemetry_reliable
            or (active.telemetry_health == "LOST")
        )
        telemetry_health = "LOST" if is_offline else "HEALTHY"

        # Check disruptions
        inc_assess = incident_impact_service.assess_route(active.route_number)
        alerts = alert_service.get_alerts(route_number=active.route_number, active_only=True)
        has_disruption = inc_assess.is_affected or len(alerts) > 0

        # Check transfer attention
        transfer_attention = bool(active.is_transfer_journey and active.is_transfer_at_risk)

        # Check approaching destination (<= 1 remaining stop or <= 5 mins)
        dest_approaching = (active.remaining_stops is not None and active.remaining_stops <= 1) or (
            active.eta_minutes is not None and active.eta_minutes <= 5
        )

        # Determine SafetyStatus
        if is_offline:
            status = SafetyStatus.OFFLINE.value
            msg = "Telemetry lost — showing last known transit data"
        elif is_assistance:
            status = SafetyStatus.ASSISTANCE_NEEDED.value
            msg = f"Assistance requested ({assistance_meta.get('reason', 'User requested assistance')})"
        elif transfer_attention:
            status = SafetyStatus.ATTENTION.value
            msg = "Transfer connection at risk due to corridor conditions"
        elif has_disruption:
            status = SafetyStatus.ATTENTION.value
            msg = f"Disruption along route: {inc_assess.message or (alerts[0].title if alerts else 'Service alert')}"
        elif dest_approaching:
            status = SafetyStatus.ATTENTION.value
            msg = f"Approaching destination: {active.destination}"
        else:
            status = SafetyStatus.NORMAL.value
            msg = "Journey progressing normally"

        is_sharing = journey_share_service.is_share_active(jid)
        last_check = self._last_safety_checks.get(jid)

        assessment = SafetyAssessment(
            journey_id=jid,
            safety_status=status,
            safety_message=msg,
            route_number=active.route_number,
            current_stop=active.current_stop,
            next_stop=active.next_stop,
            destination=active.destination,
            eta_minutes=active.eta_minutes,
            assistance_requested=is_assistance,
            assistance_requested_at=assistance_req_at,
            telemetry_health=telemetry_health,
            data_source="simulated" if not (active.telemetry_reliable and provider.is_realtime()) else "realtime",
            disruption_active=has_disruption,
            transfer_attention=transfer_attention,
            last_safety_check_at=last_check,
            disclosure=self.DEFAULT_DISCLOSURE,
            safety_events_count=len(self._events.get(jid, [])),
            is_sharing_active=is_sharing,
        )

        # Mirror back into active_journey object for cross-system consistency
        active.safety_status = status
        active.safety_message = msg
        active.telemetry_health = telemetry_health
        active.assistance_requested = is_assistance
        active.assistance_requested_at = assistance_req_at
        active.safety_event_count = len(self._events.get(jid, []))

        return assessment

    def _build_demo_override_assessment(
        self, target_id: str, active: Optional[ActiveJourney], scenario: str
    ) -> SafetyAssessment:
        now = datetime.now(timezone.utc)
        rt = active.route_number if active else "500D"
        cur = active.current_stop if active else "Silk Board"
        nxt = active.next_stop if active else "HSR Layout"
        dest = active.destination if active else "Hebbal"
        events_cnt = len(self._events.get(target_id, []))

        if scenario == "telemetry_lost":
            return SafetyAssessment(
                journey_id=target_id,
                safety_status=SafetyStatus.OFFLINE.value,
                safety_message="Telemetry lost — vehicle signal not detected for >5 minutes",
                route_number=rt,
                current_stop=cur,
                next_stop=nxt,
                destination=dest,
                eta_minutes=None,
                assistance_requested=False,
                telemetry_health="LOST",
                data_source="simulated",
                disruption_active=False,
                transfer_attention=False,
                disclosure=self.DEFAULT_DISCLOSURE,
                safety_events_count=events_cnt,
                is_sharing_active=journey_share_service.is_share_active(target_id),
            )
        elif scenario == "missed_destination":
            return SafetyAssessment(
                journey_id=target_id,
                safety_status=SafetyStatus.ATTENTION.value,
                safety_message=f"Destination passed or missed: {dest}. Nearby transit options available.",
                route_number=rt,
                current_stop=cur,
                next_stop=nxt,
                destination=dest,
                eta_minutes=0,
                assistance_requested=False,
                telemetry_health="HEALTHY",
                data_source="simulated",
                disruption_active=False,
                transfer_attention=False,
                disclosure=self.DEFAULT_DISCLOSURE,
                safety_events_count=events_cnt,
                is_sharing_active=journey_share_service.is_share_active(target_id),
            )
        elif scenario == "missed_transfer":
            return SafetyAssessment(
                journey_id=target_id,
                safety_status=SafetyStatus.ATTENTION.value,
                safety_message="Connecting bus departed or transfer window missed. Re-routing recommended.",
                route_number=rt,
                current_stop=cur,
                next_stop=nxt,
                destination=dest,
                eta_minutes=15,
                assistance_requested=False,
                telemetry_health="HEALTHY",
                data_source="simulated",
                disruption_active=False,
                transfer_attention=True,
                disclosure=self.DEFAULT_DISCLOSURE,
                safety_events_count=events_cnt,
                is_sharing_active=journey_share_service.is_share_active(target_id),
            )
        elif scenario == "disruption_attention":
            return SafetyAssessment(
                journey_id=target_id,
                safety_status=SafetyStatus.ATTENTION.value,
                safety_message="Heavy traffic congestion / road closure reported on corridor.",
                route_number=rt,
                current_stop=cur,
                next_stop=nxt,
                destination=dest,
                eta_minutes=28,
                assistance_requested=False,
                telemetry_health="HEALTHY",
                data_source="simulated",
                disruption_active=True,
                transfer_attention=False,
                disclosure=self.DEFAULT_DISCLOSURE,
                safety_events_count=events_cnt,
                is_sharing_active=journey_share_service.is_share_active(target_id),
            )
        elif scenario == "assistance_requested":
            return SafetyAssessment(
                journey_id=target_id,
                safety_status=SafetyStatus.ASSISTANCE_NEEDED.value,
                safety_message="Commuter requested transit assistance. Guidance and nearby stops displayed.",
                route_number=rt,
                current_stop=cur,
                next_stop=nxt,
                destination=dest,
                eta_minutes=12,
                assistance_requested=True,
                assistance_requested_at=now,
                telemetry_health="HEALTHY",
                data_source="simulated",
                disruption_active=False,
                transfer_attention=False,
                disclosure=self.EMERGENCY_DISCLOSURE,
                safety_events_count=events_cnt,
                is_sharing_active=journey_share_service.is_share_active(target_id),
            )
        elif scenario == "journey_share_active":
            return SafetyAssessment(
                journey_id=target_id,
                safety_status=SafetyStatus.NORMAL.value,
                safety_message="Journey sharing is active with emergency contacts.",
                route_number=rt,
                current_stop=cur,
                next_stop=nxt,
                destination=dest,
                eta_minutes=18,
                assistance_requested=False,
                telemetry_health="HEALTHY",
                data_source="simulated",
                disruption_active=False,
                transfer_attention=False,
                disclosure=self.DEFAULT_DISCLOSURE,
                safety_events_count=events_cnt,
                is_sharing_active=True,
            )
        else:  # normal_journey or default
            return SafetyAssessment(
                journey_id=target_id,
                safety_status=SafetyStatus.NORMAL.value,
                safety_message="Journey progressing normally",
                route_number=rt,
                current_stop=cur,
                next_stop=nxt,
                destination=dest,
                eta_minutes=18,
                assistance_requested=False,
                telemetry_health="HEALTHY",
                data_source="simulated",
                disruption_active=False,
                transfer_attention=False,
                disclosure=self.DEFAULT_DISCLOSURE,
                safety_events_count=events_cnt,
                is_sharing_active=journey_share_service.is_share_active(target_id),
            )

    async def request_assistance(self, req: AssistanceRequest) -> AssistanceResponse:
        """
        Records an explicit assistance request from the commuter.
        Emits a safety event and updates metrics.
        """
        now = datetime.now(timezone.utc)
        self._assistance_requests[req.journey_id] = {
            "reason": req.reason or "User requested assistance",
            "current_stop": req.current_stop,
            "requested_at": now,
        }

        active = await active_journey_service.get_active_journey()
        if not active:
            active = active_journey_service._active_journey

        if active and active.id == req.journey_id:
            active.assistance_requested = True
            active.assistance_requested_at = now
            active.safety_status = SafetyStatus.ASSISTANCE_NEEDED.value

        self.record_safety_event(
            journey_id=req.journey_id,
            event_type=SafetyEventType.USER_REQUESTED_ASSISTANCE.value,
            status=SafetyStatus.ASSISTANCE_NEEDED.value,
            route_number=active.route_number if active else None,
            current_stop=req.current_stop or (active.current_stop if active else None),
            destination=active.destination if active else None,
            details=req.reason or "User requested assistance",
        )

        metrics_service.assistance_requests += 1

        return AssistanceResponse(
            success=True,
            journey_id=req.journey_id,
            safety_status=SafetyStatus.ASSISTANCE_NEEDED.value,
            message="Assistance mode activated. Transit guidance and nearby safety stops are available.",
            assistance_requested_at=now,
            disclosure=self.EMERGENCY_DISCLOSURE,
        )

    async def cancel_assistance(self, journey_id: str) -> AssistanceResponse:
        """
        Cancels an active assistance request upon commuter confirmation.
        """
        now = datetime.now(timezone.utc)
        if journey_id in self._assistance_requests:
            del self._assistance_requests[journey_id]

        active = await active_journey_service.get_active_journey()
        if not active:
            active = active_journey_service._active_journey

        if active and active.id == journey_id:
            active.assistance_requested = False
            active.assistance_requested_at = None
            active.safety_status = SafetyStatus.NORMAL.value

        metrics_service.assistance_cancellations += 1

        return AssistanceResponse(
            success=True,
            journey_id=journey_id,
            safety_status=SafetyStatus.NORMAL.value,
            message="Assistance request cancelled. Normal journey monitoring resumed.",
            assistance_requested_at=now,
            disclosure=self.EMERGENCY_DISCLOSURE,
        )

    async def complete_safety_check(self, req: SafetyCheckRequest) -> SafetyCheckResponse:
        """
        Commuter manual 'I am OK / Verify Safety' check.
        Records a timestamp and event.
        """
        now = datetime.now(timezone.utc)
        self._last_safety_checks[req.journey_id] = now

        active = await active_journey_service.get_active_journey()
        if not active:
            active = active_journey_service._active_journey

        if active and active.id == req.journey_id:
            active.last_safety_check_at = now

        self.record_safety_event(
            journey_id=req.journey_id,
            event_type=SafetyEventType.SAFETY_CHECK.value,
            status=SafetyStatus.NORMAL.value,
            route_number=active.route_number if active else None,
            current_stop=active.current_stop if active else None,
            destination=active.destination if active else None,
            details="Safety check verified by commuter",
        )

        metrics_service.safety_checks += 1

        return SafetyCheckResponse(
            success=True,
            journey_id=req.journey_id,
            checked_at=now,
            safety_status=SafetyStatus.NORMAL.value,
            message="Safety status confirmed.",
            disclosure=self.DEFAULT_DISCLOSURE,
        )

    async def get_nearby_safety_transit(
        self, lat: Optional[float] = None, lon: Optional[float] = None
    ) -> NearbySafetyResponse:
        """
        Returns verified nearby transit stops and transfer hubs based on GTFS and mock data.
        Canonical disclosure: 'Live emergency service availability is unavailable.'
        """
        metrics_service.nearby_safety_queries += 1

        # Default Bengaluru center coordinates if lat/lon omitted
        c_lat = lat if lat is not None else 12.9716
        c_lon = lon if lon is not None else 77.5946

        all_stops = gtfs_repository.get_all_stops()
        items: List[NearbySafetyTransitItem] = []

        if all_stops:
            # Sort stops by approximate haversine distance
            stops_with_dist = []
            for s in all_stops:
                d_lat = math.radians(s.stop_lat - c_lat)
                d_lon = math.radians(s.stop_lon - c_lon)
                a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(c_lat)) * math.cos(math.radians(s.stop_lat)) * math.sin(d_lon / 2) ** 2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                dist_m = int(6371000 * c)
                stops_with_dist.append((dist_m, s))

            stops_with_dist.sort(key=lambda x: x[0])
            for dist_m, s in stops_with_dist[:5]:
                is_hub = "Bus Station" in s.stop_name or "TTMC" in s.stop_name or "Majestic" in s.stop_name
                items.append(
                    NearbySafetyTransitItem(
                        item_type="transfer_hub" if is_hub else "stop",
                        name=s.stop_name,
                        distance_meters=dist_m,
                        details="Transit interchange with connecting services" if is_hub else "Regular BMTC transit stop",
                        route_numbers=["500D", "335E", "G-4"] if is_hub else ["500D"],
                    )
                )

        if not items:
            # Fallback baseline Bengaluru stations
            items = [
                NearbySafetyTransitItem(
                    item_type="transfer_hub",
                    name="Majestic Bus Station (KBS)",
                    distance_meters=450,
                    details="Major BMTC interchange & Namma Metro hub",
                    route_numbers=["500D", "335E", "G-4", "201G"],
                ),
                NearbySafetyTransitItem(
                    item_type="stop",
                    name="Silk Board Junction",
                    distance_meters=780,
                    details="Major transit node connecting Outer Ring Road",
                    route_numbers=["500D", "356M", "K-3"],
                ),
                NearbySafetyTransitItem(
                    item_type="transfer_hub",
                    name="Shivajinagar TTMC",
                    distance_meters=1200,
                    details="Traffic and Transit Management Centre",
                    route_numbers=["279", "335E", "138"],
                ),
            ]

        return NearbySafetyResponse(
            nearby_items=items,
            emergency_service_disclosure=self.LIVE_EMERGENCY_UNAVAILABLE_DISCLOSURE,
            source_disclosure=self.DEFAULT_DISCLOSURE,
        )

    def apply_demo_override(self, scenario: str, journey_id: Optional[str] = None):
        key = journey_id or "global"
        self._demo_overrides[key] = scenario

    def clear_demo_override(self, journey_id: Optional[str] = None):
        if journey_id:
            self._demo_overrides.pop(journey_id, None)
        else:
            self._demo_overrides.clear()

    def reset(self):
        self._events.clear()
        self._assistance_requests.clear()
        self._last_safety_checks.clear()
        self._demo_overrides.clear()


safety_service = SafetyService()
