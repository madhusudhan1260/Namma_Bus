"""
Realtime vehicle tracking — ported from NammaRoute (currentStopService / BmtcNormalizer / VehicleService)
and adapted to NammaBlr's provider architecture.

Pipeline (one provider read per cycle, shared by every caller):

    active provider (BMTCTransitDataProvider raw GTFS-RT positions | MockTransitDataProvider buses)
        → freshness (LIVE ≤ 60 s, RECENT ≤ 120 s, STALE ≤ 300 s, older dropped)
        → per-vehicle direction (route pattern per direction, heading + position scoring,
          stationary buses keep their previous direction)
        → current / next / following stop with GPS-jitter hysteresis
        → progress (completed / remaining stops)

Honesty rules (differences from NammaRoute):
- A vehicle without a timestamp is excluded and counted; NammaRoute substituted "now", which marked
  vehicles LIVE with unknown age.
- Speed and bearing stay None when the feed omits them.
- Source is VERIFIED_REALTIME only for vehicles from the authorized BMTC feed; simulator vehicles are
  SIMULATED. Nothing here creates vehicles.
"""

import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..core.config import OPERATIONAL_STATEMENT_NOT_CONNECTED, settings
from ..models.realtime import RealtimeStatusResponse, RealtimeVehiclesResponse, TrackedVehicle, VehicleStopInfo
from .bmtc_provider import bmtc_provider
from .gtfs.repository import gtfs_repository
from .mock_provider import mock_provider
from .provider_factory import get_transit_provider

LIVE_MAX_S = 60
RECENT_MAX_S = 120
STALE_MAX_S = 300
MATCH_RADIUS_M = 75
APPROACH_RADIUS_M = 250
HYSTERESIS_S = 30
SNAPSHOT_TTL_S = 2.0
STATE_TTL_S = 900

# Bengaluru service area (same bounds as NammaBlr's GTFS-RT validation)
MIN_LAT, MAX_LAT, MIN_LON, MAX_LON = 12.0, 14.0, 76.5, 78.5


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def freshness_state(age_seconds: float) -> Optional[str]:
    """LIVE / RECENT / STALE, or None when too old to show as a tracked vehicle."""
    if age_seconds <= LIVE_MAX_S:
        return "LIVE"
    if age_seconds <= RECENT_MAX_S:
        return "RECENT"
    if age_seconds <= STALE_MAX_S:
        return "STALE"
    return None


def parse_vehicle_timestamp(value) -> Optional[datetime]:
    """Epoch seconds/ms, ISO strings or datetimes. Naive datetimes are treated as UTC. None stays None."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            num = float(value)
            if num <= 0:
                return None
            return datetime.fromtimestamp(num / 1000 if num > 1e11 else num, tz=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


# ---------------------------------------------------------------------------
# Route patterns per direction
# ---------------------------------------------------------------------------

@dataclass
class OrderedStop:
    stop_id: str
    name: str
    sequence: int
    lat: float
    lon: float


@dataclass
class DirectionPattern:
    direction_id: int
    origin: str
    destination: str
    stops: List[OrderedStop]
    source: str  # GTFS_TRIPS | DEMO_CATALOG_DERIVED


def build_direction_patterns(route_key: str, repo=gtfs_repository) -> List[DirectionPattern]:
    """
    One ordered stop pattern per direction. From a real GTFS feed: the longest trip per direction_id.
    From the demo catalog (one stop list, no trips): the listed order plus its reverse, labelled
    DEMO_CATALOG_DERIVED so the inference is visible.
    """
    route = repo.get_route(route_key)
    route_id = route.route_id if route else route_key
    best: Dict[int, list] = {}
    for trip in repo.get_trips_for_route(route_id):
        times = repo.stop_times.get(trip.trip_id) or []
        d = int(trip.direction_id or 0)
        if len(times) > len(best.get(d, [])):
            best[d] = times

    patterns: List[DirectionPattern] = []
    for d, times in sorted(best.items()):
        stops = []
        for i, st in enumerate(sorted(times, key=lambda x: x.stop_sequence)):
            s = repo.get_stop(st.stop_id)
            if s:
                stops.append(OrderedStop(s.stop_id, s.stop_name, i + 1, s.stop_lat, s.stop_lon))
        if len(stops) >= 2:
            patterns.append(DirectionPattern(d, stops[0].name, stops[-1].name, stops, "GTFS_TRIPS"))
    if patterns:
        return patterns

    listed = [s for s in repo.get_stops_for_route(route_id)]
    if len(listed) < 2:
        return []
    fwd = [OrderedStop(s.stop_id, s.stop_name, i + 1, s.stop_lat, s.stop_lon) for i, s in enumerate(listed)]
    rev = [OrderedStop(s.stop_id, s.stop_name, i + 1, s.stop_lat, s.stop_lon) for i, s in enumerate(reversed(listed))]
    return [
        DirectionPattern(0, fwd[0].name, fwd[-1].name, fwd, "DEMO_CATALOG_DERIVED"),
        DirectionPattern(1, rev[0].name, rev[-1].name, rev, "DEMO_CATALOG_DERIVED"),
    ]


def _patterns_from_stop_list(stop_list, source: str) -> List[DirectionPattern]:
    """Forward and reverse patterns from one ordered (stop_id, name, lat, lon) list."""
    if len(stop_list) < 2:
        return []
    fwd = [OrderedStop(sid, name, i + 1, lat, lon) for i, (sid, name, lat, lon) in enumerate(stop_list)]
    rev = [OrderedStop(sid, name, i + 1, lat, lon) for i, (sid, name, lat, lon) in enumerate(reversed(stop_list))]
    return [
        DirectionPattern(0, fwd[0].name, fwd[-1].name, fwd, source),
        DirectionPattern(1, rev[0].name, rev[-1].name, rev, source),
    ]


def select_direction(lat: float, lon: float, bearing: Optional[float], speed: Optional[float],
                     patterns: List[DirectionPattern], previous_direction: Optional[int],
                     destination: Optional[str] = None) -> Optional[DirectionPattern]:
    """
    NammaRoute selectBestVariant: keep previous direction when stationary; else a destination reported by
    the source; else nearest stop + heading penalty.
    """
    if not patterns:
        return None
    if len(patterns) == 1:
        return patterns[0]
    stationary = (speed is None or speed <= 3) and (bearing is None or bearing == 0)
    if stationary and previous_direction is not None:
        prev = next((p for p in patterns if p.direction_id == previous_direction), None)
        if prev:
            return prev

    if destination:
        dest = destination.lower().split("(")[0].strip()
        for p in patterns:
            pd = p.destination.lower().split("(")[0].strip()
            if dest and pd and (dest in pd or pd in dest):
                return p

    best, best_score = patterns[0], math.inf
    for p in patterns:
        dists = [haversine_m(lat, lon, s.lat, s.lon) for s in p.stops]
        idx = min(range(len(dists)), key=dists.__getitem__)
        penalty = 0.0
        if bearing is not None and bearing > 0 and len(p.stops) > 1:
            a = p.stops[max(0, idx - 1)]
            b = p.stops[min(len(p.stops) - 1, idx + 1)]
            if angle_diff(bearing, bearing_deg(a.lat, a.lon, b.lat, b.lon)) > 90:
                penalty = 5000.0  # heading opposite to this direction
        score = dists[idx] + penalty
        if score < best_score:
            best, best_score = p, score
    return best


# ---------------------------------------------------------------------------
# Stop detection (NammaRoute detectStop with hysteresis)
# ---------------------------------------------------------------------------

@dataclass
class VehicleState:
    last_status: str = "UNKNOWN"
    last_at_stop_seq: Optional[int] = None
    last_at_stop_id: Optional[str] = None
    last_at_stop_ts: float = 0.0
    last_next_seq: Optional[int] = None
    last_direction: Optional[int] = None
    seen_at: float = field(default_factory=time.time)


def _info(s: OrderedStop, dist: float) -> VehicleStopInfo:
    return VehicleStopInfo(stop_id=s.stop_id, stop_name=s.name, sequence=s.sequence, distance_meters=int(round(dist)))


def detect_stop(lat: float, lon: float, bearing: Optional[float], speed: Optional[float],
                stops: List[OrderedStop], prev: Optional[VehicleState], now: float
                ) -> Tuple[str, Optional[OrderedStop], Optional[OrderedStop], Dict[str, float]]:
    """Returns (status, current_stop, next_stop, distances by stop_id) and never guesses without stops."""
    if not stops:
        return "UNKNOWN", None, None, {}
    dist = {s.stop_id: haversine_m(lat, lon, s.lat, s.lon) for s in stops}
    stationary = (speed is None or speed <= 3) and (bearing is None or bearing == 0)
    by_seq = sorted(stops, key=lambda s: s.sequence)

    def after(seq: int) -> Optional[OrderedStop]:
        return next((s for s in by_seq if s.sequence > seq), None)

    # 1. AT_STOP (with hysteresis against GPS jitter)
    at = [s for s in stops if dist[s.stop_id] <= MATCH_RADIUS_M]
    if not at and prev and prev.last_status == "AT_STOP":
        p = next((s for s in stops if s.stop_id == prev.last_at_stop_id), None)
        if p and not ((speed is not None and speed > 15) or dist[p.stop_id] > MATCH_RADIUS_M * 1.5
                      or now - prev.last_at_stop_ts > HYSTERESIS_S):
            at = [p]
    if at:
        if len(at) > 1 and prev and (prev.last_at_stop_seq is not None or prev.last_next_seq is not None):
            ref = prev.last_next_seq if prev.last_next_seq is not None else prev.last_at_stop_seq
            floor = prev.last_at_stop_seq or 0
            at.sort(key=lambda s: (s.sequence < floor, abs(s.sequence - ref), dist[s.stop_id]))
        elif len(at) > 1 and bearing is not None and bearing > 0:
            at.sort(key=lambda s: (angle_diff(bearing, bearing_deg(lat, lon, s.lat, s.lon)) > 90, dist[s.stop_id]))
        else:
            at.sort(key=lambda s: dist[s.stop_id])
        cur = at[0]
        return "AT_STOP", cur, after(cur.sequence), dist

    # 2. APPROACHING (heading towards a stop within the approach radius)
    near = sorted([s for s in stops if dist[s.stop_id] <= APPROACH_RADIUS_M], key=lambda s: dist[s.stop_id])
    if near and prev and prev.last_next_seq is not None and stationary:
        fwd = [s for s in near if s.sequence >= prev.last_next_seq]
        near = fwd or near
    if near:
        n = near[0]
        towards = True
        if bearing is not None and bearing > 0:
            towards = angle_diff(bearing, bearing_deg(lat, lon, n.lat, n.lon)) <= 90
        if towards:
            return "APPROACHING_STOP", None, n, dist
        upcoming = after(n.sequence)
        if upcoming:
            return "IN_TRANSIT", None, upcoming, dist

    # 3. IN_TRANSIT: nearest segment midpoint decides the next stop
    start = max(0, prev.last_next_seq - 2) if (stationary and prev and prev.last_next_seq) else 0
    best, best_d = None, math.inf
    for i in range(start, len(by_seq) - 1):
        a, b = by_seq[i], by_seq[i + 1]
        d = haversine_m(lat, lon, (a.lat + b.lat) / 2, (a.lon + b.lon) / 2)
        if d < best_d:
            best, best_d = b, d
    if best is None:
        best = min(stops, key=lambda s: dist[s.stop_id])
    return "IN_TRANSIT", None, best, dist


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def realtime_feed_state() -> Tuple[str, bool]:
    """(feed_state, realtime_connected) from the BMTC provider — independent of what vehicles show."""
    if settings.transit_provider.lower().strip() != "bmtc" or not bmtc_provider.is_configured:
        return "NOT_CONFIGURED", False
    if bmtc_provider.has_live_data:
        if bmtc_provider.is_stale:
            return "STALE", False
        if getattr(bmtc_provider, "_consecutive_failures", 0) > 0:
            return "OFFLINE", False
        return "CONNECTED", True
    return "UNAVAILABLE", False


class VehicleTrackingService:
    def __init__(self):
        self._states: Dict[str, VehicleState] = {}
        self._patterns: Dict[str, List[DirectionPattern]] = {}
        self._patterns_key: Optional[tuple] = None
        self._snapshot: Optional[Tuple[float, RealtimeVehiclesResponse]] = None
        self._lock = asyncio.Lock()
        self.provider_reads = 0

    def reset(self):
        self._states.clear()
        self._patterns.clear()
        self._patterns_key = None
        self._snapshot = None

    def _patterns_for(self, route_key: str) -> List[DirectionPattern]:
        key = (gtfs_repository.data_source, tuple(sorted(gtfs_repository.get_stats().items())))
        if key != self._patterns_key:
            self._patterns.clear()
            self._patterns_key = key
        if route_key not in self._patterns:
            self._patterns[route_key] = build_direction_patterns(route_key)
        return self._patterns[route_key]

    async def _raw_vehicles(self) -> Tuple[str, List[dict]]:
        """Reads the active provider once. Returns (source, raw vehicle dicts)."""
        self.provider_reads += 1
        provider = get_transit_provider()
        if provider is bmtc_provider:
            raw = []
            for vp in getattr(bmtc_provider, "_raw_positions", {}).values():
                raw.append({
                    "id": vp.vehicle_id, "route": vp.route_number or vp.route_id, "trip_id": vp.trip_id,
                    "lat": vp.latitude, "lon": vp.longitude, "bearing": vp.bearing,
                    "speed": vp.speed_kmh, "timestamp": vp.timestamp,
                })
            return "VERIFIED_REALTIME", raw
        buses = await mock_provider.get_buses()
        raw = []
        for b in buses:
            # Simulated buses follow the simulator's own corridor stops, so use those (not the catalog)
            stops = await mock_provider.get_bus_stops(b.bus_id)
            raw.append({"id": b.bus_id, "route": b.route_number, "trip_id": None, "lat": b.latitude, "lon": b.longitude,
                        "bearing": b.direction, "speed": b.speed, "timestamp": b.updated_at, "destination": b.destination,
                        "stops": [(s.stop_id, s.name, s.latitude, s.longitude) for s in stops]})
        return "SIMULATED", raw

    def track(self, raw: dict, source: str, now_ts: float, excluded: Dict[str, int]) -> Optional[TrackedVehicle]:
        vid = str(raw.get("id") or "").strip()
        if not vid:
            excluded["no_vehicle_id"] += 1
            return None
        try:
            lat, lon = float(raw["lat"]), float(raw["lon"])
        except (TypeError, ValueError, KeyError):
            excluded["invalid_coordinates"] += 1
            return None
        if not (MIN_LAT <= lat <= MAX_LAT and MIN_LON <= lon <= MAX_LON):
            excluded["out_of_bounds"] += 1
            return None
        ts = parse_vehicle_timestamp(raw.get("timestamp"))
        if ts is None:
            excluded["no_timestamp"] += 1
            return None
        age = max(0.0, now_ts - ts.timestamp())
        fresh = freshness_state(age)
        if fresh is None:
            excluded["too_old"] += 1
            return None

        bearing = raw.get("bearing")
        speed = raw.get("speed")
        bearing = float(bearing) if bearing is not None else None
        speed = float(speed) if speed is not None else None
        route = raw.get("route")
        v = TrackedVehicle(
            vehicle_id=vid, route_number=str(route) if route else None, trip_id=raw.get("trip_id"),
            latitude=round(lat, 6), longitude=round(lon, 6), bearing=bearing, speed_kmh=speed,
            timestamp=ts, freshness_seconds=int(age), freshness=fresh, source=source,
        )
        if not route:
            return v

        state = self._states.get(vid)
        patterns = _patterns_from_stop_list(raw["stops"], "SIMULATOR_ROUTE") if raw.get("stops") else self._patterns_for(str(route))
        pattern = select_direction(lat, lon, bearing, speed, patterns,
                                   state.last_direction if state else None, raw.get("destination"))
        if not pattern:
            return v
        status, cur, nxt, dist = detect_stop(lat, lon, bearing, speed, pattern.stops, state, now_ts)

        new_state = state or VehicleState()
        new_state.seen_at = now_ts
        new_state.last_direction = pattern.direction_id
        new_state.last_status = status
        new_state.last_next_seq = nxt.sequence if nxt else None
        if status == "AT_STOP" and cur:
            if new_state.last_at_stop_id != cur.stop_id or dist.get(cur.stop_id, 1e9) <= MATCH_RADIUS_M:
                new_state.last_at_stop_ts = now_ts
            new_state.last_at_stop_id, new_state.last_at_stop_seq = cur.stop_id, cur.sequence
        else:
            new_state.last_at_stop_id = new_state.last_at_stop_seq = None
        self._states[vid] = new_state

        total = len(pattern.stops)
        if cur:
            completed = cur.sequence - 1
            remaining = max(0, total - cur.sequence)
        elif nxt:
            completed = nxt.sequence - 1
            remaining = max(0, total - completed)
        else:
            completed, remaining = 0, total
        following = None
        if nxt:
            following = next((s for s in pattern.stops if s.sequence == nxt.sequence + 1), None)
        start_seq = (cur.sequence + 1) if cur else (nxt.sequence if nxt else total + 1)

        v.direction_id = pattern.direction_id
        v.direction_label = f"Towards {pattern.destination}"
        v.origin, v.destination = pattern.origin, pattern.destination
        v.route_pattern_source = pattern.source
        v.stop_status = status
        v.current_stop = _info(cur, dist[cur.stop_id]) if cur else None
        v.next_stop = _info(nxt, dist[nxt.stop_id]) if nxt else None
        v.following_stop = _info(following, dist[following.stop_id]) if following else None
        v.total_stops, v.completed_stops, v.remaining_stops = total, completed, remaining
        v.progress_percentage = min(100, max(0, round(completed / (total - 1) * 100))) if total > 1 else 100
        v.remaining_stop_names = [s.name for s in pattern.stops if s.sequence >= start_seq]
        return v

    async def snapshot(self, force: bool = False) -> RealtimeVehiclesResponse:
        now = time.time()
        if not force and self._snapshot and now - self._snapshot[0] < SNAPSHOT_TTL_S:
            return self._snapshot[1]
        async with self._lock:  # concurrent callers share one provider read
            now = time.time()
            if not force and self._snapshot and now - self._snapshot[0] < SNAPSHOT_TTL_S:
                return self._snapshot[1]
            source, raw = await self._raw_vehicles()
            excluded = {"no_vehicle_id": 0, "invalid_coordinates": 0, "out_of_bounds": 0, "no_timestamp": 0, "too_old": 0, "duplicate": 0}
            vehicles: Dict[str, TrackedVehicle] = {}
            for r in raw:
                tv = self.track(r, source, now, excluded)
                if tv is None:
                    continue
                if tv.vehicle_id in vehicles:
                    excluded["duplicate"] += 1
                    if tv.timestamp <= vehicles[tv.vehicle_id].timestamp:
                        continue
                vehicles[tv.vehicle_id] = tv
            for vid in [k for k, s in self._states.items() if now - s.seen_at > STATE_TTL_S]:
                del self._states[vid]

            state, connected = realtime_feed_state()
            items = list(vehicles.values())
            counts = {k: sum(1 for v in items if v.freshness == k) for k in ("LIVE", "RECENT", "STALE")}
            resp = RealtimeVehiclesResponse(
                feed_state=state,
                source=source,
                realtime_connected=connected,
                operational_statement=None if connected else OPERATIONAL_STATEMENT_NOT_CONNECTED,
                generated_at=datetime.now(timezone.utc),
                count=len(items),
                counts_by_freshness=counts,
                excluded=excluded,
                vehicles=items,
            )
            self._snapshot = (now, resp)
            return resp

    async def get_vehicle(self, vehicle_id: str) -> Optional[TrackedVehicle]:
        snap = await self.snapshot()
        return next((v for v in snap.vehicles if v.vehicle_id == vehicle_id), None)

    async def status(self) -> RealtimeStatusResponse:
        snap = await self.snapshot()
        return RealtimeStatusResponse(
            feed_state=snap.feed_state,
            source=snap.source,
            realtime_connected=snap.realtime_connected,
            configured=bool(bmtc_provider.is_configured),
            operational_statement=snap.operational_statement,
            last_successful_update=getattr(bmtc_provider, "_last_successful_fetch", None),
            consecutive_failures=getattr(bmtc_provider, "_consecutive_failures", 0),
            last_error_code=getattr(bmtc_provider, "last_error_code", None),
            vehicle_count=snap.count,
            counts_by_freshness=snap.counts_by_freshness,
            freshness_thresholds_seconds={"LIVE": LIVE_MAX_S, "RECENT": RECENT_MAX_S, "STALE": STALE_MAX_S},
            poll_interval_seconds=bmtc_provider.poll_interval,
        )


vehicle_tracking_service = VehicleTrackingService()
