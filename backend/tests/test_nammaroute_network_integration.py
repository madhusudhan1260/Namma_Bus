"""
ನಮ್ಮ Bus × NammaRoute network integration tests.

NammaRoute is replaced by an httpx MockTransport returning SYNTHETIC responses shaped like the real
NammaRoute API. Nothing here contacts NammaRoute or BMTC.
"""

import asyncio
import json
import unittest

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.core import middleware
from app.services.nammaroute_client import NetworkUnavailable, nammaroute_client
from app.api.network_routes import normalize_vehicle

CANONICAL = "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED"

ROUTE = {
    "id": "R1", "routeNumber": "T-1", "serviceType": "ORDINARY", "origin": "Stop A", "destination": "Stop C",
    "stops": [
        {"id": "S1", "stopId": "S1", "name": "Stop A", "latitude": 12.95, "longitude": 77.60, "sequence": 1},
        {"id": "S2", "stopId": "S2", "name": "Stop B", "latitude": 12.96, "longitude": 77.61, "sequence": 2},
        {"id": "S3", "stopId": "S3", "name": "Stop C", "latitude": 12.97, "longitude": 77.62, "sequence": 3},
    ],
    "directions": [{"direction": 0}, {"direction": 1}],
}


def vehicle(vid, status, direction, current, nxt, completed, remaining):
    return {
        "id": vid, "vehicleNumber": f"KA-TEST-{vid}", "routeId": "R1", "routeNumber": "T-1",
        "latitude": 12.955, "longitude": 77.605, "bearing": 45 if direction == 0 else 225, "speed": 20,
        "timestamp": "2026-01-01T00:00:00Z", "status": status, "freshnessSeconds": 10, "direction": direction,
        "origin": "Stop A" if direction == 0 else "Stop C", "destination": "Stop C" if direction == 0 else "Stop A",
        "stopStatus": "IN_TRANSIT", "currentStop": current, "nextStop": nxt,
        "totalStops": 3, "completedStops": completed, "remainingStops": remaining, "progressPercentage": completed * 50,
    }


class FakeNammaRoute:
    def __init__(self):
        self.vehicles = []
        self.down = False
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("down", request=request)
        path, q = request.url.path.replace("/api", "", 1), request.url.params
        if path == "/data/stats":
            return httpx.Response(200, json={"status": "SUCCESS", "data": {"routes": 1, "stops": 3, "variants": 2, "trips": 4}})
        if path == "/realtime/status":
            return httpx.Response(200, json={"provider": "BMTC_REALTIME", "reachable": bool(self.vehicles), "vehicleCount": len(self.vehicles), "error": None if self.vehicles else "Unable to connect"})
        if path == "/realtime/vehicles":
            if not self.vehicles:
                return httpx.Response(200, json={"status": "UNAVAILABLE", "vehicles": [], "vehicleCount": 0, "error": "Unable to connect"})
            return httpx.Response(200, json={"status": "LIVE", "vehicles": self.vehicles, "vehicleCount": len(self.vehicles)})
        if path == "/routes" :
            hits = [ROUTE] if q.get("q", "").upper() in ("", "T-1", "T") else []
            return httpx.Response(200, json={"status": "SUCCESS", "data": {"total": len(hits), "routes": hits}})
        if path == "/routes/T-1":
            return httpx.Response(200, json={"status": "SUCCESS", "data": ROUTE})
        if path == "/routes/T-1/stops":
            stops = ROUTE["stops"] if q.get("direction", "0") == "0" else list(reversed(ROUTE["stops"]))
            return httpx.Response(200, json={"status": "SUCCESS", "data": stops})
        if path == "/routes/T-1/vehicles":
            return httpx.Response(200, json={"status": "SUCCESS", "data": self.vehicles})
        if path == "/stops/search":
            return httpx.Response(200, json={"status": "SUCCESS", "data": {"total": 1, "stops": [ROUTE["stops"][0]]}})
        if path == "/journey":
            return httpx.Response(200, json={"status": "SUCCESS", "from": q.get("from"), "to": q.get("to"), "plans": [{"id": "p1", "type": "DIRECT", "legs": [{"routeNumber": "T-1"}]}]})
        if path == "/fares":
            if (q.get("from"), q.get("to")) == ("S1", "S3"):
                return httpx.Response(200, json={"status": "SUCCESS", "data": {"fareAmount": 30.0, "currency": "INR", "source": "GTFS_FARE_RULES"}})
            return httpx.Response(404, json={"status": "ERROR"})
        return httpx.Response(404, json={"status": "ERROR"})


class TestNammaRouteNetworkIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()
        self.fake = FakeNammaRoute()
        nammaroute_client.reset()
        nammaroute_client.transport = httpx.MockTransport(self.fake.handler)

    def tearDown(self):
        nammaroute_client.transport = None
        nammaroute_client.reset()
        self.client.post("/api/demo/reset")

    # --- network data -------------------------------------------------------

    def test_status_reports_network_and_honest_realtime(self):
        s = self.client.get("/api/network/status").json()
        self.assertTrue(s["network_connected"])
        self.assertEqual(s["routes"], 1)
        self.assertFalse(s["live_connected"])
        self.assertEqual(s["operational_statement"], CANONICAL)

    def test_route_search_details_and_directions(self):
        r = self.client.get("/api/network/routes?q=T-1").json()
        self.assertEqual(r["routes"][0]["routeNumber"], "T-1")
        self.assertIn("GTFS_STATIC", r["source"])
        d = self.client.get("/api/network/routes/T-1").json()
        self.assertEqual(len(d["route"]["stops"]), 3)
        s0 = self.client.get("/api/network/routes/T-1/stops?direction=0").json()["stops"]
        s1 = self.client.get("/api/network/routes/T-1/stops?direction=1").json()["stops"]
        self.assertEqual([x["id"] for x in s0], list(reversed([x["id"] for x in s1])))
        self.assertEqual(self.client.get("/api/network/routes/NOPE").status_code, 404)

    def test_combined_search_and_journey(self):
        s = self.client.get("/api/network/search?q=T").json()
        self.assertEqual(s["routes"][0]["routeNumber"], "T-1")
        self.assertEqual(s["stops"][0]["name"], "Stop A")
        j = self.client.get("/api/network/journey?from=Stop%20A&to=Stop%20C").json()
        self.assertEqual(j["count"], 1)

    # --- realtime vehicles ----------------------------------------------------

    def test_no_vehicles_means_no_fake_buses(self):
        v = self.client.get("/api/network/vehicles").json()
        self.assertEqual(v["count"], 0)
        self.assertFalse(v["live_connected"])
        self.assertEqual(v["operational_statement"], CANONICAL)

    def test_vehicles_opposite_directions_and_freshness(self):
        self.fake.vehicles = [
            vehicle("1", "LIVE", 0, {"stopId": "S1", "stopName": "Stop A", "sequence": 1}, {"stopId": "S2", "stopName": "Stop B", "sequence": 2}, 1, 1),
            vehicle("2", "RECENT", 1, {"stopId": "S3", "stopName": "Stop C", "sequence": 1}, {"stopId": "S2", "stopName": "Stop B", "sequence": 2}, 0, 2),
            vehicle("3", "STALE", 0, None, {"stopId": "S3", "stopName": "Stop C", "sequence": 3}, 2, 0),
            {"id": "bad", "latitude": "x", "longitude": 1, "status": "LIVE"},
            {**vehicle("4", "STABLE", 0, None, None, 0, 0)},
        ]
        v = self.client.get("/api/network/vehicles").json()
        self.assertTrue(v["live_connected"])
        self.assertEqual(v["count"], 3)
        self.assertEqual(v["excluded"], 2)
        self.assertEqual(v["counts_by_freshness"], {"LIVE": 1, "RECENT": 1, "STALE": 1})
        by = {x["vehicle_id"]: x for x in v["vehicles"]}
        self.assertNotEqual(by["1"]["direction"], by["2"]["direction"])
        self.assertEqual(by["1"]["next_stop"]["stop_name"], "Stop B")
        self.assertEqual(by["2"]["current_stop"]["stop_name"], "Stop C")
        self.assertEqual((by["1"]["completed_stops"], by["1"]["remaining_stops"]), (1, 1))
        self.assertEqual(by["1"]["vehicle_number"], "KA-TEST-1")

    def test_no_vehicle_limit(self):
        self.fake.vehicles = [vehicle(str(i), "LIVE", i % 2, None, None, 0, 3) for i in range(60)]
        self.assertEqual(self.client.get("/api/network/vehicles").json()["count"], 60)

    def test_network_offline_is_honest(self):
        self.fake.down = True
        v = self.client.get("/api/network/vehicles").json()
        self.assertEqual(v["realtime_status"], "NETWORK_OFFLINE")
        self.assertEqual(v["count"], 0)
        self.assertEqual(self.client.get("/api/network/routes?q=T").status_code, 503)
        self.assertFalse(self.client.get("/api/network/status").json()["network_connected"])

    def test_shared_upstream_request(self):
        async def run():
            await asyncio.gather(*[nammaroute_client.get("/realtime/vehicles", ttl=10) for _ in range(25)])
        asyncio.run(run())
        self.assertEqual(self.fake.calls.count("/api/realtime/vehicles"), 1)

    def test_normalize_drops_unknown_freshness(self):
        self.assertIsNone(normalize_vehicle({"id": "x", "latitude": 1, "longitude": 1, "status": "STABLE"}))
        self.assertIsNone(normalize_vehicle({"id": "", "latitude": 1, "longitude": 1, "status": "LIVE"}))

    # --- ticketing on network routes -----------------------------------------------

    def _pay(self, **kw):
        body = {"route_number": "T-1", "source": "Stop A", "destination": "Stop C", "from_stop_id": "S1", "to_stop_id": "S3", "vehicle_number": "KA-TEST-1", "quantity": 2, **kw}
        return self.client.post("/api/payment/create", json=body)

    def test_gtfs_fare_ticket_end_to_end_with_conductor(self):
        rec = self._pay().json()
        self.assertEqual((rec["unit_fare"], rec["amount"], rec["fare_source"]), (30, 60, "GTFS_FARE_RULES"))
        self.client.post("/api/payment/verify", json={"payment_id": rec["payment_id"], "sandbox_outcome": "PAYMENT_SUCCESS"})
        t = self.client.post("/api/tickets/purchase", json={"payment_id": rec["payment_id"]}).json()
        self.assertEqual(t["route_number"], "T-1")
        self.assertEqual(t["vehicle_number"], "KA-TEST-1")
        self.assertEqual(t["passenger_count"], 2)
        self.assertEqual(t["payment_status"], "PAYMENT_SUCCESS")
        self.assertEqual(t["disclaimer"], "DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL")
        self.assertEqual(json.loads(t["qr_payload"])["bus"], "KA-TEST-1")
        ok = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": t["qr_payload"], "conductor_route_number": "T-1"}).json()
        self.assertTrue(ok["valid"])
        bad = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": t["qr_payload"], "conductor_route_number": "999"}).json()
        self.assertEqual(bad["status"], "mismatch")

    def test_missing_feed_fare_uses_labelled_demo_estimate(self):
        rec = self._pay(to_stop_id="S2").json()
        self.assertEqual(rec["fare_source"], "DEMO_FARE_ESTIMATE")
        self.assertEqual(rec["disclosure"], "DEMO PAYMENT — NO REAL MONEY CHARGED")

    def test_network_ticket_rejections(self):
        self.assertEqual(self._pay(to_stop_id="NOT-ON-ROUTE").status_code, 400)
        self.assertEqual(self._pay(route_number="NOPE").status_code, 400)
        self.assertEqual(self._pay(ticket_type="STUDENT").status_code, 400)
        # Cached route/fare data keeps serving during a short outage; with an empty cache it is a 503
        transport = nammaroute_client.transport
        nammaroute_client.reset()
        nammaroute_client.transport = transport
        self.fake.down = True
        self.assertEqual(self._pay().status_code, 503)

    def test_legacy_demo_routes_unchanged(self):
        rec = self.client.post("/api/payment/create", json={"route_number": "500D", "source": "a", "destination": "b"}).json()
        self.assertEqual((rec["amount"], rec["fare_source"]), (25, "DEMO_FARE_TABLE"))


if __name__ == "__main__":
    unittest.main()
