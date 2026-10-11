# NammaBlr - Backend Transit Intelligence API

Python + FastAPI backend providing real-time transit telemetry, ETA calculations, passenger crowd estimation, and journey search for BMTC bus routes across Bengaluru.

---

## Architecture & Sourcing Philosophy

To adhere to responsible development and hackathon integrity guidelines:
- **No private BMTC endpoints are scraped or reverse-engineered.**
- A simulated telemetry provider (`MockTransitDataProvider`) models realistic movement along authentic Bengaluru road corridors (Outer Ring Road, Hosur Road, etc.) with dynamic GPS updates, speed fluctuations, and passenger turnover.
- The service adheres to an abstract contract (`TransitDataProvider`). When authorized access to official BMTC open data, GTFS-RT, or municipal ITS APIs becomes available, a new `BMTCTransitDataProvider` can be plugged in without changing the REST API contracts or frontend code.

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app initialization, CORS, lifespan simulation loop
│   ├── core/
│   │   └── config.py        # Configuration tokens, simulation tick settings
│   ├── models/
│   │   └── transit.py       # Pydantic data models for Bus, Route, Stop, Occupancy, Journey
│   ├── services/
│   │   ├── provider.py      # TransitDataProvider abstract base class
│   │   ├── mock_provider.py # Simulated telemetry engine with corridor waypoints
│   │   ├── eta_service.py   # Haversine distance, speed, and dwell-time ETA engine
│   │   ├── occupancy_service.py # Capacity and available seat analytics
│   │   └── journey_service.py   # Origin-destination corridor search matching
│   └── api/
│       └── routes.py        # REST endpoints under /api/*
├── requirements.txt
└── README.md
```

---

## Installation & Running

### 1. Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Start the Backend Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

- **Interactive Swagger Documentation**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **ReDoc Documentation**: [http://localhost:8001/redoc](http://localhost:8001/redoc)
- **Health Check**: [http://localhost:8001/api/health](http://localhost:8001/api/health)

---

## REST API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness probe returning process health |
| `GET` | `/api/ready` | Readiness probe verifying data serving capability |
| `GET` | `/api/status` | System status, subsystem diagnostics, feed health |
| `GET` | `/api/system/status` | Comprehensive observability, p95 latencies, feed health |
| `POST`| `/api/realtime/validate` | Dry-run validation of GTFS-RT feeds (credential-safe) |
| `GET` | `/api/alerts` | Active corridor alerts with route & stop filtering |
| `GET` | `/api/buses` | All active buses with live coordinates & occupancy |
| `GET` | `/api/buses/{bus_id}` | Detailed telemetry and route for a specific bus |
| `GET` | `/api/buses/{bus_id}/location` | Live GPS coordinates, speed, and heading |
| `GET` | `/api/buses/{bus_id}/route` | Route name, source, destination, and stop list |
| `GET` | `/api/buses/{bus_id}/stops` | Ordered list of stops along the route |
| `GET` | `/api/buses/{bus_id}/eta` | Dynamic ETA to a target stop |
| `GET` | `/api/buses/{bus_id}/occupancy` | Real-time passenger count, seat availability, % |
| `GET` | `/api/crowd/bus/{bus_id}` | Predictive passenger crowd forecast for a bus |
| `POST`| `/api/journey/search` | Match routes for origin and destination (Rate limited) |
| `POST`| `/api/journey/recommend` | Deterministic multi-category journey recommendation |
| `POST`| `/api/ai/chat` | Grounded AI queries with data-mode awareness (Rate limited) |
| `POST`| `/api/tickets` | Issue prototype commuter ticket (Rate limited) |
| `GET` | `/api/tickets/history` | Retrieve history of created demo tickets |
| `GET` | `/api/tickets/stats` | Conductor scanning validation tallies and stats |
| `POST`| `/api/tickets/verify` | Verify pass validity for Conductor mode |
| `POST`| `/api/tickets/{ticket_id}/use` | Mark ticket as used during inspection |
| `POST`| `/api/demo/reset` | Restore baseline telemetry and demo state |
| `GET` | `/api/stops/nearby` | Geographic radius search for nearby bus stops |

---

## OpenAPI Tag Grouping (Phase 19-21)

All endpoints are organized into 10 structured OpenAPI tags:
- **Transit**: `/buses`, `/buses/{id}`, `/routes`, `/stops`, `/stops/nearby`, `/eta/...`
- **Journey**: `/journey/search`, `/journey/recommend`
- **AI**: `/ai/chat`
- **Tickets**: `/tickets`, `/tickets/history`, `/tickets/{id}`
- **Conductor**: `/tickets/verify`, `/tickets/{id}/use`, `/tickets/stats`
- **Crowd**: `/buses/{id}/crowd-prediction`, `/crowd/bus/{id}`
- **Alerts**: `/alerts`, `/notifications/events`
- **Realtime**: `POST /realtime/validate`, `GET /realtime/test`
- **Diagnostics**: `/status`, `/system/status`, `/demo/reset`
- **Health**: `/health`, `/ready`

---

## Transit Provider Configuration & Real Data Readiness

The active provider is resolved dynamically via `app.services.provider_factory`:

- `TRANSIT_PROVIDER=mock` (default): Runs high-fidelity simulated telemetry along Bengaluru corridors.
- `TRANSIT_PROVIDER=bmtc`: Targets official BMTC / GTFS-RT APIs via `BMTCTransitDataProvider`.

### Safe Fallback:
If `TRANSIT_PROVIDER=bmtc` is selected without authorized credentials configured (`BMTC_API_ENDPOINT`, `BMTC_API_KEY`):
- The system logs: `TRANSIT_PROVIDER is configured as 'bmtc', but REAL BMTC DATA SOURCE NOT CONFIGURED. Automatically falling back to MockTransitDataProvider.`
- Serves simulated data without crashing.
- `/api/health` honestly reports `data_mode: "simulated"` and `realtime: false`.
- Readiness probe `/api/ready` remains healthy.

### Authorized Realtime Feed & Commuter Intelligence (Phases 21–31)
- `diagnostic_state` validation (`mock_mode`, `bmtc_incomplete`, `bmtc_invalid_urls`, `bmtc_configured_valid`).
- Deterministic feed activation state machine with jittered exponential backoff (up to 60s).
- Coordinate bounds validation (`[12.0, 14.0]` lat / `[76.5, 78.5]` lon) and entity deduplication.
- Credential-safe probe endpoint: `GET /api/realtime/test`.
- Official TripUpdate ETA attribution (`gtfs_rt_trip_update`) vs geometric fallback (`geometric_estimate`).
- Static GTFS validation report distinguishing `Scheduled Data` from live feeds.
- Expanded 17-module System Status observability with p95 latency tracking (`GET /api/system/status`).
- Tamper-evident HMAC-SHA256 digital ticketing and conductor duplicate scan prevention.
### Active Journey Assistant & Commuter Intelligence (Phases 31–32)
- End-to-end Active Journey state machine: `GET /api/journey/active`, `POST /api/journey/active`, `PATCH /api/journey/active`, `POST /api/journey/active/end`, `GET /api/journey/history`.
- Smart Live Trip View with `following_stop` and `distance_to_next_stop_km`.
- Multi-leg Walking + Transit Journey Planning (`walk_to_stop`, `bus_ride`, `walk_from_stop`).
- Grounded AI trip context answering (`stops_remaining`, `destination_eta`, `bus_location`).
- Disruption-aware journey options cross-referencing active corridor advisories.
- Shakti Scheme ₹0 demo concession pass linking with explicit demo ticket disclaimer.
- Production metrics tracking: `active_journey_started`, `active_journey_completed`, `journey_cancelled`, `journey_state_transitions`, `journey_history_views`.

### Smart Trip Safety & Arrival Intelligence (Phase 33)
- Stop-by-stop destination progression, countdown calculations, and remaining distance tracking.
- Proactive destination arrival state machine: `DESTINATION_APPROACHING`, `GET_READY_TO_EXIT`, `DESTINATION_REACHED`, and `DESTINATION_PASSED`.
- "Get Ready to Exit" municipal warning card with explicit exit countdown and preparation steps.
- Missed destination detection with safe commuter recovery actions (`[ View Route ]`, `[ Continue Tracking ]`, `[ End Journey ]`).
- Offline journey safety retaining last-known telemetry with prominent transparency disclaimer `"OFFLINE — SHOWING LAST KNOWN DATA"`.
- Milestone notification deduplication preventing redundant alert delivery.
- Observability metrics for Phase 33 exposed in `GET /api/system/status`.

---

## Running the Automated Test Suite

```bash
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p "test_*.py" -v
```

**Test Coverage**: **271/271 tests passing (100%)** across 24 test suites:
- `test_phase33_arrival_intelligence.py` (16 tests)
- `test_phase32_active_journey.py` (10 tests)
- `test_phase31_commuter_intelligence.py` (9 tests)
- `test_phase30_production_observability.py` (3 tests)
- `test_phase29_ticketing_trust.py` (5 tests)
- `test_phase28_assistant_personalization.py` (7 tests)
- `test_phase27_realtime_resilience.py` (14 tests)
- `test_phase26_map_journey.py` (5 tests)
- `test_phase25_personalization.py` (6 tests)
- `test_phase21_production_feed.py` (30 tests)
- `test_phase20_google_maps_realtime.py` (14 tests)
- `test_phase19_production.py` (18 tests)
- `test_phase18_realtime_readiness.py` (7 tests)
- `test_phase17_commuter_intelligence.py` (9 tests)
- `test_phase16_production.py` (12 tests)
- `test_phase15_production.py` (10 tests)
- `test_phase14_production.py` (15 tests)
- `test_bmtc_realtime.py` (15 tests)
- `test_identity_verification.py` (12 tests)
- `test_ai_service.py` (9 tests)
- `test_crowd_prediction.py` (10 tests)
- `test_provider.py` (8 tests)
- `test_tickets.py` (8 tests)
- `test_system_status.py` (2 tests)



