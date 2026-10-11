import unittest
import asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.models.transit import (
    PredictionDataSource,
    PredictionConfidence,
    PredictionType,
    AIChatRequest,
)
from app.services.prediction_service import prediction_service
from app.services.personalization_service import personalization_service
from app.services.ai_service import AIService
from app.models.personalization import SavedJourneyCreateDto, FavoriteRouteCreateDto


class TestPhase38PredictionIntelligence(unittest.TestCase):
    """
    Verification suite for Phase 38: Smart Predictive Commuter Intelligence.
    Tests arrival ETA predictions, journey duration breakdowns, transfer feasibility,
    crowd forecasting, route delay predictions, personalized insights, and AI integration.
    """

    def setUp(self):
        self.client = TestClient(app)
        prediction_service.reset()
        personalization_service.reset()

    def tearDown(self):
        prediction_service.reset()
        personalization_service.reset()

    def test_predict_arrival_estimated_and_realtime(self):
        """Verify predict_arrival returns transparent data source, confidence, and disclosure."""
        pred = asyncio.run(prediction_service.predict_arrival("500D", "Central Silk Board"))
        self.assertIsNotNone(pred)
        self.assertEqual(pred.route_number, "500D")
        self.assertEqual(pred.prediction_type, PredictionType.ARRIVAL.value)
        self.assertIn(pred.data_source, [PredictionDataSource.HISTORICAL_ESTIMATE.value, PredictionDataSource.VERIFIED_REALTIME.value, PredictionDataSource.SIMULATED.value])
        self.assertIn("Estimated", pred.disclosure)
        self.assertGreater(len(pred.factors), 0)

        # Test simulation override
        prediction_service.set_simulation_override(source=PredictionDataSource.VERIFIED_REALTIME.value, confidence=PredictionConfidence.HIGH.value)
        pred_override = asyncio.run(prediction_service.predict_arrival("500D", "Hebbal"))
        self.assertEqual(pred_override.data_source, PredictionDataSource.VERIFIED_REALTIME.value)
        self.assertEqual(pred_override.confidence, PredictionConfidence.HIGH.value)

    def test_predict_journey_duration_breakdown(self):
        """Verify predict_journey_duration returns factual walk, bus, transfer, and incident breakdown."""
        pred = prediction_service.predict_journey_duration("Central Silk Board", "Hebbal", "500D")
        self.assertIsNotNone(pred)
        self.assertEqual(pred.prediction_type, PredictionType.JOURNEY_DURATION.value)
        self.assertIsNotNone(pred.breakdown)
        self.assertIn("walking_minutes", pred.breakdown)
        self.assertIn("transit_minutes", pred.breakdown)
        self.assertIn("incident_adjustment_minutes", pred.breakdown)
        self.assertIn("total_predicted_minutes", pred.breakdown)
        self.assertEqual(pred.predicted_duration_minutes, pred.breakdown["total_predicted_minutes"])
        self.assertIn("Estimated journey duration", pred.disclosure)

    def test_predict_transfer_feasibility(self):
        """Verify predict_transfer_success uses conditional language and never claims certainty."""
        pred = asyncio.run(prediction_service.predict_transfer_success("test-journey-id"))
        self.assertIsNotNone(pred)
        self.assertEqual(pred.prediction_type, PredictionType.TRANSFER_SUCCESS.value)
        self.assertNotIn("definitely", pred.disclosure.lower())
        self.assertIn("feasible", pred.disclosure.lower())

    def test_predict_crowd_and_seat_availability(self):
        """Verify crowd predictions preserve canonical disclosures and never fabricate passenger counts."""
        pred = prediction_service.predict_crowd("500D")
        self.assertIsNotNone(pred)
        self.assertEqual(pred.prediction_type, PredictionType.CROWD.value)
        self.assertTrue("passenger occupancy" in pred.disclosure.lower() and "unavailable" in pred.disclosure.lower())

    def test_predict_route_delay(self):
        """Verify predict_route_delay correlates with incident intelligence."""
        pred = prediction_service.predict_route_delay("500D")
        self.assertIsNotNone(pred)
        self.assertEqual(pred.prediction_type, PredictionType.DELAY.value)
        self.assertGreaterEqual(pred.predicted_delay_minutes, 0)

    def test_personalized_commuter_insights(self):
        """Verify non-sensitive commuter insights derived from saved journeys and favorite routes."""
        personalization_service.create_saved_journey(
            SavedJourneyCreateDto(
                origin="Koramangala",
                destination="Electronic City",
                route_number="356",
            )
        )
        personalization_service.add_favorite_route(
            FavoriteRouteCreateDto(
                route_number="500D",
                origin="Central Silk Board",
                destination="Hebbal",
            )
        )

        insights = prediction_service.get_commuter_insights()
        self.assertGreaterEqual(len(insights), 2)
        sj_insight = next((i for i in insights if i["type"] == "saved_journey_duration"), None)
        self.assertIsNotNone(sj_insight)
        self.assertIn("usually takes about 35–40 min", sj_insight["message"])

    def test_predictions_rest_api_endpoints(self):
        """Verify GET /api/predictions/* endpoints."""
        res_arr = self.client.get("/api/predictions/arrival/500D/Central%20Silk%20Board")
        self.assertEqual(res_arr.status_code, 200)
        self.assertEqual(res_arr.json()["prediction_type"], "ARRIVAL")

        res_dur = self.client.get("/api/predictions/journey?origin=Silk%20Board&destination=Hebbal&route_number=500D")
        self.assertEqual(res_dur.status_code, 200)
        self.assertEqual(res_dur.json()["prediction_type"], "JOURNEY_DURATION")

        res_xfer = self.client.get("/api/predictions/transfer/default")
        self.assertEqual(res_xfer.status_code, 200)
        self.assertEqual(res_xfer.json()["prediction_type"], "TRANSFER_SUCCESS")

        res_delay = self.client.get("/api/predictions/route/500D")
        self.assertEqual(res_delay.status_code, 200)
        self.assertEqual(res_delay.json()["prediction_type"], "DELAY")

        res_ins = self.client.get("/api/predictions/insights")
        self.assertEqual(res_ins.status_code, 200)
        self.assertIsInstance(res_ins.json(), list)

    def test_ai_prediction_intents(self):
        """Verify AI natural language responses for Phase 38 prediction intents."""
        req_arr = AIChatRequest(message="What is the predicted arrival for 500D?")
        res_arr = asyncio.run(AIService.process_chat(req_arr))
        self.assertEqual(res_arr.intent, "predicted_arrival")
        self.assertIn("Predicted arrival", res_arr.answer)
        self.assertIn("Estimated transit prediction", res_arr.answer)

        req_dur = AIChatRequest(message="What is the predicted duration of my trip?")
        res_dur = asyncio.run(AIService.process_chat(req_dur))
        self.assertEqual(res_dur.intent, "predicted_duration")
        self.assertIn("Estimated journey duration", res_dur.answer)

        req_conf = AIChatRequest(message="How confident is the prediction?")
        res_conf = asyncio.run(AIService.process_chat(req_conf))
        self.assertEqual(res_conf.intent, "prediction_confidence")
        self.assertIn("MEDIUM", res_conf.answer)


if __name__ == "__main__":
    unittest.main()
