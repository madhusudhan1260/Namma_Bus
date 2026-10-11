import os
import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

logger = logging.getLogger("nammablr.config")

OPERATIONAL_STATEMENT_NOT_CONNECTED = "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED"
OPERATIONAL_STATEMENT_CONNECTED = "REALTIME BMTC FEED: AUTHORIZED CONNECTION ACTIVE"


class Settings(BaseModel):
    app_name: str = "NammaBlr - BMTC Transit Backend"
    api_prefix: str = "/api"
    version: str = "1.0.0"
    cors_origins: list[str] = Field(default_factory=lambda: [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")
        if origin.strip()
    ])
    simulation_tick_seconds: float = 3.0
    transit_provider: str = Field(default_factory=lambda: os.getenv("TRANSIT_PROVIDER", "mock").lower())
    # BMTC_API_BASE_URL is the Phase 41 name for the same setting; BMTC_API_ENDPOINT takes precedence.
    bmtc_api_endpoint: Optional[str] = Field(default_factory=lambda: os.getenv("BMTC_API_ENDPOINT") or os.getenv("BMTC_API_BASE_URL") or None)
    bmtc_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("BMTC_API_KEY", None))
    real_transit_enabled: bool = Field(default_factory=lambda: os.getenv("REAL_TRANSIT_ENABLED", "false").lower() in ("true", "1"))
    realtime_poll_interval_seconds: float = Field(default_factory=lambda: float(os.getenv("REALTIME_POLL_INTERVAL_SECONDS", "10.0")))
    realtime_stale_threshold_seconds: float = Field(default_factory=lambda: float(os.getenv("REALTIME_STALE_THRESHOLD_SECONDS", "60.0")))
    gtfs_static_dir: Optional[str] = Field(default_factory=lambda: os.getenv("GTFS_STATIC_DIR", None))
    gtfs_rt_vehicle_positions_url: Optional[str] = Field(default_factory=lambda: os.getenv("GTFS_RT_VEHICLE_POSITIONS_URL", None))
    gtfs_rt_trip_updates_url: Optional[str] = Field(default_factory=lambda: os.getenv("GTFS_RT_TRIP_UPDATES_URL", None))
    gtfs_rt_service_alerts_url: Optional[str] = Field(default_factory=lambda: os.getenv("GTFS_RT_SERVICE_ALERTS_URL", None))
    bmtc_api_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("BMTC_API_TIMEOUT_SECONDS", os.getenv("BMTC_API_TIMEOUT", "10.0"))))
    max_request_body_bytes: int = Field(default_factory=lambda: int(os.getenv("MAX_REQUEST_BODY_BYTES", "1048576")))  # 1MB
    rate_limit_per_minute: int = Field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "120")))  # per client IP
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development").lower())
    google_maps_api_key_android: Optional[str] = Field(default_factory=lambda: os.getenv("GOOGLE_MAPS_API_KEY_ANDROID", None))
    google_maps_api_key_ios: Optional[str] = Field(default_factory=lambda: os.getenv("GOOGLE_MAPS_API_KEY_IOS", None))
    # Phase 48: security configuration (secrets only via environment variables)
    ticket_hmac_secret_set: bool = Field(default_factory=lambda: bool(os.getenv("TICKET_HMAC_SECRET")))
    conductor_access_key: Optional[str] = Field(default_factory=lambda: os.getenv("CONDUCTOR_ACCESS_KEY") or None)
    auth_identifier_hash_secret_set: bool = Field(default_factory=lambda: bool(os.getenv("AUTH_IDENTIFIER_HASH_SECRET")))

    @staticmethod
    def _is_valid_url(url: Optional[str]) -> bool:
        """Validates that a URL uses an allowed HTTP/HTTPS URL scheme and has a valid target."""
        if not url:
            return False
        ep = url.lower().strip()
        if not (ep.startswith("http://") or ep.startswith("https://")):
            return False
        # Disallow schemes with empty host (e.g. "http://")
        rest = ep.split("://", 1)[1].strip()
        return len(rest) > 0

    @property
    def is_bmtc_endpoint_valid(self) -> bool:
        """Validates that BMTC_API_ENDPOINT uses an allowed HTTP/HTTPS URL scheme."""
        return self._is_valid_url(self.bmtc_api_endpoint)

    @property
    def effective_cors_origins(self) -> list[str]:
        """
        Returns explicit allowed origins.
        In production, if cors_origins is set to ['*'], it defaults to secure domain patterns
        or explicit origins to disallow wildcards.
        """
        if self.environment == "production" and "*" in self.cors_origins:
            return [
                "https://nammablr.transit.gov.in",
                "https://app.nammablr.in",
            ]
        return self.cors_origins

    def validate_production_config(self) -> Dict[str, Any]:
        """
        Validates configuration without printing or exposing sensitive credentials.
        Returns validation status, active mode, and diagnostic warnings/errors.
        Rejects unsafe production settings such as wildcard CORS, invalid URL schemes,
        and missing required realtime parameters.
        """
        warnings: List[str] = []
        errors: List[str] = []

        is_production = self.environment == "production"

        # 1. CORS Validation
        if "*" in self.cors_origins:
            if is_production:
                errors.append("Wildcard CORS origin '*' is strictly prohibited in production.")
                warnings.append("CORS wildcard '*' is forbidden in production. Defaulted to secure origins.")
            else:
                warnings.append("CORS wildcard '*' active in development.")

        # 2. Rate Limiting & Body Limits
        if self.rate_limit_per_minute <= 0:
            errors.append("RATE_LIMIT_PER_MINUTE must be a positive integer.")
        if self.max_request_body_bytes <= 0:
            errors.append("MAX_REQUEST_BODY_BYTES must be a positive integer.")
        elif is_production and self.max_request_body_bytes > 5 * 1024 * 1024:
            warnings.append("MAX_REQUEST_BODY_BYTES exceeds 5MB recommendation.")

        # 3. Timeouts & Intervals
        if self.bmtc_api_timeout_seconds <= 0:
            errors.append("BMTC_API_TIMEOUT_SECONDS must be positive.")
        if self.realtime_poll_interval_seconds <= 0:
            errors.append("REALTIME_POLL_INTERVAL_SECONDS must be positive.")
        if self.realtime_stale_threshold_seconds <= 0:
            errors.append("REALTIME_STALE_THRESHOLD_SECONDS must be positive.")
        elif self.realtime_stale_threshold_seconds <= self.realtime_poll_interval_seconds:
            warnings.append("REALTIME_STALE_THRESHOLD_SECONDS should be greater than REALTIME_POLL_INTERVAL_SECONDS.")

        # 4. URL Validation for Endpoints
        if self.bmtc_api_endpoint and not self.is_bmtc_endpoint_valid:
            errors.append("Invalid URL scheme for BMTC_API_ENDPOINT: must use http:// or https://")

        if self.gtfs_rt_vehicle_positions_url and not self._is_valid_url(self.gtfs_rt_vehicle_positions_url):
            errors.append("Invalid URL scheme for GTFS_RT_VEHICLE_POSITIONS_URL: must use http:// or https://")

        if self.gtfs_rt_trip_updates_url and not self._is_valid_url(self.gtfs_rt_trip_updates_url):
            errors.append("Invalid URL scheme for GTFS_RT_TRIP_UPDATES_URL: must use http:// or https://")

        if self.gtfs_rt_service_alerts_url and not self._is_valid_url(self.gtfs_rt_service_alerts_url):
            errors.append("Invalid URL scheme for GTFS_RT_SERVICE_ALERTS_URL: must use http:// or https://")

        # 5. Realtime Provider & Credentials Validation
        bmtc_configured = bool(self.bmtc_api_endpoint and self.bmtc_api_key)
        if self.transit_provider == "bmtc":
            if not bmtc_configured:
                if is_production:
                    errors.append(
                        "TRANSIT_PROVIDER is configured as 'bmtc' in production, but BMTC_API_ENDPOINT or BMTC_API_KEY is missing."
                    )
                else:
                    warnings.append(
                        "TRANSIT_PROVIDER is set to 'bmtc' but BMTC_API_ENDPOINT or BMTC_API_KEY is missing. "
                        "Falling back safely to MockTransitDataProvider."
                    )

        # 6. Phase 48: secrets and conductor authorization
        # Reported as warnings (not errors) so existing deployments keep validating; startup logs them.
        if not self.ticket_hmac_secret_set:
            warnings.append(
                "TICKET_HMAC_SECRET is not set; tickets are signed with the development-only key."
            )
        if not self.conductor_access_key:
            warnings.append(
                "CONDUCTOR_ACCESS_KEY is not set; conductor validation endpoints are not access-controlled."
            )
        if is_production and not self.auth_identifier_hash_secret_set:
            warnings.append("AUTH_IDENTIFIER_HASH_SECRET is not set; mobile lookup keys change on every restart.")

        active_provider_mode = "mock" if (self.transit_provider != "bmtc" or not bmtc_configured) else "bmtc"

        # Diagnostic state classification
        has_partial_bmtc = bool(self.bmtc_api_endpoint or self.bmtc_api_key)
        if not bmtc_configured and has_partial_bmtc:
            diagnostic_state = "bmtc_incomplete"
        elif self.transit_provider != "bmtc" and not bmtc_configured:
            diagnostic_state = "mock_mode"
        elif not bmtc_configured:
            diagnostic_state = "bmtc_incomplete"
        elif not self.is_bmtc_endpoint_valid:
            diagnostic_state = "bmtc_invalid_urls"
        elif len(errors) > 0:
            diagnostic_state = "bmtc_configuration_invalid"
        else:
            diagnostic_state = "bmtc_configured_valid"

        return {
            "valid": len(errors) == 0,
            "environment": self.environment,
            "transit_provider_configured": self.transit_provider,
            "active_mode": active_provider_mode,
            "diagnostic_state": diagnostic_state,
            "bmtc_configured": bmtc_configured,
            "operational_statement": OPERATIONAL_STATEMENT_NOT_CONNECTED,
            "validated_variables": {
                "environment": self.environment,
                "transit_provider": self.transit_provider,
                "cors_origins_count": len(self.cors_origins),
                "bmtc_api_endpoint_set": bool(self.bmtc_api_endpoint),
                "gtfs_rt_vehicle_positions_url_set": bool(self.gtfs_rt_vehicle_positions_url),
                "gtfs_rt_trip_updates_url_set": bool(self.gtfs_rt_trip_updates_url),
                "gtfs_rt_service_alerts_url_set": bool(self.gtfs_rt_service_alerts_url),
                "bmtc_api_timeout_seconds": self.bmtc_api_timeout_seconds,
                "realtime_poll_interval_seconds": self.realtime_poll_interval_seconds,
                "realtime_stale_threshold_seconds": self.realtime_stale_threshold_seconds,
                "rate_limit_per_minute": self.rate_limit_per_minute,
                "max_request_body_bytes": self.max_request_body_bytes,
                "google_maps_android_configured": bool(self.google_maps_api_key_android),
                "google_maps_ios_configured": bool(self.google_maps_api_key_ios),
                "ticket_hmac_secret_set": self.ticket_hmac_secret_set,
                "conductor_access_control": bool(self.conductor_access_key),
            },
            "warnings": warnings,
            "errors": errors,
        }


settings = Settings()
