import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Deque


class MetricsService:
    """
    In-memory metrics and telemetry tracking service for NammaBlr backend observability.
    Tracks API latency, request counts, provider poller stats, and operational counters.
    """

    def __init__(self):
        self.start_time = time.time()
        self.total_requests = 0
        self.ai_requests_count = 0
        self.ticket_verifications_count = 0
        self.crowd_prediction_requests_count = 0
        self.journey_search_requests_count = 0
        self.journey_recommendations_count = 0
        self.bus_tracking_actions_count = 0
        self.crowd_forecast_views_count = 0
        self.alert_views_count = 0
        self.stale_transitions_count = 0
        self.active_trip_views_count = 0
        self.nearby_stop_queries_count = 0
        self.ai_trip_context_queries_count = 0

        # Phase 32 Smart Commuter Trip Assistant Counters
        self.active_journey_started = 0
        self.active_journey_completed = 0
        self.journey_cancelled = 0
        self.journey_state_transitions = 0
        self.journey_history_views = 0

        # Phase 33 Smart Trip Safety & Arrival Intelligence Counters
        self.destination_approach_alerts = 0
        self.get_ready_to_exit_alerts = 0
        self.destination_reached_events = 0
        self.missed_destination_warnings = 0
        self.journey_notification_events = 0

        # Phase 34 Smart Transfers & Multimodal Counters
        self.transfer_journeys_started = 0
        self.transfer_views = 0
        self.transfer_alerts = 0
        self.transfer_completed = 0
        self.missed_transfer_warnings = 0
        self.connecting_bus_tracking_actions = 0
        self.transfer_ai_queries = 0

        # Phase 35 Smart Accessibility & Inclusive Transit Counters
        self.accessible_journey_searches = 0
        self.accessible_options_viewed = 0
        self.wheelchair_priority_queries = 0
        self.low_floor_filter_applied = 0
        self.accessibility_ai_queries = 0

        # Phase 36 Smart Crowd & Occupancy Intelligence Counters
        self.crowd_queries = 0
        self.crowd_predictions = 0
        self.crowd_unknown_responses = 0
        self.crowd_verified_responses = 0
        self.crowd_estimated_responses = 0
        self.seat_availability_queries = 0
        self.crowd_ai_queries = 0
        self.crowd_alerts = 0
        self.crowd_comparison_views = 0

        # Phase 37 Smart Disruption & Incident Intelligence Counters
        self.incident_queries = 0
        self.active_incidents = 0
        self.incident_alerts = 0
        self.route_disruption_views = 0
        self.stop_disruption_views = 0
        self.active_journey_disruption_warnings = 0
        self.transfer_risk_warnings = 0
        self.alternative_journey_views = 0
        self.incident_ai_queries = 0
        self.simulated_incidents = 0
        self.official_incidents = 0

        # Phase 38 Predictive Commuter Intelligence Counters
        self.prediction_requests = 0
        self.arrival_predictions = 0
        self.journey_predictions = 0
        self.transfer_predictions = 0
        self.crowd_predictions_v2 = 0
        self.prediction_ai_queries = 0

        # Phase 39 Smart Commuter Recommendations Counters
        self.commuter_recommendations_count = 0
        self.saved_recommendations_count = 0
        self.favorite_recommendations_count = 0
        self.disruption_recommendations_count = 0
        self.recommendation_ai_queries = 0

        # Phase 40 Production Readiness & Municipal Operations Counters
        self.health_checks = 0
        self.data_quality_checks = 0
        self.operational_events_count = 0
        self.operations_ai_queries = 0

        # Phase 41 Smart Transit Trip Assurance & Commuter Safety Counters
        self.trip_assurance_queries = 0
        self.trip_assurance_on_track = 0
        self.trip_assurance_delayed = 0
        self.trip_assurance_transfer_risk = 0
        self.trip_assurance_disrupted = 0
        self.trip_assurance_offline = 0
        self.trip_assurance_arrived = 0
        self.assurance_rechecks = 0
        self.assurance_alternative_views = 0
        self.journey_completion_views = 0
        self.trip_assurance_ai_queries = 0

        # Phase 41 Smart Commuter Safety, Emergency & Journey Assistance Counters
        self.safety_status_queries = 0
        self.safety_events = 0
        self.assistance_requests = 0
        self.assistance_cancellations = 0
        self.safety_checks = 0
        self.journey_shares_started = 0
        self.journey_shares_stopped = 0
        self.journey_shares_expired = 0
        self.safety_ai_queries = 0
        self.nearby_safety_queries = 0

        # Phase 21 Production Feed Observability Counters
        self.realtime_poll_attempts = 0
        self.realtime_successful_polls = 0
        self.realtime_failed_polls = 0
        self.vehicle_entities_received = 0
        self.vehicle_entities_valid = 0
        self.vehicle_entities_invalid = 0
        self.trip_updates_received = 0
        self.service_alerts_received = 0
        self.realtime_connection_failures = 0
        self.last_successful_realtime_fetch: Optional[datetime] = None

        # Latency tracking: sliding window of the last 200 requests (ms)
        self._latencies: Deque[float] = deque(maxlen=200)
        self._group_latencies: Dict[str, Deque[float]] = {}

        # Per endpoint metrics: { endpoint: { "count": int, "total_ms": float } }
        self._endpoint_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "total_ms": 0.0})

    def record_request(self, endpoint: str, latency_ms: float):
        self.total_requests += 1
        self._latencies.append(latency_ms)
        group = self._perf_group(endpoint)
        if group:
            self._group_latencies.setdefault(group, deque(maxlen=500)).append(latency_ms)
        stat = self._endpoint_stats[endpoint]
        stat["count"] += 1
        stat["total_ms"] += latency_ms

        if "/api/ai/chat" in endpoint:
            self.ai_requests_count += 1
        elif "/api/tickets/verify" in endpoint or "/api/tickets" in endpoint:
            self.ticket_verifications_count += 1
        elif "/api/crowd" in endpoint or "/crowd-prediction" in endpoint:
            self.crowd_prediction_requests_count += 1
            self.crowd_forecast_views_count += 1
            self.crowd_queries += 1
        elif "/api/incidents" in endpoint:
            self.incident_queries += 1
        elif "/api/journey/recommend" in endpoint:
            self.journey_recommendations_count += 1
        elif "/api/journey/search" in endpoint:
            self.journey_search_requests_count += 1
        elif "/api/alerts" in endpoint:
            self.alert_views_count += 1
        elif "/stops/nearby" in endpoint or "/stops" in endpoint:
            self.nearby_stop_queries_count += 1
        elif "/location" in endpoint or "/buses/" in endpoint:
            self.bus_tracking_actions_count += 1
            self.active_trip_views_count += 1

    def record_stale_transition(self):
        self.stale_transitions_count += 1

    def record_realtime_poll(self, success: bool = True):
        self.realtime_poll_attempts += 1
        if success:
            self.realtime_successful_polls += 1
            self.last_successful_realtime_fetch = datetime.now(timezone.utc)
        else:
            self.realtime_failed_polls += 1

    def record_realtime_failure(self):
        self.realtime_connection_failures += 1

    def record_realtime_connection_failure(self):
        self.realtime_connection_failures += 1

    def record_vehicle_entity(self, valid: bool = True, count: int = 1):
        self.vehicle_entities_received += count
        if valid:
            self.vehicle_entities_valid += count
        else:
            self.vehicle_entities_invalid += count

    def record_entity_validation(self, valid: int, invalid: int, ignored: int = 0):
        self.vehicle_entities_received += (valid + invalid + ignored)
        self.vehicle_entities_valid += valid
        self.vehicle_entities_invalid += invalid

    def record_trip_update(self, count: int = 1):
        self.trip_updates_received += count

    def record_service_alert(self, count: int = 1):
        self.service_alerts_received += count

    def record_feed_counts(self, vehicle_positions: int, trip_updates: int, service_alerts: int):
        self.trip_updates_received = trip_updates
        self.service_alerts_received = service_alerts

    def get_uptime_seconds(self) -> float:
        return round(time.time() - self.start_time, 2)

    def get_latency_stats(self) -> Dict[str, float]:
        if not self._latencies:
            return {"avg_ms": 0.0, "p95_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0, "min": 0.0, "avg": 0.0, "p95": 0.0, "max": 0.0}

        sorted_lats = sorted(self._latencies)
        p95_idx = int(len(sorted_lats) * 0.95)
        p95 = sorted_lats[min(p95_idx, len(sorted_lats) - 1)]
        avg = sum(self._latencies) / len(self._latencies)
        min_v = sorted_lats[0]
        max_v = sorted_lats[-1]

        return {
            "avg_ms": round(avg, 2),
            "p95_ms": round(p95, 2),
            "min_ms": round(min_v, 2),
            "max_ms": round(max_v, 2),
            "min": round(min_v, 2),
            "avg": round(avg, 2),
            "p95": round(p95, 2),
            "max": round(max_v, 2),
            "p99_ms": round(sorted_lats[min(int(len(sorted_lats) * 0.99), len(sorted_lats) - 1)], 2),
        }

    # Phase 49: per-capability latency (bounded windows, no behaviour change)
    _PERF_GROUPS = (
        ("/api/payment/verify", "payment_verification"),
        ("/api/tickets/verify", "ticket_validation"),
        ("/api/journey/search", "journey_planning"),
        ("/api/journey/recommend", "journey_planning"),
        ("/api/ai/chat", "ai_assistant"),
        ("/api/notifications", "notifications"),
        ("/api/gtfs", "gtfs_queries"),
        ("/api/buses", "map_updates"),
    )

    def _perf_group(self, endpoint: str) -> Optional[str]:
        for prefix, name in self._PERF_GROUPS:
            if endpoint.startswith(prefix):
                return name
        return None

    @staticmethod
    def _percentiles(values) -> Dict[str, float]:
        if not values:
            return {"count": 0, "avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0}
        v = sorted(values)
        pick = lambda q: v[min(int(len(v) * q), len(v) - 1)]
        return {
            "count": len(v),
            "avg_ms": round(sum(v) / len(v), 2),
            "p50_ms": round(pick(0.50), 2),
            "p95_ms": round(pick(0.95), 2),
            "p99_ms": round(pick(0.99), 2),
            "max_ms": round(v[-1], 2),
        }

    def get_performance_report(self) -> Dict[str, Any]:
        return {
            "overall": self._percentiles(list(self._latencies)),
            "by_capability": {k: self._percentiles(list(d)) for k, d in sorted(self._group_latencies.items())},
            "window": "last 200 requests overall, last 500 per capability (in-process measurements)",
        }

    def get_summary(self) -> Dict[str, Any]:
        lat = self.get_latency_stats()
        return {
            "uptime_seconds": self.get_uptime_seconds(),
            "total_requests": self.total_requests,
            "latency": lat,
            "latency_stats": lat,
            "realtime_poll_attempts": self.realtime_poll_attempts,
            "realtime_successful_polls": self.realtime_successful_polls,
            "realtime_failed_polls": self.realtime_failed_polls,
            "vehicle_entities_received": self.vehicle_entities_received,
            "vehicle_entities_valid": self.vehicle_entities_valid,
            "vehicle_entities_invalid": self.vehicle_entities_invalid,
            "trip_updates_received": self.trip_updates_received,
            "service_alerts_received": self.service_alerts_received,
            "realtime_connection_failures": self.realtime_connection_failures,
            "counters": {
                "ai_requests": self.ai_requests_count,
                "ticket_verifications": self.ticket_verifications_count,
                "crowd_predictions": self.crowd_prediction_requests_count,
                "journey_searches": self.journey_search_requests_count,
                "journey_recommendations": self.journey_recommendations_count,
                "bus_tracking_actions": self.bus_tracking_actions_count,
                "alert_views": self.alert_views_count,
                "nearby_stop_queries": self.nearby_stop_queries_count,
                "active_trip_views": self.active_trip_views_count,
                # Phase 32
                "active_journey_started": self.active_journey_started,
                "active_journey_completed": self.active_journey_completed,
                "journey_cancelled": self.journey_cancelled,
                "journey_state_transitions": self.journey_state_transitions,
                "journey_history_views": self.journey_history_views,
                # Phase 33
                "destination_approach_alerts": self.destination_approach_alerts,
                "get_ready_to_exit_alerts": self.get_ready_to_exit_alerts,
                "destination_reached_events": self.destination_reached_events,
                "missed_destination_warnings": self.missed_destination_warnings,
                "journey_notification_events": self.journey_notification_events,
                # Phase 34
                "transfer_journeys_started": self.transfer_journeys_started,
                "transfer_views": self.transfer_views,
                "transfer_alerts": self.transfer_alerts,
                "transfer_completed": self.transfer_completed,
                "missed_transfer_warnings": self.missed_transfer_warnings,
                "connecting_bus_tracking_actions": self.connecting_bus_tracking_actions,
                "transfer_ai_queries": self.transfer_ai_queries,
                # Phase 35
                "accessible_journey_searches": self.accessible_journey_searches,
                "accessible_options_viewed": self.accessible_options_viewed,
                "wheelchair_priority_queries": self.wheelchair_priority_queries,
                "low_floor_filter_applied": self.low_floor_filter_applied,
                "accessibility_ai_queries": self.accessibility_ai_queries,
                # Phase 36
                "crowd_queries": self.crowd_queries,
                "crowd_predictions_made": self.crowd_predictions,
                "crowd_unknown_responses": self.crowd_unknown_responses,
                "crowd_verified_responses": self.crowd_verified_responses,
                "crowd_estimated_responses": self.crowd_estimated_responses,
                "seat_availability_queries": self.seat_availability_queries,
                "crowd_ai_queries": self.crowd_ai_queries,
                "crowd_alerts": self.crowd_alerts,
                "crowd_comparison_views": self.crowd_comparison_views,
                # Phase 37
                "incident_queries": self.incident_queries,
                "active_incidents": self.active_incidents,
                "incident_alerts": self.incident_alerts,
                "route_disruption_views": self.route_disruption_views,
                "stop_disruption_views": self.stop_disruption_views,
                "active_journey_disruption_warnings": self.active_journey_disruption_warnings,
                "transfer_risk_warnings": self.transfer_risk_warnings,
                "alternative_journey_views": self.alternative_journey_views,
                "incident_ai_queries": self.incident_ai_queries,
                "simulated_incidents": self.simulated_incidents,
                "official_incidents": self.official_incidents,
                # Phase 41 Trip Assurance
                "trip_assurance_queries": self.trip_assurance_queries,
                "trip_assurance_on_track": self.trip_assurance_on_track,
                "trip_assurance_delayed": self.trip_assurance_delayed,
                "trip_assurance_transfer_risk": self.trip_assurance_transfer_risk,
                "trip_assurance_disrupted": self.trip_assurance_disrupted,
                "trip_assurance_offline": self.trip_assurance_offline,
                "trip_assurance_arrived": self.trip_assurance_arrived,
                "assurance_rechecks": self.assurance_rechecks,
                "assurance_alternative_views": self.assurance_alternative_views,
                "journey_completion_views": self.journey_completion_views,
                "trip_assurance_ai_queries": self.trip_assurance_ai_queries,
                "stale_transitions": self.stale_transitions_count,
                "realtime_poll_attempts": self.realtime_poll_attempts,
                "realtime_successful_polls": self.realtime_successful_polls,
                "realtime_failed_polls": self.realtime_failed_polls,
                "vehicle_entities_received": self.vehicle_entities_received,
                "vehicle_entities_valid": self.vehicle_entities_valid,
                "vehicle_entities_invalid": self.vehicle_entities_invalid,
                "trip_updates_received": self.trip_updates_received,
                "service_alerts_received": self.service_alerts_received,
                "realtime_connection_failures": self.realtime_connection_failures,
            },
            "last_successful_realtime_fetch": self.last_successful_realtime_fetch.isoformat() if self.last_successful_realtime_fetch else None,
        }

    def reset(self):
        self._group_latencies = {}
        self.active_journey_started = 0
        self.active_journey_completed = 0
        self.journey_cancelled = 0
        self.journey_state_transitions = 0
        self.journey_history_views = 0
        self.destination_approach_alerts = 0
        self.get_ready_to_exit_alerts = 0
        self.destination_reached_events = 0
        self.missed_destination_warnings = 0
        self.journey_notification_events = 0
        self.transfer_journeys_started = 0
        self.transfer_views = 0
        self.transfer_alerts = 0
        self.transfer_completed = 0
        self.missed_transfer_warnings = 0
        self.connecting_bus_tracking_actions = 0
        self.transfer_ai_queries = 0
        self.accessible_journey_searches = 0
        self.accessible_options_viewed = 0
        self.wheelchair_priority_queries = 0
        self.low_floor_filter_applied = 0
        self.accessibility_ai_queries = 0
        self.crowd_queries = 0
        self.crowd_predictions = 0
        self.crowd_unknown_responses = 0
        self.crowd_verified_responses = 0
        self.crowd_estimated_responses = 0
        self.seat_availability_queries = 0
        self.crowd_ai_queries = 0
        self.crowd_alerts = 0
        self.crowd_comparison_views = 0
        self.incident_queries = 0
        self.active_incidents = 0
        self.incident_alerts = 0
        self.route_disruption_views = 0
        self.stop_disruption_views = 0
        self.active_journey_disruption_warnings = 0
        self.transfer_risk_warnings = 0
        self.alternative_journey_views = 0
        self.incident_ai_queries = 0
        self.simulated_incidents = 0
        self.official_incidents = 0
        # Phase 41
        self.trip_assurance_queries = 0
        self.trip_assurance_on_track = 0
        self.trip_assurance_delayed = 0
        self.trip_assurance_transfer_risk = 0
        self.trip_assurance_disrupted = 0
        self.trip_assurance_offline = 0
        self.trip_assurance_arrived = 0
        self.assurance_rechecks = 0
        self.assurance_alternative_views = 0
        self.journey_completion_views = 0
        self.trip_assurance_ai_queries = 0
        self.safety_status_queries = 0
        self.safety_events = 0
        self.assistance_requests = 0
        self.assistance_cancellations = 0
        self.safety_checks = 0
        self.journey_shares_started = 0
        self.journey_shares_stopped = 0
        self.journey_shares_expired = 0
        self.safety_ai_queries = 0
        self.nearby_safety_queries = 0


# Global metrics tracker instance
metrics_service = MetricsService()
