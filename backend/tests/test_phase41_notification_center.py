import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.core import middleware
from app.services.notification_center_service import notification_center_service, BURST_LIMIT
from app.services.active_journey_service import active_journey_service


class TestPhase41NotificationCenter(unittest.TestCase):
    """Master spec Phase 41: notification center — dedup, burst cap, expiry, read state, endpoints, journey events."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def tearDown(self):
        self.client.post("/api/demo/reset")

    def test_seeded_items_keep_legacy_shape_and_are_labelled(self):
        items = self.client.get("/api/notifications").json()
        self.assertGreaterEqual(len(items), 4)
        for n in items:
            for key in ("id", "timestamp", "category", "title", "description", "read", "severity"):
                self.assertIn(key, n)
            self.assertIn(n["source"], ("SIMULATED", "SYSTEM"))

    def test_sliding_window_deduplication(self):
        first, created = notification_center_service.publish("ROUTE_DELAY", "Delay on 500D", "x", route_number="500D", dedup_key="k1", dedup_window_seconds=60)
        self.assertTrue(created)
        _, created2 = notification_center_service.publish("ROUTE_DELAY", "Delay on 500D", "x", route_number="500D", dedup_key="k1", dedup_window_seconds=60)
        self.assertFalse(created2)
        self.assertEqual(notification_center_service.get_stats()["suppressed_duplicates"], 1)
        # zero window allows a new item
        _, created3 = notification_center_service.publish("ROUTE_DELAY", "Delay on 500D", "x", dedup_key="k1", dedup_window_seconds=0)
        self.assertTrue(created3)

    def test_burst_cap_prevents_spam_but_allows_critical(self):
        for i in range(BURST_LIMIT + 5):
            notification_center_service.publish("CROWD_CHANGE", f"c{i}", "x", dedup_key=f"b{i}")
        stats = notification_center_service.get_stats()
        self.assertEqual(stats["suppressed_burst"], 5)
        _, created = notification_center_service.publish("TRANSFER_MISSED", "Transfer missed", "x", dedup_key="crit")
        self.assertTrue(created)

    def test_expired_items_hidden(self):
        item, _ = notification_center_service.publish("SYSTEM", "Old", "x", dedup_key="exp", ttl_minutes=-1)
        ids = [n["id"] for n in self.client.get("/api/notifications").json()]
        self.assertNotIn(item.id, ids)
        ids_all = [n["id"] for n in self.client.get("/api/notifications?include_expired=true").json()]
        self.assertIn(item.id, ids_all)

    def test_unread_read_all_delete_endpoints(self):
        unread = self.client.get("/api/notifications/unread").json()
        self.assertEqual(unread["unread_count"], len(unread["items"]))
        self.assertGreater(unread["unread_count"], 0)
        nid = unread["items"][0]["id"]
        self.assertEqual(self.client.post(f"/api/notifications/{nid}/read").status_code, 200)
        self.assertEqual(self.client.get("/api/notifications/unread").json()["unread_count"], unread["unread_count"] - 1)
        # legacy PATCH still works
        self.assertEqual(self.client.patch(f"/api/notifications/{nid}/read").status_code, 200)
        res = self.client.post("/api/notifications/read-all").json()
        self.assertGreaterEqual(res["marked_read"], 0)
        self.assertEqual(self.client.get("/api/notifications/unread").json()["unread_count"], 0)
        self.assertEqual(self.client.delete(f"/api/notifications/{nid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/notifications/{nid}").status_code, 404)
        self.assertEqual(self.client.post("/api/notifications/nope/read").status_code, 404)

    def test_journey_transition_emits_single_notification(self):
        self.client.post("/api/journey/active", json={
            "route_number": "500D", "bus_id": "bus-500d-1", "origin": "Central Silk Board Junction", "destination": "Hebbal",
        })
        self.client.patch("/api/journey/active", json={"state": "BUS_APPROACHING"})
        self.client.get("/api/journey/active")
        self.client.get("/api/journey/active")
        items = [n for n in self.client.get("/api/notifications").json() if n.get("event_type") == "BUS_APPROACHING"]
        self.assertEqual(len(items), 1)
        self.assertIn(items[0]["source"], ("SIMULATED", "GTFS_RT_ESTIMATE"))
        self.assertEqual(items[0]["category"], "ARRIVALS")

    def test_demo_reset_restores_notification_state(self):
        notification_center_service.publish("SYSTEM", "temp", "x", dedup_key="tmp")
        self.client.post("/api/demo/reset")
        titles = [n["title"] for n in self.client.get("/api/notifications").json()]
        self.assertNotIn("temp", titles)
        self.assertEqual(notification_center_service.get_stats()["published"], 0)


if __name__ == "__main__":
    unittest.main()
