import csv
import io
import logging
from typing import Any, Dict, List, Optional, Union

from .models import (
    GTFSRoute,
    GTFSStop,
    GTFSTrip,
    GTFSStopTime,
    GTFSShapePoint,
    GTFSCalendar,
    GTFSCalendarDate,
    GTFSVehiclePosition,
    GTFSTripUpdate,
    GTFSStopTimeUpdate,
    GTFSServiceAlert,
)

logger = logging.getLogger("nammamove.gtfs_parser")


class GTFSParser:
    """
    Parses official GTFS Static CSV files and GTFS-Realtime JSON/payloads.
    Follows official General Transit Feed Specification standards.
    """

    # --- Static GTFS CSV Parsers ---

    @staticmethod
    def parse_routes_csv(content: str) -> List[GTFSRoute]:
        routes = []
        reader = csv.DictReader(io.StringIO(content.strip()))
        for row in reader:
            try:
                routes.append(
                    GTFSRoute(
                        route_id=row["route_id"].strip(),
                        route_short_name=row.get("route_short_name", "").strip() or row.get("route_id", "").strip(),
                        route_long_name=row.get("route_long_name", "").strip() or row.get("route_id", "").strip(),
                        route_type=int(row.get("route_type", 3)),
                        route_color=row.get("route_color", "").strip() or None,
                        route_text_color=row.get("route_text_color", "").strip() or None,
                    )
                )
            except Exception as e:
                logger.warning("Error parsing GTFS route row: %s (row=%s)", e, row)
        return routes

    @staticmethod
    def parse_stops_csv(content: str) -> List[GTFSStop]:
        stops = []
        reader = csv.DictReader(io.StringIO(content.strip()))
        for row in reader:
            try:
                stops.append(
                    GTFSStop(
                        stop_id=row["stop_id"].strip(),
                        stop_name=row["stop_name"].strip(),
                        stop_lat=float(row["stop_lat"]),
                        stop_lon=float(row["stop_lon"]),
                        stop_code=row.get("stop_code", "").strip() or None,
                        zone_id=row.get("zone_id", "").strip() or None,
                    )
                )
            except Exception as e:
                logger.warning("Error parsing GTFS stop row: %s (row=%s)", e, row)
        return stops

    @staticmethod
    def parse_trips_csv(content: str) -> List[GTFSTrip]:
        trips = []
        reader = csv.DictReader(io.StringIO(content.strip()))
        for row in reader:
            try:
                trips.append(
                    GTFSTrip(
                        trip_id=row["trip_id"].strip(),
                        route_id=row["route_id"].strip(),
                        service_id=row.get("service_id", "daily").strip(),
                        trip_headsign=row.get("trip_headsign", "").strip() or None,
                        direction_id=int(row.get("direction_id", 0)),
                        shape_id=row.get("shape_id", "").strip() or None,
                    )
                )
            except Exception as e:
                logger.warning("Error parsing GTFS trip row: %s (row=%s)", e, row)
        return trips

    @staticmethod
    def parse_stop_times_csv(content: str) -> List[GTFSStopTime]:
        stop_times = []
        reader = csv.DictReader(io.StringIO(content.strip()))
        for row in reader:
            try:
                stop_times.append(
                    GTFSStopTime(
                        trip_id=row["trip_id"].strip(),
                        arrival_time=row["arrival_time"].strip(),
                        departure_time=row["departure_time"].strip(),
                        stop_id=row["stop_id"].strip(),
                        stop_sequence=int(row["stop_sequence"]),
                    )
                )
            except Exception as e:
                logger.warning("Error parsing GTFS stop_time row: %s (row=%s)", e, row)
        return stop_times

    @staticmethod
    def parse_shapes_csv(content: str) -> List[GTFSShapePoint]:
        shapes = []
        reader = csv.DictReader(io.StringIO(content.strip()))
        for row in reader:
            try:
                shapes.append(
                    GTFSShapePoint(
                        shape_id=row["shape_id"].strip(),
                        shape_pt_lat=float(row["shape_pt_lat"]),
                        shape_pt_lon=float(row["shape_pt_lon"]),
                        shape_pt_sequence=int(row["shape_pt_sequence"]),
                    )
                )
            except Exception as e:
                logger.warning("Error parsing GTFS shape row: %s (row=%s)", e, row)
        return sorted(shapes, key=lambda s: s.shape_pt_sequence)

    @staticmethod
    def parse_calendar_rows(rows) -> List[GTFSCalendar]:
        out = []
        for row in rows:
            try:
                out.append(GTFSCalendar(
                    service_id=row["service_id"].strip(),
                    monday=row["monday"].strip() == "1",
                    tuesday=row["tuesday"].strip() == "1",
                    wednesday=row["wednesday"].strip() == "1",
                    thursday=row["thursday"].strip() == "1",
                    friday=row["friday"].strip() == "1",
                    saturday=row["saturday"].strip() == "1",
                    sunday=row["sunday"].strip() == "1",
                    start_date=row["start_date"].strip(),
                    end_date=row["end_date"].strip(),
                ))
            except Exception as e:
                logger.warning("Error parsing GTFS calendar row: %s", e)
        return out

    @staticmethod
    def parse_calendar_dates_rows(rows) -> List[GTFSCalendarDate]:
        out = []
        for row in rows:
            try:
                out.append(GTFSCalendarDate(
                    service_id=row["service_id"].strip(),
                    date=row["date"].strip(),
                    exception_type=int(row["exception_type"]),
                ))
            except Exception as e:
                logger.warning("Error parsing GTFS calendar_dates row: %s", e)
        return out

    @staticmethod
    def iter_csv_file(path: str):
        """Streams rows from a GTFS CSV file (handles a UTF-8 BOM) without loading it all into memory."""
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                yield row

    # --- GTFS-Realtime Parsers & Data Quality Pipeline ---

    @classmethod
    def parse_vehicle_positions_with_stats(
        cls, data: Union[Dict[str, Any], List[Any]]
    ) -> tuple[List[GTFSVehiclePosition], Dict[str, Any]]:
        """
        Parses GTFS-Realtime VehiclePositions with data quality validation.
        Rejects malformed entities individually rather than failing the entire feed.
        Returns valid vehicles and isolation stats (valid, invalid, ignored).
        """
        vehicles: List[GTFSVehiclePosition] = []
        valid_count = 0
        invalid_count = 0
        ignored_count = 0
        details: List[str] = []

        if not data:
            return vehicles, {
                "valid_entities": 0,
                "invalid_entities": 0,
                "ignored_entities": 0,
                "total_entities": 0,
                "validation_details": ["No data payload provided"],
            }

        entities = data.get("entity", []) if isinstance(data, dict) else data
        if not isinstance(entities, list):
            return vehicles, {
                "valid_entities": 0,
                "invalid_entities": 1,
                "ignored_entities": 0,
                "total_entities": 1,
                "validation_details": ["Payload entity field is not a list"],
            }

        for item in entities:
            try:
                if not isinstance(item, dict):
                    ignored_count += 1
                    continue

                # If this entity is not a vehicle position (e.g. alert or trip update in combined feed)
                if "alert" in item and "vehicle" not in item:
                    ignored_count += 1
                    continue
                if "trip_update" in item and "vehicle" not in item and "position" not in item:
                    ignored_count += 1
                    continue

                v_data = item.get("vehicle", item)
                pos = v_data.get("position", {}) if isinstance(v_data, dict) else {}
                trip = v_data.get("trip", {}) if isinstance(v_data, dict) else {}
                veh_info = v_data.get("vehicle", {}) if isinstance(v_data, dict) else {}

                veh_id = (
                    veh_info.get("id")
                    or v_data.get("vehicle_id")
                    or item.get("id")
                    or trip.get("trip_id")
                )
                if not veh_id:
                    invalid_count += 1
                    details.append(f"Entity missing vehicle ID: {item.get('id', 'unknown')}")
                    continue

                lat = pos.get("latitude") or v_data.get("latitude")
                lon = pos.get("longitude") or v_data.get("longitude")
                if lat is None or lon is None:
                    invalid_count += 1
                    details.append(f"Vehicle {veh_id} missing latitude/longitude")
                    continue

                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                except (ValueError, TypeError):
                    invalid_count += 1
                    details.append(f"Vehicle {veh_id} non-numeric coordinates: lat={lat}, lon={lon}")
                    continue

                # Coordinate sanity: valid global lat/lon bounds
                if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
                    invalid_count += 1
                    details.append(f"Vehicle {veh_id} coordinates out of world bounds: ({lat_f}, {lon_f})")
                    continue

                # Speed conversion: standard GTFS-RT speed is m/s
                speed = pos.get("speed") or v_data.get("speed_kmh") or v_data.get("speed")
                # Missing speed stays None (never invented); downstream ETA code applies its own documented assumption.
                speed_kmh = float(speed) * 3.6 if (speed is not None and speed < 40 and "speed_kmh" not in v_data) else (float(speed) if speed is not None else None)

                bearing = pos.get("bearing") or v_data.get("bearing") or v_data.get("heading")
                route_id = trip.get("route_id") or v_data.get("route_id") or veh_info.get("label") or v_data.get("route_number")
                route_number = v_data.get("route_number") or veh_info.get("label") or route_id

                parsed_veh = GTFSVehiclePosition(
                    vehicle_id=str(veh_id),
                    trip_id=trip.get("trip_id") or v_data.get("trip_id"),
                    route_id=str(route_id) if route_id else None,
                    route_number=str(route_number) if route_number else None,
                    latitude=lat_f,
                    longitude=lon_f,
                    bearing=float(bearing) if bearing is not None else None,
                    speed_kmh=round(speed_kmh, 1) if speed_kmh is not None else None,
                    timestamp=v_data.get("timestamp") or item.get("timestamp"),
                    occupancy_status=v_data.get("occupancy_status"),
                    current_stop_sequence=v_data.get("current_stop_sequence"),
                    current_status=v_data.get("current_status"),
                )
                vehicles.append(parsed_veh)
                valid_count += 1

            except Exception as e:
                invalid_count += 1
                details.append(f"Failed to parse entity: {str(e)}")
                logger.warning("Failed to parse GTFS-RT vehicle position entity: %s (item=%s)", e, item)

        stats = {
            "valid_entities": valid_count,
            "invalid_entities": invalid_count,
            "ignored_entities": ignored_count,
            "total_entities": valid_count + invalid_count + ignored_count,
            "validation_details": details[:10],
        }
        return vehicles, stats

    @classmethod
    def parse_vehicle_positions(cls, data: Union[Dict[str, Any], List[Any]]) -> List[GTFSVehiclePosition]:
        """Parses GTFS-Realtime VehiclePositions (backward compatible wrapper)."""
        vehicles, _ = cls.parse_vehicle_positions_with_stats(data)
        return vehicles

    @classmethod
    def parse_trip_updates_with_stats(
        cls, data: Union[Dict[str, Any], List[Any]]
    ) -> tuple[List[GTFSTripUpdate], Dict[str, Any]]:
        """
        Parses GTFS-Realtime TripUpdates with entity validation.
        """
        updates: List[GTFSTripUpdate] = []
        valid_count = 0
        invalid_count = 0
        ignored_count = 0
        details: List[str] = []

        if not data:
            return updates, {
                "valid_entities": 0,
                "invalid_entities": 0,
                "ignored_entities": 0,
                "total_entities": 0,
                "validation_details": ["No data payload provided"],
            }

        entities = data.get("entity", []) if isinstance(data, dict) else data
        if not isinstance(entities, list):
            return updates, {
                "valid_entities": 0,
                "invalid_entities": 1,
                "ignored_entities": 0,
                "total_entities": 1,
                "validation_details": ["Payload entity field is not a list"],
            }

        for item in entities:
            try:
                if not isinstance(item, dict):
                    ignored_count += 1
                    continue

                if "alert" in item and "trip_update" not in item:
                    ignored_count += 1
                    continue

                tu_data = item.get("trip_update", item)
                trip = tu_data.get("trip", {}) if isinstance(tu_data, dict) else {}
                trip_id = trip.get("trip_id") or tu_data.get("trip_id") or item.get("id")
                if not trip_id:
                    invalid_count += 1
                    details.append(f"TripUpdate missing trip ID: {item.get('id', 'unknown')}")
                    continue

                veh = tu_data.get("vehicle", {}) if isinstance(tu_data, dict) else {}
                vehicle_id = veh.get("id") or tu_data.get("vehicle_id")

                stop_updates = []
                for stu in tu_data.get("stop_time_update", []):
                    if not isinstance(stu, dict):
                        continue
                    arr = stu.get("arrival", {}) or {}
                    dep = stu.get("departure", {}) or {}
                    stop_updates.append(
                        GTFSStopTimeUpdate(
                            stop_sequence=stu.get("stop_sequence"),
                            stop_id=stu.get("stop_id"),
                            stop_name=stu.get("stop_name"),
                            arrival_delay_seconds=arr.get("delay"),
                            arrival_time=arr.get("time"),
                            departure_delay_seconds=dep.get("delay"),
                            departure_time=dep.get("time"),
                        )
                    )

                updates.append(
                    GTFSTripUpdate(
                        trip_id=str(trip_id),
                        route_id=trip.get("route_id") or tu_data.get("route_id"),
                        vehicle_id=str(vehicle_id) if vehicle_id else None,
                        stop_time_updates=stop_updates,
                        delay_seconds=tu_data.get("delay"),
                        timestamp=tu_data.get("timestamp") or item.get("timestamp"),
                    )
                )
                valid_count += 1
            except Exception as e:
                invalid_count += 1
                details.append(f"Failed to parse trip update: {str(e)}")
                logger.warning("Failed to parse GTFS-RT trip update entity: %s (item=%s)", e, item)

        stats = {
            "valid_entities": valid_count,
            "invalid_entities": invalid_count,
            "ignored_entities": ignored_count,
            "total_entities": valid_count + invalid_count + ignored_count,
            "validation_details": details[:10],
        }
        return updates, stats

    @classmethod
    def parse_trip_updates(cls, data: Union[Dict[str, Any], List[Any]]) -> List[GTFSTripUpdate]:
        """Parses GTFS-Realtime TripUpdates (backward compatible wrapper)."""
        updates, _ = cls.parse_trip_updates_with_stats(data)
        return updates

    @classmethod
    def parse_service_alerts_with_stats(
        cls, data: Union[Dict[str, Any], List[Any]]
    ) -> tuple[List[GTFSServiceAlert], Dict[str, Any]]:
        """
        Parses GTFS-Realtime ServiceAlerts with entity validation.
        """
        alerts: List[GTFSServiceAlert] = []
        valid_count = 0
        invalid_count = 0
        ignored_count = 0
        details: List[str] = []

        if not data:
            return alerts, {
                "valid_entities": 0,
                "invalid_entities": 0,
                "ignored_entities": 0,
                "total_entities": 0,
                "validation_details": ["No data payload provided"],
            }

        entities = data.get("entity", []) if isinstance(data, dict) else data
        if not isinstance(entities, list):
            return alerts, {
                "valid_entities": 0,
                "invalid_entities": 1,
                "ignored_entities": 0,
                "total_entities": 1,
                "validation_details": ["Payload entity field is not a list"],
            }

        for item in entities:
            try:
                if not isinstance(item, dict):
                    ignored_count += 1
                    continue

                if "vehicle" in item and "alert" not in item:
                    ignored_count += 1
                    continue

                alert_data = item.get("alert", item)
                alert_id = item.get("id") or alert_data.get("id")
                if not alert_id:
                    invalid_count += 1
                    details.append("Service alert missing ID")
                    continue

                header = alert_data.get("header_text", {})
                header_str = header.get("text", "") if isinstance(header, dict) else str(header)

                desc = alert_data.get("description_text", {})
                desc_str = desc.get("text", "") if isinstance(desc, dict) else str(desc)

                # Extract informed entities
                route_ids: List[str] = []
                stop_ids: List[str] = []
                trip_ids: List[str] = []
                for ie in alert_data.get("informed_entity", []):
                    if isinstance(ie, dict):
                        if ie.get("route_id"):
                            route_ids.append(str(ie["route_id"]))
                        if ie.get("stop_id"):
                            stop_ids.append(str(ie["stop_id"]))
                        if ie.get("trip_id"):
                            trip_ids.append(str(ie["trip_id"]))

                # Extract active period
                p_start = None
                p_end = None
                active_periods = alert_data.get("active_period", [])
                if active_periods and isinstance(active_periods, list) and isinstance(active_periods[0], dict):
                    p_start = active_periods[0].get("start")
                    p_end = active_periods[0].get("end")

                alerts.append(
                    GTFSServiceAlert(
                        id=str(alert_id),
                        cause=alert_data.get("cause", "UNKNOWN_CAUSE"),
                        effect=alert_data.get("effect", "UNKNOWN_EFFECT"),
                        header_text=header_str or "BMTC Transit Alert",
                        description_text=desc_str or None,
                        active_period_start=p_start,
                        active_period_end=p_end,
                        affected_route_ids=route_ids,
                        affected_stop_ids=stop_ids,
                        affected_trip_ids=trip_ids,
                        severity_level=alert_data.get("severity_level", "INFO"),
                    )
                )
                valid_count += 1
            except Exception as e:
                invalid_count += 1
                details.append(f"Failed to parse service alert: {str(e)}")
                logger.warning("Failed to parse GTFS-RT service alert entity: %s (item=%s)", e, item)

        stats = {
            "valid_entities": valid_count,
            "invalid_entities": invalid_count,
            "ignored_entities": ignored_count,
            "total_entities": valid_count + invalid_count + ignored_count,
            "validation_details": details[:10],
        }
        return alerts, stats

    @classmethod
    def parse_service_alerts(cls, data: Union[Dict[str, Any], List[Any]]) -> List[GTFSServiceAlert]:
        """Parses GTFS-Realtime ServiceAlerts (backward compatible wrapper)."""
        alerts, _ = cls.parse_service_alerts_with_stats(data)
        return alerts
