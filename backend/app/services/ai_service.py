import re
from typing import Any, Dict, Optional, Tuple

from .ai_provider import get_ai_provider
from .provider_factory import get_transit_provider, get_provider_health
from .journey_service import JourneyService
from .crowd_prediction_service import CrowdPredictionService
from .crowd_service import crowd_service
from .alert_service import alert_service
from .incident_service import incident_service
from .incident_impact_service import incident_impact_service
from .active_journey_service import active_journey_service
from .metrics_service import metrics_service
from ..models.transit import AIChatRequest, AIChatResponse, JourneySearchRequest


# In-memory session context for multi-turn conversation memory
_SESSION_MEMORY: Dict[str, Dict[str, Any]] = {}


class IntentDetector:
    """Natural-language query analyzer for BMTC transit queries."""

    BUS_PATTERNS = [
        r"\b500[- ]?D\b",
        r"\b356\b",
        r"\b201[- ]?R\b",
        r"\bKIA[- ]?8\b",
        r"\bG[- ]?2\b",
    ]

    @classmethod
    def extract_route_number(cls, text: str) -> Optional[str]:
        for pattern in cls.BUS_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                clean = match.group(0).upper().replace(" ", "").replace("-", "")
                # Normalize formatting
                if clean == "500D":
                    return "500D"
                if clean == "356":
                    return "356"
                if clean == "201R":
                    return "201R"
                if clean == "KIA8":
                    return "KIA-8"
                if clean == "G2":
                    return "G-2"
        # Also check for any 3-digit or route-like token
        generic_match = re.search(r"\b([0-9]{3}[A-Z]?|KIA[- ]?[0-9]+|G[- ]?[0-9]+)\b", text, re.IGNORECASE)
        if generic_match:
            return generic_match.group(0).upper()
        return None

    @classmethod
    def extract_journey_endpoints(cls, text: str) -> Tuple[Optional[str], Optional[str]]:
        # Pattern: from X to Y
        m = re.search(r"from\s+([a-zA-Z\s]+?)\s+to\s+([a-zA-Z\s]+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        # Pattern: to Y
        m2 = re.search(r"to\s+([a-zA-Z\s]+)", text, re.IGNORECASE)
        if m2:
            return "Central Silk Board Junction", m2.group(1).strip()
        return None, None

    @classmethod
    def detect_intent(cls, message: str) -> str:
        q = message.lower().strip()
        if not q:
            return "general"

        # Phase 41 Safety & Emergency Assistance Intents
        if any(w in q for w in ["safety status", "is my journey safe", "check safety", "am i safe", "safety check"]):
            return "safety_status"
        if any(w in q for w in ["request assistance", "i need help", "need assistance", "help me exit", "transit assistance", "call help", "sos"]):
            return "request_assistance"
        if any(w in q for w in ["journey sharing", "share journey", "share trip", "share my journey", "share my trip", "sharing status"]):
            return "journey_sharing"
        if any(w in q for w in ["emergency guidance", "emergency service", "call ambulance", "call police", "police response"]):
            return "emergency_guidance"
        if any(w in q for w in ["telemetry lost", "signal lost", "gps lost", "lost signal", "no bus signal"]):
            return "telemetry_lost"
        if any(w in q for w in ["missed destination", "missed my stop", "passed my stop", "went past destination"]):
            return "missed_destination_help"
        if any(w in q for w in ["missed transfer help", "missed connection help", "lost connection"]):
            return "missed_transfer_help"
        if any(w in q for w in ["nearby safety transit", "safe stops nearby", "nearest well-lit stop", "nearest safe stop", "transit hubs nearby"]):
            return "nearby_transit_help"

        # Phase 40 Operations Intents
        if any(w in q for w in ["system status", "system health", "is the system running", "server status", "platform status"]):
            return "system_status"
        if any(w in q for w in ["feed status", "gtfs feed status", "realtime feed status", "is feed connected", "feed health"]):
            return "feed_status"
        if any(w in q for w in ["why is feed stale", "why feed stale", "feed stale"]):
            return "why_feed_stale"
        if any(w in q for w in ["why is eta unavailable", "eta unavailable"]):
            return "why_eta_unavailable"
        if any(w in q for w in ["why is crowd unavailable", "crowd unavailable"]):
            return "why_crowd_unavailable"
        if any(w in q for w in ["how many active incidents", "incident status", "disruption count"]):
            return "incident_status"
        if any(w in q for w in ["prediction source", "how are predictions calculated", "what is prediction source"]):
            return "prediction_source"
        if any(w in q for w in ["simulator status", "is simulator active", "simulator mode"]):
            return "simulator_status"
        if any(w in q for w in ["offline status", "am i offline", "is app offline"]):
            return "offline_status"

        # Phase 38 Predictive Commuter Intelligence Intents
        if any(w in q for w in ["predicted arrival", "predict arrival", "estimated arrival time", "predicted eta", "predict eta"]):
            return "predicted_arrival"
        if any(w in q for w in ["predicted duration", "predict duration", "how long will journey take", "estimated journey duration", "predict my journey"]):
            return "predicted_duration"
        if any(w in q for w in ["prediction confidence", "how confident is the prediction", "confidence of prediction", "is prediction reliable"]):
            return "prediction_confidence"
        if any(w in q for w in ["transfer probability", "probability of catching", "chance of catching", "can i make the transfer"]):
            return "transfer_probability"
        if any(w in q for w in ["predicted crowd", "predict crowd", "how crowded will it be later", "crowd forecast"]):
            return "predicted_crowd"
        if any(w in q for w in ["predicted delay", "predict delay", "how much delay is predicted"]):
            return "predicted_delay"

        # Phase 39 Smart Recommendations & Commute Summary Intents
        if any(w in q for w in ["what should i take", "which route should i take", "what bus do you recommend", "recommend a route"]):
            return "what_should_i_take"
        if any(w in q for w in ["favorite route status", "how is my favorite route", "status of my favorite route", "check favorite route"]):
            return "favorite_route_status"
        if any(w in q for w in ["saved journey status", "how is my saved journey", "status of my saved trip", "check saved journey"]):
            return "saved_journey_status"
        if any(w in q for w in ["lower crowd option", "bus with fewer people", "less crowded alternative"]):
            return "lower_crowd_option"
        if any(w in q for w in ["accessible option", "wheelchair friendly option", "accessible recommendation"]):
            return "accessible_option"
        if any(w in q for w in ["disruption alternative", "alternate route due to delay", "avoid disruption"]):
            return "disruption_alternative"
        if any(w in q for w in ["commute summary", "my transit today", "commute overview", "transit today"]):
            return "commute_summary"

        # Phase 35 Accessibility Intents
        if any(w in q for w in ["wheelchair", "accessible", "accessibility", "handicap", "divyang", "pwd"]):
            if any(w in q for w in ["stop", "station", "terminal", "junction"]):
                return "stop_accessibility"
            return "wheelchair_routes"
        if any(w in q for w in ["low floor", "low-floor", "step free", "step-free", "ramp"]):
            if any(w in q for w in ["stop", "station", "terminal", "junction"]):
                return "stop_accessibility"
            return "low_floor_bus"
        if any(w in q for w in ["senior", "elderly", "senior citizen", "older passenger", "grandparent"]):
            return "senior_friendly"

        # Phase 36 Smart Crowd & Occupancy Intents
        if any(w in q for w in ["least crowded", "less crowded", "lower crowd", "lower estimated crowd", "least crowd", "less crowd", "which bus has lower"]):
            return "least_crowded_option"
        if any(w in q for w in ["standing space", "stand", "standing room", "standing likelihood", "will i have to stand"]):
            return "standing_likelihood"
        if any(w in q for w in ["occupancy source", "how is occupancy", "is crowd verified", "crowd source", "crowd data source", "is occupancy verified"]):
            return "occupancy_source"
        if any(w in q for w in ["is 500d crowded", "is 356 crowded", "is 201r crowded", "is kia-8 crowded", "is g-2 crowded", "is my bus crowded", "is the bus crowded"]):
            return "crowded_bus"
        if any(w in q for w in ["crowd level", "crowd status", "crowd tier"]):
            return "crowd_level"
        if any(w in q for w in ["seat", "seats", "sit", "empty seat", "will i get a seat"]):
            return "seat_availability"
        if any(w in q for w in ["how crowded", "crowd", "crowded", "occupancy", "packed", "crowding", "how full"]):
            return "bus_occupancy"

        # Phase 37 Disruption & Incident Intents
        if any(w in q for w in ["transfer still possible", "miss my connecting bus", "transfer at risk", "transfer risk", "is my transfer still possible", "is my transfer at risk"]):
            return "transfer_risk"
        if any(w in q for w in ["why is my journey showing a warning", "warning on my journey", "warning on my trip", "journey warning", "trip warning", "showing a warning"]):
            return "active_journey_alert"
        if any(w in q for w in ["take another route", "another route", "alternative route", "can i take another", "alternate route", "alternative", "alternatives"]):
            return "alternative_after_disruption"
        if any(w in q for w in ["is silk board affected", "is stop affected", "stop closed", "stop closure", "is silk board closed"]):
            return "stop_closure"
        if any(w in q for w in ["is 500d delayed", "is 356 delayed", "is my bus delayed", "is the bus delayed", "why is 500d slow"]):
            return "route_delay"
        if any(w in q for w in ["is my bus affected", "is 500d affected", "is 356 affected", "is 500d disrupted", "is 356 disrupted", "route disruption", "corridor disruption", "disruptions on", "disruption on", "any disruption", "any disruptions"]):
            return "route_disruption"
        if any(w in q for w in ["any service alert?", "is there a service alert", "tell me service alert", "check service alert"]):
            return "service_alert"

        if any(w in q for w in ["nearest stop", "nearest", "closest stop", "closest", "close stop", "take me to the nearest stop", "take me to nearest stop"]):
            return "nearest_stop"
        if any(w in q for w in ["alert", "alerts", "delay", "delays", "advisory", "metro work", "disruption", "delayed", "congested", "congestion", "traffic"]):
            return "service_alerts"
        if any(w in q for w in ["official", "calculated", "how is eta", "eta source", "is eta official"]):
            return "eta_source"
        if any(w in q for w in ["fresh", "stale", "feed status", "realtime status", "live feed"]):
            return "feed_freshness"
        if any(w in q for w in ["fastest", "fast option", "quickest"]):
            return "fastest_option"
        if any(w in q for w in ["cheapest", "lowest fare", "least fare", "fare"]):
            return "cheapest_option"
        if any(w in q for w in ["show me the stops", "show stops", "list stops", "what are the stops", "stops of", "its stops"]):
            return "bus_route"
        if any(w in q for w in ["where do i change buses", "change buses", "change bus", "where to change", "transfer stop", "tell me my transfer", "what happens after", "where do i transfer", "transfer details", "my transfer"]):
            return "transfer_guidance"
        if any(w in q for w in ["which bus do i take next", "connecting bus", "where is my connecting bus", "next bus to take", "what bus next"]):
            return "connecting_bus"
        if any(w in q for w in ["how long do i have to change", "will i make my connection", "transfer buffer", "time to change", "make my connection"]):
            return "transfer_timing"
        if any(w in q for w in ["how far do i walk", "walk to connecting stop", "walking distance for transfer", "how far to walk"]):
            return "transfer_walking"
        if any(w in q for w in ["when should i get down", "where should i get off", "when to get off", "when to get down", "tell me when i should get down", "tell me when to get down", "should i get down", "when should i get off", "where to get down"]):
            return "arrival_guidance"
        if any(w in q for w in ["near my destination", "near destination", "am i near", "is my destination near", "close to destination", "close to my destination", "am i close"]):
            return "near_destination"
        if any(w in q for w in ["reached my destination", "reached destination", "has my bus reached", "have we reached", "did i reach", "reached yet", "have i reached", "did the bus reach"]):
            return "reached_destination"
        if any(w in q for w in ["reach destination", "when will i reach", "reach by", "destination eta", "reach at", "reach the destination"]):
            return "destination_eta"
        if any(w in q for w in ["how many stops", "stops left", "stops remaining"]):
            return "stops_remaining"
        if any(w in q for w in ["when will", "how long", "reach my stop", "eta", "arrive"]):
            return "bus_eta"
        if any(w in q for w in ["where does", "route", "stops", "stop at"]):
            return "bus_route"
        if any(w in q for w in ["how do i go", "which bus", "how to go", "buses from"]):
            return "journey_search"
        if any(w in q for w in ["next bus", "next"]):
            return "next_bus"
        if any(w in q for w in ["hello", "hi", "hey", "help", "what can you do", "who are you", "work"]):
            return "general"

        return "bus_location"


class AIService:
    """
    Core AI orchestration service.
    Implements the Grounded Transit AI Pipeline:
    Query -> Intent & Entity Extraction -> Verified Telemetry Lookup -> AI Response Generation -> Structured Output.
    """

    @classmethod
    async def process_chat(cls, request: AIChatRequest) -> AIChatResponse:
        message = (request.message or "").strip()
        session_id = request.session_id or "default_session"
        if not message:
            return AIChatResponse(
                answer="Please ask a question about Bengaluru BMTC buses, routes, seats, or arrival times.",
                intent="general",
                provider="MockAIProvider",
            )

        intent = IntentDetector.detect_intent(message)
        route_extracted = IntentDetector.extract_route_number(message)
        origin_ext, dest_ext = IntentDetector.extract_journey_endpoints(message)

        # Multi-turn contextual bus memory & pronoun resolution (e.g. "Where is 500D?" -> "Show me its stops"):
        session_data = _SESSION_MEMORY.get(session_id, {})
        lowered = f" {message.lower()} "
        has_pronoun = (
            " it " in lowered
            or " its " in lowered
            or "its stops" in lowered
            or "that bus" in lowered
            or "this bus" in lowered
            or "my bus" in lowered
            or "the bus" in lowered
            or "the stops" in lowered
            or intent in ["seat_availability", "bus_occupancy", "bus_eta", "eta_source", "bus_route", "stops_remaining", "destination_eta", "arrival_guidance", "near_destination", "reached_destination", "transfer_guidance", "connecting_bus", "transfer_timing", "transfer_walking", "wheelchair_routes", "low_floor_bus", "senior_friendly", "accessibility_check"]
        )
        if not route_extracted and has_pronoun:
            route_extracted = session_data.get("last_route")
        if not route_extracted and request.transit_context:
            route_extracted = request.transit_context.get("route_number") or request.transit_context.get("route")
        if not route_extracted and active_journey_service._active_journey:
            route_extracted = active_journey_service._active_journey.route_number

        transit_provider = get_transit_provider()
        health = get_provider_health()
        all_buses = await transit_provider.get_buses()
        matched_bus = None

        if route_extracted:
            matched_bus = next((b for b in all_buses if b.route_number.upper() == route_extracted.upper()), None)
            if matched_bus:
                _SESSION_MEMORY[session_id] = {"last_route": matched_bus.route_number, "last_bus_id": matched_bus.bus_id}
            else:
                # User asked about a non-tracked bus number
                provider = get_ai_provider()
                answer = await provider.generate_response(
                    message, "unknown_bus", {"queried_route": route_extracted, "provider": transit_provider.provider_name(), "data_mode": transit_provider.get_data_mode()}
                )
                return AIChatResponse(
                    answer=answer,
                    intent="unknown_bus",
                    route_number=route_extracted,
                    provider=provider.__class__.__name__,
                )
        else:
            # If still no route matched, default to first active corridor bus (e.g. 500D)
            if intent in ["bus_location", "bus_eta", "seat_availability", "bus_occupancy", "eta_source", "stops_remaining", "destination_eta", "arrival_guidance", "near_destination", "reached_destination", "transfer_guidance", "connecting_bus", "transfer_timing", "transfer_walking", "wheelchair_routes", "low_floor_bus", "senior_friendly", "accessibility_check", "crowd_level", "crowded_bus", "least_crowded_option", "standing_likelihood", "occupancy_source"]:
                matched_bus = all_buses[0] if all_buses else None
                if matched_bus:
                    _SESSION_MEMORY[session_id] = {"last_route": matched_bus.route_number, "last_bus_id": matched_bus.bus_id}

        if intent in ["stops_remaining", "destination_eta", "arrival_guidance", "near_destination", "reached_destination"]:
            metrics_service.ai_trip_context_queries_count += 1
        elif intent in ["transfer_guidance", "connecting_bus", "transfer_timing", "transfer_walking"]:
            metrics_service.transfer_ai_queries += 1
        elif intent in ["wheelchair_routes", "low_floor_bus", "senior_friendly", "stop_accessibility", "accessibility_check"]:
            metrics_service.accessibility_ai_queries += 1
        elif intent in ["crowd_level", "seat_availability", "crowded_bus", "least_crowded_option", "standing_likelihood", "occupancy_source", "bus_occupancy"]:
            metrics_service.crowd_ai_queries += 1
            if intent == "seat_availability":
                metrics_service.seat_availability_queries += 1

        relevant_alerts = alert_service.get_alerts(route_number=matched_bus.route_number if matched_bus else route_extracted)
        transit_context: Dict[str, Any] = {
            "provider": transit_provider.provider_name(),
            "data_mode": transit_provider.get_data_mode(),
            "is_realtime": transit_provider.is_realtime(),
            "feed_status": health.feed_status,
            "is_stale": health.stale,
            "provider_name": transit_provider.provider_name(),
            "last_update": health.last_update,
            "service_alerts": [a.model_dump() for a in relevant_alerts],
        }

        if active_journey_service._active_journey:
            aj = active_journey_service._active_journey
            transit_context.update({
                "is_active_journey": True,
                "active_journey": aj.model_dump(),
                "remaining_stops": aj.remaining_stops,
                "destination_eta_str": aj.destination_eta_str,
                "current_stop": aj.current_stop,
                "destination": aj.destination,
                "is_destination_reached": aj.is_destination_reached,
                "is_destination_passed": aj.is_destination_passed,
                "is_get_ready_to_exit": aj.is_get_ready_to_exit,
                "telemetry_reliable": aj.telemetry_reliable,
                "telemetry_disclosure": aj.telemetry_disclosure,
                "data_transparency_label": aj.data_transparency_label,
                "is_transfer_journey": aj.is_transfer_journey,
            })
            if aj.is_transfer_journey and aj.transfer_details:
                transit_context.update({
                    "transfer_stop": aj.transfer_details.transfer_stop,
                    "connecting_route": aj.connecting_route or aj.transfer_details.connecting_route,
                    "connecting_bus_id": aj.connecting_bus_id or aj.transfer_details.connecting_bus_id,
                    "connecting_bus_eta_minutes": aj.connecting_bus_eta_minutes or aj.transfer_details.connecting_bus_eta_minutes,
                    "transfer_buffer_minutes": aj.transfer_buffer_minutes or aj.transfer_details.transfer_buffer_minutes,
                    "walking_distance_meters": aj.transfer_details.walking_distance_meters,
                    "walking_duration_minutes": aj.transfer_details.walking_duration_minutes,
                    "is_transfer_missed": aj.is_transfer_missed,
                })
            if not aj.telemetry_reliable:
                transit_context["is_offline"] = True


        # Assemble verified transit context based on intent
        if matched_bus:
            route_obj = await transit_provider.get_bus_route(matched_bus.bus_id)
            stops_obj = await transit_provider.get_bus_stops(matched_bus.bus_id)
            pred_resp = await CrowdPredictionService.predict_for_bus(matched_bus.bus_id)
            eta_obj = await transit_provider.get_eta(matched_bus.bus_id)

            has_apc = not transit_provider.is_realtime() or (matched_bus.occupancy_percentage > 0 or (matched_bus.available_seats is not None and matched_bus.available_seats > 0))

            transit_context.update({
                "bus_id": matched_bus.bus_id,
                "route_number": matched_bus.route_number,
                "bus_type": matched_bus.bus_type,
                "destination": matched_bus.destination,
                "latitude": matched_bus.latitude,
                "longitude": matched_bus.longitude,
                "speed": matched_bus.speed,
                "direction": matched_bus.direction,
                "next_stop": matched_bus.next_stop,
                "eta_minutes": matched_bus.eta_minutes or (eta_obj.eta_minutes if eta_obj else 6),
                "eta_source": eta_obj.source if eta_obj else "geometric_estimate",
                "occupancy_available": has_apc,
                "occupancy_percentage": matched_bus.occupancy_percentage,
                "available_seats": matched_bus.available_seats or 12,
                "capacity": matched_bus.capacity,
                "plate_number": matched_bus.plate_number,
                "source": route_obj.source if route_obj else "Origin",
                "stops": [s.name for s in stops_obj],
                "accessibility": matched_bus.accessibility.model_dump() if matched_bus.accessibility else None,
            })
            crowd_meta = matched_bus.crowd or crowd_service.get_crowd_metadata(matched_bus.bus_id, matched_bus.route_number)
            transit_context.update({
                "crowd_metadata": crowd_meta.model_dump(),
                "crowd_status": crowd_meta.crowd_status,
                "seat_status": crowd_meta.estimated_seat_availability,
                "standing_likelihood": crowd_meta.standing_likelihood,
                "crowd_source": crowd_meta.source,
                "crowd_disclosure": crowd_meta.disclosure,
            })
            if pred_resp:
                transit_context["prediction"] = {
                    "current_crowd_tier": pred_resp.current_crowd_tier,
                    "current_occupancy_percent": pred_resp.current_occupancy_percent,
                    "available_seats": pred_resp.available_seats,
                    "disclaimer": pred_resp.disclaimer,
                    "predictions": [p.model_dump() for p in pred_resp.predictions],
                }

        # Check if user query mentions a stop for stop-level intelligence
        matched_stop = None
        for stop in getattr(transit_provider, "_stops", {}).values():
            if stop.name.lower() in message.lower() or (stop.kannada_name and stop.kannada_name in message):
                matched_stop = stop
                break
        if matched_stop:
            transit_context["stop_name"] = matched_stop.name
            transit_context["stop_accessibility"] = matched_stop.accessibility.model_dump() if matched_stop.accessibility else None
            stop_crowd = crowd_service.get_crowd_metadata(matched_stop.stop_id)
            transit_context["stop_crowd"] = stop_crowd.model_dump()

        if all_buses:
            rank_map = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "VERY_HIGH": 4, "UNKNOWN": 5}
            sorted_buses = sorted(
                all_buses,
                key=lambda b: rank_map.get((b.crowd.crowd_status if b.crowd else "UNKNOWN").upper(), 5)
            )
            if sorted_buses:
                best_bus = sorted_buses[0]
                b_meta = best_bus.crowd or crowd_service.get_crowd_metadata(best_bus.bus_id, best_bus.route_number)
                transit_context["least_crowded_bus"] = {
                    "route_number": best_bus.route_number,
                    "bus_id": best_bus.bus_id,
                    "crowd_status": b_meta.crowd_status,
                    "seat_status": b_meta.estimated_seat_availability,
                    "source": b_meta.source,
                }

        # Phase 37 Disruption / Incident context
        incidents = incident_service.get_active_incidents()
        transit_context["incidents"] = [i.model_dump() for i in incidents]
        if matched_bus:
            b_inc = incident_service.get_incidents(route_number=matched_bus.route_number, active_only=True)
            transit_context["bus_incidents"] = [i.model_dump() for i in b_inc]
        if intent in [
            "service_alert", "service_alerts", "route_disruption", "stop_closure",
            "route_delay", "alternative_after_disruption", "active_journey_alert", "transfer_risk"
        ]:
            metrics_service.incident_ai_queries += 1
        elif intent in ["predicted_arrival", "predicted_duration", "prediction_confidence", "transfer_probability", "predicted_crowd", "predicted_delay"]:
            metrics_service.prediction_ai_queries += 1
        elif intent in ["what_should_i_take", "route_alternative", "favorite_route_status", "saved_journey_status", "lower_crowd_option", "accessible_option", "disruption_alternative", "commute_summary"]:
            metrics_service.recommendation_ai_queries += 1
        elif intent in ["system_status", "feed_status", "why_feed_stale", "why_eta_unavailable", "why_crowd_unavailable", "incident_status", "prediction_source", "simulator_status", "offline_status"]:
            metrics_service.operations_ai_queries += 1

        # Handle journey queries
        if (intent in ["journey_search", "next_bus"] or dest_ext) and intent not in [
            "nearest_stop", "service_alerts", "service_alert", "route_disruption", "stop_closure",
            "route_delay", "alternative_after_disruption", "active_journey_alert", "transfer_risk",
            "predicted_arrival", "predicted_duration", "prediction_confidence", "transfer_probability", "predicted_crowd", "predicted_delay",
            "what_should_i_take", "route_alternative", "favorite_route_status", "saved_journey_status", "lower_crowd_option", "accessible_option", "disruption_alternative", "commute_summary",
            "system_status", "feed_status", "why_feed_stale", "why_eta_unavailable", "why_crowd_unavailable", "incident_status", "prediction_source", "simulator_status", "offline_status",
            "bus_location", "bus_eta", "seat_availability",
            "bus_occupancy", "bus_route", "standing_likelihood", "least_crowded_option",
            "occupancy_source", "crowded_bus", "crowd_level"
        ]:
            origin_name = origin_ext or request.user_stop or "Central Silk Board Junction"
            dest_name = dest_ext or "Majestic (Kempegowda Bus Station)"
            journey_res = await JourneyService.search_journey(
                JourneySearchRequest(origin=origin_name, destination=dest_name)
            )
            transit_context.update({
                "origin": origin_name,
                "destination": dest_name,
                "options": [o.model_dump() for o in journey_res.options],
            })
            intent = "journey_search" if intent != "next_bus" else "next_bus"

        if request.transit_context:
            transit_context.update(request.transit_context)

        # Generate grounded natural-language answer
        ai_provider = get_ai_provider()
        answer_text = await ai_provider.generate_response(message, intent, transit_context)

        # Build structured data payload for mobile UI card integration
        structured_data: Optional[Dict[str, Any]] = None
        if matched_bus:
            c_meta = matched_bus.crowd or crowd_service.get_crowd_metadata(matched_bus.bus_id, matched_bus.route_number)
            structured_data = {
                "routeNumber": matched_bus.route_number,
                "destination": matched_bus.destination,
                "etaMinutes": matched_bus.eta_minutes or 6,
                "occupancyPercent": matched_bus.occupancy_percentage,
                "seatsEstimated": matched_bus.available_seats or 12,
                "nextStop": matched_bus.next_stop,
                "speed": matched_bus.speed,
                "busType": matched_bus.bus_type,
                "crowdStatus": c_meta.crowd_status,
                "seatStatus": c_meta.estimated_seat_availability,
                "standingLikelihood": c_meta.standing_likelihood,
                "crowdSource": c_meta.source,
                "crowdDisclosure": c_meta.disclosure,
            }
        elif transit_context.get("options"):
            first_opt = transit_context["options"][0]
            structured_data = {
                "routeNumber": first_opt["route_number"],
                "destination": first_opt["destination"],
                "etaMinutes": first_opt["eta_minutes"],
                "occupancyPercent": first_opt["occupancy_percentage"],
                "seatsEstimated": first_opt["available_seats"],
                "journeyDuration": first_opt["journey_duration_minutes"],
                "fareRupees": first_opt["fare_rupees"],
                "busType": first_opt["bus_type"],
                "crowdStatus": first_opt.get("crowd_status", "UNKNOWN"),
                "seatStatus": first_opt.get("estimated_seat_availability", "UNKNOWN"),
                "standingLikelihood": first_opt.get("standing_likelihood", "UNKNOWN"),
            }

        return AIChatResponse(
            answer=answer_text,
            intent=intent,
            bus_id=matched_bus.bus_id if matched_bus else None,
            route_number=matched_bus.route_number if matched_bus else (route_extracted or None),
            data=structured_data,
            prediction=transit_context.get("prediction"),
            provider=ai_provider.__class__.__name__,
        )
