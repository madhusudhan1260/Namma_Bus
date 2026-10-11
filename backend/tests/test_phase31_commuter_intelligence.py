import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import OPERATIONAL_STATEMENT_NOT_CONNECTED


class TestPhase31CommuterIntelligence(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_smart_live_trip_view_bus_fields(self):
        """Verify Bus API and model populate following_stop and distance_to_next_stop_km."""
        res = self.client.get("/api/buses")
        self.assertEqual(res.status_code, 200)
        buses = res.json()
        self.assertGreater(len(buses), 0)
        bus = buses[0]
        self.assertIn("following_stop", bus)
        self.assertIn("distance_to_next_stop_km", bus)
        if bus["following_stop"]:
            self.assertIsInstance(bus["following_stop"], str)
            self.assertNotEqual(bus["following_stop"], bus["next_stop"])
        if bus["distance_to_next_stop_km"] is not None:
            self.assertGreaterEqual(bus["distance_to_next_stop_km"], 0.0)

    def test_multi_leg_walking_and_transit_journey_summary(self):
        """Verify Journey Search computes multi-leg walking and transit segments."""
        res = self.client.post(
            "/api/journey/search",
            json={"origin": "Central Silk Board Junction", "destination": "Majestic (Kempegowda Bus Station)"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        opts = data.get("options", [])
        self.assertGreater(len(opts), 0)
        opt = opts[0]
        self.assertIn("walk_to_stop_meters", opt)
        self.assertIn("walk_to_stop_minutes", opt)
        self.assertIn("bus_ride_minutes", opt)
        self.assertIn("walk_from_stop_meters", opt)
        self.assertIn("walk_from_stop_minutes", opt)
        self.assertGreater(opt["walk_to_stop_meters"], 0)
        self.assertGreater(opt["walk_to_stop_minutes"], 0)
        self.assertGreater(opt["bus_ride_minutes"], 0)
        self.assertGreater(opt["walk_from_stop_meters"], 0)
        self.assertGreater(opt["walk_from_stop_minutes"], 0)

    def test_disruption_aware_journey_planning(self):
        """Verify journeys crossing disrupted routes flag has_disruption without fabricating delays."""
        res = self.client.post(
            "/api/journey/search",
            json={"origin": "Central Silk Board Junction", "destination": "Majestic (Kempegowda Bus Station)"},
        )
        self.assertEqual(res.status_code, 200)
        opts = res.json().get("options", [])
        disrupted_opts = [o for o in opts if o.get("has_disruption")]
        if disrupted_opts:
            self.assertTrue(disrupted_opts[0]["has_disruption"])
            self.assertTrue(bool(disrupted_opts[0].get("disruption_alert_id")))

    def test_service_alerts_source_attribution_and_mode(self):
        """Verify ServiceAlerts distinguish official feeds from demo corridor advisories."""
        res = self.client.get("/api/alerts")
        self.assertEqual(res.status_code, 200)
        alerts = res.json()
        self.assertGreater(len(alerts), 0)
        for alert in alerts:
            self.assertIn("source_type", alert)
            self.assertIn("data_mode", alert)
            self.assertIn(alert["source_type"], ["official_feed", "demo_advisory", "advisory_demo"])
            self.assertIn(alert["data_mode"], ["simulated", "realtime"])

    def test_ai_trip_context_stops_remaining(self):
        """Verify AI assistant answers stops_remaining query grounded in corridor context."""
        ctx = {
            "bus_id": "bus-500d-01",
            "route_number": "500D",
            "destination": "Hebbal",
            "next_stop": "Marathahalli",
            "eta_minutes": 14,
        }
        res = self.client.post(
            "/api/ai/chat",
            json={"message": "How many stops are remaining on this bus?", "transit_context": ctx},
        )
        self.assertEqual(res.status_code, 200)
        answer = res.json().get("answer", "")
        self.assertIn("remaining", answer.lower())
        self.assertIn("500D", answer)

    def test_ai_trip_context_destination_eta(self):
        """Verify AI assistant answers destination_eta with transparent calculated disclosure."""
        ctx = {
            "bus_id": "bus-500d-01",
            "route_number": "500D",
            "destination": "Hebbal",
            "next_stop": "Marathahalli",
            "eta_minutes": 14,
        }
        res = self.client.post(
            "/api/ai/chat",
            json={"message": "When will this bus reach destination?", "transit_context": ctx},
        )
        self.assertEqual(res.status_code, 200)
        answer = res.json().get("answer", "")
        self.assertIn("reach Hebbal", answer)
        self.assertIn("estimate", answer.lower())

    def test_nearby_stops_intelligence_endpoint(self):
        """Verify GET /api/stops/nearby provides walking distances and transit actions."""
        res = self.client.get("/api/stops/nearby?lat=12.9176&lon=77.6238&radius_km=3.0")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreater(len(data), 0)
        stop = data[0]
        self.assertIn("stop_id", stop)
        self.assertIn("name", stop)
        self.assertIn("distance_meters", stop)
        self.assertIn("routes", stop)

    def test_phase31_metrics_counters(self):
        """Verify active_trip_views, nearby_stop_queries, and ai_trip_context_queries are tracked."""
        self.client.get("/api/stops/nearby?lat=12.9176&lon=77.6238")
        self.client.get("/api/buses/bus-500d-01")
        self.client.post("/api/ai/chat", json={"message": "How many stops remaining on this bus?"})

        status_res = self.client.get("/api/system/status")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        diag = status_data.get("diagnostics", {})
        transit_diag = diag.get("transit", {})
        ai_diag = diag.get("ai", {})
        self.assertIn("active_trip_views", transit_diag)
        self.assertIn("nearby_stop_queries", transit_diag)
        self.assertIn("ai_trip_context_queries", ai_diag)
        self.assertGreaterEqual(transit_diag["active_trip_views"], 1)
        self.assertGreaterEqual(transit_diag["nearby_stop_queries"], 1)

    def test_operational_transparency_statement_integrity(self):
        """Strictly verify the canonical operational transparency statement is preserved intact."""
        res = self.client.get("/api/realtime/test")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        expected = "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED"
        self.assertEqual(data.get("message"), expected)
        self.assertEqual(OPERATIONAL_STATEMENT_NOT_CONNECTED, expected)


if __name__ == "__main__":
    unittest.main()
