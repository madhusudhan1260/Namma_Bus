import asyncio
import unittest
from unittest.mock import patch

from app.models.transit import AIChatRequest
from app.services.ai_service import AIService, IntentDetector
from app.services.ai_provider import MockAIProvider


class TestAIService(unittest.TestCase):
    """
    Test suite for NammaBlr Assistant covering all required intent scenarios,
    transit context assembly, error handling, and zero-hallucination compliance.
    """

    def test_intent_detection(self):
        self.assertEqual(IntentDetector.detect_intent("Where is my bus?"), "bus_location")
        self.assertEqual(IntentDetector.detect_intent("Where is 500D?"), "bus_location")
        self.assertEqual(IntentDetector.detect_intent("When will 500D arrive?"), "bus_eta")
        self.assertEqual(IntentDetector.detect_intent("How crowded is 500D?"), "bus_occupancy")
        self.assertEqual(IntentDetector.detect_intent("Will I get a seat on 500D?"), "seat_availability")
        self.assertEqual(IntentDetector.detect_intent("Where does 356 go?"), "bus_route")
        self.assertEqual(IntentDetector.detect_intent("How do I go from Silk Board to Majestic?"), "journey_search")
        self.assertEqual(IntentDetector.detect_intent("Next bus to Majestic"), "next_bus")
        self.assertEqual(IntentDetector.detect_intent("What can you do?"), "general")

    def test_entity_extraction(self):
        self.assertEqual(IntentDetector.extract_route_number("Where is 500D?"), "500D")
        self.assertEqual(IntentDetector.extract_route_number("Track bus 356"), "356")
        self.assertEqual(IntentDetector.extract_route_number("Is 201R an AC bus?"), "201R")
        self.assertEqual(IntentDetector.extract_route_number("When is KIA-8 coming?"), "KIA-8")
        self.assertEqual(IntentDetector.extract_route_number("G-2 crowd status"), "G-2")

        orig, dest = IntentDetector.extract_journey_endpoints("from Silk Board to Majestic")
        self.assertEqual(orig, "Silk Board")
        self.assertEqual(dest, "Majestic")

    def test_1_where_is_500d(self):
        req = AIChatRequest(message="Where is 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "bus_location")
        self.assertEqual(res.route_number, "500D")
        self.assertIn("500D", res.answer)
        self.assertIsNotNone(res.data)
        self.assertEqual(res.data["routeNumber"], "500D")

    def test_2_when_will_500d_arrive(self):
        req = AIChatRequest(message="When will 500D arrive?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "bus_eta")
        self.assertEqual(res.route_number, "500D")
        self.assertIn("minutes", res.answer.lower())
        self.assertIsNotNone(res.data)
        self.assertIn("etaMinutes", res.data)

    def test_3_how_crowded_is_500d(self):
        req = AIChatRequest(message="How crowded is 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "bus_occupancy")
        self.assertEqual(res.route_number, "500D")
        self.assertIn("% occupied", res.answer)
        self.assertIsNotNone(res.data)
        self.assertIn("occupancyPercent", res.data)

    def test_4_will_i_get_a_seat_on_500d(self):
        req = AIChatRequest(message="Will I get a seat on 500D?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "seat_availability")
        self.assertEqual(res.route_number, "500D")
        self.assertIn("seats", res.answer.lower())
        self.assertIsNotNone(res.data)
        self.assertIn("seatsEstimated", res.data)

    def test_5_where_does_356_go(self):
        req = AIChatRequest(message="Where does 356 go?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "bus_route")
        self.assertEqual(res.route_number, "356")
        self.assertIn("356", res.answer)
        self.assertIn("Shivajinagar", res.answer)

    def test_6_journey_silk_board_to_majestic(self):
        req = AIChatRequest(message="How do I go from Silk Board to Majestic?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "journey_search")
        self.assertIn("Silk Board", res.answer)
        self.assertIn("Majestic", res.answer)
        self.assertIsNotNone(res.data)

    def test_7_unknown_bus(self):
        req = AIChatRequest(message="Where is bus 999X?")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "unknown_bus")
        self.assertIn("999X", res.answer)
        self.assertIn("couldn't find", res.answer.lower())

    def test_8_empty_message(self):
        req = AIChatRequest(message="   ")
        res = asyncio.run(AIService.process_chat(req))
        self.assertEqual(res.intent, "general")
        self.assertIn("Please ask a question", res.answer)

    def test_9_transit_data_fallback_resilience(self):
        # Test that MockAIProvider handles empty/missing transit context gracefully
        provider = MockAIProvider()
        ans = asyncio.run(provider.generate_response("Where is my bus?", "bus_location", {}))
        self.assertIn("couldn't locate", ans)

        ans2 = asyncio.run(provider.generate_response("How crowded is it?", "bus_occupancy", {}))
        self.assertIn("don't have real-time crowd data", ans2)


if __name__ == "__main__":
    unittest.main()
