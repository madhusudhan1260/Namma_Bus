import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ai_service import AIService, IntentDetector, _SESSION_MEMORY
from app.services.personalization_service import personalization_service


class TestPhase28AssistantPersonalization(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _SESSION_MEMORY.clear()
        personalization_service.reset()

    def tearDown(self):
        _SESSION_MEMORY.clear()
        personalization_service.reset()

    def test_intent_detection_patterns(self):
        """Verify intent detection for diverse Bengaluru commuter queries."""
        cases = [
            ("Take me to the nearest stop", "nearest_stop"),
            ("Where is the closest stop?", "nearest_stop"),
            ("Is there any delay or alert on 500D?", "service_alerts"),
            ("Is Silk Board congested?", "service_alerts"),
            ("Is this ETA official or calculated?", "eta_source"),
            ("Is the feed fresh or stale?", "feed_freshness"),
            ("What is the fastest option to Whitefield?", "fastest_option"),
            ("What is the cheapest fare?", "cheapest_option"),
            ("Show me the stops for 500D", "bus_route"),
            ("Where is 500D right now?", "bus_location"),
            ("When will 500D arrive?", "bus_eta"),
            ("Are there empty seats on 500D?", "seat_availability"),
            ("How crowded is 500D?", "bus_occupancy"),
            ("How do I go from Silk Board to Majestic?", "journey_search"),
            ("Next bus to Majestic", "next_bus"),
            ("Hello, what can you do?", "general"),
        ]
        for query, expected_intent in cases:
            intent = IntentDetector.detect_intent(query)
            self.assertEqual(
                intent,
                expected_intent,
                f"Query '{query}' expected '{expected_intent}' but got '{intent}'",
            )

    def test_route_extraction_patterns(self):
        """Verify extraction of various Bangalore BMTC route formats."""
        self.assertEqual(IntentDetector.extract_route_number("Where is 500D?"), "500D")
        self.assertEqual(IntentDetector.extract_route_number("Track bus 500-D please"), "500D")
        self.assertEqual(IntentDetector.extract_route_number("When will 356 arrive?"), "356")
        self.assertEqual(IntentDetector.extract_route_number("Show stops of 201R"), "201R")
        self.assertEqual(IntentDetector.extract_route_number("Is KIA-8 on time?"), "KIA-8")
        self.assertEqual(IntentDetector.extract_route_number("Check G-2 occupancy"), "G-2")

    def test_multi_turn_pronoun_resolution(self):
        """Verify session memory preserves previous route when user asks follow-up with pronouns."""
        session_id = "test_commuter_session_1"

        # Turn 1: Ask about 500D location
        resp1 = self.client.post(
            "/api/ai/chat",
            json={"message": "Where is 500D?", "session_id": session_id},
        )
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1["route_number"], "500D")
        self.assertIn("500D", data1["answer"])

        # Turn 2: Follow-up with pronoun "Show me its stops"
        resp2 = self.client.post(
            "/api/ai/chat",
            json={"message": "Show me its stops", "session_id": session_id},
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2["route_number"], "500D")
        self.assertEqual(data2["intent"], "bus_route")
        self.assertIn("500D", data2["answer"])

        # Turn 3: Follow-up with "Are there seats on it?"
        resp3 = self.client.post(
            "/api/ai/chat",
            json={"message": "Are there seats on it?", "session_id": session_id},
        )
        self.assertEqual(resp3.status_code, 200)
        data3 = resp3.json()
        self.assertEqual(data3["route_number"], "500D")
        self.assertEqual(data3["intent"], "seat_availability")
        self.assertIn("seats", data3["answer"].lower())

    def test_ai_response_grounding_and_disclosures(self):
        """Verify AI response is grounded and includes simulated data disclosure when in mock mode."""
        resp = self.client.post(
            "/api/ai/chat",
            json={"message": "Where is 500D?"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("500D", data["answer"])
        # Check that simulated disclosure is present in mock mode
        self.assertTrue(
            "simulated data for hackathon demonstration" in data["answer"].lower()
            or "simulated" in data["answer"].lower()
        )
        # Verify structured card data payload
        self.assertIsNotNone(data["data"])
        self.assertEqual(data["data"]["routeNumber"], "500D")
        self.assertIn("etaMinutes", data["data"])

    def test_nearest_stop_query(self):
        """Verify nearest stop query is routed and answered cleanly."""
        resp = self.client.post(
            "/api/ai/chat",
            json={"message": "Take me to the nearest stop"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["intent"], "nearest_stop")
        self.assertIn("Silk Board", data["answer"])

    def test_journey_search_query(self):
        """Verify natural language journey search extracts endpoints and provides options."""
        resp = self.client.post(
            "/api/ai/chat",
            json={"message": "How do I go from Silk Board to Majestic?"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["intent"], "journey_search")
        self.assertTrue(any(w in data["answer"].lower() for w in ["bus", "buses", "matching", "option"]))
        self.assertIsNotNone(data["data"])

    def test_personalization_workflow(self):
        """Verify commuter preferences and saved journeys end-to-end."""
        # 1. Update preferences
        pref_resp = self.client.post(
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
        self.assertEqual(pref_resp.status_code, 200)
        prefs = pref_resp.json()
        self.assertEqual(prefs["language"], "KN")
        self.assertEqual(prefs["bus_preference"], "Vajra AC")
        self.assertTrue(prefs["accessibility_priority"])

        # 2. Add saved journey
        journey_resp = self.client.post(
            "/api/saved-journeys",
            json={
                "name": "Office ↔ Home Express",
                "origin": "Electronic City",
                "destination": "Silk Board",
                "preferred_bus_type": "Vajra AC",
                "preferred_departure_time": "06:00 PM",
                "notifications_enabled": True,
            },
        )
        self.assertEqual(journey_resp.status_code, 200)
        new_journey = journey_resp.json()
        self.assertEqual(new_journey["name"], "Office ↔ Home Express")

        # 3. List saved journeys and verify presence
        list_resp = self.client.get("/api/saved-journeys")
        self.assertEqual(list_resp.status_code, 200)
        journeys = list_resp.json()
        found = any(j["name"] == "Office ↔ Home Express" for j in journeys)
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()
