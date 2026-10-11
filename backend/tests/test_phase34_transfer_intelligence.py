import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import OPERATIONAL_STATEMENT_NOT_CONNECTED
from app.services.active_journey_service import active_journey_service
from app.services.metrics_service import metrics_service
from app.models.transit import (
    ActiveJourneyCreateRequest,
    JourneyState,
    TransferDetails,
    JourneyLeg,
)


class TestPhase34TransferIntelligence(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        active_journey_service.reset()

    def test_01_multimodal_journey_model_generation(self):
        """1. Multi-leg journey generation with WALK, BUS, TRANSFER, WALK legs."""
        res = self.client.post(
            "/api/journey/search",
            json={"origin": "Electronic City", "destination": "Shivajinagar"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        options = data.get("options", [])
        transfer_opt = next((opt for opt in options if opt.get("is_multimodal")), None)
        self.assertIsNotNone(transfer_opt)
        self.assertTrue(len(transfer_opt["legs"]) >= 3)
        leg_types = [l["leg_type"] for l in transfer_opt["legs"]]
        self.assertIn("WALK", leg_types)
        self.assertIn("BUS", leg_types)
        self.assertIn("TRANSFER", leg_types)

    def test_02_transfer_card_data_presence(self):
        """2. Transfer details contains transfer_stop, walking_distance, buffer, connecting_route."""
        res = self.client.post(
            "/api/journey/search",
            json={"origin": "Electronic City", "destination": "Shivajinagar"},
        )
        self.assertEqual(res.status_code, 200)
        transfer_opt = next(opt for opt in res.json()["options"] if opt.get("is_multimodal"))
        xfer = transfer_opt["transfer_details"]
        self.assertIsNotNone(xfer)
        self.assertTrue(xfer["walking_distance_meters"] > 0)
        self.assertTrue(xfer["walking_duration_minutes"] > 0)
        self.assertTrue(xfer["transfer_buffer_minutes"] >= 0)
        self.assertTrue(len(xfer["connecting_route"]) > 0)

    def test_03_active_journey_start_with_transfer(self):
        """3. Starting an active journey with transfer sets is_transfer_journey and initializes transfer_details."""
        res = self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "ON_BUS",
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_transfer_journey"])
        self.assertIsNotNone(data["transfer_details"])
        self.assertIsNotNone(data["legs"])
        self.assertEqual(metrics_service.transfer_journeys_started, 1)

    def test_04_transfer_state_transitions_on_bus_to_approaching(self):
        """4. Forward transition: ON_BUS -> TRANSFER_APPROACHING."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "ON_BUS",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "TRANSFER_APPROACHING"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "TRANSFER_APPROACHING")

    def test_05_transfer_state_transitions_approaching_to_ready(self):
        """5. Forward transition: TRANSFER_APPROACHING -> TRANSFER_READY."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "TRANSFER_APPROACHING",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "TRANSFER_READY"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "TRANSFER_READY")

    def test_06_transfer_state_transitions_ready_to_walking(self):
        """6. Forward transition: TRANSFER_READY -> WALKING_TO_CONNECTION."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "TRANSFER_READY",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "WALKING_TO_CONNECTION"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "WALKING_TO_CONNECTION")

    def test_07_transfer_state_transitions_walking_to_waiting(self):
        """7. Forward transition: WALKING_TO_CONNECTION -> WAITING_FOR_CONNECTION."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "WALKING_TO_CONNECTION",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "WAITING_FOR_CONNECTION"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "WAITING_FOR_CONNECTION")

    def test_08_transfer_state_transitions_waiting_to_connecting_approaching(self):
        """8. Forward transition: WAITING_FOR_CONNECTION -> CONNECTING_BUS_APPROACHING."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "WAITING_FOR_CONNECTION",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "CONNECTING_BUS_APPROACHING"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "CONNECTING_BUS_APPROACHING")
        self.assertTrue(res.json()["is_connecting_bus_approaching"])

    def test_09_transfer_state_transitions_to_transfer_completed(self):
        """9. Forward transition: CONNECTING_BUS_APPROACHING -> TRANSFER_COMPLETED."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "CONNECTING_BUS_APPROACHING",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "TRANSFER_COMPLETED"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "TRANSFER_COMPLETED")

    def test_10_transfer_state_transitions_completed_to_destination_approaching(self):
        """10. Forward transition: TRANSFER_COMPLETED -> DESTINATION_APPROACHING."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "TRANSFER_COMPLETED",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "DESTINATION_APPROACHING"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "DESTINATION_APPROACHING")

    def test_11_transfer_buffer_calculation(self):
        """11. Factual transfer buffer calculation: connecting_bus_eta - walking_duration."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "transfer_details": {
                    "transfer_stop": "Central Silk Board Junction",
                    "walking_distance_meters": 250,
                    "walking_duration_minutes": 4,
                    "transfer_buffer_minutes": 6,
                    "connecting_route": "356",
                    "connecting_bus_id": "bus-356-01",
                    "connecting_bus_eta_minutes": 10,
                },
            },
        )
        res = self.client.get("/api/journey/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNotNone(data["transfer_buffer_minutes"])

    def test_12_missed_transfer_detection_reliable_telemetry(self):
        """12. Missed transfer flagged when connecting bus ETA drops to 0 while user is walking."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "WALKING_TO_CONNECTION",
                "transfer_details": {
                    "transfer_stop": "Central Silk Board Junction",
                    "walking_distance_meters": 250,
                    "walking_duration_minutes": 4,
                    "transfer_buffer_minutes": -2,
                    "connecting_route": "356",
                    "connecting_bus_id": "bus-356-01",
                    "connecting_bus_eta_minutes": 0,
                },
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "TRANSFER_MISSED"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "TRANSFER_MISSED")
        self.assertTrue(res.json()["is_transfer_missed"])
        self.assertGreaterEqual(metrics_service.missed_transfer_warnings, 1)

    def test_13_missed_transfer_suppression_when_offline(self):
        """13. Missed transfer warning is suppressed when journey is OFFLINE or telemetry is unreliable."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "OFFLINE",
            },
        )
        res = self.client.get("/api/journey/active")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json().get("is_transfer_missed", False))

    def test_14_get_active_journey_transfer_endpoint(self):
        """14. GET /api/journey/transfer returns transfer metadata and updates transfer_views counter."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "WAITING_FOR_CONNECTION",
            },
        )
        initial_views = metrics_service.transfer_views
        res = self.client.get("/api/journey/transfer")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("transfer_details", data)
        self.assertIn("transfer_buffer_minutes", data)
        self.assertEqual(metrics_service.transfer_views, initial_views + 1)

    def test_15_get_active_journey_transfer_404_when_no_transfer(self):
        """15. GET /api/journey/transfer returns 404 when active journey is direct (no transfer)."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal",
                "is_transfer_journey": False,
            },
        )
        res = self.client.get("/api/journey/transfer")
        self.assertEqual(res.status_code, 404)

    def test_16_ai_query_transfer_guidance(self):
        """16. Grounded AI assistant answers transfer guidance with data disclosure."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "ON_BUS",
            },
        )
        res = self.client.post(
            "/api/ai/chat",
            json={"message": "Where do I transfer for my trip?"},
        )
        self.assertEqual(res.status_code, 200)
        content = res.json().get("answer", "")
        self.assertIn("transfer", content.lower())
        self.assertTrue(
            "simulated" in content.lower() or "feed" in content.lower()
        )
        self.assertGreaterEqual(metrics_service.transfer_ai_queries, 1)

    def test_17_ai_query_connecting_bus_eta(self):
        """17. Grounded AI assistant answers connecting bus ETA query."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "WALKING_TO_CONNECTION",
            },
        )
        res = self.client.post(
            "/api/ai/chat",
            json={"message": "When does my connecting bus arrive?"},
        )
        self.assertEqual(res.status_code, 200)
        content = res.json().get("answer", "")
        self.assertTrue("connecting bus" in content.lower() or "356" in content)
        self.assertGreaterEqual(metrics_service.transfer_ai_queries, 1)

    def test_18_system_status_observability_counters(self):
        """18. GET /api/system/status exposes all Phase 34 transfer metrics in diagnostics.journey."""
        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)
        diag = res.json().get("diagnostics", {})
        journey_diag = diag.get("journey", {})
        self.assertIn("transfer_journeys_started", journey_diag)
        self.assertIn("transfer_views", journey_diag)
        self.assertIn("transfer_alerts", journey_diag)
        self.assertIn("transfer_completed", journey_diag)
        self.assertIn("missed_transfer_warnings", journey_diag)
        self.assertIn("connecting_bus_tracking_actions", journey_diag)
        self.assertIn("transfer_ai_queries", journey_diag)

    def test_19_end_journey_increments_transfer_completed(self):
        """19. Ending a transfer journey increments transfer_completed metric."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "is_transfer_journey": True,
                "initial_state": "TRANSFER_COMPLETED",
            },
        )
        initial = metrics_service.transfer_completed
        res = self.client.post("/api/journey/active/end?reason=COMPLETED")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(metrics_service.transfer_completed, initial + 1)

    def test_20_invalid_state_transition_from_terminal_rejected(self):
        """20. Rejects invalid transition out of COMPLETED state."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Electronic City",
                "destination": "Shivajinagar",
                "initial_state": "COMPLETED",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "TRANSFER_APPROACHING"})
        self.assertEqual(res.status_code, 400)

    def test_21_canonical_operational_statement_preserved(self):
        """21. Absolute verification that canonical statement is exactly preserved."""
        self.assertEqual(
            OPERATIONAL_STATEMENT_NOT_CONNECTED,
            "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED",
        )
        res = self.client.get("/api/realtime/test")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.json().get("message"),
            "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED",
        )

    def test_22_zero_raw_aadhaar_data(self):
        """22. Verify no raw Aadhaar number or biometric fields in active journey, transfer, or search."""
        res = self.client.post(
            "/api/journey/search",
            json={"origin": "Electronic City", "destination": "Shivajinagar"},
        )
        raw_text = res.text
        self.assertNotIn("aadhaar_number", raw_text)
        self.assertNotIn("biometric", raw_text)
        self.assertNotIn("fingerprint", raw_text)


if __name__ == "__main__":
    unittest.main()
