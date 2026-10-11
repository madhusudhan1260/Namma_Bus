import unittest
import asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.models.transit import (
    RecommendationType,
    CommuterRecommendation,
    AIChatRequest,
)
from app.services.commuter_recommendation_service import commuter_recommendation_service
from app.services.personalization_service import personalization_service
from app.services.incident_service import incident_service
from app.services.ai_service import AIService
from app.models.personalization import SavedJourneyCreateDto, FavoriteRouteCreateDto


class TestPhase39RecommendationIntelligence(unittest.TestCase):
    """
    Verification suite for Phase 39: Smart Personalized Commuter & Route Recommendation Engine.
    Tests multi-factor factual comparisons, saved/favorite recommendations, disruption recovery,
    notification deduplication, REST endpoints, and AI grounded recommendations.
    """

    def setUp(self):
        self.client = TestClient(app)
        commuter_recommendation_service.reset()
        personalization_service.reset()
        incident_service.reset()

    def tearDown(self):
        commuter_recommendation_service.reset()
        personalization_service.reset()
        incident_service.reset()

    def test_factual_recommendations_avoid_subjective_best(self):
        """Verify recommendations provide factual dimensions and avoid universal 'best' claims."""
        recs = commuter_recommendation_service.get_recommendations()
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertNotIn("universally best", r.title.lower())
            self.assertIsNotNone(r.comparison_factors)
            self.assertTrue(any(w in r.disclosure for w in ["Factual", "SIMULATED", "Estimated", "Accessible"]))

    def test_saved_journey_and_favorite_route_recommendations(self):
        """Verify saved journeys and favorites generate contextual commute options."""
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

        saved_recs = commuter_recommendation_service.get_saved_journey_recommendations()
        self.assertGreaterEqual(len(saved_recs), 1)
        self.assertTrue(any("Koramangala" in r.title for r in saved_recs))

        fav_recs = commuter_recommendation_service.get_favorite_route_recommendations()
        self.assertGreaterEqual(len(fav_recs), 1)
        self.assertIn("500D", fav_recs[0].title)

    def test_disruption_recovery_alternatives_comparison(self):
        """Verify disrupted routes generate comparative alternatives with delta walk, time, and fare."""
        # 500D is disrupted by Silk Board waterlogging in baseline
        alt_recs = commuter_recommendation_service.get_disruption_recommendations("500D")
        self.assertGreater(len(alt_recs), 0)

        first_alt = alt_recs[0]
        self.assertEqual(first_alt.type, RecommendationType.DISRUPTION_RECOVERY.value)
        self.assertIn("Alternative available", first_alt.reason)
        factors = first_alt.comparison_factors
        self.assertIn("additional_walk_meters", factors)
        self.assertIn("additional_time_minutes", factors)
        self.assertIn("transfers", factors)
        self.assertIn("fare_rupees", factors)
        self.assertGreater(factors["additional_walk_meters"], 0)

    def test_notification_deduplication(self):
        """Verify notification intelligence deduplicates alerts within sliding window."""
        key = "alert-silk-board-waterlogging"
        # First check: not duplicate
        self.assertFalse(commuter_recommendation_service.should_deduplicate_notification(key, window_seconds=300))
        # Second check immediately: is duplicate
        self.assertTrue(commuter_recommendation_service.should_deduplicate_notification(key, window_seconds=300))
        # After reset: not duplicate
        commuter_recommendation_service.reset()
        self.assertFalse(commuter_recommendation_service.should_deduplicate_notification(key, window_seconds=300))

    def test_recommendations_rest_api_endpoints(self):
        """Verify GET /api/recommendations/* endpoints."""
        res_all = self.client.get("/api/recommendations")
        self.assertEqual(res_all.status_code, 200)
        self.assertIsInstance(res_all.json(), list)

        res_j = self.client.get("/api/recommendations/journey?origin=Silk%20Board&destination=Hebbal")
        self.assertEqual(res_j.status_code, 200)

        res_r = self.client.get("/api/recommendations/route/500D")
        self.assertEqual(res_r.status_code, 200)

        res_saved = self.client.get("/api/recommendations/saved")
        self.assertEqual(res_saved.status_code, 200)

        res_fav = self.client.get("/api/recommendations/favorites")
        self.assertEqual(res_fav.status_code, 200)

        res_disrupt = self.client.get("/api/recommendations/disruption/500D")
        self.assertEqual(res_disrupt.status_code, 200)

    def test_ai_recommendation_intents(self):
        """Verify AI natural language responses for Phase 39 recommendation intents."""
        req_take = AIChatRequest(message="What should I take to go to Hebbal?")
        res_take = asyncio.run(AIService.process_chat(req_take))
        self.assertEqual(res_take.intent, "what_should_i_take")
        self.assertIn("500D", res_take.answer)
        self.assertIn("factual comparison", res_take.answer.lower())

        req_alt = AIChatRequest(message="What is the disruption alternative for 500D?")
        res_alt = asyncio.run(AIService.process_chat(req_alt))
        self.assertEqual(res_alt.intent, "disruption_alternative")
        self.assertIn("Alternative", res_alt.answer)

        req_sum = AIChatRequest(message="Give me my commute summary for today")
        res_sum = asyncio.run(AIService.process_chat(req_sum))
        self.assertEqual(res_sum.intent, "commute_summary")
        self.assertIn("Transit Today", res_sum.answer)


if __name__ == "__main__":
    unittest.main()
