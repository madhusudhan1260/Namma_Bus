from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class GTFSOccupancyStatus(str, Enum):
    EMPTY = "EMPTY"
    MANY_SEATS_AVAILABLE = "MANY_SEATS_AVAILABLE"
    FEW_SEATS_AVAILABLE = "FEW_SEATS_AVAILABLE"
    STANDING_ROOM_ONLY = "STANDING_ROOM_ONLY"
    CRUSHED_STANDING_ROOM_ONLY = "CRUSHED_STANDING_ROOM_ONLY"
    FULL = "FULL"
    NOT_ACCEPTING_PASSENGERS = "NOT_ACCEPTING_PASSENGERS"
    NO_DATA_AVAILABLE = "NO_DATA_AVAILABLE"


# --- GTFS Static Models ---

class GTFSRoute(BaseModel):
    route_id: str
    route_short_name: str
    route_long_name: str
    route_type: int = 3  # 3 = Bus
    route_color: Optional[str] = None
    route_text_color: Optional[str] = None


class GTFSStop(BaseModel):
    stop_id: str
    stop_name: str
    stop_lat: float
    stop_lon: float
    stop_code: Optional[str] = None
    zone_id: Optional[str] = None


class GTFSTrip(BaseModel):
    trip_id: str
    route_id: str
    service_id: str = "daily"
    trip_headsign: Optional[str] = None
    direction_id: Optional[int] = 0
    shape_id: Optional[str] = None


class GTFSStopTime(BaseModel):
    trip_id: str
    arrival_time: str
    departure_time: str
    stop_id: str
    stop_sequence: int


class GTFSCalendar(BaseModel):
    service_id: str
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    start_date: str  # YYYYMMDD
    end_date: str  # YYYYMMDD


class GTFSCalendarDate(BaseModel):
    service_id: str
    date: str  # YYYYMMDD
    exception_type: int  # 1 = service added, 2 = service removed


class GTFSShapePoint(BaseModel):
    shape_id: str
    shape_pt_lat: float
    shape_pt_lon: float
    shape_pt_sequence: int


# --- GTFS-Realtime Models ---

class GTFSVehiclePosition(BaseModel):
    vehicle_id: str
    trip_id: Optional[str] = None
    route_id: Optional[str] = None
    route_number: Optional[str] = None
    latitude: float
    longitude: float
    bearing: Optional[float] = None
    speed_kmh: Optional[float] = None
    timestamp: Optional[int] = None
    occupancy_status: Optional[str] = None
    current_stop_sequence: Optional[int] = None
    current_status: Optional[str] = None


class GTFSStopTimeUpdate(BaseModel):
    stop_sequence: Optional[int] = None
    stop_id: Optional[str] = None
    stop_name: Optional[str] = None
    arrival_delay_seconds: Optional[int] = None
    arrival_time: Optional[int] = None
    departure_delay_seconds: Optional[int] = None
    departure_time: Optional[int] = None


class GTFSTripUpdate(BaseModel):
    trip_id: str
    route_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    stop_time_updates: List[GTFSStopTimeUpdate] = Field(default_factory=list)
    delay_seconds: Optional[int] = None
    timestamp: Optional[int] = None


class GTFSServiceAlert(BaseModel):
    id: str
    cause: Optional[str] = "UNKNOWN_CAUSE"
    effect: Optional[str] = "UNKNOWN_EFFECT"
    header_text: str
    description_text: Optional[str] = None
    active_period_start: Optional[int] = None
    active_period_end: Optional[int] = None
    affected_route_ids: List[str] = Field(default_factory=list)
    affected_stop_ids: List[str] = Field(default_factory=list)
    affected_trip_ids: List[str] = Field(default_factory=list)
    severity_level: Optional[str] = "INFO"
