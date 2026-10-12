# Request for official access to BMTC real-time bus data

Fill in everything in **[square brackets]**, then send it as a letter or email (see "How to send" at the end).

---

**To**
The Managing Director
Bengaluru Metropolitan Transport Corporation (BMTC)
Central Offices, K.H. Road, Shanthinagar
Bengaluru – 560027

**Copy to:** Chief Traffic Manager (Operations) / Head of IT / ITS (Intelligent Transport System) division, BMTC

**Date:** [DD Month YYYY]

**Subject:** Request for authorised access to BMTC real-time vehicle location data (GTFS-Realtime or API) for the "ನಮ್ಮ Bus" passenger information app

Respected Sir / Madam,

I am **[Your full name]**, **[your role, e.g. student of Computer Science at XYZ College / founder of ABC]**, Bengaluru. I am developing **ನಮ್ಮ Bus**, a free passenger-information app for Bengaluru commuters (web and Android/iOS) that shows BMTC routes, stops, journey planning and live bus positions in **English and Kannada**.

**What the app does for BMTC passengers**
- Shows every BMTC route and stop (4,434 routes, 9,960 stops) with ordered stops for both directions.
- Shows where buses are right now, the next stop, and how far a bus has progressed on its route, so passengers wait less at stops.
- Clearly labels data freshness (Live / Recent / Stale) and never shows invented or simulated buses as real.
- Works offline for saved tickets and includes accessibility features (screen-reader labels, large text, Kannada).

**What I am requesting**
Authorised access to BMTC real-time data in any one of these forms, whichever BMTC prefers:
1. A **GTFS-Realtime** feed (VehiclePositions, and TripUpdates if available), or
2. Access to a BMTC **vehicle-position API** with an API key, or
3. Any other official data-sharing arrangement BMTC offers (e.g. through the ITS/Namma BMTC platform or the Karnataka open-data portal).

The fields needed are only operational data: vehicle registration number, route, trip/direction, latitude/longitude, timestamp and next stop. **No passenger or personal data is required.**

**How the data will be used and protected**
- **Purpose:** free public passenger information only. The data will not be sold or passed on to third parties.
- **Load on BMTC systems:** a single server fetches the data on a fixed schedule (for example once every 30 seconds) and shares it with app users through its own cache, so app users never call BMTC directly. I will follow any rate limit BMTC sets.
- **Security:** the API key will be kept only on the server, never inside the app, and will not be shared.
- **Attribution:** the app will credit "Data: BMTC" and follow any display or branding rules BMTC specifies. The app will not present itself as an official BMTC product.
- **Accuracy:** if BMTC data is delayed or unavailable, the app says so clearly instead of guessing.

**Transparency**
While building the app, I tested it against the publicly reachable endpoint used by the Namma BMTC app. When that endpoint began restricting automated requests, I stopped relying on it and am now requesting proper authorisation instead.

I am happy to sign a data-sharing agreement or terms of use, provide a demonstration of the app, share usage statistics, and pass on passenger feedback about stops or routes that could help BMTC.

Thank you for considering this request. I look forward to your guidance on the procedure.

Yours faithfully,

**[Your full name]**
**[Organisation / college, if any]**
**[Mobile number]** · **[Email address]**
**[Postal address]**
App demo: **[link or "available on request"]**

---

## How to send

1. **Find BMTC's current official email** on BMTC's website (mybmtc.karnataka.gov.in → Contact Us). Use only addresses published there.
2. **Send it** to the Managing Director's office, copying the IT/ITS division. Attach 2–3 screenshots of the app: the map, a route page and the ticket screen.
3. **Paper copy (optional but helpful):** post or hand-deliver a signed copy to BMTC Central Offices, K.H. Road, Shanthinagar, and get it acknowledged (inward number).
4. **If there's no reply in about 30 days,** you can file an **RTI application** asking for "the procedure and policy for third parties to obtain access to BMTC real-time vehicle location data". This often gets you the right contact.
5. **Also check** the Karnataka open-data portal and the Government of India open-data portal (data.gov.in) for any official BMTC datasets.

## When BMTC replies

Give the values BMTC sends to whoever runs the server (never paste keys into chats or commit them). In `namma-route/backend/.env`:

```
BMTC_API_BASE_URL="<official endpoint URL from BMTC>"
BMTC_API_KEY="<key from BMTC>"
BMTC_API_KEY_HEADER="<header name BMTC specifies, e.g. x-api-key or Authorization>"
BMTC_API_KEY_PREFIX=""   # e.g. "Bearer " if BMTC says so
```

If BMTC provides a **GTFS-Realtime (protobuf) feed** instead of the current JSON API, NammaRoute needs a small GTFS-RT reader added. Ask the developer to add it when the feed URL arrives.
