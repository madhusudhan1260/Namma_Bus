"""Official Authorized GTFS Static Data Importer for NammaBlr.

Usage:
    python -m app.services.gtfs.import_static <GTFS_DIRECTORY>
"""
import sys
import os
import argparse
from typing import Dict, Any, List

from .parser import GTFSParser
from .repository import gtfs_repository


class GTFSStaticImporter:
    """Production importer for authorized municipal GTFS Static datasets."""

    REQUIRED_FILES = ['routes.txt', 'stops.txt', 'trips.txt', 'stop_times.txt']
    OPTIONAL_FILES = ['shapes.txt', 'calendar.txt', 'agency.txt']

    # Bengaluru regional bounds (including Kempegowda Airport and suburban corridors)
    MIN_LAT, MAX_LAT = 12.0, 14.0
    MIN_LON, MAX_LON = 76.5, 78.5

    @classmethod
    def import_directory(cls, dir_path: str) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            'success': False,
            'directory': dir_path,
            'routes_loaded': 0,
            'stops_loaded': 0,
            'trips_loaded': 0,
            'stop_times_loaded': 0,
            'shape_points_loaded': 0,
            'duplicates_detected': 0,
            'malformed_rows': 0,
            'relationship_errors': 0,
            'warnings': [],
            'errors': [],
            'record_counts': {
                'routes': 0,
                'stops': 0,
                'trips': 0,
                'stop_times': 0,
                'shapes': 0,
            },
        }

        if not dir_path or not os.path.isdir(dir_path):
            report['errors'].append(f"Directory not found or inaccessible: '{dir_path}'")
            return report

        # 1. Validate required files exist
        for req in cls.REQUIRED_FILES:
            fp = os.path.join(dir_path, req)
            if not os.path.isfile(fp):
                report['errors'].append(f"Required GTFS file missing: '{req}'")

        if report['errors']:
            return report

        # 2. Parse and validate routes.txt
        seen_routes = set()
        try:
            with open(os.path.join(dir_path, 'routes.txt'), 'r', encoding='utf-8') as f:
                content = f.read()
                routes = GTFSParser.parse_routes_csv(content)
                for r in routes:
                    if r.route_id in seen_routes:
                        report['duplicates_detected'] += 1
                        report['warnings'].append(f"Duplicate route_id '{r.route_id}' in routes.txt")
                    seen_routes.add(r.route_id)
                    gtfs_repository.routes[r.route_id] = r
                    gtfs_repository.routes[r.route_short_name] = r
                report['routes_loaded'] = len(seen_routes)
                report['record_counts']['routes'] = len(seen_routes)
        except Exception as e:
            report['errors'].append(f'Failed parsing routes.txt: {e}')

        # 3. Parse and validate stops.txt
        seen_stops = set()
        try:
            with open(os.path.join(dir_path, 'stops.txt'), 'r', encoding='utf-8') as f:
                content = f.read()
                stops = GTFSParser.parse_stops_csv(content)
                for s in stops:
                    if s.stop_id in seen_stops:
                        report['duplicates_detected'] += 1
                        report['warnings'].append(f"Duplicate stop_id '{s.stop_id}' in stops.txt")
                    seen_stops.add(s.stop_id)
                    # Geographic boundary sanity check
                    if not (cls.MIN_LAT <= s.stop_lat <= cls.MAX_LAT and cls.MIN_LON <= s.stop_lon <= cls.MAX_LON):
                        report['warnings'].append(
                            f"Stop '{s.stop_id}' ({s.stop_name}) has coordinates ({s.stop_lat}, {s.stop_lon}) "
                            f"outside Bengaluru regional bounding box."
                        )
                    gtfs_repository.stops[s.stop_id] = s
                report['stops_loaded'] = len(seen_stops)
                report['record_counts']['stops'] = len(seen_stops)
        except Exception as e:
            report['errors'].append(f'Failed parsing stops.txt: {e}')

        # 4. Parse and validate trips.txt
        seen_trips = set()
        try:
            with open(os.path.join(dir_path, 'trips.txt'), 'r', encoding='utf-8') as f:
                content = f.read()
                trips = GTFSParser.parse_trips_csv(content)
                for t in trips:
                    if t.trip_id in seen_trips:
                        report['duplicates_detected'] += 1
                        report['warnings'].append(f"Duplicate trip_id '{t.trip_id}' in trips.txt")
                    seen_trips.add(t.trip_id)
                    # Relationship validation: trip -> route
                    if t.route_id and t.route_id not in gtfs_repository.routes:
                        report['relationship_errors'] += 1
                        report['warnings'].append(f"Trip '{t.trip_id}' references unknown route_id '{t.route_id}'")
                    gtfs_repository.trips[t.trip_id] = t
                report['trips_loaded'] = len(seen_trips)
                report['record_counts']['trips'] = len(seen_trips)
        except Exception as e:
            report['errors'].append(f'Failed parsing trips.txt: {e}')

        # 5. Parse and validate stop_times.txt
        try:
            with open(os.path.join(dir_path, 'stop_times.txt'), 'r', encoding='utf-8') as f:
                content = f.read()
                stop_times = GTFSParser.parse_stop_times_csv(content)
                for st in stop_times:
                    if not st.trip_id or not st.stop_id:
                        report['malformed_rows'] += 1
                        continue
                    # Relationship validation: stop_time -> trip, stop_time -> stop
                    if st.trip_id not in gtfs_repository.trips:
                        report['relationship_errors'] += 1
                    if st.stop_id not in gtfs_repository.stops:
                        report['relationship_errors'] += 1

                    gtfs_repository.stop_times.setdefault(st.trip_id, []).append(st)
                report['stop_times_loaded'] = len(stop_times)
                report['record_counts']['stop_times'] = len(stop_times)

                # Map route stops
                for trip_id, times in gtfs_repository.stop_times.items():
                    trip = gtfs_repository.trips.get(trip_id)
                    if trip and trip.route_id:
                        sorted_st = sorted(times, key=lambda x: x.stop_sequence)
                        gtfs_repository.route_stops[trip.route_id] = [st.stop_id for st in sorted_st]
        except Exception as e:
            report['errors'].append(f'Failed parsing stop_times.txt: {e}')

        # 6. Parse and validate shapes.txt (Optional)
        shapes_fp = os.path.join(dir_path, 'shapes.txt')
        if os.path.isfile(shapes_fp):
            try:
                with open(shapes_fp, 'r', encoding='utf-8') as f:
                    shape_pts = GTFSParser.parse_shapes_csv(f.read())
                    shape_ids = set()
                    for pt in shape_pts:
                        shape_ids.add(pt.shape_id)
                        # Shape coordinate bounding box sanity check
                        if not (cls.MIN_LAT <= pt.shape_pt_lat <= cls.MAX_LAT and cls.MIN_LON <= pt.shape_pt_lon <= cls.MAX_LON):
                            report['warnings'].append(
                                f"Shape point {pt.shape_id} seq {pt.shape_pt_sequence} coords "
                                f"({pt.shape_pt_lat}, {pt.shape_pt_lon}) outside Bengaluru regional box."
                            )
                        gtfs_repository.shapes.setdefault(pt.shape_id, []).append(pt)
                    report['shape_points_loaded'] = len(shape_pts)
                    report['record_counts']['shapes'] = len(shape_ids)
            except Exception as e:
                report['warnings'].append(f'Could not parse shapes.txt: {e}')
        else:
            report['warnings'].append('shapes.txt not found. Map will use stop-to-stop waypoints.')

        report['success'] = len(report['errors']) == 0
        return report

    @classmethod
    def startup_import(cls) -> Optional[Dict[str, Any]]:
        """Optionally imports static GTFS dataset on application startup if GTFS_STATIC_DIR is set."""
        from ...core.config import settings
        if settings.gtfs_static_dir and os.path.isdir(settings.gtfs_static_dir):
            import logging
            log = logging.getLogger("nammablr.gtfs_importer")
            log.info("[STARTUP] Ingesting static GTFS dataset from %s", settings.gtfs_static_dir)
            return cls.import_directory(settings.gtfs_static_dir)
        return None


def main():
    parser = argparse.ArgumentParser(description='Ingest official GTFS Static dataset into NammaBlr')
    parser.add_argument('directory', help='Path to folder containing routes.txt, stops.txt, etc.')
    args = parser.parse_args()

    print(f'[NAMMABLR] Ingesting GTFS Static directory: {args.directory}')
    res = GTFSStaticImporter.import_directory(args.directory)

    print("\n================ INGESTION SUMMARY ================")
    print(f"Status:               {'SUCCESS' if res['success'] else 'FAILED'}")
    print(f"Routes loaded:        {res['routes_loaded']}")
    print(f"Stops loaded:         {res['stops_loaded']}")
    print(f"Trips loaded:         {res['trips_loaded']}")
    print(f"Stop times loaded:    {res['stop_times_loaded']}")
    print(f"Shape points loaded:  {res['shape_points_loaded']}")
    if res["warnings"]:
        print("\nWarnings:")
        for w in res["warnings"]:
            print(f"  [!] {w}")
    if res["errors"]:
        print("\nErrors:")
        for err in res["errors"]:
            print(f"  [x] {err}")
    print("===================================================\n")

    if not res['success']:
        sys.exit(1)


if __name__ == '__main__':
    main()
