import unittest
from datetime import datetime, timezone, timedelta
from backend.app.services.bmtc_provider import BMTCTransitDataProvider
from backend.app.services.provider_factory import get_transit_provider
from backend.app.services.mock_provider import MockTransitDataProvider
from backend.app.core.config import settings


class TestPhase27RealtimeResilience(unittest.TestCase):
    """
    Phase 27 automated verification:
    - Valid, malformed, and empty GTFS-RT feed ingestion
    - Geographic bounding box coordinate validation
    - Vehicle deduplication retaining latest timestamp
    - Stale feed state machine transitions
    - Consecutive failure backoff progression (5s, 10s, 20s, 40s, 60s)
    - Last-known-good telemetry retention during transient errors
    - Automatic recovery on valid payload
    - Official TripUpdate ETA vs geometric ETA calculation
    - Passenger occupancy honesty (no fabricated APC counts)
    - Safe provider fallback to MockTransitDataProvider
    - Independent component health reporting (VP, TU, SA)
    """

    def setUp(self):
        self.provider = BMTCTransitDataProvider(
            endpoint="https://authorized.bmtc.gov.in/api/realtime",
            api_key="bmtc-test-authorized-key",
            poll_interval=10.0,
            stale_threshold=30.0,
        )

    def _sample_valid_payload(self):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        return {
            "header": {
                "gtfs_realtime_version": "2.0",
                "timestamp": now_ts,
            },
            "entity": [
                {
                    "id": "entity-500d-1",
                    "vehicle": {
                        "trip": {
                            "trip_id": "trip-500d-eb-01",
                            "route_id": "500D",
                        },
                        "position": {
                            "latitude": 12.9176,
                            "longitude": 77.6238,
                            "bearing": 92.0,
                            "speed": 28.5,
                        },
                        "timestamp": now_ts,
                        "vehicle": {
                            "id": "KA-01-FA-5001",
                            "label": "500D-AC-01",
                        },
                    },
                },
                {
                    "id": "entity-356-1",
                    "vehicle": {
                        "trip": {
                            "trip_id": "trip-356-nb-01",
                            "route_id": "356",
                        },
                        "position": {
                            "latitude": 12.8452,
                            "longitude": 77.6602,
                            "bearing": 340.0,
                            "speed": 34.0,
                        },
                        "timestamp": now_ts,
                        "vehicle": {
                            "id": "KA-57-F-3561",
                            "label": "356-ORD-01",
                        },
                    },
                },
            ],
        }

    def test_valid_feed_ingestion(self):
        """1. Valid GTFS-RT payload ingests successfully and populates vehicles."""
        payload = self._sample_valid_payload()
        count = self.provider.ingest_payload(payload)
        self.assertEqual(count, 2)
        self.assertTrue(self.provider.has_live_data)
        self.assertEqual(self.provider.feed_status, "connected")

    def test_malformed_feed_rejection(self):
        """2. Malformed feed payload is rejected gracefully without crashing."""
        malformed_payload = "NOT_A_VALID_GTFS_OBJECT"
        count = self.provider.ingest_payload(malformed_payload)
        self.assertEqual(count, 0)
        self.assertEqual(self.provider._consecutive_failures, 1)

    def test_empty_feed_rejection(self):
        """3. Empty payload or 0 entities payload is safely rejected."""
        empty_payload = {"header": {"gtfs_realtime_version": "2.0"}, "entity": []}
        count = self.provider.ingest_payload(empty_payload)
        self.assertEqual(count, 0)
        self.assertEqual(self.provider._consecutive_failures, 1)

    def test_invalid_coordinates_out_of_bounds(self):
        """4. Geographic bounding box validates that out-of-Bengaluru coordinates are rejected."""
        now_ts = int(datetime.now(timezone.utc).timestamp())
        out_of_bounds_payload = {
            "entity": [
                {
                    "id": "entity-ny-1",
                    "vehicle": {
                        "trip": {"route_id": "500D"},
                        "position": {
                            "latitude": 40.7128,  # New York coordinates
                            "longitude": -74.0060,
                        },
                        "timestamp": now_ts,
                    },
                }
            ]
        }
        count = self.provider.ingest_payload(out_of_bounds_payload)
        self.assertEqual(count, 0)

    def test_duplicate_vehicles_deduplication(self):
        """5. Duplicate vehicle entities with same ID are deduplicated retaining latest timestamp."""
        now_ts = int(datetime.now(timezone.utc).timestamp())
        payload = {
            "entity": [
                {
                    "id": "entity-1",
                    "vehicle": {
                        "trip": {"route_id": "500D"},
                        "position": {"latitude": 12.9176, "longitude": 77.6238},
                        "timestamp": now_ts - 60,
                        "vehicle": {"id": "BUS-DUP-01"},
                    },
                },
                {
                    "id": "entity-2",
                    "vehicle": {
                        "trip": {"route_id": "500D"},
                        "position": {"latitude": 12.9200, "longitude": 77.6250},
                        "timestamp": now_ts,  # Newer timestamp
                        "vehicle": {"id": "BUS-DUP-01"},
                    },
                },
            ]
        }
        count = self.provider.ingest_payload(payload)
        self.assertEqual(count, 1)  # Deduplicated to 1 vehicle

    def test_stale_feed_state_transition(self):
        """6. When elapsed time exceeds stale threshold, feed_status transitions to stale."""
        self.provider.ingest_payload(self._sample_valid_payload())
        # Simulate last updated 45 seconds ago (stale_threshold is 30s)
        self.provider._last_updated_at = datetime.now(timezone.utc) - timedelta(seconds=45)
        self.assertTrue(self.provider.is_stale)
        self.assertEqual(self.provider.feed_status, "stale")

    def test_failed_feed_backoff_progression(self):
        """7. Consecutive failures safely scale backoff: 5s, 10s, 20s, 40s, 60s max."""
        self.provider._consecutive_failures = 1
        self.assertEqual(self.provider.calculate_backoff_delay(), 5.0)

        self.provider._consecutive_failures = 2
        self.assertEqual(self.provider.calculate_backoff_delay(), 10.0)

        self.provider._consecutive_failures = 3
        self.assertEqual(self.provider.calculate_backoff_delay(), 20.0)

        self.provider._consecutive_failures = 4
        self.assertEqual(self.provider.calculate_backoff_delay(), 40.0)

        self.provider._consecutive_failures = 5
        self.assertEqual(self.provider.calculate_backoff_delay(), 60.0)

        # Capped at 60s maximum
        self.provider._consecutive_failures = 10
        self.assertEqual(self.provider.calculate_backoff_delay(), 60.0)

    def test_last_known_good_retention(self):
        """8. When subsequent feed update fails, existing buses are retained (not wiped)."""
        # Step A: Ingest valid payload
        self.provider.ingest_payload(self._sample_valid_payload())
        self.assertEqual(len(self.provider._buses), 2)

        # Step B: Ingest broken payload
        self.provider.ingest_payload("MALFORMED_DATA")

        # Existing buses MUST remain in memory (last-known-good retained)
        self.assertEqual(len(self.provider._buses), 2)

    def test_recovery_from_failure(self):
        """9. Valid payload resets failure counters and restores feed status to healthy."""
        self.provider._consecutive_failures = 4
        self.provider.ingest_payload(self._sample_valid_payload())
        self.assertEqual(self.provider._consecutive_failures, 0)
        self.assertEqual(self.provider.feed_status, "connected")

    def test_trip_update_eta_attribution(self):
        """10. GTFS-RT TripUpdate provides official ETA with attribution source 'gtfs_rt_trip_update'."""
        import asyncio
        self.provider.ingest_payload(self._sample_valid_payload())

        now_epoch = int(datetime.now(timezone.utc).timestamp())
        trip_updates_payload = {
            "entity": [
                {
                    "id": "tu-1",
                    "trip_update": {
                        "trip": {"trip_id": "trip-500d-eb-01", "route_id": "500D"},
                        "vehicle": {"id": "KA-01-FA-5001"},
                        "stop_time_update": [
                            {
                                "stop_name": "Central Silk Board Junction",
                                "arrival": {"time": now_epoch + 480},  # 8 minutes
                            }
                        ],
                    },
                }
            ]
        }
        self.provider.ingest_payload(self._sample_valid_payload(), trip_updates_data=trip_updates_payload)

        bus_id = list(self.provider._buses.keys())[0]
        eta_obj = asyncio.run(self.provider.get_eta(bus_id, target_stop_name="Central Silk Board Junction"))
        self.assertIsNotNone(eta_obj)
        self.assertEqual(eta_obj.source, "gtfs_rt_trip_update")
        self.assertGreaterEqual(eta_obj.eta_minutes, 1)

    def test_geometric_eta_fallback(self):
        """11. When TripUpdate is absent, geometric calculation is used with source 'geometric_estimate'."""
        import asyncio
        self.provider.ingest_payload(self._sample_valid_payload())
        bus_id = list(self.provider._buses.keys())[0]
        eta_obj = asyncio.run(self.provider.get_eta(bus_id, target_stop_name="Unknown Target Stop"))
        self.assertIsNotNone(eta_obj)
        self.assertEqual(eta_obj.source, "geometric_estimate")

    def test_occupancy_absence_honesty(self):
        """12. When APC data is absent in real feed, occupancy returns None (no fake seat guessing)."""
        import asyncio
        self.provider.ingest_payload(self._sample_valid_payload())
        bus_id = list(self.provider._buses.keys())[0]
        occ = asyncio.run(self.provider.get_bus_occupancy(bus_id))
        self.assertIsNone(occ)

    def test_provider_switching_fallback(self):
        """13. When TRANSIT_PROVIDER is unconfigured or unavailable, fallback is MockTransitDataProvider."""
        unconfigured_provider = BMTCTransitDataProvider(endpoint="", api_key="")
        self.assertFalse(unconfigured_provider.is_configured)
        self.assertEqual(unconfigured_provider.feed_status, "unconfigured")
        # Global resolution fallback check
        resolved = get_transit_provider()
        self.assertIsInstance(resolved, MockTransitDataProvider)

    def test_independent_feed_health_components(self):
        """14. FeedHealth diagnostic independently reports VehiclePositions, TripUpdates, and ServiceAlerts."""
        self.provider.ingest_payload(self._sample_valid_payload())
        health = self.provider.get_feed_health()
        self.assertIsNotNone(health.vehicle_positions_feed)
        self.assertIsNotNone(health.trip_updates_feed)
        self.assertIsNotNone(health.service_alerts_feed)
        self.assertTrue(health.vehicle_positions_feed.valid)
        self.assertEqual(health.vehicle_positions_feed.entity_count, 2)


if __name__ == "__main__":
    unittest.main()
