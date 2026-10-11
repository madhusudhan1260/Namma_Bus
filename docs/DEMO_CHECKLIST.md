# NammaBlr — Pre-Demo Checklist & Contingency Playbook

**Hackathon Live Presentation Runbook**  
**Zero-Failure Demonstration Protocol**

---

## 📋 1. Pre-Flight Checklist (T - 15 Minutes)

Complete these checks prior to stepping on stage or presenting to judges:

### 1.1 Backend Service Verification
- [ ] Backend is running on host port 8001:
  ```bash
  curl -s http://localhost:8001/api/health | jq .
  curl -s http://localhost:8001/api/ready | jq .
  ```
  *Expected Output:* `"status": "healthy"`, `"service": "NammaBlr - BMTC Transit Backend"`, `"ready": true`
- [ ] All 236 backend tests pass cleanly:
  ```bash
  PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p "test_*.py" -v
  ```

### 1.2 Mobile Client Verification
- [ ] Expo server running on port 8082 without bundle compilation errors.
- [ ] TypeScript passes with 0 errors: `npx tsc --noEmit`.
- [ ] Device connected to local WiFi network / hotspot (or Expo Go tunnel).
  - Open NammaBlr on device using the iOS Camera app to open Expo Go.
  - **On Simulator**: Press `i` in the Expo terminal.
- [ ] **5. Verify Device API Connection**
  - Open NammaBlr on device.
  - Verify the header telemetry badge reports: `● SIMULATED TRANSIT DATA (Bengaluru Corridor Engine)`.
- [ ] **6. Reset Demo State**
  - Go to **More** (`app/(tabs)/more.tsx`) → Scroll to **Hackathon Demo Controls**.
  - Tap **[ 🔄 Reset Demo State ]** → Tap **Reset**.
  - Confirms bus positions, ticket records, and conductor scan tallies are at initial factory defaults.
- [ ] **7. Quick Subsystem Spot Check**
  - **Home**: Verify nearby buses (500D, 356, KIA-8) are listing with active ETAs.
  - **Map**: Verify native map renders with dark styling, moving buses, and route lines.
  - **AI**: Tap *"Where is my 500D?"* and confirm prompt card generation.
  - **Passes**: Verify active pass `NMA-500D-8F42A1` appears with `"DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL"`.
  - **Conductor**: Tap **[ ● Active Pass ]** pill and verify `VALID DEMO TICKET` badge appears.
  - **More**: Check **System Status → Realtime Integration** card and run dry-run validation.

---

## 🎬 2. COMPLETE 35-STEP JUDGING DEMO FLOW

| Step | Action | What to Say / Point Out |
|---|---|---|
| **1–3** | Open Home Screen | *"NammaBlr provides real-time Bengaluru BMTC transit intelligence. Notice the transparent telemetry disclosure."* |
| **4–6** | Set From = `Silk Board`, To = `Majestic`, press **Find Buses** | *"The journey search engine instantly aggregates active corridor buses connecting Silk Board and Majestic."* |
| **7–8** | Display Journey Options | Point out comparison badges: `⚡ Fastest` (500D — 18 min), `💰 Lowest Fare` (356 — ₹20), and `💺 More Seats`. |
| **9–10** | Select 500D & tap **Track Bus 500D** | *"Selecting a journey option deep-links directly into live vehicle tracking."* |
| **11–13** | Live Map opens with 500D in focus | Show the bus marker moving along the Outer Ring Road corridor with live heading angle. |
| **14–15** | Point out Route Polyline & Bus Stops | Blue/cyan arterial route connecting Silk Board to Kempegowda Bus Station (Majestic). |
| **16** | Tap Bus / Open **Crowd Forecast** | Show Bayesian crowd projection: current occupancy (39/50 seats) and seat predictions for upcoming stops. |
| **17** | Verify **Following Mode** | Header banner shows `Following 500D • xx km/h`. Map auto-centers as the bus advances. |
| **18–20** | Open **AI Assistant** & ask *"Where is my 500D?"* | *"Zero hallucination AI assistant. It binds commuter intent directly to live vehicle telemetry without making up ETAs."* |
| **21–22** | Tap **[ 📍 Track on Live Map ]** in AI card | Smooth cross-screen transition back to the Live Map with 500D selected. |
| **23–25** | Open **Passes** tab & tap **+ Book Demo Pass** | Select Route 500D, 1 Rider (₹25), and tap **Generate Demo Pass**. |
| **26** | Tap **Inspect QR** | Show crisp QR code generated in pure TypeScript vector blocks with zero binary bloat. |
| **27–28** | Switch to **Conductor Mode** (from More tab) | Handheld crew validator. Enter or test active ticket. Large green banner: `VALID DEMO TICKET • Authorized for Travel`. |
| **29–30** | Tap **Mark Ticket as Used**, then re-verify | Pass transitions to used. Re-verification immediately triggers amber warning: `ALREADY USED • Reject Passenger`. |
| **31–33** | Open **More** → View **System Status** | Show all 7 core modules operating with green indicators and live latency metrics. |
| **34–35** | Tap **[ 🔄 Reset Demo State ]** | One-tap factory reset ready for the next judge! |

---

## 🛡️ 3. CONTINGENCY & BACKUP PLAYBOOK

### Scenario A: Backend Server Stops or Crashes During Demo
- **Symptom**: Red network error banners or stalled API fetches.
- **Immediate Action**:
  - The frontend has built-in offline fallbacks: `ApiService` automatically supplies rich local datasets (`MOCK_BUSES`, `MOCK_BUS_STOPS`, offline ticket storage).
  - You can say: *"Notice how our offline-first architecture gracefully preserves local corridor timetables and passenger features even during connectivity drops."*
  - To restart backend: run `python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8001 --reload`.

### Scenario B: Wi-Fi Disconnects on Mobile Device
- **Symptom**: Expo Go loses connection or says "Could not connect to Metro".
- **Immediate Action**:
  - Switch to local iOS Simulator (`EXPO_NO_TELEMETRY=1 npx expo start --ios`) which connects to `http://localhost:8001` with zero Wi-Fi dependencies.
  - Or use iPhone USB cable connection with reverse port forwarding if needed.

### Scenario C: Device Location Permission Denied
- **Symptom**: User taps "Don't Allow" on iOS location prompt.
- **Immediate Action**:
  - The app automatically falls back to `Demo location: Silk Board Junction` (`12.9176, 77.6238`) without crashing.
  - You can say: *"When GPS permissions are denied or in indoor environments, the app falls back to Bengaluru's central Silk Board transit hub for continuous demonstration."*

### Scenario D: AI Query Network Timeout
- **Symptom**: Chat query takes longer than 3.5 seconds.
- **Immediate Action**:
  - The app triggers the friendly offline assistant fallback: *"I'm unable to reach the transit service right now. You can still check live bus positions directly from the Map screen."* with no unhandled errors.
