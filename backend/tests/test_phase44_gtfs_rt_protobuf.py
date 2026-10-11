import json
import time
import unittest

from fastapi.testclient import TestClient
from google.transit import gtfs_realtime_pb2

from app.main import app
from app.core.config import settings, OPERATIONAL_STATEMENT_NOT_CONNECTED
from app.services.bmtc_provider import BMTCTransitDataProvider
from app.services.gtfs.protobuf_decoder import decode_feed_message
from app.services.provider_factory import get_provider_health
from app.services import provider_factory


def _feed(vehicles):
    """Builds a synthetic GTFS-RT FeedMessage (test data only — not BMTC data)."""
    msg = gtfs_realtime_pb2.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    msg.header.timestamp = int(time.time())
    for vid, lat, lon, route in vehicles:
        ent = msg.entity.add()
        ent.id = vid
        ent.vehicle.vehicle.id = vid
        ent.vehicle.trip.route_id = route
        ent.vehicle.position.latitude = lat
        ent.vehicle.position.longitude = lon
        ent.vehicle.position.speed = 8.0
        ent.vehicle.timestamp = int(time.time())
    return msg.SerializeToString()


class TestPhase44GTFSRealtimeProtobuf(unittest.TestCase):
    """Master spec Phase 44: authorized GTFS-RT protobuf ingestion path and honest status reporting."""

    def test_decode_valid_feed_message(self):
        data = decode_feed_message(_feed([("V1", 12.95, 77.60, "500D")]))
        self.assertIsNotNone(data)
        self.assertEqual(data["entity"][0]["vehicle"]["vehicle"]["id"], "V1")
        self.assertIsInstance(data["entity"][0]["vehicle"]["timestamp"], int)

    def test_malformed_bytes_rejected(self):
        self.assertIsNone(decode_feed_message(b"\x00\xffnot-protobuf"))
        self.assertIsNone(BMTCTransitDataProvider._decode_feed_body("application/octet-stream", b"garbage-bytes"))
        self.assertIsNone(BMTCTransitDataProvider._decode_feed_body("application/json", b"{broken"))

    def test_json_and_protobuf_bodies_both_accepted(self):
        js = BMTCTransitDataProvider._decode_feed_body("application/json", json.dumps({"entity": []}).encode())
        self.assertEqual(js, {"entity": []})
        pb = BMTCTransitDataProvider._decode_feed_body("application/x-protobuf", _feed([("V1", 12.95, 77.60, "500D")]))
        self.assertEqual(len(pb["entity"]), 1)

    def test_protobuf_ingestion_filters_and_dedups(self):
        provider = BMTCTransitDataProvider()
        data = decode_feed_message(_feed([
            ("V1", 12.95, 77.60, "500D"),
            ("V1", 12.95, 77.60, "500D"),  # duplicate
            ("V2", 28.61, 77.20, "500D"),  # outside Bengaluru bounds
            ("V3", 12.97, 77.59, "356"),
        ]))
        count = provider.ingest_payload(data)
        self.assertEqual(count, 2)
        self.assertEqual(sorted(provider._buses), ["V1", "V3"])

    def test_configured_without_data_is_not_reported_realtime(self):
        original_provider = settings.transit_provider
        bmtc = provider_factory.bmtc_provider
        saved = (bmtc.endpoint, bmtc.api_key, dict(bmtc._buses))
        try:
            settings.transit_provider = "bmtc"
            bmtc.endpoint, bmtc.api_key = "https://feeds.example.invalid/gtfs-rt", "test-key"
            bmtc._buses = {}
            health = get_provider_health()
            self.assertFalse(health.realtime)
            self.assertEqual(health.data_mode, "simulated")
        finally:
            settings.transit_provider = original_provider
            bmtc.endpoint, bmtc.api_key = saved[0], saved[1]
            bmtc._buses = saved[2]

    def test_unconfigured_statement_unchanged(self):
        res = TestClient(app).get("/api/realtime/test").json()
        self.assertEqual(res["message"], OPERATIONAL_STATEMENT_NOT_CONNECTED)
        self.assertEqual(res["message"], "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED")


if __name__ == "__main__":
    unittest.main()
