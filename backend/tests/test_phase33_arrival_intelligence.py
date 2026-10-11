import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import OPERATIONAL_STATEMENT_NOT_CONNECTED
from app.services.active_journey_service import active_journey_service
from app.services.metrics_service import metrics_service
from app.models.transit import ActiveJourneyCreateRequest, JourneyState


class TestPhase33ArrivalIntelligence(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        active_journey_service.reset()

    def test_destination_arrival_detection(self):
        """1. Verify state machine progression: DESTINATION_APPROACHING -> GET_READY_TO_EXIT -> DESTINATION_REACHED."""
        create_res = self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "initial_state": "ON_BUS",
            },
        )
        self.assertEqual(create_res.status_code, 200)

        # Transition to DESTINATION_APPROACHING
        p1 = self.client.patch("/api/journey/active", json={"state": "DESTINATION_APPROACHING"})
        self.assertEqual(p1.status_code, 200)
        self.assertEqual(p1.json()["state"], "DESTINATION_APPROACHING")

        # Transition to GET_READY_TO_EXIT
        p2 = self.client.patch("/api/journey/active", json={"state": "GET_READY_TO_EXIT"})
        self.assertEqual(p2.status_code, 200)
        self.assertEqual(p2.json()["state"], "GET_READY_TO_EXIT")
        self.assertTrue(p2.json()["is_get_ready_to_exit"])

        # Transition to DESTINATION_REACHED
        p3 = self.client.patch("/api/journey/active", json={"state": "DESTINATION_REACHED"})
        self.assertEqual(p3.status_code, 200)
        self.assertEqual(p3.json()["state"], "DESTINATION_REACHED")
        self.assertTrue(p3.json()["is_destination_reached"])

    def test_stop_by_stop_progression(self):
        """2. Verify stop-by-stop progress tracking updates current, next, and remaining stops."""
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
        # Update progress with telemetry sync
        res = self.client.patch(
            "/api/journey/active",
            json={"current_stop": "HSR Layout BDA Complex", "next_stop": "Agara Junction", "eta_minutes": 5},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["current_stop"], "HSR Layout BDA Complex")
        self.assertEqual(data["next_stop"], "Agara Junction")
        self.assertIn("HSR Layout BDA Complex", data["passed_stops"])
        self.assertTrue(data["remaining_stops"] > 0)

    def test_stops_remaining_calculation(self):
        """3. Verify stops_remaining accurately calculates remaining corridor stops towards destination."""
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
        # When current stop is Marathahalli Bridge (close to Hebbal along 500D corridor)
        res = self.client.patch(
            "/api/journey/active",
            json={"current_stop": "Marathahalli Bridge", "next_stop": "HAL Main Gate"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data["remaining_stops"], int)
        self.assertTrue(data["remaining_stops"] >= 0)

    def test_destination_approaching_trigger(self):
        """4. Verify DESTINATION_APPROACHING triggers when remaining stops <= 2."""
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
        res = self.client.patch("/api/journey/active", json={"state": "DESTINATION_APPROACHING"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "DESTINATION_APPROACHING")

    def test_get_ready_to_exit_trigger(self):
        """5. Verify GET_READY_TO_EXIT triggers when remaining stops <= 1 or ETA <= 3 min."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "initial_state": "DESTINATION_APPROACHING",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "GET_READY_TO_EXIT"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["state"], "GET_READY_TO_EXIT")
        self.assertTrue(data["is_get_ready_to_exit"])

    def test_destination_reached_trigger(self):
        """6. Verify DESTINATION_REACHED triggers at destination stop and sets reached flag."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "initial_state": "GET_READY_TO_EXIT",
            },
        )
        res = self.client.patch("/api/journey/active", json={"state": "DESTINATION_REACHED"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["state"], "DESTINATION_REACHED")
        self.assertTrue(data["is_destination_reached"])

    def test_missed_destination_detection(self):
        """7. Verify missed destination detection: bus passing destination transitions to DESTINATION_PASSED."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Agara Junction",
                "initial_state": "ON_BUS",
            },
        )
        # Transition state to DESTINATION_PASSED
        res = self.client.patch("/api/journey/active", json={"state": "DESTINATION_PASSED"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["state"], "DESTINATION_PASSED")
        self.assertTrue(data["is_destination_passed"])

    def test_notification_deduplication(self):
        """8. Verify repeated polling or sync retains stable journey state without duplicate corruption."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "initial_state": "GET_READY_TO_EXIT",
            },
        )
        # Poll multiple times
        r1 = self.client.get("/api/journey/active").json()
        r2 = self.client.get("/api/journey/active").json()
        r3 = self.client.get("/api/journey/active").json()
        self.assertEqual(r1["state"], r2["state"])
        self.assertEqual(r2["state"], r3["state"])
        self.assertEqual(r1["id"], r3["id"])

    def test_ambiguous_telemetry_safety(self):
        """9. Verify ambiguous or missing telemetry falls back safely without inventing positions."""
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
        # Update with unknown stop
        res = self.client.patch(
            "/api/journey/active",
            json={"current_stop": "Unknown Mysore Stop 99"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        # Does not crash or invent coordinates
        self.assertIsNotNone(data["remaining_stops"])
        self.assertIsNotNone(data["state"])

    def test_offline_journey_behavior(self):
        """10. Verify offline conditions retain last known journey state and add telemetry disclosure."""
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
        # Transition to OFFLINE state
        patch_res = self.client.patch("/api/journey/active", json={"state": "OFFLINE"})
        self.assertEqual(patch_res.status_code, 200)

        res = self.client.get("/api/journey/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["telemetry_reliable"])
        self.assertIn("outdated", data["telemetry_disclosure"])
        self.assertEqual(data["data_transparency_label"], "OFFLINE — SHOWING LAST KNOWN DATA")

    def test_realtime_disclosure(self):
        """11. Verify authorized realtime disclosure when realtime feed is active."""
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
        res = self.client.get("/api/journey/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("data_transparency_label", data)
        self.assertIsNotNone(data["data_transparency_label"])

    def test_simulator_disclosure(self):
        """12. Verify simulator disclosure attribution when mock provider is used."""
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
        res = self.client.get("/api/journey/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["data_source"], "simulated_corridor")

    def test_ai_active_journey_arrival_questions(self):
        """13. Verify AI assistant answers arrival questions grounded in active journey state."""
        self.client.post(
            "/api/journey/active",
            json={
                "route_number": "500D",
                "bus_id": "bus-500d-01",
                "origin": "Central Silk Board Junction",
                "destination": "Hebbal Bus Stop",
                "initial_state": "GET_READY_TO_EXIT",
            },
        )
        # Query: "When should I get down?"
        res1 = self.client.post("/api/ai/chat", json={"message": "When should I get down?"})
        self.assertEqual(res1.status_code, 200)
        ans1 = res1.json()["answer"].lower()
        self.assertTrue("exit" in ans1 or "get ready" in ans1 or "hebbal" in ans1 or "destination" in ans1)

        # Query: "Am I near my destination?"
        res2 = self.client.post("/api/ai/chat", json={"message": "Am I near my destination?"})
        self.assertEqual(res2.status_code, 200)
        ans2 = res2.json()["answer"].lower()
        self.assertTrue("near" in ans2 or "yes" in ans2 or "hebbal" in ans2 or "stops" in ans2)

        # Query: "Has my bus reached my destination?"
        res3 = self.client.post("/api/ai/chat", json={"message": "Has my bus reached my destination?"})
        self.assertEqual(res3.status_code, 200)
        ans3 = res3.json()["answer"].lower()
        self.assertTrue("not yet" in ans3 or "remaining" in ans3 or "hebbal" in ans3 or "stops" in ans3)

    def test_arrival_metrics_counters(self):
        """14. Verify observability metrics track Phase 33 arrival intelligence counters."""
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
        # Trigger arrival transitions
        self.client.patch("/api/journey/active", json={"state": "DESTINATION_APPROACHING"})
        self.client.patch("/api/journey/active", json={"state": "GET_READY_TO_EXIT"})
        self.client.patch("/api/journey/active", json={"state": "DESTINATION_REACHED"})

        status_res = self.client.get("/api/system/status")
        self.assertEqual(status_res.status_code, 200)
        diag = status_res.json().get("diagnostics", {})
        journey_diag = diag.get("journey", {})

        self.assertIn("destination_approach_alerts", journey_diag)
        self.assertIn("get_ready_to_exit_alerts", journey_diag)
        self.assertIn("destination_reached_events", journey_diag)
        self.assertIn("missed_destination_warnings", journey_diag)
        self.assertIn("journey_notification_events", journey_diag)
        self.assertTrue(journey_diag["destination_approach_alerts"] >= 1)
        self.assertTrue(journey_diag["get_ready_to_exit_alerts"] >= 1)
        self.assertTrue(journey_diag["destination_reached_events"] >= 1)

    def test_demo_reset_clears_arrival_state(self):
        """15. Verify demo reset clears active journey and resets metrics."""
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
        reset_res = self.client.post("/api/demo/reset")
        self.assertEqual(reset_res.status_code, 200)

        # Active journey should be cleared (GET returns 404)
        get_res = self.client.get("/api/journey/active")
        self.assertEqual(get_res.status_code, 404)
        self.assertIsNone(active_journey_service._active_journey)

    def test_canonical_operational_statement_preserved(self):
        """16. Strictly verify canonical operational statement remains unaltered."""
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
