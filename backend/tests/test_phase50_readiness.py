import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.core import middleware
from app.services.crowd_service import crowd_service
from app.services.notification_service import notification_service

ALLOWED_SOURCES = {"VERIFIED_REALTIME", "GTFS_RT_ESTIMATE", "HISTORICAL_ESTIMATE", "SIMULATED", "UNAVAILABLE",
                   "OFFLINE_CACHED", "SYSTEM", "SANDBOX", "DEMO_CATALOG", "GTFS_STATIC",
                   "DEMO_VERIFICATION", "AUTHORIZED_VERIFICATION"}


class TestPhase50Readiness(unittest.TestCase):
    """Master spec Phase 50: truthful readiness report, deterministic reset and the end-to-end commuter flow."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def tearDown(self):
        self.client.post("/api/demo/reset")

    def test_readiness_is_truthful_in_demo_configuration(self):
        r = self.client.get("/api/system/readiness").json()
        self.assertFalse(r["realtime_connected"])
        self.assertFalse(r["real_payments_active"])
        self.assertFalse(r["real_identity_verification_active"])
        self.assertEqual(r["operational_statement"], "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED")
        mods = {m["module"]: m for m in r["modules"]}
        for name in ("backend", "gtfs_static", "gtfs_realtime", "map_vehicle_positions", "ai_assistant", "tickets", "payments",
                     "notifications", "accessibility", "crowd", "incidents", "predictions", "recommendations", "identity", "offline"):
            self.assertIn(name, mods)
            self.assertIn(mods[name]["source"], ALLOWED_SOURCES, name)
        self.assertEqual(mods["gtfs_realtime"]["status"], "UNAVAILABLE")
        self.assertEqual(mods["map_vehicle_positions"]["source"], "SIMULATED")
        self.assertIn("DEMO PAYMENT — NO REAL MONEY CHARGED", mods["payments"]["details"])
        self.assertIn("DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL", mods["tickets"]["details"])
        self.assertNotEqual(mods["identity"]["source"], "AUTHORIZED_VERIFICATION")

    def test_reset_clears_crowd_override_and_event_stream(self):
        crowd_service.set_simulation_override("HIGH")
        notification_service.create_event("service_alert", "temp", "temp")
        self.client.post("/api/demo/reset")
        self.assertIsNone(crowd_service.get_simulation_override())
        self.assertNotIn("temp", [e.title for e in notification_service.get_events()])

    def test_end_to_end_commuter_flow(self):
        c = self.client
        # Search → journey option
        search = c.post("/api/journey/search", json={"origin": "Central Silk Board", "destination": "Majestic"})
        self.assertEqual(search.status_code, 200)
        # Start journey → wait → bus approaching → on board → transfer → exit → destination
        start = c.post("/api/journey/active", json={"route_number": "500D", "bus_id": "bus-500d-1",
                                                    "origin": "Central Silk Board Junction", "destination": "Hebbal",
                                                    "initial_state": "WALKING_TO_STOP"})
        self.assertIn(start.status_code, (200, 201))
        for state in ("WAITING_FOR_BUS", "BUS_APPROACHING", "ON_BUS", "TRANSFER_APPROACHING", "TRANSFER_READY",
                      "WALKING_TO_CONNECTION", "WAITING_FOR_CONNECTION", "CONNECTING_BUS_APPROACHING", "TRANSFER_COMPLETED",
                      "GET_READY_TO_EXIT", "DESTINATION_REACHED", "COMPLETED"):
            res = c.patch("/api/journey/active", json={"state": state})
            self.assertEqual(res.status_code, 200, f"{state}: {res.text}")
        events = {n.get("event_type") for n in c.get("/api/notifications").json()}
        for ev in ("BUS_APPROACHING", "TRANSFER_APPROACHING", "TRANSFER_READY", "CONNECTING_BUS_APPROACHING", "GET_READY_TO_EXIT", "DESTINATION_REACHED"):
            self.assertIn(ev, events)
        # Ticket via payment → conductor validation
        pid = c.post("/api/payment/create", json={"route_number": "500D", "source": "Central Silk Board", "destination": "Hebbal"}).json()["payment_id"]
        c.post("/api/payment/verify", json={"payment_id": pid, "sandbox_outcome": "PAYMENT_SUCCESS"})
        ticket = c.post("/api/tickets/purchase", json={"payment_id": pid}).json()
        verdict = c.post("/api/tickets/verify", json={"qr_payload_or_code": ticket["qr_payload"], "conductor_route_number": "500D"}).json()
        self.assertTrue(verdict["valid"])
        self.assertTrue(c.post(f"/api/tickets/{ticket['ticket_id']}/use").json()["valid"])


if __name__ == "__main__":
    unittest.main()
