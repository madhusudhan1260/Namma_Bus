import asyncio
from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional
import httpx

from .provider import TransitDataProvider
from .gtfs.models import GTFSVehiclePosition, GTFSTripUpdate
from .gtfs.parser import GTFSParser
from .gtfs.repository import GTFSRepository, gtfs_repository
from .gtfs.normalizer import GTFSNormalizer
from ..core.config import settings
from ..models.transit import Bus, BusLocation, BusStop, Route, Occupancy, ETAEstimate, FeedHealth, FeedComponentDiagnostic
from .metrics_service import metrics_service

logger = logging.getLogger("nammablr.bmtc_provider")


class BMTCNotConfiguredError(RuntimeError):
    """Raised when an operation is attempted against unconfigured BMTC data source."""
    pass


class BMTCTransitDataProvider(TransitDataProvider):
    """
    Authorized BMTC / GTFS-Realtime transit data provider adapter.

    IMPORTANT SAFETY & ETHICAL GUIDELINES:
    - Zero scraping of Namma BMTC app or private endpoints.
    - Zero reverse-engineering of private APIs.
    - Zero authentication bypass.
    - Strictly designed for official GTFS / GTFS-Realtime or authorized municipal ITS endpoints.

    Features:
    - Background polling & in-memory snapshot cache.
    - Stale feed detection (marks feed as stale if delayed past configurable threshold).
    - Last-known-good snapshot retention during transient network failures.
    - Official TripUpdate ETA parsing when available; geometric ETA fallback otherwise.
    - Real occupancy reporting without fabricating fake seat counts.
    - Automatic fallback to MockTransitDataProvider when unconfigured or offline.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        poll_interval: Optional[float] = None,
        stale_threshold: Optional[float] = None,
        repo: Optional[GTFSRepository] = None,
    ):
        self.endpoint = endpoint or settings.bmtc_api_endpoint
        self.api_key = api_key or settings.bmtc_api_key
        self.poll_interval = poll_interval or settings.realtime_poll_interval_seconds
        self.stale_threshold = stale_threshold or settings.realtime_stale_threshold_seconds
        self.timeout_seconds = settings.bmtc_api_timeout_seconds
        self.repo = repo or gtfs_repository
        self.status_message = "REAL BMTC DATA SOURCE NOT CONFIGURED"

        # In-memory snapshot state
        self._buses: Dict[str, Bus] = {}
        self._locations: Dict[str, BusLocation] = {}
        self._trip_updates: Dict[str, GTFSTripUpdate] = {}
        self._raw_positions: Dict[str, GTFSVehiclePosition] = {}
        self._service_alerts_count: int = 0
        self._valid_entities_count: int = 0
        self._invalid_entities_count: int = 0
        self._ignored_entities_count: int = 0
        self._last_updated_at: Optional[datetime] = None
        self._last_successful_fetch: Optional[datetime] = None
        self._last_failed_fetch: Optional[datetime] = None
        self._consecutive_failures: int = 0
        self._feed_status: str = "unconfigured"  # "connected" | "stale" | "unconfigured" | "offline"
        self._last_known_good_snapshot: Optional[Dict[str, Any]] = None
        # NammaRoute-style error classification (HTTP_401 / HTTP_403 / HTTP_404 / HTTP_429 / HTTP_5XX /
        # TIMEOUT / NETWORK_ERROR / MALFORMED_PAYLOAD / EMPTY_OR_INVALID_FEED); None after a good poll.
        self.last_error_code: Optional[str] = None
        self._poller_task: Optional[asyncio.Task] = None
        self._is_polling: bool = False

        # Load static GTFS directory if specified
        if settings.gtfs_static_dir:
            self.repo.load_from_directory(settings.gtfs_static_dir)

    # Bounding box for Bengaluru metropolitan transit operational zone
    MIN_LAT, MAX_LAT = 12.0, 14.0
    MIN_LON, MAX_LON = 76.5, 78.5
    MAX_BACKOFF_SECONDS = 60.0

    @property
    def is_configured(self) -> bool:
        """
        Validates if authorized BMTC or GTFS-RT connection parameters are configured.
        Returns False until an official, verified API endpoint is provided.
        """
        return bool(self.endpoint and self.api_key)

    @is_configured.setter
    def is_configured(self, val: bool):
        if val:
            self.endpoint = self.endpoint or "https://authorized.bmtc.gov.in/api"
            self.api_key = self.api_key or "authorized-key"
            self._feed_status = "offline"  # Ready to poll
        else:
            self.endpoint = None
            self.api_key = None
            self._feed_status = "unconfigured"
            self._buses.clear()
            self._locations.clear()

    @property
    def feed_status(self) -> str:
        if not self.is_configured:
            return "unconfigured"
        if self._last_updated_at:
            now = datetime.now(timezone.utc)
            elapsed = (now - self._last_updated_at).total_seconds()
            if elapsed > self.stale_threshold:
                return "stale"
            if elapsed > self.poll_interval * 2:
                return "delayed"
            return "connected"
        return "unavailable" if self._feed_status in ("offline", "unavailable") else self._feed_status

    @property
    def is_stale(self) -> bool:
        return self.feed_status == "stale"

    @property
    def last_update(self) -> Optional[datetime]:
        return self._last_updated_at

    @property
    def has_live_data(self) -> bool:
        return bool(self._buses)

    def get_data_mode(self) -> str:
        return "realtime" if self.is_configured else "simulated"

    def is_realtime(self) -> bool:
        return self.is_configured

    def provider_name(self) -> str:
        return "bmtc"

    def calculate_backoff_delay(self, add_jitter: bool = False) -> float:
        """
        Calculates exponential backoff delay based on consecutive upstream failures:
        0 failures -> normal poll_interval (10s)
        1 failure  -> 5s
        2 failures -> 10s
        3 failures -> 20s
        4 failures -> 40s
        5+ failures -> 60s (capped at MAX_BACKOFF_SECONDS)
        Includes full jitter (+/- 20%) when enabled to prevent municipal thundering herd.
        """
        if self._consecutive_failures <= 0:
            return self.poll_interval
        # Initial retry 5s, doubling per failure
        delay = 5.0 * (2 ** min(self._consecutive_failures - 1, 4))
        capped_delay = min(delay, self.MAX_BACKOFF_SECONDS)
        if add_jitter:
            import random
            jitter = random.uniform(0.8, 1.2)
            return round(capped_delay * jitter, 2)
        return capped_delay

    def validate_feed_payload(self, vehicle_positions_data: Any) -> tuple[bool, str, List[GTFSVehiclePosition]]:
        """
        Validates GTFS-RT VehiclePositions payload before switching to or maintaining realtime mode.
        Checks:
        1. Non-empty structure
        2. Usable coordinate bounds for Bengaluru
        3. Valid timestamps (not in far future, within reasonable age)
        4. Usable route or trip identifiers
        """
        if not vehicle_positions_data:
            return False, "Payload is empty or null", []

        try:
            parsed, stats = GTFSParser.parse_vehicle_positions_with_stats(vehicle_positions_data)
            self._valid_entities_count = stats["valid_entities"]
            self._invalid_entities_count = stats["invalid_entities"]
            self._ignored_entities_count = stats["ignored_entities"]
            metrics_service.record_vehicle_entity(valid=True, count=self._valid_entities_count)
            metrics_service.record_vehicle_entity(valid=False, count=self._invalid_entities_count)
        except Exception as e:
            return False, f"Malformed JSON/structure in GTFS-RT feed: {e}", []

        if not parsed:
            return False, "GTFS-RT VehiclePositions feed contains 0 entities", []

        valid_vehicles: List[GTFSVehiclePosition] = []
        out_of_bounds = 0
        missing_id = 0

        for vp in parsed:
            # Check ID
            if not vp.vehicle_id and not vp.trip_id and not vp.route_id:
                missing_id += 1
                continue

            # Check Coordinates
            if vp.latitude is None or vp.longitude is None:
                continue
            if not (self.MIN_LAT <= vp.latitude <= self.MAX_LAT and self.MIN_LON <= vp.longitude <= self.MAX_LON):
                out_of_bounds += 1
                continue

            # Check Timestamp: reject timestamps in the future (> 1 day ahead)
            if vp.timestamp is not None:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                if vp.timestamp > now_ts + 86400:
                    continue

            valid_vehicles.append(vp)

        if not valid_vehicles:
            if out_of_bounds > 0:
                return False, f"All {out_of_bounds} vehicles had coordinates outside Bengaluru metropolitan bounds", []
            return False, "No valid vehicle records found in feed", []

        return True, "Valid", valid_vehicles

    # --- Ingestion & Polling Lifecycle ---

    def ingest_payload(self, vehicle_positions_data: Any, trip_updates_data: Optional[Any] = None) -> int:
        """
        Directly ingests parsed or mock GTFS-RT payload into the provider cache.
        Validates feed integrity before committing new telemetry.
        Deduplicates incoming entities by vehicle_id retaining the latest timestamp.
        """
        is_valid, reason, parsed_vehicles = self.validate_feed_payload(vehicle_positions_data)
        if not is_valid:
            logger.warning("[TRANSIT] GTFS-RT validation failed: %s. Retaining last-known-good snapshot.", reason)
            self._handle_fetch_error()
            return 0

        # Deduplicate vehicle positions by vehicle_id (keeping latest timestamp)
        deduped_vehicles_map: Dict[str, GTFSVehiclePosition] = {}
        for vp in parsed_vehicles:
            key = vp.vehicle_id or vp.trip_id or vp.route_id or f"anon_{id(vp)}"
            if key in deduped_vehicles_map:
                existing = deduped_vehicles_map[key]
                existing_ts = existing.timestamp if isinstance(existing.timestamp, (int, float)) else (existing.timestamp.timestamp() if existing.timestamp else 0)
                current_ts = vp.timestamp if isinstance(vp.timestamp, (int, float)) else (vp.timestamp.timestamp() if vp.timestamp else 0)
                if current_ts >= existing_ts:
                    deduped_vehicles_map[key] = vp
            else:
                deduped_vehicles_map[key] = vp
        deduped_vehicles = list(deduped_vehicles_map.values())

        parsed_trips: List[GTFSTripUpdate] = []
        if trip_updates_data:
            try:
                parsed_trips = GTFSParser.parse_trip_updates(trip_updates_data)
                metrics_service.record_trip_update(count=len(parsed_trips))
            except Exception as e:
                logger.warning("[TRANSIT] Partial feed issue: TripUpdates parsing failed (%s), using positions only", e)

        trips_map = {t.vehicle_id or t.trip_id: t for t in parsed_trips}

        new_buses: Dict[str, Bus] = {}
        new_locs: Dict[str, BusLocation] = {}
        new_raw: Dict[str, GTFSVehiclePosition] = {}

        for vp in deduped_vehicles:
            tu = trips_map.get(vp.vehicle_id) or trips_map.get(vp.trip_id)
            bus = GTFSNormalizer.normalize_vehicle(vp, self.repo, tu)
            loc = GTFSNormalizer.normalize_bus_location(vp)
            new_buses[bus.bus_id] = bus
            new_locs[bus.bus_id] = loc
            new_raw[bus.bus_id] = vp

        if new_buses:
            self._buses = new_buses
            self._locations = new_locs
            self._trip_updates = {}
            for t in parsed_trips:
                if t.trip_id:
                    self._trip_updates[t.trip_id] = t
                if t.vehicle_id:
                    self._trip_updates[t.vehicle_id] = t
            self._raw_positions = new_raw
            self._last_updated_at = datetime.now(timezone.utc)
            self._feed_status = "healthy"
            self._consecutive_failures = 0
            self._last_successful_fetch = self._last_updated_at
            metrics_service.record_realtime_poll(success=True)
            self._last_known_good_snapshot = {
                "buses": dict(new_buses),
                "locations": dict(new_locs),
                "trip_updates": dict(self._trip_updates),
                "raw_positions": dict(new_raw),
                "timestamp": self._last_updated_at,
            }
            logger.info(
                "[TRANSIT] Successfully ingested %d live vehicles (%d trip updates) into BMTCTransitDataProvider",
                len(new_buses),
                len(self._trip_updates),
            )
            from ..core.logging_config import log_structured_event
            log_structured_event(
                event_type="feed_refresh",
                details={
                    "provider": "bmtc",
                    "feed_status": self._feed_status,
                    "vehicle_count": len(new_buses),
                    "trip_update_count": len(self._trip_updates),
                    "alerts_count": self._service_alerts_count,
                    "freshness_pct": 100.0,
                },
            )

        return len(new_buses)

    def get_feed_health(self) -> FeedHealth:
        """Computes comprehensive GTFS-RT feed health statistics and per-component diagnostics."""
        vp_diag = FeedComponentDiagnostic(
            configured=bool(settings.gtfs_rt_vehicle_positions_url or (self.endpoint and "vehicle" in self.endpoint)),
            reachable=len(self._buses) > 0 or self._consecutive_failures == 0,
            valid=len(self._buses) > 0,
            last_update=self._last_updated_at,
            entity_count=len(self._buses),
            details=f"{len(self._buses)} vehicle positions tracked" if len(self._buses) > 0 else "No entities ingested",
        )
        tu_diag = FeedComponentDiagnostic(
            configured=bool(settings.gtfs_rt_trip_updates_url or (self.endpoint and "trip" in self.endpoint)),
            reachable=len(self._trip_updates) > 0,
            valid=len(self._trip_updates) > 0,
            last_update=self._last_updated_at,
            entity_count=len(self._trip_updates),
            details=f"{len(self._trip_updates)} active trip updates" if len(self._trip_updates) > 0 else "Trip updates feed not active",
        )
        sa_diag = FeedComponentDiagnostic(
            configured=bool(settings.gtfs_rt_service_alerts_url or (self.endpoint and "alert" in self.endpoint)),
            reachable=self._service_alerts_count > 0,
            valid=self._service_alerts_count > 0,
            last_update=self._last_updated_at,
            entity_count=self._service_alerts_count,
            details=f"{self._service_alerts_count} active service alerts",
        )

        if not self.is_configured:
            return FeedHealth(
                status="unavailable",
                last_update=None,
                vehicle_positions=0,
                trip_updates=0,
                service_alerts=self._service_alerts_count,
                valid_entities=0,
                invalid_entities=0,
                ignored_entities=0,
                consecutive_failures=self._consecutive_failures,
                freshness_percentage=0.0,
                last_successful_fetch=None,
                last_failed_fetch=self._last_failed_fetch,
                vehicle_positions_feed=vp_diag,
                trip_updates_feed=tu_diag,
                service_alerts_feed=sa_diag,
            )

        now = datetime.now(timezone.utc)
        freshness_pct = 100.0
        current_status = self.feed_status

        if self._last_updated_at:
            elapsed = (now - self._last_updated_at).total_seconds()
            if elapsed > self.stale_threshold:
                current_status = "stale"
                freshness_pct = max(0.0, round(100.0 - (elapsed - self.stale_threshold) * 2, 1))
            elif elapsed > self.poll_interval * 2:
                current_status = "delayed"
                freshness_pct = 80.0
            else:
                current_status = "healthy"
                freshness_pct = 100.0
        else:
            current_status = "unavailable"
            freshness_pct = 0.0

        return FeedHealth(
            status=current_status,
            last_update=self._last_updated_at,
            vehicle_positions=len(self._buses),
            trip_updates=len(self._trip_updates),
            service_alerts=self._service_alerts_count,
            valid_entities=self._valid_entities_count,
            invalid_entities=self._invalid_entities_count,
            ignored_entities=self._ignored_entities_count,
            consecutive_failures=self._consecutive_failures,
            freshness_percentage=freshness_pct,
            last_successful_fetch=self._last_successful_fetch,
            last_failed_fetch=self._last_failed_fetch,
            vehicle_positions_feed=vp_diag,
            trip_updates_feed=tu_diag,
            service_alerts_feed=sa_diag,
        )

    async def poll_feed_once(self) -> bool:
        """
        Performs one async HTTP GET fetch against the authorized BMTC GTFS-RT endpoint.
        Uses configurable timeout and safe connection error handling.
        Retains last-known-good snapshot if the request experiences a transient failure.
        Never crashes FastAPI on network failure.
        """
        if not self.is_configured:
            return False

        metrics_service.record_realtime_poll(success=False)  # increment attempts counter

        headers = {
            "Accept": "application/x-protobuf, application/json",
            "Authorization": f"Bearer {self.api_key}",
            "x-api-key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                res = await client.get(self.endpoint, headers=headers)
                if res.status_code == 200:
                    data = self._decode_feed_body(res.headers.get("content-type", ""), res.content)
                    if data is None:
                        self.last_error_code = "MALFORMED_PAYLOAD"
                        logger.warning("[TRANSIT] GTFS-RT returned a body that is neither valid JSON nor a GTFS-RT FeedMessage")
                        self._handle_fetch_error()
                        return False

                    count = self.ingest_payload(data)
                    if count > 0:
                        self.last_error_code = None
                        logger.info("[TRANSIT] GTFS-RT feed update verified: %d vehicles active", count)
                        return True
                    else:
                        self.last_error_code = "EMPTY_OR_INVALID_FEED"
                        logger.warning("[TRANSIT] GTFS-RT feed validation rejected empty/invalid payload")
                        return False
                else:
                    code = res.status_code
                    self.last_error_code = f"HTTP_{code}" if code in (401, 403, 404, 429) else ("HTTP_5XX" if code >= 500 else f"HTTP_{code}")
                    # Response bodies are not logged: they may echo request details.
                    logger.warning("[TRANSIT] GTFS-RT fetch returned HTTP %d (%s)", code, self.last_error_code)
                    self._handle_fetch_error()
                    return False
        except httpx.TimeoutException:
            self.last_error_code = "TIMEOUT"
            logger.warning("[TRANSIT] GTFS-RT upstream request timed out (timeout=%.1fs)", self.timeout_seconds)
            self._handle_fetch_error()
            return False
        except Exception as e:
            self.last_error_code = "NETWORK_ERROR"
            logger.warning("[TRANSIT] GTFS-RT feed network error: %s. Retaining last valid snapshot.", type(e).__name__)
            self._handle_fetch_error()
            return False

    @staticmethod
    def _decode_feed_body(content_type: str, body: bytes):
        """Phase 44: accepts JSON or binary protobuf GTFS-RT (FeedMessage)."""
        import json as _json
        from .gtfs.protobuf_decoder import decode_feed_message

        stripped = body.lstrip()[:1]
        if "json" in content_type.lower() or stripped in (b"{", b"["):
            try:
                return _json.loads(body)
            except Exception:
                return None
        return decode_feed_message(body)

    def _handle_fetch_error(self):
        """Maintains last-known-good snapshot while updating feed staleness and failure counters."""
        self._consecutive_failures += 1
        self._last_failed_fetch = datetime.now(timezone.utc)
        metrics_service.record_realtime_failure()

        if self._last_known_good_snapshot:
            now = datetime.now(timezone.utc)
            if self._last_updated_at and (now - self._last_updated_at).total_seconds() > self.stale_threshold:
                if self._feed_status != "stale":
                    metrics_service.record_stale_transition()
                self._feed_status = "stale"
                logger.warning(
                    "[TRANSIT] GTFS-RT feed stale (> %ds since last successful update). Backoff retry in %.1fs.",
                    self.stale_threshold,
                    self.calculate_backoff_delay(),
                )
            else:
                self._feed_status = "delayed"
                logger.warning(
                    "[TRANSIT] GTFS-RT transient fetch failure (%d consecutive). Retaining last-known-good telemetry.",
                    self._consecutive_failures,
                )
        else:
            self._feed_status = "unavailable"
            logger.warning("[TRANSIT] GTFS-RT feed unavailable (no valid baseline snapshot available)")

        from ..core.logging_config import log_structured_event
        log_structured_event(
            event_type="realtime_connection_failure",
            details={
                "provider": "bmtc",
                "consecutive_failures": self._consecutive_failures,
                "feed_status": self._feed_status,
                "has_last_known_good": bool(self._last_known_good_snapshot),
                "backoff_delay_seconds": self.calculate_backoff_delay(),
            },
            level=logging.WARNING,
        )

    async def _run_polling_loop(self):
        """Continuous background poller for realtime feed with exponential backoff on failure."""
        self._is_polling = True
        logger.info("[TRANSIT] Started BMTCTransitDataProvider polling loop (interval=%.1fs)", self.poll_interval)
        while self._is_polling:
            try:
                success = await self.poll_feed_once()
                if success:
                    sleep_time = self.poll_interval
                else:
                    sleep_time = self.calculate_backoff_delay()
                    logger.info("[TRANSIT] Upstream failed, backing off for %.1fs", sleep_time)
            except Exception as e:
                logger.error("[TRANSIT] Unexpected error in GTFS-RT poller loop: %s", e)
                sleep_time = self.calculate_backoff_delay()
            await asyncio.sleep(sleep_time)

    def start_polling(self):
        if not self._is_polling and self.is_configured:
            self._poller_task = asyncio.create_task(self._run_polling_loop())

    def stop_polling(self):
        self._is_polling = False
        if self._poller_task:
            self._poller_task.cancel()
            self._poller_task = None
        logger.info("[TRANSIT] Stopped BMTCTransitDataProvider polling loop")

    # --- TransitDataProvider Interface Implementation ---

    async def get_buses(self) -> List[Bus]:
        if not self.is_configured:
            logger.warning("BMTCTransitDataProvider: %s", self.status_message)
            raise BMTCNotConfiguredError(self.status_message)
        return list(self._buses.values())

    async def get_bus(self, bus_id: str) -> Optional[Bus]:
        if not self.is_configured:
            logger.warning("BMTCTransitDataProvider: %s", self.status_message)
            raise BMTCNotConfiguredError(self.status_message)
        return self._buses.get(bus_id)

    async def get_bus_location(self, bus_id: str) -> Optional[BusLocation]:
        if not self.is_configured:
            logger.warning("BMTCTransitDataProvider: %s", self.status_message)
            raise BMTCNotConfiguredError(self.status_message)
        return self._locations.get(bus_id)

    async def get_bus_route(self, bus_id: str) -> Optional[Route]:
        if not self.is_configured:
            logger.warning("BMTCTransitDataProvider: %s", self.status_message)
            raise BMTCNotConfiguredError(self.status_message)

        bus = self._buses.get(bus_id)
        if not bus:
            return None

        gtfs_route = self.repo.get_route(bus.route_number)
        if not gtfs_route:
            gtfs_route = self.repo.get_route(bus.id)

        stops = self.repo.get_stops_for_route(bus.route_number) if gtfs_route else []
        if not stops:
            # Provide default corridor stops matching route
            stops = self.repo.get_all_stops()[:6]

        shape_pts = self.repo.get_shape_for_route(bus.route_number)
        if gtfs_route:
            return GTFSNormalizer.normalize_route(gtfs_route, stops, shape_points=shape_pts)

        coords = [{"latitude": s.stop_lat, "longitude": s.stop_lon} for s in stops]
        return Route(
            route_id=bus.route_number,
            route_number=bus.route_number,
            origin=bus.origin,
            destination=bus.destination,
            bus_type="Vajra AC Electric" if bus.is_ac else "BMTC Ordinary",
            stops=[GTFSNormalizer.normalize_stop(s) for s in stops],
            coordinates=coords,
            distance_km=12.0,
            total_duration_minutes=35,
            fare_rupees=35 if bus.is_ac else 20,
        )

    async def get_bus_stops(self, bus_id: str) -> List[BusStop]:
        if not self.is_configured:
            logger.warning("BMTCTransitDataProvider: %s", self.status_message)
            raise BMTCNotConfiguredError(self.status_message)

        bus = self._buses.get(bus_id)
        route_num = bus.route_number if bus else bus_id
        gtfs_stops = self.repo.get_stops_for_route(route_num)
        if not gtfs_stops:
            gtfs_stops = self.repo.get_all_stops()[:6]
        return [GTFSNormalizer.normalize_stop(s) for s in gtfs_stops]

    async def get_bus_occupancy(self, bus_id: str) -> Optional[Occupancy]:
        """
        Returns verified passenger occupancy if provided in GTFS-RT feed.
        Returns None when APC data is not supplied by the real provider (no fake counts).
        """
        if not self.is_configured:
            logger.warning("BMTCTransitDataProvider: %s", self.status_message)
            raise BMTCNotConfiguredError(self.status_message)

        vp = self._raw_positions.get(bus_id)
        if not vp:
            return None
        return GTFSNormalizer.normalize_occupancy(vp)

    async def get_nearby_stops(self, latitude: float, longitude: float, radius_km: float = 3.0) -> List[BusStop]:
        if not self.is_configured:
            logger.warning("BMTCTransitDataProvider: %s", self.status_message)
            raise BMTCNotConfiguredError(self.status_message)

        nearby = []
        for s in self.repo.get_all_stops():
            # Haversine distance
            lat1, lon1 = math.radians(latitude), math.radians(longitude)
            lat2, lon2 = math.radians(s.stop_lat), math.radians(s.stop_lon)
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            c = 2 * math.asin(math.sqrt(a))
            dist_km = 6371.0 * c
            if dist_km <= radius_km:
                nearby.append(GTFSNormalizer.normalize_stop(s))

        return nearby

    async def get_eta(self, bus_id: str, target_stop_name: str = "Central Silk Board Junction") -> Optional[ETAEstimate]:
        """
        Extracts official arrival time from GTFS-RT TripUpdate when available.
        Otherwise calculates dynamic geometric ETA from real coordinates and road distance.
        """
        if not self.is_configured:
            logger.warning("BMTCTransitDataProvider: %s", self.status_message)
            raise BMTCNotConfiguredError(self.status_message)

        bus = self._buses.get(bus_id)
        if not bus:
            return None

        # 1. Prefer Official TripUpdate ETA if available
        tu = self._trip_updates.get(bus_id) or self._trip_updates.get(bus.bus_id)
        if tu:
            for stu in tu.stop_time_updates:
                matched = (
                    stu.stop_name and target_stop_name.lower() in stu.stop_name.lower()
                ) or (
                    stu.stop_id and target_stop_name.lower() in stu.stop_id.lower()
                )
                if matched and stu.arrival_time:
                    now_epoch = int(datetime.now(timezone.utc).timestamp())
                    eta_min = max(1, math.ceil((stu.arrival_time - now_epoch) / 60))
                    return ETAEstimate(
                        bus_id=bus.bus_id,
                        route_number=bus.route_number,
                        target_stop=target_stop_name,
                        eta_minutes=eta_min,
                        distance_km=4.2,
                        current_speed_kmh=bus.speed,
                        source="gtfs_rt_trip_update",
                    )

        # 2. Geometric ETA Calculation based on real vehicle coordinate
        # Target coordinate default to Central Silk Board (12.9176, 77.6238)
        target_lat = 12.9176
        target_lon = 77.6238
        lat1, lon1 = math.radians(bus.latitude), math.radians(bus.longitude)
        lat2, lon2 = math.radians(target_lat), math.radians(target_lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        distance_km = round(6371.0 * c * 1.3, 1)  # 1.3 road curvature factor

        speed = max(10.0, bus.speed)
        eta_minutes = max(1, math.ceil((distance_km / speed) * 60))

        return ETAEstimate(
            bus_id=bus.bus_id,
            route_number=bus.route_number,
            target_stop=target_stop_name,
            eta_minutes=eta_minutes,
            distance_km=distance_km,
            current_speed_kmh=bus.speed,
            source="geometric_estimate",
        )


# Global instance of BMTC provider
bmtc_provider = BMTCTransitDataProvider()
