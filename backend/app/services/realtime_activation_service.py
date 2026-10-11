"""
Realtime Activation Verification Service for NammaBlr.

Follows strict safety and ethical standards:
- Zero scraping of Namma BMTC or private endpoints.
- Zero credential leakage in logs or responses.
- Safe 8-stage verification pipeline:
  CONFIGURATION -> ENDPOINT VALIDATION -> CREDENTIAL VALIDATION -> FEED CONNECTION ->
  PAYLOAD VALIDATION -> GTFS-RT ENTITY VALIDATION -> DATA FRESHNESS -> REALTIME ACTIVATION
- Dry-run validation mode (evaluates feed without permanent state mutation).
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import httpx

from ..core.config import (
    settings,
    OPERATIONAL_STATEMENT_NOT_CONNECTED,
    OPERATIONAL_STATEMENT_CONNECTED,
)
from ..models.transit import (
    RealtimeValidationRequest,
    RealtimeValidationResponse,
    RealtimeActivationDiagnostics,
)
from .gtfs.parser import GTFSParser
from .provider_factory import get_transit_provider, get_provider_health

logger = logging.getLogger("nammablr.realtime_activation")


class RealtimeActivationService:
    """Dedicated verification service for BMTC / GTFS-RT feed activation and dry-run auditing."""

    @staticmethod
    def _sanitize_url(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        # Remove any embedded user:password credentials from URL
        try:
            parts = url.split("://", 1)
            if len(parts) == 2 and "@" in parts[1]:
                scheme = parts[0]
                host_path = parts[1].split("@", 1)[1]
                return f"{scheme}://{host_path}"
            return url
        except Exception:
            return url

    @staticmethod
    def _is_valid_url_scheme(url: Optional[str]) -> bool:
        if not url:
            return False
        clean = url.strip().lower()
        if not (clean.startswith("http://") or clean.startswith("https://")):
            return False
        rest = clean.split("://", 1)[1]
        return len(rest.strip()) > 0

    async def validate_feed(
        self, request: Optional[RealtimeValidationRequest] = None
    ) -> RealtimeValidationResponse:
        """
        Executes safe dry-run validation against configured or proposed realtime endpoints.
        Evaluates connectivity, schema validity, entity isolation, and freshness
        WITHOUT permanently mutating active transit provider state.
        Never exposes API keys or secrets.
        """
        errors: List[str] = []

        # Determine target parameters (override with request if specified)
        target_endpoint = (request.endpoint if request and request.endpoint is not None else settings.bmtc_api_endpoint)
        target_api_key = (request.api_key if request and request.api_key is not None else settings.bmtc_api_key)
        target_vp_url = (request.vehicle_positions_url if request and request.vehicle_positions_url is not None else settings.gtfs_rt_vehicle_positions_url)
        target_tu_url = (request.trip_updates_url if request and request.trip_updates_url is not None else settings.gtfs_rt_trip_updates_url)
        target_sa_url = (request.service_alerts_url if request and request.service_alerts_url is not None else settings.gtfs_rt_service_alerts_url)
        timeout_seconds = (request.timeout_seconds if request and request.timeout_seconds else settings.bmtc_api_timeout_seconds)

        # Build sanitized configuration representation (NEVER include raw secret key)
        endpoint_config = {
            "endpoint": self._sanitize_url(target_endpoint),
            "vehicle_positions_url": self._sanitize_url(target_vp_url),
            "trip_updates_url": self._sanitize_url(target_tu_url),
            "service_alerts_url": self._sanitize_url(target_sa_url),
            "has_credentials": bool(target_api_key),
            "timeout_seconds": timeout_seconds,
        }

        # Stage 1: Configuration Check
        if not target_endpoint and not target_vp_url and not target_tu_url and not target_sa_url:
            errors.append("No realtime feed endpoints are configured.")
            return RealtimeValidationResponse(
                success=False,
                endpoint_configuration=endpoint_config,
                connectivity=False,
                response_validity=False,
                entity_count=0,
                valid_entities=0,
                invalid_entities=0,
                ignored_entities=0,
                timestamp_freshness_seconds=None,
                vehicle_positions_status="unconfigured",
                trip_updates_status="unconfigured",
                service_alerts_status="unconfigured",
                occupancy_availability=False,
                operational_statement=OPERATIONAL_STATEMENT_NOT_CONNECTED,
                validation_errors=errors,
            )

        # Stage 2: Endpoint Scheme Validation
        endpoints_to_check = [
            ("BMTC Endpoint", target_endpoint),
            ("VehiclePositions URL", target_vp_url),
            ("TripUpdates URL", target_tu_url),
            ("ServiceAlerts URL", target_sa_url),
        ]
        for name, url in endpoints_to_check:
            if url and not self._is_valid_url_scheme(url):
                errors.append(f"{name} uses an invalid URL scheme (must be http:// or https://)")

        if errors:
            return RealtimeValidationResponse(
                success=False,
                endpoint_configuration=endpoint_config,
                connectivity=False,
                response_validity=False,
                entity_count=0,
                valid_entities=0,
                invalid_entities=0,
                ignored_entities=0,
                timestamp_freshness_seconds=None,
                vehicle_positions_status="invalid_configuration",
                trip_updates_status="invalid_configuration",
                service_alerts_status="invalid_configuration",
                occupancy_availability=False,
                operational_statement=OPERATIONAL_STATEMENT_NOT_CONNECTED,
                validation_errors=errors,
            )

        # Stage 3: Credential Validation
        if not target_api_key:
            errors.append("Authorized credentials missing: API key is required to access official feed.")

        # Stage 4: Feed Connection & Testing
        primary_url = target_vp_url or target_endpoint
        headers = {}
        if target_api_key:
            headers["Authorization"] = f"Bearer {target_api_key}"
            headers["x-api-key"] = target_api_key

        connectivity = False
        response_validity = False
        entity_count = 0
        valid_entities = 0
        invalid_entities = 0
        ignored_entities = 0
        freshness_sec: Optional[float] = None
        occupancy_avail = False

        vp_status = "unconfigured"
        tu_status = "unconfigured"
        sa_status = "unconfigured"

        if primary_url:
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
                    resp = await client.get(primary_url, headers=headers)
                    connectivity = True
                    if resp.status_code == 200:
                        try:
                            payload = resp.json()
                            response_validity = True

                            # Stage 5 & 6: Payload & Entity Validation
                            vehicles, stats = GTFSParser.parse_vehicle_positions_with_stats(payload)
                            valid_entities += stats["valid_entities"]
                            invalid_entities += stats["invalid_entities"]
                            ignored_entities += stats["ignored_entities"]
                            entity_count += len(vehicles)

                            if stats["invalid_entities"] > 0:
                                errors.extend(stats["validation_details"])

                            vp_status = "active" if len(vehicles) > 0 else "empty"

                            # Stage 7: Freshness Check
                            now = datetime.now(timezone.utc).timestamp()
                            timestamps = [v.timestamp for v in vehicles if v.timestamp]
                            if timestamps:
                                max_ts = max(timestamps)
                                freshness_sec = max(0.0, now - max_ts)

                            # Stage 8: Occupancy availability
                            occupancy_avail = any(v.occupancy_status is not None for v in vehicles)

                        except Exception as parse_err:
                            errors.append(f"Payload validation failed: {str(parse_err)}")
                            response_validity = False
                            vp_status = "invalid_payload"
                    else:
                        errors.append(f"Feed responded with HTTP status {resp.status_code}")
                        vp_status = f"http_{resp.status_code}"
            except httpx.ConnectError:
                errors.append("Network connection failed: unable to connect to feed host.")
                vp_status = "unreachable"
            except httpx.TimeoutException:
                errors.append("Connection timed out waiting for feed response.")
                vp_status = "timeout"
            except Exception as e:
                errors.append(f"Feed check error: {str(e)}")
                vp_status = "error"

        # Check TripUpdates URL if separate
        if target_tu_url and target_tu_url != primary_url:
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
                    tu_resp = await client.get(target_tu_url, headers=headers)
                    if tu_resp.status_code == 200:
                        tu_data = tu_resp.json()
                        updates, tu_stats = GTFSParser.parse_trip_updates_with_stats(tu_data)
                        valid_entities += tu_stats["valid_entities"]
                        invalid_entities += tu_stats["invalid_entities"]
                        ignored_entities += tu_stats["ignored_entities"]
                        tu_status = "active" if len(updates) > 0 else "empty"
                    else:
                        tu_status = f"http_{tu_resp.status_code}"
            except Exception:
                tu_status = "unreachable"

        # Check ServiceAlerts URL if separate
        if target_sa_url and target_sa_url != primary_url:
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
                    sa_resp = await client.get(target_sa_url, headers=headers)
                    if sa_resp.status_code == 200:
                        sa_data = sa_resp.json()
                        alerts, sa_stats = GTFSParser.parse_service_alerts_with_stats(sa_data)
                        valid_entities += sa_stats["valid_entities"]
                        invalid_entities += sa_stats["invalid_entities"]
                        ignored_entities += sa_stats["ignored_entities"]
                        sa_status = "active" if len(alerts) > 0 else "empty"
                    else:
                        sa_status = f"http_{sa_resp.status_code}"
            except Exception:
                sa_status = "unreachable"

        is_success = connectivity and response_validity and (valid_entities > 0) and len(errors) == 0

        op_statement = (
            OPERATIONAL_STATEMENT_CONNECTED if is_success else OPERATIONAL_STATEMENT_NOT_CONNECTED
        )

        return RealtimeValidationResponse(
            success=is_success,
            endpoint_configuration=endpoint_config,
            connectivity=connectivity,
            response_validity=response_validity,
            entity_count=entity_count,
            valid_entities=valid_entities,
            invalid_entities=invalid_entities,
            ignored_entities=ignored_entities,
            timestamp_freshness_seconds=freshness_sec,
            vehicle_positions_status=vp_status,
            trip_updates_status=tu_status,
            service_alerts_status=sa_status,
            occupancy_availability=occupancy_avail,
            operational_statement=op_statement,
            validation_errors=errors,
        )

    def get_activation_diagnostics(self) -> RealtimeActivationDiagnostics:
        """
        Determines current realtime activation state.
        Reports structured pipeline state and preserves transparency.
        """
        health = get_provider_health()

        is_bmtc = health.provider == "bmtc"
        is_realtime = health.data_mode == "realtime"
        is_healthy = health.feed_status == "healthy" or health.feed_status == "connected"

        # Check configuration validity without exposing credentials
        bmtc_configured = bool(settings.bmtc_api_endpoint and settings.bmtc_api_key)
        config_valid = bmtc_configured and settings.is_bmtc_endpoint_valid

        reason = (
            "Authorized realtime BMTC feed connected"
            if (is_realtime and is_healthy)
            else (
                "Realtime feed configured but currently unavailable"
                if (bmtc_configured and not is_healthy)
                else "Authorized realtime BMTC feed not configured"
            )
        )

        vp_count = health.feed_health.vehicle_positions if health.feed_health else 0
        tu_count = health.feed_health.trip_updates if health.feed_health else 0
        sa_count = health.feed_health.service_alerts if health.feed_health else 0
        valid_cnt = health.feed_health.valid_entities if health.feed_health else 0
        invalid_cnt = health.feed_health.invalid_entities if health.feed_health else 0
        ignored_cnt = health.feed_health.ignored_entities if health.feed_health else 0

        return RealtimeActivationDiagnostics(
            configured=bmtc_configured,
            configuration_valid=config_valid,
            feed_reachable=health.feed_status in ("healthy", "connected", "delayed"),
            feed_valid=is_realtime,
            activated=is_realtime,
            provider="bmtc" if is_bmtc else "mock",
            reason=reason,
            entity_count=vp_count,
            valid_entities=valid_cnt,
            invalid_entities=invalid_cnt,
            ignored_entities=ignored_cnt,
            occupancy_available=False,  # Truthful APC rule: no APC data in unverified feed
            timestamp_freshness_seconds=None,
            vehicle_positions_status="active" if vp_count > 0 else "unconfigured",
            trip_updates_status="active" if tu_count > 0 else "unconfigured",
            service_alerts_status="active" if sa_count > 0 else "unconfigured",
            validation_errors=[],
        )


realtime_activation_service = RealtimeActivationService()
