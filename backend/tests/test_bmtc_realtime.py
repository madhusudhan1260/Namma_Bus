import asyncio
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch, MagicMock

from app.core.config import settings
from app.models.transit import Bus, BusLocation, HealthResponse, SystemStatusResponse, AIChatRequest
from app.services.provider import TransitDataProvider
from app.services.mock_provider import mock_provider, MockTransitDataProvider
from app.services.bmtc_provider import (
    bmtc_provider,
    BMTCTransitDataProvider,
    BMTCNotConfiguredError,
)
from app.services.provider_factory import get_transit_provider, get_provider_health
from app.services.gtfs.models import (
    GTFSVehiclePosition,
    GTFSTripUpdate,
    GTFSOccupancyStatus,
)
from app.services.gtfs.parser import GTFSParser
from app.services.gtfs.normalizer import GTFSNormalizer
from app.services.gtfs.repository import gtfs_repository
from app.services.ai_service import AIService
from app.api.routes import get_system_status


class TestBMTCRealtimeIntegration(unittest.TestCase):
    """
    Phase 13 Comprehensive Test Suite for Real BMTC & GTFS-Realtime Integration.
    Covers all 15 required scenarios:
    1. Mock provider still works
    2. BMTC provider implements TransitDataProvider
    3. Missing BMTC credentials
    4. Invalid feed response
    5. Empty feed
    6. Valid vehicle position parsing
    7. Vehicle position normalization
    8. Trip update parsing
    9. Provider fallback
    10. Feed staleness
    11. Last-known-good snapshot
    12. Health status
    13. System status
    14. Occupancy unavailable behavior
    15. AI grounding with realtime telemetry
    """

    def setUp(self):
        # Sample standard GTFS-RT payload
        self.sample_gtfs_rt_payload = {
            "header": {"gtfs_realtime_version": "2.0", "timestamp": int(datetime.now(timezone.utc).timestamp())},
            "entity": [
                {
                    "id": "entity-500d-live",
                    "vehicle": {
                        "trip": {"trip_id": "trip-500d-1", "route_id": "500D"},
                        "position": {"latitude": 12.9176, "longitude": 77.6238, "bearing": 95.0, "speed": 8.5},
                        "timestamp": int(datetime.now(timezone.utc).timestamp()),
                        "vehicle": {"id": "KA-01-F-4819", "label": "500D"},
                        "occupancy_status": "FEW_SEATS_AVAILABLE",
                    },
                },
                {
                    "id": "entity-356-live",
                    "vehicle": {
                        "trip": {"trip_id": "trip-356-1", "route_id": "356"},
                        "position": {"latitude": 12.9029, "longitude": 77.6242, "bearing": 180.0, "speed": 10.0},
                        "timestamp": int(datetime.now(timezone.utc).timestamp()),
                        "vehicle": {"id": "KA-57-F-1200", "label": "356"},
                        # Omit occupancy_status to simulate real agency feed without APC
                    },
                },
            ],
        }

        self.sample_trip_updates_payload = {
            "entity": [
                {
                    "id": "tu-500d-1",
                    "trip_update": {
                        "trip": {"trip_id": "trip-500d-1", "route_id": "500D"},
                        "vehicle": {"id": "KA-01-F-4819"},
                        "stop_time_update": [
                            {
                                "stop_sequence": 2,
                                "stop_id": "stop-silk-board",
                                "stop_name": "Central Silk Board Junction",
                                "arrival": {
                                    "delay": 120,
                                    "time": int(datetime.now(timezone.utc).timestamp()) + 360,  # 6 min ETA
                                },
                            }
                        ],
                    },
                }
            ]
        }

    # 1. Mock provider still works
    def test_1_mock_provider_still_works(self):
        with patch.object(settings, "transit_provider", "mock"):
            p = get_transit_provider()
            self.assertIsInstance(p, MockTransitDataProvider)
            self.assertEqual(p.get_data_mode(), "simulated")
            self.assertFalse(p.is_realtime())
            buses = asyncio.run(p.get_buses())
            self.assertGreater(len(buses), 0)

    # 2. BMTC provider implements TransitDataProvider
    def test_2_bmtc_provider_implements_interface(self):
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret-key")
        self.assertIsInstance(provider, TransitDataProvider)
        self.assertEqual(provider.provider_name(), "bmtc")
        self.assertTrue(provider.is_configured)
        self.assertEqual(provider.get_data_mode(), "realtime")
        self.assertTrue(provider.is_realtime())

    # 3. Missing BMTC credentials
    def test_3_missing_bmtc_credentials_safety(self):
        unconfigured = BMTCTransitDataProvider(endpoint=None, api_key=None)
        self.assertFalse(unconfigured.is_configured)
        self.assertEqual(unconfigured.feed_status, "unconfigured")
        with self.assertRaises(BMTCNotConfiguredError):
            asyncio.run(unconfigured.get_buses())

    # 4. Invalid feed response
    def test_4_invalid_feed_response_resilience(self):
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret-key")
        # Ingest malformed / unexpected dictionary
        count = provider.ingest_payload({"invalid_key": "unsupported_data"})
        self.assertEqual(count, 0)
        self.assertFalse(provider.has_live_data)

    # 5. Empty feed
    def test_5_empty_feed_handling(self):
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret-key")
        count = provider.ingest_payload({"header": {}, "entity": []})
        self.assertEqual(count, 0)
        self.assertEqual(len(provider._buses), 0)

    # 6. Valid vehicle position parsing
    def test_6_valid_vehicle_position_parsing(self):
        vehicles = GTFSParser.parse_vehicle_positions(self.sample_gtfs_rt_payload)
        self.assertEqual(len(vehicles), 2)
        v1 = vehicles[0]
        self.assertEqual(v1.vehicle_id, "KA-01-F-4819")
        self.assertEqual(v1.route_id, "500D")
        self.assertEqual(v1.latitude, 12.9176)
        self.assertEqual(v1.longitude, 77.6238)
        self.assertEqual(v1.occupancy_status, "FEW_SEATS_AVAILABLE")

    # 7. Vehicle position normalization
    def test_7_vehicle_position_normalization(self):
        vehicles = GTFSParser.parse_vehicle_positions(self.sample_gtfs_rt_payload)
        bus = GTFSNormalizer.normalize_vehicle(vehicles[0], gtfs_repository)
        self.assertIsInstance(bus, Bus)
        self.assertEqual(bus.bus_id, "KA-01-F-4819")
        self.assertEqual(bus.route_number, "500D")
        self.assertIn("AC", bus.bus_type)
        self.assertEqual(bus.occupancy_percentage, 68)
        self.assertGreater(bus.available_seats, 0)

        loc = GTFSNormalizer.normalize_bus_location(vehicles[0])
        self.assertIsInstance(loc, BusLocation)
        self.assertEqual(loc.bus_id, "KA-01-F-4819")
        self.assertEqual(loc.latitude, 12.9176)

    # 8. Trip update parsing & official ETA extraction
    def test_8_trip_update_parsing_and_eta(self):
        tu_list = GTFSParser.parse_trip_updates(self.sample_trip_updates_payload)
        self.assertEqual(len(tu_list), 1)
        self.assertEqual(tu_list[0].vehicle_id, "KA-01-F-4819")
        self.assertEqual(len(tu_list[0].stop_time_updates), 1)

        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret-key")
        provider.ingest_payload(self.sample_gtfs_rt_payload, self.sample_trip_updates_payload)

        eta = asyncio.run(provider.get_eta("KA-01-F-4819", "Central Silk Board Junction"))
        self.assertIsNotNone(eta)
        self.assertEqual(eta.bus_id, "KA-01-F-4819")
        self.assertGreater(eta.eta_minutes, 0)

    # 9. Provider fallback when credentials missing
    def test_9_provider_fallback_when_unconfigured(self):
        with patch.object(settings, "transit_provider", "bmtc"):
            with patch.object(bmtc_provider, "endpoint", None), patch.object(bmtc_provider, "api_key", None):
                with self.assertLogs("nammamove.provider_factory", level="WARNING"):
                    active = get_transit_provider()
                    self.assertIsInstance(active, MockTransitDataProvider)

    # 10. Feed staleness detection
    def test_10_feed_staleness_detection(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://test.bmtc.gov.in/api",
            api_key="secret-key",
            stale_threshold=5.0,  # 5 second threshold for testing
        )
        provider.ingest_payload(self.sample_gtfs_rt_payload)
        self.assertEqual(provider.feed_status, "connected")
        self.assertFalse(provider.is_stale)

        # Artificially age the timestamp beyond stale threshold
        provider._last_updated_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        self.assertEqual(provider.feed_status, "stale")
        self.assertTrue(provider.is_stale)

    # 11. Last-known-good snapshot retained during temporary error
    def test_11_last_known_good_snapshot_retention(self):
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret-key")
        provider.ingest_payload(self.sample_gtfs_rt_payload)
        self.assertTrue(provider.has_live_data)
        self.assertEqual(len(provider._buses), 2)

        # Trigger fetch error
        provider._handle_fetch_error()
        # Data remains available from snapshot
        self.assertEqual(len(provider._buses), 2)
        buses = asyncio.run(provider.get_buses())
        self.assertEqual(len(buses), 2)

    # 12. Health status reporting (simulated vs realtime vs stale)
    def test_12_health_status_reporting(self):
        # 12.1 Simulated Mode
        with patch.object(settings, "transit_provider", "mock"):
            h1 = get_provider_health()
            self.assertEqual(h1.data_mode, "simulated")
            self.assertFalse(h1.realtime)
            self.assertFalse(h1.stale)

        # 12.2 Realtime Mode
        with patch.object(settings, "transit_provider", "bmtc"):
            with patch.object(bmtc_provider, "endpoint", "https://test.bmtc.gov.in/api"), patch.object(bmtc_provider, "api_key", "valid-key"):
                bmtc_provider.ingest_payload(self.sample_gtfs_rt_payload)
                h2 = get_provider_health()
                self.assertEqual(h2.data_mode, "realtime")
                self.assertTrue(h2.realtime)
                self.assertEqual(h2.feed_status, "connected")
                self.assertFalse(h2.stale)

    # 13. System status endpoint reports feed status and modules
    def test_13_system_status_endpoint(self):
        status = asyncio.run(get_system_status())
        self.assertIsInstance(status, SystemStatusResponse)
        self.assertEqual(status.overall_status, "Active")
        self.assertIn("Transit Data", [m.name for m in status.modules])

    # 14. Occupancy safely reports Unavailable when APC not in feed
    def test_14_occupancy_unavailable_when_no_apc(self):
        vehicles = GTFSParser.parse_vehicle_positions(self.sample_gtfs_rt_payload)
        # Vehicle 2 has no occupancy_status in payload
        bus2 = GTFSNormalizer.normalize_vehicle(vehicles[1], gtfs_repository)
        self.assertEqual(bus2.occupancy_percentage, 0)
        self.assertEqual(bus2.available_seats, 0)

        # normalize_occupancy returns None when no APC data
        occ = GTFSNormalizer.normalize_occupancy(vehicles[1])
        self.assertIsNone(occ)

    # 15. AI grounding with realtime telemetry
    def test_15_ai_grounding_with_realtime_telemetry(self):
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret-key")
        provider.ingest_payload(self.sample_gtfs_rt_payload, self.sample_trip_updates_payload)

        with patch("app.services.ai_service.get_transit_provider", return_value=provider):
            req = AIChatRequest(message="Where is 500D?", user_stop="Central Silk Board Junction")
            resp = asyncio.run(AIService.process_chat(req))
            self.assertEqual(resp.bus_id, "KA-01-F-4819")
            self.assertEqual(resp.route_number, "500D")
            self.assertIn("500D", resp.answer)
            self.assertIsNotNone(resp.data)
            self.assertEqual(resp.data.get("routeNumber"), "500D")


if __name__ == "__main__":
    unittest.main()
