from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import uuid
import logging

from ..models.transit import (
    RecommendationType,
    CommuterRecommendation,
)
from .personalization_service import personalization_service
from .incident_impact_service import incident_impact_service
from .crowd_service import crowd_service
from .provider_factory import get_transit_provider

logger = logging.getLogger("nammablr.commuter_recommendation_service")


class CommuterRecommendationService:
    """
    Transparent Commuter Recommendation Engine for Bengaluru transit.
    Provides factual multi-factor comparisons across travel time, fare, walking distance,
    transfer count, crowd status, accessibility, and disruption impact.
    Strictly avoids declaring any route as objectively 'best'.
    """

    FACTUAL_DISCLOSURE = "Factual comparative transit assessment avoiding subjective ranking."

    def __init__(self):
        self._recent_notifications: Dict[str, datetime] = {}
        self._scenario_override: Optional[str] = None

    def reset(self):
        self._recent_notifications.clear()
        self._scenario_override = None

    def set_scenario_override(self, scenario: Optional[str]):
        self._scenario_override = scenario

    def should_deduplicate_notification(self, key: str, window_seconds: int = 300) -> bool:
        """
        Deduplicates commuter notifications within a sliding window (default 5 minutes).
        Returns True if notification was sent recently and should be suppressed.
        """
        now = datetime.now(timezone.utc)
        if key in self._recent_notifications:
            last_sent = self._recent_notifications[key]
            if (now - last_sent).total_seconds() < window_seconds:
                return True
        self._recent_notifications[key] = now
        return False

    def get_recommendations(self, user_stop: Optional[str] = None) -> List[CommuterRecommendation]:
        """
        Generates contextual commuter recommendations for 'Your Transit Today'.
        """
        recommendations: List[CommuterRecommendation] = []

        # 1. Check Saved Journeys
        saved_recs = self.get_saved_journey_recommendations()
        recommendations.extend(saved_recs)

        # 2. Check Favorite Routes & Disruptions
        fav_recs = self.get_favorite_route_recommendations()
        recommendations.extend(fav_recs)

        # 3. Crowd-aware options
        low_crowd = self._generate_low_crowd_recommendation()
        if low_crowd:
            recommendations.append(low_crowd)

        # 4. Accessibility-aware options
        access_rec = self._generate_accessible_recommendation()
        if access_rec:
            recommendations.append(access_rec)

        # Fallback general recommendation if list is minimal
        if len(recommendations) < 2:
            recommendations.append(
                CommuterRecommendation(
                    id=f"rec-gen-{uuid.uuid4().hex[:8]}",
                    type=RecommendationType.FASTEST_ESTIMATE.value,
                    title="Estimated 8 min faster via Outer Ring Road",
                    description="Route 500D offers frequent peak-hour headway.",
                    route_number="500D",
                    destination="Hebbal",
                    reason="Estimated 8 min faster compared to interior arterial roads",
                    comparison_factors={
                        "time_delta_minutes": -8,
                        "fare_rupees": 25,
                        "transfers": 0,
                        "crowd_status": "MODERATE",
                    },
                    data_source="HISTORICAL_ESTIMATE",
                    confidence="MEDIUM",
                    disclosure=self.FACTUAL_DISCLOSURE,
                    action_route="500D",
                )
            )

        return recommendations

    def get_saved_journey_recommendations(self) -> List[CommuterRecommendation]:
        """Evaluates saved journeys for timely commuter actions and disruption alerts."""
        recs: List[CommuterRecommendation] = []
        saved = personalization_service.get_saved_journeys()

        for sj in saved:
            # Check if corridor disrupted
            impact = incident_impact_service.assess_route("500D")
            if impact.is_affected and ("silk board" in sj.origin.lower() or "silk board" in sj.destination.lower()):
                recs.append(
                    CommuterRecommendation(
                        id=f"rec-saved-disrupt-{sj.id}",
                        type=RecommendationType.DISRUPTION_RECOVERY.value,
                        title=f"Advisory on your saved journey: {sj.origin} → {sj.destination}",
                        description="Corridor advisory active. Alternative parallel route available.",
                        route_number="500D",
                        destination=sj.destination,
                        reason="Alternative available with +400m walk and 1 transfer avoiding disruption",
                        comparison_factors={
                            "additional_walk_meters": 400,
                            "additional_time_minutes": 8,
                            "transfers": 1,
                            "fare_rupees": 20,
                            "recommendation_label": "Alternative available",
                        },
                        data_source="SIMULATED",
                        confidence="HIGH",
                        disclosure="Factual transit comparison avoiding affected corridor.",
                        action_route="356",
                    )
                )
            else:
                recs.append(
                    CommuterRecommendation(
                        id=f"rec-saved-ready-{sj.id}",
                        type=RecommendationType.SAVED_JOURNEY.value,
                        title=f"Saved Commute: {sj.origin} → {sj.destination}",
                        description=f"Standard scheduled corridor operations. Estimated 35–40 min.",
                        route_number="500D",
                        destination=sj.destination,
                        reason="Regular saved journey route with normal scheduled headway",
                        comparison_factors={
                            "estimated_duration_minutes": 38,
                            "transfers": 0,
                            "fare_rupees": 25,
                        },
                        data_source="HISTORICAL_ESTIMATE",
                        confidence="MEDIUM",
                        disclosure=self.FACTUAL_DISCLOSURE,
                        action_route="500D",
                    )
                )

        return recs

    def get_favorite_route_recommendations(self) -> List[CommuterRecommendation]:
        """Evaluates favorite routes for status advisories and alternatives."""
        recs: List[CommuterRecommendation] = []
        favs = personalization_service.get_favorite_routes()

        for f in favs:
            impact = incident_impact_service.assess_route(f.route_number)
            if impact.is_affected:
                recs.append(
                    CommuterRecommendation(
                        id=f"rec-fav-disrupt-{f.route_number}",
                        type=RecommendationType.SERVICE_ALTERNATIVE.value,
                        title=f"Favorite Route {f.route_number}: Advisory Active",
                        description=f"{impact.title or 'Service delay'}. Alternative corridor option available.",
                        route_number=f.route_number,
                        destination=f.destination,
                        reason="Alternative route available avoiding primary corridor crawl",
                        comparison_factors={
                            "delay_estimate_minutes": impact.delay_estimate_minutes,
                            "recommendation_label": "Alternative available",
                        },
                        data_source="SIMULATED",
                        confidence="HIGH",
                        disclosure=impact.advisory_label or "SIMULATED CORRIDOR ADVISORY",
                        action_route=f.route_number,
                    )
                )
            else:
                recs.append(
                    CommuterRecommendation(
                        id=f"rec-fav-normal-{f.route_number}",
                        type=RecommendationType.FAVORITE_ROUTE.value,
                        title=f"Favorite Route {f.route_number}: Normal Schedule",
                        description="Operating normally without reported service disruptions.",
                        route_number=f.route_number,
                        destination=f.destination,
                        reason="Favorite route confirmed clear of active advisories",
                        comparison_factors={
                            "has_disruption": False,
                        },
                        data_source="HISTORICAL_ESTIMATE",
                        confidence="MEDIUM",
                        disclosure=self.FACTUAL_DISCLOSURE,
                        action_route=f.route_number,
                    )
                )

        return recs

    def get_disruption_recommendations(self, route_number: str) -> List[CommuterRecommendation]:
        """
        Returns structured alternative recommendations when a specific route is disrupted.
        Never calls an alternative 'best'; labels 'Alternative available'.
        """
        impact = incident_impact_service.assess_route(route_number)
        if not impact.is_affected:
            return []

        recs: List[CommuterRecommendation] = []
        for alt in impact.alternatives:
            r_num = alt.alternative_route or alt.route_number
            recs.append(
                CommuterRecommendation(
                    id=f"rec-alt-{uuid.uuid4().hex[:8]}",
                    type=RecommendationType.DISRUPTION_RECOVERY.value,
                    title=f"Alternative: Route {r_num}",
                    description=f"Avoiding {route_number} congestion. +{alt.additional_walk_meters}m walk, +{alt.additional_travel_time_minutes}m duration.",
                    route_number=r_num,
                    destination=alt.destination,
                    reason=f"Alternative available ({alt.transfers_required} transfer, ₹{alt.estimated_fare} fare)",
                    comparison_factors={
                        "additional_walk_meters": alt.additional_walk_meters,
                        "additional_time_minutes": alt.additional_travel_time_minutes,
                        "transfers": alt.transfers_required,
                        "fare_rupees": alt.estimated_fare,
                        "crowd_status": alt.crowd_status,
                        "accessibility_status": alt.accessibility_status,
                        "recommendation_label": "Alternative available",
                    },
                    data_source="SIMULATED",
                    confidence="HIGH",
                    disclosure=alt.disclosure,
                    action_route=r_num,
                )
            )

        return recs

    def get_route_recommendations(self, route_number: str) -> List[CommuterRecommendation]:
        """Generates recommendations relevant to a specific route."""
        disrupt_recs = self.get_disruption_recommendations(route_number)
        if disrupt_recs:
            return disrupt_recs

        return [
            CommuterRecommendation(
                id=f"rec-route-{route_number}",
                type=RecommendationType.FASTEST_ESTIMATE.value,
                title=f"Route {route_number} Operating Normally",
                description="Regular corridor headway based on scheduled timetable.",
                route_number=route_number,
                reason="Direct connection with 0 transfers",
                comparison_factors={
                    "transfers": 0,
                    "fare_rupees": 25,
                },
                data_source="HISTORICAL_ESTIMATE",
                confidence="MEDIUM",
                disclosure=self.FACTUAL_DISCLOSURE,
                action_route=route_number,
            )
        ]

    def _generate_low_crowd_recommendation(self) -> Optional[CommuterRecommendation]:
        """Factual low-crowd alternative comparison."""
        meta = crowd_service.get_crowd_metadata("bus-201r", "201R")
        if meta.crowd_status in ["LOW", "MODERATE"]:
            return CommuterRecommendation(
                id=f"rec-crowd-{uuid.uuid4().hex[:8]}",
                type=RecommendationType.LOW_CROWD.value,
                title="Lower estimated crowd on Route 201R",
                description="Estimated seats likely available based on historical corridor volume.",
                route_number="201R",
                destination="Indiranagar",
                reason="Lower estimated crowd based on historical off-peak patterns",
                comparison_factors={
                    "crowd_status": meta.crowd_status,
                    "seat_status": meta.estimated_seat_availability,
                    "fare_rupees": 20,
                },
                data_source=meta.source,
                confidence=meta.confidence,
                disclosure=meta.disclosure,
                action_route="201R",
            )
        return None

    def _generate_accessible_recommendation(self) -> Optional[CommuterRecommendation]:
        """Factual wheelchair-accessible transit option."""
        return CommuterRecommendation(
            id=f"rec-access-{uuid.uuid4().hex[:8]}",
            type=RecommendationType.ACCESSIBLE.value,
            title="Wheelchair-accessible Vajra Electric on 500D",
            description="Verified low-floor bus equipped with boarding ramp.",
            route_number="500D",
            destination="Hebbal",
            reason="Verified wheelchair accessibility and priority seating",
            comparison_factors={
                "wheelchair_accessible": True,
                "low_floor": True,
                "fare_rupees": 35,
            },
            data_source="SIMULATED",
            confidence="HIGH",
            disclosure="Accessible transit feature based on low-floor electric bus specification.",
            action_route="500D",
        )


commuter_recommendation_service = CommuterRecommendationService()
