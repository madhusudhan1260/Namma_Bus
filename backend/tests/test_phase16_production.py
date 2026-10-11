import os
import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import (
    settings,
    Settings,
    OPERATIONAL_STATEMENT_NOT_CONNECTED,
)
from app.core.logging_config import sanitize_dict
from app.services.bmtc_provider import BMTCTransitDataProvider
from app.services.provider_factory import get_transit_provider, get_provider_health, get_provider_info
from app.services.mock_provider import MockTransitDataProvider
from app.services.gtfs.import_static import GTFSStaticImporter


class TestPhase16ProductionDeployment(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.sample_valid_payload = {
            "header": {"gtfs_realtime_version": "2.0", "timestamp": 1720000000},
            "entity": [
                {
                    "id": "v1",
                    "vehicle": {
                        "trip": {"trip_id": "t-500d-1", "route_id": "500D"},
                        "position": {"latitude": 12.9176, "longitude": 77.6238, "speed": 8.5},
                        "vehicle": {"id": "KA-01-F-4819", "label": "500D-01"},
                        "timestamp": 1720000000,
                    },
                }
            ],
        }

    def test_1_production_environment_validation(self):
        """Validates production config validation rules without exposing credentials."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "CORS_ALLOWED_ORIGINS": "*"}):
            s = Settings()
            val = s.validate_production_config()
            self.assertEqual(val["environment"], "production")
            self.assertIn("CORS wildcard '*' is forbidden in production. Defaulted to secure origins.", val["warnings"])
            self.assertEqual(val["operational_statement"], OPERATIONAL_STATEMENT_NOT_CONNECTED)

    def test_2_cors_production_restrictions(self):
        """In production, wildcard origins are replaced with explicit secure domains."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "CORS_ALLOWED_ORIGINS": "*"}):
            s = Settings()
            origins = s.effective_cors_origins
            self.assertNotIn("*", origins)
            self.assertTrue(any("nammablr" in o for o in origins))

    def test_3_realtime_feed_validation_valid(self):
        """Valid GTFS-RT feed payload with usable coordinates passes validation."""
        provider = BMTCTransitDataProvider(endpoint="https://authorized.bmtc.gov.in/api", api_key="test-key")
        is_valid, reason, vehicles = provider.validate_feed_payload(self.sample_valid_payload)
        self.assertTrue(is_valid)
        self.assertEqual(len(vehicles), 1)

    def test_4_realtime_feed_validation_empty_rejected(self):
        """Empty GTFS-RT feed payload is rejected by validation."""
        provider = BMTCTransitDataProvider(endpoint="https://authorized.bmtc.gov.in/api", api_key="test-key")
        is_valid, reason, vehicles = provider.validate_feed_payload({"entity": []})
        self.assertFalse(is_valid)
        self.assertIn("0 entities", reason)

    def test_5_realtime_feed_validation_out_of_bounds_coords_rejected(self):
        """Vehicles with coordinates outside Bengaluru metropolitan area are rejected."""
        provider = BMTCTransitDataProvider(endpoint="https://authorized.bmtc.gov.in/api", api_key="test-key")
        out_of_bounds_payload = {
            "entity": [
                {
                    "id": "v-london",
                    "vehicle": {
                        "position": {"latitude": 51.5074, "longitude": -0.1278},  # London coordinates
                        "vehicle": {"id": "UK-BUS-1"},
                    },
                }
            ]
        }
        is_valid, reason, vehicles = provider.validate_feed_payload(out_of_bounds_payload)
        self.assertFalse(is_valid)
        self.assertIn("outside Bengaluru", reason)

    def test_6_exponential_backoff_calculation(self):
        """Exponential backoff scales delay from 5s to 40s and caps at 60s."""
        provider = BMTCTransitDataProvider(endpoint="https://authorized.bmtc.gov.in/api", api_key="test-key")
        provider._consecutive_failures = 0
        self.assertEqual(provider.calculate_backoff_delay(), provider.poll_interval)

        provider._consecutive_failures = 1
        self.assertEqual(provider.calculate_backoff_delay(), 5.0)

        provider._consecutive_failures = 2
        self.assertEqual(provider.calculate_backoff_delay(), 10.0)

        provider._consecutive_failures = 3
        self.assertEqual(provider.calculate_backoff_delay(), 20.0)

        provider._consecutive_failures = 4
        self.assertEqual(provider.calculate_backoff_delay(), 40.0)

        provider._consecutive_failures = 10
        self.assertEqual(provider.calculate_backoff_delay(), 60.0)  # Capped at MAX_BACKOFF_SECONDS

    def test_7_last_known_good_snapshot_retention(self):
        """On transient upstream failure, last-known-good telemetry is retained."""
        provider = BMTCTransitDataProvider(endpoint="https://authorized.bmtc.gov.in/api", api_key="test-key")
        count = provider.ingest_payload(self.sample_valid_payload)
        self.assertEqual(count, 1)
        self.assertIsNotNone(provider._last_known_good_snapshot)

        # Trigger failure
        provider._handle_fetch_error()
        self.assertEqual(provider._consecutive_failures, 1)
        # Buses and locations remain available from snapshot
        self.assertEqual(len(provider._buses), 1)

    def test_8_realtime_to_stale_transition(self):
        """Feed transitions to stale when elapsed time exceeds stale threshold."""
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="test-key",
            stale_threshold=5.0,
        )
        provider.ingest_payload(self.sample_valid_payload)
        self.assertFalse(provider.is_stale)

        # Artificially age the timestamp
        provider._last_updated_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        self.assertTrue(provider.is_stale)
        self.assertEqual(provider.feed_status, "stale")

    def test_9_status_endpoint_alias_and_diagnostics(self):
        """GET /api/status returns SystemStatusResponse with diagnostics block."""
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("diagnostics", data)
        self.assertIn("backend", data["diagnostics"])
        self.assertIn("transit", data["diagnostics"])
        self.assertIn("gtfs", data["diagnostics"])
        self.assertIn("realtime", data["diagnostics"])

    def test_10_logging_sanitizer_redacts_credentials(self):
        """Logging sanitizer strictly redacts API keys, tokens, and secrets."""
        test_data = {
            "api_key": "super-secret-key-12345",
            "bmtc_api_key": "bmtc-secret",
            "token": "bearer-token-abc",
            "safe_field": "public_data",
            "nested": {"secret": "hidden-value", "vehicle_id": "KA-01-F-4819"},
        }
        sanitized = sanitize_dict(test_data)
        self.assertEqual(sanitized["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["bmtc_api_key"], "[REDACTED]")
        self.assertEqual(sanitized["token"], "[REDACTED]")
        self.assertEqual(sanitized["safe_field"], "public_data")
        self.assertEqual(sanitized["nested"]["secret"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["vehicle_id"], "KA-01-F-4819")

    def test_11_docker_compose_and_dockerfile_sanity(self):
        """Verifies docker-compose.yml and Dockerfile exist and are non-root compliant."""
        dockerfile_path = os.path.join(os.path.dirname(__file__), "..", "Dockerfile")
        compose_path = os.path.join(os.path.dirname(__file__), "..", "..", "docker-compose.yml")

        self.assertTrue(os.path.isfile(dockerfile_path))
        self.assertTrue(os.path.isfile(compose_path))

        with open(dockerfile_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("appuser", content)
            self.assertIn("HEALTHCHECK", content)
            self.assertIn("STOPSIGNAL", content)

        with open(compose_path, "r", encoding="utf-8") as f:
            compose_content = f.read()
            self.assertIn("nammablr-backend", compose_content)
            self.assertIn("8001:8001", compose_content)

    def test_12_operational_statement_integrity(self):
        """The exact unconfigured operational statement string is preserved."""
        expected = "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED"
        self.assertEqual(OPERATIONAL_STATEMENT_NOT_CONNECTED, expected)


if __name__ == "__main__":
    unittest.main()
