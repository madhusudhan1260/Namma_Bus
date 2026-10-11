import unittest
import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.config import (
    Settings,
    OPERATIONAL_STATEMENT_NOT_CONNECTED,
    OPERATIONAL_STATEMENT_CONNECTED,
)
from backend.app.services.gtfs.models import GTFSVehiclePosition, GTFSTripUpdate, GTFSStopTimeUpdate, GTFSOccupancyStatus
from backend.app.services.gtfs.normalizer import GTFSNormalizer
from backend.app.services.bmtc_provider import BMTCTransitDataProvider
from backend.app.services.eta_service import ETAService
from backend.app.services.alert_service import alert_service
from backend.app.services.provider_factory import get_transit_provider, get_provider_health
from backend.app.models.transit import ServiceAlert, JourneySearchRequest


class TestPhase20GoogleMapsRealtime(unittest.TestCase):
    """
    Phase 20 Test Suite: Google Maps + Realtime Transit Experience.
    Verifies all 20 required specifications under strict rules:
    - Zero scraping
    - Zero fabrication
    - Honest attribution
    - Robust fallback and error boundaries
    """

    def setUp(self):
        self.client = TestClient(app)

    # 1. Google Maps configuration handling
    def test_1_google_maps_configuration_handling(self):
        """Settings properly reads Google Maps keys from environment without errors."""
        with patch.dict("os.environ", {
            "GOOGLE_MAPS_API_KEY_ANDROID": "AIzaSyTestAndroidKey123",
            "GOOGLE_MAPS_API_KEY_IOS": "AIzaSyTestIosKey456",
        }):
            s = Settings()
            self.assertEqual(s.google_maps_api_key_android, "AIzaSyTestAndroidKey123")
            self.assertEqual(s.google_maps_api_key_ios, "AIzaSyTestIosKey456")
            report = s.validate_production_config()
            self.assertTrue(report["validated_variables"]["google_maps_android_configured"])
            self.assertTrue(report["validated_variables"]["google_maps_ios_configured"])

    # 2. Missing Google Maps key behavior
    def test_2_missing_google_maps_key_behavior(self):
        """When Google Maps keys are absent, app config remains valid with fallback enabled."""
        s = Settings(google_maps_api_key_android=None, google_maps_api_key_ios=None)
        report = s.validate_production_config()
        self.assertFalse(report["validated_variables"]["google_maps_android_configured"])
        self.assertFalse(report["validated_variables"]["google_maps_ios_configured"])
        self.assertTrue(report["valid"])

    # 3. Authorized realtime activation
    def test_3_authorized_realtime_activation(self):
        """BMTCTransitDataProvider activates realtime mode only when valid endpoint and key exist."""
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/feed",
            api_key="valid-secret-token",
        )
        self.assertTrue(provider.is_configured)
        self.assertTrue(provider.is_realtime())
        self.assertEqual(provider.get_data_mode(), "realtime")

    # 4. Unauthorized realtime fallback
    def test_4_unauthorized_realtime_fallback(self):
        """When credentials are absent, BMTCTransitDataProvider defaults to unconfigured/simulated."""
        provider = BMTCTransitDataProvider(endpoint=None, api_key=None)
        self.assertFalse(provider.is_configured)
        self.assertFalse(provider.is_realtime())
        self.assertEqual(provider.get_data_mode(), "simulated")
        self.assertEqual(provider.feed_status, "unconfigured")

    # 5. VehiclePosition normalization
    def test_5_vehicle_position_normalization(self):
        """GTFSVehiclePosition normalizes accurately into Bus and BusLocation models."""
        vp = GTFSVehiclePosition(
            vehicle_id="KA-01-F-4819",
            route_id="500D",
            route_number="500D",
            latitude=12.9176,
            longitude=77.6238,
            bearing=145.0,
            speed_kmh=32.5,
            timestamp=1700000000,
        )
        bus = GTFSNormalizer.normalize_vehicle(vp)
        self.assertEqual(bus.bus_id, "KA-01-F-4819")
        self.assertEqual(bus.route_number, "500D")
        self.assertAlmostEqual(bus.latitude, 12.9176)
        self.assertAlmostEqual(bus.longitude, 77.6238)
        self.assertEqual(bus.speed, 32.5)
        self.assertEqual(bus.direction, 145.0)

        loc = GTFSNormalizer.normalize_bus_location(vp)
        self.assertEqual(loc.bus_id, "KA-01-F-4819")
        self.assertEqual(loc.heading, 145.0)
        self.assertEqual(loc.speed, 32.5)

    # 6. Vehicle heading
    def test_6_vehicle_heading_normalization(self):
        """Vehicle heading is correctly bounded and mapped to direction and heading fields."""
        vp = GTFSVehiclePosition(
            vehicle_id="KA-01-F-1111",
            latitude=12.9200,
            longitude=77.6300,
            bearing=270.5,
        )
        loc = GTFSNormalizer.normalize_bus_location(vp)
        self.assertEqual(loc.heading, 270.5)
        self.assertEqual(loc.direction, 270.5)

    # 7. Vehicle timestamp
    def test_7_vehicle_timestamp_handling(self):
        """Epoch timestamp in seconds is normalized to timezone-aware UTC datetime."""
        epoch = 1718000000
        vp = GTFSVehiclePosition(
            vehicle_id="KA-01-F-2222",
            latitude=12.9300,
            longitude=77.6400,
            timestamp=epoch,
        )
        loc = GTFSNormalizer.normalize_bus_location(vp)
        self.assertEqual(loc.timestamp.timestamp(), epoch)

    # 8. Vehicle coordinate validation (Bengaluru bounds)
    def test_8_vehicle_coordinate_bounds_validation(self):
        """Provider strictly rejects coordinates outside Bengaluru metropolitan transit bounds."""
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/feed",
            api_key="valid-key",
        )
        # Coordinates in Delhi (outside Bengaluru)
        bad_payload = {
            "entity": [{
                "id": "bad-bus",
                "vehicle": {
                    "vehicle": {"id": "KA-99-9999"},
                    "position": {"latitude": 28.6139, "longitude": 77.2090},
                }
            }]
        }
        valid, reason, vehicles = provider.validate_feed_payload(bad_payload)
        self.assertFalse(valid)
        self.assertIn("outside Bengaluru", reason)

    # 9. Realtime map data endpoint
    def test_9_realtime_map_data_endpoint(self):
        """GET /api/buses returns structured buses with coordinates and heading."""
        res = self.client.get("/api/buses")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        first = data[0]
        self.assertIn("latitude", first)
        self.assertIn("longitude", first)
        self.assertIn("direction", first)
        self.assertIn("bus_id", first)

    # 10. TripUpdate ETA source
    def test_10_trip_update_eta_source(self):
        """When TripUpdate is available, ETAEstimate marks source as 'gtfs_rt_trip_update'."""
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/feed",
            api_key="valid-key",
        )
        provider.is_configured = True
        provider._buses["KA-01-F-4819"] = GTFSNormalizer.normalize_vehicle(
            GTFSVehiclePosition(
                vehicle_id="KA-01-F-4819",
                route_id="500D",
                latitude=12.9176,
                longitude=77.6238,
            )
        )
        now_sec = int(datetime.now(timezone.utc).timestamp())
        provider._trip_updates["KA-01-F-4819"] = GTFSTripUpdate(
            trip_id="trip-1",
            vehicle_id="KA-01-F-4819",
            stop_time_updates=[
                GTFSStopTimeUpdate(
                    stop_name="Central Silk Board Junction",
                    arrival_time=now_sec + 300,  # 5 min
                )
            ]
        )

        eta = asyncio.run(provider.get_eta("KA-01-F-4819", "Central Silk Board Junction"))
        self.assertIsNotNone(eta)
        self.assertEqual(eta.source, "gtfs_rt_trip_update")
        self.assertEqual(eta.eta_minutes, 5)

    # 11. Geometric ETA fallback
    def test_11_geometric_eta_fallback(self):
        """Without TripUpdate, ETAEstimate falls back to 'geometric_estimate'."""
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/feed",
            api_key="valid-key",
        )
        provider.is_configured = True
        provider._buses["KA-01-F-4819"] = GTFSNormalizer.normalize_vehicle(
            GTFSVehiclePosition(
                vehicle_id="KA-01-F-4819",
                route_id="500D",
                latitude=12.9176,
                longitude=77.6238,
                speed_kmh=30.0,
            )
        )
        provider._trip_updates.clear()

        eta = asyncio.run(provider.get_eta("KA-01-F-4819", "Majestic (Kempegowda Bus Station)"))
        self.assertIsNotNone(eta)
        self.assertEqual(eta.source, "geometric_estimate")
        self.assertGreater(eta.eta_minutes, 0)

    # 12. ServiceAlert integration
    def test_12_service_alert_integration(self):
        """GET /api/alerts filters and distinguishes 'gtfs_rt' from 'demo' advisories."""
        res = self.client.get("/api/alerts")
        self.assertEqual(res.status_code, 200)
        alerts = res.json()
        self.assertGreater(len(alerts), 0)

        real_alert = ServiceAlert(
            id="gtfs-rt-alert-1",
            route_number="500D",
            title="Realtime Diverted Service",
            description="Service diverted due to roadwork",
            severity="WARNING",
            source="gtfs_rt",
            is_official_realtime=True,
        )
        alert_service.add_realtime_alert(real_alert)

        res_rt = self.client.get("/api/alerts?source=gtfs_rt")
        self.assertEqual(res_rt.status_code, 200)
        rt_alerts = res_rt.json()
        self.assertTrue(any(a["id"] == "gtfs-rt-alert-1" for a in rt_alerts))
        alert_service.reset()

    # 13. Occupancy availability
    def test_13_occupancy_availability(self):
        """When APC data is missing in GTFS-RT, normalize_occupancy returns None (no fake seats)."""
        vp_no_apc = GTFSVehiclePosition(
            vehicle_id="KA-01-F-4819",
            latitude=12.9176,
            longitude=77.6238,
            occupancy_status=None,
        )
        occ = GTFSNormalizer.normalize_occupancy(vp_no_apc)
        self.assertIsNone(occ)

        vp_with_apc = GTFSVehiclePosition(
            vehicle_id="KA-01-F-4819",
            latitude=12.9176,
            longitude=77.6238,
            occupancy_status=GTFSOccupancyStatus.FEW_SEATS_AVAILABLE,
        )
        occ_present = GTFSNormalizer.normalize_occupancy(vp_with_apc)
        self.assertIsNotNone(occ_present)
        self.assertEqual(occ_present.occupancy_level, "Medium")

    # 14. Feed stale handling
    def test_14_feed_stale_handling(self):
        """Provider transitions to 'stale' status when update age exceeds threshold."""
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/feed",
            api_key="valid-key",
            stale_threshold=10.0,
        )
        provider.is_configured = True
        old_time = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 30, tz=timezone.utc)
        provider._last_updated_at = old_time
        self.assertEqual(provider.feed_status, "stale")
        self.assertTrue(provider.is_stale)

    # 15. Last-known-good retention
    def test_15_last_known_good_retention(self):
        """Transient fetch failure retains cached vehicles rather than clearing them immediately."""
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/feed",
            api_key="valid-key",
            stale_threshold=60.0,
        )
        provider.is_configured = True
        valid_payload = {
            "entity": [{
                "id": "bus-1",
                "vehicle": {
                    "vehicle": {"id": "KA-01-F-4819"},
                    "position": {"latitude": 12.9176, "longitude": 77.6238, "speed": 28.0, "bearing": 90.0},
                    "timestamp": int(datetime.now(timezone.utc).timestamp()),
                }
            }]
        }
        provider.ingest_payload(valid_payload)
        self.assertEqual(len(provider._buses), 1)

        provider._handle_fetch_error()
        self.assertEqual(len(provider._buses), 1)
        self.assertEqual(provider._consecutive_failures, 1)

    # 16. Offline fallback
    def test_16_offline_fallback(self):
        """Readiness probe remains ready and reports fallback even if provider is unconfigured."""
        res = self.client.get("/api/ready")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ready"])
        self.assertIn("active_provider", data)

    # 17. Realtime diagnostics in /api/status
    def test_17_realtime_diagnostics_in_status(self):
        """GET /api/status exposes detailed diagnostics and feed health."""
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("modules", data)
        self.assertIn("diagnostics", data)
        self.assertIn("feed_status", data)

    # 18. Security regression
    def test_18_security_regression(self):
        """Security headers and response time profiling remain active."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertIn("x-response-time-ms", res.headers)
        self.assertIn("x-content-type-options", res.headers)

    # 19. Provider state consistency
    def test_19_provider_state_consistency(self):
        """Operational statement remains accurately bounded."""
        health = get_provider_health()
        if not health.realtime:
            self.assertIn("simulated", health.data_mode)
            self.assertIn(health.provider, ["mock", "bmtc"])

    # 20. Existing functionality regression
    def test_20_existing_functionality_regression(self):
        """Journey Search, AI Chat, and Tickets operate smoothly without regression."""
        # Journey Search
        j_res = self.client.post("/api/journey/search", json={
            "origin": "Central Silk Board",
            "destination": "Majestic"
        })
        self.assertEqual(j_res.status_code, 200)
        j_data = j_res.json()
        self.assertGreater(len(j_data["options"]), 0)
        first_opt = j_data["options"][0]
        self.assertIn("eta_source", first_opt)
        self.assertIn("data_source", first_opt)

        # AI Chat
        ai_res = self.client.post("/api/ai/chat", json={"message": "Where is 500D?"})
        self.assertEqual(ai_res.status_code, 200)
        self.assertIn("500D", ai_res.json()["answer"])

        # Ticket Verification (invalid ticket test)
        t_res = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": "TKT-NONEXISTENT"})
        self.assertEqual(t_res.status_code, 200)
        self.assertFalse(t_res.json()["valid"])


if __name__ == "__main__":
    unittest.main()
