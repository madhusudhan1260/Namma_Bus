from datetime import datetime, timezone
from typing import Dict, Optional
from ..models.transit import (
    CrowdStatus,
    CrowdDataSource,
    SeatAvailabilityStatus,
    CrowdMetadata,
    CrowdDetailsResponse,
)


class CrowdService:
    """
    Transparent Crowd & Occupancy Intelligence Service for Bengaluru Transit.
    
    CRITICAL NON-NEGOTIABLE PRINCIPLES:
    - NEVER invent exact passenger numbers.
    - NEVER convert bus speed, GPS position, or route frequency into fake passenger counts.
    - If verified APC/occupancy data is unavailable, occupancy_percentage remains None.
    - Strictly differentiate VERIFIED_APC, HISTORICAL_ESTIMATE, SIMULATED, and UNAVAILABLE.
    - When unavailable, return canonical disclosure:
      "Passenger occupancy data is unavailable from the current feed."
    - Seat availability categories:
      "SEATS LIKELY AVAILABLE", "LIMITED SEATS", "STANDING LIKELY", "VERY CROWDED", "UNKNOWN".
    """

    def __init__(self):
        # Optional evaluator simulation override ("LOW", "MODERATE", "HIGH", "VERY_HIGH", "UNKNOWN", or None)
        self._simulation_override: Optional[str] = None

        # Route baseline characteristics based on real Bengaluru commute corridors
        self._route_corridor_profiles: Dict[str, dict] = {
            "500D": {
                "corridor": "Outer Ring Road (Silk Board to Hebbal/Kadugodi)",
                "peak_crowd": CrowdStatus.HIGH.value,
                "offpeak_crowd": CrowdStatus.MODERATE.value,
                "standing_likelihood_peak": "HIGH",
                "standing_likelihood_offpeak": "MODERATE",
                "seat_peak": SeatAvailabilityStatus.STANDING_LIKELY.value,
                "seat_offpeak": SeatAvailabilityStatus.LIMITED_SEATS.value,
            },
            "356": {
                "corridor": "Hosur Road (Electronic City to Shivajinagar)",
                "peak_crowd": CrowdStatus.VERY_HIGH.value,
                "offpeak_crowd": CrowdStatus.MODERATE.value,
                "standing_likelihood_peak": "HIGH",
                "standing_likelihood_offpeak": "LOW",
                "seat_peak": SeatAvailabilityStatus.VERY_CROWDED.value,
                "seat_offpeak": SeatAvailabilityStatus.SEATS_LIKELY_AVAILABLE.value,
            },
            "201R": {
                "corridor": "Banashankari to Majestic via BTM & Lalbagh",
                "peak_crowd": CrowdStatus.MODERATE.value,
                "offpeak_crowd": CrowdStatus.LOW.value,
                "standing_likelihood_peak": "MODERATE",
                "standing_likelihood_offpeak": "LOW",
                "seat_peak": SeatAvailabilityStatus.LIMITED_SEATS.value,
                "seat_offpeak": SeatAvailabilityStatus.SEATS_LIKELY_AVAILABLE.value,
            },
            "KIA-8": {
                "corridor": "Airport Express (Electronic City to Kempegowda Intl Airport)",
                "peak_crowd": CrowdStatus.MODERATE.value,
                "offpeak_crowd": CrowdStatus.LOW.value,
                "standing_likelihood_peak": "LOW",
                "standing_likelihood_offpeak": "LOW",
                "seat_peak": SeatAvailabilityStatus.SEATS_LIKELY_AVAILABLE.value,
                "seat_offpeak": SeatAvailabilityStatus.SEATS_LIKELY_AVAILABLE.value,
            },
            "G-2": {
                "corridor": "Sarjapur Road to Brigade Road / MG Road",
                "peak_crowd": CrowdStatus.HIGH.value,
                "offpeak_crowd": CrowdStatus.MODERATE.value,
                "standing_likelihood_peak": "HIGH",
                "standing_likelihood_offpeak": "LOW",
                "seat_peak": SeatAvailabilityStatus.LIMITED_SEATS.value,
                "seat_offpeak": SeatAvailabilityStatus.SEATS_LIKELY_AVAILABLE.value,
            },
        }

    def set_simulation_override(self, scenario: Optional[str]):
        """Evaluator/demo control to deterministically set crowd scenario."""
        if scenario:
            sc = scenario.upper().strip()
            valid = {s.value for s in CrowdStatus}
            if sc in valid:
                self._simulation_override = sc
            else:
                self._simulation_override = None
        else:
            self._simulation_override = None

    def get_simulation_override(self) -> Optional[str]:
        return self._simulation_override

    def is_peak_hour(self, now: Optional[datetime] = None) -> bool:
        """Determines if the specified time is peak commuting hour in Bengaluru (IST)."""
        dt = now or datetime.now(timezone.utc)
        # Approximate IST hour: UTC + 5:30
        ist_hour = (dt.hour + 5 + (1 if dt.minute + 30 >= 60 else 0)) % 24
        # Morning peak: 8:30 - 11:30, Evening peak: 17:00 - 20:30
        is_morning_peak = 8 <= ist_hour <= 11
        is_evening_peak = 17 <= ist_hour <= 20
        # Weekday check (0=Mon, 6=Sun)
        is_weekday = dt.weekday() < 6
        return is_weekday and (is_morning_peak or is_evening_peak)

    def get_crowd_metadata(
        self,
        identifier: str,
        route_number: Optional[str] = None,
        is_simulated: bool = True,
        verified_occupancy: Optional[int] = None,
    ) -> CrowdMetadata:
        """
        Calculates honest crowd metadata for a given bus, route, or stop.
        Strictly preserves disclosures and avoids fake passenger headcounts.
        """
        # 1. Check for manual evaluator simulation override
        if self._simulation_override is not None:
            status = self._simulation_override
            seat_map = {
                CrowdStatus.LOW.value: SeatAvailabilityStatus.SEATS_LIKELY_AVAILABLE.value,
                CrowdStatus.MODERATE.value: SeatAvailabilityStatus.LIMITED_SEATS.value,
                CrowdStatus.HIGH.value: SeatAvailabilityStatus.STANDING_LIKELY.value,
                CrowdStatus.VERY_HIGH.value: SeatAvailabilityStatus.VERY_CROWDED.value,
                CrowdStatus.UNKNOWN.value: SeatAvailabilityStatus.UNKNOWN.value,
            }
            standing_map = {
                CrowdStatus.LOW.value: "LOW",
                CrowdStatus.MODERATE.value: "MODERATE",
                CrowdStatus.HIGH.value: "HIGH",
                CrowdStatus.VERY_HIGH.value: "HIGH",
                CrowdStatus.UNKNOWN.value: "UNKNOWN",
            }
            return CrowdMetadata(
                crowd_status=status,
                occupancy_percentage=None,  # Do not invent exact percent in simulation mode
                estimated_seat_availability=seat_map.get(status, "UNKNOWN"),
                standing_likelihood=standing_map.get(status, "UNKNOWN"),
                source=CrowdDataSource.SIMULATED.value,
                confidence="HIGH" if status != "UNKNOWN" else "LOW",
                disclosure="SIMULATED CROWD DATA for evaluation. Actual passenger occupancy is unavailable from the current feed.",
                updated_at=datetime.now(timezone.utc),
            )

        # 2. Check for legitimate verified APC / GTFS-RT occupancy
        if verified_occupancy is not None and 0 <= verified_occupancy <= 100:
            if verified_occupancy >= 85:
                st = CrowdStatus.VERY_HIGH.value
                seat = SeatAvailabilityStatus.VERY_CROWDED.value
                standing = "HIGH"
            elif verified_occupancy >= 70:
                st = CrowdStatus.HIGH.value
                seat = SeatAvailabilityStatus.STANDING_LIKELY.value
                standing = "HIGH"
            elif verified_occupancy >= 40:
                st = CrowdStatus.MODERATE.value
                seat = SeatAvailabilityStatus.LIMITED_SEATS.value
                standing = "MODERATE"
            else:
                st = CrowdStatus.LOW.value
                seat = SeatAvailabilityStatus.SEATS_LIKELY_AVAILABLE.value
                standing = "LOW"

            return CrowdMetadata(
                crowd_status=st,
                occupancy_percentage=verified_occupancy,
                estimated_seat_availability=seat,
                standing_likelihood=standing,
                source=CrowdDataSource.VERIFIED_APC.value,
                confidence="HIGH",
                disclosure="Verified occupancy reported by transit telemetry.",
                updated_at=datetime.now(timezone.utc),
            )

        # 3. Resolve route number
        rnum = (route_number or identifier or "").strip().upper()
        # Clean bus IDs like "bus-500d-1" -> "500D"
        if "500D" in rnum:
            rnum = "500D"
        elif "356" in rnum:
            rnum = "356"
        elif "201R" in rnum:
            rnum = "201R"
        elif "KIA" in rnum:
            rnum = "KIA-8"
        elif "G2" in rnum or "G-2" in rnum:
            rnum = "G-2"

        profile = self._route_corridor_profiles.get(rnum)
        if not profile:
            # Fallback unknown when no verified data or historical corridor profile exists
            return CrowdMetadata(
                crowd_status=CrowdStatus.UNKNOWN.value,
                occupancy_percentage=None,
                estimated_seat_availability=SeatAvailabilityStatus.UNKNOWN.value,
                standing_likelihood="UNKNOWN",
                source=CrowdDataSource.UNAVAILABLE.value,
                confidence="LOW",
                disclosure="Passenger occupancy data is unavailable from the current feed.",
                updated_at=datetime.now(timezone.utc),
            )

        # 4. Compute estimate from historical patterns
        peak = self.is_peak_hour()
        crowd_status = profile["peak_crowd"] if peak else profile["offpeak_crowd"]
        seat_status = profile["seat_peak"] if peak else profile["seat_offpeak"]
        standing_likelihood = profile["standing_likelihood_peak"] if peak else profile["standing_likelihood_offpeak"]
        source_label = CrowdDataSource.SIMULATED.value if is_simulated else CrowdDataSource.HISTORICAL_ESTIMATE.value

        disclosure_text = (
            "SIMULATED CROWD DATA: Estimated from corridor schedule models. Actual passenger occupancy is unavailable from the current feed."
            if is_simulated
            else "Estimated from historical route patterns. Actual passenger occupancy is unavailable from the current feed."
        )

        return CrowdMetadata(
            crowd_status=crowd_status,
            occupancy_percentage=None,  # Strictly None - never fabricate exact passenger counts
            estimated_seat_availability=seat_status,
            standing_likelihood=standing_likelihood,
            source=source_label,
            confidence="MEDIUM",
            disclosure=disclosure_text,
            updated_at=datetime.now(timezone.utc),
        )

    def get_details_response(self, identifier: str) -> CrowdDetailsResponse:
        """Constructs a REST API response for a route, bus, or stop."""
        ident_clean = identifier.strip()
        meta = self.get_crowd_metadata(identifier=ident_clean)
        explanation = (
            f"Corridor passenger flow indicates {meta.crowd_status.lower()} crowding. "
            f"Seat status: {meta.estimated_seat_availability.lower()}."
        )
        return CrowdDetailsResponse(
            identifier=ident_clean,
            route_or_bus_id=ident_clean,
            crowd_status=meta.crowd_status,
            seat_status=meta.estimated_seat_availability or "UNKNOWN",
            standing_likelihood=meta.standing_likelihood or "UNKNOWN",
            occupancy_percentage=meta.occupancy_percentage,
            source=meta.source,
            confidence=meta.confidence or "MEDIUM",
            disclosure=meta.disclosure,
            explanation=explanation,
            updated_at=meta.updated_at,
        )


crowd_service = CrowdService()
