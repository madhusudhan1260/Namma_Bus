"""
NammaRoute integration tests: direction, current stop, freshness, realtime endpoints, error handling.

All realtime payloads here are SYNTHETIC TEST DATA built in this file. They exercise the authorized
GTFS-RT path of BMTCTransitDataProvider; they are not BMTC data and prove nothing about a live feed.
"""

import asyncio
import time
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.core import middleware
from app.core.config import settings
from app.services import bmtc_provider as bmtc_module
from app.services.bmtc_provider import bmtc_provider
from app.services.gtfs.repository import gtfs_repository
from app.services.vehicle_tracking_service import (
    DirectionPattern,
    OrderedStop,
    VehicleTrackingService,
    build_direction_patterns,
    detect_stop,
    freshness_state,
    parse_vehicle_timestamp,
    select_direction,
    vehicle_tracking_service,
)

CANONICAL = "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED"

# Demo-catalog stops on route 500D (Silk Board → … → Majestic)
IBBLUR = (12.9189, 77.6505)
BELLANDUR = (12.9260, 77.6762)
MID_IBBLUR_BELLANDUR = (12.9222, 77.6630)


def entity(vid, lat, lon, bearing=None, speed=None, age=10, route="500D", ts=True):
    veh = {"vehicle": {"id": vid}, "trip": {"route_id": route}, "position": {"latitude": lat, "longitude": lon}}
    if bearing is not None:
        veh["position"]["bearing"] = bearing
    if speed is not None:
        veh["position"]["speed"] = speed
    if ts:
        veh["timestamp"] = int(time.time() - age)
    return {"id": vid, "vehicle": veh}


class _BmtcTestMode:
    """Switches the provider factory to the (synthetic) authorized feed for one test."""

    def __enter__(self):
        self.saved = (settings.transit_provider, bmtc_provider.endpoint, bmtc_provider.api_key,
                      dict(bmtc_provider._buses), dict(getattr(bmtc_provider, "_raw_positions", {})),
                      bmtc_provider._last_updated_at, bmtc_provider._consecutive_failures)
        settings.transit_provider = "bmtc"
        bmtc_provider.endpoint = "https://feeds.example.invalid/gtfs-rt"
        bmtc_provider.api_key = "test-key-not-real"
        vehicle_tracking_service.reset()
        return self

    def __exit__(self, *exc):
        (settings.transit_provider, bmtc_provider.endpoint, bmtc_provider.api_key, buses, raw,
         bmtc_provider._last_updated_at, bmtc_provider._consecutive_failures) = self.saved
        bmtc_provider._buses = buses
        bmtc_provider._raw_positions = raw
        bmtc_provider.last_error_code = None
        vehicle_tracking_service.reset()


class TestFreshnessAndParsing(unittest.TestCase):
    def test_freshness_thresholds(self):
        self.assertEqual(freshness_state(0), "LIVE")
        self.assertEqual(freshness_state(60), "LIVE")
        self.assertEqual(freshness_state(61), "RECENT")
        self.assertEqual(freshness_state(120), "RECENT")
        self.assertEqual(freshness_state(121), "STALE")
        self.assertEqual(freshness_state(300), "STALE")
        self.assertIsNone(freshness_state(301))

    def test_timestamps_never_default_to_now(self):
        self.assertIsNone(parse_vehicle_timestamp(None))
        self.assertIsNone(parse_vehicle_timestamp(""))
        self.assertIsNone(parse_vehicle_timestamp("not-a-date"))
        self.assertIsNone(parse_vehicle_timestamp(0))
        ts = int(time.time())
        self.assertEqual(int(parse_vehicle_timestamp(ts).timestamp()), ts)
        self.assertEqual(int(parse_vehicle_timestamp(ts * 1000).timestamp()), ts)
        self.assertEqual(parse_vehicle_timestamp("2026-01-01T10:00:00").tzinfo is not None, True)


class TestDirectionAndStops(unittest.TestCase):
    def setUp(self):
        gtfs_repository.clear()
        gtfs_repository.init_default_bengaluru_catalog()
        self.patterns = build_direction_patterns("500D")

    def test_route_has_two_directions(self):
        self.assertEqual(len(self.patterns), 2)
        self.assertEqual(self.patterns[0].origin, self.patterns[1].destination)
        self.assertEqual(self.patterns[0].destination, self.patterns[1].origin)
        self.assertEqual(self.patterns[0].source, "DEMO_CATALOG_DERIVED")

    def test_opposite_headings_select_opposite_directions(self):
        east = select_direction(*MID_IBBLUR_BELLANDUR, bearing=75, speed=25, patterns=self.patterns, previous_direction=None)
        west = select_direction(*MID_IBBLUR_BELLANDUR, bearing=255, speed=25, patterns=self.patterns, previous_direction=None)
        self.assertNotEqual(east.direction_id, west.direction_id)
        self.assertEqual(east.destination, "Majestic (Kempegowda Bus Station)")
        self.assertEqual(west.destination, "Central Silk Board Junction")

    def test_reported_destination_selects_direction(self):
        d = select_direction(*MID_IBBLUR_BELLANDUR, bearing=None, speed=20, patterns=self.patterns,
                             previous_direction=None, destination="Central Silk Board")
        self.assertEqual(d.destination, "Central Silk Board Junction")

    def test_stationary_bus_keeps_previous_direction(self):
        d = select_direction(*MID_IBBLUR_BELLANDUR, bearing=0, speed=0, patterns=self.patterns, previous_direction=1)
        self.assertEqual(d.direction_id, 1)

    def test_next_stop_depends_on_direction(self):
        east = self.patterns[0]
        west = self.patterns[1]
        _, _, nxt_e, _ = detect_stop(*MID_IBBLUR_BELLANDUR, 75, 25, east.stops, None, time.time())
        _, _, nxt_w, _ = detect_stop(*MID_IBBLUR_BELLANDUR, 255, 25, west.stops, None, time.time())
        self.assertEqual(nxt_e.name, "Bellandur EcoSpace")
        self.assertEqual(nxt_w.name, "Ibblur Junction")

    def test_at_stop_and_hysteresis(self):
        stops = self.patterns[0].stops
        status, cur, nxt, _ = detect_stop(*BELLANDUR, 75, 5, stops, None, time.time())
        self.assertEqual(status, "AT_STOP")
        self.assertEqual(cur.name, "Bellandur EcoSpace")
        self.assertEqual(nxt.name, "Kadubeesanahalli")
        from app.services.vehicle_tracking_service import VehicleState
        prev = VehicleState(last_status="AT_STOP", last_at_stop_id=cur.stop_id, last_at_stop_seq=cur.sequence,
                            last_at_stop_ts=time.time(), last_next_seq=nxt.sequence)
        # ~90 m of GPS jitter while still slow: remains AT_STOP
        status2, cur2, _, _ = detect_stop(BELLANDUR[0] + 0.0008, BELLANDUR[1], 75, 5, stops, prev, time.time())
        self.assertEqual(status2, "AT_STOP")
        self.assertEqual(cur2.stop_id, cur.stop_id)

    def test_no_stops_means_unknown(self):
        status, cur, nxt, _ = detect_stop(12.9, 77.6, None, None, [], None, time.time())
        self.assertEqual((status, cur, nxt), ("UNKNOWN", None, None))


class TestRealtimeEndpointsSimulated(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def test_status_not_configured_uses_canonical_statement(self):
        s = self.client.get("/api/realtime/status").json()
        self.assertEqual(s["feed_state"], "NOT_CONFIGURED")
        self.assertFalse(s["realtime_connected"])
        self.assertEqual(s["source"], "SIMULATED")
        self.assertEqual(s["operational_statement"], CANONICAL)

    def test_simulated_vehicles_are_labelled_simulated(self):
        r = self.client.get("/api/realtime/vehicles").json()
        self.assertGreater(r["count"], 0)
        self.assertTrue(all(v["source"] == "SIMULATED" for v in r["vehicles"]))
        self.assertTrue(all(v["direction_label"] for v in r["vehicles"]))
        self.assertEqual(self.client.get("/api/realtime/vehicles/does-not-exist").status_code, 404)
        self.assertEqual(self.client.get("/api/realtime/vehicles?freshness=STABLE").status_code, 422)

    def test_active_journey_gets_simulated_telemetry_without_changing_state(self):
        self.client.post("/api/journey/active", json={"route_number": "500D", "bus_id": "bus-500d-1",
                                                      "origin": "Central Silk Board Junction", "destination": "Hebbal"})
        before = self.client.get("/api/journey/active").json()
        j = self.client.get("/api/journey/active").json()
        # the existing state machine decides the state; telemetry only adds data
        self.assertIn(j["state"], ("WAITING_FOR_BUS", "BUS_APPROACHING"))
        self.assertEqual(j["current_stop"], before["current_stop"])
        self.assertEqual(j["vehicle_telemetry"]["vehicle_id"], "bus-500d-1")
        self.assertEqual(j["vehicle_telemetry"]["source"], "SIMULATED")


class TestAuthorizedFeedPath(unittest.TestCase):
    """Synthetic GTFS-RT payloads through the authorized-feed path of BMTCTransitDataProvider."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()
        gtfs_repository.clear()
        gtfs_repository.init_default_bengaluru_catalog()

    def tearDown(self):
        self.client.post("/api/demo/reset")

    def test_multiple_buses_opposite_directions_and_freshness(self):
        with _BmtcTestMode():
            bmtc_provider.ingest_payload({"entity": [
                entity("V-EAST", *MID_IBBLUR_BELLANDUR, bearing=75, speed=6.0, age=10),
                entity("V-WEST", *MID_IBBLUR_BELLANDUR, bearing=255, speed=6.0, age=90),
                entity("V-STOP", *BELLANDUR, bearing=75, speed=1.0, age=200),
                entity("V-OLD", *IBBLUR, bearing=75, age=400),
                entity("V-NOTS", *IBBLUR, bearing=75, ts=False),
            ]})
            r = self.client.get("/api/realtime/vehicles").json()
            self.assertEqual(r["source"], "VERIFIED_REALTIME")
            self.assertEqual(r["feed_state"], "CONNECTED")
            self.assertTrue(r["realtime_connected"])
            self.assertIsNone(r["operational_statement"])
            by = {v["vehicle_id"]: v for v in r["vehicles"]}
            self.assertEqual(set(by), {"V-EAST", "V-WEST", "V-STOP"})
            self.assertEqual(r["excluded"]["too_old"], 1)
            self.assertEqual(r["excluded"]["no_timestamp"], 1)
            self.assertEqual((by["V-EAST"]["freshness"], by["V-WEST"]["freshness"], by["V-STOP"]["freshness"]), ("LIVE", "RECENT", "STALE"))
            self.assertNotEqual(by["V-EAST"]["direction_id"], by["V-WEST"]["direction_id"])
            self.assertEqual(by["V-EAST"]["next_stop"]["stop_name"], "Bellandur EcoSpace")
            self.assertEqual(by["V-WEST"]["next_stop"]["stop_name"], "Ibblur Junction")
            self.assertEqual(by["V-STOP"]["stop_status"], "AT_STOP")
            self.assertEqual(by["V-STOP"]["current_stop"]["stop_name"], "Bellandur EcoSpace")
            self.assertEqual(by["V-EAST"]["speed_kmh"], 21.6)  # 6 m/s from the feed, not invented
            # Selecting A then B returns each bus's own details
            a = self.client.get("/api/realtime/vehicles/V-EAST").json()
            b = self.client.get("/api/realtime/vehicles/V-WEST").json()
            self.assertNotEqual(a["direction_label"], b["direction_label"])
            self.assertEqual(self.client.get("/api/realtime/vehicles?direction=1").json()["count"], 1)

    def test_missing_speed_and_bearing_stay_unknown(self):
        with _BmtcTestMode():
            bmtc_provider.ingest_payload({"entity": [entity("V-BARE", *MID_IBBLUR_BELLANDUR, age=5)]})
            v = self.client.get("/api/realtime/vehicles/V-BARE").json()
            self.assertIsNone(v["speed_kmh"])
            self.assertIsNone(v["bearing"])

    def test_no_artificial_vehicle_limit(self):
        with _BmtcTestMode():
            ents = [entity(f"V{i}", 12.92 + (i % 30) * 0.001, 77.60 + (i // 30) * 0.01, bearing=90, age=5) for i in range(150)]
            bmtc_provider.ingest_payload({"entity": ents})
            r = self.client.get("/api/realtime/vehicles").json()
            self.assertEqual(r["count"], 150)
            self.assertEqual(len(r["vehicles"]), 150)

    def test_configured_but_no_data_falls_back_honestly(self):
        with _BmtcTestMode():
            bmtc_provider._buses = {}
            bmtc_provider._raw_positions = {}
            s = self.client.get("/api/realtime/status").json()
            self.assertEqual(s["feed_state"], "UNAVAILABLE")
            self.assertFalse(s["realtime_connected"])
            self.assertEqual(s["source"], "SIMULATED")
            self.assertEqual(s["operational_statement"], CANONICAL)

    def test_active_journey_consumes_verified_telemetry(self):
        with _BmtcTestMode():
            bmtc_provider.ingest_payload({"entity": [entity("V-EAST", *MID_IBBLUR_BELLANDUR, bearing=75, speed=6.0, age=5)]})
            res = self.client.post("/api/journey/active", json={"route_number": "500D", "bus_id": "V-EAST",
                                                                "origin": "Central Silk Board Junction", "destination": "Majestic (Kempegowda Bus Station)"})
            self.assertIn(res.status_code, (200, 201), res.text)
            j = self.client.get("/api/journey/active").json()
            self.assertEqual(j["vehicle_telemetry"]["source"], "VERIFIED_REALTIME")
            self.assertEqual(j["next_stop"], "Bellandur EcoSpace")
            self.assertEqual(j["remaining_stops"], j["vehicle_telemetry"]["remaining_stops"])
            self.assertIn(j["state"], ("WAITING_FOR_BUS", "BUS_APPROACHING"))  # state machine untouched

    def test_predictions_work_while_verified_feed_is_active(self):
        # Regression: is_stale is a property on the BMTC provider; calling it crashed predictions.
        with _BmtcTestMode():
            bmtc_provider.ingest_payload({"entity": [entity("V-EAST", *MID_IBBLUR_BELLANDUR, bearing=75, speed=6.0, age=5)]})
            self.assertEqual(self.client.get("/api/predictions/route/500D").status_code, 200)

    def test_single_provider_read_for_concurrent_callers(self):
        svc = VehicleTrackingService()

        async def run():
            await asyncio.gather(*[svc.snapshot() for _ in range(20)])

        asyncio.run(run())
        self.assertEqual(svc.provider_reads, 1)


class TestFeedErrorHandling(unittest.TestCase):
    """Authentication header and upstream failures via a mocked HTTP transport (no network)."""

    def _poll(self, handler):
        seen = {}

        def wrapped(request):
            seen["auth"] = request.headers.get("Authorization")
            return handler(request)

        real_client = httpx.AsyncClient
        with _BmtcTestMode(), mock.patch.object(bmtc_module.httpx, "AsyncClient",
                                                lambda **kw: real_client(transport=httpx.MockTransport(wrapped), **kw)):
            bmtc_provider._buses = {}
            bmtc_provider._raw_positions = {}
            ok = asyncio.run(bmtc_provider.poll_feed_once())
            code = bmtc_provider.last_error_code
            count = self_count = len(bmtc_provider._raw_positions)
        return ok, code, seen, count

    def test_bearer_auth_sent_and_not_logged(self):
        with self.assertLogs(level="WARNING") as cap:
            ok, code, seen, _ = self._poll(lambda r: httpx.Response(401))
        self.assertEqual(seen["auth"], "Bearer test-key-not-real")
        self.assertFalse(ok)
        self.assertEqual(code, "HTTP_401")
        self.assertNotIn("test-key-not-real", "\n".join(cap.output))

    def test_http_errors_classified(self):
        for status, expected in ((403, "HTTP_403"), (404, "HTTP_404"), (429, "HTTP_429"), (503, "HTTP_5XX")):
            ok, code, _, count = self._poll(lambda r, s=status: httpx.Response(s))
            self.assertFalse(ok)
            self.assertEqual(code, expected)
            self.assertEqual(count, 0)  # no vehicles invented

    def test_malformed_empty_and_timeout(self):
        ok, code, _, count = self._poll(lambda r: httpx.Response(200, content=b"\x00garbage", headers={"content-type": "application/octet-stream"}))
        self.assertEqual((ok, code, count), (False, "MALFORMED_PAYLOAD", 0))
        ok, code, _, count = self._poll(lambda r: httpx.Response(200, json={"entity": []}))
        self.assertEqual((ok, code, count), (False, "EMPTY_OR_INVALID_FEED", 0))

        def boom(r):
            raise httpx.ReadTimeout("timeout", request=r)
        ok, code, _, count = self._poll(boom)
        self.assertEqual((ok, code, count), (False, "TIMEOUT", 0))

    def test_successful_poll_parses_vehicles(self):
        body = {"entity": [entity("V-OK", *MID_IBBLUR_BELLANDUR, bearing=75, speed=5.0, age=3)]}
        ok, code, _, count = self._poll(lambda r: httpx.Response(200, json=body))
        self.assertTrue(ok)
        self.assertIsNone(code)
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
