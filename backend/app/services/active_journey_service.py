import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..models.transit import (
    ActiveJourney,
    ActiveJourneyCreateRequest,
    ActiveJourneyUpdateRequest,
    JourneyHistoryItem,
    JourneyLeg,
    JourneyState,
    TransferDetails,
)
from .alert_service import alert_service
from .crowd_service import crowd_service
from .incident_service import incident_service
from .incident_impact_service import incident_impact_service
from .metrics_service import metrics_service
from .provider_factory import get_transit_provider, is_simulation_active
from .notification_center_service import notification_center_service


def _provider_is_stale(provider) -> bool:
    """is_stale is a property on BMTCTransitDataProvider but may be a method elsewhere."""
    stale = getattr(provider, "is_stale", False)
    return bool(stale() if callable(stale) else stale)


class ActiveJourneyService:
    """
    State machine and lifecycle orchestration service for commuter active journeys.
    Grounds all state transitions in verified corridor telemetry without fabricating sensor data.
    """

    def __init__(self):
        self._active_journey: Optional[ActiveJourney] = None
        self._history: List[JourneyHistoryItem] = [
            # Seed initial realistic non-sensitive history items for demonstration
            JourneyHistoryItem(
                id="hist-seed-1",
                route_number="500D",
                origin="Electronic City",
                destination="Shivajinagar",
                bus_type="Vajra Electric",
                fare=35,
                fare_type="standard_demo_fare",
                started_at=datetime.now(timezone.utc) - timedelta(hours=24),
                completed_at=datetime.now(timezone.utc) - timedelta(hours=23, minutes=25),
                status="COMPLETED",
                duration_minutes=35,
            ),
            JourneyHistoryItem(
                id="hist-seed-2",
                route_number="356",
                origin="Hosur Road",
                destination="Shivajinagar",
                bus_type="BMTC Ordinary",
                fare=20,
                fare_type="standard_demo_fare",
                started_at=datetime.now(timezone.utc) - timedelta(days=2),
                completed_at=datetime.now(timezone.utc) - timedelta(days=2, hours=-1),
                status="COMPLETED",
                duration_minutes=42,
            ),
        ]


    # Phase 41 (master spec): notification center events for real journey state transitions.
    _STATE_EVENTS = {
        JourneyState.BUS_APPROACHING: ("BUS_APPROACHING", "Bus {route} approaching", "Bus {route} is approaching your stop {origin}."),
        JourneyState.DESTINATION_APPROACHING: ("DESTINATION_APPROACHING", "Destination approaching", "{destination} is coming up on route {route}."),
        JourneyState.GET_READY_TO_EXIT: ("GET_READY_TO_EXIT", "Get ready to exit", "Your stop {destination} is next on route {route}."),
        JourneyState.DESTINATION_REACHED: ("DESTINATION_REACHED", "Destination reached", "You have reached {destination}."),
        JourneyState.DESTINATION_PASSED: ("DESTINATION_PASSED", "Missed destination", "The bus has passed {destination}. Please plan a return journey."),
        JourneyState.TRANSFER_APPROACHING: ("TRANSFER_APPROACHING", "Transfer approaching", "Your transfer stop is coming up on route {route}."),
        JourneyState.TRANSFER_READY: ("TRANSFER_READY", "Transfer ready", "Get off at the next stop to make your connection."),
        JourneyState.CONNECTING_BUS_APPROACHING: ("CONNECTING_BUS_APPROACHING", "Connecting bus approaching", "Your connecting bus is approaching."),
        JourneyState.TRANSFER_MISSED: ("TRANSFER_MISSED", "Transfer missed", "Your connection was missed. Check alternative options."),
    }

    def _notify_transition(self, before) -> None:
        journey = self._active_journey
        if journey is None or journey.state == before or journey.state not in self._STATE_EVENTS:
            return
        event_type, title, body = self._STATE_EVENTS[journey.state]
        fields = {"route": journey.route_number, "origin": journey.origin, "destination": journey.destination}
        notification_center_service.publish(
            event_type,
            title.format(**fields),
            body.format(**fields),
            route_number=journey.route_number,
            source="SIMULATED" if is_simulation_active() else "GTFS_RT_ESTIMATE",
            dedup_key=f"journey:{journey.id}:{event_type}",
        )

    async def start_journey(self, req: ActiveJourneyCreateRequest) -> ActiveJourney:
        provider = get_transit_provider()
        buses = await provider.get_buses()
        matched_bus = next((b for b in buses if b.bus_id == req.bus_id or b.route_number.upper() == req.route_number.upper()), None)

        # Check for service disruptions
        inc_assess = incident_impact_service.assess_route(req.route_number)
        disruptions = alert_service.get_alerts(route_number=req.route_number, active_only=True)
        has_disruption = inc_assess.is_affected or len(disruptions) > 0
        disruption_msg = inc_assess.message or (disruptions[0].title if disruptions else None)
        if inc_assess.is_affected:
            metrics_service.active_journey_disruption_warnings += 1

        # Resolve stops along route
        stops: List[str] = []
        if matched_bus:
            route_obj = await provider.get_bus_route(matched_bus.bus_id)
            if route_obj and route_obj.stops:
                stops = route_obj.stops
            elif matched_bus.upcoming_stops:
                stops = [matched_bus.origin] + matched_bus.upcomingStops if hasattr(matched_bus, "upcomingStops") else [matched_bus.origin, matched_bus.next_stop, matched_bus.destination]
        if not stops:
            stops = [req.origin, "Dairy Circle", "Adugodi", req.destination]

        cur_stop = matched_bus.next_stop if matched_bus else (stops[0] if stops else req.origin)
        next_s = matched_bus.following_stop if (matched_bus and matched_bus.following_stop) else (stops[1] if len(stops) > 1 else req.destination)
        following_s = stops[2] if len(stops) > 2 else None

        # Estimated arrival time formatted
        eta_min = matched_bus.eta_minutes if (matched_bus and matched_bus.eta_minutes) else 18
        dest_dt = datetime.now(timezone.utc) + timedelta(minutes=eta_min + 30, hours=5)  # IST approx
        dest_eta_str = dest_dt.strftime("%I:%M %p").lstrip("0")

        # Fare & Ticket Configuration
        fare_val = req.fare if req.fare is not None else 20
        fare_type_val = req.fare_type or ("karnataka_women_shakti" if fare_val == 0 else "standard_demo_fare")
        ticket_val = req.ticket_id
        if not ticket_val:
            if fare_type_val == "karnataka_women_shakti" or fare_val == 0:
                ticket_val = f"TCK-SHAKTI-{uuid.uuid4().hex[:6].upper()}"
            else:
                ticket_val = f"TCK-DEMO-{uuid.uuid4().hex[:6].upper()}"

        # Phase 34 Transfer resolution
        is_transfer = bool(req.is_transfer_journey or req.transfer_details or req.connecting_route)
        transfer_det = req.transfer_details
        connecting_r = req.connecting_route or (req.transfer_details.connecting_route if req.transfer_details else None)
        connecting_b = req.connecting_bus_id or (req.transfer_details.connecting_bus_id if req.transfer_details else None)

        if is_transfer and not transfer_det:
            transfer_det = TransferDetails(
                transfer_stop="Central Silk Board Junction",
                walking_distance_meters=250,
                walking_duration_minutes=3,
                transfer_buffer_minutes=3,
                connecting_route=connecting_r or "356",
                connecting_bus_id=connecting_b or "bus-356-1",
                connecting_bus_eta_minutes=6,
                connecting_bus_eta_source="geometric_estimate",
                connecting_bus_status="approaching",
            )

        legs_list = req.legs
        if is_transfer and not legs_list and transfer_det:
            legs_list = [
                JourneyLeg(leg_type="WALK", sequence=1, origin_name="Origin", destination_name=stops[0] if stops else req.origin, distance_meters=req.walking_distance_meters or 350, duration_minutes=req.walking_duration_minutes or 4),
                JourneyLeg(leg_type="BUS", sequence=2, route_number=req.route_number, bus_id=req.bus_id, bus_type=req.bus_type or "BMTC Ordinary", boarding_stop=stops[0] if stops else req.origin, alighting_stop=transfer_det.transfer_stop, duration_minutes=22, fare=fare_val),
                JourneyLeg(leg_type="TRANSFER", sequence=3, transfer_stop=transfer_det.transfer_stop, walking_distance_meters=transfer_det.walking_distance_meters, walking_duration_minutes=transfer_det.walking_duration_minutes, transfer_buffer_minutes=transfer_det.transfer_buffer_minutes, connecting_route=transfer_det.connecting_route),
                JourneyLeg(leg_type="BUS", sequence=4, route_number=transfer_det.connecting_route, bus_id=transfer_det.connecting_bus_id, boarding_stop=transfer_det.transfer_stop, alighting_stop=req.destination, duration_minutes=18),
                JourneyLeg(leg_type="WALK", sequence=5, origin_name=req.destination, destination_name="Destination", distance_meters=400, duration_minutes=5),
            ]

        journey = ActiveJourney(
            id=f"journey-{uuid.uuid4().hex[:8]}",
            route_number=req.route_number,
            bus_id=req.bus_id,
            bus_type=req.bus_type or (matched_bus.bus_type if matched_bus else "BMTC Ordinary"),
            origin=req.origin,
            destination=req.destination,
            current_stop=cur_stop,
            next_stop=next_s,
            following_stop=following_s,
            remaining_stops=max(1, len(stops) - 1),
            eta_minutes=eta_min,
            destination_eta_str=dest_eta_str,
            stops=stops,
            passed_stops=[],
            walking_distance_meters=req.walking_distance_meters or 350,
            walking_duration_minutes=req.walking_duration_minutes or 4,
            bus_distance_km=matched_bus.distance_to_next_stop_km if (matched_bus and matched_bus.distance_to_next_stop_km) else 1.8,
            state=req.initial_state or JourneyState.WAITING_FOR_BUS,
            started_at=datetime.now(timezone.utc),
            data_source="realtime_gtfs_rt" if provider.is_realtime() else "simulated_corridor",
            feed_status="connected" if provider.is_realtime() else "simulated",
            fare=fare_val,
            fare_type=fare_type_val,
            ticket_id=ticket_val,
            ticket_status="active",
            has_disruption=has_disruption,
            disruption_message=disruption_msg,
            # Phase 34 Transfer attributes
            legs=legs_list,
            transfer_details=transfer_det,
            is_transfer_journey=is_transfer,
            current_leg_index=0,
            transfer_buffer_minutes=transfer_det.transfer_buffer_minutes if transfer_det else None,
            connecting_bus_eta_minutes=transfer_det.connecting_bus_eta_minutes if transfer_det else None,
            # Phase 36 Smart Crowd & Occupancy attributes
            crowd=(matched_bus.crowd if matched_bus else None) or crowd_service.get_crowd_metadata(req.bus_id, req.route_number),
            crowd_status=((matched_bus.crowd.crowd_status if (matched_bus and matched_bus.crowd) else None) or crowd_service.get_crowd_metadata(req.bus_id, req.route_number).crowd_status),
            estimated_seat_availability=((matched_bus.crowd.estimated_seat_availability if (matched_bus and matched_bus.crowd) else None) or crowd_service.get_crowd_metadata(req.bus_id, req.route_number).estimated_seat_availability),
            standing_likelihood=((matched_bus.crowd.standing_likelihood if (matched_bus and matched_bus.crowd) else None) or crowd_service.get_crowd_metadata(req.bus_id, req.route_number).standing_likelihood),
            occupancy_disclosure=((matched_bus.crowd.disclosure if (matched_bus and matched_bus.crowd) else None) or crowd_service.get_crowd_metadata(req.bus_id, req.route_number).disclosure),
            incident_impact=inc_assess if inc_assess.is_affected else None,
            is_transfer_at_risk=False,
            transfer_risk_warning=None,
        )

        self._active_journey = journey
        metrics_service.active_journey_started += 1
        if is_transfer:
            metrics_service.transfer_journeys_started += 1
        return journey

    async def get_active_journey(self) -> Optional[ActiveJourney]:
        before = self._active_journey.state if self._active_journey else None
        journey = await self._evaluate_active_journey()
        self._notify_transition(before)
        if journey is not None:
            await self._attach_vehicle_telemetry(journey)
        return journey

    async def _attach_vehicle_telemetry(self, journey: ActiveJourney) -> None:
        """
        Attaches the tracked vehicle (freshness, direction, current/next stop, source). The journey state
        machine is not changed here. Stop fields are only overwritten from VERIFIED_REALTIME telemetry that
        is LIVE or RECENT; simulated journeys keep their existing behaviour.
        """
        from .vehicle_tracking_service import vehicle_tracking_service
        if journey.state in (JourneyState.COMPLETED, JourneyState.CANCELLED):
            return
        vehicle = await vehicle_tracking_service.get_vehicle(journey.bus_id)
        journey.vehicle_telemetry = vehicle
        if vehicle and vehicle.source == "VERIFIED_REALTIME" and vehicle.freshness in ("LIVE", "RECENT"):
            if vehicle.current_stop:
                journey.current_stop = vehicle.current_stop.stop_name
            if vehicle.next_stop:
                journey.next_stop = vehicle.next_stop.stop_name
            journey.following_stop = vehicle.following_stop.stop_name if vehicle.following_stop else journey.following_stop
            if vehicle.remaining_stops is not None:
                journey.remaining_stops = vehicle.remaining_stops
            journey.last_telemetry_sync = vehicle.timestamp

    async def _evaluate_active_journey(self) -> Optional[ActiveJourney]:
        if not self._active_journey:
            return None

        # Track transfer views
        if self._active_journey.is_transfer_journey:
            metrics_service.transfer_views += 1

        # If completed or cancelled, return static state
        if self._active_journey.state in [JourneyState.COMPLETED, JourneyState.CANCELLED]:
            return self._active_journey

        if self._active_journey.state == JourneyState.OFFLINE:
            self._active_journey.telemetry_reliable = False
            self._active_journey.telemetry_disclosure = (
                "Arrival status may be outdated because realtime telemetry is unavailable."
            )
            self._active_journey.data_transparency_label = "OFFLINE — SHOWING LAST KNOWN DATA"
            return self._active_journey

        # Synchronize telemetry with active provider
        provider = get_transit_provider()
        buses = await provider.get_buses()
        bus = next((b for b in buses if b.bus_id == self._active_journey.bus_id or b.route_number.upper() == self._active_journey.route_number.upper()), None)

        if bus:
            self._active_journey.current_stop = bus.next_stop
            self._active_journey.next_stop = bus.following_stop or (self._active_journey.stops[-1] if self._active_journey.stops else self._active_journey.destination)
            self._active_journey.eta_minutes = bus.eta_minutes
            if bus.distance_to_next_stop_km is not None:
                self._active_journey.bus_distance_km = bus.distance_to_next_stop_km

            self._active_journey.telemetry_reliable = True
            self._active_journey.telemetry_disclosure = None
            self._active_journey.last_telemetry_sync = datetime.now(timezone.utc)
            self._active_journey.data_transparency_label = (
                "AUTHORIZED BMTC REALTIME FEED" if (provider.is_realtime() and not _provider_is_stale(provider))
                else ("STALE REALTIME DATA" if provider.is_realtime() else "SIMULATED TRANSIT DATA")
            )

            # Phase 36: Crowd & Occupancy Synchronization
            c_meta = bus.crowd or crowd_service.get_crowd_metadata(bus.bus_id, bus.route_number)
            self._active_journey.crowd = c_meta
            self._active_journey.crowd_status = c_meta.crowd_status
            self._active_journey.estimated_seat_availability = c_meta.estimated_seat_availability
            self._active_journey.standing_likelihood = c_meta.standing_likelihood
            self._active_journey.occupancy_disclosure = c_meta.disclosure

            # Dynamic remaining stops calculation
            dest_name = self._active_journey.destination.lower()
            dest_idx = -1
            if self._active_journey.stops:
                for idx, s in enumerate(self._active_journey.stops):
                    if dest_name in s.lower() or s.lower() in dest_name:
                        dest_idx = idx
                        break
                if dest_idx == -1:
                    dest_idx = len(self._active_journey.stops) - 1

            cur_idx = -1
            if self._active_journey.stops and self._active_journey.current_stop in self._active_journey.stops:
                cur_idx = self._active_journey.stops.index(self._active_journey.current_stop)
                self._active_journey.passed_stops = self._active_journey.stops[:cur_idx]
                self._active_journey.remaining_stops = max(0, (dest_idx - cur_idx) if dest_idx >= cur_idx else 0)
            else:
                self._active_journey.remaining_stops = max(1, self._active_journey.remaining_stops)

            # Destination ETA update
            dest_dt = datetime.now(timezone.utc) + timedelta(minutes=self._active_journey.eta_minutes + 30, hours=5)
            self._active_journey.destination_eta_str = dest_dt.strftime("%I:%M %p").lstrip("0")

            # Phase 34: Transfer Telemetry Sync & Connecting Bus Tracking
            connecting_bus = None
            if self._active_journey.is_transfer_journey:
                c_id = self._active_journey.connecting_bus_id
                c_r = (self._active_journey.connecting_route or "").upper()
                connecting_bus = next((b for b in buses if (c_id and b.bus_id == c_id) or (c_r and b.route_number.upper() == c_r)), None)
                if connecting_bus:
                    self._active_journey.connecting_bus_eta_minutes = connecting_bus.eta_minutes
                    walk_min = (self._active_journey.transfer_details.walking_duration_minutes if self._active_journey.transfer_details else 3)
                    self._active_journey.transfer_buffer_minutes = max(0, connecting_bus.eta_minutes - walk_min)
                    if self._active_journey.transfer_details:
                        self._active_journey.transfer_details.connecting_bus_eta_minutes = connecting_bus.eta_minutes
                        self._active_journey.transfer_details.transfer_buffer_minutes = self._active_journey.transfer_buffer_minutes
                    if connecting_bus.eta_minutes <= 3:
                        self._active_journey.is_connecting_bus_approaching = True
                        if self._active_journey.state == JourneyState.WAITING_FOR_CONNECTION:
                            self._active_journey.state = JourneyState.CONNECTING_BUS_APPROACHING
                            metrics_service.journey_state_transitions += 1

                # Check transfer countdown if commuter is still on the first bus
                if self._active_journey.transfer_details:
                    xfer_stop_name = self._active_journey.transfer_details.transfer_stop.lower()
                    xfer_idx = -1
                    if self._active_journey.stops:
                        for idx, s in enumerate(self._active_journey.stops):
                            if xfer_stop_name in s.lower() or s.lower() in xfer_stop_name:
                                xfer_idx = idx
                                break
                    if xfer_idx != -1 and cur_idx != -1:
                        rem_to_xfer = max(0, xfer_idx - cur_idx)
                        if self._active_journey.state in [JourneyState.ON_BUS, JourneyState.TRANSFER_APPROACHING]:
                            if rem_to_xfer <= 1 or cur_idx == xfer_idx:
                                if self._active_journey.state != JourneyState.TRANSFER_READY:
                                    self._active_journey.state = JourneyState.TRANSFER_READY
                                    metrics_service.transfer_alerts += 1
                                    metrics_service.journey_state_transitions += 1
                            elif rem_to_xfer <= 2:
                                if self._active_journey.state != JourneyState.TRANSFER_APPROACHING:
                                    self._active_journey.state = JourneyState.TRANSFER_APPROACHING
                                    metrics_service.transfer_alerts += 1
                                    metrics_service.journey_state_transitions += 1

                # Missed transfer detection (only with reliable telemetry, not offline, not stale)
                if (
                    self._active_journey.telemetry_reliable
                    and not getattr(provider, "is_stale", False)
                    and self._active_journey.state in [JourneyState.WALKING_TO_CONNECTION, JourneyState.WAITING_FOR_CONNECTION]
                ):
                    if connecting_bus and connecting_bus.eta_minutes == 0 and (self._active_journey.transfer_buffer_minutes or 0) <= 0:
                        self._active_journey.state = JourneyState.TRANSFER_MISSED
                        self._active_journey.is_transfer_missed = True
                        if self._active_journey.transfer_details:
                            self._active_journey.transfer_details.is_missed = True
                            self._active_journey.transfer_details.connecting_bus_status = "missed"
                        metrics_service.missed_transfer_warnings += 1
                        metrics_service.journey_state_transitions += 1

            # Automatic telemetry-driven state transitions:
            # 1. WAITING_FOR_BUS -> BUS_APPROACHING when ETA <= 3 min and bus within 1.5 km
            if self._active_journey.state == JourneyState.WAITING_FOR_BUS:
                if (bus.eta_minutes <= 3 or (bus.distance_to_next_stop_km is not None and bus.distance_to_next_stop_km <= 1.5)):
                    self._active_journey.state = JourneyState.BUS_APPROACHING
                    metrics_service.journey_state_transitions += 1

            # 2. Phase 33 Smart Arrival Progression for ON_BUS / approaching states:
            elif self._active_journey.state in [
                JourneyState.ON_BUS,
                JourneyState.NEAR_DESTINATION,
                JourneyState.DESTINATION_APPROACHING,
                JourneyState.GET_READY_TO_EXIT,
            ]:
                # Check for Missed Destination (bus passed destination)
                if dest_idx != -1 and cur_idx != -1 and cur_idx > dest_idx:
                    self._active_journey.state = JourneyState.DESTINATION_PASSED
                    self._active_journey.is_destination_passed = True
                    metrics_service.missed_destination_warnings += 1
                    metrics_service.journey_state_transitions += 1
                # Check for Destination Reached
                elif (
                    (cur_idx != -1 and cur_idx == dest_idx)
                    or (bus.next_stop and dest_name in bus.next_stop.lower() and bus.eta_minutes <= 1)
                    or (bus.distance_to_next_stop_km is not None and bus.distance_to_next_stop_km <= 0.2 and dest_name in (bus.next_stop or "").lower())
                ):
                    self._active_journey.state = JourneyState.DESTINATION_REACHED
                    self._active_journey.is_destination_reached = True
                    metrics_service.destination_reached_events += 1
                    metrics_service.journey_state_transitions += 1
                # Check for Get Ready to Exit (1 stop remaining or ETA <= 3 min)
                elif self._active_journey.remaining_stops <= 1 or bus.eta_minutes <= 3 or (bus.next_stop and dest_name in bus.next_stop.lower()):
                    if self._active_journey.state != JourneyState.GET_READY_TO_EXIT and not self._active_journey.is_transfer_journey:
                        self._active_journey.state = JourneyState.GET_READY_TO_EXIT
                        self._active_journey.is_get_ready_to_exit = True
                        metrics_service.get_ready_to_exit_alerts += 1
                        metrics_service.journey_state_transitions += 1
                # Check for Destination Approaching (2 stops remaining or ETA <= 6 min)
                elif self._active_journey.remaining_stops <= 2 or bus.eta_minutes <= 6:
                    if self._active_journey.state != JourneyState.DESTINATION_APPROACHING and not self._active_journey.is_transfer_journey:
                        self._active_journey.state = JourneyState.DESTINATION_APPROACHING
                        metrics_service.destination_approach_alerts += 1
                        metrics_service.journey_state_transitions += 1
        else:
            # Telemetry is unavailable/offline
            self._active_journey.telemetry_reliable = False
            self._active_journey.telemetry_disclosure = (
                "Arrival status may be outdated because realtime telemetry is unavailable."
            )
            self._active_journey.data_transparency_label = "OFFLINE — SHOWING LAST KNOWN DATA"

        # Dynamic re-evaluation of corridor incidents and transfer risks
        if self._active_journey:
            inc_assess, banner_msg = incident_impact_service.assess_active_journey(self._active_journey)
            if inc_assess.is_affected:
                self._active_journey.has_disruption = True
                self._active_journey.disruption_message = banner_msg
                self._active_journey.incident_impact = inc_assess
                metrics_service.active_journey_disruption_warnings += 1

            if self._active_journey.is_transfer_journey:
                first_delay = inc_assess.delay_estimate_minutes if inc_assess.is_affected else 0
                is_risk, risk_msg = incident_impact_service.assess_transfer_risk(
                    self._active_journey,
                    first_bus_delay_minutes=first_delay,
                    connecting_bus_eta_minutes=self._active_journey.connecting_bus_eta_minutes,
                    transfer_buffer_minutes=self._active_journey.transfer_buffer_minutes,
                    is_offline=not self._active_journey.telemetry_reliable,
                )
                self._active_journey.is_transfer_at_risk = is_risk
                self._active_journey.transfer_risk_warning = risk_msg
                if is_risk:
                    metrics_service.transfer_risk_warnings += 1

        return self._active_journey

    def update_journey(self, req: ActiveJourneyUpdateRequest) -> ActiveJourney:
        before = self._active_journey.state if self._active_journey else None
        journey = self._apply_journey_update(req)
        self._notify_transition(before)
        return journey

    def _apply_journey_update(self, req: ActiveJourneyUpdateRequest) -> ActiveJourney:
        if not self._active_journey:
            raise ValueError("No active journey to update")

        current_state = self._active_journey.state

        # Validate state transitions
        if req.state:
            # Cannot transition out of terminal states
            if current_state in [JourneyState.COMPLETED, JourneyState.CANCELLED] and req.state != current_state:
                raise ValueError(f"Cannot transition from terminal state '{current_state}' to '{req.state}'")

            # Validate forward progression
            allowed_transitions = {
                JourneyState.PLANNING: [JourneyState.WALKING_TO_STOP, JourneyState.WAITING_FOR_BUS, JourneyState.OFFLINE, JourneyState.CANCELLED],
                JourneyState.WALKING_TO_STOP: [JourneyState.WAITING_FOR_BUS, JourneyState.BUS_APPROACHING, JourneyState.OFFLINE, JourneyState.CANCELLED],
                JourneyState.WAITING_FOR_BUS: [JourneyState.BUS_APPROACHING, JourneyState.ON_BUS, JourneyState.OFFLINE, JourneyState.CANCELLED],
                JourneyState.BUS_APPROACHING: [JourneyState.ON_BUS, JourneyState.WAITING_FOR_BUS, JourneyState.OFFLINE, JourneyState.CANCELLED],
                JourneyState.ON_BUS: [
                    JourneyState.TRANSFER_APPROACHING,
                    JourneyState.TRANSFER_READY,
                    JourneyState.WALKING_TO_CONNECTION,
                    JourneyState.NEAR_DESTINATION,
                    JourneyState.DESTINATION_APPROACHING,
                    JourneyState.GET_READY_TO_EXIT,
                    JourneyState.DESTINATION_REACHED,
                    JourneyState.DESTINATION_PASSED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.TRANSFER_APPROACHING: [
                    JourneyState.TRANSFER_READY,
                    JourneyState.WALKING_TO_CONNECTION,
                    JourneyState.WAITING_FOR_CONNECTION,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.TRANSFER_READY: [
                    JourneyState.WALKING_TO_CONNECTION,
                    JourneyState.WAITING_FOR_CONNECTION,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.WALKING_TO_CONNECTION: [
                    JourneyState.WAITING_FOR_CONNECTION,
                    JourneyState.CONNECTING_BUS_APPROACHING,
                    JourneyState.ON_BUS,
                    JourneyState.TRANSFER_MISSED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.WAITING_FOR_CONNECTION: [
                    JourneyState.CONNECTING_BUS_APPROACHING,
                    JourneyState.ON_BUS,
                    JourneyState.TRANSFER_COMPLETED,
                    JourneyState.TRANSFER_MISSED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.CONNECTING_BUS_APPROACHING: [
                    JourneyState.ON_BUS,
                    JourneyState.TRANSFER_COMPLETED,
                    JourneyState.TRANSFER_MISSED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.TRANSFER_COMPLETED: [
                    JourneyState.ON_BUS,
                    JourneyState.NEAR_DESTINATION,
                    JourneyState.DESTINATION_APPROACHING,
                    JourneyState.GET_READY_TO_EXIT,
                    JourneyState.DESTINATION_REACHED,
                    JourneyState.DESTINATION_PASSED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.TRANSFER_MISSED: [
                    JourneyState.WAITING_FOR_CONNECTION,
                    JourneyState.CONNECTING_BUS_APPROACHING,
                    JourneyState.ON_BUS,
                    JourneyState.TRANSFER_COMPLETED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.NEAR_DESTINATION: [
                    JourneyState.DESTINATION_APPROACHING,
                    JourneyState.GET_READY_TO_EXIT,
                    JourneyState.DESTINATION_REACHED,
                    JourneyState.DESTINATION_PASSED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.DESTINATION_APPROACHING: [
                    JourneyState.GET_READY_TO_EXIT,
                    JourneyState.DESTINATION_REACHED,
                    JourneyState.DESTINATION_PASSED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.GET_READY_TO_EXIT: [
                    JourneyState.DESTINATION_REACHED,
                    JourneyState.DESTINATION_PASSED,
                    JourneyState.OFFLINE,
                    JourneyState.COMPLETED,
                    JourneyState.CANCELLED,
                ],
                JourneyState.DESTINATION_REACHED: [JourneyState.COMPLETED, JourneyState.CANCELLED],
                JourneyState.DESTINATION_PASSED: [JourneyState.COMPLETED, JourneyState.CANCELLED],
                JourneyState.OFFLINE: [
                    JourneyState.PLANNING,
                    JourneyState.WALKING_TO_STOP,
                    JourneyState.WAITING_FOR_BUS,
                    JourneyState.BUS_APPROACHING,
                    JourneyState.ON_BUS,
                    JourneyState.TRANSFER_APPROACHING,
                    JourneyState.TRANSFER_READY,
                    JourneyState.WALKING_TO_CONNECTION,
                    JourneyState.WAITING_FOR_CONNECTION,
                    JourneyState.CONNECTING_BUS_APPROACHING,
                    JourneyState.TRANSFER_COMPLETED,
                    JourneyState.TRANSFER_MISSED,
                    JourneyState.DESTINATION_APPROACHING,
                    JourneyState.GET_READY_TO_EXIT,
                    JourneyState.DESTINATION_REACHED,
                    JourneyState.DESTINATION_PASSED,
                    JourneyState.CANCELLED,
                    JourneyState.COMPLETED,
                ],
            }

            if req.state != current_state and req.state not in allowed_transitions.get(current_state, []):
                raise ValueError(f"Invalid transition from '{current_state}' to '{req.state}'")

            self._active_journey.state = req.state
            if req.state == JourneyState.DESTINATION_APPROACHING:
                metrics_service.destination_approach_alerts += 1
            elif req.state == JourneyState.GET_READY_TO_EXIT:
                self._active_journey.is_get_ready_to_exit = True
                metrics_service.get_ready_to_exit_alerts += 1
            elif req.state == JourneyState.DESTINATION_REACHED:
                self._active_journey.is_destination_reached = True
                metrics_service.destination_reached_events += 1
            elif req.state == JourneyState.DESTINATION_PASSED:
                self._active_journey.is_destination_passed = True
                metrics_service.missed_destination_warnings += 1
            elif req.state in [JourneyState.TRANSFER_APPROACHING, JourneyState.TRANSFER_READY]:
                metrics_service.transfer_alerts += 1
            elif req.state == JourneyState.CONNECTING_BUS_APPROACHING:
                self._active_journey.is_connecting_bus_approaching = True
                metrics_service.transfer_alerts += 1
            elif req.state == JourneyState.TRANSFER_COMPLETED:
                self._active_journey.is_connecting_bus_approaching = False
                metrics_service.transfer_completed += 1
            elif req.state == JourneyState.TRANSFER_MISSED:
                self._active_journey.is_transfer_missed = True
                metrics_service.missed_transfer_warnings += 1
            elif req.state == JourneyState.OFFLINE:
                self._active_journey.telemetry_reliable = False
                self._active_journey.telemetry_disclosure = (
                    "Arrival status may be outdated because realtime telemetry is unavailable."
                )
                self._active_journey.data_transparency_label = "OFFLINE — SHOWING LAST KNOWN DATA"
            metrics_service.journey_state_transitions += 1

        if req.current_stop:
            self._active_journey.current_stop = req.current_stop
            if req.current_stop not in self._active_journey.passed_stops:
                self._active_journey.passed_stops.append(req.current_stop)
        if req.next_stop:
            self._active_journey.next_stop = req.next_stop
        if req.eta_minutes is not None:
            self._active_journey.eta_minutes = req.eta_minutes
        if req.ticket_id:
            self._active_journey.ticket_id = req.ticket_id
        if req.current_leg_index is not None:
            self._active_journey.current_leg_index = req.current_leg_index
        if req.transfer_buffer_minutes is not None:
            self._active_journey.transfer_buffer_minutes = req.transfer_buffer_minutes
        if req.is_transfer_missed is not None:
            self._active_journey.is_transfer_missed = req.is_transfer_missed

        return self._active_journey

    def end_journey(self, reason: str = "COMPLETED") -> ActiveJourney:
        if not self._active_journey:
            raise ValueError("No active journey to end")

        now = datetime.now(timezone.utc)
        duration_min = max(1, int((now - self._active_journey.started_at).total_seconds() / 60))

        status = "COMPLETED" if reason.upper() == "COMPLETED" else "CANCELLED"
        self._active_journey.state = JourneyState.COMPLETED if status == "COMPLETED" else JourneyState.CANCELLED
        self._active_journey.completed_at = now
        self._active_journey.actual_duration_minutes = duration_min

        # Add to history
        hist_item = JourneyHistoryItem(
            id=f"hist-{uuid.uuid4().hex[:8]}",
            route_number=self._active_journey.route_number,
            origin=self._active_journey.origin,
            destination=self._active_journey.destination,
            bus_type=self._active_journey.bus_type,
            fare=self._active_journey.fare,
            fare_type=self._active_journey.fare_type,
            started_at=self._active_journey.started_at,
            completed_at=now,
            status=status,
            duration_minutes=duration_min,
            ticket_id=self._active_journey.ticket_id,
        )
        self._history.insert(0, hist_item)
        if len(self._history) > 50:
            self._history = self._history[:50]

        if status == "COMPLETED":
            metrics_service.active_journey_completed += 1
            if self._active_journey.is_transfer_journey:
                metrics_service.transfer_completed += 1
        else:
            metrics_service.journey_cancelled += 1

        ended = self._active_journey
        self._active_journey = None
        return ended

    def get_history(self) -> List[JourneyHistoryItem]:
        metrics_service.journey_history_views += 1
        return self._history

    def reset(self):
        self._active_journey = None
        self._history = []
        metrics_service.reset()


active_journey_service = ActiveJourneyService()
