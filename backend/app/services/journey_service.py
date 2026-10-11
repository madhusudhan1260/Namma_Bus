from .provider_factory import get_transit_provider
from .crowd_prediction_service import CrowdPredictionService
from .crowd_service import crowd_service
from .alert_service import alert_service
from .incident_service import incident_service
from .incident_impact_service import incident_impact_service
from .personalization_service import personalization_service
from .metrics_service import metrics_service
from ..models.transit import (
    JourneyOption,
    JourneySearchRequest,
    JourneySearchResponse,
    JourneyLeg,
    TransferDetails,
    AccessibilityMetadata,
    AccessibilityStatus,
    CrowdMetadata,
    CrowdStatus,
)


def compute_accessibility_score(acc: Optional[AccessibilityMetadata], walk_meters: int = 0) -> int:
    """Calculates an objective accessibility score (0-100) based on confirmed transit data."""
    if not acc:
        return 45  # Baseline when data unavailable
    if acc.status == AccessibilityStatus.NOT_ACCESSIBLE:
        score = 15
        if walk_meters <= 400:
            score += 10
        return score
    if acc.status == AccessibilityStatus.UNKNOWN:
        return 45
    score = 40  # Verified accessible foundation
    if acc.wheelchair_accessible:
        score += 25
    if acc.low_floor_bus:
        score += 15
    if acc.boarding_assistance_available:
        score += 10
    if acc.audio_announcements:
        score += 5
    if acc.visual_displays:
        score += 5
    if walk_meters <= 400:
        score += 10
    elif walk_meters <= 800:
        score += 5
    return min(100, score)


class JourneyService:
    """
    Search and transit matching engine connecting passenger origin-destination
    pairs to optimal BMTC routes.
    """

    @classmethod
    async def search_journey(cls, request: JourneySearchRequest) -> JourneySearchResponse:
        origin_q = request.origin.strip().lower()
        dest_q = request.destination.strip().lower()

        provider = get_transit_provider()
        all_buses = await provider.get_buses()
        options: List[JourneyOption] = []

        for bus in all_buses:
            route = await provider.get_bus_route(bus.bus_id)
            if not route:
                continue

            stops_lower = [s.lower() for s in route.stops]
            dest_lower = route.destination.lower()
            source_lower = route.source.lower()

            matches_origin = (
                not origin_q
                or any(origin_q in s for s in stops_lower)
                or origin_q in source_lower
                or "current" in origin_q
                or "silk" in origin_q  # Default user mock location is Silk Board
            )

            matches_dest = (
                not dest_q
                or any(dest_q in s for s in stops_lower)
                or dest_q in dest_lower
                or (dest_q in bus.route_number.lower())
            )

            if matches_origin and matches_dest:
                # Fare estimation (Ordinary ₹15-25, AC Vajra ₹25-45, Airport KIA ₹150-250)
                if "KIA" in bus.route_number:
                    fare = 240
                elif bus.bus_type == "Vajra Electric":
                    fare = 35
                else:
                    fare = 20

                pred_resp = await CrowdPredictionService.predict_for_bus(bus.bus_id)
                pred_occ = pred_resp.predictions[0].occupancy_percent if (pred_resp and pred_resp.predictions) else bus.occupancy_percentage
                pred_seats = pred_resp.predictions[0].estimated_seats if (pred_resp and pred_resp.predictions) else (bus.available_seats or 12)

                eta_obj = await provider.get_eta(bus.bus_id, target_stop_name=route.destination)
                eta_src = eta_obj.source if eta_obj else "geometric_estimate"
                is_rt = provider.is_realtime()
                data_src = "authorized_gtfs_rt" if is_rt else "simulated_corridor"
                freshness_status = "simulated" if not is_rt else ("stale" if provider.is_stale else "fresh")
                alerts = alert_service.get_alerts(route_number=bus.route_number)
                walk_m = 350
                walk_min = 4
                bus_ride_m = max(10, route.estimated_duration - 11)
                walk_dest_m = 600
                walk_dest_min = 7
                inc_assess = incident_impact_service.assess_route(bus.route_number)
                has_disr = inc_assess.is_affected or len(alerts) > 0
                disr_id = inc_assess.incident_id or (alerts[0].id if alerts else None)
                alt_options = incident_impact_service.find_alternative_options(bus.route_number, route.destination) if inc_assess.is_affected else None
                if inc_assess.is_affected:
                    metrics_service.route_disruption_views += 1

                bus_acc = bus.accessibility
                bus_crowd = bus.crowd or crowd_service.get_crowd_metadata(bus.bus_id, bus.route_number)
                total_walk = walk_m + walk_dest_m
                opt_score = compute_accessibility_score(bus_acc, total_walk)

                legs_list = [
                    JourneyLeg(
                        leg_type="WALK",
                        sequence=1,
                        origin_name=request.origin or "Origin",
                        destination_name=route.stops[0],
                        distance_meters=walk_m,
                        duration_minutes=walk_min,
                        accessibility=AccessibilityMetadata(
                            status=AccessibilityStatus.ACCESSIBLE if walk_m <= 400 else AccessibilityStatus.NOT_ACCESSIBLE,
                            accessible_stop=True if walk_m <= 400 else False,
                            accessibility_disclosure="Walking segment with pedestrian pavement." if walk_m <= 400 else "Walking segment exceeds 400m.",
                            accessibility_source="pedestrian_network",
                        ),
                    ),
                    JourneyLeg(
                        leg_type="BUS",
                        sequence=2,
                        route_number=bus.route_number,
                        bus_id=bus.bus_id,
                        bus_type=bus.bus_type,
                        boarding_stop=route.stops[0],
                        alighting_stop=route.destination,
                        duration_minutes=bus_ride_m,
                        fare=fare,
                        eta=bus.eta_minutes,
                        eta_source=eta_src,
                        data_source=data_src,
                        accessibility=bus_acc,
                        crowd=bus_crowd,
                    ),
                    JourneyLeg(
                        leg_type="WALK",
                        sequence=3,
                        origin_name=route.destination,
                        destination_name=request.destination or "Destination",
                        distance_meters=walk_dest_m,
                        duration_minutes=walk_dest_min,
                        accessibility=AccessibilityMetadata(
                            status=AccessibilityStatus.ACCESSIBLE if walk_dest_m <= 400 else AccessibilityStatus.NOT_ACCESSIBLE,
                            accessible_stop=True if walk_dest_m <= 400 else False,
                            accessibility_disclosure="Walking segment with pedestrian pavement." if walk_dest_m <= 400 else "Walking segment exceeds 400m.",
                            accessibility_source="pedestrian_network",
                        ),
                    ),
                ]

                options.append(
                    JourneyOption(
                        route_number=bus.route_number,
                        destination=bus.destination,
                        bus_id=bus.bus_id,
                        bus_type=bus.bus_type,
                        eta_minutes=bus.eta_minutes or (eta_obj.eta_minutes if eta_obj else 6),
                        journey_duration_minutes=route.estimated_duration,
                        occupancy_percentage=bus.occupancy_percentage,
                        available_seats=bus.available_seats or 12,
                        predicted_occupancy_percent=pred_occ,
                        predicted_seats=pred_seats,
                        number_of_stops=len(route.stops),
                        origin_stop=route.stops[0],
                        destination_stop=route.destination,
                        fare_rupees=fare,
                        data_source=data_src,
                        eta_source=eta_src,
                        freshness=freshness_status,
                        transfers=0,
                        walking_distance_meters=walk_m + walk_dest_m,
                        walking_duration_minutes=walk_min + walk_dest_min,
                        service_alerts_count=max(len(alerts), 1 if inc_assess.is_affected else 0),
                        walk_to_stop_meters=walk_m,
                        walk_to_stop_minutes=walk_min,
                        bus_ride_minutes=bus_ride_m,
                        walk_from_stop_meters=walk_dest_m,
                        walk_from_stop_minutes=walk_dest_min,
                        has_disruption=has_disr,
                        disruption_alert_id=disr_id,
                        legs=legs_list,
                        is_multimodal=False,
                        accessibility=bus_acc,
                        accessibility_score=opt_score,
                        crowd=bus_crowd,
                        crowd_status=bus_crowd.crowd_status,
                        estimated_seat_availability=bus_crowd.estimated_seat_availability,
                        standing_likelihood=bus_crowd.standing_likelihood,
                        incident_impact=inc_assess if inc_assess.is_affected else None,
                        alternative_options=alt_options,
                    )
                )

        # Multi-corridor transfer option generation (e.g. 500D Outer Ring Road transferring to 356 at Silk Board)
        bus_500d = next((b for b in all_buses if "500D" in b.route_number.upper()), None)
        bus_356 = next((b for b in all_buses if "356" in b.route_number.upper()), None)
        if bus_500d and bus_356 and not any(o.transfers == 1 for o in options):
            xfer_alerts = alert_service.get_alerts(route_number=bus_356.route_number)
            first_alerts = alert_service.get_alerts(route_number=bus_500d.route_number)
            xfer_details = TransferDetails(
                transfer_stop="Central Silk Board Junction",
                walking_distance_meters=250,
                walking_duration_minutes=3,
                transfer_buffer_minutes=max(1, (bus_356.eta_minutes or 6) - 3),
                connecting_route=bus_356.route_number,
                connecting_bus_id=bus_356.bus_id,
                connecting_bus_eta_minutes=bus_356.eta_minutes or 6,
                connecting_bus_eta_source="geometric_estimate",
                connecting_bus_status="approaching",
                has_alert=len(xfer_alerts) > 0,
                alert_message=xfer_alerts[0].title if xfer_alerts else None,
            )
            xfer_acc = AccessibilityMetadata(
                status=AccessibilityStatus.NOT_ACCESSIBLE,
                wheelchair_accessible=False,
                low_floor_bus=False,
                boarding_assistance_available=False,
                accessible_stop=True,
                audio_announcements=False,
                visual_displays=False,
                accessibility_disclosure="Transfer journey contains high-floor bus leg on Route 356 (not wheelchair accessible).",
                accessibility_source="bmtc_fleet_registry",
            )
            xfer_score = compute_accessibility_score(xfer_acc, 650)
            xfer_legs = [
                JourneyLeg(leg_type="WALK", sequence=1, origin_name=request.origin or "Origin", destination_name="Electronic City", distance_meters=350, duration_minutes=4),
                JourneyLeg(leg_type="BUS", sequence=2, route_number=bus_500d.route_number, bus_id=bus_500d.bus_id, bus_type=bus_500d.bus_type, boarding_stop="Electronic City", alighting_stop="Central Silk Board Junction", duration_minutes=22, fare=20, eta=bus_500d.eta_minutes, eta_source="geometric_estimate", data_source="simulated_corridor", accessibility=bus_500d.accessibility),
                JourneyLeg(leg_type="TRANSFER", sequence=3, transfer_stop="Central Silk Board Junction", walking_distance_meters=250, walking_duration_minutes=3, transfer_buffer_minutes=xfer_details.transfer_buffer_minutes, connecting_route=bus_356.route_number, connecting_bus_id=bus_356.bus_id, connecting_bus_eta=bus_356.eta_minutes or 6),
                JourneyLeg(leg_type="BUS", sequence=4, route_number=bus_356.route_number, bus_id=bus_356.bus_id, bus_type=bus_356.bus_type, boarding_stop="Central Silk Board Junction", alighting_stop="Shivajinagar Bus Station", duration_minutes=18, fare=20, eta=bus_356.eta_minutes or 6, accessibility=bus_356.accessibility),
                JourneyLeg(leg_type="WALK", sequence=5, origin_name="Shivajinagar Bus Station", destination_name=request.destination or "Destination", distance_meters=400, duration_minutes=5),
            ]
            xfer_crowd = bus_500d.crowd or crowd_service.get_crowd_metadata(bus_500d.bus_id, bus_500d.route_number)
            options.append(
                JourneyOption(
                    route_number=bus_500d.route_number,
                    destination="Shivajinagar (Transfer Silk Board)",
                    bus_id=bus_500d.bus_id,
                    bus_type=bus_500d.bus_type,
                    eta_minutes=bus_500d.eta_minutes or 5,
                    journey_duration_minutes=52,
                    occupancy_percentage=bus_500d.occupancy_percentage,
                    available_seats=bus_500d.available_seats or 14,
                    number_of_stops=12,
                    origin_stop="Electronic City",
                    destination_stop="Shivajinagar Bus Station",
                    fare_rupees=35,
                    data_source="simulated_corridor",
                    eta_source="geometric_estimate",
                    freshness="simulated",
                    transfers=1,
                    walking_distance_meters=650,
                    walking_duration_minutes=9,
                    service_alerts_count=len(first_alerts) + len(xfer_alerts),
                    walk_to_stop_meters=350,
                    walk_to_stop_minutes=4,
                    bus_ride_minutes=40,
                    walk_from_stop_meters=400,
                    walk_from_stop_minutes=5,
                    has_disruption=len(first_alerts) > 0 or len(xfer_alerts) > 0,
                    legs=xfer_legs,
                    transfer_details=xfer_details,
                    is_multimodal=True,
                    accessibility=xfer_acc,
                    accessibility_score=xfer_score,
                    crowd=xfer_crowd,
                    crowd_status=xfer_crowd.crowd_status,
                    estimated_seat_availability=xfer_crowd.estimated_seat_availability,
                    standing_likelihood=xfer_crowd.standing_likelihood,
                )
            )

        # Fallback: if no direct match found, return the closest corridor routes so the user is never stuck
        if not options:
            for bus in all_buses[:3]:
                route = await provider.get_bus_route(bus.bus_id)
                alerts = alert_service.get_alerts(route_number=bus.route_number)
                bus_acc = bus.accessibility
                bus_crowd = bus.crowd or crowd_service.get_crowd_metadata(bus.bus_id, bus.route_number)
                options.append(
                    JourneyOption(
                        route_number=bus.route_number,
                        destination=bus.destination,
                        bus_id=bus.bus_id,
                        bus_type=bus.bus_type,
                        eta_minutes=bus.eta_minutes or 8,
                        journey_duration_minutes=route.estimated_duration if route else 35,
                        occupancy_percentage=bus.occupancy_percentage,
                        available_seats=bus.available_seats or 15,
                        number_of_stops=len(route.stops) if route else 6,
                        origin_stop="Central Silk Board Junction",
                        destination_stop=bus.destination,
                        fare_rupees=25,
                        walk_to_stop_meters=350,
                        walk_to_stop_minutes=4,
                        bus_ride_minutes=24,
                        walk_from_stop_meters=600,
                        walk_from_stop_minutes=7,
                        has_disruption=len(alerts) > 0,
                        disruption_alert_id=alerts[0].id if alerts else None,
                        service_alerts_count=len(alerts),
                        accessibility=bus_acc,
                        accessibility_score=compute_accessibility_score(bus_acc, 950),
                        crowd=bus_crowd,
                        crowd_status=bus_crowd.crowd_status,
                        estimated_seat_availability=bus_crowd.estimated_seat_availability,
                        standing_likelihood=bus_crowd.standing_likelihood,
                    )
                )

        # Check commuter preferences or queries prioritizing accessibility
        prefs = personalization_service.get_preferences()
        wants_accessible = (
            prefs.accessibility_priority
            or prefs.wheelchair_required
            or prefs.low_floor_preferred
            or prefs.reduced_walking_preferred
            or prefs.senior_friendly_preferred
            or any(kw in origin_q or kw in dest_q for kw in ["wheelchair", "accessible", "low floor", "low-floor", "senior", "elderly", "ramp"])
        )

        if wants_accessible:
            metrics_service.accessible_journey_searches += 1
            if prefs.wheelchair_required or "wheelchair" in origin_q or "wheelchair" in dest_q:
                metrics_service.wheelchair_priority_queries += 1
            if prefs.low_floor_preferred or "low floor" in origin_q or "low floor" in dest_q:
                metrics_service.low_floor_filter_applied += 1

            options.sort(
                key=lambda opt: (
                    -(opt.accessibility_score or 0),
                    opt.walking_distance_meters or 9999,
                    opt.journey_duration_minutes,
                )
            )

        metrics_service.accessible_options_viewed += sum(
            1 for o in options if o.accessibility and o.accessibility.status == AccessibilityStatus.ACCESSIBLE
        )
        metrics_service.crowd_comparison_views += 1

        return JourneySearchResponse(
            origin=request.origin,
            destination=request.destination,
            options=options,
        )
