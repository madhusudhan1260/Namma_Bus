import asyncio
import json
import logging
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app
from app.core import middleware
from app.core.config import Settings, settings
from app.services.payment_service import PaymentCreateRequest, PaymentVerifyRequest, PaymentStatus, PaymentError, payment_service
from app.services.notification_center_service import notification_center_service
from app.services.bmtc_provider import BMTCTransitDataProvider


class TestPhase48Security(unittest.TestCase):
    """Master spec Phase 48: conductor authorization, secret configuration, log hygiene, rate limiting."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def tearDown(self):
        settings.conductor_access_key = None
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def test_conductor_key_enforced_when_configured(self):
        ticket = self.client.post("/api/tickets", json={"route_number": "500D", "source": "A", "destination": "B"}).json()
        settings.conductor_access_key = "test-conductor-key"
        body = {"qr_payload_or_code": ticket["qr_payload"], "conductor_route_number": "500D"}
        self.assertEqual(self.client.post("/api/tickets/verify", json=body).status_code, 403)
        self.assertEqual(self.client.post("/api/tickets/verify", json=body, headers={"X-Conductor-Key": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/tickets/{ticket['ticket_id']}/use").status_code, 403)
        ok = self.client.post("/api/tickets/verify", json=body, headers={"X-Conductor-Key": "test-conductor-key"})
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["valid"])

    def test_conductor_open_when_not_configured(self):
        ticket = self.client.post("/api/tickets", json={"route_number": "500D", "source": "A", "destination": "B"}).json()
        self.assertEqual(self.client.post("/api/tickets/verify", json={"qr_payload_or_code": ticket["ticket_id"]}).status_code, 200)

    def test_missing_secrets_reported_without_leaking_values(self):
        s = Settings(environment="production", cors_origins=["https://app.nammablr.in"], bmtc_api_key="super-secret-value")
        s.ticket_hmac_secret_set = False
        s.conductor_access_key = None
        report = s.validate_production_config()
        joined = " ".join(report["warnings"])
        self.assertIn("TICKET_HMAC_SECRET", joined)
        self.assertIn("CONDUCTOR_ACCESS_KEY", joined)
        self.assertNotIn("super-secret-value", json.dumps(report))

    def test_payment_endpoints_rate_limited(self):
        original = settings.rate_limit_per_minute
        settings.rate_limit_per_minute = 3
        try:
            codes = [self.client.post("/api/payment/create", json={"route_number": "500D", "source": "a", "destination": "b"}).status_code for _ in range(5)]
        finally:
            settings.rate_limit_per_minute = original
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3:], [429, 429])

    def test_no_tokens_or_payment_secrets_in_logs(self):
        with self.assertLogs(level=logging.INFO) as cap:
            tok = self.client.post("/api/auth/register", json={"full_name": "Log Check", "mobile": "9000011111", "email": "log.check@gmail.com"}).json()["session_token"]
            pid = self.client.post("/api/payment/create", json={"route_number": "500D", "source": "a", "destination": "b"}, headers={"Authorization": f"Bearer {tok}"}).json()["payment_id"]
            self.client.post("/api/payment/verify", json={"payment_id": pid, "sandbox_outcome": "PAYMENT_SUCCESS"})
            logging.getLogger("nammablr.test").info("marker")
        out = "\n".join(cap.output)
        for value in (tok, "9000011111", "log.check@gmail.com"):
            self.assertNotIn(value, out)


class TestPhase49Reliability(unittest.TestCase):
    """Master spec Phase 49: concurrency, bursts, malformed input and latency sanity checks."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def tearDown(self):
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def test_concurrent_purchases_cannot_double_spend_a_payment(self):
        rec = payment_service.create(PaymentCreateRequest(route_number="500D", source="a", destination="b"))
        payment_service.verify(PaymentVerifyRequest(payment_id=rec.payment_id, sandbox_outcome=PaymentStatus.PAYMENT_SUCCESS))

        def claim(_):
            try:
                payment_service.reserve_for_ticket(rec.payment_id)
                return True
            except PaymentError:
                return False

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(claim, range(50)))
        self.assertEqual(results.count(True), 1)

    def test_concurrent_journey_and_map_queries(self):
        def hit(i):
            if i % 2:
                return self.client.get("/api/buses").status_code
            return self.client.post("/api/journey/search", json={"origin": "Central Silk Board", "destination": "Majestic"}).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(hit, range(60)))
        self.assertTrue(all(c == 200 for c in codes), set(codes))

    def test_notification_burst_is_bounded(self):
        t0 = time.perf_counter()
        created = sum(1 for i in range(1000) if notification_center_service.publish("CROWD_CHANGE", f"burst {i}", "x", dedup_key=f"burst-{i}")[1])
        elapsed = time.perf_counter() - t0
        self.assertLessEqual(created, 30)
        self.assertLess(elapsed, 2.0)

    def test_conductor_scan_burst(self):
        ticket = self.client.post("/api/tickets", json={"route_number": "500D", "source": "A", "destination": "B"}).json()
        t0 = time.perf_counter()
        results = [self.client.post("/api/tickets/verify", json={"qr_payload_or_code": ticket["qr_payload"], "conductor_route_number": "500D"}).json()["valid"] for _ in range(100)]
        self.assertTrue(all(results))
        self.assertLess((time.perf_counter() - t0) / 100, 0.05)

    def test_gtfs_rt_burst_with_malformed_entities(self):
        provider = BMTCTransitDataProvider()
        entities = []
        for i in range(2000):
            if i % 4 == 0:
                entities.append({"id": f"bad{i}", "vehicle": {"position": {"latitude": "x", "longitude": None}}})
            else:
                entities.append({"id": f"v{i}", "vehicle": {"vehicle": {"id": f"v{i}"}, "trip": {"route_id": "500D"}, "position": {"latitude": 12.9 + (i % 50) * 0.001, "longitude": 77.6}}})
        t0 = time.perf_counter()
        count = provider.ingest_payload({"entity": entities})
        self.assertEqual(count, 1500)
        self.assertLess(time.perf_counter() - t0, 5.0)

    def test_network_interruption_keeps_last_known_good(self):
        provider = BMTCTransitDataProvider()
        provider.ingest_payload({"entity": [{"id": "v1", "vehicle": {"vehicle": {"id": "v1"}, "trip": {"route_id": "500D"}, "position": {"latitude": 12.95, "longitude": 77.6}}}]})
        provider.endpoint, provider.api_key = "http://127.0.0.1:9/unreachable", "k"
        provider.timeout_seconds = 0.5
        ok = asyncio.run(provider.poll_feed_once())
        self.assertFalse(ok)
        self.assertIn("v1", provider._buses)

    def test_performance_report_exposes_percentiles(self):
        for _ in range(20):
            self.client.get("/api/buses")
            self.client.get("/api/gtfs/routes")
        report = self.client.get("/api/system/performance").json()
        self.assertIn("p99_ms", report["overall"])
        self.assertGreater(report["by_capability"]["map_updates"]["count"], 0)
        self.assertGreater(report["by_capability"]["gtfs_queries"]["count"], 0)
        self.assertIn("p99_ms", self.client.get("/api/system/status").json()["latency_stats"])


if __name__ == "__main__":
    unittest.main()
