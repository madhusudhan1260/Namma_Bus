import unittest
import asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.models.transit import (
    IncidentSeverity,
    IncidentType,
    IncidentSource,
    IncidentStatus,
    AIChatRequest,
    ActiveJourneyCreateRequest,
)
from app.services.incident_service import incident_service
from app.services.incident_impact_service import incident_impact_service
from app.services.ai_service import AIService
from app.services.active_journey_service import active_journey_service
from app.services.metrics_service import metrics_service


class TestPhase37DisruptionIntelligence(unittest.TestCase):
    """
    Comprehensive verification suite for Phase 37:
    Smart Transit Disruption & Incident Intelligence for Bengaluru Transit.
    """

    def setUp(self):
        self.client = TestClient(app)
        incident_service.reset()

    def tearDown(self):
        incident_service.reset()

    # -------------------------------------------------------------------------
    # 1. CORE INCIDENT REPOSITORIES & CANONICAL ATTRIBUTIONS
    # -------------------------------------------------------------------------
    def test_deterministic_incidents_and_source_attribution(self):
        """Verify deterministic incidents have grounded attribution badges and types."""
        incidents = incident_service.get_active_incidents()
        self.assertGreater(len(incidents), 0)

        # Check Silk Board waterlogging incident
        silk_board_inc = next((i for i in incidents if "Silk Board" in (i.corridor or "")), None)
        self.assertIsNotNone(silk_board_inc)
        self.assertEqual(silk_board_inc.incident_type, IncidentType.WATERLOGGING.value)
        self.assertEqual(silk_board_inc.severity, IncidentSeverity.DISRUPTION.value)
        self.assertEqual(silk_board_inc.source, IncidentSource.SIMULATED.value)
        self.assertIn("SIMULATED", silk_board_inc.source_attribution_badge)
        self.assertIn("500D", silk_board_inc.affected_route_numbers)
        self.assertEqual(silk_board_inc.expected_delay_minutes, 18)

    def test_gtfs_rt_alert_ingestion(self):
        """Verify official/authorized GTFS-RT alerts ingest with correct badge."""
        alert_id = incident_service.ingest_gtfs_rt_alert(
            alert_id="GTFS_RT_ALERT_TEST_101",
            title="Road Diversion near Hebbal",
            description="Outer Ring Road traffic diverted via service lane.",
            affected_routes=["500D", "KIA-8"],
            affected_stops=["Hebbal"],
            severity=IncidentSeverity.WARNING.value,
        )
        self.assertEqual(alert_id, "GTFS_RT_ALERT_TEST_101")
        inc = incident_service.get_incident_by_id(alert_id)
        self.assertIsNotNone(inc)
        self.assertEqual(inc.source, IncidentSource.AUTHORIZED_GTFS_RT.value)
        self.assertEqual(inc.source_attribution_badge, "Authorized GTFS-RT Service Alert")
        self.assertIn("500D", inc.affected_route_numbers)

    # -------------------------------------------------------------------------
    # 2. IMPACT ASSESSMENTS & FACTUAL ALTERNATIVES
    # -------------------------------------------------------------------------
    def test_route_impact_assessment_and_alternatives(self):
        """Verify assessing a disrupted route returns factual deltas and 'Alternative available'."""
        impact = incident_impact_service.assess_route("500D")
        self.assertTrue(impact.has_disruption)
        self.assertGreaterEqual(impact.delay_estimate_minutes, 15)
        self.assertTrue(impact.alternative_available)
        self.assertGreater(len(impact.alternatives), 0)

        alt = impact.alternatives[0]
        self.assertEqual(alt.recommendation_label, "Alternative available")
        self.assertGreater(alt.additional_walk_meters, 0)
        self.assertGreater(alt.additional_travel_time_minutes, 0)
        self.assertGreaterEqual(alt.transfers_required, 0)
        self.assertGreater(alt.estimated_fare, 0)

    def test_clean_route_impact_assessment(self):
        """Verify assessing a route with no incidents returns has_disruption=False."""
        impact = incident_impact_service.assess_route("CLEAN_ROUTE_999")
        self.assertFalse(impact.has_disruption)
        self.assertEqual(impact.delay_estimate_minutes, 0)
        self.assertEqual(len(impact.incidents), 0)

    def test_stop_impact_assessment(self):
        """Verify assessing stop with incident returns active disruption."""
        impact = incident_impact_service.assess_stop("Central Silk Board")
        self.assertTrue(impact.has_disruption)
        self.assertIn("Silk Board", impact.disruption_summary or "")

    # -------------------------------------------------------------------------
    # 3. EVALUATOR SIMULATION OVERRIDES & API
    # -------------------------------------------------------------------------
    def test_simulation_override_api(self):
        """Verify evaluator override sets scenario and demo reset clears it."""
        # Post override
        payload = {
            "corridor": "Tin Factory",
            "route_number": "KIA-8",
            "incident_type": "BREAKDOWN",
            "severity": "CRITICAL",
            "delay_minutes": 30,
            "description": "Bus breakdown blocking flyover lane.",
        }
        res = self.client.post("/api/incidents/simulation/override", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")

        # Verify route assessment reflects override
        impact = incident_impact_service.assess_route("KIA-8")
        self.assertTrue(impact.has_disruption)
        self.assertGreaterEqual(impact.delay_estimate_minutes, 30)

        # Demo reset clears overrides
        res_reset = self.client.post("/api/demo/reset")
        self.assertEqual(res_reset.status_code, 200)
        self.assertEqual(len(incident_service.get_simulation_overrides()), 0)

    # -------------------------------------------------------------------------
    # 4. REST API ENDPOINTS
    # -------------------------------------------------------------------------
    def test_incidents_rest_endpoints(self):
        """Verify GET /api/incidents, /api/incidents/active, /api/incidents/route/{r}."""
        res_all = self.client.get("/api/incidents")
        self.assertEqual(res_all.status_code, 200)
        self.assertIsInstance(res_all.json(), list)

        res_active = self.client.get("/api/incidents/active")
        self.assertEqual(res_active.status_code, 200)
        self.assertIsInstance(res_active.json(), list)

        res_route = self.client.get("/api/incidents/route/500D")
        self.assertEqual(res_route.status_code, 200)
        data_route = res_route.json()
        self.assertTrue(data_route["has_disruption"])
        self.assertIn("incidents", data_route)

        res_stop = self.client.get("/api/incidents/stop/Central%20Silk%20Board")
        self.assertEqual(res_stop.status_code, 200)
        self.assertTrue(res_stop.json()["has_disruption"])

        # Specific incident details
        inc_id = res_active.json()[0]["id"]
        res_detail = self.client.get(f"/api/incidents/{inc_id}")
        self.assertEqual(res_detail.status_code, 200)
        self.assertIn("incident", res_detail.json())

    # -------------------------------------------------------------------------
    # 5. ACTIVE JOURNEY CORRIDOR DISRUPTION & TRANSFER RISK
    # -------------------------------------------------------------------------
    def test_active_journey_disruption_and_transfer_risk(self):
        """Verify active journeys evaluate corridor disruption and transfer risk."""
        # Start a transfer journey that involves 500D
        create_req = ActiveJourneyCreateRequest(
            route_number="500D",
            bus_id="KA-01-F-5001",
            origin="Hebbal",
            destination="Electronic City",
            is_transfer_journey=True,
            connecting_route="356",
        )
        journey = asyncio.run(active_journey_service.start_journey(create_req))
        self.assertIsNotNone(journey)
        self.assertTrue(journey.has_disruption)
        self.assertIsNotNone(journey.incident_impact)

        # Get active journey and check transfer risk evaluation
        active = asyncio.run(active_journey_service.get_active_journey())
        self.assertIsNotNone(active)
        self.assertTrue(active.is_transfer_at_risk)
        self.assertIn("Transfer buffer at risk", active.transfer_risk_warning or "")

    # -------------------------------------------------------------------------
    # 6. AI CHAT INTENTS & GROUNDED DISCLOSURES
    # -------------------------------------------------------------------------
    def test_ai_route_disruption_intent(self):
        """Verify AI responds to disruption queries with grounded advice."""
        req = AIChatRequest(message="Are there any disruptions on route 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "route_disruption")
        self.assertIn("500D", res.answer)
        self.assertIn("Waterlogging", res.answer)
        self.assertIn("SIMULATED TRANSIT ALERT", res.answer)

    def test_ai_alternative_advice_intent(self):
        """Verify AI provides factual alternatives when requested."""
        req = AIChatRequest(message="What alternative route can I take instead of 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "alternative_after_disruption")
        self.assertIn("Alternative available", res.answer)
        self.assertIn("Route", res.answer)

    def test_ai_transfer_risk_intent(self):
        """Verify AI handles transfer risk inquiries."""
        req = AIChatRequest(message="Is my transfer at risk due to delay?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "transfer_risk")
        self.assertIn("transfer", res.answer.lower())

    # -------------------------------------------------------------------------
    # 7. OBSERVABILITY & SYSTEM STATUS
    # -------------------------------------------------------------------------
    def test_system_status_and_observability(self):
        """Verify /api/system/status includes Phase 37 modules and diagnostics."""
        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        module_names = [m["name"] for m in data.get("modules", [])]
        self.assertIn("Incident Engine", module_names)
        self.assertIn("Service Alert Engine", module_names)
        self.assertIn("Disruption Impact Engine", module_names)
        self.assertIn("Alternative Journey Engine", module_names)

        self.assertIn("incidents", data.get("diagnostics", {}))
        self.assertGreater(data["diagnostics"]["incidents"]["active_count"], 0)


if __name__ == "__main__":
    unittest.main()
