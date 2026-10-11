import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.services.personalization_service import personalization_service


class TestPhase25Personalization(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        personalization_service.reset()

    def tearDown(self):
        personalization_service.reset()

    def test_get_preferences_default(self):
        res = self.client.get("/api/preferences")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["language"], "EN")
        self.assertEqual(data["bus_preference"], "All")
        self.assertTrue(data["saved_journeys_enabled"])

    def test_update_preferences(self):
        update_payload = {
            "language": "KN",
            "bus_preference": "Vajra AC",
            "accessibility_priority": True,
            "frequent_routes_enabled": True,
            "arrival_notifications_enabled": True,
            "service_alerts_enabled": True,
            "saved_journeys_enabled": True,
        }
        res = self.client.post("/api/preferences", json=update_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["language"], "KN")
        self.assertEqual(data["bus_preference"], "Vajra AC")
        self.assertTrue(data["accessibility_priority"])

    def test_get_saved_journeys(self):
        res = self.client.get("/api/saved-journeys")
        self.assertEqual(res.status_code, 200)
        journeys = res.json()
        self.assertGreaterEqual(len(journeys), 3)
        names = [j["name"] for j in journeys]
        self.assertIn("Home → Majestic", names)

    def test_create_and_delete_saved_journey(self):
        create_payload = {
            "name": "Gym → Home",
            "origin": "Koramangala 5th Block",
            "destination": "HSR Layout Sector 2",
            "preferred_bus_type": "BMTC Ordinary",
            "preferred_departure_time": "07:30 PM",
            "notifications_enabled": True,
        }
        res = self.client.post("/api/saved-journeys", json=create_payload)
        self.assertEqual(res.status_code, 200)
        created = res.json()
        self.assertEqual(created["name"], "Gym → Home")
        self.assertIn("id", created)
        jid = created["id"]

        # Delete it
        del_res = self.client.delete(f"/api/saved-journeys/{jid}")
        self.assertEqual(del_res.status_code, 200)

        # Confirm deleted
        del_again = self.client.delete(f"/api/saved-journeys/{jid}")
        self.assertEqual(del_again.status_code, 404)

    def test_get_favorite_routes(self):
        res = self.client.get("/api/favorite-routes")
        self.assertEqual(res.status_code, 200)
        favs = res.json()
        route_nums = [f["route_number"] for f in favs]
        self.assertIn("500D", route_nums)
        self.assertIn("356", route_nums)

    def test_add_and_remove_favorite_route(self):
        add_payload = {
            "route_number": "201R",
            "destination": "Banashankari TTMC",
            "bus_type": "BMTC Ordinary",
        }
        res = self.client.post("/api/favorite-routes", json=add_payload)
        self.assertEqual(res.status_code, 200)
        fav = res.json()
        self.assertEqual(fav["route_number"], "201R")

        # Verify present
        favs = self.client.get("/api/favorite-routes").json()
        self.assertIn("201R", [f["route_number"] for f in favs])

        # Delete
        del_res = self.client.delete("/api/favorite-routes/201R")
        self.assertEqual(del_res.status_code, 200)

    def test_get_notifications_and_filtering(self):
        res = self.client.get("/api/notifications")
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertGreaterEqual(len(items), 4)

        # Filter by ARRIVALS
        arrivals = self.client.get("/api/notifications?category=ARRIVALS").json()
        self.assertTrue(all(i["category"] == "ARRIVALS" for i in arrivals))

        # Filter by SERVICE ALERTS
        alerts = self.client.get("/api/notifications?category=SERVICE%20ALERTS").json()
        self.assertTrue(all(i["category"] == "SERVICE ALERTS" for i in alerts))

    def test_mark_notification_read(self):
        notifs = self.client.get("/api/notifications").json()
        target = notifs[0]
        nid = target["id"]

        res = self.client.patch(f"/api/notifications/{nid}/read")
        self.assertEqual(res.status_code, 200)

        # Confirm read
        updated_notifs = self.client.get("/api/notifications").json()
        updated_target = next(n for n in updated_notifs if n["id"] == nid)
        self.assertTrue(updated_target["read"])

    def test_create_arrival_reminder(self):
        reminder_payload = {
            "route_number": "500D",
            "stop_name": "Silk Board",
            "minutes_before": 10,
            "target_eta_minutes": 18,
        }
        res = self.client.post("/api/notifications/reminders", json=reminder_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["route_number"], "500D")
        self.assertEqual(data["minutes_before"], 10)
        self.assertIn("Arrival reminders use available transit data", data["disclosure"])

        # Check that an ARRIVALS notification was created
        notifs = self.client.get("/api/notifications?category=ARRIVALS").json()
        self.assertTrue(any("Reminder Set for 500D" in n["title"] for n in notifs))

    def test_demo_reset_restores_personalization(self):
        # Mutate preferences
        self.client.post("/api/preferences", json={
            "language": "KN",
            "bus_preference": "Ordinary",
            "accessibility_priority": True,
            "frequent_routes_enabled": False,
            "arrival_notifications_enabled": False,
            "service_alerts_enabled": False,
            "saved_journeys_enabled": False,
        })
        # Reset demo
        res = self.client.post("/api/demo/reset")
        self.assertEqual(res.status_code, 200)

        # Confirm preferences restored to default
        prefs = self.client.get("/api/preferences").json()
        self.assertEqual(prefs["language"], "EN")
        self.assertEqual(prefs["bus_preference"], "All")
        self.assertTrue(prefs["saved_journeys_enabled"])


if __name__ == "__main__":
    unittest.main()
