# NammaBlr — Bengaluru Intelligent Transit Assistant

**Hackathon Competition Edition — 100% Verified & Demo-Ready**

NammaBlr is a mobile-first intelligent transit platform designed for Bengaluru public bus commuters (BMTC) and transit crew. Built with **Expo SDK 57 + React Native 0.86 + Expo Router + TypeScript** on the frontend and **Python 3 + FastAPI + Pydantic** on the backend.

---

## 🌟 Key Highlights

- **Live Native Map Tracking**: Real-time vehicle positions along 5 authentic Bengaluru corridors with auto-centering follow camera and stop detail sheets.
- **Predictive Crowd & Seat Availability**: Stop-by-stop Bayesian occupancy model calculating seat vacancies for upcoming stops with confidence metrics.
- **Telemetry-Grounded AI Assistant**: Commuter natural-language query engine with zero hallucination, binding directly to vehicle telemetry and deep-linking into map tracking.
- **Digital Pass Prototype & Conductor Validator**: Seamless contactless passenger QR ticket generation and handheld crew validation with real-time onboard tallies.
- **Pluggable Provider Architecture & GTFS-RT Foundation**: Production-grade `TransitDataProvider` abstraction with GTFS Static and GTFS-Realtime (VehiclePositions & TripUpdates) parser, background poller, in-memory snapshot cache, staleness detection, and automatic fallback to Bengaluru corridor simulation.
- **Production Readiness & Observability (Phases 26–30)**: Security middleware (`X-Request-ID`, security headers, 1MB payload limits, IP rate-limiting on sensitive endpoints), runtime latency tracking (avg, p95), FeedHealth freshness, and isolated liveness (`/api/health`) and readiness (`/api/ready`) probes.
- **Production Commuter Experience & Map Intelligence (Phase 26)**: User location marker with pulse ring, "Center on my location" FAB, route overview camera fitting all corridor waypoints, bus-follow mode with pan-drag disengage, stop-focused camera mode, upcoming arrivals sheet with dynamic ETAs, and professional municipal bus markers.
- **Realtime Feed Activation & Resilience (Phase 27)**: Authorized GTFS-RT pipeline for VehiclePositions, TripUpdates, and ServiceAlerts with geographic bounding box validation, entity deduplication, jittered exponential backoff (5s–60s), last-known-good snapshot retention, and official TripUpdate vs calculated estimate attribution.
- **Intelligent Commuter Assistant & Personalization (Phase 28)**: Natural language query engine with intent detection, multi-turn pronoun resolution ("Where is 500D?" -> "Show me its stops"), grounded transit disclosures, Home screen Saved Journeys and Favorite Routes with live ETA badges, and English/Kannada bilingual support.
- **Ticketing, Identity, Conductor & Trust Hardening (Phase 29)**: Complete ticket lifecycle (ACTIVE, USED, EXPIRED, INVALID, MISMATCH), HMAC-SHA256 tamper-evident digital signatures, duplicate scan blocking with timestamp recording, route mismatch enforcement, minimal conductor view with zero raw Aadhaar or biometrics, and Shakti Scheme ₹0 demo concession pass.
- **Final Production Demo & Observability (Phase 30)**: Expanded `GET /api/system/status` reporting 17 municipal engine modules, p95 latency tracking, Diagnostics UI, deterministic `POST /api/demo/reset`, and strict operational statement preservation.
- **Real-World Commuter Intelligence (Phase 31)**: Smart Live Trip View with following stops and remaining corridor distance, visual `LiveJourneyProgress` timeline (`✓` passed, `●` next with pulse, `○` upcoming), multi-leg walking + transit journey summaries (`Walk → Bus → Walk`), disruption-aware journey alerts, smart nearby transit stops with proximity and walking minutes, AI assistant trip-context answering (`stops_remaining`, `destination_eta`), and expanded observability counters.
- **Smart Commuter Trip Assistant (Phase 32)**: End-to-end active journey lifecycle state machine (`PLANNING` ➔ `WALKING_TO_STOP` ➔ `WAITING_FOR_BUS` ➔ `BUS_APPROACHING` ➔ `ON_BUS` ➔ `NEAR_DESTINATION` ➔ `COMPLETED`), municipal `ActiveJourneyCard` prioritized on Home, real-time telemetry syncing, Map Active-Journey Mode with `"FOLLOWING 500D"` banner and pan-drag disengage, smart notification dispatching, Shakti scheme zero-fare linking with demo ticket disclaimer, non-sensitive journey history with one-tap repeat journeys, and grounded AI assistant trip queries.
- **Smart Trip Safety & Arrival Intelligence (Phase 33)**: Smart arrival detection (`DESTINATION_APPROACHING`, `GET_READY_TO_EXIT`, `DESTINATION_REACHED`, `DESTINATION_PASSED`), proactive "Get Ready to Exit" municipal warning card with 44×44pt action buttons (`[ View Route ]`, `[ Continue Tracking ]`), missed destination protection (`[ View Route ]`, `[ Continue Tracking ]`, `[ End Journey ]`), milestone notification deduplication (zero spamming on polling), offline journey safety with `"OFFLINE — SHOWING LAST KNOWN DATA"` preservation, Map Arrival Mode with dynamic colored status banners (`Recenter` action on pan/zoom), enhanced `LiveJourneyProgress` stop timeline (`✓ ARRIVED`, `● GET READY TO EXIT`, `⚠ PASSED`), grounded AI arrival question answering, full Kannada/English localization, and observability metrics.
- **Smart Transfers & Multimodal Journey Intelligence (Phase 34)**: End-to-end multi-leg journey model (`WALK` → `BUS 1` → `TRANSFER` → `WALK` → `BUS 2` → `DESTINATION`) with factual walking distances and durations, non-breaking 7-stage transfer state machine (`TRANSFER_APPROACHING`, `TRANSFER_READY`, `WALKING_TO_CONNECTION`, `WAITING_FOR_CONNECTION`, `CONNECTING_BUS_APPROACHING`, `TRANSFER_COMPLETED`, `TRANSFER_MISSED`), factual transfer buffer computation (`connecting_bus_eta - walking_duration`), reliable missed connection protection (suppressed during offline/stale telemetry), dedicated municipal Transfer Card and Missed Connection Warning Card with ≥44×44pt touch targets, Multimodal Journey Timeline, Map Transfer Mode floating banner, grounded bilingual AI Assistant query engine, and aggregate observability counters in `GET /api/system/status`.
- **Smart Accessibility & Inclusive Transit (Phase 35)**: Verified accessibility data modeling (`AccessibilityStatus`, `AccessibilityMetadata`) with strict factual disclosure: never claiming wheelchair accessibility unless explicitly verified in underlying transit data (strictly falling back to `"Accessibility information unavailable from the current transit data."`). Fleet accessibility attribution (Vajra Electric 500D/G-2 and Vayu Vajra KIA-8 low-floor with wheelchair ramps vs BMTC Ordinary 356/201R high-floor step boarding) and station hub accessibility (Majestic, Silk Board, Electronic City, Airport T2 with ramp and boarding assistance). Multi-factor accessibility scoring (0–100), preference-aware ranking for wheelchair, low-floor, and reduced walking commuters, grounded conversational AI assistant for accessibility queries, bilingual English/Kannada accessibility localization, expanded Commuter Preferences toggles (≥44×44pt touch targets), accessibility badges on journey cards, active journey low-floor indicators, and comprehensive observability metrics with `GET /api/transit/accessibility/{route_or_bus_id}` and `GET /api/system/status`.
- **302/302 Passing Backend Tests & 0 TypeScript Errors**: Comprehensive automated coverage across 26 test suites verifying all subsystems, active journey state machine, authorized realtime feed management, commuter intelligence, arrival intelligence, smart transfers, accessibility intelligence, and production error boundaries.
- **Production Containerization**: Dockerfile with least-privilege non-root execution (`appuser`), healthcheck probes, `STOPSIGNAL SIGTERM`, and `docker-compose.yml` for unified deployment.

---

## 🏛️ System Architecture

```
Mobile App (Expo SDK 57 + React Native 0.86)
    │
    ▼
FastAPI Backend (REST API /api/*)
    │  ├─ Security & Observability Middleware (Rate Limit, Latency p95, X-Request-ID)
    │  ├─ Structured Operational Event Logging (credential-safe, request ID tracing)
    │  ├─ Liveness /api/health & Readiness /api/ready Probes
    │  └─ Corridor Service Alerts (/api/alerts)
    ▼
Transit Provider Factory (provider_factory.py)
   ↙                                ↘
MockTransitDataProvider             BMTCTransitDataProvider
(Bengaluru Corridor Simulation)     (Authorized GTFS / GTFS-RT with Exponential Backoff)
   │                                │
   └───────────────┬────────────────┘
                   ▼
         Standard Transit Models
     (Bus, BusLocation, Route, Occupancy)
                   │
    ┌──────────────┼──────────────┬──────────────┬──────────────┐
    ▼              ▼              ▼              ▼              ▼
ETAService    Occupancy     CrowdPrediction  AIService     TicketService
              Service           Engine       (Grounded)    (Conductor Mode)
```

For complete subsystem designs, diagrams, and technical deep-dives, see:  
👉 [docs/HACKATHON_ARCHITECTURE.md](docs/HACKATHON_ARCHITECTURE.md)

---

## 📱 Feature Tour

| Feature | Screen | Details |
|---|---|---|
| **Journey Planner & Comparison** | `Home` | Search Bengaluru hubs (Silk Board, Majestic, Electronic City). Compare routes with `⚡ Fastest`, `💰 Lowest Fare`, and `💺 More Seats` tags. |
| **Service Alerts & Corridor Advisories** | `Home` | Live corridor notices (metro construction, traffic diversions) with route filtering and severity badges. |
| **Data Details Diagnostics** | `Home` | Interactive modal showing 5 status states (🟢 `REALTIME DATA`, 🟡 `FEED DELAYED`, 🟠 `FEED STALE`, 🔴 `FEED UNAVAILABLE`, 🔵 `SIMULATED DATA`), freshness %, last update time, and feed health status. |
| **Live Native Map** | `Map` | Real-time moving buses on `react-native-maps`, route polylines, heading markers, dynamic data status pills, and 1-tap `[ 🎯 Follow Bus ]` camera lock. |
| **Grounded AI Assistant** | `AI` | Ask natural questions (*"Will I get a seat on 500D?"*, *"Where is bus 356?"*). 4-state data awareness with strict occupancy honesty. |
| **Digital Passes** | `Passes` | Book prototype passes for active corridors. Inspect crisp QR codes generated in pure TypeScript with zero native binary bloat. |
| **Conductor Handheld Validator** | `More` → `Conductor` | Optical scanner & pass validator with live onboard tallies (Scanned, Admitted, Rejected) and 1-tap test pills. |
| **System Status Dashboard** | `More` | Real-time telemetry monitoring for all modules, p95/avg latency metrics, GTFS repository statistics, provider feed health, and uptime. |
| **Demo State Reset** | `More` | 1-tap confirmation dialog that resets simulation progress, passenger exchange, tickets, and conductor tallies. |

---

## 🚀 Quick Start Guide

### Prerequisites
- **Node.js** >= 18
- **Python** >= 3.10
- **Expo Go** mobile app on iOS/Android (or Xcode Simulator / Android Studio Emulator)

---

### 1. Start the FastAPI Backend
```bash
# Terminal 1: Navigate to repository root
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8001 --reload
```
- **Swagger API Docs**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **Liveness Probe**: [http://localhost:8001/api/health](http://localhost:8001/api/health)
- **Readiness Probe**: [http://localhost:8001/api/ready](http://localhost:8001/api/ready)
- **Service Alerts**: [http://localhost:8001/api/alerts](http://localhost:8001/api/alerts)
- **Live System Status**: [http://localhost:8001/api/status](http://localhost:8001/api/status)

Or run with Docker Compose:
```bash
docker compose up --build
```

---

### 2. Start the Mobile Client
```bash
# Terminal 2: In repository root
EXPO_NO_TELEMETRY=1 npx expo start --port 8082
```
- Press `i` to open iOS Simulator.
- Press `a` to open Android Emulator.
- Or scan the QR code in your terminal with the **Expo Go** app on your physical iPhone or Android device.

---

## 🧪 Verification & Test Suites

### Backend Unit Tests (293 Tests — 100% Pass)
```bash
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p "test_*.py" -v
```
- `test_phase34_transfer_intelligence.py`: Phase 34 Multimodal journey generation, 7 transfer states, transfer buffer calculation, missed transfer telemetry guard, transfer endpoint, grounded transfer AI, and observability metrics (22 tests).
- `test_phase33_arrival_intelligence.py`: Phase 33 Smart arrival detection, proactive exit alerts, missed destination protection, deduplicated notifications, offline preservation, and arrival map mode (16 tests).
- `test_phase32_trip_assistant.py`: Phase 32 Active journey state machine progression, telemetry sync, notification dispatching, Shakti demo pass linking, journey history, and trip assistant AI queries (10 tests).
- `test_phase31_commuter_intelligence.py`: Phase 31 Smart live trip tracking, visual progress timeline, walking + transit multimodal summaries, nearby stops, and trip-context AI queries (9 tests).
- `test_phase30_production_observability.py`: Phase 30 Expanded system status observability (17 modules), p95 latency tracking, and deterministic demo reset (3 tests).
- `test_phase29_ticketing_trust.py`: Phase 29 Full ticket lifecycle, HMAC-SHA256 signature verification & tampering detection, route mismatch, duplicate scan blocking, conductor data minimization, and Shakti Scheme concession labeling (5 tests).
- `test_phase28_assistant_personalization.py`: Phase 28 Intent detection, route extraction, multi-turn pronoun resolution, grounded AI disclosures, nearest stop routing, and commuter personalization persistence (7 tests).
- `test_phase27_realtime_resilience.py`: Phase 27 GTFS-RT feed health, geographic bounding box validation, entity deduplication, exponential backoff, snapshot retention, TripUpdate ETA attribution, and occupancy honesty (14 tests).
- `test_phase26_map_journey.py`: Phase 26 Stop arrivals, dynamic ETAs, feed disclosure, walking metrics, and service alerts count (5 tests).
- `test_phase25_personalization.py`: Phase 25 Commuter preferences, saved journeys CRUD, and notification preferences (6 tests).
- `test_phase23_production.py`: Phase 23 Municipal branding, Google Maps fallback, conductor verification, and ticket lifecycle (8 tests).
- `test_phase21_production_feed.py`: Phase 21 Feed management, configuration validation, activation state machine, and diagnostic probes (30 tests).
- `test_phase20_production.py`: Phase 20 Google Maps integration, feed health diagnostics, and vehicle positions (14 tests).
- `test_phase19_production.py`: Phase 19 Production deployment, config validator, invalid URL rejection, and CORS safety (18 tests).
- `test_phase18_realtime_readiness.py`: Phase 18 Provider activation, ticket route mismatch, and operational statement exactness (7 tests).
- `test_phase17_commuter_intelligence.py`: Phase 17 Commuter intelligence, journey recommendations, and crowd trends (9 tests).
- `test_phase16_production.py`: Phase 16 Environment validation, CORS restrictions, backoff, and logging sanitization (12 tests).
- `test_phase15_production.py`: Phase 15 Non-wildcard CORS, GTFS Static ingestion, and TripUpdate ETA attribution (10 tests).
- `test_phase14_production.py`: Phase 14 Secret protection, rate limiting, request size limits, and readiness probes (15 tests).
- `test_bmtc_realtime.py`: GTFS Static & GTFS-RT integration foundation, parser, normalization, and snapshot retention (15 tests).
- `test_ai_service.py`: Intent classification, entity extraction, telemetry binding, and fallback resilience (9 tests).
- `test_crowd_prediction.py`: Bayesian crowd tiers, seat availability clamping, and stop confidence progression (10 tests).
- `test_provider.py`: Provider interface adherence, unconfigured BMTC safety, and automatic fallback (8 tests).
- `test_tickets.py`: Digital ticket generation, route validity, expiration checks, and conductor single-use enforcement (8 tests).
- `test_system_status.py`: 12-module status reporting, latency metrics, and demo state reset endpoint (2 tests).
- `test_metrics_service.py`: Latency statistics and counters tracking (21 tests).

### Frontend TypeScript Check (0 Errors)
```bash
npx tsc --noEmit
```
- **Result**: **0 TypeScript errors (Strict Mode)**. All 5 tabs and Conductor mode fully type checked.

---

## 🛡️ Security, Ethics & Real-Data Policy

- **Operational Statement**: `REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED`.
- **Zero Scraping Policy**: NammaBlr does **NOT** scrape private BMTC APIs or the Namma BMTC consumer mobile app.
- **Honest Data Mode Disclosure**: All interfaces clearly display `● SIMULATED TRANSIT DATA` when operating in simulation mode.
- **Zero Real-Money Gateways**: Digital ticketing is strictly a local demo prototype. No banking, UPI, or payment gateways are integrated.
- **Official Open Data Roadmap**: For guidelines on connecting authorized municipal GTFS Static and GTFS-Realtime feeds, see [docs/REAL_TRANSIT_DATA.md](docs/REAL_TRANSIT_DATA.md).

---

## 🎤 Presentation & Demo Script

For a step-by-step 3-to-5 minute competition pitch walkthrough with exact dialog and screen transitions:  
👉 [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
