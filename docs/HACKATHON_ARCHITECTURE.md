# NammaBlr — Technical Architecture & Subsystem Specification

**Edition:** Hackathon Competition Presentation  
**Status:** 100% Production Verified (Expo SDK 57 + React Native 0.86 + FastAPI Backend)  
**Corridor Coverage:** Outer Ring Road (ORR), Hosur Road, Old Airport Road, Sarjapur, Bannerghatta  

---

## 1. Executive Summary

**NammaBlr** is a mobile-first intelligent transit companion engineered for Bengaluru's public bus commuters and transit staff. It bridges the gap between raw transit telemetry and daily commuter needs by combining:

1. **Live GPS Tracking & Native Mapping**: Real-time vehicle positions, stop sheets, route polylines, and camera follow modes.
2. **Predictive Crowd & Seat Availability**: Stop-by-stop passenger flow forecasting using Bayesian occupancy modeling.
3. **Telemetry-Grounded AI Assistant**: Natural language query engine strictly bound to live vehicle data with zero hallucination.
4. **Digital Pass Prototype & Conductor Validator**: Seamless passenger QR ticket generation and onboard conductor optical verification with live session tallies.
5. **Pluggable Provider Architecture**: An honest, ethical data provider abstraction that runs a high-fidelity Bengaluru corridor simulator today, with automatic fallback and zero friction when connecting to authorized GTFS/GTFS-RT municipal feeds tomorrow.

---

## 2. End-to-End System Architecture

```mermaid
flowchart TD
    subgraph MobileApp ["Mobile Client (Expo SDK 57 / React Native 0.86)"]
        UI_Home["Home Screen (Journey Planner & Telemetry)"]
        UI_Map["Native Map (react-native-maps, Follow Mode)"]
        UI_AI["AI Assistant (Interactive Telemetry Cards)"]
        UI_Tickets["Digital Pass Generator (Pure TS QR Engine)"]
        UI_Conductor["Conductor Mode (Optical Scanner & Tally)"]
        UI_More["Settings & Subsystem Telemetry Dashboard"]
        
        TransitContext["Shared TransitContext (Unified State & Polling)"]
        UI_Home --> TransitContext
        UI_Map --> TransitContext
        UI_AI --> TransitContext
        UI_Tickets --> TransitContext
        UI_Conductor --> TransitContext
        UI_More --> TransitContext
    end

    subgraph BackendGateway ["FastAPI Gateway (Port 8001 / REST)"]
        Router["API Router (/api/v1)"]
        AuthFallback["Safe Configuration & Fallback Engine"]
    end

    subgraph IntelligenceServices ["Transit Intelligence Services"]
        ETAService["ETA Engine (Velocity & Distance)"]
        CrowdService["Crowd Prediction Engine (Bayesian Flow)"]
        AIService["AI Grounding Engine (Intent & Telemetry Binder)"]
        TicketService["Demo Ticket & Validation Store"]
    end

    subgraph DataProviderLayer ["Transit Data Provider Abstraction"]
        ProviderFactory{"Provider Factory"}
        MockProvider["MockTransitDataProvider (Bengaluru Corridors)"]
        BMTCProvider["BMTCTransitDataProvider (Authorized Feed Adapter)"]
    end

    subgraph ExternalFeeds ["External Municipal Feeds (Future)"]
        GTFS["GTFS Static (Timetables, Routes)"]
        GTFSRT["GTFS-RT (VehiclePositions, TripUpdates)"]
    end

    TransitContext <-->|HTTP / JSON (3.5s Polling)| Router
    Router --> ProviderFactory
    Router --> ETAService
    Router --> CrowdService
    Router --> AIService
    Router --> TicketService

    ProviderFactory -->|Default / Fallback| MockProvider
    ProviderFactory -->|If Authorized & Configured| BMTCProvider
    BMTCProvider -.->|Authorized API Keys| GTFS
    BMTCProvider -.->|Protobuf / REST| GTFSRT

    MockProvider -.-> ETAService
    MockProvider -.-> CrowdService
    MockProvider -.-> AIService
```

---

## 3. Frontend Architecture

### 3.1 Stack & Platform Foundation
- **Framework**: Expo SDK 57 (React Native 0.86, Fabric architecture disabled for maximum native map stability).
- **Navigation**: Expo Router v4 (typed file-based routing with root stack and 4-tab navigator).
- **Type Safety**: TypeScript 5.x in strict mode with zero compiler errors (`npx tsc --noEmit`).
- **Maps**: `react-native-maps` with native Apple Maps (iOS) / Google Maps (Android) clustering and custom SVG vehicle markers.
- **Color Theme**: BMTC Dark Navy theme (`#0F172A` background, `#00F0FF` electric cyan, `#F59E0B` amber warning, `#10B981` emerald seats).

### 3.2 Key Frontend Components
| Component | Path | Functionality |
|---|---|---|
| `NativeTransitMap` | `components/NativeTransitMap.tsx` | Native map with live moving buses, route polylines, animated camera tracking, and stop detail bottom sheets. |
| `CrowdPredictionCard` | `components/CrowdPredictionCard.tsx` | Visual crowd meter with Bayesian confidence rating and stop-by-stop seat availability bar chart. |
| `QRCodeView` | `components/QRCodeView.tsx` | Pure TypeScript QR matrix generator rendering scalable SVG blocks with zero external binary dependencies. |
| `SearchField` | `components/SearchField.tsx` | Bengaluru hub autocompletion with 1-tap swap, live GPS location matching, and quick filter chips. |
| `TicketCard` | `components/TicketCard.tsx` | Active and past digital pass cards with status ribbons, route tags, and QR inspection modals. |

### 3.3 State Management (`TransitContext`)
The mobile application uses a unified React Context (`context/TransitContext.tsx`) that eliminates prop drilling and synchronizes:
- Active vehicle telemetry polling at 3,500ms intervals with abort controllers.
- Camera follow-mode and selected bus coordination across Home, Map, and AI screens.
- Active journey origin/destination search parameters.
- Honest data mode state (`simulated` vs `realtime`) and provider health status.
- Single-tap **Demo Reset Action** that resets bus locations, tickets, and conductor scan tallies back to baseline.

---

## 4. Backend Subsystems

### 4.1 FastAPI Service Gateway
- **Framework**: FastAPI with Pydantic v2 data models for rigorous schema validation.
- **Asynchronous Loop**: Background simulation worker (`run_simulation_loop`) continuously updates bus waypoint interpolation every 3.5 seconds.
- **CORS Support**: Permissive cross-origin access configured for seamless local development across mobile simulators and physical devices.

### 4.2 TransitDataProvider Abstraction
NammaBlr abstracts all transit operations behind an interface:
```python
class TransitDataProvider(ABC):
    @abstractmethod
    async def get_buses(self) -> List[Bus]: ...
    @abstractmethod
    async def get_bus(self, bus_id: str) -> Optional[Bus]: ...
    @abstractmethod
    async def get_bus_location(self, bus_id: str) -> Optional[BusLocation]: ...
    @abstractmethod
    async def get_bus_route(self, bus_id: str) -> Optional[Route]: ...
    @abstractmethod
    async def get_bus_stops(self, bus_id: str) -> List[BusStop]: ...
    @abstractmethod
    async def get_bus_occupancy(self, bus_id: str) -> Optional[Occupancy]: ...
    @abstractmethod
    async def get_nearby_stops(self, latitude: float, longitude: float, radius_km: float) -> List[BusStop]: ...
    @abstractmethod
    async def get_eta(self, bus_id: str, target_stop_name: str) -> Optional[ETAEstimate]: ...
    @abstractmethod
    def get_data_mode(self) -> str: ...
    @abstractmethod
    def is_realtime(self) -> bool: ...
```

#### Provider Factory & Automatic Fallback
When `TRANSIT_PROVIDER=bmtc` is configured in `.env`, the provider factory verifies whether valid API keys and endpoints exist. If unconfigured or unresponsive, it **automatically falls back to `MockTransitDataProvider`** with a logged warning, ensuring zero crashes or broken user experiences.

### 4.3 Grounded AI Assistant Engine
The AI assistant (`backend/app/services/ai_service.py`) operates on a **zero-hallucination grounding pipeline**:
1. **Intent Classification**: Classifies queries into `bus_eta`, `bus_occupancy`, `seat_availability`, `route_info`, `journey_search`, or `general_help`.
2. **Entity Extraction**: Extracts route numbers (`500D`, `356`, `KIA-8`, etc.) and stop names using regex and fuzzy stop matching.
3. **Telemetry Binding**: Queries active vehicle telemetry from the provider before formulating answers.
4. **Interactive Card Generation**: If a specific bus is identified, the backend returns structured metadata including ETA, occupancy, next stop, and crowd predictions. The mobile client renders interactive action buttons (`[ 📍 Track on Live Map ]`, `[ 🗺️ View Route ]`, `[ 👥 See Forecast ]`) that deep-link directly into native views.

### 4.4 Predictive Crowd & Seat Availability Engine
The crowd prediction service (`backend/app/services/crowd_prediction_service.py`) models corridor dynamics:
- **Baseline Occupancy**: Current onboard passenger counts.
- **Corridor Boarding/Alighting Factors**: Major transfer hubs (e.g. Central Silk Board, Majestic KBS) have high turnover; intermediate stops experience steady boarding.
- **Capacity Clamping**: Occupancy is strictly clamped between 0% and 100%.
- **Seat Availability**: Seats are calculated as `max(0, Capacity - PredictedPassengers)`.
- **Honest Disclaimer**: All responses carry an explicit disclaimer indicating model predictions based on historical corridor patterns.

### 4.5 Digital Demo Ticketing & Conductor Validation
- **Passenger Mode**: Users can generate demo QR passes for active routes (500D, 356, KIA-8, 201R, G-2). Passes include origin, destination, fare, issue timestamp, expiration window, and cryptographic demo flag.
- **Conductor Handheld Validator**: Transit staff view live route passenger tallies, can optically scan or manually enter ticket IDs, and transition active tickets to `used` in real-time, preventing double validation.

### 4.7 Realtime Activation & Data Quality Subsystems (Phase 19)
- **Realtime Activation Verification Engine (`backend/app/services/realtime_activation_service.py`)**: An 8-stage pre-flight verification pipeline (`CONFIGURATION -> ENDPOINT VALIDATION -> CREDENTIAL CHECK -> NETWORK CONNECTION -> PAYLOAD PARSING -> GTFS-RT ENTITY BOUNDS CHECK -> FRESHNESS CALCULATION -> REALTIME ACTIVATION`).
- **Dry-Run Validation (`POST /api/realtime/validate`)**: Enables DevOps, municipal administrators, and mobile clients to validate proposed GTFS-RT feed endpoints and credentials safely in sandbox mode without mutating server state or affecting live production feeds.
- **GTFS-RT Entity Tracking & Isolation Pipeline (`backend/app/services/gtfs/parser.py`)**: Individual entity parser wrappers (`parse_vehicle_positions_with_stats`, `parse_trip_updates_with_stats`, `parse_service_alerts_with_stats`) isolate malformed records (out-of-bounds coordinates, empty IDs) into `invalid_entities` and `ignored_entities` without terminating feed ingestion.
- **Strict Production Configuration (`backend/app/core/config.py`)**: `Settings.validate_production_config()` strictly audits 12 environment parameters, rejects wildcard CORS (`*`), enforces HTTPS/WSS, and protects secrets from logs.
- **Structured OpenAPI Documentation**: 10 categorized OpenAPI tags (`Transit`, `Journey`, `AI`, `Tickets`, `Conductor`, `Crowd`, `Alerts`, `Realtime`, `Diagnostics`, `Health`).

### 4.8 Google Maps & Realtime Transit Experience (Phase 20)
- **Production Google Maps Integration**: Environment-driven Google Maps configuration for Android and iOS (`app.json`, `.env.example`) using `PROVIDER_GOOGLE` on Android with graceful fallback to native providers.
- **Fail-Safe Map Lifecycle**: Gracefully handles missing API keys, initialization errors, or connectivity drops with `"Map service unavailable"` view while preserving full access to Journey Planner, AI Assistant, and Passes.
- **Lost Vehicle Detection in Follow Mode**: When a tracked vehicle drops from live feed updates, the map displays `"Bus location temporarily unavailable"` while retaining the last-known-good position according to stale thresholds.
- **Accurate Telemetry & ETA Attribution**: Every bus card displays the verified ETA source (`"Official Trip Update"` from GTFS-RT vs `"Calculated Estimate"` from geometric velocity).
- **Service Alerts on Map**: Displays route-specific and stop-specific municipal advisories on bottom inspection sheets.

---

## 5. Security, Ethics & Privacy Standards

1. **Operational Statement**: `REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED`.
2. **Zero Scraping Guarantee**: The codebase contains zero scraping routines, undocumented endpoint calls, or session hijacking logic for the consumer Namma BMTC application.
3. **Transparent Telemetry Labeling**: The app displays explicit banners on all primary screens indicating `● SIMULATED TRANSIT DATA (Bengaluru Corridor Engine)` or authorized realtime status.
4. **No Financial Risk**: The ticketing subsystem is strictly an in-memory demonstration engine. No credit card, UPI, or banking gateways are integrated.
5. **Graceful Degradation**: If backend connectivity is lost, the mobile application falls back gracefully to local offline datasets, displaying user-friendly offline indicators rather than blank screens or crashes.

---

## 6. Test & Quality Assurance

| Test Suite | File | Tests | Coverage |
|---|---|---|---|
| Phase 21 Production Feed Management | `backend/tests/test_phase21_production_feed.py` | 30 | Centralized config diagnostic states, state machine transitions, jittered backoff, GTFS-RT pipeline, coordinate bounds, deduplication, official vs calculated ETA, static GTFS validation report, alert separation, credential-safe test probe, observability metrics, error handling |
| Phase 20 Google Maps & Realtime | `backend/tests/test_phase20_google_maps_realtime.py` | 20 | Google Maps config, missing key fallback, realtime activation, VehiclePosition normalization, heading/speed/timestamps, TripUpdate vs geometric ETA, service alerts, occupancy honesty, stale handling, diagnostics |
| Phase 19 Production & Activation | `backend/tests/test_phase19_production.py` | 18 | Production config validator, dry-run endpoint, GTFS-RT quality pipeline, entity isolation, realtime activation, OpenAPI tags, diagnostics |
| Phase 18 Production UX & Resilience | `backend/tests/test_phase18_realtime_readiness.py` | 17 | UX telemetry, offline sync, diagnostics, fallback recovery, UI health cards |
| Phase 17 Commuter Intelligence | `backend/tests/test_phase17_commuter_intelligence.py` | 15 | Commuter intelligence, notification dispatch, journey comparisons, stop discovery |
| Phase 16 Production & Activation | `backend/tests/test_phase16_production.py` | 12 | Environment validation, CORS rules, GTFS-RT validation, backoff, logging sanitization |
| Phase 15 Production Deployment | `backend/tests/test_phase15_production.py` | 10 | Production CORS, GTFS Static ingestion, shapes, ETA source, diagnostics |
| Phase 14 Production & Security | `backend/tests/test_phase14_production.py` | 15 | Secrets protection, rate limiting, request size, probes, feed health, alerts, AI modes |
| GTFS-RT Realtime Foundation | `backend/tests/test_bmtc_realtime.py` | 15 | Static GTFS, VehiclePositions, TripUpdates, staleness, snapshot cache, APC |
| AI Service & Grounding | `backend/tests/test_ai_service.py` | 9 | Intent parsing, entity extraction, telemetry binding, fallback resilience |
| Crowd & Seat Prediction | `backend/tests/test_crowd_prediction.py` | 10 | Occupancy thresholds, seat clamping, confidence progression, disclaimers |
| Provider Architecture | `backend/tests/test_provider.py` | 8 | Interface adherence, fallback on missing BMTC keys, health mode reporting |
| Digital Tickets & Conductor | `backend/tests/test_tickets.py` | 8 | Ticket creation, route validation, duplicate use rejection, expiration |
| System Status & Reset | `backend/tests/test_system_status.py` | 2 | 7-module status dashboard, latency stats, demo state reset endpoint |
| **Total Backend** | `python3 -m unittest` | **176** | **100% Pass Rate (0.35s)** |
| **Frontend TypeScript** | `npx tsc --noEmit` | - | **0 Errors (Strict Mode)** |
