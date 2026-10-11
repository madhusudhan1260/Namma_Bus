"""
Realtime vehicle tracking models (NammaRoute integration).

Every tracked vehicle carries its data source. Values the source does not provide stay None /
UNKNOWN — speed, bearing and stop positions are never invented.
"""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

VehicleFreshness = Literal["LIVE", "RECENT", "STALE"]
VehicleSource = Literal["VERIFIED_REALTIME", "SIMULATED"]
StopStatus = Literal["AT_STOP", "APPROACHING_STOP", "IN_TRANSIT", "UNKNOWN"]
FeedState = Literal["CONNECTED", "STALE", "OFFLINE", "UNAVAILABLE", "NOT_CONFIGURED"]


class VehicleStopInfo(BaseModel):
    stop_id: str
    stop_name: str
    sequence: int
    distance_meters: int


class TrackedVehicle(BaseModel):
    vehicle_id: str
    route_number: Optional[str] = None
    trip_id: Optional[str] = None
    latitude: float
    longitude: float
    bearing: Optional[float] = None
    speed_kmh: Optional[float] = None
    timestamp: datetime
    freshness_seconds: int
    freshness: VehicleFreshness
    source: VehicleSource
    # Direction (resolved per vehicle — a route has more than one direction)
    direction_id: Optional[int] = None
    direction_label: Optional[str] = None  # "Towards <last stop>"
    origin: Optional[str] = None
    destination: Optional[str] = None
    route_pattern_source: Optional[str] = None  # GTFS_TRIPS | DEMO_CATALOG_DERIVED | SIMULATOR_ROUTE
    # Stop detection
    stop_status: StopStatus = "UNKNOWN"
    current_stop: Optional[VehicleStopInfo] = None
    next_stop: Optional[VehicleStopInfo] = None
    following_stop: Optional[VehicleStopInfo] = None
    total_stops: Optional[int] = None
    completed_stops: Optional[int] = None
    remaining_stops: Optional[int] = None
    progress_percentage: Optional[int] = None
    remaining_stop_names: List[str] = Field(default_factory=list)


class RealtimeVehiclesResponse(BaseModel):
    feed_state: FeedState
    source: VehicleSource
    realtime_connected: bool
    operational_statement: Optional[str] = None
    generated_at: datetime
    count: int
    counts_by_freshness: Dict[str, int]
    excluded: Dict[str, int]
    vehicles: List[TrackedVehicle]


class RealtimeStatusResponse(BaseModel):
    feed_state: FeedState
    source: VehicleSource
    realtime_connected: bool
    configured: bool
    operational_statement: Optional[str] = None
    last_successful_update: Optional[datetime] = None
    consecutive_failures: int = 0
    last_error_code: Optional[str] = None
    vehicle_count: int
    counts_by_freshness: Dict[str, int]
    freshness_thresholds_seconds: Dict[str, int]
    poll_interval_seconds: float
