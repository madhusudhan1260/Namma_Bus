import asyncio
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.models.transit import ServiceAlert, FeedHealth, ReadinessResponse, HealthResponse
from app.services.bmtc_provider import bmtc_provider, BMTCTransitDataProvider
from app.services.provider_factory import get_transit_provider, get_provider_health
from app.services.alert_service import alert_service
from app.services.ai_service import AIService
from app.models.transit import AIChatRequest
from app.services.mock_provider import MockTransitDataProvider


class TestPhase14ProductionAndSecurity(unittest.TestCase):
    """
    Phase 14 Comprehensive Test Suite:
    - Secret protection (API keys never logged or exposed in responses)
    - BMTC API endpoint validation
    - Feed health metrics calculation
    - Upstream timeout and connection resilience
    - Service alerts retrieval and filtering
    - Liveness (/api/health) and Readiness (/api/ready) separation
    - System status observability metrics (uptime, latency stats, feed health)
    - Security middleware (X-Request-ID, X-Response-Time-Ms, rate limiting, payload size)
    - Grounded AI Assistant data mode awareness across 4 modes
    - Demo reset preservation and safety safeguards
    """

    def setUp(self):
        self.client = TestClient(app)

    # --- 1. Secret Protection & Validation ---
    def test_1_secret_protection_in_responses(self):
        """Ensure API keys and secrets are never returned in system responses."""
        with patch.object(bmtc_provider, "api_key", "super-secret-production-token-123"):
            res = self.client.get("/api/health")
            self.assertEqual(res.status_code, 200)
            self.assertNotIn("super-secret-production-token-123", res.text)

            res_status = self.client.get("/api/system/status")
            self.assertEqual(res_status.status_code, 200)
            self.assertNotIn("super-secret-production-token-123", res_status.text)

    def test_2_bmtc_endpoint_validation(self):
        """Validate URL schemes for BMTC API endpoint."""
        with patch.object(settings, "bmtc_api_endpoint", "https://authorized.bmtc.gov.in/gtfs"):
            self.assertTrue(settings.is_bmtc_endpoint_valid)

        with patch.object(settings, "bmtc_api_endpoint", "ftp://invalid-server.com"):
            self.assertFalse(settings.is_bmtc_endpoint_valid)

        with patch.object(settings, "bmtc_api_endpoint", None):
            self.assertFalse(settings.is_bmtc_endpoint_valid)

    # --- 2. Middleware, Tracing & Rate Limiting ---
    def test_3_security_headers_and_request_id(self):
        """Verify X-Request-ID, timing, and security headers are attached to responses."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertIn("X-Request-ID", res.headers)
        self.assertIn("X-Response-Time-Ms", res.headers)
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")

    def test_4_request_size_limit_rejection(self):
        """Ensure oversized requests are rejected with HTTP 413."""
        huge_headers = {"Content-Length": str(2 * 1024 * 1024)}  # 2MB > 1MB limit
        res = self.client.post("/api/tickets", headers=huge_headers, content=b"A" * 100)
        self.assertEqual(res.status_code, 413)

    # --- 3. Health & Readiness Probes ---
    def test_5_liveness_health_endpoint(self):
        """Liveness check returns healthy process status."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("provider", data)
        self.assertIn("data_mode", data)

    def test_6_readiness_probe_remains_ready_during_feed_offline(self):
        """
        Readiness probe verifies the application can serve requests.
        Even if BMTC feed is offline or unconfigured, application remains ready
        by safely serving its configured fallback simulation.
        """
        res = self.client.get("/api/ready")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ready"])
        self.assertEqual(data["status"], "ready")
        self.assertGreaterEqual(data["uptime_seconds"], 0)

    # --- 4. Realtime Feed Quality & FeedHealth ---
    def test_7_feed_health_unconfigured(self):
        """Unconfigured provider returns unavailable feed health safely."""
        unconfigured = BMTCTransitDataProvider(endpoint=None, api_key=None)
        fh = unconfigured.get_feed_health()
        self.assertEqual(fh.status, "unavailable")
        self.assertEqual(fh.vehicle_positions, 0)
        self.assertEqual(fh.freshness_percentage, 0.0)

    def test_8_feed_health_active_and_stale(self):
        """FeedHealth tracks active vehicles and calculates freshness percentage."""
        provider = BMTCTransitDataProvider(
            endpoint="https://test.bmtc.gov.in/api",
            api_key="secret",
            poll_interval=10.0,
            stale_threshold=30.0,
        )
        sample_payload = {
            "entity": [
                {
                    "id": "v1",
                    "vehicle": {
                        "trip": {"trip_id": "t1", "route_id": "500D"},
                        "position": {"latitude": 12.9176, "longitude": 77.6238},
                        "vehicle": {"id": "KA-01-F-4819"},
                    },
                }
            ]
        }
        provider.ingest_payload(sample_payload)
        fh = provider.get_feed_health()
        self.assertEqual(fh.status, "healthy")
        self.assertEqual(fh.vehicle_positions, 1)
        self.assertEqual(fh.consecutive_failures, 0)
        self.assertEqual(fh.freshness_percentage, 100.0)

        # Simulate delay past stale threshold
        provider._last_updated_at = datetime.now(timezone.utc) - timedelta(seconds=45)
        fh_stale = provider.get_feed_health()
        self.assertEqual(fh_stale.status, "stale")
        self.assertLess(fh_stale.freshness_percentage, 100.0)

    def test_9_feed_fetch_failure_counter(self):
        """Consecutive failures are incremented on fetch error."""
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret")
        self.assertEqual(provider._consecutive_failures, 0)
        provider._handle_fetch_error()
        self.assertEqual(provider._consecutive_failures, 1)
        self.assertIsNotNone(provider._last_failed_fetch)

    # --- 5. Service Alerts Subsystem ---
    def test_10_service_alerts_endpoint_and_filtering(self):
        """GET /api/alerts returns active alerts with route/stop filtering."""
        res = self.client.get("/api/alerts")
        self.assertEqual(res.status_code, 200)
        alerts = res.json()
        self.assertGreater(len(alerts), 0)

        # Filter by route 500D
        res_filtered = self.client.get("/api/alerts?route=500D")
        self.assertEqual(res_filtered.status_code, 200)
        data = res_filtered.json()
        self.assertGreater(len(data), 0)
        self.assertTrue(any(a["route_number"] == "500D" for a in data))

    # --- 6. System Status Observability ---
    def test_11_system_status_extended_observability(self):
        """GET /api/system/status returns latency statistics, uptime, and feed health."""
        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("uptime_seconds", data)
        self.assertIn("latency_stats", data)
        self.assertIn("feed_health", data)
        self.assertIn("provider_polling_interval", data)
        self.assertIsInstance(data["modules"], list)

    # --- 7. AI Assistant 4-State Data Quality Awareness ---
    def test_12_ai_awareness_simulated_mode(self):
        """AI Assistant acknowledges simulated mode for demo."""
        req = AIChatRequest(message="Where is 500D?")
        with patch.object(settings, "transit_provider", "mock"):
            resp = asyncio.run(AIService.process_chat(req))
            self.assertIn("simulated Bengaluru corridor telemetry", resp.answer)

    def test_13_ai_awareness_realtime_mode(self):
        """AI Assistant acknowledges authorized realtime feed when live."""
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="key")
        sample_payload = {
            "entity": [
                {
                    "id": "v1",
                    "vehicle": {
                        "trip": {"trip_id": "t1", "route_id": "500D"},
                        "position": {"latitude": 12.9176, "longitude": 77.6238},
                        "vehicle": {"id": "KA-01-F-4819"},
                        "occupancy_status": "MANY_SEATS_AVAILABLE",
                    },
                }
            ]
        }
        provider.ingest_payload(sample_payload)

        with patch("app.services.ai_service.get_transit_provider", return_value=provider), \
             patch("app.services.ai_service.get_provider_health", return_value=HealthResponse(feed_status="connected", data_mode="realtime", realtime=True, provider="bmtc")):
            req = AIChatRequest(message="Where is 500D?")
            resp = asyncio.run(AIService.process_chat(req))
            self.assertIn("authorized BMTC realtime feed", resp.answer)

    def test_14_ai_awareness_stale_mode(self):
        """AI Assistant warns commuter when feed is delayed/stale."""
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="key", stale_threshold=5.0)
        sample_payload = {
            "entity": [
                {
                    "id": "v1",
                    "vehicle": {
                        "trip": {"trip_id": "t1", "route_id": "500D"},
                        "position": {"latitude": 12.9176, "longitude": 77.6238},
                        "vehicle": {"id": "KA-01-F-4819"},
                    },
                }
            ]
        }
        provider.ingest_payload(sample_payload)
        provider._last_updated_at = datetime.now(timezone.utc) - timedelta(seconds=15)

        with patch("app.services.ai_service.get_transit_provider", return_value=provider), \
             patch("app.services.ai_service.get_provider_health", return_value=HealthResponse(stale=True, feed_status="stale", data_mode="realtime", realtime=True, provider="bmtc")):
            req = AIChatRequest(message="When will 500D arrive?")
            resp = asyncio.run(AIService.process_chat(req))
            self.assertIn("realtime feed is delayed", resp.answer)

    # --- 8. Demo Reset & Transition Safety ---
    def test_15_demo_reset_preserves_safety(self):
        """POST /api/demo/reset restores simulator baseline without changing provider."""
        res = self.client.post("/api/demo/reset")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")

        # Provider remains safe simulator
        p = get_transit_provider()
        self.assertIsInstance(p, MockTransitDataProvider)


if __name__ == "__main__":
    unittest.main()
