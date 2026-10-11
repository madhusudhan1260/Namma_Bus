"""The ನಮ್ಮ Bus assistant answers only from real network/live data it is given (no invented buses)."""

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace

from app.services.network_assistant import Sources, answer

sys.path.insert(0, os.path.dirname(__file__))


def run(coro):
    return asyncio.run(coro)


def make_sources(live=True, vehicles=None, route=None, plans=None, stops=None):
    async def v(route_no=None):
        vs = vehicles or []
        if route_no:
            vs = [x for x in vs if x.route_number == route_no]
        return SimpleNamespace(live_connected=live and bool(vehicles), count=len(vs), vehicles=vs)

    async def r(token):
        return route if route and token.upper() == route["routeNumber"] else None

    async def j(a, b):
        return {"plans": plans or []}

    async def s(q):
        return stops or []

    return Sources(v, r, j, s)


BUS = SimpleNamespace(vehicle_id="13251", vehicle_number="KA57F1206", route_number="V-300MV", destination="Sir M Visvesvaraya Terminal",
                      next_stop=SimpleNamespace(stop_name="Maharani College"), freshness="LIVE", freshness_seconds=40)
ROUTE = {"routeNumber": "500-D", "origin": "Hebbala Bridge", "destination": "Central Silk Board",
         "directions": [{"destinationName": "Central Silk Board", "stopCount": 36}, {"destinationName": "Hebbala Bridge", "stopCount": 36}]}


class NetworkAssistantTests(unittest.TestCase):
    def test_live_bus_found_from_feed(self):
        r = run(answer("where is KA 57 F 1206", "EN", make_sources(vehicles=[BUS])))
        self.assertIn("V-300MV", r["answer"])
        self.assertIn("Maharani College", r["answer"])
        self.assertEqual(r["actions"][0]["href"], "/(tabs)/map?vehicle=13251")

    def test_live_feed_unavailable_is_honest(self):
        r = run(answer("where is KA57F1206", "EN", make_sources(live=False)))
        self.assertEqual(r["kind"], "unavailable")
        self.assertIn("unavailable", r["answer"])

    def test_unknown_bus_not_invented(self):
        r = run(answer("where is KA01AB1234", "EN", make_sources(vehicles=[BUS])))
        self.assertEqual(r["kind"], "not_found")

    def test_route_details_and_kannada(self):
        r = run(answer("500-D", "KN", make_sources(route=ROUTE)))
        self.assertIn("ಮಾರ್ಗ 500-D", r["answer"])
        self.assertIn("36", r["answer"])
        self.assertTrue(any(a["href"] == "/access/buy?route=500-D" for a in r["actions"]))

    def test_journey_from_plans(self):
        plans = [{"legs": [{"routeNumber": "500-D", "stopCount": 37}], "totalDurationMinutes": 113, "transferCount": 0}]
        r = run(answer("Hebbal to Silk Board", "EN", make_sources(plans=plans)))
        self.assertIn("500-D", r["answer"])
        self.assertIn("37 stops", r["answer"])
        empty = run(answer("Hebbal to Nowhere", "EN", make_sources(plans=[])))
        self.assertEqual(empty["kind"], "not_found")

    def test_stop_search_only_real_matches(self):
        stops = [{"name": "Kempegowda Bus Station(Majestic/KBS)"}, {"name": "Central Silk Board"}]
        r = run(answer("Majestic stop", "EN", make_sources(stops=stops)))
        self.assertIn("Kempegowda", r["answer"])
        self.assertNotIn("Silk Board", r["answer"])  # fallback/popular stops are not presented as matches
        nonsense = run(answer("qwzxv", "EN", make_sources(stops=stops)))  # was "hello", which is now a greeting
        self.assertEqual(nonsense["kind"], "not_found")
        self.assertNotIn("Kempegowda", nonsense["answer"])


class AssistantUnderstandingTests(unittest.TestCase):
    """Intent accuracy on labelled questions (English, Kanglish, Kannada) and grounded answers per intent."""

    def _score(self, cases):
        from app.services.network_assistant import classify

        fails = []
        for q, intent, slots in cases:
            r = classify(q)
            if not (r.name == intent and all(r.slots.get(k) == v for k, v in slots.items())):
                fails.append(f"{q!r}: expected {intent} {slots}, got {r.name} {r.slots}")
        return len(cases) - len(fails), fails

    def test_eval_set_all_correct(self):
        from tests_assistant_sets import EVAL_SET

        ok, fails = self._score(EVAL_SET)
        self.assertEqual(fails, [], f"{ok}/{len(EVAL_SET)}")

    def test_holdout_generalisation(self):
        from tests_assistant_sets import HOLDOUT_SET

        ok, fails = self._score(HOLDOUT_SET)
        self.assertGreaterEqual(ok / len(HOLDOUT_SET), 0.85, fails)

    def test_fare_answer_uses_stage_fares_per_leg(self):
        plans = [{"legs": [{"routeNumber": "500-D", "stopCount": 20, "fromStop": {"id": "1"}, "toStop": {"id": "2"}},
                           {"routeNumber": "335-E", "stopCount": 5, "fromStop": {"id": "2"}, "toStop": {"id": "3"}}],
                  "totalDurationMinutes": 60, "transferCount": 1}]
        quotes = {"500-D": SimpleNamespace(fares={"ADULT": 23, "CHILD": 12, "SENIOR": 18}, distance_km=9.4, stage=5, unit_fare=23),
                  "335-E": SimpleNamespace(fares={"ADULT": 12, "CHILD": 6, "SENIOR": 9}, distance_km=3.1, stage=2, unit_fare=12)}
        src = make_sources(plans=plans)

        async def fare(route, a, b):
            return quotes[route]

        src.fare = fare
        r = run(answer("fare from hebbal to majestic", "EN", src))
        self.assertEqual(r["intent"], "FARE")
        self.assertIn("Adult ₹35", r["answer"])  # 23 + 12: each bus is a separate ticket
        self.assertIn("Child ₹18", r["answer"])
        self.assertIn("12.5 km", r["answer"])
        child = run(answer("child fare from hebbal to majestic", "KN", src))
        self.assertIn("ಮಕ್ಕಳು ₹18", child["answer"])

    def test_routes_at_stop_from_real_stop_data(self):
        stops = [{"id": "20921", "name": "Kempegowda Bus Station", "routes": ["333-C", "171-G", "365-P"]}]
        r = run(answer("which bus goes to majestic", "EN", make_sources(stops=stops)))
        self.assertEqual(r["intent"], "ROUTES_TO")
        self.assertIn("333-C, 171-G, 365-P", r["answer"])
        self.assertEqual(r["actions"][0]["href"], "/(tabs)/map?route=333-C")
        none = run(answer("buses at qwzxv", "EN", make_sources(stops=stops)))
        self.assertEqual(none["kind"], "not_found")

    def test_live_count_and_timing_honesty(self):
        r = run(answer("how many buses are running", "EN", make_sources(vehicles=[BUS])))
        self.assertIn("1 BMTC buses", r["answer"])
        off = run(answer("live buses", "EN", make_sources(live=False)))
        self.assertEqual(off["kind"], "unavailable")
        t = run(answer("500D timings", "EN", make_sources(route=ROUTE)))
        self.assertIn("can't give times", t["answer"])  # never invents arrival times
        self.assertTrue(any(a["href"] == "/(tabs)/map?route=500-D" for a in t["actions"]))

    def test_smalltalk_and_topics(self):
        self.assertEqual(run(answer("namaskara", "KN", make_sources()))["intent"], "GREETING")
        free = run(answer("is bus free for women", "EN", make_sources()))
        self.assertIn("Gender alone never makes a ticket free", free["answer"])
        self.assertEqual(free["actions"][0]["href"], "/access/aadhaar")
        info = run(answer("minimum fare", "EN", make_sources()))
        self.assertIn("≤2 km ₹6", info["answer"])


if __name__ == "__main__":
    unittest.main()
