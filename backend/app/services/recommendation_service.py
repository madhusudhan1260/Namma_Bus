from typing import List, Dict, Any, Optional
from ..models.transit import (
    JourneyOption,
    JourneyRecommendationRequest,
    JourneyRecommendationResponse,
    RecommendationWinner,
    JourneySearchRequest,
)
from .journey_service import JourneyService
from .provider_factory import get_transit_provider, get_provider_health


class RecommendationService:
    """
    Deterministic journey recommendation engine for Bengaluru transit corridors.
    Computes factual category comparisons (Fastest, Lowest Fare, More Seats,
    Fewest Stops, Least Transfers) with zero subjective score bias.
    """

    @classmethod
    async def recommend_journey(
        cls, request: JourneyRecommendationRequest
    ) -> JourneyRecommendationResponse:
        search_res = await JourneyService.search_journey(
            JourneySearchRequest(origin=request.origin, destination=request.destination)
        )
        options = search_res.options

        if not options:
            return JourneyRecommendationResponse(
                origin=request.origin,
                destination=request.destination,
                options=[],
                winners=[],
                factual_comparison={},
            )

        # Factual measurement winners
        # 1. Fastest: minimum (eta_minutes + journey_duration_minutes)
        fastest_opt = min(
            options,
            key=lambda o: (o.eta_minutes + o.journey_duration_minutes, o.journey_duration_minutes),
        )
        total_time = fastest_opt.eta_minutes + fastest_opt.journey_duration_minutes

        # 2. Lowest Fare: minimum fare_rupees
        cheapest_opt = min(
            options,
            key=lambda o: (o.fare_rupees, o.eta_minutes),
        )

        # 3. More Seats: maximum available_seats
        most_seats_opt = max(
            options,
            key=lambda o: (o.available_seats, -o.occupancy_percentage),
        )

        # 4. Fewest Stops: minimum number_of_stops
        fewest_stops_opt = min(
            options,
            key=lambda o: (o.number_of_stops, o.journey_duration_minutes),
        )

        # 5. Least Transfers: minimum transfers
        least_transfers_opt = min(
            options,
            key=lambda o: (o.transfers, o.eta_minutes),
        )

        winners: List[RecommendationWinner] = [
            RecommendationWinner(
                category="Fastest",
                icon="⚡",
                metric_label="Total Travel Time",
                metric_value=f"{total_time} min ({fastest_opt.journey_duration_minutes}m ride + {fastest_opt.eta_minutes}m wait)",
                route_number=fastest_opt.route_number,
                bus_id=fastest_opt.bus_id,
            ),
            RecommendationWinner(
                category="Lowest Fare",
                icon="💰",
                metric_label="Ticket Cost",
                metric_value=f"₹{cheapest_opt.fare_rupees}",
                route_number=cheapest_opt.route_number,
                bus_id=cheapest_opt.bus_id,
            ),
            RecommendationWinner(
                category="More Seats",
                icon="💺",
                metric_label="Available Seats",
                metric_value=f"{most_seats_opt.available_seats} seats ({most_seats_opt.occupancy_percentage}% full)",
                route_number=most_seats_opt.route_number,
                bus_id=most_seats_opt.bus_id,
            ),
            RecommendationWinner(
                category="Fewest Stops",
                icon="🚌",
                metric_label="Intermediates",
                metric_value=f"{fewest_stops_opt.number_of_stops} stops",
                route_number=fewest_stops_opt.route_number,
                bus_id=fewest_stops_opt.bus_id,
            ),
            RecommendationWinner(
                category="Least Transfers",
                icon="🔄",
                metric_label="Transfers",
                metric_value=f"{least_transfers_opt.transfers} transfers (Direct)" if least_transfers_opt.transfers == 0 else f"{least_transfers_opt.transfers} transfers",
                route_number=least_transfers_opt.route_number,
                bus_id=least_transfers_opt.bus_id,
            ),
        ]

        # 6. Lower Estimated Crowd (Only when comparison is supported by data)
        crowd_rank = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "VERY_HIGH": 4}
        options_with_crowd = [o for o in options if o.crowd_status and o.crowd_status.upper() in crowd_rank]
        if options_with_crowd:
            lowest_crowd_opt = min(
                options_with_crowd,
                key=lambda o: (crowd_rank.get(o.crowd_status.upper(), 99), o.eta_minutes),
            )
            c_label = lowest_crowd_opt.crowd_status.capitalize()
            winners.append(
                RecommendationWinner(
                    category="Lower Estimated Crowd",
                    icon="👥",
                    metric_label="Estimated Crowd",
                    metric_value=f"{c_label} ({lowest_crowd_opt.estimated_seat_availability or 'Estimate'})",
                    route_number=lowest_crowd_opt.route_number,
                    bus_id=lowest_crowd_opt.bus_id,
                )
            )

        factual_comparison: Dict[str, Any] = {
            "fastest_route": fastest_opt.route_number,
            "fastest_total_minutes": total_time,
            "lowest_fare_route": cheapest_opt.route_number,
            "lowest_fare_rupees": cheapest_opt.fare_rupees,
            "most_seats_route": most_seats_opt.route_number,
            "most_seats_count": most_seats_opt.available_seats,
            "fewest_stops_route": fewest_stops_opt.route_number,
            "fewest_stops_count": fewest_stops_opt.number_of_stops,
            "total_options_evaluated": len(options),
            "crowd_comparison": lowest_crowd_opt.crowd_status if options_with_crowd else "Crowd comparison unavailable.",
        }

        return JourneyRecommendationResponse(
            origin=request.origin,
            destination=request.destination,
            options=options,
            winners=winners,
            factual_comparison=factual_comparison,
        )
