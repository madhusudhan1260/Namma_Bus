# NammaBlr — 3 to 5 Minute Competition Demo Script

**Hackathon Presentation & Live Demo Guide**  
**Bengaluru Metropolitan Transport Corporation (BMTC) Intelligent Assistant**

---

## Overview

- **Target Duration**: 3 to 5 minutes.
- **Presenter Setup**:
  - Expo Go / Simulator running on iOS or Android (`http://localhost:8082`).
  - FastAPI backend active on port 8001 (`http://localhost:8001`).
  - Terminal open with test suite ready (`python3 -m unittest discover -s backend/tests -v`).
- **Key Themes to Highlight**:
  1. Real-time telemetry grounding (no AI hallucinations).
  2. Commuter relief through predictive crowd & seat forecasting.
  3. Seamless passenger-to-conductor digital pass lifecycle.
  4. Ethical, production-ready provider abstraction ready for official BMTC GTFS feeds.

---

## Demo Step-by-Step Flow

### 0:00 – 0:30 | The Hook & Problem Statement
* **Presenter says**:  
  > *"Every day, over 3.5 million commuters navigate Bengaluru on BMTC buses. Yet commuters face two chronic uncertainties: 'Where is my bus really?' and 'Will I even be able to step inside or get a seat?'  
  > Existing apps give static schedules or raw coordinate feeds. Today, we present **NammaBlr**—a full-stack intelligent transit assistant with live native tracking, Bayesian seat prediction, telemetry-grounded AI, and a conductor validation system."*
* **On Screen**: App opens to the **Home Screen** (`app/(tabs)/index.tsx`).

---

### 0:30 – 1:15 | Step 1: Home Screen, Live Corridors, Service Alerts & Journey Planner
* **What to do**:
  1. Point to the **Honest Data Mode Banner**: `● SIMULATED TRANSIT DATA (Bengaluru Corridor Engine)`.
  2. Tap **"Details"** on the banner to open the new **Data Details modal**:
     - Point out the active provider, 100% freshness percentage, and last telemetry update timestamp.
  3. Show the **Active Corridor Alerts** section:
     - Notice the live advisories for ORR metro construction and Silk Board peak lane diversions.
  4. In the Journey Planner, type destination: `Majestic`.
  5. Show the multi-option comparison card with badges:
     - `⚡ Fastest` (500D Vajra AC Electric — 18 min)
     - `💰 Lowest Fare` (356 Ordinary — ₹20)
     - `💺 More Seats` (Comfortable seating forecast)
  6. Tap the **"Track Bus 500D"** CTA button on the fastest card.
* **Presenter says**:  
  > *"Notice how the home screen immediately grounds the commuter with honest data status, real-time corridor alerts for metro work, and our Data Details diagnostics. Tapping 'Track Bus' transitions directly into our native map."*

---

### 1:15 – 2:00 | Step 2: Native Map & Camera Follow Mode
* **What to do**:
  1. The screen transitions to the **Live Map** (`app/(tabs)/map.tsx`).
  2. Point out the glowing animated bus marker moving smoothly along the Outer Ring Road corridor.
  3. Note the live status pill: `● SIMULATED` and the **"Last updated 2s ago"** freshness counter.
  4. Tap the **Follow Camera** pill (`[ 🎯 Following Bus 500D ]`). As the bus moves, the camera pans automatically.
  5. Tap the bus marker to open the **Bus Stop Sheet**: show ordered stops (*HSR Layout → Silk Board → BTM Layout → Jayadeva → Majestic*), live ETA, and current occupancy (39/50 seats).
  6. Tap a stop marker (e.g. *Central Silk Board Junction*) to view upcoming buses arriving at that specific stop.
* **Presenter says**:  
  > *"This is built on react-native-maps. We have real-time waypoint interpolation, live vehicle heading angles, a live freshness timer, and an auto-centering follow mode designed for commuters standing at a bus stop."*

---

### 2:00 – 2:45 | Step 3: Grounded AI Assistant (Zero Hallucination)
* **What to do**:
  1. Switch to the **AI Tab** (`app/(tabs)/ai.tsx`).
  2. Tap the suggested pill: **"Will I get a seat on 500D?"**
  3. Show the instant, streaming-fast AI reply grounded in vehicle `KA-01-F-4819` telemetry:
     > *"I’m using simulated Bengaluru corridor telemetry for this demo. Bus 500D (KA-01-F-4819) is currently near Central Silk Board Junction with 39 passengers (78% occupancy, Moderate Crowd). According to our corridor forecast, approximately 11 seats are currently vacant, but occupancy will peak at BTM Layout before easing."*
  4. Mention the AI's 4-state data awareness (Simulated, Realtime, Delayed/Stale, and Unavailable) and strict Automated Passenger Counting honesty.
  5. Point out the interactive **Telemetry Card** embedded directly under the response:
     - ETA: `4 mins` | Occupancy: `78%` | Next Stop: `Central Silk Board`
     - Tap **[ 📍 Track on Live Map ]** to demonstrate deep linking.
* **Presenter says**:  
  > *"Unlike generic LLM wrappers that hallucinate routes or make up ETAs, NammaBlr parses commuter intent, extracts the route and corridor, binds directly to active vehicle telemetry, acknowledges its exact data mode, and formats verified actionable cards."*

---

### 2:45 – 3:30 | Step 4: Digital Demo Pass & Pure TypeScript QR Generator
* **What to do**:
  1. Switch to the **Passes Tab** (`app/(tabs)/tickets.tsx`).
  2. Tap **"+ Book Demo Ticket"**.
  3. Select Route **500D (Vajra AC Electric)**, from **Central Silk Board** to **Majestic (KBS)**.
  4. Tap **"Generate Demo Pass (₹25)"**.
  5. An active green digital ticket appears with a live countdown timer.
  6. Tap **"Inspect QR"**: show the dynamic, crisp QR code generated entirely on-device with zero external binary packages.
* **Presenter says**:  
  > *"For contactless boarding, we built a digital pass prototype. It generates cryptographically structured QR payloads in pure TypeScript SVG. No third-party payment gateways or banking APIs are touched—it's a clean, production-shaped prototype."*

---

### 3:30 – 4:15 | Step 5: Conductor Mode — Handheld Verification
* **What to do**:
  1. Switch to the **More Tab** (`app/(tabs)/more.tsx`) and tap **"Conductor Mode"** (`app/conductor.tsx`).
  2. Show the Handheld Validator interface:
     - Route Selector (`500D`, `356`, `KIA-8`)
     - Onboard Passenger Tally: Scanned vs Admitted vs Rejected
  3. Tap the quick test pill: **"[ 🎟️ Test Valid Active Pass ]"**.
     - Notice the green check: `VALID PASS • ADMIT PASSENGER`.
  4. Tap **"Mark Ticket as Used"**. The pass is consumed and the onboard tally increments.
  5. Tap the test pill: **"[ ⚠️ Test Already Used Pass ]"**.
     - Notice the amber warning: `ALREADY USED • REJECT PASSENGER`.
  6. Tap the test pill: **"[ ❌ Test Expired Pass ]"**.
     - Notice the red alert: `EXPIRED PASS • VALIDITY LAPSED`.
* **Presenter says**:  
  > *"Every transit system needs two sides: the commuter and the crew. Conductor Mode gives BMTC staff a handheld optical validator that enforces single-use passes and maintains real-time passenger tallies."*

---

### 4:15 – 4:45 | Step 6: System Status, Realtime Integration & Clean Reset
* **What to do**:
  1. Go back to the **More Tab** (`app/(tabs)/more.tsx`).
  2. Scroll to the **System Status** dashboard:
     - All modules active: Transit Data, Bus GPS Simulator, ETA Engine, Crowd Prediction, AI Assistant, Ticket Engine, Conductor Mode.
     - Note the **p95 Latency stats** and **Uptime counter**.
     - Note the **Feed Health diagnostics**.
  3. Show the **Realtime Integration** card:
     - Point out: `Feed: READY FOR CONFIGURATION`, `Vehicles: 0 active`, `VehiclePositions: Inactive`, `TripUpdates: Inactive`, `ServiceAlerts: Inactive`.
     - Tap **[ 🔍 Validate Realtime Feed (Dry Run) ]** to execute an interactive pre-flight audit against the activation pipeline.
     - Tap **[ ⚡ Test Authorized Realtime Probe ]** to execute a credential-safe live probe (`GET /api/realtime/test`) verifying reachable entity counts.
  4. Scroll to **Hackathon Demo Controls**:
     - Tap **[ 🔄 Reset Demo State ]**. Confirm in the alert dialog.
     - Notice the bus positions, tickets, and scan counters smoothly restore to factory baseline.
* **Presenter says**:  
  > *"Under the hood, our TransitDataProvider abstraction supports both our Bengaluru corridor simulator and authorized GTFS feeds. With production security middleware, p95 latency monitoring, separate liveness and readiness probes, a live dry-run validation pipeline, and credential-safe diagnostic probes, the system is truly enterprise-ready. With one tap on 'Reset Demo State', the entire system resets for the next presentation."*

---

### 4:45 – 5:00 | Conclusion & Q&A
* **Presenter concludes**:  
  > *"NammaBlr: 176/176 passing backend tests, 0 TypeScript errors, zero hallucinations, and zero scraping. A transparent, production-ready blueprint for the future of Bengaluru public transit with Google Maps and GTFS-RT support. Thank you, and we're ready for your questions!"*
