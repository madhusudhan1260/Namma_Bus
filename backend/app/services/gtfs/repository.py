import os
import logging
import time
from datetime import date as date_cls, datetime
from typing import Dict, List, Optional, Any, Set

from .models import GTFSRoute, GTFSStop, GTFSTrip, GTFSShapePoint, GTFSStopTime, GTFSCalendar, GTFSCalendarDate
from .parser import GTFSParser

logger = logging.getLogger("nammamove.gtfs_repository")


class GTFSRepository:
    """
    In-memory storage and query interface for GTFS Static transit network metadata.
    Loads from an authorized static GTFS directory when available; otherwise provides
    baseline Bengaluru corridor definitions.
    """

    def __init__(self):
        self.routes: Dict[str, GTFSRoute] = {}
        self.stops: Dict[str, GTFSStop] = {}
        self.trips: Dict[str, GTFSTrip] = {}
        self.shapes: Dict[str, List[GTFSShapePoint]] = {}
        self.stop_times: Dict[str, List[Any]] = {}  # trip_id -> list of GTFSStopTime
        self.route_stops: Dict[str, List[str]] = {}  # route_id -> list of stop_ids
        # Phase 46: scalable indexes and service calendars
        self.route_trips: Dict[str, List[str]] = {}  # route_id -> trip_ids
        self.stop_routes: Dict[str, Set[str]] = {}  # stop_id -> route_ids
        self.calendars: Dict[str, GTFSCalendar] = {}
        self.calendar_dates: Dict[str, List[GTFSCalendarDate]] = {}
        self.data_source: str = "DEMO_CATALOG"  # DEMO_CATALOG | GTFS_STATIC
        self.last_load_report: Dict[str, Any] = {}

    def clear(self):
        self.__init__()

    def load_from_directory(self, dir_path: str) -> bool:
        """
        Streams a GTFS static feed (routes, stops, trips, stop_times, shapes, calendar, calendar_dates)
        into memory and builds route/stop/trip indexes. Malformed rows are skipped and counted.
        Nothing is hard-coded: every route and stop comes from the feed files.
        """
        if not dir_path or not os.path.isdir(dir_path):
            return False

        t0 = time.perf_counter()
        malformed: Dict[str, int] = {}
        loaded_any = False

        def rows(name: str):
            path = os.path.join(dir_path, name)
            return GTFSParser.iter_csv_file(path) if os.path.exists(path) else None

        def bad(name: str):
            malformed[name] = malformed.get(name, 0) + 1

        try:
            it = rows("routes.txt")
            if it is not None:
                for row in it:
                    try:
                        rid = row["route_id"].strip()
                        short = (row.get("route_short_name") or "").strip()
                        long_name = (row.get("route_long_name") or "").strip()
                        if not rid or not (short or long_name):
                            raise ValueError("GTFS requires route_short_name or route_long_name")
                        r = GTFSRoute(
                            route_id=rid,
                            route_short_name=(row.get("route_short_name") or "").strip() or rid,
                            route_long_name=(row.get("route_long_name") or "").strip() or rid,
                            route_type=int(row.get("route_type") or 3),
                            route_color=(row.get("route_color") or "").strip() or None,
                            route_text_color=(row.get("route_text_color") or "").strip() or None,
                        )
                        self.routes[r.route_id] = r
                        self.routes[r.route_short_name] = r
                    except Exception:
                        bad("routes.txt")
                loaded_any = True

            it = rows("stops.txt")
            if it is not None:
                for row in it:
                    try:
                        st = GTFSStop(
                            stop_id=row["stop_id"].strip(),
                            stop_name=row["stop_name"].strip(),
                            stop_lat=float(row["stop_lat"]),
                            stop_lon=float(row["stop_lon"]),
                            stop_code=(row.get("stop_code") or "").strip() or None,
                            zone_id=(row.get("zone_id") or "").strip() or None,
                        )
                        self.stops[st.stop_id] = st
                    except Exception:
                        bad("stops.txt")
                loaded_any = True

            it = rows("shapes.txt")
            if it is not None:
                for row in it:
                    try:
                        pt = GTFSShapePoint.model_construct(
                            shape_id=row["shape_id"].strip(),
                            shape_pt_lat=float(row["shape_pt_lat"]),
                            shape_pt_lon=float(row["shape_pt_lon"]),
                            shape_pt_sequence=int(row["shape_pt_sequence"]),
                        )
                        self.shapes.setdefault(pt.shape_id, []).append(pt)
                    except Exception:
                        bad("shapes.txt")
                for pts in self.shapes.values():
                    pts.sort(key=lambda p: p.shape_pt_sequence)
                loaded_any = True

            it = rows("trips.txt")
            if it is not None:
                for row in it:
                    try:
                        tr = GTFSTrip(
                            trip_id=row["trip_id"].strip(),
                            route_id=row["route_id"].strip(),
                            service_id=(row.get("service_id") or "daily").strip(),
                            trip_headsign=(row.get("trip_headsign") or "").strip() or None,
                            direction_id=int(row.get("direction_id") or 0),
                            shape_id=(row.get("shape_id") or "").strip() or None,
                        )
                        self.trips[tr.trip_id] = tr
                        self.route_trips.setdefault(tr.route_id, []).append(tr.trip_id)
                    except Exception:
                        bad("trips.txt")
                loaded_any = True

            it = rows("stop_times.txt")
            if it is not None:
                for row in it:
                    try:
                        stt = GTFSStopTime.model_construct(
                            trip_id=row["trip_id"].strip(),
                            arrival_time=row["arrival_time"].strip(),
                            departure_time=row["departure_time"].strip(),
                            stop_id=row["stop_id"].strip(),
                            stop_sequence=int(row["stop_sequence"]),
                        )
                        self.stop_times.setdefault(stt.trip_id, []).append(stt)
                    except Exception:
                        bad("stop_times.txt")
                # Index: route -> stops of its longest trip pattern; stop -> routes
                best_len: Dict[str, int] = {}
                for trip_id, times in self.stop_times.items():
                    times.sort(key=lambda x: x.stop_sequence)
                    trip_obj = self.trips.get(trip_id)
                    if not trip_obj:
                        continue
                    for x in times:
                        self.stop_routes.setdefault(x.stop_id, set()).add(trip_obj.route_id)
                    if len(times) > best_len.get(trip_obj.route_id, -1):
                        best_len[trip_obj.route_id] = len(times)
                        self.route_stops[trip_obj.route_id] = [x.stop_id for x in times]
                loaded_any = True

            it = rows("calendar.txt")
            if it is not None:
                for c in GTFSParser.parse_calendar_rows(it):
                    self.calendars[c.service_id] = c
                loaded_any = True

            it = rows("calendar_dates.txt")
            if it is not None:
                for cd in GTFSParser.parse_calendar_dates_rows(it):
                    self.calendar_dates.setdefault(cd.service_id, []).append(cd)
                loaded_any = True

            if loaded_any:
                self.data_source = "GTFS_STATIC"
                self.last_load_report = {
                    "directory": os.path.basename(os.path.normpath(dir_path)),
                    "load_seconds": round(time.perf_counter() - t0, 3),
                    "malformed_rows": malformed,
                    **self.get_stats(),
                }
                logger.info(
                    "[TRANSIT] Loaded GTFS static dataset: %d routes, %d stops, %d trips in %.2fs",
                    len(self.get_all_routes()), len(self.get_all_stops()), len(self.trips), time.perf_counter() - t0,
                )
        except Exception as e:
            logger.error("[TRANSIT] Error loading GTFS static directory %s: %s", dir_path, e)

        return loaded_any

    # -- Phase 46 queries -----------------------------------------------------

    def _route_id(self, route_id_or_number: str) -> str:
        r = self.get_route(route_id_or_number)
        return r.route_id if r else route_id_or_number

    def get_trips_for_route(self, route_id_or_number: str) -> List[GTFSTrip]:
        return [self.trips[t] for t in self.route_trips.get(self._route_id(route_id_or_number), []) if t in self.trips]

    def get_routes_for_stop(self, stop_id: str) -> List[GTFSRoute]:
        ids = set(self.stop_routes.get(stop_id, set()))
        # Demo catalog has no stop_times; fall back to the route -> stops mapping
        for rid, stops in self.route_stops.items():
            if stop_id in stops:
                ids.add(rid)
        return sorted((self.routes[r] for r in ids if r in self.routes), key=lambda r: r.route_short_name)

    def search_routes(self, query: str = "", limit: int = 50) -> List[GTFSRoute]:
        q = query.strip().lower()
        out = [r for r in self.get_all_routes() if not q or q in r.route_short_name.lower() or q in r.route_long_name.lower()]
        out.sort(key=lambda r: (not r.route_short_name.lower().startswith(q), r.route_short_name))
        return out[:limit]

    def search_stops(self, query: str = "", limit: int = 50) -> List[GTFSStop]:
        q = query.strip().lower()
        out = [s for s in self.get_all_stops() if not q or q in s.stop_name.lower() or q == (s.stop_code or "").lower()]
        out.sort(key=lambda s: (not s.stop_name.lower().startswith(q), s.stop_name))
        return out[:limit]

    def is_service_active(self, service_id: str, on: date_cls) -> bool:
        """GTFS calendar semantics: calendar.txt weekday/date range, overridden by calendar_dates.txt."""
        ymd = on.strftime("%Y%m%d")
        for cd in self.calendar_dates.get(service_id, []):
            if cd.date == ymd:
                return cd.exception_type == 1
        cal = self.calendars.get(service_id)
        if not cal:
            return False
        if not (cal.start_date <= ymd <= cal.end_date):
            return False
        return [cal.monday, cal.tuesday, cal.wednesday, cal.thursday, cal.friday, cal.saturday, cal.sunday][on.weekday()]

    def get_active_service_ids(self, on: date_cls) -> List[str]:
        ids = set(self.calendars) | set(self.calendar_dates)
        return sorted(sid for sid in ids if self.is_service_active(sid, on))

    def get_validation_report(self) -> Dict[str, Any]:
        """
        Generates comprehensive validation report for ingested static GTFS dataset.
        Identifies imported records, orphans, coordinate validity, and integrity metrics.
        Labels data explicitly as 'Scheduled Data'.
        """
        orphan_trips = 0
        orphan_stops = 0
        orphan_stop_times = 0
        invalid_coords = 0

        # Check trips for missing route references
        for trip in self.trips.values():
            if trip.route_id not in self.routes:
                orphan_trips += 1

        # Check stops for out-of-bounds or non-numeric coordinates
        for stop in self.stops.values():
            if not (10.0 <= stop.stop_lat <= 15.0 and 75.0 <= stop.stop_lon <= 80.0):
                invalid_coords += 1

        # Check stop_times for missing trips or missing stops
        for trip_id, st_list in self.stop_times.items():
            if trip_id not in self.trips:
                orphan_stop_times += len(st_list)
            for st in st_list:
                if st.stop_id not in self.stops:
                    orphan_stops += 1

        return {
            "data_category": "Scheduled Data",
            "is_realtime": False,
            "records_imported": {
                "routes": len(self.get_all_routes()),
                "stops": len(self.get_all_stops()),
                "trips": len(self.trips),
                "shapes": len(self.shapes),
                "stop_times": sum(len(v) for v in self.stop_times.values()),
            },
            "integrity_checks": {
                "orphan_trips": orphan_trips,
                "orphan_stops": orphan_stops,
                "orphan_stop_times": orphan_stop_times,
                "invalid_coordinates": invalid_coords,
                "relationship_valid": orphan_trips == 0 and orphan_stops == 0 and orphan_stop_times == 0,
            },
        }

    def init_default_bengaluru_catalog(self):
        """Initializes default Bengaluru arterial corridor metadata."""
        if self.stops and self.routes:
            return  # Already populated

        # Default Stops along key corridors
        default_stops = [
            GTFSStop(stop_id="stop-silk-board", stop_name="Central Silk Board Junction", stop_lat=12.9176, stop_lon=77.6238),
            GTFSStop(stop_id="stop-btm-water-tank", stop_name="BTM Layout Water Tank", stop_lat=12.9152, stop_lon=77.6120),
            GTFSStop(stop_id="stop-jayadeva", stop_name="Jayadeva Hospital", stop_lat=12.9180, stop_lon=77.5980),
            GTFSStop(stop_id="stop-majestic", stop_name="Majestic (Kempegowda Bus Station)", stop_lat=12.9774, stop_lon=77.5708),
            GTFSStop(stop_id="stop-shivajinagar", stop_name="Shivajinagar Bus Station", stop_lat=12.9856, stop_lon=77.6057),
            GTFSStop(stop_id="stop-electronic-city", stop_name="Electronic City Phase 1", stop_lat=12.8452, stop_lon=77.6602),
            GTFSStop(stop_id="stop-bommanahalli", stop_name="Bommanahalli", stop_lat=12.9029, stop_lon=77.6242),
            GTFSStop(stop_id="stop-hsr-5th", stop_name="HSR Layout Sector 5", stop_lat=12.9198, stop_lon=77.6401),
            GTFSStop(stop_id="stop-st-johns", stop_name="St. John’s Hospital", stop_lat=12.9290, stop_lon=77.6198),
            GTFSStop(stop_id="stop-koramangala-bda", stop_name="Koramangala BDA Complex", stop_lat=12.9345, stop_lon=77.6255),
            GTFSStop(stop_id="stop-airport", stop_name="Kempegowda Intl Airport (T2)", stop_lat=13.1986, stop_lon=77.7066),
            GTFSStop(stop_id="stop-hebbal", stop_name="Hebbal Flyover Junction", stop_lat=13.0354, stop_lon=77.5988),
            GTFSStop(stop_id="stop-marathahalli", stop_name="Marathahalli Bridge", stop_lat=12.9591, stop_lon=77.6974),
            GTFSStop(stop_id="stop-kadubeesanahalli", stop_name="Kadubeesanahalli", stop_lat=12.9352, stop_lon=77.6890),
            GTFSStop(stop_id="stop-bellandur", stop_name="Bellandur EcoSpace", stop_lat=12.9260, stop_lon=77.6762),
            GTFSStop(stop_id="stop-ibblur", stop_name="Ibblur Junction", stop_lat=12.9189, stop_lon=77.6505),
        ]
        for s in default_stops:
            self.stops[s.stop_id] = s

        # Default Routes
        default_routes = [
            GTFSRoute(route_id="500D", route_short_name="500D", route_long_name="Hebbal - Central Silk Board Express (ORR)", route_type=3),
            GTFSRoute(route_id="356", route_short_name="356", route_long_name="Kempegowda Bus Station - Electronic City", route_type=3),
            GTFSRoute(route_id="KIA-8", route_short_name="KIA-8", route_long_name="Electronic City - Kempegowda Intl Airport (Vayu Vajra)", route_type=3),
            GTFSRoute(route_id="201R", route_short_name="201R", route_long_name="Shivajinagar - BTM Layout 2nd Stage", route_type=3),
            GTFSRoute(route_id="G-2", route_short_name="G-2", route_long_name="Brigade Road - Sarjapur Road WIPRO", route_type=3),
        ]
        for r in default_routes:
            self.routes[r.route_id] = r
            self.routes[r.route_short_name] = r

        # Route to Stops mapping
        self.route_stops["500D"] = [
            "stop-silk-board", "stop-ibblur", "stop-bellandur", "stop-kadubeesanahalli",
            "stop-marathahalli", "stop-hebbal", "stop-majestic"
        ]
        self.route_stops["356"] = [
            "stop-electronic-city", "stop-bommanahalli", "stop-silk-board", "stop-st-johns", "stop-majestic"
        ]
        self.route_stops["KIA-8"] = [
            "stop-electronic-city", "stop-silk-board", "stop-marathahalli", "stop-hebbal", "stop-airport"
        ]
        self.route_stops["201R"] = [
            "stop-btm-water-tank", "stop-jayadeva", "stop-st-johns", "stop-koramangala-bda", "stop-shivajinagar"
        ]
        self.route_stops["G-2"] = [
            "stop-koramangala-bda", "stop-hsr-5th", "stop-ibblur", "stop-bellandur"
        ]

    def get_route(self, route_id_or_number: str) -> Optional[GTFSRoute]:
        return self.routes.get(route_id_or_number)

    def get_stop(self, stop_id: str) -> Optional[GTFSStop]:
        return self.stops.get(stop_id)

    def get_stops_for_route(self, route_id_or_number: str) -> List[GTFSStop]:
        stop_ids = self.route_stops.get(route_id_or_number, [])
        return [self.stops[sid] for sid in stop_ids if sid in self.stops]

    def get_all_stops(self) -> List[GTFSStop]:
        # Return unique stop objects
        seen = set()
        unique = []
        for s in self.stops.values():
            if s.stop_id not in seen:
                seen.add(s.stop_id)
                unique.append(s)
        return unique

    def get_all_routes(self) -> List[GTFSRoute]:
        seen = set()
        unique = []
        for r in self.routes.values():
            if r.route_id not in seen:
                seen.add(r.route_id)
                unique.append(r)
        return unique

    def get_shape(self, shape_id: str) -> List[GTFSShapePoint]:
        return self.shapes.get(shape_id, [])

    def get_shape_for_route(self, route_id_or_number: str) -> List[GTFSShapePoint]:
        """Finds any shape associated with trips running on this route."""
        route = self.get_route(route_id_or_number)
        target_route_id = route.route_id if route else route_id_or_number
        for t in self.trips.values():
            if t.route_id == target_route_id and t.shape_id and t.shape_id in self.shapes:
                return self.shapes[t.shape_id]
        return []

    def get_stats(self) -> Dict[str, int]:
        return {
            "routes": len(self.get_all_routes()),
            "stops": len(self.get_all_stops()),
            "trips": len(self.trips),
            "shapes": len(self.shapes),
            "stop_times": sum(len(v) for v in self.stop_times.values()),
            "calendars": len(self.calendars),
            "calendar_dates": sum(len(v) for v in self.calendar_dates.values()),
        }

    def get_validation_report(self) -> Dict[str, Any]:
        """
        Generates static GTFS ingestion and validation summary report.
        Identifies loaded records, orphan trips/stops, coordinate bounds,
        and clearly labels data source as 'Scheduled Data'.
        """
        all_stops = self.get_all_stops()
        all_routes = self.get_all_routes()

        # Coordinate checks
        invalid_coords = sum(
            1 for s in all_stops
            if not (12.0 <= s.stop_lat <= 14.0 and 76.5 <= s.stop_lon <= 78.5)
        )

        # Orphan trips (trips referencing missing route_id)
        known_route_ids = {r.route_id for r in all_routes}
        orphan_trips = sum(1 for t in self.trips.values() if t.route_id not in known_route_ids)

        # Orphan stop_times (referencing missing stop_id)
        known_stop_ids = {s.stop_id for s in all_stops}
        orphan_stop_times = 0
        for st_list in self.stop_times.values():
            for st in st_list:
                if st.stop_id not in known_stop_ids:
                    orphan_stop_times += 1

        return {
            "data_source": "Scheduled Data",
            "routes_count": len(all_routes),
            "stops_count": len(all_stops),
            "trips_count": len(self.trips),
            "shapes_count": len(self.shapes),
            "stop_times_count": sum(len(v) for v in self.stop_times.values()),
            "orphan_trips": orphan_trips,
            "orphan_stop_times": orphan_stop_times,
            "stops_outside_bounds": invalid_coords,
            "is_valid": invalid_coords == 0 and orphan_trips == 0,
        }


# Global GTFS repository instance
gtfs_repository = GTFSRepository()
gtfs_repository.init_default_bengaluru_catalog()
