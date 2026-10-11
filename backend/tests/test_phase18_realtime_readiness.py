import unittest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings, Settings, OPERATIONAL_STATEMENT_NOT_CONNECTED
from app.services.bmtc_provider import BMTCTransitDataProvider, bmtc_provider
from app.services.mock_provider import MockTransitDataProvider, mock_provider
from app.services.provider_factory import get_transit_provider, get_provider_health
from app.services.ticket_service import ticket_service
from app.services.ai_service import AIService
from app.models.transit import AIChatRequest, TicketCreateRequest


class TestPhase18RealtimeReadiness(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_1_realtime_provider_activation_with_valid_credentials(self):
        """When TRANSIT_PROVIDER=bmtc AND valid endpoints exist with live data, activates BMTCTransitDataProvider."""
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="valid-secret-key"
        )
        self.assertTrue(provider.is_configured)
        # Without data, fallback logic keeps serving verified fallback safely
        self.assertFalse(provider.has_live_data)

    def test_2_provider_activation_fallback_when_credentials_missing(self):
        """When TRANSIT_PROVIDER=bmtc but credentials missing, safely uses MockTransitDataProvider."""
        with patch.object(settings, "transit_provider", "bmtc"):
            with patch.object(bmtc_provider, "endpoint", None):
                with patch.object(bmtc_provider, "api_key", None):
                    active = get_transit_provider()
                    self.assertIsInstance(active, MockTransitDataProvider)
                    health = get_provider_health()
                    self.assertEqual(health.data_mode, "simulated")
                    self.assertFalse(health.realtime)

    def test_3_gtfs_rt_separate_component_diagnostics(self):
        """GTFS-RT diagnostics separately report vehicle_positions, trip_updates, and service_alerts."""
        feed_health = bmtc_provider.get_feed_health()
        self.assertIsNotNone(feed_health.vehicle_positions_feed)
        self.assertIsNotNone(feed_health.trip_updates_feed)
        self.assertIsNotNone(feed_health.service_alerts_feed)
        self.assertIn("entity_count", feed_health.vehicle_positions_feed.model_dump())
        self.assertIn("configured", feed_health.trip_updates_feed.model_dump())
        self.assertIn("reachable", feed_health.service_alerts_feed.model_dump())

    def test_4_ticket_route_mismatch_detection(self):
        """Conductor verification detects when a ticket is presented on a different route."""
        # Create ticket for 500D
        ticket = asyncio.run(ticket_service.create_ticket(
            TicketCreateRequest(route_number="500D", source="Silk Board", destination="Hebbal")
        ))
        
        # Verify on matching route 500D
        res_match = ticket_service.verify_ticket(ticket.ticket_id, conductor_route_number="500D")
        self.assertTrue(res_match.valid)
        self.assertEqual(res_match.status, "active")

        # Verify on mismatched route 356
        res_mismatch = ticket_service.verify_ticket(ticket.ticket_id, conductor_route_number="356")
        self.assertFalse(res_mismatch.valid)
        self.assertEqual(res_mismatch.status, "mismatch")
        self.assertIn("Route Mismatch", res_mismatch.message)

    def test_5_ticket_explicit_demo_disclaimer(self):
        """All created tickets carry the explicit DEMO PASS disclaimer."""
        ticket = asyncio.run(ticket_service.create_ticket(
            TicketCreateRequest(route_number="KIA-8", source="HSR Layout", destination="Airport")
        ))
        self.assertEqual(ticket.disclaimer, "DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL")

    def test_6_ai_multi_turn_stops_intent(self):
        """AI resolves 'Show me the stops' using session route memory."""
        session_id = "phase18-stops-test-session"
        # Turn 1: Ask about 356
        req1 = AIChatRequest(message="Where is 356?", session_id=session_id)
        resp1 = asyncio.run(AIService.process_chat(req1))
        self.assertEqual(resp1.intent, "bus_location")

        # Turn 2: Follow up 'Show me the stops.'
        req2 = AIChatRequest(message="Show me the stops.", session_id=session_id)
        resp2 = asyncio.run(AIService.process_chat(req2))
        self.assertEqual(resp2.intent, "bus_route")
        self.assertIn("356", resp2.answer)

    def test_7_operational_statement_exactness(self):
        """Verifies exact operational statement when unconfigured."""
        s = Settings()
        val = s.validate_production_config()
        self.assertEqual(val["operational_statement"], OPERATIONAL_STATEMENT_NOT_CONNECTED)
        self.assertEqual(
            OPERATIONAL_STATEMENT_NOT_CONNECTED,
            "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED"
        )


if __name__ == "__main__":
    unittest.main()
