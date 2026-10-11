import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.services.metrics_service import metrics_service
from app.services.ticket_service import ticket_service
from app.services.personalization_service import personalization_service


class TestPhase30ProductionObservability(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_expanded_system_status_observability(self):
        """Verify GET /api/system/status exposes all required municipal subsystems and metrics."""
        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Check top-level municipal status fields
        self.assertEqual(data["overall_status"], "Active")
        self.assertEqual(data["data_mode"], "simulated")
        self.assertIn(data["feed_status"], ["connected", "unconfigured", "simulated"])
        self.assertFalse(data["stale"])
        self.assertIsNotNone(data["uptime_seconds"])
        self.assertIsNotNone(data["latency_stats"])

        # Check Phase 30 top-level metrics
        self.assertGreaterEqual(data.get("tracked_vehicles", 0), 5)
        self.assertGreaterEqual(data.get("gtfs_routes", 0), 4)
        self.assertGreaterEqual(data.get("gtfs_stops", 0), 32)
        self.assertIn("p95_latency_ms", data)

        # Check all required engine modules are reported
        module_names = [m["name"] for m in data["modules"]]
        expected_modules = [
            "Backend",
            "Transit Data",
            "GTFS",
            "Realtime Feed",
            "ETA Engine",
            "Crowd Prediction",
            "AI Assistant",
            "Ticket Engine",
            "Conductor Mode",
            "Alert Engine",
            "Recommendation Engine",
            "Identity Engine",
            "Notification Engine",
            "VehiclePositions",
            "TripUpdates",
            "ServiceAlerts",
        ]
        for mod in expected_modules:
            self.assertIn(mod, module_names, f"Module '{mod}' missing from system status modules list")

        # Security check: Zero secrets in output
        response_str = str(data).lower()
        forbidden_secret_tokens = ["api_key", "secret", "password", "private_key", "token_secret"]
        for token in forbidden_secret_tokens:
            self.assertNotIn(token, response_str)

    def test_performance_latency_tracking(self):
        """Verify performance latency tracking across major transit endpoints."""
        # Execute major transit endpoints to generate metrics
        self.client.get("/api/buses")
        self.client.get("/api/buses/bus-500d-01/location")
        self.client.post(
            "/api/journey/search",
            json={"origin": "Central Silk Board Junction", "destination": "Majestic (Kempegowda Bus Station)"},
        )
        self.client.post(
            "/api/ai/chat",
            json={"message": "Where is 500D?"},
        )
        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)

        latency_stats = res.json()["latency_stats"]
        self.assertIn("avg_ms", latency_stats)
        self.assertIn("p95_ms", latency_stats)
        self.assertIn("min_ms", latency_stats)
        self.assertIn("max_ms", latency_stats)
        self.assertGreaterEqual(latency_stats["max_ms"], 0.0)

    def test_deterministic_demo_reset(self):
        """Verify POST /api/demo/reset restores all subsystems to pristine deterministic state."""
        # Mutate ticket state
        self.client.post(
            "/api/tickets",
            json={
                "route_number": "500D",
                "source": "Central Silk Board Junction",
                "destination": "Majestic (Kempegowda Bus Station)",
            },
        )

        # Mutate preferences
        self.client.post(
            "/api/preferences",
            json={
                "language": "KN",
                "bus_preference": "Vajra AC",
                "accessibility_priority": True,
                "frequent_routes_enabled": True,
                "arrival_notifications_enabled": True,
                "service_alerts_enabled": True,
                "saved_journeys_enabled": True,
            },
        )

        # Trigger reset
        reset_res = self.client.post("/api/demo/reset")
        self.assertEqual(reset_res.status_code, 200)
        self.assertEqual(reset_res.json()["status"], "success")

        # Verify tickets reset to seeded count (3)
        tickets = self.client.get("/api/tickets/history").json()
        self.assertEqual(len(tickets), 3)

        # Verify preferences reset to default
        prefs = self.client.get("/api/preferences").json()
        self.assertEqual(prefs["language"], "EN")
        self.assertEqual(prefs["bus_preference"], "All")


if __name__ == "__main__":
    unittest.main()
