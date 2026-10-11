from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid
import logging

from ..models.transit import (
    Incident,
    IncidentSeverity,
    IncidentType,
    IncidentSource,
    IncidentStatus,
    IncidentDetailsResponse,
    IncidentOverrideRequest,
)

logger = logging.getLogger("nammablr.incident_service")


class IncidentService:
    """
    Core Incident & Transit Disruption Service for NammaBlr.
    Manages municipal corridor advisories, GTFS-RT ServiceAlerts, and evaluator simulation overrides.
    Maintains strict source attribution: SIMULATED vs AUTHORIZED_GTFS_RT vs OFFICIAL_BMTC_ALERT.
    Never fabricates unverified passenger or incident data.
    """

    SIMULATED_DISCLOSURE = "SIMULATED CORRIDOR ADVISORY"
    OFFICIAL_DISCLOSURE = "OFFICIAL BMTC SERVICE ADVISORY"
    GTFS_RT_DISCLOSURE = "Authorized GTFS-RT Service Alert"

    def __init__(self):
        self._override_mode: Optional[str] = None
        self._incidents: Dict[str, Incident] = {}
        self._init_baseline_incidents()

    def _init_baseline_incidents(self):
        """Initializes deterministic Bengaluru corridor demo incidents."""
        now = datetime.now(timezone.utc)
        self._incidents = {
            "inc-500d-silkboard": Incident(
                id="inc-500d-silkboard",
                title="500D Silk Board Corridor Advisory: Waterlogging",
                description="Simulated waterlogging and service crawl near Central Silk Board flyover ramp. Expect 18 min transit delays.",
                incident_type=IncidentType.WATERLOGGING,
                severity=IncidentSeverity.DISRUPTION,
                status=IncidentStatus.ACTIVE,
                source=IncidentSource.SIMULATED,
                affected_routes=["500D", "KIA-8"],
                affected_stops=["stop-silk-board", "Central Silk Board Junction", "Central Silk Board", "Agara Lake"],
                affected_bus_ids=["bus-500d-1", "bus-500d-2"],
                affected_corridors=["Outer Ring Road", "Silk Board", "Central Silk Board"],
                corridor="Central Silk Board",
                start_time=now,
                last_updated=now,
                is_simulated=True,
                disclosure=self.SIMULATED_DISCLOSURE,
                source_attribution_badge="SIMULATED TRANSIT ALERT",
                impact_level="MODERATE",
                expected_delay_minutes=18,
                latitude=12.9176,
                longitude=77.6238,
            ),
            "inc-356-ecity": Incident(
                id="inc-356-ecity",
                title="356 Electronic City Corridor Disruption",
                description="Simulated corridor disruption near Electronic City. Lane reduction in effect.",
                incident_type=IncidentType.TRAFFIC_DISRUPTION,
                severity=IncidentSeverity.DISRUPTION,
                status=IncidentStatus.ACTIVE,
                source=IncidentSource.SIMULATED,
                affected_routes=["356"],
                affected_stops=["stop-electronic-city", "Electronic City Toll Gate"],
                affected_bus_ids=["bus-356-1"],
                affected_corridors=["Hosur Road", "Electronic City"],
                start_time=now,
                last_updated=now,
                is_simulated=True,
                disclosure=self.SIMULATED_DISCLOSURE,
                impact_level="HIGH",
                latitude=12.8452,
                longitude=77.6602,
            ),
            "inc-kia8-airport": Incident(
                id="inc-kia8-airport",
                title="KIA-8 Airport Corridor Advisory",
                description="Simulated service advisory near Airport corridor. Standard airport frequency active.",
                incident_type=IncidentType.SERVICE_DELAY,
                severity=IncidentSeverity.NOTICE,
                status=IncidentStatus.ACTIVE,
                source=IncidentSource.SIMULATED,
                affected_routes=["KIA-8"],
                affected_stops=["Kempegowda International Airport", "Hebbal"],
                affected_bus_ids=["bus-kia8-1"],
                affected_corridors=["Airport Expressway", "Bellary Road"],
                start_time=now,
                last_updated=now,
                is_simulated=True,
                disclosure=self.SIMULATED_DISCLOSURE,
                impact_level="LOW",
                latitude=13.1986,
                longitude=77.7066,
            ),
            "inc-201r-advisory": Incident(
                id="inc-201r-advisory",
                title="201R Route Advisory",
                description="Simulated route advisory along Domlur and Indiranagar. Normal frequency.",
                incident_type=IncidentType.ROUTE_DIVERSION,
                severity=IncidentSeverity.INFO,
                status=IncidentStatus.ACTIVE,
                source=IncidentSource.SIMULATED,
                affected_routes=["201R"],
                affected_stops=["Domlur", "Indiranagar"],
                affected_bus_ids=["bus-201r-1"],
                affected_corridors=["Inner Ring Road"],
                start_time=now,
                last_updated=now,
                is_simulated=True,
                disclosure=self.SIMULATED_DISCLOSURE,
                impact_level="LOW",
                latitude=12.9610,
                longitude=77.6400,
            ),
            "inc-g2-stop": Incident(
                id="inc-g2-stop",
                title="G-2 Stop Advisory",
                description="Simulated stop advisory near Brigade Road. Minor crowd buildup.",
                incident_type=IncidentType.STOP_CLOSURE,
                severity=IncidentSeverity.NOTICE,
                status=IncidentStatus.ACTIVE,
                source=IncidentSource.SIMULATED,
                affected_routes=["G-2"],
                affected_stops=["Brigade Road", "MG Road"],
                affected_bus_ids=["bus-g2-1"],
                affected_corridors=["CBD"],
                start_time=now,
                last_updated=now,
                is_simulated=True,
                disclosure=self.SIMULATED_DISCLOSURE,
                impact_level="LOW",
                latitude=12.9730,
                longitude=77.6080,
            ),
        }

    def set_simulation_override(self, req: Optional[IncidentOverrideRequest] = None):
        """Sets evaluator simulation override mode."""
        if not req or getattr(req, "clear", False) or req.mode == "none":
            self._override_mode = None
            self._init_baseline_incidents()
            return

        now = datetime.now(timezone.utc)
        # Custom override with explicit corridor or route
        if getattr(req, "corridor", None) or getattr(req, "route_number", None):
            self._override_mode = "custom"
            corr = req.corridor or "Corridor"
            r_num = req.route_number or "500D"
            sev_str = (req.severity or "WARNING").upper()
            try:
                sev = IncidentSeverity(sev_str)
            except ValueError:
                sev = IncidentSeverity.WARNING

            inc_type_str = (getattr(req, "incident_type", None) or "SERVICE_DELAY").upper()
            try:
                inc_type = IncidentType(inc_type_str)
            except ValueError:
                inc_type = IncidentType.SERVICE_DELAY

            custom_inc = Incident(
                id=f"override-{uuid.uuid4().hex[:8]}",
                title=getattr(req, "title", None) or f"{r_num} {corr} Advisory",
                description=getattr(req, "description", None) or f"Simulated transit disruption on {corr}.",
                incident_type=inc_type,
                severity=sev,
                status=IncidentStatus.ACTIVE,
                source=IncidentSource.SIMULATED,
                affected_routes=[r_num],
                affected_stops=[corr],
                affected_corridors=[corr],
                corridor=corr,
                start_time=now,
                last_updated=now,
                is_simulated=True,
                disclosure=self.SIMULATED_DISCLOSURE,
                source_attribution_badge="SIMULATED TRANSIT ALERT",
                impact_level="HIGH" if sev in [IncidentSeverity.DISRUPTION, IncidentSeverity.CRITICAL] else "MODERATE",
                expected_delay_minutes=getattr(req, "delay_minutes", 15) or 15,
                latitude=12.9176,
                longitude=77.6238,
            )
            self._incidents = {custom_inc.id: custom_inc}
            return

        mode = req.mode.lower().strip()
        self._override_mode = mode

        if mode == "500d_disruption":
            self._incidents = {
                "inc-500d-silkboard": Incident(
                    id="inc-500d-silkboard",
                    title="500D Silk Board Corridor Advisory: Waterlogging",
                    description="Simulated waterlogging near Silk Board Junction. Expect 18 min transit delays.",
                    incident_type=IncidentType.WATERLOGGING,
                    severity=IncidentSeverity.DISRUPTION,
                    status=IncidentStatus.ACTIVE,
                    source=IncidentSource.SIMULATED,
                    affected_routes=["500D"],
                    affected_stops=["stop-silk-board", "Central Silk Board Junction", "Central Silk Board"],
                    affected_bus_ids=["bus-500d-1"],
                    affected_corridors=["Outer Ring Road", "Central Silk Board"],
                    corridor="Central Silk Board",
                    start_time=now,
                    last_updated=now,
                    is_simulated=True,
                    disclosure=self.SIMULATED_DISCLOSURE,
                    source_attribution_badge="SIMULATED TRANSIT ALERT",
                    impact_level="MODERATE",
                    expected_delay_minutes=18,
                    latitude=12.9176,
                    longitude=77.6238,
                )
            }
        elif mode == "356_disruption":
            self._incidents = {
                "inc-356-ecity": Incident(
                    id="inc-356-ecity",
                    title="356 Electronic City Corridor Disruption",
                    description="Simulated corridor disruption near Electronic City. Lane reduction in effect.",
                    incident_type=IncidentType.TRAFFIC_DISRUPTION,
                    severity=IncidentSeverity.DISRUPTION,
                    status=IncidentStatus.ACTIVE,
                    source=IncidentSource.SIMULATED,
                    affected_routes=["356"],
                    affected_stops=["stop-electronic-city"],
                    affected_bus_ids=["bus-356-1"],
                    affected_corridors=["Hosur Road"],
                    start_time=now,
                    last_updated=now,
                    is_simulated=True,
                    disclosure=self.SIMULATED_DISCLOSURE,
                    impact_level="HIGH",
                    latitude=12.8452,
                    longitude=77.6602,
                )
            }
        elif mode == "stop_closure":
            self._incidents = {
                "inc-silkboard-closure": Incident(
                    id="inc-silkboard-closure",
                    title="Central Silk Board Platform Closure",
                    description="Simulated stop closure at Central Silk Board bay 2 due to civil maintenance.",
                    incident_type=IncidentType.STOP_CLOSURE,
                    severity=IncidentSeverity.CRITICAL,
                    status=IncidentStatus.ACTIVE,
                    source=IncidentSource.SIMULATED,
                    affected_routes=["500D", "356", "KIA-8", "201R"],
                    affected_stops=["stop-silk-board", "Central Silk Board Junction"],
                    affected_bus_ids=[],
                    affected_corridors=["Silk Board Interchange"],
                    start_time=now,
                    last_updated=now,
                    is_simulated=True,
                    disclosure=self.SIMULATED_DISCLOSURE,
                    impact_level="CRITICAL",
                    latitude=12.9176,
                    longitude=77.6238,
                )
            }
        elif mode == "transfer_risk":
            self._incidents = {
                "inc-transfer-silkboard": Incident(
                    id="inc-transfer-silkboard",
                    title="Silk Board Transfer Advisory",
                    description="Heavy transit slowdown on connecting feeder bay. Transfers between 500D and 356 at risk.",
                    incident_type=IncidentType.TRANSFER_RISK,
                    severity=IncidentSeverity.WARNING,
                    status=IncidentStatus.ACTIVE,
                    source=IncidentSource.SIMULATED,
                    affected_routes=["500D", "356"],
                    affected_stops=["Central Silk Board Junction", "stop-silk-board"],
                    affected_bus_ids=["bus-500d-1", "bus-356-1"],
                    affected_corridors=["Silk Board Transfer Hub"],
                    start_time=now,
                    last_updated=now,
                    is_simulated=True,
                    disclosure=self.SIMULATED_DISCLOSURE,
                    impact_level="HIGH",
                    latitude=12.9176,
                    longitude=77.6238,
                )
            }
        elif mode == "multiple":
            self._init_baseline_incidents()
        else:
            self._init_baseline_incidents()

    def get_simulation_override(self) -> Optional[str]:
        return self._override_mode

    def get_simulation_overrides(self) -> Dict[str, Incident]:
        if self._override_mode is not None:
            return self._incidents
        return {}

    def get_incidents(
        self,
        route_number: Optional[str] = None,
        stop_id_or_name: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Incident]:
        """Retrieves incidents matching query criteria with strict normalization."""
        incidents = list(self._incidents.values())

        if active_only:
            incidents = [i for i in incidents if i.status == IncidentStatus.ACTIVE]

        if status:
            s_up = status.upper().strip()
            incidents = [i for i in incidents if i.status.value == s_up]

        if severity:
            sev_up = severity.upper().strip()
            incidents = [i for i in incidents if i.severity.value == sev_up]

        if route_number:
            r_norm = route_number.upper().replace(" ", "").replace("-", "")
            incidents = [
                i for i in incidents
                if any(r_norm in r.upper().replace(" ", "").replace("-", "") for r in i.affected_routes)
            ]

        if stop_id_or_name:
            s_norm = stop_id_or_name.lower().strip()
            incidents = [
                i for i in incidents
                if any(s_norm in s.lower() for s in i.affected_stops)
            ]

        return incidents

    def get_incident_by_id(self, incident_id: str) -> Optional[Incident]:
        return self._incidents.get(incident_id)

    def get_active_incidents(self) -> List[Incident]:
        return [i for i in self._incidents.values() if i.status == IncidentStatus.ACTIVE]

    def add_or_update_incident(self, incident: Incident):
        self._incidents[incident.id] = incident

    def ingest_gtfs_rt_alert(
        self,
        alert_id: str,
        header_text: Optional[str] = None,
        description_text: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        cause: str = "UNKNOWN_CAUSE",
        effect: str = "UNKNOWN_EFFECT",
        affected_routes: Optional[List[str]] = None,
        affected_stops: Optional[List[str]] = None,
        affected_trips: Optional[List[str]] = None,
        severity_level: str = "INFO",
        severity: Optional[str] = None,
    ) -> str:
        """Ingests authorized GTFS-RT ServiceAlert into the Incident repository."""
        # Map cause/effect to IncidentType
        inc_type = IncidentType.SERVICE_DELAY
        eff_upper = (effect or "").upper()
        if "CANCEL" in eff_upper:
            inc_type = IncidentType.SERVICE_CANCELLATION
        elif "DETOUR" in eff_upper or "DIVERT" in eff_upper:
            inc_type = IncidentType.ROUTE_DIVERSION
        elif "STOP" in eff_upper and "CLOSE" in eff_upper:
            inc_type = IncidentType.STOP_CLOSURE
        elif "ACCIDENT" in (cause or "").upper():
            inc_type = IncidentType.ROAD_INCIDENT
        elif "WEATHER" in (cause or "").upper():
            inc_type = IncidentType.WEATHER_IMPACT

        # Map severity
        sev = IncidentSeverity.INFO
        s_up = (severity or severity_level or "INFO").upper()
        if s_up in ["WARNING", "SEVERE"]:
            sev = IncidentSeverity.WARNING if s_up == "WARNING" else IncidentSeverity.DISRUPTION
        elif s_up == "CRITICAL":
            sev = IncidentSeverity.CRITICAL
        elif s_up == "DISRUPTION":
            sev = IncidentSeverity.DISRUPTION

        now = datetime.now(timezone.utc)
        final_title = title or header_text or "Authorized GTFS-RT Service Alert"
        final_desc = description or description_text

        incident = Incident(
            id=alert_id,
            title=final_title,
            description=final_desc,
            incident_type=inc_type,
            severity=sev,
            status=IncidentStatus.ACTIVE,
            source=IncidentSource.AUTHORIZED_GTFS_RT,
            affected_routes=affected_routes or [],
            affected_stops=affected_stops or [],
            affected_bus_ids=[],
            affected_corridors=[],
            start_time=now,
            last_updated=now,
            is_simulated=False,
            disclosure=self.GTFS_RT_DISCLOSURE,
            source_attribution_badge="Authorized GTFS-RT Service Alert",
            impact_level="HIGH" if sev in [IncidentSeverity.DISRUPTION, IncidentSeverity.CRITICAL] else "MODERATE",
            expected_delay_minutes=15 if sev in [IncidentSeverity.DISRUPTION, IncidentSeverity.CRITICAL] else 8,
        )
        self._incidents[incident.id] = incident
        return incident.id

    def get_details_response(self, incident_id: str) -> Optional[IncidentDetailsResponse]:
        inc = self.get_incident_by_id(incident_id)
        if not inc:
            return None

        if inc.is_simulated:
            source_label = "SIMULATED CORRIDOR ADVISORY"
            disclosure = self.SIMULATED_DISCLOSURE
        elif inc.source == IncidentSource.AUTHORIZED_GTFS_RT:
            source_label = "AUTHORIZED GTFS-RT SERVICE ALERT"
            disclosure = self.GTFS_RT_DISCLOSURE
        elif inc.source == IncidentSource.OFFICIAL_BMTC_ALERT:
            source_label = "OFFICIAL BMTC SERVICE ADVISORY"
            disclosure = self.OFFICIAL_DISCLOSURE
        else:
            source_label = "TRANSIT SERVICE ADVISORY"
            disclosure = inc.disclosure

        return IncidentDetailsResponse(
            incident=inc,
            affected_routes_count=len(inc.affected_routes),
            affected_stops_count=len(inc.affected_stops),
            source_attribution_label=source_label,
            is_simulated=inc.is_simulated,
            can_track_bus=len(inc.affected_routes) > 0,
            can_view_route=len(inc.affected_routes) > 0,
            disclosure=disclosure,
        )

    def reset(self):
        """Restores baseline demo incidents."""
        self._override_mode = None
        self._init_baseline_incidents()


incident_service = IncidentService()
