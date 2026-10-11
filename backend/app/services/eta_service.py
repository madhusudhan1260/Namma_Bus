from datetime import datetime, timezone
import math
from typing import Optional
from ..models.transit import ETAEstimate


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on the Earth in kilometers.
    """
    radius = 6371.0  # Earth radius in kilometers

    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius * c


class ETAService:
    """
    Algorithmic ETA calculation engine based on geospatial coordinates,
    corridor route geometry, speed vectors, stop dwell overheads, and feed freshness.
    """

    DEFAULT_URBAN_SPEED_KMH = 22.0  # Average Bengaluru city transit speed
    STOP_DWELL_MINUTES = 0.75       # Average passenger boarding dwell time per stop

    @classmethod
    def calculate_eta(
        cls,
        bus_id: str,
        route_number: str,
        bus_lat: float,
        bus_lon: float,
        target_stop_name: str,
        target_lat: float,
        target_lon: float,
        current_speed_kmh: Optional[float] = None,
        intermediate_stops_count: int = 1,
        source: str = "geometric_estimate",
        feed_is_stale: bool = False,
        trip_update_eta_seconds: Optional[int] = None,
        last_updated: Optional[datetime] = None,
    ) -> ETAEstimate:
        dist_km = haversine_distance_km(bus_lat, bus_lon, target_lat, target_lon)

        if source == "gtfs_rt_trip_update" and trip_update_eta_seconds is not None:
            total_eta = max(1, round(trip_update_eta_seconds / 60.0))
            speed = current_speed_kmh if (current_speed_kmh and current_speed_kmh > 0) else cls.DEFAULT_URBAN_SPEED_KMH
        else:
            source = "geometric_estimate"
            # Use reported telemetry speed if sensible (> 5 km/h), else fallback to urban default
            speed = (
                current_speed_kmh
                if current_speed_kmh and current_speed_kmh > 5.0
                else cls.DEFAULT_URBAN_SPEED_KMH
            )

            # Raw travel time in minutes: (distance / speed) * 60
            travel_minutes = (dist_km / speed) * 60.0

            # Add dwell overhead for intermediate passenger stops
            dwell_minutes = intermediate_stops_count * cls.STOP_DWELL_MINUTES

            total_eta = max(1, round(travel_minutes + dwell_minutes))

        # Calculate confidence
        if feed_is_stale:
            confidence = "low"
        elif source == "gtfs_rt_trip_update":
            confidence = "high"
        elif dist_km < 4.0:
            confidence = "high"
        elif dist_km < 10.0:
            confidence = "moderate"
        else:
            confidence = "low"

        return ETAEstimate(
            bus_id=bus_id,
            route_number=route_number,
            target_stop=target_stop_name,
            eta_minutes=total_eta,
            distance_km=round(dist_km, 2),
            current_speed_kmh=round(speed, 1),
            source=source,
            confidence=confidence,
            is_stale=feed_is_stale,
            last_updated=last_updated or datetime.now(timezone.utc),
        )

