import unittest
import asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.models.transit import (
    ModuleHealthStatus,
    AIChatRequest,
    DemoControlsRequest,
)
from app.services.health_service import health_service
from app.services.ai_service import AIService


class TestPhase40ProductionResilience(unittest.TestCase):
    """
    Verification suite for Phase 40: Production Readiness, Resilience & Municipal Operations Center.
    Tests 18-module system health, feed diagnostics, data quality scoring, operational event logging,
    demo scenario controls, deterministic reset, canonical disclosures, and AI operations queries.
    """

    def setUp(self):
        self.client = TestClient(app)
        health_service.reset()

    def tearDown(self):
        health_service.reset()

    def test_eighteen_module_system_health(self):
        """Verify 18 discrete transit platform modules report structured health statuses."""
        modules = health_service.get_system_modules()
        self.assertEqual(len(modules), 18)

        module_names = [m.name for m in modules]
        expected_names = [
            "Backend Server",
            "Transit Provider",
            "GTFS Static Repository",
            "Vehicle Positions Feed",
            "Trip Updates Feed",
            "Service Alerts Feed",
            "ETA Engine",
            "Crowd Engine",
            "Accessibility Engine",
            "Incident Engine",
            "Prediction Engine",
            "Recommendation Engine",
            "Notification Engine",
            "AI Engine",
            "Ticket Engine",
            "Identity Engine",
            "Simulator",
            "Offline Cache",
        ]
        for expected in expected_names:
            self.assertIn(expected, module_names)

        for m in modules:
            self.assertIn(m.status, [
                ModuleHealthStatus.HEALTHY.value,
                ModuleHealthStatus.DEGRADED.value,
                ModuleHealthStatus.STALE.value,
                ModuleHealthStatus.OFFLINE.value,
                ModuleHealthStatus.UNAVAILABLE.value,
                ModuleHealthStatus.STANDBY.value,
            ])
            self.assertGreater(len(m.disclosure), 0)

    def test_feed_health_and_stale_detection(self):
        """Verify feed health tracking, backoff states, and stale state detection."""
        feed = health_service.get_feed_health()
        self.assertIsNotNone(feed)
        self.assertIn(feed.backoff_state, ["IDLE", "RETRYING", "BACKOFF", "SUSPENDED"])

        # Override feed mode to stale
        health_service.apply_demo_controls(DemoControlsRequest(feed_mode="stale"))
        feed_stale = health_service.get_feed_health()
        self.assertEqual(feed_stale.feed_status, "STALE")
        self.assertEqual(feed_stale.backoff_state, "BACKOFF")

        # Override feed mode to disconnected
        health_service.apply_demo_controls(DemoControlsRequest(feed_mode="disconnected"))
        feed_disc = health_service.get_feed_health()
        self.assertEqual(feed_disc.feed_status, "DISCONNECTED")

    def test_data_quality_assessment_score(self):
        """Verify data quality score computation and diagnostic disclaimer."""
        dq = health_service.get_data_quality_assessment()
        self.assertIsNotNone(dq)
        self.assertGreaterEqual(dq.data_quality_score, 0)
        self.assertLessEqual(dq.data_quality_score, 100)
        self.assertIn("Diagnostic assessment score only — never used to rank commuter routes.", dq.diagnostic_statement)

    def test_diagnostic_event_logging_zero_pii(self):
        """Verify structured operational event logging adheres to zero-PII requirements."""
        evt = health_service.record_event(
            event_type="FEED_CONNECTED",
            title="Authorized Feed Reconnected",
            details="TripUpdate stream re-established without data loss.",
            severity="INFO",
            metadata={"latency_ms": 12},
        )
        self.assertIsNotNone(evt)
        self.assertEqual(evt.event_type, "FEED_CONNECTED")

        events = health_service.get_events(limit=10)
        self.assertGreaterEqual(len(events), 1)

        # Verify no PII fields
        for e in events:
            details_lower = e.details.lower()
            self.assertNotIn("aadhaar", details_lower)
            self.assertNotIn("password", details_lower)
            self.assertNotIn("secret", details_lower)

    def test_demo_controls_and_deterministic_reset(self):
        """Verify demo controls set scenario states and POST /api/demo/reset clears them."""
        # Set evaluator controls
        res_ctrl = self.client.post("/api/system/demo-controls", json={
            "feed_mode": "delayed",
            "offline_mode": True,
        })
        self.assertEqual(res_ctrl.status_code, 200)
        self.assertEqual(health_service._demo_feed_mode, "delayed")
        self.assertTrue(health_service._demo_offline_mode)

        # Execute demo reset
        res_reset = self.client.post("/api/demo/reset")
        self.assertEqual(res_reset.status_code, 200)
        self.assertEqual(res_reset.json()["status"], "success")

        # Verify reset
        self.assertEqual(health_service._demo_feed_mode, "unconfigured")
        self.assertFalse(health_service._demo_offline_mode)

    def test_canonical_operational_statement_and_disclosures(self):
        """Verify canonical operational statement and mandatory disclosures are preserved verbatim."""
        self.assertEqual(
            health_service.CANONICAL_FEED_DISCLOSURE,
            "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED",
        )

        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("diagnostics", data)
        self.assertIn("health", data["diagnostics"])
        self.assertIn("feeds", data["diagnostics"])
        self.assertIn("predictions", data["diagnostics"])
        self.assertIn("recommendations", data["diagnostics"])

    def test_ai_operations_intents(self):
        """Verify AI responds to operations queries accurately and cleanly."""
        req_sys = AIChatRequest(message="What is the system status?")
        res_sys = asyncio.run(AIService.process_chat(req_sys))
        self.assertEqual(res_sys.intent, "system_status")
        self.assertIn("Platform System Health", res_sys.answer)

        req_feed = AIChatRequest(message="What is the feed status?")
        res_feed = asyncio.run(AIService.process_chat(req_feed))
        self.assertEqual(res_feed.intent, "feed_status")
        self.assertIn("REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED", res_feed.answer)

        req_pred = AIChatRequest(message="What is the prediction source?")
        res_pred = asyncio.run(AIService.process_chat(req_pred))
        self.assertEqual(res_pred.intent, "prediction_source")
        self.assertIn("Authorized GTFS-RT", res_pred.answer)


if __name__ == "__main__":
    unittest.main()
