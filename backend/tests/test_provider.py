import asyncio
import os
import unittest
from unittest.mock import patch

from app.models.transit import HealthResponse, ETAEstimate
from app.services.provider_factory import get_transit_provider, get_provider_health, is_simulation_active
from app.services.mock_provider import mock_provider, MockTransitDataProvider
from app.services.bmtc_provider import bmtc_provider, BMTCTransitDataProvider, BMTCNotConfiguredError
from app.core.config import settings


class TestProviderArchitecture(unittest.TestCase):
    """
    Test suite for TransitDataProvider abstraction, provider resolution,
    unconfigured BMTC safety guards, automatic fallback to simulator,
    and data mode reporting.
    """

    def test_1_mock_provider_implements_interface(self):
        """Verify MockTransitDataProvider satisfies all provider interface methods."""
        p = MockTransitDataProvider()
        self.assertEqual(p.get_data_mode(), "simulated")
        self.assertFalse(p.is_realtime())
        self.assertEqual(p.provider_name(), "mock")

        buses = asyncio.run(p.get_buses())
        self.assertGreater(len(buses), 0)

        bus = asyncio.run(p.get_bus("bus-500d-1"))
        self.assertIsNotNone(bus)
        self.assertEqual(bus.route_number, "500D")

        loc = asyncio.run(p.get_bus_location("bus-500d-1"))
        self.assertIsNotNone(loc)
        self.assertEqual(loc.heading, loc.direction)
        self.assertIsNotNone(loc.timestamp)

        route = asyncio.run(p.get_bus_route("bus-500d-1"))
        self.assertIsNotNone(route)

        stops = asyncio.run(p.get_bus_stops("bus-500d-1"))
        self.assertGreater(len(stops), 0)

        occ = asyncio.run(p.get_bus_occupancy("bus-500d-1"))
        self.assertIsNotNone(occ)
        self.assertEqual(occ.passengers, occ.current_passengers)
        self.assertEqual(occ.crowd_level, occ.occupancy_level)

        nearby = asyncio.run(p.get_nearby_stops(12.9176, 77.6238, radius_km=5.0))
        self.assertGreater(len(nearby), 0)

    def test_2_mock_provider_get_eta(self):
        """Verify get_eta computes dynamic estimate to target stop."""
        p = MockTransitDataProvider()
        eta_res = asyncio.run(p.get_eta("bus-500d-1", "Central Silk Board Junction"))
        self.assertIsNotNone(eta_res)
        self.assertIsInstance(eta_res, ETAEstimate)
        self.assertEqual(eta_res.bus_id, "bus-500d-1")
        self.assertEqual(eta_res.route_number, "500D")
        self.assertGreater(eta_res.eta_minutes, 0)
        self.assertGreater(eta_res.distance_km, 0)

        unknown_eta = asyncio.run(p.get_eta("bus-unknown-999"))
        self.assertIsNone(unknown_eta)

    def test_3_default_provider_selection_is_mock(self):
        """Default configuration must select MockTransitDataProvider."""
        with patch.object(settings, "transit_provider", "mock"):
            active = get_transit_provider()
            self.assertIsInstance(active, MockTransitDataProvider)
            self.assertTrue(is_simulation_active())

    def test_4_bmtc_provider_unconfigured_safety(self):
        """BMTCTransitDataProvider safely raises BMTCNotConfiguredError when credentials are not configured."""
        unconfigured_bmtc = BMTCTransitDataProvider(endpoint=None, api_key=None)
        self.assertFalse(unconfigured_bmtc.is_configured)
        self.assertFalse(unconfigured_bmtc.is_realtime())
        self.assertEqual(unconfigured_bmtc.get_data_mode(), "simulated")
        self.assertEqual(unconfigured_bmtc.provider_name(), "bmtc")

        with self.assertRaises(BMTCNotConfiguredError) as ctx:
            asyncio.run(unconfigured_bmtc.get_buses())
        self.assertIn("REAL BMTC DATA SOURCE NOT CONFIGURED", str(ctx.exception))

        with self.assertRaises(BMTCNotConfiguredError):
            asyncio.run(unconfigured_bmtc.get_bus("bus-500d-1"))

        with self.assertRaises(BMTCNotConfiguredError):
            asyncio.run(unconfigured_bmtc.get_eta("bus-500d-1"))

    def test_5_automatic_fallback_when_bmtc_unconfigured(self):
        """
        When TRANSIT_PROVIDER='bmtc' but no valid credentials exist,
        provider_factory must log a warning and automatically fall back to mock_provider.
        """
        with patch.object(settings, "transit_provider", "bmtc"):
            with patch.object(bmtc_provider, "endpoint", None), patch.object(bmtc_provider, "api_key", None):
                with self.assertLogs("nammamove.provider_factory", level="WARNING") as log:
                    active = get_transit_provider()
                    self.assertIsInstance(active, MockTransitDataProvider)
                    self.assertIn("Automatically falling back to MockTransitDataProvider", log.output[0])

    def test_6_health_reporting_simulated_mode(self):
        """Health check returns accurate data_mode and provider status in simulated mode."""
        with patch.object(settings, "transit_provider", "mock"):
            health = get_provider_health()
            self.assertIsInstance(health, HealthResponse)
            self.assertEqual(health.status, "healthy")
            self.assertEqual(health.provider, "mock")
            self.assertEqual(health.data_mode, "simulated")
            self.assertFalse(health.realtime)
            self.assertTrue(health.configured)

    def test_7_health_reporting_fallback_mode(self):
        """Health check reflects unconfigured BMTC status and active fallback."""
        with patch.object(settings, "transit_provider", "bmtc"):
            with patch.object(bmtc_provider, "endpoint", None), patch.object(bmtc_provider, "api_key", None):
                health = get_provider_health()
                self.assertEqual(health.provider, "mock")
                self.assertEqual(health.data_mode, "simulated")
                self.assertFalse(health.realtime)
                self.assertFalse(health.configured)
                self.assertIn("Automatic fallback", health.details)

    def test_8_health_reporting_authorized_realtime_mode(self):
        """Health check reflects realtime mode when an authorized feed is attached."""
        with patch.object(settings, "transit_provider", "bmtc"):
            with patch.object(bmtc_provider, "endpoint", "https://authorized.bmtc.gov.in/api"), patch.object(bmtc_provider, "api_key", "secret-token"):
                health = get_provider_health()
                self.assertEqual(health.provider, "bmtc")
                self.assertEqual(health.data_mode, "realtime")
                self.assertTrue(health.realtime)
                self.assertTrue(health.configured)


if __name__ == "__main__":
    unittest.main()
