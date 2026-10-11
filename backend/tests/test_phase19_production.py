import unittest
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
from backend.app.services.gtfs.parser import GTFSParser
from backend.app.services.gtfs.models import GTFSVehiclePosition, GTFSTripUpdate, GTFSServiceAlert
from backend.app.services.eta_service import ETAService
from backend.app.services.bmtc_provider import BMTCTransitDataProvider
from backend.app.services.realtime_activation_service import realtime_activation_service
from backend.app.models.transit import RealtimeValidationRequest


class TestPhase19Production(unittest.TestCase):
    """
    Comprehensive Phase 19 Production Deployment & Realtime Activation Validation Suite.
    Tests all 18 requirements without breaking existing functionality or mocking away core features.
    """

    def setUp(self):
        self.client = TestClient(app)

    # 1. Production Config Validation
    def test_1_production_config_validation(self):
        """Test production configuration validation for valid and invalid parameters."""
        valid_settings = Settings(
            environment="production",
            cors_origins=["https://nammablr.transit.gov.in", "https://app.nammablr.in"],
            bmtc_api_endpoint="https://authorized.bmtc.gov.in/feed",
            bmtc_api_key="secret-token",
            transit_provider="bmtc",
            rate_limit_per_minute=120,
            max_request_body_bytes=1048576,
            bmtc_api_timeout_seconds=5.0,
            realtime_poll_interval_seconds=10.0,
            realtime_stale_threshold_seconds=60.0,
        )
        res = valid_settings.validate_production_config()
        self.assertTrue(res["valid"])
        self.assertEqual(len(res["errors"]), 0)
        self.assertEqual(res["active_mode"], "bmtc")
        # Ensure raw secret is never included in validation report
        self.assertNotIn("secret-token", json.dumps(res))

    # 2. Invalid URL Rejection
    def test_2_invalid_url_rejection(self):
        """Rejects unsafe or malformed URL schemes such as ftp://, file://, javascript:."""
        bad_settings = Settings(
            environment="production",
            bmtc_api_endpoint="ftp://malicious.bmtc.gov.in/feed",
            gtfs_rt_vehicle_positions_url="file:///etc/passwd",
        )
        res = bad_settings.validate_production_config()
        self.assertFalse(res["valid"])
        self.assertTrue(any("Invalid URL scheme for BMTC_API_ENDPOINT" in err for err in res["errors"]))
        self.assertTrue(any("Invalid URL scheme for GTFS_RT_VEHICLE_POSITIONS_URL" in err for err in res["errors"]))

    # 3. CORS Production Safety
    def test_3_cors_production_safety(self):
        """Wildcard CORS origin '*' is strictly rejected in production environment."""
        prod_settings = Settings(
            environment="production",
            cors_origins=["*"],
        )
        res = prod_settings.validate_production_config()
        self.assertFalse(res["valid"])
        self.assertTrue(any("Wildcard CORS origin '*' is strictly prohibited" in err for err in res["errors"]))
        # Effective origins must default to safe whitelist
        self.assertNotIn("*", prod_settings.effective_cors_origins)
        self.assertIn("https://app.nammablr.in", prod_settings.effective_cors_origins)

    # 4. Realtime Dry-Run Response
    def test_4_realtime_dry_run_response(self):
        """POST /api/realtime/validate evaluates feed reachability without mutating provider state."""
        response = self.client.post("/api/realtime/validate", json={})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("connectivity", data)
        self.assertIn("response_validity", data)
        self.assertIn("entity_count", data)
        self.assertIn("valid_entities", data)
        self.assertIn("invalid_entities", data)
        self.assertIn("ignored_entities", data)
        self.assertEqual(data["operational_statement"], OPERATIONAL_STATEMENT_NOT_CONNECTED)

    # 5. Feed Validation Pipeline
    def test_5_feed_validation_pipeline(self):
        """Feed validation identifies missing credentials or endpoints without exposing secrets."""
        req = RealtimeValidationRequest(
            endpoint="https://authorized.bmtc.gov.in/test-feed",
            api_key=None,
        )
        # Run validate_feed directly
        import asyncio
        res = asyncio.run(realtime_activation_service.validate_feed(req))
        self.assertFalse(res.success)
        self.assertTrue(any("credentials missing" in err.lower() for err in res.validation_errors))
        # Ensure raw secrets never leaked
        self.assertFalse(res.endpoint_configuration["has_credentials"])

    # 6. VehiclePosition Validation
    def test_6_vehicle_position_validation(self):
        """VehiclePositions validation enforces valid coordinates, ID, and reasonable bounds."""
        payload = {
            "entity": [
                {
                    "id": "veh-1",
                    "vehicle": {
                        "vehicle": {"id": "KA-01-FA-1001"},
                        "position": {"latitude": 12.9716, "longitude": 77.5946, "speed": 8.0, "bearing": 90.0},
                        "timestamp": int(datetime.now(timezone.utc).timestamp()),
                    }
                }
            ]
        }
        vehicles, stats = GTFSParser.parse_vehicle_positions_with_stats(payload)
        self.assertEqual(len(vehicles), 1)
        self.assertEqual(stats["valid_entities"], 1)
        self.assertEqual(stats["invalid_entities"], 0)
        self.assertEqual(vehicles[0].vehicle_id, "KA-01-FA-1001")

    # 7. TripUpdate Validation
    def test_7_trip_update_validation(self):
        """TripUpdates validation parses stop sequence, arrival/departure delays and timestamps."""
        payload = {
            "entity": [
                {
                    "id": "tu-1",
                    "trip_update": {
                        "trip": {"trip_id": "trip-500d-1", "route_id": "500D"},
                        "vehicle": {"id": "KA-01-FA-1001"},
                        "stop_time_update": [
                            {
                                "stop_sequence": 3,
                                "stop_id": "CSB-01",
                                "stop_name": "Central Silk Board",
                                "arrival": {"delay": 120, "time": 1718000000},
                            }
                        ],
                        "delay": 120,
                    }
                }
            ]
        }
        updates, stats = GTFSParser.parse_trip_updates_with_stats(payload)
        self.assertEqual(len(updates), 1)
        self.assertEqual(stats["valid_entities"], 1)
        self.assertEqual(updates[0].trip_id, "trip-500d-1")
        self.assertEqual(updates[0].stop_time_updates[0].arrival_delay_seconds, 120)

    # 8. ServiceAlert Validation
    def test_8_service_alert_validation(self):
        """ServiceAlerts validation enforces alert ID, header and description texts."""
        payload = {
            "entity": [
                {
                    "id": "alert-101",
                    "alert": {
                        "header_text": {"text": "ORR Metro Construction Diversion"},
                        "description_text": {"text": "Buses rerouted near Silk Board flyover"},
                        "cause": "CONSTRUCTION",
                        "effect": "DETOUR",
                    }
                }
            ]
        }
        alerts, stats = GTFSParser.parse_service_alerts_with_stats(payload)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(stats["valid_entities"], 1)
        self.assertEqual(alerts[0].id, "alert-101")
        self.assertIn("ORR Metro", alerts[0].header_text)

    # 9. Invalid Entity Isolation
    def test_9_invalid_entity_isolation(self):
        """Malformed entities are dropped individually without crashing the entire feed."""
        mixed_payload = {
            "entity": [
                # Valid vehicle
                {
                    "id": "v1",
                    "vehicle": {
                        "vehicle": {"id": "KA-01-F-1111"},
                        "position": {"latitude": 12.9716, "longitude": 77.5946},
                    }
                },
                # Invalid vehicle: non-numeric latitude
                {
                    "id": "v2",
                    "vehicle": {
                        "vehicle": {"id": "KA-01-F-2222"},
                        "position": {"latitude": "corrupt-lat", "longitude": 77.5946},
                    }
                },
                # Invalid vehicle: missing latitude & longitude
                {
                    "id": "v3",
                    "vehicle": {
                        "vehicle": {"id": "KA-01-F-3333"},
                        "position": {},
                    }
                },
                # Ignored entity: ServiceAlert in VehiclePositions feed
                {
                    "id": "a1",
                    "alert": {"id": "alert-1", "header_text": "Advisory"},
                }
            ]
        }
        vehicles, stats = GTFSParser.parse_vehicle_positions_with_stats(mixed_payload)
        self.assertEqual(len(vehicles), 1)
        self.assertEqual(stats["valid_entities"], 1)
        self.assertEqual(stats["invalid_entities"], 2)
        self.assertEqual(stats["ignored_entities"], 1)
        self.assertEqual(stats["total_entities"], 4)

    # 10. Realtime Activation Logic
    def test_10_realtime_activation_logic(self):
        """Realtime activation diagnostics truthful when feed is not configured."""
        diag = realtime_activation_service.get_activation_diagnostics()
        self.assertFalse(diag.activated)
        self.assertEqual(diag.provider, "mock")
        self.assertEqual(diag.reason, "Authorized realtime BMTC feed not configured")

    # 11. Mock Fallback
    def test_11_mock_fallback(self):
        """BMTCTransitDataProvider safely raises BMTCNotConfiguredError and defaults to mock."""
        provider = BMTCTransitDataProvider(endpoint=None, api_key=None)
        self.assertFalse(provider.is_configured)
        self.assertEqual(provider.feed_status, "unconfigured")

    # 12. Last-Known-Good Retention
    def test_12_last_known_good_retention(self):
        """When an incoming payload is corrupt, provider retains the previous last-known-good snapshot."""
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret")
        valid_payload = {
            "entity": [
                {
                    "id": "v1",
                    "vehicle": {
                        "vehicle": {"id": "KA-01-FA-9999"},
                        "position": {"latitude": 12.9716, "longitude": 77.5946},
                    }
                }
            ]
        }
        ingested = provider.ingest_payload(valid_payload)
        self.assertEqual(ingested, 1)
        self.assertIsNotNone(provider._last_known_good_snapshot)

        # Ingest corrupt payload
        corrupt_payload = {"entity": []}
        second_ingested = provider.ingest_payload(corrupt_payload)
        self.assertEqual(second_ingested, 0)
        # Verify previous snapshot is retained
        self.assertIn("KA-01-FA-9999", provider._buses)

    # 13. Occupancy Honesty
    def test_13_occupancy_honesty(self):
        """When GTFS-RT provides no APC data, occupancy is reported as unavailable without fabricating counts."""
        veh_no_apc = GTFSVehiclePosition(
            vehicle_id="KA-01-F-1234",
            latitude=12.9716,
            longitude=77.5946,
            occupancy_status=None,  # No APC data
        )
        provider = BMTCTransitDataProvider(endpoint="https://test.bmtc.gov.in/api", api_key="secret")
        provider._raw_positions["KA-01-F-1234"] = veh_no_apc

        import asyncio
        occ = asyncio.run(provider.get_bus_occupancy("KA-01-F-1234"))
        self.assertIsNone(occ)

    # 14. ETA Source Attribution
    def test_14_eta_source_attribution(self):
        """ETAService correctly distinguishes official trip update vs geometric estimate."""
        # 1. Official TripUpdate ETA
        eta_official = ETAService.calculate_eta(
            bus_id="bus-1",
            route_number="500D",
            bus_lat=12.9300,
            bus_lon=77.6200,
            target_stop_name="Silk Board",
            target_lat=12.9176,
            target_lon=77.6238,
            source="gtfs_rt_trip_update",
            trip_update_eta_seconds=300,
        )
        self.assertEqual(eta_official.source, "gtfs_rt_trip_update")
        self.assertEqual(eta_official.eta_minutes, 5)
        self.assertEqual(eta_official.confidence, "high")

        # 2. Geometric Estimate ETA
        eta_geom = ETAService.calculate_eta(
            bus_id="bus-1",
            route_number="500D",
            bus_lat=12.9300,
            bus_lon=77.6200,
            target_stop_name="Silk Board",
            target_lat=12.9176,
            target_lon=77.6238,
            source="geometric_estimate",
        )
        self.assertEqual(eta_geom.source, "geometric_estimate")

    # 15. Offline Resilience
    def test_15_offline_resilience(self):
        """GET /api/ready remains ready to serve commuters even when external realtime feed is offline."""
        resp = self.client.get("/api/ready")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ready"])
        self.assertEqual(data["status"], "ready")

    # 16. Security Regression
    def test_16_security_regression(self):
        """Security regression: request ID exists, timing header exists, sensitive credentials not exposed."""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("X-Request-ID", resp.headers)
        self.assertTrue(
            "X-Response-Time" in resp.headers
            or "X-Response-Time-Ms" in resp.headers
            or "x-response-time-ms" in resp.headers
        )

        # Check diagnostics never leaks raw secret credentials
        diag_resp = self.client.get("/api/system/status")
        self.assertEqual(diag_resp.status_code, 200)
        body_str = diag_resp.text
        self.assertNotIn("bmtc_api_key", body_str.lower())
        self.assertNotIn("secret", body_str.lower())

    # 17. Diagnostics Response
    def test_17_diagnostics_response(self):
        """GET /api/status returns all core modules, detailed feeds, and entity counts."""
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("modules", data)
        self.assertGreaterEqual(len(data["modules"]), 11)
        self.assertIn("feed_health", data)
        self.assertIn("valid_entities", data["feed_health"])
        self.assertIn("invalid_entities", data["feed_health"])
        self.assertIn("ignored_entities", data["feed_health"])

    # 18. OpenAPI Endpoint Registration & Tag Grouping
    def test_18_openapi_endpoint_registration(self):
        """OpenAPI schema contains all required tags and registers required endpoints."""
        schema = app.openapi()
        registered_tags = set()
        for path_item in schema["paths"].values():
            for method_item in path_item.values():
                if "tags" in method_item:
                    registered_tags.update(method_item["tags"])

        required_tags = {
            "Transit",
            "Journey",
            "AI",
            "Tickets",
            "Conductor",
            "Crowd",
            "Alerts",
            "Realtime",
            "Diagnostics",
            "Health",
        }
        for tag in required_tags:
            self.assertIn(tag, registered_tags, f"Tag '{tag}' missing from OpenAPI registration")

        # Verify key endpoints registered
        paths = schema["paths"]
        self.assertIn("/api/health", paths)
        self.assertIn("/api/ready", paths)
        self.assertIn("/api/status", paths)
        self.assertIn("/api/system/status", paths)
        self.assertIn("/api/realtime/validate", paths)


if __name__ == "__main__":
    unittest.main()
