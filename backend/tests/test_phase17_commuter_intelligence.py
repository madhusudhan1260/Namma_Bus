import unittest
import asyncio
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta

from app.main import app
from app.models.transit import (
    JourneyRecommendationRequest,
    JourneyRecommendationResponse,
    AIChatRequest,
)
from app.services.recommendation_service import RecommendationService
from app.services.eta_service import ETAService
from app.services.crowd_prediction_service import CrowdPredictionService
from app.services.ai_service import AIService
from app.services.notification_service import notification_service
from app.services.metrics_service import metrics_service


class TestPhase17CommuterIntelligence(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_1_recommendation_engine_factual_winners(self):
        """Test journey recommendation service returns factual winners without subjective scoring."""
        req = JourneyRecommendationRequest(
            origin="Silk Board",
            destination="Hebbal"
        )
        res = asyncio.run(RecommendationService.recommend_journey(req))
        self.assertIsInstance(res, JourneyRecommendationResponse)
        self.assertGreater(len(res.options), 0)
        self.assertGreater(len(res.winners), 0)
        categories = [w.category for w in res.winners]
        self.assertTrue(any(c in ["Fastest", "Lowest Fare", "More Seats", "Fewest Stops", "Least Transfers"] for c in categories))
        self.assertIn("fastest_route", res.factual_comparison)
        self.assertIn("lowest_fare_route", res.factual_comparison)

    def test_2_recommendation_api_endpoint(self):
        """Test POST /api/journey/recommend endpoint."""
        payload = {
            "origin": "Silk Board",
            "destination": "Hebbal"
        }
        resp = self.client.post("/api/journey/recommend", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("winners", data)
        self.assertIn("options", data)
        self.assertIn("factual_comparison", data)

    def test_3_eta_intelligence_confidence_and_freshness(self):
        """Test ETA engine confidence grading, staleness detection, and trip update integration."""
        eta_high = ETAService.calculate_eta(
            bus_id="500D_UP_01",
            route_number="500D",
            bus_lat=12.9176,
            bus_lon=77.6238,
            target_stop_name="Hebbal",
            target_lat=13.0358,
            target_lon=77.5970,
            source="gtfs_rt_trip_update",
            feed_is_stale=False,
            trip_update_eta_seconds=240,
        )
        self.assertEqual(eta_high.confidence, "high")
        self.assertEqual(eta_high.source, "gtfs_rt_trip_update")
        self.assertFalse(eta_high.is_stale)

        eta_stale = ETAService.calculate_eta(
            bus_id="500D_UP_01",
            route_number="500D",
            bus_lat=12.9176,
            bus_lon=77.6238,
            target_stop_name="Hebbal",
            target_lat=13.0358,
            target_lon=77.5970,
            source="geometric_estimate",
            feed_is_stale=True,
        )
        self.assertEqual(eta_stale.confidence, "low")
        self.assertTrue(eta_stale.is_stale)

    def test_4_crowd_intelligence_trend_and_disclaimer(self):
        """Test crowd prediction service trend computation, factual corridor explanation, and disclaimer."""
        pred = asyncio.run(CrowdPredictionService.predict_for_bus("bus-500d-1"))
        self.assertIsNotNone(pred)
        self.assertIn(pred.trend, ["increasing", "stable", "decreasing"])
        self.assertTrue(len(pred.predictions) >= 3)
        self.assertTrue(len(pred.explanation) > 0)
        self.assertIn("Estimated crowd based on simulated historical boarding patterns", pred.disclaimer)
        self.assertIn("Actual occupancy may vary", pred.disclaimer)

    def test_5_ai_session_memory_pronoun_resolution(self):
        """Test conversational AI multi-turn pronoun resolution via session_id."""
        session_id = "test-phase17-session-001"
        # Turn 1: Ask about 500D
        req1 = AIChatRequest(message="Where is 500D?", session_id=session_id)
        resp1 = asyncio.run(AIService.process_chat(req1))
        self.assertEqual(resp1.intent, "bus_location")

        # Turn 2: Follow-up pronoun "Will I get a seat?"
        req2 = AIChatRequest(message="Will I get a seat?", session_id=session_id)
        resp2 = asyncio.run(AIService.process_chat(req2))
        self.assertEqual(resp2.intent, "seat_availability")
        self.assertIn("500D", resp2.answer)

    def test_6_ai_service_alerts_intent(self):
        """Test conversational AI handles alert inquiries."""
        req = AIChatRequest(message="Are there any service alerts on Outer Ring Road?")
        resp = asyncio.run(AIService.process_chat(req))
        self.assertEqual(resp.intent, "service_alerts")
        self.assertTrue(len(resp.answer) > 0)

    def test_7_nearby_stops_intelligence_endpoint(self):
        """Test GET /api/stops/nearby returns structured intelligence with distance and buses."""
        resp = self.client.get("/api/stops/nearby?latitude=12.9176&longitude=77.6238&radius_meters=3000")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        first_stop = data[0]
        self.assertIn("stop_id", first_stop)
        self.assertIn("name", first_stop)
        self.assertIn("distance_meters", first_stop)
        self.assertIn("routes", first_stop)
        self.assertIn("next_bus_route", first_stop)

    def test_8_notification_service(self):
        """Test notification event creation and retrieval."""
        evt = notification_service.create_event(
            event_type="approaching_bus",
            title="500D Approaching",
            message="Bus 500D is 3 minutes from Silk Board",
            route_number="500D",
            stop_name="Central Silk Board Junction",
            severity="INFO"
        )
        self.assertEqual(evt.event_type, "approaching_bus")
        self.assertEqual(evt.route_number, "500D")

        events = notification_service.get_events(limit=10)
        self.assertGreater(len(events), 0)
        self.assertTrue(any(e.id == evt.id for e in events))

    def test_9_metrics_service_counters(self):
        """Test aggregate non-sensitive metric counters via record_request."""
        metrics_service.record_request("/api/journey/recommend", 15.0)
        metrics_service.record_request("/buses/bus-500d-1", 5.0)
        metrics_service.record_request("/api/crowd/bus-500d-1", 10.0)
        metrics_service.record_request("/api/alerts", 4.0)

        self.assertGreater(metrics_service.journey_recommendations_count, 0)
        self.assertGreater(metrics_service.bus_tracking_actions_count, 0)
        self.assertGreater(metrics_service.crowd_forecast_views_count, 0)
        self.assertGreater(metrics_service.alert_views_count, 0)

    def test_10_system_status_all_modules(self):
        """Test GET /api/system/status returns all expected modules and system diagnostics."""
        resp = self.client.get("/api/system/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(len(data["modules"]), 11)
        module_names = [m["name"] for m in data["modules"]]
        self.assertIn("Transit Data", module_names)
        self.assertIn("Bus GPS Simulator", module_names)
        self.assertIn("Crowd Prediction", module_names)
        self.assertIn("AI Assistant", module_names)
        self.assertIn("Ticket Engine", module_names)
        self.assertIn("Alert Engine", module_names)
        self.assertIn("Recommendation Engine", module_names)
        self.assertIn("diagnostics", data)


if __name__ == "__main__":
    unittest.main()
