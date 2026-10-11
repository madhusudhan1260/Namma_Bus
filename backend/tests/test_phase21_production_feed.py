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
from backend.app.services.gtfs.models import (
    GTFSVehiclePosition,
    GTFSTripUpdate,
    GTFSStopTimeUpdate,
    GTFSOccupancyStatus,
)
from backend.app.services.gtfs.normalizer import GTFSNormalizer
from backend.app.services.gtfs.repository import GTFSRepository
from backend.app.services.bmtc_provider import BMTCTransitDataProvider
from backend.app.services.eta_service import ETAService
from backend.app.services.alert_service import alert_service
from backend.app.services.provider_factory import get_transit_provider, get_provider_health
from backend.app.services.metrics_service import metrics_service
from backend.app.models.transit import ServiceAlert


class TestPhase21ProductionFeed(unittest.TestCase):
    """
    Phase 21 Comprehensive Automated Test Suite:
    AUTHORIZED BMTC DATA ACTIVATION + PRODUCTION FEED MANAGEMENT
    Verifies all 30 tests across configuration, state machine, GTFS-RT pipeline,
    ETA attribution, static validation, alert separation, safe diagnostic probe,
    observability, and error handling.
    """

    def setUp(self):
        self.client = TestClient(app)

    # 1. Config: mock_mode when UNCONFIGURED
    def test_1_config_mock_mode_when_unconfigured(self):
        s = Settings(bmtc_api_endpoint=None, bmtc_api_key=None, transit_provider="mock")
        report = s.validate_production_config()
        self.assertEqual(report["diagnostic_state"], "mock_mode")
        self.assertFalse(report["bmtc_configured"])

    # 2. Config: bmtc_incomplete when endpoint present but key missing
    def test_2_config_bmtc_incomplete_missing_key(self):
        s = Settings(bmtc_api_endpoint="https://authorized.bmtc.gov.in/api", bmtc_api_key=None)
        report = s.validate_production_config()
        self.assertEqual(report["diagnostic_state"], "bmtc_incomplete")
        self.assertFalse(report["bmtc_configured"])

    # 3. Config: bmtc_invalid_urls when URL malformed
    def test_3_config_bmtc_invalid_urls(self):
        s = Settings(
            bmtc_api_endpoint="not-a-valid-url",
            bmtc_api_key="valid-key-12345",
            transit_provider="bmtc",
        )
        report = s.validate_production_config()
        self.assertIn(report["diagnostic_state"], ("bmtc_invalid_urls", "bmtc_configuration_invalid"))

    # 4. Config: bmtc_configured_valid when properly set
    def test_4_config_bmtc_configured_valid(self):
        s = Settings(
            bmtc_api_endpoint="https://authorized.bmtc.gov.in/feed/gtfs-rt",
            bmtc_api_key="valid-key-12345",
            gtfs_rt_vehicle_positions_url="https://authorized.bmtc.gov.in/feed/vehicle-positions",
            transit_provider="bmtc",
        )
        report = s.validate_production_config()
        self.assertEqual(report["diagnostic_state"], "bmtc_configured_valid")
        self.assertTrue(report["bmtc_configured"])

    # 5. State machine: UNCONFIGURED state
    def test_5_state_machine_unconfigured(self):
        provider = BMTCTransitDataProvider(endpoint=None, api_key=None)
        self.assertFalse(provider.is_configured)
        self.assertEqual(provider.feed_status, "unconfigured")

    # 6. State machine: transition to CONNECTED on successful ingest
    def test_6_state_machine_connected_on_ingest(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        payload = {
            "entity": [
                {
                    "id": "VP-KA01F9999",
                    "vehicle": {
                        "trip": {"trip_id": "T-335E-01", "route_id": "335E"},
                        "position": {"latitude": 12.9716, "longitude": 77.5946, "speed": 22.0},
                        "timestamp": int(datetime.now(timezone.utc).timestamp()),
                        "vehicle": {"id": "KA01F9999", "label": "KA-01-F-9999"},
                    },
                }
            ]
        }
        count = provider.ingest_payload(payload)
        self.assertEqual(count, 1)
        self.assertIn(provider.feed_status, ("connected", "healthy"))

    # 7. State machine: transition to STALE when elapsed > stale_threshold
    def test_7_state_machine_transition_to_stale(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
            stale_threshold=5.0,
        )
        provider._last_updated_at = datetime.fromtimestamp(1000000, tz=timezone.utc)
        self.assertTrue(provider.is_stale)
        self.assertEqual(provider.feed_status, "stale")

    # 8. State machine: backoff delay increases exponentially
    def test_8_state_machine_backoff_increases(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        provider._consecutive_failures = 1
        d1 = provider.calculate_backoff_delay(add_jitter=False)
        provider._consecutive_failures = 3
        d3 = provider.calculate_backoff_delay(add_jitter=False)
        self.assertGreater(d3, d1)
        self.assertEqual(d1, 5.0)
        self.assertEqual(d3, 20.0)

    # 9. State machine: backoff delay capped at MAX_BACKOFF_SECONDS
    def test_9_state_machine_backoff_capped(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        provider._consecutive_failures = 10
        delay = provider.calculate_backoff_delay(add_jitter=False)
        self.assertEqual(delay, provider.MAX_BACKOFF_SECONDS)

    # 10. Pipeline: parse valid VehiclePosition entity
    def test_10_pipeline_parse_valid_entity(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        payload = {
            "entity": [
                {
                    "id": "VP-KA01F1234",
                    "vehicle": {
                        "position": {"latitude": 12.9352, "longitude": 77.6245, "speed": 18.5},
                        "vehicle": {"id": "KA01F1234", "label": "KA-01-F-1234"},
                        "trip": {"route_id": "500D"},
                    },
                }
            ]
        }
        count = provider.ingest_payload(payload)
        self.assertEqual(count, 1)
        buses = asyncio.run(provider.get_buses())
        self.assertEqual(len(buses), 1)
        self.assertEqual(buses[0].bus_id, "KA01F1234")

    # 11. Pipeline: reject entity with coordinates outside Bengaluru bounds
    def test_11_pipeline_reject_out_of_bounds_entity(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        # Delhi coords: lat 28.61, lon 77.20
        payload = {
            "entity": [
                {
                    "id": "VP-DELHI",
                    "vehicle": {
                        "position": {"latitude": 28.6139, "longitude": 77.2090},
                        "vehicle": {"id": "DL01A1111"},
                    },
                }
            ]
        }
        count = provider.ingest_payload(payload)
        self.assertEqual(count, 0)
        self.assertEqual(len(provider._buses), 0)

    # 12. Pipeline: reject entity with invalid timestamp in far future
    def test_12_pipeline_reject_far_future_timestamp(self):
        # 10 days in future
        future_ts = int(datetime.now(timezone.utc).timestamp()) + 864000
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        payload = {
            "entity": [
                {
                    "id": "VP-FUTURE",
                    "vehicle": {
                        "position": {"latitude": 12.9716, "longitude": 77.5946},
                        "timestamp": future_ts,
                        "vehicle": {"id": "KA01F9999"},
                    },
                }
            ]
        }
        count = provider.ingest_payload(payload)
        self.assertEqual(count, 0)

    # 13. Pipeline: vehicle deduplication keeping latest timestamp
    def test_13_pipeline_deduplication_keeps_latest(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        ts1 = 1700000000
        ts2 = 1700000100
        payload = {
            "entity": [
                {
                    "id": "VP-1",
                    "vehicle": {
                        "position": {"latitude": 12.9716, "longitude": 77.5946},
                        "speed_kmh": 10.0,
                        "timestamp": ts1,
                        "vehicle": {"id": "KA01F8888"},
                    },
                },
                {
                    "id": "VP-2",
                    "vehicle": {
                        "position": {"latitude": 12.9720, "longitude": 77.5950},
                        "speed_kmh": 35.0,
                        "timestamp": ts2,
                        "vehicle": {"id": "KA01F8888"},
                    },
                },
            ]
        }
        count = provider.ingest_payload(payload)
        self.assertEqual(count, 1)
        buses = asyncio.run(provider.get_buses())
        self.assertEqual(buses[0].speed, 35.0)

    # 14. Pipeline: partial feed with VehiclePositions only works
    def test_14_pipeline_positions_only_without_trip_updates(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        payload = {
            "entity": [
                {
                    "id": "VP-1",
                    "vehicle": {
                        "position": {"latitude": 12.9716, "longitude": 77.5946},
                        "vehicle": {"id": "KA01F5001"},
                    },
                }
            ]
        }
        count = provider.ingest_payload(payload, trip_updates_data=None)
        self.assertEqual(count, 1)
        self.assertEqual(len(provider._trip_updates), 0)

    # 15. ETA: Official TripUpdate ETA attribution
    def test_15_eta_official_trip_update_attribution(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        target_time = int(datetime.now(timezone.utc).timestamp()) + 600
        vp_payload = {
            "entity": [
                {
                    "id": "VP-1",
                    "vehicle": {
                        "position": {"latitude": 12.9716, "longitude": 77.5946, "speed": 20.0},
                        "vehicle": {"id": "KA01F6001"},
                        "trip": {"trip_id": "TRIP-1"},
                    },
                }
            ]
        }
        tu_payload = {
            "entity": [
                {
                    "id": "TU-1",
                    "trip_update": {
                        "trip": {"trip_id": "TRIP-1"},
                        "vehicle": {"id": "KA01F6001"},
                        "stop_time_update": [
                            {
                                "stop_id": "STOP-CSB",
                                "stop_name": "Central Silk Board Junction",
                                "arrival": {"time": target_time},
                            }
                        ],
                    },
                }
            ]
        }
        provider.ingest_payload(vp_payload, tu_payload)
        eta = asyncio.run(provider.get_eta("KA01F6001", "Central Silk Board Junction"))
        self.assertIsNotNone(eta)
        self.assertEqual(eta.source, "gtfs_rt_trip_update")

    # 16. ETA: Geometric fallback when TripUpdate unavailable
    def test_16_eta_geometric_fallback_attribution(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        vp_payload = {
            "entity": [
                {
                    "id": "VP-1",
                    "vehicle": {
                        "position": {"latitude": 12.9716, "longitude": 77.5946, "speed": 20.0},
                        "vehicle": {"id": "KA01F7001"},
                    },
                }
            ]
        }
        provider.ingest_payload(vp_payload, trip_updates_data=None)
        eta = asyncio.run(provider.get_eta("KA01F7001", "Central Silk Board Junction"))
        self.assertIsNotNone(eta)
        self.assertEqual(eta.source, "geometric_estimate")

    # 17. ETA: ETA calculation with valid speed and distance
    def test_17_eta_calculation_positive_bounds(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        vp_payload = {
            "entity": [
                {
                    "id": "VP-1",
                    "vehicle": {
                        "position": {"latitude": 12.9716, "longitude": 77.5946, "speed": 25.0},
                        "vehicle": {"id": "KA01F7002"},
                    },
                }
            ]
        }
        provider.ingest_payload(vp_payload)
        eta = asyncio.run(provider.get_eta("KA01F7002", "Central Silk Board Junction"))
        self.assertGreater(eta.eta_minutes, 0)
        self.assertGreater(eta.distance_km, 0)
        self.assertGreater(eta.current_speed_kmh, 0.0)

    # 18. Static GTFS: get_validation_report runs cleanly
    def test_18_static_gtfs_validation_report(self):
        repo = GTFSRepository()
        report = repo.get_validation_report()
        self.assertEqual(report["data_source"], "Scheduled Data")
        self.assertIn("routes_count", report)
        self.assertIn("stops_count", report)
        self.assertIn("orphan_trips", report)

    # 19. Static GTFS: Scheduled Data distinct from Realtime Feed
    def test_19_static_gtfs_scheduled_distinct_from_realtime(self):
        repo = GTFSRepository()
        report = repo.get_validation_report()
        self.assertNotEqual(report["data_source"], "Realtime Feed")
        self.assertEqual(report["data_source"], "Scheduled Data")

    # 20. Alerts: gtfs_rt source distinct from demo source
    def test_20_alerts_source_separation(self):
        alert_service.reset()
        alert_service._alerts.clear()
        rt_alert = ServiceAlert(
            id="ALERT-RT-01",
            title="BMTC Official Alert",
            description="Official realtime alert from municipal feed",
            severity="WARNING",
            source="gtfs_rt",
        )
        demo_alert = ServiceAlert(
            id="ALERT-DEMO-01",
            title="Demo Advisory",
            description="Simulated alert for demonstration",
            severity="INFO",
            source="demo",
        )
        alert_service.add_alert(rt_alert)
        alert_service.add_alert(demo_alert)

        rt_alerts = alert_service.get_alerts(source="gtfs_rt")
        demo_alerts = alert_service.get_alerts(source="demo")
        self.assertEqual(len(rt_alerts), 1)
        self.assertEqual(rt_alerts[0].id, "ALERT-RT-01")
        self.assertEqual(len(demo_alerts), 1)
        self.assertEqual(demo_alerts[0].id, "ALERT-DEMO-01")
        alert_service.reset()

    # 21. Alerts: filter by source via HTTP endpoint
    def test_21_alerts_filter_by_source_endpoint(self):
        res_rt = self.client.get("/api/alerts?source=gtfs_rt")
        self.assertEqual(res_rt.status_code, 200)
        for a in res_rt.json():
            self.assertEqual(a["source"], "gtfs_rt")

        res_demo = self.client.get("/api/alerts?source=demo")
        self.assertEqual(res_demo.status_code, 200)
        for a in res_demo.json():
            self.assertEqual(a["source"], "demo")

    # 22. Probe: GET /api/realtime/test returns credential-safe structure
    def test_22_probe_realtime_test_credential_safe(self):
        res = self.client.get("/api/realtime/test")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("configured", data)
        self.assertIn("provider", data)
        self.assertIn("feed_status", data)
        self.assertIn("vehicle_positions", data)
        self.assertIn("trip_updates", data)
        self.assertIn("service_alerts", data)
        self.assertIn("message", data)

        text = json.dumps(data)
        self.assertNotIn("api_key", text.lower())
        self.assertNotIn("bearer", text.lower())
        self.assertNotIn("secret", text.lower())
        self.assertNotIn("token", text.lower())

    # 23. Probe: unconfigured state returns exact operational statement
    def test_23_probe_unconfigured_statement(self):
        res = self.client.get("/api/realtime/test")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["message"], OPERATIONAL_STATEMENT_NOT_CONNECTED)

    # 24. Observability: metrics_service tracks poll attempts and successes
    def test_24_metrics_tracks_poll_attempts(self):
        metrics_service.realtime_poll_attempts = 0
        metrics_service.realtime_successful_polls = 0
        metrics_service.record_realtime_poll(success=True)
        self.assertEqual(metrics_service.realtime_poll_attempts, 1)
        self.assertEqual(metrics_service.realtime_successful_polls, 1)

    # 25. Observability: metrics_service tracks entity counts
    def test_25_metrics_tracks_entity_counts(self):
        metrics_service.vehicle_entities_received = 0
        metrics_service.vehicle_entities_valid = 0
        metrics_service.vehicle_entities_invalid = 0
        metrics_service.record_vehicle_entity(valid=True, count=5)
        metrics_service.record_vehicle_entity(valid=False, count=2)
        self.assertEqual(metrics_service.vehicle_entities_received, 7)
        self.assertEqual(metrics_service.vehicle_entities_valid, 5)
        self.assertEqual(metrics_service.vehicle_entities_invalid, 2)

    # 26. Observability: metrics included in get_summary()
    def test_26_metrics_included_in_summary(self):
        summary = metrics_service.get_summary()
        self.assertIn("realtime_poll_attempts", summary)
        self.assertIn("realtime_successful_polls", summary)
        self.assertIn("vehicle_entities_received", summary)
        self.assertIn("vehicle_entities_valid", summary)

    # 27. Error handling: transient HTTP failure retains last-known-good
    def test_27_error_handling_retains_last_known_good(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        payload = {
            "entity": [
                {
                    "id": "VP-LKG",
                    "vehicle": {
                        "position": {"latitude": 12.9716, "longitude": 77.5946},
                        "vehicle": {"id": "KA01F1111"},
                    },
                }
            ]
        }
        provider.ingest_payload(payload)
        self.assertEqual(len(provider._buses), 1)

        # Simulate network error
        provider._handle_fetch_error()
        self.assertEqual(len(provider._buses), 1)
        self.assertIsNotNone(provider._last_known_good_snapshot)

    # 28. Error handling: consecutive failures transition to degraded/stale
    def test_28_error_handling_consecutive_failures(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
            stale_threshold=0.01,
        )
        payload = {
            "entity": [
                {
                    "id": "VP-FAIL",
                    "vehicle": {
                        "position": {"latitude": 12.9716, "longitude": 77.5946},
                        "vehicle": {"id": "KA01F2222"},
                    },
                }
            ]
        }
        provider.ingest_payload(payload)
        provider._last_updated_at = datetime.fromtimestamp(1000000, tz=timezone.utc)
        provider._handle_fetch_error()
        self.assertEqual(provider.feed_status, "stale")

    # 29. Error handling: malformed feed payload rejected safely
    def test_29_error_handling_malformed_payload_rejected(self):
        provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api",
            api_key="authorized-token",
        )
        malformed_data = {"invalid_key": [1, 2, 3]}
        count = provider.ingest_payload(malformed_data)
        self.assertEqual(count, 0)

    # 30. Error handling: HTTP probe to /api/system/status reflects realtime metrics
    def test_30_system_status_reflects_metrics(self):
        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("diagnostics", data)
        self.assertIn("realtime", data["diagnostics"])
        self.assertIn("vehicle_positions", data["diagnostics"]["realtime"])


if __name__ == "__main__":
    unittest.main()
