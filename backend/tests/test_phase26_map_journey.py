import unittest
from fastapi.testclient import TestClient
from backend.app.main import app


class TestPhase26MapJourney(unittest.TestCase):
    """
    Phase 26 automated verification:
    - Stop intelligence, arrivals, and feed disclosures.
    - Journey planner enriched metadata without subjective 'Best Route'.
    - Recommendation 5-dimension objective categories.
    - Nearby stop intelligence with walking proximity.
    """

    def setUp(self):
        self.client = TestClient(app)

    def test_stop_details_and_arrivals(self):
        """Verify GET /api/stops/{stop_id}/details returns structured stop intelligence."""
        res = self.client.get("/api/stops/silk-board-junction/details")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["stop_id"], "silk-board-junction")
        self.assertIn("Silk Board", data["name"])
        self.assertIsInstance(data["serving_routes"], list)
        self.assertGreater(len(data["serving_routes"]), 0)
        self.assertIsInstance(data["upcoming_arrivals"], list)
        self.assertGreater(len(data["upcoming_arrivals"]), 0)

        # Check arrival structure
        first_arrival = data["upcoming_arrivals"][0]
        self.assertIn("route_number", first_arrival)
        self.assertIn("destination", first_arrival)
        self.assertIn("bus_type", first_arrival)
        self.assertIn("eta_minutes", first_arrival)
        self.assertIn(first_arrival["eta_source"], ["Calculated Estimate", "Official Trip Update"])

        # Check honest data disclosure when unconfigured
        self.assertEqual(data["feed_disclosure"], "Realtime BMTC feed not connected.")

    def test_stop_arrivals_alias_endpoint(self):
        """Verify GET /api/stops/{stop_id}/arrivals is an accessible alias."""
        res = self.client.get("/api/stops/silk-board-junction/arrivals")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["stop_id"], "silk-board-junction")
        self.assertGreater(len(data["upcoming_arrivals"]), 0)

    def test_journey_search_metadata_and_walking_metrics(self):
        """Verify POST /api/journey/search returns all required metadata without subjective best route."""
        payload = {
            "origin": "Central Silk Board Junction",
            "destination": "Majestic",
        }
        res = self.client.post("/api/journey/search", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("options", data)
        self.assertGreater(len(data["options"]), 0)

        opt = data["options"][0]
        self.assertIn("route_number", opt)
        self.assertIn("bus_type", opt)
        self.assertIn("origin_stop", opt)
        self.assertIn("destination_stop", opt)
        self.assertIn("eta_minutes", opt)
        self.assertIn("journey_duration_minutes", opt)
        self.assertIn("fare_rupees", opt)
        self.assertIn("number_of_stops", opt)
        self.assertIn("transfers", opt)
        self.assertIn("available_seats", opt)
        self.assertIn("occupancy_percentage", opt)
        self.assertIn("eta_source", opt)
        self.assertIn("data_source", opt)
        self.assertIn("freshness", opt)
        self.assertIn("walking_distance_meters", opt)
        self.assertIn("walking_duration_minutes", opt)
        self.assertIn("service_alerts_count", opt)

        # Confirm no subjective "best_route" field
        self.assertNotIn("is_best_route", opt)
        self.assertNotIn("best_route_rank", opt)

    def test_journey_recommend_five_objective_dimensions(self):
        """Verify POST /api/journey/recommend returns 5 objective dimensions without subjective bias."""
        payload = {
            "origin": "Central Silk Board Junction",
            "destination": "Majestic",
        }
        res = self.client.post("/api/journey/recommend", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("winners", data)
        categories = [w["category"] for w in data["winners"]]
        expected = ["Fastest", "Lowest Fare", "More Seats", "Fewest Stops", "Least Transfers"]
        for exp in expected:
            self.assertIn(exp, categories)

    def test_nearby_stops_enriched_intelligence(self):
        """Verify GET /api/stops/nearby returns proximity distance and serving routes."""
        res = self.client.get("/api/stops/nearby?lat=12.9176&lon=77.6238&radius_km=3.0")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

        stop = data[0]
        self.assertIn("stop_id", stop)
        self.assertIn("name", stop)
        self.assertIn("distance_meters", stop)
        self.assertIn("routes", stop)
        self.assertIn("next_bus_route", stop)
        self.assertGreaterEqual(stop["distance_meters"], 0)


if __name__ == "__main__":
    unittest.main()
