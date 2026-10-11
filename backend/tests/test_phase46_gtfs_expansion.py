import csv
import os
import tempfile
import time
import unittest
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.services.gtfs.repository import GTFSRepository, gtfs_repository

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "gtfs_test_feed")


def _restore_default_repo():
    gtfs_repository.clear()
    gtfs_repository.init_default_bengaluru_catalog()


class TestPhase46GTFSExpansion(unittest.TestCase):
    """Master spec Phase 46: dynamic GTFS static ingestion (synthetic fixture feed, not BMTC data)."""

    def setUp(self):
        self.repo = GTFSRepository()
        self.assertTrue(self.repo.load_from_directory(FIXTURE))

    def tearDown(self):
        _restore_default_repo()

    def test_loads_all_files_and_skips_malformed_rows(self):
        stats = self.repo.get_stats()
        self.assertEqual(stats["routes"], 2)
        self.assertEqual(stats["stops"], 3)  # "Broken Stop" skipped
        self.assertEqual(stats["trips"], 3)
        self.assertEqual(stats["stop_times"], 5)  # malformed row skipped
        self.assertEqual(stats["calendars"], 2)
        self.assertEqual(stats["calendar_dates"], 2)
        self.assertEqual(self.repo.data_source, "GTFS_STATIC")
        self.assertEqual(self.repo.last_load_report["malformed_rows"]["stops.txt"], 1)
        self.assertEqual(self.repo.last_load_report["malformed_rows"]["stop_times.txt"], 1)
        # BOM on routes.txt header is handled
        self.assertIsNotNone(self.repo.get_route("R1"))

    def test_route_and_stop_indexes(self):
        self.assertEqual(self.repo.get_route("T-100").route_id, "R1")
        self.assertEqual([s.stop_id for s in self.repo.get_stops_for_route("R1")], ["S1", "S2"])  # longest trip
        self.assertEqual(sorted(t.trip_id for t in self.repo.get_trips_for_route("T-100")), ["TR1", "TR2"])
        self.assertEqual(sorted(r.route_id for r in self.repo.get_routes_for_stop("S2")), ["R1", "R2"])
        self.assertEqual([p.shape_pt_sequence for p in self.repo.get_shape_for_route("R1")], [1, 2])
        self.assertEqual(self.repo.search_routes("t-2")[0].route_id, "R2")
        self.assertEqual(self.repo.search_stops("market")[0].stop_id, "S3")

    def test_service_calendar_semantics(self):
        monday = date(2026, 1, 19)
        saturday = date(2026, 1, 24)
        holiday_monday = date(2026, 1, 26)
        self.assertEqual(self.repo.get_active_service_ids(monday), ["WK"])
        self.assertEqual(self.repo.get_active_service_ids(saturday), ["WE"])
        self.assertEqual(self.repo.get_active_service_ids(holiday_monday), ["WE"])  # calendar_dates override
        self.assertEqual(self.repo.get_active_service_ids(date(2027, 1, 4)), [])

    def test_endpoints_serve_loaded_feed(self):
        gtfs_repository.clear()
        gtfs_repository.load_from_directory(FIXTURE)
        client = TestClient(app)
        status = client.get("/api/gtfs/status").json()
        self.assertEqual(status["data_source"], "GTFS_STATIC")
        self.assertFalse(status["is_realtime"])
        self.assertEqual(client.get("/api/gtfs/routes?q=T-1").json()["routes"][0]["route_id"], "R1")
        self.assertEqual(len(client.get("/api/gtfs/routes/R1/stops").json()["stops"]), 2)
        self.assertEqual(len(client.get("/api/gtfs/routes/T-100/trips").json()["trips"]), 2)
        self.assertEqual(len(client.get("/api/gtfs/routes/R1/shape").json()["points"]), 2)
        self.assertEqual(len(client.get("/api/gtfs/stops/S2/routes").json()["routes"]), 2)
        self.assertEqual(client.get("/api/gtfs/services?date=2026-01-26").json()["active_service_ids"], ["WE"])
        self.assertEqual(client.get("/api/gtfs/routes/NOPE/stops").status_code, 404)
        self.assertEqual(client.get("/api/gtfs/services?date=bad").status_code, 422)

    def test_default_catalog_is_labelled_demo(self):
        _restore_default_repo()
        client = TestClient(app)
        body = client.get("/api/gtfs/routes").json()
        self.assertEqual(body["data_source"], "DEMO_CATALOG")
        self.assertIn("500D", [r["route_short_name"] for r in body["routes"]])
        self.assertIn("500D", [r["route_short_name"] for r in client.get("/api/gtfs/stops/stop-silk-board/routes").json()["routes"]])

    def test_large_synthetic_feed_performance(self):
        """Phase 49: 2,500 routes / 25,000 trips / 250,000 stop_times load well under a time budget."""
        with tempfile.TemporaryDirectory() as d:
            def write(name, header, rows):
                with open(os.path.join(d, name), "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(header)
                    w.writerows(rows)
            write("routes.txt", ["route_id", "route_short_name", "route_long_name", "route_type"],
                  ([f"R{i}", f"{i}", f"Synthetic {i}", 3] for i in range(2500)))
            write("stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon"],
                  ([f"S{i}", f"Stop {i}", 12.9 + i * 1e-5, 77.5 + i * 1e-5] for i in range(5000)))
            write("trips.txt", ["trip_id", "route_id", "service_id"],
                  ([f"T{i}", f"R{i % 2500}", "WK"] for i in range(25000)))
            write("stop_times.txt", ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
                  ([f"T{i // 10}", "08:00:00", "08:00:00", f"S{(i * 7) % 5000}", i % 10] for i in range(250000)))
            repo = GTFSRepository()
            t0 = time.perf_counter()
            self.assertTrue(repo.load_from_directory(d))
            elapsed = time.perf_counter() - t0
        self.assertEqual(repo.get_stats()["routes"], 2500)
        self.assertEqual(repo.get_stats()["stop_times"], 250000)
        self.assertLess(elapsed, 20.0, f"GTFS load took {elapsed:.2f}s")
        t0 = time.perf_counter()
        for i in range(0, 2500, 25):
            repo.get_stops_for_route(f"R{i}")
            repo.get_trips_for_route(f"R{i}")
        self.assertLess(time.perf_counter() - t0, 1.0)


if __name__ == "__main__":
    unittest.main()
