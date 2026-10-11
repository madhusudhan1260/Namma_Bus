from datetime import datetime, timezone
import math
from typing import List, Optional

from .models import (
    GTFSVehiclePosition,
    GTFSTripUpdate,
    GTFSRoute,
    GTFSStop,
    GTFSOccupancyStatus,
)
from .repository import GTFSRepository, gtfs_repository
from ...models.transit import (
    Bus,
    BusLocation,
    Route,
    BusStop,
    Coordinate,
    Occupancy,
    ETAEstimate,
)


class GTFSNormalizer:
    """
    Normalizes external GTFS Static and GTFS-Realtime entities into
    clean internal application models (Bus, BusLocation, Route, BusStop, Occupancy, ETAEstimate).
    """

    @staticmethod
    def normalize_bus_location(vp: GTFSVehiclePosition) -> BusLocation:
        dt = (
            datetime.fromtimestamp(vp.timestamp, tz=timezone.utc)
            if vp.timestamp
            else datetime.now(timezone.utc)
        )
        heading = vp.bearing or 0.0
        speed = vp.speed_kmh or 25.0

        return BusLocation(
            bus_id=vp.vehicle_id,
            route_number=vp.route_number or vp.route_id or "BMTC",
            latitude=vp.latitude,
            longitude=vp.longitude,
            speed=round(speed, 1),
            direction=round(heading, 1),
            heading=round(heading, 1),
            timestamp=dt,
            next_stop=None,
            eta_next_stop_minutes=None,
        )

    @classmethod
    def normalize_vehicle(
        cls,
        vp: GTFSVehiclePosition,
        repo: Optional[GTFSRepository] = None,
        trip_update: Optional[GTFSTripUpdate] = None,
    ) -> Bus:
        r = repo or gtfs_repository
        route_id = vp.route_id or vp.route_number or "500D"
        gtfs_route = r.get_route(route_id)

        route_num = vp.route_number or (gtfs_route.route_short_name if gtfs_route else route_id)
        is_ac = "vajra" in route_num.lower() or "kia" in route_num.lower() or route_num.startswith("500")

        # Determine Origin / Destination from route or catalog
        origin = "Central Silk Board"
        destination = "Majestic (KBS)"
        if gtfs_route and " - " in gtfs_route.route_long_name:
            parts = gtfs_route.route_long_name.split(" - ")
            origin = parts[0].strip()
            destination = parts[1].strip()

        # Occupancy normalization (strictly adheres to official GTFS-RT status if present)
        occ_pct = 0
        total_capacity = 50

        if vp.occupancy_status:
            status_upper = vp.occupancy_status.upper()
            if status_upper == GTFSOccupancyStatus.EMPTY:
                occ_pct = 10
            elif status_upper == GTFSOccupancyStatus.MANY_SEATS_AVAILABLE:
                occ_pct = 35
            elif status_upper == GTFSOccupancyStatus.FEW_SEATS_AVAILABLE:
                occ_pct = 68
            elif status_upper == GTFSOccupancyStatus.STANDING_ROOM_ONLY:
                occ_pct = 85
            elif status_upper in (GTFSOccupancyStatus.CRUSHED_STANDING_ROOM_ONLY, GTFSOccupancyStatus.FULL):
                occ_pct = 95
            elif status_upper == GTFSOccupancyStatus.NOT_ACCEPTING_PASSENGERS:
                occ_pct = 100

        passengers = int(total_capacity * (occ_pct / 100.0))
        avail_seats = max(0, total_capacity - passengers) if vp.occupancy_status else 0

        # Next stop and ETA extraction from TripUpdate if available
        next_stop = "Upcoming Stop"
        next_stop_eta = 5
        if trip_update and trip_update.stop_time_updates:
            first_stu = trip_update.stop_time_updates[0]
            if first_stu.stop_id:
                stop_obj = r.get_stop(first_stu.stop_id)
                if stop_obj:
                    next_stop = stop_obj.stop_name
                elif first_stu.stop_name:
                    next_stop = first_stu.stop_name

            if first_stu.arrival_time:
                now_epoch = int(datetime.now(timezone.utc).timestamp())
                diff_sec = max(0, first_stu.arrival_time - now_epoch)
                next_stop_eta = max(1, math.ceil(diff_sec / 60))
            elif first_stu.arrival_delay_seconds is not None:
                next_stop_eta = max(1, math.ceil(first_stu.arrival_delay_seconds / 60))

        dt = (
            datetime.fromtimestamp(vp.timestamp, tz=timezone.utc)
            if vp.timestamp
            else datetime.now(timezone.utc)
        )

        bus_type = "Vajra AC Electric" if is_ac else "BMTC Ordinary"

        return Bus(
            bus_id=vp.vehicle_id,
            route_number=route_num,
            bus_type=bus_type,
            destination=destination,
            latitude=vp.latitude,
            longitude=vp.longitude,
            speed=vp.speed_kmh or 25.0,
            direction=vp.bearing or 0.0,
            capacity=total_capacity,
            current_passengers=passengers,
            occupancy_percentage=occ_pct,
            status="IN_SERVICE",
            next_stop=next_stop,
            updated_at=dt,
            plate_number=vp.vehicle_id,
            eta_minutes=next_stop_eta,
            available_seats=avail_seats,
        )

    @staticmethod
    def normalize_stop(gtfs_stop: GTFSStop) -> BusStop:
        return BusStop(
            stop_id=gtfs_stop.stop_id,
            name=gtfs_stop.stop_name,
            latitude=gtfs_stop.stop_lat,
            longitude=gtfs_stop.stop_lon,
            buses_stopping_soon=[],
        )

    @classmethod
    def normalize_route(
        cls,
        gtfs_route: GTFSRoute,
        stops: List[GTFSStop],
        shape_points: Optional[List[GTFSShapePoint]] = None,
    ) -> Route:
        stop_names = [s.stop_name for s in stops]
        if shape_points and len(shape_points) > 1:
            waypoints = [Coordinate(latitude=pt.shape_pt_lat, longitude=pt.shape_pt_lon) for pt in shape_points]
        else:
            waypoints = [Coordinate(latitude=s.stop_lat, longitude=s.stop_lon) for s in stops]

        is_ac = (
            "vajra" in gtfs_route.route_short_name.lower()
            or "kia" in gtfs_route.route_short_name.lower()
            or gtfs_route.route_short_name.startswith("500")
        )

        origin = "Central Silk Board"
        destination = "Majestic (KBS)"
        if " - " in gtfs_route.route_long_name:
            parts = gtfs_route.route_long_name.split(" - ")
            origin = parts[0].strip()
            destination = parts[1].strip()

        return Route(
            route_id=gtfs_route.route_id,
            route_number=gtfs_route.route_short_name,
            source=origin,
            destination=destination,
            stops=stop_names,
            estimated_duration=42,
            is_ac=is_ac,
            bus_type="Vajra AC Electric" if is_ac else "BMTC Ordinary",
            waypoints=waypoints,
        )

    @classmethod
    def normalize_occupancy(cls, vp: GTFSVehiclePosition) -> Optional[Occupancy]:
        """
        Returns normalized Occupancy only if authorized GTFS-RT occupancy_status
        is explicitly provided. Returns None if APC data is unavailable.
        """
        if not vp.occupancy_status or vp.occupancy_status.upper() == GTFSOccupancyStatus.NO_DATA_AVAILABLE:
            return None

        status_upper = vp.occupancy_status.upper()
        level = "Low"
        pct = 20
        passengers = 10
        capacity = 50

        if status_upper == GTFSOccupancyStatus.EMPTY:
            level, pct, passengers = "Low", 5, 2
        elif status_upper == GTFSOccupancyStatus.MANY_SEATS_AVAILABLE:
            level, pct, passengers = "Low", 30, 15
        elif status_upper == GTFSOccupancyStatus.FEW_SEATS_AVAILABLE:
            level, pct, passengers = "Medium", 65, 33
        elif status_upper == GTFSOccupancyStatus.STANDING_ROOM_ONLY:
            level, pct, passengers = "High", 85, 42
        elif status_upper in (GTFSOccupancyStatus.CRUSHED_STANDING_ROOM_ONLY, GTFSOccupancyStatus.FULL):
            level, pct, passengers = "High", 95, 48
        elif status_upper == GTFSOccupancyStatus.NOT_ACCEPTING_PASSENGERS:
            level, pct, passengers = "High", 100, 50

        avail = max(0, capacity - passengers)
        dt = (
            datetime.fromtimestamp(vp.timestamp, tz=timezone.utc)
            if vp.timestamp
            else datetime.now(timezone.utc)
        )

        return Occupancy(
            bus_id=vp.vehicle_id,
            route_number=vp.route_number or vp.route_id or "BMTC",
            current_passengers=passengers,
            total_capacity=capacity,
            occupancy_level=level,
            available_seats=avail,
            timestamp=dt,
        )
