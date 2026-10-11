import asyncio
import unittest

from app.models.transit import AIChatRequest, JourneySearchRequest
from app.services.crowd_prediction_service import CrowdPredictionService
from app.services.ai_service import AIService
from app.services.journey_service import JourneyService


class TestCrowdPrediction(unittest.TestCase):
    """
    Test suite for BMTC Passenger-Flow and Seat Availability Prediction engine.
    Validates mathematical bounds, tier classifications, AI grounding,
    and fallback safety.
    """

    def test_1_crowd_tier_thresholds(self):
        self.assertEqual(CrowdPredictionService.get_crowd_tier(30), "Comfortable")
        self.assertEqual(CrowdPredictionService.get_crowd_tier(49), "Comfortable")
        self.assertEqual(CrowdPredictionService.get_crowd_tier(50), "Moderate")
        self.assertEqual(CrowdPredictionService.get_crowd_tier(74), "Moderate")
        self.assertEqual(CrowdPredictionService.get_crowd_tier(75), "Crowded")
        self.assertEqual(CrowdPredictionService.get_crowd_tier(89), "Crowded")
        self.assertEqual(CrowdPredictionService.get_crowd_tier(90), "Very Crowded")
        self.assertEqual(CrowdPredictionService.get_crowd_tier(100), "Very Crowded")

    def test_2_predict_for_bus_valid(self):
        res = asyncio.run(CrowdPredictionService.predict_for_bus("bus-500d-1"))
        self.assertIsNotNone(res)
        self.assertEqual(res.bus_id, "bus-500d-1")
        self.assertEqual(res.route_number, "500D")
        self.assertGreater(len(res.predictions), 0)
        self.assertIn("Estimated", res.disclaimer)

    def test_3_predict_passenger_capacity_clamped(self):
        res = asyncio.run(CrowdPredictionService.predict_for_bus("bus-500d-1"))
        self.assertIsNotNone(res)
        for stop_pred in res.predictions:
            self.assertGreaterEqual(stop_pred.estimated_passengers, 0)
            self.assertLessEqual(stop_pred.estimated_passengers, res.capacity)
            self.assertGreaterEqual(stop_pred.occupancy_percent, 0)
            self.assertLessEqual(stop_pred.occupancy_percent, 100)

    def test_4_predict_seats_non_negative(self):
        res = asyncio.run(CrowdPredictionService.predict_for_bus("bus-356-1"))
        self.assertIsNotNone(res)
        for stop_pred in res.predictions:
            self.assertGreaterEqual(stop_pred.estimated_seats, 0)
            self.assertLessEqual(stop_pred.estimated_seats, res.capacity)
            self.assertEqual(stop_pred.estimated_seats, res.capacity - stop_pred.estimated_passengers)

    def test_5_predict_stop_progression_and_confidence(self):
        res = asyncio.run(CrowdPredictionService.predict_for_bus("bus-500d-1"))
        self.assertIsNotNone(res)
        prev_step = 0
        prev_conf = 1.0
        for p in res.predictions:
            self.assertGreater(p.stops_ahead, prev_step)
            prev_step = p.stops_ahead
            self.assertLessEqual(p.confidence, prev_conf)
            prev_conf = p.confidence

    def test_6_predict_unknown_bus_returns_none(self):
        res = asyncio.run(CrowdPredictionService.predict_for_bus("bus-nonexistent-999"))
        self.assertIsNone(res)

    def test_7_ai_chat_seat_query_includes_prediction(self):
        req = AIChatRequest(message="Will I get a seat on 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "seat_availability")
        self.assertIsNotNone(res.prediction)
        self.assertIn("predictions", res.prediction)
        self.assertGreater(len(res.prediction["predictions"]), 0)
        self.assertIn("seat", res.answer.lower())

    def test_8_ai_chat_occupancy_query_includes_prediction(self):
        req = AIChatRequest(message="How crowded is 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "bus_occupancy")
        self.assertIsNotNone(res.prediction)
        self.assertIn("current_crowd_tier", res.prediction)
        self.assertIn("Forecast", res.answer)

    def test_9_prediction_disclaimer_present(self):
        res = asyncio.run(CrowdPredictionService.predict_for_bus("bus-500d-1"))
        self.assertIsNotNone(res)
        self.assertIn("Estimated crowd", res.disclaimer)
        self.assertIn("Actual occupancy may vary", res.disclaimer)

    def test_10_journey_search_includes_crowd_predictions(self):
        req = JourneySearchRequest(origin="Silk Board", destination="Majestic")
        res = asyncio.run(JourneyService.search_journey(req))
        self.assertGreater(len(res.options), 0)
        first_opt = res.options[0]
        self.assertIsNotNone(first_opt.predicted_occupancy_percent)
        self.assertIsNotNone(first_opt.predicted_seats)
        self.assertGreaterEqual(first_opt.predicted_seats, 0)


if __name__ == "__main__":
    unittest.main()
