import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.models.transit import (
    AccessibilityStatus,
    AccessibilityMetadata,
    JourneySearchRequest,
    AIChatRequest,
)
from app.models.personalization import CommuterPreferencesDto
from app.services.mock_provider import mock_provider
from app.services.journey_service import JourneyService, compute_accessibility_score
from app.services.ai_service import AIService, IntentDetector
from app.services.ai_provider import MockAIProvider
from app.services.personalization_service import personalization_service
from app.services.metrics_service import metrics_service


class TestPhase35AccessibilityIntelligence(unittest.IsolatedAsyncioTestCase):
    """
    Test suite for Phase 35 Smart Accessibility & Inclusive Transit.
    Verifies data-truth accessibility models, fleet & stop metadata,
    scoring & ranking, grounded AI assistant, diagnostics, and REST APIs.
    """

    def setUp(self):
        self.client = TestClient(app)
        personalization_service.reset()
        metrics_service.reset()

    def test_accessibility_model_defaults_and_truthfulness(self):
        """Verify AccessibilityMetadata default is strictly UNKNOWN with mandated disclosure."""
        acc = AccessibilityMetadata()
        self.assertEqual(acc.status, AccessibilityStatus.UNKNOWN)
        self.assertIsNone(acc.wheelchair_accessible)
        self.assertIsNone(acc.low_floor_bus)
        self.assertFalse(acc.accessible_stop)
        self.assertFalse(acc.boarding_assistance_available)
        self.assertEqual(
            acc.accessibility_disclosure,
            "Accessibility information unavailable from the current transit data.",
        )

    def test_bus_fleet_accessibility_metadata(self):
        """Verify simulated fleet buses have accurate, verified accessibility metadata."""
        # Vajra Electric 500D
        acc_500d = mock_provider.get_accessibility_info("500D")
        self.assertEqual(acc_500d.status, AccessibilityStatus.ACCESSIBLE)
        self.assertTrue(acc_500d.wheelchair_accessible)
        self.assertTrue(acc_500d.low_floor_bus)
        self.assertTrue(acc_500d.boarding_assistance_available)
        self.assertTrue(acc_500d.audio_announcements)

        # Vayu Vajra KIA-8
        acc_kia8 = mock_provider.get_accessibility_info("KIA-8")
        self.assertEqual(acc_kia8.status, AccessibilityStatus.ACCESSIBLE)
        self.assertTrue(acc_kia8.wheelchair_accessible)
        self.assertTrue(acc_kia8.low_floor_bus)

        # Vajra Electric G-2
        acc_g2 = mock_provider.get_accessibility_info("G-2")
        self.assertEqual(acc_g2.status, AccessibilityStatus.ACCESSIBLE)
        self.assertTrue(acc_g2.wheelchair_accessible)

        # BMTC Ordinary 356
        acc_356 = mock_provider.get_accessibility_info("356")
        self.assertEqual(acc_356.status, AccessibilityStatus.NOT_ACCESSIBLE)
        self.assertFalse(acc_356.wheelchair_accessible)
        self.assertFalse(acc_356.low_floor_bus)
        self.assertIn("Not wheelchair accessible", acc_356.accessibility_disclosure)

        # BMTC Ordinary 201R
        acc_201r = mock_provider.get_accessibility_info("201R")
        self.assertEqual(acc_201r.status, AccessibilityStatus.NOT_ACCESSIBLE)
        self.assertFalse(acc_201r.wheelchair_accessible)

        # Unknown route
        acc_unknown = mock_provider.get_accessibility_info("999X")
        self.assertEqual(acc_unknown.status, AccessibilityStatus.UNKNOWN)
        self.assertIsNone(acc_unknown.wheelchair_accessible)
        self.assertEqual(
            acc_unknown.accessibility_disclosure,
            "Accessibility information unavailable from the current transit data.",
        )

    def test_stop_accessibility_metadata(self):
        """Verify verified station hubs vs generic stops."""
        # Verified accessible stops
        majestic = mock_provider.get_accessibility_info("stop-majestic")
        self.assertEqual(majestic.status, AccessibilityStatus.ACCESSIBLE)
        self.assertTrue(majestic.accessible_stop)
        self.assertTrue(majestic.wheelchair_accessible)

        silk_board = mock_provider.get_accessibility_info("Central Silk Board Junction")
        self.assertEqual(silk_board.status, AccessibilityStatus.ACCESSIBLE)
        self.assertTrue(silk_board.accessible_stop)

        airport = mock_provider.get_accessibility_info("stop-airport")
        self.assertEqual(airport.status, AccessibilityStatus.ACCESSIBLE)
        self.assertTrue(airport.accessible_stop)

        # Unverified stop
        btm = mock_provider.get_accessibility_info("BTM Layout Water Tank")
        self.assertEqual(btm.status, AccessibilityStatus.UNKNOWN)
        self.assertEqual(
            btm.accessibility_disclosure,
            "Accessibility information unavailable from the current transit data.",
        )

    async def test_journey_service_accessibility_scoring_and_ranking(self):
        """Verify journey options populate accessibility metadata, scores, and rank accessible routes when requested."""
        # 1. Standard search without priority
        resp = await JourneyService.search_journey(
            JourneySearchRequest(origin="Central Silk Board Junction", destination="Majestic (Kempegowda Bus Station)")
        )
        self.assertTrue(len(resp.options) > 0)
        first_opt = resp.options[0]
        self.assertIsNotNone(first_opt.accessibility)
        self.assertIsNotNone(first_opt.accessibility_score)
        self.assertTrue(first_opt.accessibility_score > 0)

        # Check leg accessibility
        bus_legs = [l for l in first_opt.legs or [] if l.leg_type == "BUS"]
        self.assertTrue(len(bus_legs) > 0)
        self.assertIsNotNone(bus_legs[0].accessibility)

        # 2. Preference with wheelchair_required = True
        personalization_service.update_preferences(
            CommuterPreferencesDto(
                language="EN",
                bus_preference="All",
                accessibility_priority=True,
                wheelchair_required=True,
                low_floor_preferred=True,
            )
        )

        resp_pref = await JourneyService.search_journey(
            JourneySearchRequest(origin="Silk Board", destination="")
        )
        self.assertTrue(len(resp_pref.options) > 0)
        # Top option must be accessible with top accessibility score
        top_opt = resp_pref.options[0]
        self.assertIsNotNone(top_opt.accessibility)
        self.assertEqual(top_opt.accessibility.status, AccessibilityStatus.ACCESSIBLE)
        self.assertTrue(top_opt.accessibility.wheelchair_accessible)
        self.assertTrue(top_opt.accessibility_score >= 80)

        # Metric counters must have incremented
        self.assertTrue(metrics_service.accessible_journey_searches >= 1)
        self.assertTrue(metrics_service.wheelchair_priority_queries >= 1)
        self.assertTrue(metrics_service.low_floor_filter_applied >= 1)

    async def test_ai_assistant_accessibility_queries(self):
        """Verify grounded conversational answers for accessibility intents."""
        # 1. Query about 500D wheelchair accessibility
        res_500d = await AIService.process_chat(
            AIChatRequest(message="Is bus 500D wheelchair accessible?", session_id="acc-session-1")
        )
        self.assertIn("wheelchair", res_500d.intent.lower())
        self.assertIn("500D", res_500d.answer)
        self.assertIn("wheelchair accessible", res_500d.answer.lower())
        self.assertIn("ramp", res_500d.answer.lower())

        # 2. Query about 356 wheelchair accessibility (high-floor, not accessible)
        res_356 = await AIService.process_chat(
            AIChatRequest(message="Can I board bus 356 with a wheelchair?", session_id="acc-session-2")
        )
        self.assertIn("356", res_356.answer)
        self.assertIn("not wheelchair accessible", res_356.answer.lower())

        # 3. Query about low-floor buses
        res_low_floor = await AIService.process_chat(
            AIChatRequest(message="Which buses have low floor easy boarding?", session_id="acc-session-3")
        )
        self.assertIn("low-floor", res_low_floor.answer.lower())
        self.assertIn("500D", res_low_floor.answer)

        # 4. Query about senior citizens
        res_senior = await AIService.process_chat(
            AIChatRequest(message="Is 500D senior friendly for elderly commuters?", session_id="acc-session-4")
        )
        self.assertIn("senior", res_senior.answer.lower())

        # 5. Stop accessibility query
        res_stop = await AIService.process_chat(
            AIChatRequest(message="Is there a wheelchair ramp at Majestic terminal?", session_id="acc-session-5")
        )
        self.assertIn("Majestic", res_stop.answer)
        self.assertIn("ramp", res_stop.answer.lower())

        # Verify AI accessibility metrics counter
        self.assertTrue(metrics_service.accessibility_ai_queries >= 4)

    async def test_ai_strict_unverified_fallback(self):
        """Verify that when accessibility is unknown, the strict canonical disclosure is returned."""
        provider = MockAIProvider()
        # Unknown route
        res = await provider.generate_response(
            message="Is route 999 accessible?",
            intent="accessibility_check",
            transit_context={"route_number": "999", "bus_type": "BMTC Ordinary", "accessibility": None},
        )
        self.assertIn("Accessibility information unavailable from the current transit data.", res)

        # Unknown stop
        res_stop = await provider.generate_response(
            message="Is stop X accessible?",
            intent="stop_accessibility",
            transit_context={"stop_name": "Random Street Stop", "stop_accessibility": {"status": "UNKNOWN"}},
        )
        self.assertIn("Accessibility information unavailable from the current transit data.", res_stop)

    def test_rest_api_transit_accessibility_endpoint(self):
        """Verify GET /api/transit/accessibility/{route_or_bus_id} endpoint."""
        # 1. 500D Accessible
        r1 = self.client.get("/api/transit/accessibility/500D")
        self.assertEqual(r1.status_code, 200)
        data1 = r1.json()
        self.assertEqual(data1["status"], "ACCESSIBLE")
        self.assertTrue(data1["wheelchair_accessible"])
        self.assertTrue(data1["low_floor_bus"])

        # 2. 356 Not Accessible
        r2 = self.client.get("/api/transit/accessibility/356")
        self.assertEqual(r2.status_code, 200)
        data2 = r2.json()
        self.assertEqual(data2["status"], "NOT_ACCESSIBLE")
        self.assertFalse(data2["wheelchair_accessible"])

        # 3. Stop Silk Board
        r3 = self.client.get("/api/transit/accessibility/stop-silk-board")
        self.assertEqual(r3.status_code, 200)
        data3 = r3.json()
        self.assertEqual(data3["status"], "ACCESSIBLE")
        self.assertTrue(data3["accessible_stop"])

        # 4. Unknown query returns UNKNOWN with mandated disclosure
        r4 = self.client.get("/api/transit/accessibility/non-existent-stop")
        self.assertEqual(r4.status_code, 200)
        data4 = r4.json()
        self.assertEqual(data4["status"], "UNKNOWN")
        self.assertEqual(
            data4["accessibility_disclosure"],
            "Accessibility information unavailable from the current transit data.",
        )

    def test_diagnostics_system_status_accessibility(self):
        """Verify GET /api/system/status exposes accessibility module and counters."""
        r = self.client.get("/api/system/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()

        # Check modules
        modules = data.get("modules", [])
        acc_module = next((m for m in modules if m["name"] == "Accessibility Engine"), None)
        self.assertIsNotNone(acc_module)
        self.assertEqual(acc_module["status"], "Active")

        # Check diagnostics
        diag = data.get("diagnostics", {})
        self.assertIn("accessibility", diag)
        acc_diag = diag["accessibility"]
        self.assertIn("accessible_journey_searches", acc_diag)
        self.assertIn("accessible_options_viewed", acc_diag)
        self.assertIn("wheelchair_priority_queries", acc_diag)
        self.assertIn("low_floor_filter_applied", acc_diag)
        self.assertIn("accessibility_ai_queries", acc_diag)

    def test_commuter_preferences_accessibility_persistence(self):
        """Verify commuter preferences round-trip with accessibility fields."""
        prefs_payload = {
            "language": "KN",
            "bus_preference": "Vajra Electric",
            "accessibility_priority": True,
            "wheelchair_required": True,
            "low_floor_preferred": True,
            "reduced_walking_preferred": True,
            "senior_friendly_preferred": True,
            "audio_guidance_enabled": True,
            "high_contrast_enabled": True,
            "large_text_enabled": True,
        }
        r = self.client.post("/api/preferences", json=prefs_payload)
        self.assertEqual(r.status_code, 200)
        res_data = r.json()
        self.assertTrue(res_data["accessibility_priority"])
        self.assertTrue(res_data["wheelchair_required"])
        self.assertTrue(res_data["low_floor_preferred"])
        self.assertTrue(res_data["reduced_walking_preferred"])
        self.assertTrue(res_data["senior_friendly_preferred"])
        self.assertTrue(res_data["audio_guidance_enabled"])
        self.assertTrue(res_data["high_contrast_enabled"])
        self.assertTrue(res_data["large_text_enabled"])

        # Also verify GET /api/preferences returns the updated preferences
        r_get = self.client.get("/api/preferences")
        self.assertEqual(r_get.status_code, 200)
        get_data = r_get.json()
        self.assertTrue(get_data["wheelchair_required"])
        self.assertTrue(get_data["low_floor_preferred"])


if __name__ == "__main__":
    unittest.main()
