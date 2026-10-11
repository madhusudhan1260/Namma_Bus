# Namma Bus Access module

Accounts, role-based access control, passenger eligibility, student passes verified by colleges,
backend-priced tickets with signed QR codes, conductor validation and Super Admin oversight.

It is **additive**: live BMTC tracking, routes, stops, journey planning, nearby buses and the
NammaRoute integration are untouched. The backend is mounted under `/api/access` only when
`ACCESS_DATABASE_URL` is set; the frontend lives under `app/access/*`.

```
Namma Bus frontend (app/access/*)
        ↓  Bearer token (never role data)
/api/access  →  auth · RBAC · eligibility · tickets · college · conductor · admin
        ↓                                   ↓
PostgreSQL (nammabus_access)        NammaRoute (/api/network → GTFS stops + fares)
```

## What is real and what is development-only

| Part | Status |
| --- | --- |
| Accounts, passwords (scrypt), JWT + rotating refresh tokens, lockout, rate limits | Real |
| RBAC (PASSENGER, STUDENT, CONDUCTOR, COLLEGE_ADMIN, SUPER_ADMIN), college scoping | Real, enforced server-side |
| Fares | Real GTFS fare rules from NammaRoute; otherwise the labelled `DEMO FARE ESTIMATE` |
| Eligibility decision | Real engine, **configurable policy** (`eligibility_policy.json`). The default policy is a development policy, **not** an official BMTC/Government rule |
| Identity verification | `IDENTITY_PROVIDER=mock` → development simulator, labelled **"DEVELOPMENT VERIFICATION — NOT REAL IDENTITY VERIFICATION"**. `digilocker` slot needs official partner credentials; until the partner attribute retrieval is implemented it reports UNAVAILABLE |
| Face verification | `BIOMETRIC_PROVIDER=mock` → **no face recognition runs**; the developer chooses the result (labelled). A real authorized provider must be plugged in. No claim is made that Aadhaar/DigiLocker offers face matching |
| OTP | `OTP_PROVIDER=mock` returns the code in the response with "DEVELOPMENT OTP — NOT SENT BY SMS" |
| Payment | `pay-demo` step, labelled "DEMO PAYMENT — NO REAL MONEY CHARGED" |
| Malware scan | Hook present; default only detects the EICAR test file and reports `NOT_SCANNED` (never claims CLEAN) |

`ACCESS_ENV=production` refuses to start with development secrets or mock providers.

## Setup

```bash
cd backend
python3 -m pip install "psycopg[binary]" alembic python-multipart   # new dependencies only
cp .env.access.example .env.access        # fill in DB URL and secrets
createdb nammabus_access && createdb nammabus_access_test
python3 -m app.access.cli migrate         # Alembic migrations 0001–0004
ACCESS_SUPERADMIN_PASSWORD='...' python3 -m app.access.cli create-superadmin --name "Ops Admin" --email admin@example.org
python3 -m app.access.cli seed-demo       # development only: 3 buses, 3 conductors, demo colleges + passengers
SIMULATION_ENABLED=false python3 -m uvicorn app.main:app --port 8011
```

### Demo accounts (development only)

`seed-demo` creates the following. **Passwords are random and written only to `backend/.env.access.accounts`**
(git-ignored, file mode 600). They are never printed or committed; rotate them with `seed-demo --reset-passwords`.

| Account | Sign in with | Notes |
| --- | --- | --- |
| `CONDUCTOR-365P` | Conductor portal → Conductor ID + password | BUS 1, route 365-P |
| `CONDUCTOR-356M` | Conductor portal → Conductor ID + password | BUS 2, route 356-M |
| `CONDUCTOR-361C` | Conductor portal → Conductor ID + password | BUS 3, route 361-C |
| `DEMO-COLLEGE` officer | College portal | APPROVED college |
| `officer.pending@example.com` | College portal | PENDING college — login is refused until a Super Admin approves it |
| `male.regular@`, `male.buspass@`, `female.noaadhaar@`, `female.aadhaar@example.com` | Passenger portal | one per passenger category; no verification is pre-completed |

The buses have **no registration number** on purpose: their live position shows `REALTIME DATA UNAVAILABLE`
until a Super Admin enters the registration of a bus that is actually in the BMTC feed (Admin → Buses).
Nothing about GPS, approvals or verification is pre-filled or invented. There is no public conductor or
Super Admin registration; the earlier sample conductor `EMP1001` is disabled.

The Super Admin manages colleges, students, conductors and buses in the Admin portal, and can enable TOTP
two-factor for staff (`POST /admin/users/{id}/two-factor`).

Frontend: `npx expo start --web` and open `/access`.

## API (all under `/api/access`; interactive docs at `/docs`)

| Method & path | Who |
| --- | --- |
| `POST /auth/register` (gender + `has_bus_pass` or `has_aadhaar`, `date_of_birth`) · `POST /auth/login` · `POST /auth/login/verify` · `POST /auth/otp/request` · `POST /auth/otp/verify` · `POST /auth/refresh` · `POST /auth/logout` | public / signed-in |
| `POST /auth/password/forgot` · `POST /auth/password/reset` (15-min code, 5 tries, signs out all devices) | public |
| `GET /auth/sessions` · `DELETE /auth/sessions/{id}` | signed-in |
| `GET /me` (alias `/auth/me`) · `GET /health` | signed-in / public |
| `GET|PUT /passenger/profile` · `POST /passenger/profile/photo` · `GET /passenger/eligibility` | passenger, student |
| `POST /face/start` · `POST /face/verify` (alias `/biometric/verify`) · `GET /face/status` | passenger, student |
| `POST /identity/aadhaar-answer` · `POST /identity/start` (consent required) · `GET /identity/status` · `GET|POST /identity/callback` | passenger, student |
| `POST /biometric/verify` (consent + camera image; image never stored) | passenger, student |
| `GET /colleges/approved` (alias `/colleges`; APPROVED colleges only) · `POST /colleges/register` (multipart, starts PENDING) | public |
| `POST /bus-pass` (alias `/students/pass/upload`) · `GET /bus-pass/status` (alias `/students/pass/status`) | student |
| `GET /college/dashboard` · `GET /college/requests[?status=&q=]` (alias `/college/students`) · `GET /college/students/{id}` · `POST /college/requests/{id}/approve` · `/reject` · `/revoke` | college admin (own APPROVED college only) |
| `GET /documents/{id}/url` · `GET /documents/{id}/content?token=` | owner, their college admin, super admin |
| `POST /tickets/quote` · `POST /tickets/create` · `POST /tickets/{id}/pay-demo` · `GET /tickets` · `GET /tickets/{id}` | passenger, student |
| `POST /conductor/login` (Conductor ID + password/PIN, TOTP if enabled) | public |
| `GET /conductor/me` · `GET /conductor/bus` (live position or `REALTIME DATA UNAVAILABLE`) · `GET /conductor/trip` · `POST /conductor/trip/start` · `POST /conductor/trip/end` · `POST /conductor/ticket/verify` → `VALID / EXPIRED / ALREADY_USED / INVALID / REVOKED / WRONG_ROUTE / WRONG_BUS` | conductor |
| `GET /admin/dashboard` (incl. `stats`) · `/admin/users` · `/admin/verifications` · `/admin/tickets` · `POST /admin/tickets/{id}/revoke` · `/admin/audit-logs` · `/admin/reports` | super admin |
| `GET /admin/colleges[?status=&q=]` · `GET /admin/colleges/{id}` · `POST /admin/colleges/{id}/approve|reject|suspend|reactivate` · `POST /admin/colleges` · `/admin/college-admins` | super admin |
| `GET /admin/students[?q=]` · `GET /admin/students/{id}` · `POST /admin/students/{id}/suspend-eligibility|reinstate-eligibility` | super admin |
| `GET|POST /admin/conductors` · `PATCH /admin/conductors/{id}` (bus) · `GET /admin/conductors/{id}/activity` · `POST /admin/conductors/{id}/reset-credentials` · `POST /admin/users/{id}/activate|deactivate|two-factor` | super admin |
| `GET|POST /admin/buses` · `PATCH /admin/buses/{id}` (registration, route, conductor, IN_SERVICE / OUT_OF_SERVICE / MAINTENANCE) | super admin |

## Fares (BMTC revised stage-fare table)

Ordinary services (ORDINARY, BIG10, METRO_FEEDER) are priced from the BMTC revised fare chart in `fares.py`
(`STAGE_FARES`): 25 chargeable stages of 2 km, with Adult / Child / Senior Citizen columns (e.g. stage 1 ≤ 2 km:
₹6 / ₹3 / ₹5; stage 5 ≤ 10 km: ₹23 / ₹12 / ₹18; stage 25 ≤ 50 km: ₹32 / ₹16 / ₹24). The distance is summed stop to
stop along the route between the boarding and destination stops, using GTFS stop coordinates, so it can be slightly
shorter than the road distance. Journeys over 50 km use the last stage. Tickets carry `fare_category`, `distance_km`
and `fare_stage` (migration 0005). `SENIOR` needs the account's date of birth to show age 60+. `CHILD` is
for a child travelling on the ticket, and the conductor sees the category when scanning. AC services (Vajra, Vayu Vajra)
are not in this chart and keep the labelled DEMO_FARE_ESTIMATE. Free eligibility still makes the fare ₹0.

## Eligibility (backend only)

`eligibility.evaluate()` runs the enabled rules from the policy file. Default rules:

Every decision returns an **eligibility** (`REGULAR_PAID`, `STUDENT_FREE`, `FEMALE_IDENTITY_VERIFIED_FREE`) and a
**reason code** (`ELIGIBLE_FREE`, `NOT_ELIGIBLE`, `VERIFICATION_REQUIRED`, `VERIFICATION_EXPIRED`, `VERIFICATION_FAILED`).
Both rules first require `eligibility_not_suspended` (Super Admin can suspend a passenger's free-ticket eligibility).

- `female_identity_verified`: `identity_verified` + `identity_attested_female` (the **provider's**
  attribute, not the self-declared gender) + `face_verified_recent` (a MATCH bound to that identity
  verification, unexpired, **single use**). Max 1 passenger.
- `student_bus_pass`: `student_college_approved` (the pass was approved **and the college is still APPROVED**) +
  `student_pass_approved` + `student_pass_valid_today`.

No/pending/rejected/expired pass, failed or unavailable verification → regular fare. The conductor
re-checks the eligibility at scan time.

## Security summary

- Passwords: scrypt; lockout after 5 failures (15 min); per-IP/user rate limits (429).
- Tokens: 15-min JWT (HS256) + 14-day refresh token stored hashed, rotated on use; reuse revokes all
  sessions. Web refresh cookie is HttpOnly/SameSite=Strict with double-submit CSRF.
- Role is re-read from the DB on every request; college admins are scoped to their college (404 otherwise).
- Documents: magic-byte type check (PDF/JPEG/PNG), 5 MB limit, scan hook, Fernet encryption at rest in
  private storage, random storage keys, 5-minute signed links re-authorized on access, `no-store`.
- QR: `{v,tid,ref,rid,ts,exp,sig}` HMAC-SHA256 signed; no personal/identity/biometric data.
- Stored identity data: provider, status, opaque reference, `{"gender": "F"|"M"}`, timestamps. No Aadhaar
  numbers/documents/credentials. Face attempts: result + reference only, purged after
  `BIOMETRIC_AUDIT_RETENTION_DAYS` (`python3 -m app.access.cli purge-face-audit`).
- Audit log for logins, verifications, approvals, ticket creation/validation, admin actions (no secrets).

## Tests

```bash
cd backend && python3 -m pytest tests/test_access_module.py tests/test_network_assistant.py -q   # needs ACCESS_TEST_DATABASE_URL
cd .. && npx tsc --noEmit                                                                        # frontend types
```

64 backend tests cover: male regular / bus-pass, female with / without Aadhaar, face match and no-match, a tampered
client trying to force a free ticket or claim a role, college registration → approval / rejection / suspension,
college search and pass revocation, expired passes, suspended eligibility, conductor login and wrong login, bus
assignment and `REALTIME DATA UNAVAILABLE`, trips, `WRONG_ROUTE` / `WRONG_BUS` / `REVOKED`, admin-only endpoints,
credential reset, password reset and session management, plus the original RBAC / QR / document / 2FA tests.

## Folder structure

```
backend/app/access/
  api.py  config.py  db.py  models.py  rbac.py  security.py  audit.py  documents.py  fares.py
  eligibility.py  eligibility_policy.json  seed.py  cli.py  configure_email.py
  providers/   identity.py (mock | digilocker | unavailable)  biometric.py  otp.py  scanner.py
  routers/     auth.py  passenger.py  identity.py (identity + face)  students.py (bus pass + colleges)
               conductor.py  tickets.py  admin.py  support.py
  migrations/versions/0001…0004
backend/tests/test_access_module.py
app/access/  index (sign in) · register · forgot · aadhaar · passenger · student · buy · ticket · tickets
             college-register · college · conductor · admin · help · privacy
components/access/  AccessUi · DocumentPicker · CameraCapture · routeAfterLogin · dob
services/accessApi.ts · constants/accessI18n.ts (English + Kannada)
```

## Database tables (PostgreSQL, prefix `access_`)

`users` (role, DOB, profile photo ref, lockout) · `refresh_tokens` (hashed, device + IP) · `password_resets` (hashed codes) ·
`otp_challenges` · `passenger_profiles` (gender, bus-pass / Aadhaar answers, eligibility suspension) ·
`colleges` (status PENDING / APPROVED / REJECTED / SUSPENDED, officer, document, review) · `college_admins` ·
`student_profiles` · `student_passes` · `student_verifications` · `documents` (encrypted, private) ·
`identity_verifications` (provider, status, opaque reference, attested gender only) · `face_verification_attempts`
(result + reference; images never stored) · `buses` (label, registration, route, status) · `conductors` (ID, bus) ·
`trips` · `tickets` · `ticket_verifications` · `audit_logs` (actor, action, target, result, IP, user agent) · `feedback`.

## Female passenger: Aadhaar Offline e-KYC + face match (real)

Flow: account → "Do you have Aadhaar?" Yes → upload the **UIDAI Aadhaar Paperless Offline e-KYC** ZIP + the 4-digit share
code (`POST /identity/aadhaar-ekyc`, consent required) → VERIFIED → at ticket time the camera capture is compared with the
UIDAI-signed photo (`POST /face/verify`) → MATCH → free ticket (single use, 10 minutes).

- `providers/aadhaar_ekyc.py` opens the ZIP (WinZip AES or ZipCrypto), parses the XML safely and checks UIDAI's
  enveloped XML-DSig signature (RSA-SHA1/SHA256, C14N) against `ACCESS_UIDAI_CERT_PATH`. Files older than
  `ACCESS_EKYC_MAX_AGE_HOURS` (72) are refused. Without the certificate nothing is ever VERIFIED (status UNAVAILABLE).
- Kept: attested gender, DOB (replaces the self-declared one), name-match flag, the photo (encrypted private document
  `AADHAAR_EKYC_PHOTO`) and a keyed fingerprint that blocks one Aadhaar on several accounts. **Not kept:** Aadhaar number,
  address, share code, the ZIP or the XML.
- `BIOMETRIC_PROVIDER=opencv` → `OpenCVFaceProvider`: OpenCV YuNet face detection + SFace recognition (cosine ≥
  `ACCESS_FACE_MATCH_THRESHOLD`, default 0.363) using the ONNX models in `ACCESS_FACE_MODEL_DIR` (default `backend/models/face/`:
  `face_detection_yunet_2023mar.onnx`, `face_recognition_sface_2021dec.onnx` from github.com/opencv/opencv_zoo). One face
  required in the capture. **Not certified liveness detection**: a printed photo held to the camera could pass.
- Verified independently with xmllint (C14N) + openssl (RSA) + bsdtar (AES-256 ZIP) generated files (`test_k01`–`test_k05`).
- **e-Aadhaar PDF** (the usual "Download Aadhaar" file, full or masked) is accepted on the same endpoint
  (`POST /identity/aadhaar`, field `pdf_password` = first 4 letters of the name in capitals + birth year).
  `providers/eaadhaar_pdf.py` + `providers/cms.py`: the PDF signature must cover the whole file, the CMS signature must
  verify, and the signer must be UIDAI — trusted either because its key equals UIDAI's published certificate
  (`ACCESS_UIDAI_CERT_PATH`, pinned) or because it chains to a root in `ACCESS_TRUSTED_CA_DIR` (default `backend/certs/trusted/`,
  e.g. the CCA India root). The password proves the first 4 letters of the name and the birth year; gender, DOB, the last
  4 digits (transient) and the photo (the embedded image with exactly one face) are read; nothing else is kept.
  Tested with PDFs built by matplotlib, encrypted by pypdf and signed by `openssl cms` with test CA chains (`test_p01`, `test_p02`).
- Web upload: choose the file or drag & drop it onto the box (`components/access/AadhaarFilePicker.web.tsx`). Native apps
  need `expo-document-picker`; until it is added the upload is done from the web app.

## Connecting real DigiLocker and face verification

Nothing here is real until an authorized provider is configured; until then every screen shows
`DEVELOPMENT VERIFICATION — NOT REAL IDENTITY VERIFICATION`.

1. **DigiLocker** – register as a requester on the DigiLocker Partner portal (requires an organisation and
   MeitY/DigiLocker approval). Put the issued values in `backend/.env.access`: `DIGILOCKER_CLIENT_ID`,
   `DIGILOCKER_CLIENT_SECRET`, `DIGILOCKER_REDIRECT_URI` (your HTTPS `/api/access/identity/callback`),
   `DIGILOCKER_AUTHORIZE_URL`, `DIGILOCKER_TOKEN_URL`, then set `IDENTITY_PROVIDER=digilocker`. Complete the
   attribute mapping in `providers/identity.py` against the approved scopes (only gender is kept).
2. **Face verification** – contract a licensed face-match provider (e.g. one approved for Aadhaar face
   authentication through a UIDAI AUA/KUA). Implement `BiometricProvider.verify()` in `providers/biometric.py`
   and set `BIOMETRIC_PROVIDER` to it. Images must stay in memory only (the router already discards them).
3. Set `ACCESS_ENV=production`: startup then refuses mock providers and development secrets.

## Live bus location for conductors

`GET /conductor/bus` matches the bus's registration number against the BMTC feed served by NammaRoute
(`/api/network/vehicles`). When the bus is not in the feed, has no registration, or the feed is down, the
response is `REALTIME DATA UNAVAILABLE` with a reason. No position is ever stored or invented.

## Integrating into the existing Namma Bus app

The module already runs inside the Namma Bus backend and Expo app; these steps switch users over
from the older Phase 41 flow when you are ready. None of them touch the live-bus code.

1. **Backend** – nothing to add: `app/main.py` mounts the module when `ACCESS_DATABASE_URL` is set.
   Unset it to switch the module off.
2. **Entry point** – point the app's sign-in button (e.g. `app/login.tsx` or the More tab) to
   `router.push('/access')`. Keep `app/login.tsx` until you retire the old demo login.
3. **Tickets** – to use eligibility-priced tickets from the existing map/route screens, replace the
   `/ticket-purchase?network=1&route=…` navigation in `NetworkBusSheet` and `app/network/route/[route].tsx`
   with `/access/buy` (pass `route` and `vehicle` as params if you want them prefilled).
4. **Payment** – replace `POST /tickets/{id}/pay-demo` with the existing `/payment` flow (create a payment
   for `ticket.fare`, and on server-verified success mark the access ticket ISSUED).
5. **Conductor** – point the existing Conductor screen at `POST /api/access/conductor/ticket/verify`, or send
   conductors to `/access/conductor`.
6. **Production** – set `ACCESS_ENV=production`, real secrets, HTTPS (`ACCESS_COOKIE_SECURE=true`), a real
   SMS/email OTP gateway, an authorized identity provider and biometric provider, a real malware scanner,
   and replace the in-process rate limiter with Redis if you run several workers.
