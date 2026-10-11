"""
Facilities near BMTC bus stations and near the user, from OpenStreetMap (Overpass API).

BMTC's own facility register is not available to Namma Bus, so this uses real community-mapped OpenStreetMap
data (toilets, pharmacies, ATMs, drinking water, parking, police, hospitals/clinics, food) and labels it as such.
Results are cached (stations: 24 h, near-me: 10 min) to keep load on the free Overpass servers low; when every
server is busy the API says so instead of returning anything made up.
"""

import asyncio
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
USER_AGENT = "NammaBus/1.0 (Bengaluru public transport app; facilities lookup)"
SOURCE = "OpenStreetMap contributors (via Overpass API) — community data, may be incomplete"

# OSM tag → our category
CATEGORY = {
    ("amenity", "toilets"): "TOILETS",
    ("amenity", "pharmacy"): "MEDICAL",
    ("shop", "chemist"): "MEDICAL",
    ("amenity", "atm"): "ATM",
    ("amenity", "bank"): "ATM",
    ("amenity", "drinking_water"): "WATER",
    ("amenity", "parking"): "PARKING",
    ("amenity", "bicycle_parking"): "PARKING",
    ("amenity", "police"): "POLICE",
    ("amenity", "hospital"): "HOSPITAL",
    ("amenity", "clinic"): "HOSPITAL",
    ("amenity", "doctors"): "HOSPITAL",
    ("amenity", "restaurant"): "FOOD",
    ("amenity", "cafe"): "FOOD",
    ("amenity", "fast_food"): "FOOD",
}
_AMENITY_RE = "^(toilets|pharmacy|atm|bank|drinking_water|parking|bicycle_parking|police|hospital|clinic|doctors|restaurant|cafe|fast_food)$"

# Major BMTC bus stations / TTMCs (names as in the BMTC stop data; coordinates are resolved from the network)
MAJOR_STATIONS = [
    "Kempegowda Bus Station", "Shivajinagara Bus Station", "Kengeri", "Vijayanagara", "Banashankari", "Yeshwanthapura",
    "Jayanagar", "K R Market", "Shanthinagara", "Hebbala", "White Field Bus Station", "Electronic City", "Domlur",
    "Kempegowda International Airport", "Koramangala", "Marathahalli",
]

_cache: Dict[str, Tuple[float, Any]] = {}


def _cached(key: str, ttl: float) -> Optional[Any]:
    hit = _cache.get(key)
    return hit[1] if hit and time.time() - hit[0] < ttl else None


def distance_m(a: Tuple[float, float], b: Tuple[float, float]) -> int:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return int(6371000 * 2 * math.asin(math.sqrt(h)))


async def _overpass(query: str) -> Optional[List[dict]]:
    async with httpx.AsyncClient(timeout=45, headers={"User-Agent": USER_AGENT}) as client:
        for url in OVERPASS_SERVERS:
            try:
                r = await client.post(url, data={"data": query})
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                    return r.json().get("elements", [])
            except (httpx.HTTPError, ValueError):
                continue
    return None


def _to_place(e: dict) -> Optional[dict]:
    tags = e.get("tags") or {}
    cat = next((c for (k, v), c in CATEGORY.items() if tags.get(k) == v), None)
    lat = e.get("lat") or (e.get("center") or {}).get("lat")
    lon = e.get("lon") or (e.get("center") or {}).get("lon")
    if not cat or lat is None or lon is None:
        return None
    return {"id": f"{e.get('type')}/{e.get('id')}", "category": cat, "name": tags.get("name") or tags.get("name:en"),
            "latitude": lat, "longitude": lon, "phone": tags.get("phone") or tags.get("contact:phone"),
            "opening_hours": tags.get("opening_hours")}


async def _station_facilities(st: dict, radius: int) -> Optional[List[dict]]:
    key = f"station:{st['name']}:{radius}"
    cached = _cached(key, 24 * 3600)
    if cached is not None:
        return cached
    if _cached(f"failed:{key}", 30 * 60):  # don't hammer busy servers for a station that just failed
        return None
    elements = await _overpass(f'[out:json][timeout:25];nwr(around:{radius},{st["latitude"]},{st["longitude"]})[amenity~"{_AMENITY_RE}"];out center 300;')
    if elements is None:
        _cache[f"failed:{key}"] = (time.time(), True)
        return None
    here = []
    for p in (_to_place(e) for e in elements):
        if p:
            d = distance_m((st["latitude"], st["longitude"]), (p["latitude"], p["longitude"]))
            if d <= radius:
                here.append({**p, "distance_m": d})
    here.sort(key=lambda p: p["distance_m"])
    _cache[key] = (time.time(), here)
    return here


async def stations_facilities(resolve_station, radius: int = 350) -> Dict[str, Any]:
    """Facilities within `radius` m of each major bus station. `resolve_station(name)` → stop dict or None.
    One small Overpass query per station (3 at a time), each cached for 24 h; stations whose query failed are
    simply omitted (never invented)."""
    cached = _cached("stations", 6 * 3600) or _cached("stations_partial", 30 * 60)
    if cached:
        return cached
    stations = []
    for name in MAJOR_STATIONS:
        stop = await resolve_station(name)
        if stop:
            stations.append({"name": stop["name"], "query": name, "latitude": stop["latitude"], "longitude": stop["longitude"]})
    if not stations:
        return {"available": False, "source": SOURCE, "stations": []}
    sem = asyncio.Semaphore(3)

    async def one(st):
        async with sem:
            return st, await _station_facilities(st, radius)

    out = []
    for st, here in await asyncio.gather(*(one(s) for s in stations)):
        if here is None:
            continue
        st["facilities"] = here
        st["counts"] = {c: sum(1 for p in here if p["category"] == c) for c in sorted({p["category"] for p in here})}
        out.append(st)
    if not out:
        return {"available": False, "source": SOURCE, "stations": [], "message": "OpenStreetMap servers are busy right now. Please try again shortly."}
    result = {"available": True, "source": SOURCE, "radius_m": radius, "stations": out, "partial": len(out) < len(stations)}
    _cache["stations" if not result["partial"] else "stations_partial"] = (time.time(), result)
    return result


async def near(lat: float, lng: float, radius: int, categories: List[str]) -> Dict[str, Any]:
    """Facilities of the given categories near a point (e.g. hospitals and police for the Emergency screen)."""
    key = f"near:{round(lat, 3)}:{round(lng, 3)}:{radius}:{','.join(sorted(categories))}"
    cached = _cached(key, 600)
    if cached:
        return cached
    elements = await _overpass(f'[out:json][timeout:25];nwr(around:{radius},{lat},{lng})[amenity~"{_AMENITY_RE}"];out center 400;')
    if elements is None:
        return {"available": False, "source": SOURCE, "places": [], "message": "OpenStreetMap servers are busy right now. Please try again shortly."}
    places = []
    for p in (_to_place(e) for e in elements):
        if p and (not categories or p["category"] in categories):
            places.append({**p, "distance_m": distance_m((lat, lng), (p["latitude"], p["longitude"]))})
    places.sort(key=lambda p: p["distance_m"])
    result = {"available": True, "source": SOURCE, "places": places[:60]}
    _cache[key] = (time.time(), result)
    return result
