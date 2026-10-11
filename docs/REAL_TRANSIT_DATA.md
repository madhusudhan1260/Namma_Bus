# Real Transit Data Integration Specification — NammaBlr

This document details the architectural foundation, schema requirements, and protocol specifications necessary to connect **NammaBlr** to an official/authorized Bengaluru Metropolitan Transport Corporation (BMTC) transit data source, General Transit Feed Specification (GTFS), or municipal Intelligent Transportation System (ITS) platform.

---

## 1. Ethical & Compliance Notice

> [!IMPORTANT]
> **Operational Status Statement**:
> `REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED`
>
> **Strict Policy Against Scraping or Reverse-Engineering**:
> - NammaBlr does **NOT** scrape the Namma BMTC mobile app, web portals, or private backend APIs.
> - NammaBlr does **NOT** reverse-engineer undocumented endpoints or bypass authentication mechanisms.
> - Current live demonstrations operate on a verified Bengaluru corridor simulation (`MockTransitDataProvider`).
> - Future integration must strictly utilize official open-data portals, authorized GTFS/GTFS-RT public endpoints, or formal institutional API partnerships.
> - No claims are made that BMTC currently provides any specific real-time or passenger-count feed unless independently verified and officially authorized.

---

## 2. Transit Data Categorization

NammaBlr categorizes transit data into three functional tiers. Each tier supports specific features of the passenger experience:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. STATIC TRANSIT DATA (Schedule & Infrastructure)           │
│    • GTFS Static (routes.txt, stops.txt, stop_times.txt)    │
├─────────────────────────────────────────────────────────────┤
│ 2. REAL-TIME TELEMETRY (Live Operations)                    │
│    • GTFS-Realtime (VehiclePositions, TripUpdates, Alerts)  │
├─────────────────────────────────────────────────────────────┤
│ 3. OCCUPANCY & PASSENGER-FLOW DATA (Crowd Intelligence)      │
│    • Automated Passenger Counting (APC) / Ticketing Feeds   │
└─────────────────────────────────────────────────────────────┘
```

---

### A. Static Transit Data (GTFS Static)

Static data defines the fixed network topology and timetable. It rarely changes more than a few times per year.

| Entity | Required Fields | Purpose in NammaBlr |
|---|---|---|
| **Routes** | `route_id`, `route_short_name` (e.g. `500D`), `route_long_name`, `route_type` | Journey search, route filtering, AC vs Ordinary designation |
| **Stops** | `stop_id`, `stop_name`, `stop_lat`, `stop_lon`, `zone_id` | Map bus stop markers, distance computation, nearby stops discovery |
| **Trips & Sequences** | `trip_id`, `route_id`, `service_id`, `shape_id`, `direction_id` | Polyline generation, stop order, direction determination |
| **Stop Times** | `trip_id`, `stop_id`, `stop_sequence`, `arrival_time`, `departure_time` | Scheduled journey durations, corridor matching |
| **Shapes** | `shape_id`, `shape_pt_lat`, `shape_pt_lon`, `shape_pt_sequence` | Map polylines connecting stops along actual Bengaluru road curves |

**Features powered by Static Data**:
- Route directory and line listings (500D, 356, 201R, KIA-8, G-2).
- Bus stop geographic discovery and radius searches.
- Origin-Destination trip search matching.
- Scheduled travel duration baselines.

---

### B. Real-Time Transit Data (GTFS-Realtime)

Real-time feeds publish high-frequency vehicle telemetry and operational adjustments (typically updated every 5–30 seconds via Protocol Buffers or JSON REST).

#### 1. VehiclePositions (`VehiclePosition`)
| Field | Type | Description |
|---|---|---|
| `vehicle.id` | String | Unique hardware/fleet identifier (e.g. `KA-01-F-4819`) |
| `trip.trip_id` | String | Active scheduled trip association |
| `trip.route_id` | String | Route code (`500D`) |
| `position.latitude` | Float | Current WGS-84 latitude |
| `position.longitude` | Float | Current WGS-84 longitude |
| `position.bearing` | Float | Vehicle heading in degrees ($0^\circ - 360^\circ$) |
| `position.speed` | Float | Current ground speed in m/s or km/h |
| `timestamp` | Integer | POSIX epoch seconds of telemetry capture |
| `current_stop_sequence`| Integer | Sequence index of current or next stop |

**Features powered by VehiclePositions**:
- Moving bus markers on the native interactive map (`react-native-maps`).
- Bus-following camera tracking (`isFollowingBus`).
- Real-time vehicle speed display.
- Dynamic ETAs based on actual vehicle velocity and haversine distance.

#### 2. TripUpdates (`TripUpdate`)
| Field | Type | Description |
|---|---|---|
| `trip.trip_id` | String | Active trip being updated |
| `stop_time_update.stop_id` | String | Target stop identifier |
| `stop_time_update.arrival.delay` | Integer | Delay in seconds relative to schedule |
| `stop_time_update.arrival.time` | Integer | Estimated arrival epoch timestamp |

**Features powered by TripUpdates**:
- Corridor congestion delays and traffic status.
- Next-stop ETAs in Home search comparison cards and AI Assistant grounded answers.

#### 3. ServiceAlerts (`Alert`)
- Route diversions, strikes, corridor maintenance, or weather disruptions.

---

### C. Occupancy & Passenger-Flow Data

Real-time crowd intelligence requires sensor or ticketing infrastructure data.

| Data Element | Required Source | Description |
|---|---|---|
| **Passenger Count** | Automated Passenger Counting (APC) infra | Infrared or optical overhead doorway sensors counting boardings & alightings |
| **Available Seats** | APC + Vehicle Seating Manifest | Computed as $\max(0, \text{Seating Capacity} - \text{Current Passengers})$ |
| **Crowd Level / Tier** | Sensor / Ticketing telemetry | `Comfortable` ($<50\%$), `Moderate` ($50-74\%$), `Crowded` ($75-89\%$), `Very Crowded` ($\ge 90\%$) |
| **Historical Boarding Flow** | Electronic Ticketing Machines (ETM) logs | Historical tap-in / ticket issue timestamps grouped by stop and hour |

> [!WARNING]
> **Limitations Without Live APC Feeds**:
> - GTFS-Realtime feeds often omit passenger-load metrics unless the transit agency has equipped fleet doors with optical APC hardware and enabled the `VehiclePosition.occupancy_status` enum.
> - **Seat vacancy and upcoming stop crowd predictions CANNOT be verified in real time without APC or live ETM ticketing validation streams.**
> - When operating without live APC feeds, NammaBlr uses deterministic simulated passenger-flow models and explicitly discloses:
>   *"Prediction only — actual passenger levels may vary. Estimated based on simulated historical boarding patterns."*

---

## 3. Provider Architecture & Connecting Real Data
 
 NammaBlr abstracts all transit telemetry behind the `TransitDataProvider` interface:
 
 ```
                      FastAPI Application
                              │
                     get_transit_provider()
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
    MockTransitDataProvider       BMTCTransitDataProvider
    (Bengaluru Simulator)         (Authorized External Source)
               │                             │
    [Corridor Interpolation]      [Official GTFS-RT Endpoint]
               │                             │
               └──────────────┬──────────────┘
                              ▼
                   Standard Transit Models
             (Bus, BusLocation, BusStop, Occupancy)
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
           ETAService   OccupancyService  AIService
 ```

### Implemented Phase 19 Architecture Components:
- **`RealtimeActivationService`** (`backend/app/services/realtime_activation_service.py`):
  Executes an 8-stage verification pipeline (`Configuration -> Endpoint Validation -> Credential Check -> Network Connection -> Payload Parsing -> GTFS-RT Entity Bounds Check -> Freshness Calculation -> Realtime Activation`).
- **Dry-Run Validation Endpoint** (`POST /api/realtime/validate`):
  Safe, non-destructive audit endpoint that validates live endpoint reachability, credentials, and entity quality without modifying active runtime providers or leaking secrets.
- **GTFS Parser & Quality Pipeline** (`backend/app/services/gtfs/parser.py`):
  Parses GTFS-RT entities with individual error isolation (`valid_entities`, `invalid_entities`, `ignored_entities`). Rejects corrupt entities individually without failing the entire feed.
- **`BMTCTransitDataProvider`** (`backend/app/services/bmtc_provider.py`):
  Production-grade adapter with background polling task (`asyncio`), in-memory snapshot cache, thread-safe updates, exponential backoff, and stale-feed detection.
- **APC Honesty Engine**:
  When GTFS-RT feeds do not supply automated passenger count data, occupancy is explicitly reported as unavailable with: `"Passenger occupancy data is unavailable from the current feed."` No fake seat counts are fabricated.
- **GTFS Normalizer** (`backend/app/services/gtfs/normalizer.py`):
  Normalizes external GTFS entities to internal application models (`Bus`, `BusLocation`, `Route`, `BusStop`, `Occupancy`, `ETAEstimate`).
- **GTFS Repository** (`backend/app/services/gtfs/repository.py`):
  Thread-safe in-memory store for static transit data with arterial corridor baseline catalog.
- **Safety & Fallback Engine** (`backend/app/services/provider_factory.py`):
  Gracefully falls back to `MockTransitDataProvider` when real feed credentials are unconfigured or failing, avoiding any crashes or empty screens.

- **Google Maps & Realtime Transit Experience (Phase 20)**:
  - Full support for `PROVIDER_GOOGLE` on Android with fallback to native platform engines.
  - Fail-safe map lifecycle with `"Map service unavailable"` view upon key or initialization errors.
  - VehiclePosition normalization of bearing, velocity, and timestamp telemetry into `Bus` and `BusLocation`.
  - Dynamic ETA source identification: `"Official Trip Update"` (GTFS-RT `TripUpdate`) vs `"Calculated Estimate"` (geometric model).
  - Corridor Service Alerts on Map inspection sheets.
  - Transparent lost bus indication in follow mode: `"Bus location temporarily unavailable"`.

- **Authorized BMTC Data Activation & Production Feed Management (Phase 21)**:
  - Centralized feed configuration validation (`mock_mode`, `bmtc_incomplete`, `bmtc_invalid_urls`, `bmtc_configured_valid`).
  - Deterministic feed activation state machine with jittered exponential backoff (up to 60s cap).
  - Telemetry coordinate bounding box enforcement (`[12.0, 14.0]` lat / `[76.5, 78.5]` lon) with entity deduplication.
  - Static GTFS validation reporting identifying orphan trips/stops and labeled as `"Scheduled Data"`.
  - Strict service alert separation (`gtfs_rt` vs `demo`).
  - Credential-safe probe endpoint: `GET /api/realtime/test`.
  - Frontend interactive diagnostic card with live dry-run validation and probe verification.

### Steps to Connect an Authorized Live Source:
 
 1. **Obtain Official Credentials**:
    Acquire authorized API access tokens or GTFS-RT feed URLs from BMTC / Bangalore Smart City / Open City data initiatives.
 2. **Dry-Run Validate Prospective Feed**:
    Use the dry-run validation endpoint or More -> System Status -> Realtime Integration:
    ```bash
    curl -X POST http://localhost:8001/api/realtime/validate \
      -H "Content-Type: application/json" \
      -d '{"endpoint": "https://authorized-api.bmtc.gov.in/gtfs-rt", "api_key": "your-token"}'
    ```
 3. **Configure Environment Variables in Production**:
    ```bash
    export ENVIRONMENT="production"
    export TRANSIT_PROVIDER="bmtc"
    export BMTC_API_ENDPOINT="https://authorized-api.bmtc.gov.in/gtfs-rt"
    export BMTC_API_KEY="your-authorized-secret-token"
    export REALTIME_POLL_INTERVAL_SECONDS="10.0"
    export REALTIME_STALE_THRESHOLD_SECONDS="60.0"
    export GOOGLE_MAPS_API_KEY_ANDROID="your-android-google-maps-key"
    export GOOGLE_MAPS_API_KEY_IOS="your-ios-google-maps-key"
    ```
 4. **Live Polling & Ingestion**:
    Upon startup with valid credentials, `BMTCTransitDataProvider` immediately initiates its background polling loop, fetching live vehicle positions and trip updates while retaining the last-known-good snapshot if temporary network blips occur.
 5. **Zero Frontend Modifications Required**:
    Because `BMTCTransitDataProvider` implements the unified `TransitDataProvider` interface and returns standard models, the mobile React Native client immediately presents live vehicles with 0 lines of frontend changes.
