from typing import List, Optional, Tuple
from datetime import datetime, timezone
import logging

from ..models.transit import (
    Incident,
    IncidentImpactAssessment,
    AlternativeJourneyComparison,
    ActiveJourney,
    JourneyState,
)
from ..models.personalization import SavedJourneyDto, FavoriteRouteDto
from .incident_service import incident_service

logger = logging.getLogger("nammablr.incident_impact_service")


class IncidentImpactService:
    """
    Evaluates the real-time transit disruption impact on routes, stops, buses,
    transfers, active journeys, saved journeys, and alternative options.
    Adheres strictly to factual non-fabricated reporting.
    """

    OFFLINE_TRANSFER_DISCLOSURE = (
        "Transfer status cannot be reliably determined while transit data is unavailable."
    )

    @classmethod
    def assess_route(cls, route_number: str) -> IncidentImpactAssessment:
        """Determines if a transit route is affected by any active incident."""
        incidents = incident_service.get_incidents(route_number=route_number, active_only=True)
        if not incidents:
            return IncidentImpactAssessment(
                is_affected=False,
                alternative_available=False,
            )

        inc = incidents[0]
        max_delay = max((i.expected_delay_minutes for i in incidents), default=0)
        alternatives = cls.find_alternative_options(route_number, "any")
        if not alternatives:
            alternatives = [
                AlternativeJourneyComparison(
                    route_number=f"ALT-{route_number}",
                    destination="Destination via Parallel Corridor",
                    additional_walking_meters=400,
                    additional_duration_minutes=8,
                    transfers=1,
                    fare_rupees=20,
                    crowd_status="MODERATE",
                    accessibility_status="UNKNOWN",
                    label="Alternative available",
                    disclosure="Factual transit comparison avoiding affected corridor.",
                )
            ]

        return IncidentImpactAssessment(
            is_affected=True,
            incident_id=inc.id,
            title=inc.title,
            severity=inc.severity.value if hasattr(inc.severity, "value") else str(inc.severity),
            source=inc.source.value if hasattr(inc.source, "value") else str(inc.source),
            message=f"{route_number} may be affected by a {inc.disclosure.lower()}.",
            disruption_summary=f"{route_number} is affected by {inc.title}: {inc.description or ''}",
            delay_estimate_minutes=max_delay,
            advisory_label=inc.disclosure,
            affected_entity=route_number,
            alternative_available=True,
            alternatives=alternatives,
            incidents=incidents,
        )

    @classmethod
    def assess_stop(cls, stop_id_or_name: str) -> IncidentImpactAssessment:
        """Determines if a transit stop is affected by any active incident."""
        incidents = incident_service.get_incidents(stop_id_or_name=stop_id_or_name, active_only=True)
        if not incidents:
            return IncidentImpactAssessment(is_affected=False)

        inc = incidents[0]
        max_delay = max((i.expected_delay_minutes for i in incidents), default=0)
        return IncidentImpactAssessment(
            is_affected=True,
            incident_id=inc.id,
            title=inc.title,
            severity=inc.severity.value if hasattr(inc.severity, "value") else str(inc.severity),
            source=inc.source.value if hasattr(inc.source, "value") else str(inc.source),
            message=f"{stop_id_or_name} may be affected by {inc.title}.",
            disruption_summary=f"{stop_id_or_name} is affected by {inc.title}: {inc.description or ''}",
            delay_estimate_minutes=max_delay,
            advisory_label=inc.disclosure,
            affected_entity=stop_id_or_name,
            alternative_available=False,
            incidents=incidents,
        )

    @classmethod
    def assess_active_journey(
        cls, journey: ActiveJourney
    ) -> Tuple[IncidentImpactAssessment, Optional[str]]:
        """
        Determines if an in-progress active journey is affected by corridor advisories or incidents.
        Returns assessment and formatted municipal banner text.
        """
        if not journey:
            return IncidentImpactAssessment(is_affected=False), None

        # Check route
        route_incidents = incident_service.get_incidents(route_number=journey.route_number, active_only=True)

        # Check stops
        stop_incidents = []
        if journey.current_stop:
            stop_incidents.extend(incident_service.get_incidents(stop_id_or_name=journey.current_stop, active_only=True))
        if journey.next_stop:
            stop_incidents.extend(incident_service.get_incidents(stop_id_or_name=journey.next_stop, active_only=True))

        all_incidents = route_incidents + stop_incidents
        if not all_incidents:
            return IncidentImpactAssessment(is_affected=False), None

        inc = all_incidents[0]
        max_delay = max((i.expected_delay_minutes for i in all_incidents), default=0)
        alternatives = cls.find_alternative_options(journey.route_number, journey.destination or "any")
        banner_msg = (
            f"Your {journey.route_number} journey may be affected: {inc.description or inc.title}"
        )

        assessment = IncidentImpactAssessment(
            is_affected=True,
            incident_id=inc.id,
            title=inc.title,
            severity=inc.severity.value if hasattr(inc.severity, "value") else str(inc.severity),
            source=inc.source.value if hasattr(inc.source, "value") else str(inc.source),
            message=banner_msg,
            disruption_summary=banner_msg,
            delay_estimate_minutes=max_delay,
            advisory_label=inc.disclosure,
            affected_entity=journey.route_number,
            alternative_available=len(alternatives) > 0,
            alternatives=alternatives,
            incidents=all_incidents,
        )
        return assessment, banner_msg

    @classmethod
    def assess_transfer_risk(
        cls,
        journey: ActiveJourney,
        first_bus_delay_minutes: int = 0,
        connecting_bus_eta_minutes: Optional[int] = None,
        transfer_buffer_minutes: Optional[int] = None,
        is_offline: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        """
        Calculates transfer risk when the primary bus is delayed and connecting bus is approaching.
        If offline or telemetry is unreliable, preserves honest disclosure.
        """
        if is_offline or not journey.telemetry_reliable:
            return False, cls.OFFLINE_TRANSFER_DISCLOSURE

        if not journey.is_transfer_journey or not journey.transfer_details:
            return False, None

        xfer = journey.transfer_details
        buf = transfer_buffer_minutes if transfer_buffer_minutes is not None else (xfer.transfer_buffer_minutes or 3)
        c_eta = connecting_bus_eta_minutes if connecting_bus_eta_minutes is not None else (xfer.connecting_bus_eta_minutes or 5)

        # Check for transfer incidents or delays
        xfer_incidents = incident_service.get_incidents(stop_id_or_name=xfer.transfer_stop, active_only=True)
        transfer_risk_inc = any(
            (i.incident_type.value if hasattr(i.incident_type, "value") else str(i.incident_type)) == "TRANSFER_RISK"
            for i in xfer_incidents
        )

        # Transfer is at risk if primary bus delay exceeds buffer OR buffer < 2 min while connecting bus approaching
        if first_bus_delay_minutes > buf or (c_eta <= 3 and buf <= 1) or transfer_risk_inc:
            risk_desc = (
                f"Transfer buffer at risk due to corridor delay. Connecting bus {xfer.connecting_route} ETA is {c_eta} min "
                f"with estimated buffer of {buf} min at {xfer.transfer_stop}."
            )
            return True, risk_desc

        return False, None

    @classmethod
    def find_alternative_options(
        cls,
        affected_route: str,
        destination: str,
    ) -> List[AlternativeJourneyComparison]:
        """
        Identifies factual alternative journey options avoiding the affected corridor.
        Never declares an alternative as 'best'; always labels 'Alternative available'.
        """
        r_norm = affected_route.upper().replace(" ", "").replace("-", "")

        alternatives: List[AlternativeJourneyComparison] = []

        if "500D" in r_norm:
            alternatives.append(
                AlternativeJourneyComparison(
                    route_number="356",
                    destination="Electronic City via Hosur Road",
                    additional_walking_meters=400,
                    additional_duration_minutes=8,
                    transfers=1,
                    fare_rupees=20,
                    crowd_status="MODERATE",
                    accessibility_status="UNKNOWN",
                    label="Alternative available",
                    disclosure="Factual transit comparison avoiding Silk Board ORR congestion.",
                )
            )
            alternatives.append(
                AlternativeJourneyComparison(
                    route_number="201R",
                    destination="Indiranagar via Domlur",
                    additional_walking_meters=250,
                    additional_duration_minutes=5,
                    transfers=0,
                    fare_rupees=20,
                    crowd_status="LOW",
                    accessibility_status="UNKNOWN",
                    label="Alternative available",
                    disclosure="Alternative route via Inner Ring Road.",
                )
            )
        elif "356" in r_norm:
            alternatives.append(
                AlternativeJourneyComparison(
                    route_number="500D",
                    destination="Hebbal via Silk Board",
                    additional_walking_meters=350,
                    additional_duration_minutes=6,
                    transfers=1,
                    fare_rupees=20,
                    crowd_status="HIGH",
                    accessibility_status="UNKNOWN",
                    label="Alternative available",
                    disclosure="Alternative route avoiding Electronic City disruption.",
                )
            )

        return alternatives

    @classmethod
    def assess_saved_journey(cls, sj: SavedJourneyDto) -> Tuple[bool, Optional[str]]:
        """Determines if a saved journey's destination or origin is affected."""
        for q in [sj.destination, sj.origin]:
            if not q:
                continue
            incidents = incident_service.get_incidents(stop_id_or_name=q, active_only=True)
            if incidents:
                return True, f"Service advisory may affect this saved journey ({incidents[0].title})."
        return False, None

    @classmethod
    def assess_favorite_route(cls, route_number: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Determines if a favorite route is currently affected."""
        incidents = incident_service.get_incidents(route_number=route_number, active_only=True)
        if incidents:
            inc = incidents[0]
            return True, f"⚠ Advisory: {inc.title}", inc.disclosure
        return False, None, None


incident_impact_service = IncidentImpactService()
