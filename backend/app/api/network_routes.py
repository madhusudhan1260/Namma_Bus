"""
/api/network/* — the complete BMTC network inside ನಮ್ಮ Bus (served from NammaRoute's PostgreSQL backend).

Every response states its data source. When NammaRoute is down the endpoints answer 503 with a plain
message; the rest of ನಮ್ಮ Bus keeps working. Vehicles are passed through from NammaRoute only — no
vehicle, position or freshness is created here.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..core.config import OPERATIONAL_STATEMENT_NOT_CONNECTED
from ..services.nammaroute_client import NetworkNotFound, NetworkUnavailable, nammaroute_client

router = APIRouter(prefix="/network", tags=["BMTC Network"])

STATIC_SOURCE = "GTFS_STATIC (bmtc-gtfs via NammaRoute)"
FRESHNESS = {"LIVE", "RECENT", "STALE"}


class NetworkStopRef(BaseModel):
    stop_id: Optional[str] = None
    stop_name: Optional[str] = None
    sequence: Optional[int] = None
    distance_meters: Optional[int] = None


class NetworkVehicle(BaseModel):
    vehicle_id: str
    vehicle_number: Optional[str] = None
    route_id: Optional[str] = None
    route_number: Optional[str] = None
    latitude: float
    longitude: float
    bearing: Optional[float] = None
    speed_kmh: Optional[float] = None
    timestamp: Optional[str] = None
    freshness: str  # LIVE | RECENT | STALE
    freshness_seconds: Optional[int] = None
    source: str = "BMTC_REALTIME_VIA_NAMMAROUTE"
    direction: Optional[int] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    stop_status: Optional[str] = None
    current_stop: Optional[NetworkStopRef] = None
    next_stop: Optional[NetworkStopRef] = None
    total_stops: Optional[int] = None
    completed_stops: Optional[int] = None
    remaining_stops: Optional[int] = None
    progress_percentage: Optional[int] = None


class NetworkVehiclesResponse(BaseModel):
    realtime_status: str  # LIVE | DATA_DELAYED | UNAVAILABLE | NETWORK_OFFLINE
    live_connected: bool
    operational_statement: Optional[str] = None
    error: Optional[str] = None
    count: int
    counts_by_freshness: Dict[str, int]
    excluded: int
    generated_at: str
    vehicles: List[NetworkVehicle]


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc) or "BMTC route network service is unavailable right now.")


def _stop_ref(raw: Any) -> Optional[NetworkStopRef]:
    if not isinstance(raw, dict):
        return None
    return NetworkStopRef(
        stop_id=raw.get("stopId"),
        stop_name=raw.get("stopName"),
        sequence=raw.get("sequence"),
        distance_meters=raw.get("distanceMeters"),
    )


def normalize_vehicle(raw: Dict[str, Any]) -> Optional[NetworkVehicle]:
    """Maps a NammaRoute NormalizedVehicle. Anything without id, coordinates or a known freshness is dropped."""
    try:
        vid = str(raw.get("id") or "").strip()
        lat, lon = float(raw["latitude"]), float(raw["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    freshness = str(raw.get("status") or "").upper()
    if not vid or freshness not in FRESHNESS:
        return None
    return NetworkVehicle(
        vehicle_id=vid,
        vehicle_number=raw.get("vehicleNumber"),
        route_id=raw.get("routeId"),
        route_number=raw.get("routeNumber"),
        latitude=lat,
        longitude=lon,
        bearing=raw.get("bearing"),
        speed_kmh=raw.get("speed"),
        timestamp=raw.get("timestamp"),
        freshness=freshness,
        freshness_seconds=raw.get("freshnessSeconds"),
        direction=raw.get("direction"),
        origin=raw.get("origin"),
        destination=raw.get("destination"),
        stop_status=raw.get("stopStatus"),
        current_stop=_stop_ref(raw.get("currentStop")),
        next_stop=_stop_ref(raw.get("nextStop")),
        total_stops=raw.get("totalStops"),
        completed_stops=raw.get("completedStops"),
        remaining_stops=raw.get("remainingStops"),
        progress_percentage=raw.get("progressPercentage"),
    )


@router.get("/status", summary="BMTC Network & Realtime Status")
async def network_status():
    try:
        stats = (await nammaroute_client.get("/data/stats", ttl=300)).get("data", {})
    except NetworkUnavailable as exc:
        return {
            "network_connected": False,
            "message": str(exc),
            "live_connected": False,
            "operational_statement": OPERATIONAL_STATEMENT_NOT_CONNECTED,
        }
    try:
        rt = await nammaroute_client.get("/realtime/status", ttl=10)
    except NetworkUnavailable:
        rt = {}
    live = bool(rt.get("reachable")) and int(rt.get("vehicleCount") or 0) > 0
    return {
        "network_connected": True,
        "static_source": STATIC_SOURCE,
        "routes": stats.get("routes"),
        "stops": stats.get("stops"),
        "variants": stats.get("variants"),
        "trips": stats.get("trips"),
        "network_scope": stats.get("networkScope"),
        "data_source": stats.get("dataSource"),
        "last_import": stats.get("lastImport"),
        "realtime_provider": rt.get("provider"),
        "realtime_reachable": bool(rt.get("reachable")),
        "realtime_vehicle_count": rt.get("vehicleCount", 0),
        "realtime_error": rt.get("error"),
        "live_connected": live,
        "operational_statement": None if live else OPERATIONAL_STATEMENT_NOT_CONNECTED,
    }


@router.get("/routes", summary="Search BMTC Routes")
async def network_routes(q: str = Query(default="", max_length=64), limit: int = Query(default=30, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    try:
        data = (await nammaroute_client.get("/routes", {"q": q.strip(), "limit": limit, "offset": offset}, ttl=120)).get("data", {})
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    return {"source": STATIC_SOURCE, **data}


@router.get("/routes/{route}", summary="BMTC Route Details (directions, geometry, ordered stops)")
async def network_route(route: str):
    try:
        data = (await nammaroute_client.get(f"/routes/{route}", ttl=300)).get("data")
    except NetworkNotFound:
        raise HTTPException(status_code=404, detail=f"Route '{route}' not found in the BMTC network")
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    return {"source": STATIC_SOURCE, "route": data}


@router.get("/routes/{route}/stops", summary="Ordered Stops For A Direction")
async def network_route_stops(route: str, direction: int = Query(default=0, ge=0, le=1)):
    try:
        data = (await nammaroute_client.get(f"/routes/{route}/stops", {"direction": direction}, ttl=300)).get("data")
    except NetworkNotFound:
        raise HTTPException(status_code=404, detail=f"Route '{route}' not found in the BMTC network")
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    return {"source": STATIC_SOURCE, "route": route, "direction": direction, "stops": data if isinstance(data, list) else (data or {}).get("stops", [])}


@router.get("/stops", summary="Search BMTC Stops")
async def network_stops(q: str = Query(default="", max_length=64), limit: int = Query(default=20, ge=1, le=100)):
    try:
        data = (await nammaroute_client.get("/stops/search", {"q": q.strip(), "limit": limit}, ttl=120)).get("data", {})
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    return {"source": STATIC_SOURCE, **(data if isinstance(data, dict) else {"stops": data})}


@router.get("/search", summary="Search Routes And Stops")
async def network_search(q: str = Query(..., min_length=1, max_length=64)):
    try:
        routes = (await nammaroute_client.get("/routes", {"q": q.strip(), "limit": 20}, ttl=120)).get("data", {})
        stops = (await nammaroute_client.get("/stops/search", {"q": q.strip(), "limit": 10}, ttl=120)).get("data", {})
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    return {
        "source": STATIC_SOURCE,
        "query": q,
        "routes": routes.get("routes", []),
        "routes_total": routes.get("total", 0),
        "stops": stops.get("stops", []) if isinstance(stops, dict) else stops,
    }


@router.get("/journey", summary="Plan A BMTC Journey")
async def network_journey(from_: str = Query(..., alias="from", min_length=1, max_length=80), to: str = Query(..., min_length=1, max_length=80)):
    try:
        body = await nammaroute_client.get("/journey", {"from": from_, "to": to}, ttl=300)
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    plans = body.get("plans") or body.get("data") or []
    # The GTFS import contains BMTC's internal test entries (e.g. "EXP Test AFCS"); never offer them to passengers
    plans = [p for p in plans if not any(re.search(r"\btest\b", str(l.get("routeNumber") or ""), re.I) for l in (p.get("legs") or []))]
    return {"source": STATIC_SOURCE, "from": body.get("from"), "to": body.get("to"), "count": len(plans), "plans": plans}


@router.get("/routes/{route}/timetable", summary="Scheduled Departures For A Route (BMTC GTFS)")
async def network_route_timetable(route: str):
    """Scheduled trip departures from the BMTC GTFS timetable, grouped by direction. Scheduled, not live."""
    try:
        data = (await nammaroute_client.get(f"/routes/{route}/timetable", ttl=3600)).get("data") or []
    except NetworkNotFound:
        raise HTTPException(status_code=404, detail=f"Route '{route}' does not exist in the BMTC network.")
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    directions: Dict[int, Dict[str, Any]] = {}
    for trip in data:
        d = int(trip.get("direction") or 0)
        bucket = directions.setdefault(d, {"direction": d, "headsign": trip.get("tripHeadsign"), "from": trip.get("originStop"), "departures": []})
        dep = (trip.get("departureTime") or "")[:5]
        if dep and dep not in bucket["departures"]:
            bucket["departures"].append(dep)
    for b in directions.values():
        b["departures"].sort()
    return {"source": "BMTC GTFS timetable (scheduled; actual times may vary)", "route": route,
            "directions": [directions[k] for k in sorted(directions)]}


@router.get("/fare-estimate", summary="Fare Between Two Places (BMTC stage-fare chart)")
async def network_fare_estimate(from_: str = Query(..., alias="from", min_length=2, max_length=80), to: str = Query(..., min_length=2, max_length=80)):
    """Journey options between two places with the BMTC stage fare for Adult / Child / Senior on each option.
    Each bus in a journey is a separate ticket, so multi-bus options add up per leg."""
    from ..access.fares import get_fare_provider

    journey = await network_journey(from_=from_, to=to)
    options = []
    for plan in (journey.get("plans") or [])[:4]:
        legs_out, totals, ok = [], {"ADULT": 0, "CHILD": 0, "SENIOR": 0}, True
        for leg in plan.get("legs") or []:
            fs, ts = (leg.get("fromStop") or {}).get("id"), (leg.get("toStop") or {}).get("id")
            if not (leg.get("routeNumber") and fs and ts):
                ok = False
                break
            try:
                q = await get_fare_provider().quote(leg["routeNumber"], None, str(fs), str(ts))
            except HTTPException:
                ok = False
                break
            fares = q.fares or {k: q.unit_fare for k in totals}
            for k in totals:
                totals[k] += int(fares.get(k, 0))
            legs_out.append({"route": q.route, "from": q.from_stop, "to": q.to_stop, "distance_km": q.distance_km, "stage": q.stage,
                             "fares": fares, "source": q.source})
        if ok and legs_out:
            options.append({"legs": legs_out, "totals": totals, "minutes": plan.get("totalDurationMinutes"),
                            "estimate": any(l["source"] != "BMTC_STAGE_FARE_TABLE" for l in legs_out)})
    return {"source": "BMTC stage-fare chart (ordinary services)", "from": journey.get("from"), "to": journey.get("to"), "options": options}


@router.get("/facilities", summary="Facilities Near Major Bus Stations (OpenStreetMap)")
async def network_facilities():
    from ..services.facilities import stations_facilities

    async def resolve(name: str):
        try:
            data = (await nammaroute_client.get("/stops/search", {"q": name, "limit": 5}, ttl=86400)).get("data", {})
        except (NetworkUnavailable, NetworkNotFound):
            return None
        stops = data.get("stops", []) if isinstance(data, dict) else (data or [])
        ql = name.lower()
        match = next((s for s in stops if ql in (s.get("name") or "").lower()), None)
        return match

    return await stations_facilities(resolve)


@router.get("/facilities/near", summary="Facilities Near A Point (OpenStreetMap)")
async def network_facilities_near(lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180),
                                  radius: int = Query(default=2000, ge=100, le=5000), types: str = Query(default="", max_length=120)):
    from ..services.facilities import near

    cats = [t.strip().upper() for t in types.split(",") if t.strip()]
    return await near(round(lat, 4), round(lng, 4), radius, cats)


@router.get("/fare", summary="Fare Between Two Stops (GTFS fare rules)")
async def network_fare(from_: str = Query(..., alias="from", max_length=40), to: str = Query(..., max_length=40), route: Optional[str] = Query(default=None, max_length=32)):
    try:
        data = (await nammaroute_client.get("/fares", {"from": from_, "to": to, "route": route}, ttl=3600)).get("data")
    except NetworkNotFound:
        raise HTTPException(status_code=404, detail="No fare in the GTFS feed for this stop pair")
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    return data


@router.get("/vehicles", response_model=NetworkVehiclesResponse, summary="BMTC Buses (all, or one route)")
async def network_vehicles(route: Optional[str] = Query(default=None, max_length=32)):
    """No count limit. One shared upstream request per cache window (10 s)."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        if route:
            body = await nammaroute_client.get(f"/routes/{route}/vehicles", ttl=15)
            raw_list, status, error = body.get("data") or [], "LIVE" if body.get("data") else "UNAVAILABLE", None
        else:
            body = await nammaroute_client.get("/realtime/vehicles", ttl=10)
            raw_list = body.get("vehicles") or []
            status = str(body.get("status") or "UNAVAILABLE").replace(" ", "_")
            error = body.get("error")
    except NetworkNotFound:
        raise HTTPException(status_code=404, detail=f"Route '{route}' not found in the BMTC network")
    except NetworkUnavailable as exc:
        return NetworkVehiclesResponse(
            realtime_status="NETWORK_OFFLINE", live_connected=False, operational_statement=OPERATIONAL_STATEMENT_NOT_CONNECTED,
            error=str(exc), count=0, counts_by_freshness={"LIVE": 0, "RECENT": 0, "STALE": 0}, excluded=0, generated_at=now, vehicles=[],
        )
    vehicles = [v for v in (normalize_vehicle(r) for r in raw_list if isinstance(r, dict)) if v]
    live = len(vehicles) > 0
    return NetworkVehiclesResponse(
        realtime_status=status if live else "UNAVAILABLE",
        live_connected=live,
        operational_statement=None if live else OPERATIONAL_STATEMENT_NOT_CONNECTED,
        error=error,
        count=len(vehicles),
        counts_by_freshness={k: sum(1 for v in vehicles if v.freshness == k) for k in ("LIVE", "RECENT", "STALE")},
        excluded=len(raw_list) - len(vehicles),
        generated_at=now,
        vehicles=vehicles,
    )


@router.get("/stops/nearby", summary="BMTC Stops Near A Location")
async def network_stops_nearby(lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180),
                               radius: int = Query(default=800, ge=50, le=3000), limit: int = Query(default=10, ge=1, le=50)):
    try:
        data = (await nammaroute_client.get("/stops/nearby", {"lat": round(lat, 5), "lng": round(lng, 5), "radius": radius, "limit": limit}, ttl=120)).get("data") or []
    except NetworkUnavailable as exc:
        raise _unavailable(exc)
    data = data[:limit]
    return {"source": STATIC_SOURCE, "count": len(data), "stops": data}


class AssistantRequest(BaseModel):
    message: str
    lang: str = "EN"


@router.post("/assistant", summary="Assistant Answering From Real BMTC Data Only")
async def network_assistant(req: AssistantRequest):
    from ..services.network_assistant import Sources, answer

    async def route_detail(route: str):
        try:
            return (await nammaroute_client.get(f"/routes/{route}", ttl=300)).get("data")
        except NetworkNotFound:
            return None

    async def journey(a: str, b: str):
        return await network_journey(from_=a, to=b)

    async def stops(q: str):
        data = (await nammaroute_client.get("/stops/search", {"q": q, "limit": 8}, ttl=120)).get("data", {})
        return data.get("stops", []) if isinstance(data, dict) else (data or [])

    async def vehicles(route: Optional[str] = None):
        return await network_vehicles(route=route)

    async def stop_detail(stop_id: str):
        try:
            data = (await nammaroute_client.get(f"/stops/{stop_id}", ttl=300)).get("data")
            return data if isinstance(data, dict) else None
        except NetworkNotFound:
            return None

    async def fare(route: str, from_id: str, to_id: str):
        # The same server-side BMTC stage-fare pricing used for tickets
        from ..access.fares import get_fare_provider

        return await get_fare_provider().quote(route, None, from_id, to_id)

    message = (req.message or "")[:300]
    try:
        return await answer(message, req.lang.upper(), Sources(vehicles, route_detail, journey, stops, stop_detail, fare))
    except (NetworkUnavailable, HTTPException):
        from ..services.network_assistant import T

        return {"answer": T["KN" if req.lang.upper() == "KN" else "EN"]["offline"], "kind": "unavailable", "actions": [], "source": STATIC_SOURCE}
