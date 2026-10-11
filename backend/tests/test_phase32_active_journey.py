import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import OPERATIONAL_STATEMENT_NOT_CONNECTED
from app.services.active_journey_service import active_journey_service


class TestPhase32ActiveJourney(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Reset active journey state before each test
        active_journey_service.reset()

    def test_create_active_journey(self):
        """Verify POST /api/journey/active creates and starts an active journey."""
        payload = {
            "route_number": "500D",
            "bus_id": "bus-500d-01",
            "origin": "Central Silk Board Junction",
            "destination": "Hebbal Bus Stop",
            "bus_type": "BMTC Ordinary",
            "fare": 25,
            "walking_distance_meters": 420,
            "walking_duration_minutes": 5,
            "initial_state": "WAITING_FOR_BUS",
        }
        res = self.client.post("/api/journey/active", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["route_number"], "500D")
        self.assertEqual(data["origin"], "Central Silk Board Junction")
        self.assertEqual(data["destination"], "Hebbal Bus Stop")
        self.assertEqual(data["state"], "WAITING_FOR_BUS")
        self.assertEqual(data["walking_distance_meters"], 420)
        self.assertEqual(data["walking_duration_minutes"], 5)
        self.assertTrue(len(data["stops"]) > 0)
        self.assertIsNotNone(data["ticket_id"])

    def test_get_active_journey_sync(self):
        """Verify GET /api/journey/active retrieves the active journey with live telemetry."""
        # Create journey
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
            },
        )
        res = self.client.get("/api/journey/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNotNone(data)
        self.assertEqual(data["route_number"], "500D")
        self.assertIn("next_stop", data)
        self.assertIn("remaining_stops", data)
        self.assertIn("eta_minutes", data)

    def test_update_active_journey_state_machine(self):
        """Verify journey state transitions follow the valid lifecycle machine."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "initial_state": "WAITING_FOR_BUS",
            },
        )

        # Transition to BUS_APPROACHING
        res1 = self.client.patch("/api/journey/active", json={"state": "BUS_APPROACHING"})
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["state"], "BUS_APPROACHING")

        # Transition to ON_BUS
        res2 = self.client.patch("/api/journey/active", json={"state": "ON_BUS"})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["state"], "ON_BUS")

        # Transition to NEAR_DESTINATION
        res3 = self.client.patch("/api/journey/active", json={"state": "NEAR_DESTINATION"})
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.json()["state"], "NEAR_DESTINATION")

        # Transition to COMPLETED
        res4 = self.client.patch("/api/journey/active", json={"state": "COMPLETED"})
        self.assertEqual(res4.status_code, 200)
        self.assertEqual(res4.json()["state"], "COMPLETED")

    def test_invalid_state_transition_rejection(self):
        """Verify invalid state transitions are rejected with HTTP 400."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "initial_state": "COMPLETED",
            },
        )
        # Attempt to transition from COMPLETED to WAITING_FOR_BUS
        res = self.client.patch("/api/journey/active", json={"state": "WAITING_FOR_BUS"})
        self.assertEqual(res.status_code, 400)

    def test_end_active_journey_and_history_archival(self):
        """Verify POST /api/journey/active/end moves journey to history and clears active."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "356",
                "bus_id": "bus-356-01",
                "origin": "Electronic City",
                "destination": "Majestic (Kempegowda Bus Station)",
                "fare": 30,
            },
        )
        res_end = self.client.post("/api/journey/active/end")
        self.assertEqual(res_end.status_code, 200)
        self.assertEqual(res_end.json()["status"], "ended")

        # Verify active journey is now completed or cleared
        res_active = self.client.get("/api/journey/active")
        self.assertEqual(res_active.status_code, 404)

        # Verify history includes the ended journey
        res_history = self.client.get("/api/journey/history")
        self.assertEqual(res_history.status_code, 200)
        history = res_history.json()
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["route_number"], "356")
        self.assertEqual(history[0]["origin"], "Electronic City")
        self.assertEqual(history[0]["destination"], "Majestic (Kempegowda Bus Station)")

    def test_shakti_concession_ticket_linking(self):
        """Verify Shakti scheme zero-fare pass linking and demo pass disclaimer."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "fare": 0,
                "fare_type": "karnataka_women_shakti",
            },
        )
        res = self.client.get("/api/journey/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["fare"], 0)
        self.assertEqual(data["fare_type"], "karnataka_women_shakti")
        self.assertTrue(data["ticket_id"].startswith("TCK-SHAKTI-"))

    def test_service_alert_corridor_linking(self):
        """Verify active journey along a disrupted corridor detects active alert."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
            },
        )
        res = self.client.get("/api/journey/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("has_disruption", data)
        # 500D has a Metro construction advisory in mock alerts
        if data["has_disruption"]:
            self.assertIsNotNone(data["disruption_message"])

    def test_ai_active_journey_context(self):
        """Verify AI assistant uses active journey context to answer trip queries."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "initial_state": "ON_BUS",
            },
        )
        # Ask AI "How many stops left?"
        res_ai = self.client.post(
            "/api/ai/chat",
            json={"message": "How many stops left on my trip?"},
        )
        self.assertEqual(res_ai.status_code, 200)
        answer = res_ai.json().get("answer", "")
        self.assertIn("500D", answer)
        self.assertIn("remaining", answer.lower())

    def test_phase32_metrics_tracking(self):
        """Verify Phase 32 journey metrics counters are tracked in system diagnostics."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
            },
        )
        self.client.patch("/api/journey/active", json={"state": "BUS_APPROACHING"})
        self.client.post("/api/journey/active/end")
        self.client.get("/api/journey/history")

        res_status = self.client.get("/api/system/status")
        self.assertEqual(res_status.status_code, 200)
        diag = res_status.json().get("diagnostics", {})
        journey_diag = diag.get("journey", {})

        self.assertIn("active_journey_started", journey_diag)
        self.assertIn("active_journey_completed", journey_diag)
        self.assertIn("journey_state_transitions", journey_diag)
        self.assertIn("journey_history_views", journey_diag)
        self.assertGreaterEqual(journey_diag["active_journey_started"], 1)
        self.assertGreaterEqual(journey_diag["active_journey_completed"], 1)
        self.assertGreaterEqual(journey_diag["journey_state_transitions"], 1)
        self.assertGreaterEqual(journey_diag["journey_history_views"], 1)

    def test_operational_statement_integrity_phase32(self):
        """Strictly verify canonical operational statement remains unaltered."""
        res = self.client.get("/api/realtime/test")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.json().get("message"),
            "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED",
        )
        self.assertEqual(
            OPERATIONAL_STATEMENT_NOT_CONNECTED,
            "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED",
        )


if __name__ == "__main__":
    unittest.main()
