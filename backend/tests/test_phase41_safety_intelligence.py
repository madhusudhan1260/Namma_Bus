import asyncio
import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.services.safety_service import safety_service
from app.services.journey_share_service import journey_share_service
from app.services.metrics_service import metrics_service
from app.services.active_journey_service import active_journey_service
from app.models.transit import ActiveJourneyCreateRequest


class TestPhase41SafetyIntelligence(unittest.TestCase):
    """
    Verification suite for Phase 41: Smart Commuter Safety, Emergency & Journey Assistance.
    Tests safety status assessments, assistance requests and cancellations, safety checks,
    journey sharing with HMAC tokens and zero PII, nearby safety transit stops,
    evaluator demo overrides, AI assistant safety intents, and system status integration.
    """

    def setUp(self):
        self.client = TestClient(app)
        active_journey_service.reset()
        safety_service.reset()
        journey_share_service.reset()
        metrics_service.reset()

    def tearDown(self):
        active_journey_service.reset()
        safety_service.reset()
        journey_share_service.reset()
        metrics_service.reset()

    def test_safety_status_no_active_journey(self):
        res = self.client.get("/api/safety/status/no-journey-test")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["safety_status"], "NORMAL")
        self.assertIn("Safety status is based on the available transit data.", data["disclosure"])
        self.assertFalse(data["assistance_requested"])

    def test_safety_status_with_active_journey(self):
        req = ActiveJourneyCreateRequest(
            route_number="500D",
            origin="Central Silk Board Junction",
            destination="Hebbal",
            bus_id="bus-500d-1",
        )
        journey = asyncio.run(active_journey_service.start_journey(req))

        res = self.client.get(f"/api/safety/status/{journey.id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["journey_id"], journey.id)
        self.assertEqual(data["route_number"], "500D")
        self.assertIn(data["safety_status"], ["NORMAL", "ATTENTION"])
        self.assertIn("Safety status is based on the available transit data.", data["disclosure"])

    def test_safety_assistance_request_and_cancel(self):
        jid = "journey-test-safety-41"
        # 1. Request assistance
        res = self.client.post("/api/safety/assistance/request", json={
            "journey_id": jid,
            "reason": "Need transit guidance at interchange",
            "current_stop": "Silk Board"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["safety_status"], "ASSISTANCE_NEEDED")
        self.assertIn("Emergency assistance information is for guidance only.", data["disclosure"])

        # 2. Check safety status reflects assistance needed
        st_res = self.client.get(f"/api/safety/status/{jid}")
        self.assertEqual(st_res.status_code, 200)
        st_data = st_res.json()
        self.assertEqual(st_data["safety_status"], "ASSISTANCE_NEEDED")
        self.assertTrue(st_data["assistance_requested"])

        # 3. Check event was recorded
        evt_res = self.client.get(f"/api/safety/events/{jid}")
        self.assertEqual(evt_res.status_code, 200)
        events = evt_res.json()
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "USER_REQUESTED_ASSISTANCE")

        # 4. Cancel assistance
        cancel_res = self.client.post("/api/safety/assistance/cancel", json={"journey_id": jid})
        self.assertEqual(cancel_res.status_code, 200)
        cancel_data = cancel_res.json()
        self.assertTrue(cancel_data["success"])
        self.assertEqual(cancel_data["safety_status"], "NORMAL")

        # 5. Check safety status reverted
        st_res2 = self.client.get(f"/api/safety/status/{jid}")
        self.assertEqual(st_res2.status_code, 200)
        self.assertFalse(st_res2.json()["assistance_requested"])

    def test_safety_check_confirmation(self):
        jid = "journey-chk-123"
        res = self.client.post("/api/safety/check", json={"journey_id": jid})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["safety_status"], "NORMAL")
        self.assertIn("Safety status is based on the available transit data.", data["disclosure"])

        # Check safety event logged
        evt_res = self.client.get(f"/api/safety/events/{jid}")
        self.assertEqual(evt_res.status_code, 200)
        events = evt_res.json()
        self.assertTrue(any(e["event_type"] == "SAFETY_CHECK" for e in events))

    def test_journey_sharing_lifecycle(self):
        jid = "share-journey-abc"
        # 1. Start share (30 min)
        start_res = self.client.post("/api/safety/share/start", json={
            "journey_id": jid,
            "duration_minutes": 30
        })
        self.assertEqual(start_res.status_code, 200)
        s_data = start_res.json()
        self.assertEqual(s_data["share_state"], "ACTIVE")
        self.assertEqual(s_data["duration_minutes"], 30)
        token = s_data["share_token"]
        self.assertTrue(token and "." in token)
        self.assertIn("Your journey location is not shared automatically.", s_data["disclosure"])
        self.assertIn("Journey sharing is active only after explicit user confirmation.", s_data["confirmation_text"])

        # 2. Check share status
        st_res = self.client.get(f"/api/safety/share/status/{jid}")
        self.assertEqual(st_res.status_code, 200)
        st_data = st_res.json()
        self.assertEqual(st_data["share_state"], "ACTIVE")
        self.assertEqual(st_data["share_token"], token)
        self.assertGreaterEqual(st_data["remaining_minutes"], 29)

        # 3. Stop share
        stop_res = self.client.post("/api/safety/share/stop", json={"journey_id": jid})
        self.assertEqual(stop_res.status_code, 200)
        stop_data = stop_res.json()
        self.assertEqual(stop_data["share_state"], "CANCELLED")

        # 4. Check status reflects cancelled
        st_res2 = self.client.get(f"/api/safety/share/status/{jid}")
        self.assertEqual(st_res2.status_code, 200)
        self.assertEqual(st_res2.json()["share_state"], "CANCELLED")
        self.assertIsNone(st_res2.json()["share_token"])

    def test_journey_sharing_hmac_token_verification(self):
        jid = "sec-test-jid"
        res = asyncio.run(journey_share_service.start_share(
            journey_share_service._shares.get(jid) or
            type("Req", (), {"journey_id": jid, "duration_minutes": 15})()
        ))
        token = res.share_token

        # Valid token verification
        is_valid, payload, msg = journey_share_service.verify_token(token)
        self.assertTrue(is_valid)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["jid"], jid)
        # Assert zero PII in token payload
        self.assertNotIn("aadhaar", payload)
        self.assertNotIn("phone", payload)
        self.assertNotIn("name", payload)
        self.assertNotIn("email", payload)

        # Tampered token
        tampered = token[:-4] + "fake"
        is_valid_t, _, _ = journey_share_service.verify_token(tampered)
        self.assertFalse(is_valid_t)

    def test_nearby_safety_transit_stops(self):
        res = self.client.get("/api/safety/nearby?lat=12.9716&lon=77.5946")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(len(data["nearby_items"]), 1)
        self.assertIn("Live emergency service availability is unavailable.", data["emergency_service_disclosure"])
        self.assertIn("Safety status is based on the available transit data.", data["source_disclosure"])

    def test_safety_demo_override_scenarios(self):
        scenarios = [
            ("telemetry_lost", "OFFLINE"),
            ("missed_destination", "ATTENTION"),
            ("missed_transfer", "ATTENTION"),
            ("disruption_attention", "ATTENTION"),
            ("assistance_requested", "ASSISTANCE_NEEDED"),
            ("normal_journey", "NORMAL"),
        ]
        for sc, expected_status in scenarios:
            over_res = self.client.post("/api/safety/demo/override", json={"scenario": sc, "journey_id": "test-override-j"})
            self.assertEqual(over_res.status_code, 200)

            st_res = self.client.get("/api/safety/status/test-override-j")
            self.assertEqual(st_res.status_code, 200)
            st_data = st_res.json()
            self.assertEqual(st_data["safety_status"], expected_status)

    def test_ai_safety_intents(self):
        # Safety status intent
        res1 = self.client.post("/api/ai/chat", json={"message": "What is my safety status?"})
        self.assertEqual(res1.status_code, 200)
        self.assertIn("Safety status is based on the available transit data.", res1.json()["answer"])

        # Request assistance intent
        res2 = self.client.post("/api/ai/chat", json={"message": "I need help exiting the bus"})
        self.assertEqual(res2.status_code, 200)
        self.assertIn("Emergency assistance information is for guidance only.", res2.json()["answer"])

        # Emergency guidance intent
        res3 = self.client.post("/api/ai/chat", json={"message": "Call police or ambulance"})
        self.assertEqual(res3.status_code, 200)
        self.assertIn("Live emergency service availability is unavailable.", res3.json()["answer"])
        self.assertIn("112", res3.json()["answer"])

        # Journey sharing intent
        res4 = self.client.post("/api/ai/chat", json={"message": "How do I share my journey?"})
        self.assertEqual(res4.status_code, 200)
        self.assertIn("Your journey location is not shared automatically.", res4.json()["answer"])

    def test_system_status_and_demo_reset_includes_safety(self):
        # Request assistance to bump counter
        self.client.post("/api/safety/assistance/request", json={"journey_id": "j-sys-test"})

        # Get system status
        sys_res = self.client.get("/api/system/status")
        self.assertEqual(sys_res.status_code, 200)
        diag = sys_res.json()["diagnostics"]
        self.assertIn("safety", diag)
        self.assertGreaterEqual(diag["safety"]["assistance_requests"], 1)

        # Reset demo state
        reset_res = self.client.post("/api/demo/reset")
        self.assertEqual(reset_res.status_code, 200)

        # Verify safety metrics reset
        sys_res2 = self.client.get("/api/system/status")
        self.assertEqual(sys_res2.status_code, 200)
        self.assertEqual(sys_res2.json()["diagnostics"]["safety"]["assistance_requests"], 0)


if __name__ == "__main__":
    unittest.main()
