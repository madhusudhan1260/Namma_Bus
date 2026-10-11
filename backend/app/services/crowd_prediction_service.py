from typing import Dict, List, Optional
from ..models.transit import Bus, BusCrowdPredictionResponse, StopCrowdPrediction
from .provider_factory import get_transit_provider

MAJOR_INTERCHANGES = {
    "central silk board junction",
    "majestic (kempegowda bus station)",
    "shivajinagar bus station",
    "electronic city phase 1",
    "marathahalli bridge",
    "hebbal flyover",
    "banashankari ttmc",
    "agara junction",
    "koramangala bda complex",
    "jayadeva hospital",
}


class CrowdPredictionService:
    """
    Deterministic passenger-flow prediction service for BMTC buses.
    Calculates anticipated passenger boardings, alightings, crowd tiers,
    and seat vacancy across consecutive upcoming stops.
    """

    @classmethod
    def get_crowd_tier(cls, occupancy_percent: int) -> str:
        if occupancy_percent >= 90:
            return "Very Crowded"
        elif occupancy_percent >= 75:
            return "Crowded"
        elif occupancy_percent >= 50:
            return "Moderate"
        else:
            return "Comfortable"

    @classmethod
    async def predict_for_bus(cls, bus_id: str) -> Optional[BusCrowdPredictionResponse]:
        provider = get_transit_provider()
        bus = await provider.get_bus(bus_id)
        if not bus:
            return None

        route = await provider.get_bus_route(bus_id)
        all_stops: List[str] = route.stops if route and route.stops else [bus.next_stop, bus.destination]

        # Determine index of the current or next stop along the route
        current_idx = 0
        for i, s in enumerate(all_stops):
            if s.lower() == bus.next_stop.lower():
                current_idx = i
                break

        # Upcoming stops from current onwards
        upcoming_stops = all_stops[current_idx:]
        if not upcoming_stops:
            upcoming_stops = [bus.next_stop]

        capacity = max(1, bus.capacity)
        running_passengers = max(0, min(capacity, bus.current_passengers))
        total_upcoming = len(upcoming_stops)

        predictions: List[StopCrowdPrediction] = []

        # Simulate flow step-by-step
        for step, stop_name in enumerate(upcoming_stops[:8], start=1):
            is_major = any(major in stop_name.lower() for major in MAJOR_INTERCHANGES)
            is_destination = (step == total_upcoming) or (stop_name.lower() == bus.destination.lower())

            if is_destination:
                alight_ratio = 0.85
                board_ratio = 0.0
            elif is_major:
                alight_ratio = 0.28
                board_ratio = 0.35
            else:
                alight_ratio = 0.12
                board_ratio = 0.15

            estimated_alighting = int(round(running_passengers * alight_ratio))
            free_space = max(0, capacity - (running_passengers - estimated_alighting))
            potential_boarding = int(round(capacity * board_ratio))
            estimated_boarding = min(free_space, potential_boarding)

            new_passengers = max(0, min(capacity, running_passengers - estimated_alighting + estimated_boarding))
            running_passengers = new_passengers

            occ_pct = min(100, round((running_passengers / capacity) * 100))
            seats = max(0, capacity - running_passengers)
            tier = cls.get_crowd_tier(occ_pct)

            confidence = max(0.60, round(0.92 - (step - 1) * 0.06, 2))

            predictions.append(
                StopCrowdPrediction(
                    stop_name=stop_name,
                    stops_ahead=step,
                    occupancy_percent=occ_pct,
                    estimated_passengers=running_passengers,
                    estimated_seats=seats,
                    estimated_boarding=estimated_boarding,
                    estimated_alighting=estimated_alighting,
                    crowd_tier=tier,
                    confidence=confidence,
                )
            )

        selected_predictions = predictions[:5]

        curr_occ = bus.occupancy_percentage
        curr_seats = max(0, capacity - bus.current_passengers)
        curr_tier = cls.get_crowd_tier(curr_occ)

        # Determine trend comparing current vs 3 stops ahead (or last available)
        target_forecast = selected_predictions[min(2, len(selected_predictions) - 1)] if selected_predictions else None
        if target_forecast and target_forecast.occupancy_percent >= curr_occ + 5:
            trend = "increasing"
        elif target_forecast and target_forecast.occupancy_percent <= curr_occ - 5:
            trend = "decreasing"
        else:
            trend = "stable"

        # Deterministic explanation
        explanation_parts = []
        approaching_major = [p.stop_name for p in selected_predictions if any(m in p.stop_name.lower() for m in MAJOR_INTERCHANGES)]
        if trend == "increasing":
            if approaching_major:
                explanation_parts.append(
                    f"Occupancy is predicted to increase approaching {approaching_major[0]} because this corridor is a major interchange."
                )
            else:
                explanation_parts.append(
                    "Occupancy is projected to trend upward across intermediate corridor boarding stops."
                )
        elif trend == "decreasing":
            explanation_parts.append(
                f"Occupancy is predicted to decrease as passengers alight approaching terminal destinations near {bus.destination}."
            )
        else:
            explanation_parts.append(
                f"Corridor passenger flow along {bus.route_number} is balanced with steady boarding and alighting."
            )

        explanation = " ".join(explanation_parts)

        return BusCrowdPredictionResponse(
            bus_id=bus.bus_id,
            route_number=bus.route_number,
            bus_type=bus.bus_type,
            capacity=capacity,
            current_passengers=bus.current_passengers,
            current_occupancy_percent=curr_occ,
            current_crowd_tier=curr_tier,
            available_seats=curr_seats,
            trend=trend,
            explanation=explanation,
            predictions=selected_predictions,
            disclaimer="Estimated crowd based on simulated historical boarding patterns. Actual occupancy may vary. Prediction only — actual passenger levels may vary.",
        )

