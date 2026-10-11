import logging
from typing import Optional

from .provider import TransitDataProvider
from .mock_provider import mock_provider, MockTransitDataProvider
from .bmtc_provider import bmtc_provider, BMTCTransitDataProvider
from ..core.config import settings
from ..models.transit import HealthResponse

logger = logging.getLogger("nammamove.provider_factory")


def get_transit_provider() -> TransitDataProvider:
    """
    Resolves the active TransitDataProvider based on configuration and feed validity.
    
    Rules:
    - UNCONFIGURED: Mock provider (simulated)
    - CONFIGURED BUT FEED INVALID/UNREACHABLE with no cached data: Mock provider (simulated)
    - CONFIGURED + VALID FEED (or valid last-known-good snapshot): BMTC provider (realtime)
    """
    configured_provider = settings.transit_provider.lower().strip()

    if configured_provider == "bmtc":
        if not bmtc_provider.is_configured:
            logger.warning(
                "TRANSIT_PROVIDER is configured as 'bmtc', but REAL BMTC DATA SOURCE NOT CONFIGURED. "
                "Automatically falling back to MockTransitDataProvider."
            )
            return mock_provider

        # Configured, check if valid live data or last-known-good telemetry exists
        if bmtc_provider.has_live_data:
            return bmtc_provider
        else:
            logger.warning(
                "TRANSIT_PROVIDER is configured as 'bmtc', but no valid realtime telemetry is currently available (%s). "
                "Serving verified simulator fallback.",
                bmtc_provider.feed_status,
            )
            return mock_provider

    return mock_provider


def get_provider_health() -> HealthResponse:
    """
    Returns standardized health status and honest data mode reporting.
    Exposes data_mode, realtime, provider_name, feed_status, last_update, and freshness_percentage.
    """
    configured_provider = settings.transit_provider.lower().strip()

    if configured_provider == "bmtc":
        if bmtc_provider.is_configured:
            feed_hlth = bmtc_provider.get_feed_health()
            f_status = bmtc_provider.feed_status

            if bmtc_provider.has_live_data:
                is_stale = bmtc_provider.is_stale
                if is_stale:
                    details = "Authorized BMTC feed delayed (stale telemetry threshold exceeded)."
                    status_label = "degraded"
                elif f_status == "delayed":
                    details = "BMTC telemetry is delayed."
                    status_label = "healthy"
                else:
                    details = "Connected to authorized BMTC realtime transit source."
                    status_label = "healthy"

                return HealthResponse(
                    status=status_label,
                    provider="bmtc",
                    provider_name="BMTCTransitDataProvider",
                    data_mode="realtime",
                    realtime=True,
                    configured=True,
                    details=details,
                    feed_status=f_status,
                    stale=is_stale,
                    last_update=bmtc_provider.last_update,
                    feed_health=feed_hlth,
                )
            else:
                # Configured, but feed is awaiting first snapshot or temporarily unavailable
                return HealthResponse(
                    status="degraded",
                    provider="bmtc",
                    provider_name="BMTCTransitDataProvider",
                    data_mode="simulated",
                    realtime=False,
                    configured=True,
                    details="Authorized BMTC feed configured but no valid realtime data received yet. Serving simulated corridor data.",
                    feed_status=f_status if f_status != "unconfigured" else "unavailable",
                    stale=False,
                    last_update=None,
                    feed_health=feed_hlth,
                )
        else:
            # Unconfigured
            return HealthResponse(
                status="healthy",
                provider="mock",
                provider_name="MockTransitDataProvider",
                data_mode="simulated",
                realtime=False,
                configured=False,
                details="TRANSIT_PROVIDER='bmtc' requested, but REAL BMTC DATA SOURCE NOT CONFIGURED. Automatic fallback to Mock provider active.",
                feed_status="unconfigured",
                stale=False,
                last_update=None,
                feed_health=bmtc_provider.get_feed_health(),
            )

    feed_hlth = bmtc_provider.get_feed_health()
    return HealthResponse(
        status="healthy",
        provider="mock",
        provider_name="MockTransitDataProvider",
        data_mode="simulated",
        realtime=False,
        configured=True,
        details="Bengaluru corridor telemetry simulation active.",
        feed_status="connected",
        stale=False,
        last_update=None,
        feed_health=feed_hlth,
    )


def is_simulation_active() -> bool:
    """
    Returns True if the active provider relies on simulated coordinate advancement.
    """
    active = get_transit_provider()
    return isinstance(active, MockTransitDataProvider)


def get_provider_info() -> dict:
    """Returns concise provider status metadata for diagnostics and logging."""
    hlth = get_provider_health()
    return {
        "data_mode": hlth.data_mode,
        "realtime": hlth.realtime,
        "provider_name": hlth.provider_name,
        "feed_status": hlth.feed_status,
        "last_update": hlth.last_update,
        "freshness_percentage": hlth.feed_health.freshness_percentage if hlth.feed_health else 100.0,
    }
