import unittest
import asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.models.transit import (
    CrowdStatus,
    CrowdDataSource,
    SeatAvailabilityStatus,
    AIChatRequest,
    JourneySearchRequest,
    ActiveJourneyCreateRequest,
)
from app.services.crowd_service import crowd_service
from app.services.ai_service import AIService
from app.services.journey_service import JourneyService
from app.services.recommendation_service import RecommendationService
from app.services.active_journey_service import active_journey_service
from app.services.metrics_service import metrics_service
from app.services.notification_service import notification_service


class TestPhase36CrowdIntelligence(unittest.TestCase):
    """
    Comprehensive verification suite for Phase 36:
    Smart Crowd, Seat & Occupancy Intelligence for Bengaluru Transit.
    """

    def setUp(self):
        self.client = TestClient(app)
        crowd_service.set_simulation_override(None)

    def tearDown(self):
        crowd_service.set_simulation_override(None)

    # -------------------------------------------------------------------------
    # 1. CORE DISCLOSURES & NO FAKE HEADCOUNTS
    # -------------------------------------------------------------------------
    def test_canonical_disclosures_and_no_fake_headcounts(self):
        """Verify canonical disclosures and that unverified occupancy has None percentage."""
        # Query an unknown route
        meta_unknown = crowd_service.get_crowd_metadata("UNKNOWN-ROUTE-999")
        self.assertEqual(meta_unknown.crowd_status, CrowdStatus.UNKNOWN.value)
        self.assertIsNone(meta_unknown.occupancy_percentage)
        self.assertEqual(
            meta_unknown.disclosure,
            "Passenger occupancy data is unavailable from the current feed.",
        )
        self.assertEqual(meta_unknown.source, CrowdDataSource.UNAVAILABLE.value)

        # Query known corridor 500D in simulated mode
        meta_500d = crowd_service.get_crowd_metadata("500D", is_simulated=True)
        self.assertIsNone(meta_500d.occupancy_percentage)  # Never fake exact counts
        self.assertIn(meta_500d.crowd_status, [CrowdStatus.HIGH.value, CrowdStatus.MODERATE.value])
        self.assertIn("SIMULATED CROWD DATA", meta_500d.disclosure)
        self.assertIn(
            "Actual passenger occupancy is unavailable from the current feed.",
            meta_500d.disclosure,
        )

    def test_verified_apc_telemetry_handling(self):
        """When legitimate verified APC is reported, attach percentage honestly."""
        meta_verified = crowd_service.get_crowd_metadata("500D", verified_occupancy=78)
        self.assertEqual(meta_verified.source, CrowdDataSource.VERIFIED_APC.value)
        self.assertEqual(meta_verified.occupancy_percentage, 78)
        self.assertEqual(meta_verified.crowd_status, CrowdStatus.HIGH.value)
        self.assertEqual(meta_verified.estimated_seat_availability, SeatAvailabilityStatus.STANDING_LIKELY.value)
        self.assertIn("Verified occupancy reported by transit telemetry.", meta_verified.disclosure)

    # -------------------------------------------------------------------------
    # 2. EVALUATOR SIMULATION OVERRIDE
    # -------------------------------------------------------------------------
    def test_evaluator_simulation_override(self):
        """Test jury/evaluator toggle for low, moderate, high, very high, unknown, and clear."""
        # Set override to VERY_HIGH
        crowd_service.set_simulation_override("VERY_HIGH")
        meta = crowd_service.get_crowd_metadata("500D")
        self.assertEqual(meta.crowd_status, CrowdStatus.VERY_HIGH.value)
        self.assertEqual(meta.estimated_seat_availability, SeatAvailabilityStatus.VERY_CROWDED.value)
        self.assertEqual(meta.standing_likelihood, "HIGH")
        self.assertEqual(meta.source, CrowdDataSource.SIMULATED.value)
        self.assertIsNone(meta.occupancy_percentage)

        # Set override to LOW
        crowd_service.set_simulation_override("LOW")
        meta_low = crowd_service.get_crowd_metadata("356")
        self.assertEqual(meta_low.crowd_status, CrowdStatus.LOW.value)
        self.assertEqual(meta_low.estimated_seat_availability, SeatAvailabilityStatus.SEATS_LIKELY_AVAILABLE.value)

        # Clear override
        crowd_service.set_simulation_override(None)
        self.assertIsNone(crowd_service.get_simulation_override())

    # -------------------------------------------------------------------------
    # 3. AI CHAT INTENTS & GROUNDED DISCLOSURES
    # -------------------------------------------------------------------------
    def test_ai_least_crowded_option(self):
        """Verify AI responds with least crowded bus option."""
        req = AIChatRequest(message="Which is the least crowded bus?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "least_crowded_option")
        self.assertIn("lowest estimated crowd", res.answer.lower())
        self.assertTrue(metrics_service.crowd_ai_queries > 0)

    def test_ai_standing_likelihood(self):
        """Verify AI responds to standing likelihood without fabricating passenger counts."""
        req = AIChatRequest(message="Will I have to stand on 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "standing_likelihood")
        self.assertIn("standing likelihood", res.answer.lower())
        self.assertIn("500d", res.answer.lower())

    def test_ai_occupancy_source(self):
        """Verify AI discloses occupancy telemetry source."""
        req = AIChatRequest(message="What is the occupancy source for 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "occupancy_source")
        self.assertIn("occupancy data source", res.answer.lower())

    def test_ai_seat_availability_disclosure(self):
        """Verify AI responds to seat availability with transparent likelihood."""
        req = AIChatRequest(message="Will I get a seat on 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "seat_availability")
        self.assertIn("seat", res.answer.lower())
        self.assertTrue(metrics_service.seat_availability_queries > 0)

    # -------------------------------------------------------------------------
    # 4. REST API ENDPOINTS
    # -------------------------------------------------------------------------
    def test_rest_api_crowd_bus(self):
        """Verify GET /api/crowd/{route_or_bus_id}."""
        resp = self.client.get("/api/crowd/500D")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["route_or_bus_id"], "500D")
        self.assertIn(data["crowd_status"], ["LOW", "MODERATE", "HIGH", "VERY_HIGH"])
        self.assertIn(data["seat_status"].replace("_", " "), [
            "SEATS LIKELY AVAILABLE", "LIMITED SEATS", "STANDING LIKELY", "VERY CROWDED", "UNKNOWN"
        ])
        self.assertIn("feed", data["disclosure"])

    def test_rest_api_crowd_stop(self):
        """Verify GET /api/crowd/stop/{stop_id}."""
        resp = self.client.get("/api/crowd/stop/stop-silk-board")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["stop_id"], "stop-silk-board")
        self.assertIn("crowd_status", data)

    def test_rest_api_crowd_simulation_override(self):
        """Verify POST /api/crowd/simulation/override."""
        post_resp = self.client.post("/api/crowd/simulation/override", json={"scenario": "HIGH"})
        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(post_resp.json()["simulation_override"], "HIGH")

        # Check that GET now reflects the override
        get_resp = self.client.get("/api/crowd/500D")
        self.assertEqual(get_resp.json()["crowd_status"], "HIGH")

        # Clear override
        clear_resp = self.client.post("/api/crowd/simulation/override", json={"scenario": None})
        self.assertEqual(clear_resp.status_code, 200)
        self.assertIsNone(clear_resp.json()["simulation_override"])

    def test_rest_api_system_status_crowd_engine(self):
        """Verify GET /api/system/status exposes Crowd Engine and diagnostics."""
        resp = self.client.get("/api/system/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        module_names = [m["name"] for m in data["modules"]]
        self.assertIn("Crowd Engine", module_names)
        self.assertIn("Occupancy Feed", module_names)
        self.assertIn("crowd", data["diagnostics"])
        crowd_diag = data["diagnostics"]["crowd"]
        self.assertIn("crowd_queries", crowd_diag)
        self.assertIn("crowd_predictions", crowd_diag)

    # -------------------------------------------------------------------------
    # 5. JOURNEY SERVICE & RECOMMENDATIONS WITH CROWD
    # -------------------------------------------------------------------------
    def test_journey_service_attaches_crowd(self):
        """Verify search_journey attaches crowd metadata to options and legs."""
        req = JourneySearchRequest(
            origin="Central Silk Board Junction",
            destination="Majestic (Kempegowda Bus Station)"
        )
        res = asyncio.run(JourneyService.search_journey(req))
        self.assertTrue(len(res.options) > 0)
        for opt in res.options:
            self.assertIsNotNone(opt.crowd)
            self.assertIn(opt.crowd.crowd_status, ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "UNKNOWN"])
            self.assertIn(opt.crowd_status, ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "UNKNOWN"])

    def test_journey_recommendations_lower_crowd_winner(self):
        """Verify factual comparison includes lower estimated crowd when available."""
        from app.models.transit import JourneyRecommendationRequest
        rec_req = JourneyRecommendationRequest(
            origin="Central Silk Board Junction",
            destination="Majestic (Kempegowda Bus Station)"
        )
        rec_res = asyncio.run(RecommendationService.recommend_journey(rec_req))
        winner_categories = [w.category for w in rec_res.winners]
        self.assertIn("Lower Estimated Crowd", winner_categories)
        self.assertIn("crowd_comparison", rec_res.factual_comparison)

    # -------------------------------------------------------------------------
    # 6. ACTIVE JOURNEY WITH CROWD TELEMETRY
    # -------------------------------------------------------------------------
    def test_active_journey_crowd_synchronization(self):
        """Verify active journey initializes and synchronizes crowd telemetry."""
        create_req = ActiveJourneyCreateRequest(
            route_number="500D",
            bus_id="bus-500d-1",
            origin="Central Silk Board Junction",
            destination="Majestic (Kempegowda Bus Station)"
        )
        aj = asyncio.run(active_journey_service.start_journey(create_req))
        self.assertIsNotNone(aj.crowd)
        self.assertIn(aj.crowd.crowd_status, ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "UNKNOWN"])
        self.assertIsNone(aj.crowd.occupancy_percentage)

        # GET /api/crowd/journey/{journey_id}
        resp = self.client.get(f"/api/crowd/journey/{aj.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["journey_id"], aj.id)
        self.assertIn(data["crowd_status"], ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "UNKNOWN"])

        # End journey cleanup
        active_journey_service.end_journey()

    # -------------------------------------------------------------------------
    # 7. CROWD ALERT DEDUPLICATION
    # -------------------------------------------------------------------------
    def test_crowd_alert_deduplication(self):
        """Verify notification_service.create_crowd_alert deduplicates within 5 minutes."""
        evt1 = notification_service.create_crowd_alert("500D", "HIGH")
        self.assertIsNotNone(evt1)
        # Immediate duplicate should be suppressed
        evt2 = notification_service.create_crowd_alert("500D", "HIGH")
        self.assertIsNone(evt2)


if __name__ == "__main__":
    unittest.main()
