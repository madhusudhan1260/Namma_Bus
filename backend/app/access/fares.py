"""
Fare calculation for access-module tickets. Always server-side.

NammaRouteFareProvider reuses the existing Namma Bus → NammaRoute integration (the imported BMTC GTFS
network): the route must exist, and both stops must be on it in the chosen direction with the boarding stop
before the destination.

Ordinary (non-AC) services are priced from the BMTC revised stage-fare table below: the journey distance is
measured along the route through every stop between boarding and destination, converted to 2 km chargeable
stages, and looked up for the passenger category (Adult / Child / Senior Citizen). AC services (Vajra,
Vayu Vajra) are not covered by that table and keep the clearly-labelled DEMO_FARE_ESTIMATE.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException

DEMO_FARE_BY_SERVICE_TYPE = {"ORDINARY": 25, "BIG10": 25, "METRO_FEEDER": 15, "VAJRA": 50, "VAYU_VAJRA": 240}

# BMTC revised fare table (ordinary services). Row n = chargeable stage n = up to 2n km.
# Columns: (Adult, Child, Senior Citizen) in rupees.
STAGE_KM = 2.0
STAGE_FARES: List[Tuple[int, int, int]] = [
    (6, 3, 5), (12, 6, 9), (18, 9, 14), (23, 12, 18), (23, 12, 18),            # stages 1–5   (≤ 10 km)
    (24, 12, 18), (24, 12, 18), (28, 14, 21), (28, 14, 21), (28, 14, 21),      # stages 6–10  (≤ 20 km)
    (30, 15, 23), (30, 15, 23), (30, 15, 23), (30, 15, 23), (30, 15, 23),      # stages 11–15 (≤ 30 km)
    (30, 15, 23), (30, 15, 23), (30, 15, 23), (30, 15, 23), (30, 15, 23),      # stages 16–20 (≤ 40 km)
    (32, 16, 24), (32, 16, 24), (32, 16, 24), (32, 16, 24), (32, 16, 24),      # stages 21–25 (≤ 50 km)
]
FARE_CATEGORIES = ("ADULT", "CHILD", "SENIOR")
STAGE_TABLE_SERVICES = {"ORDINARY", "BIG10", "METRO_FEEDER"}
STAGE_FARE_SOURCE = "BMTC_STAGE_FARE_TABLE"


def stage_for_distance(distance_km: float) -> int:
    """2.0 km → stage 1, 2.1 km → stage 2 … Journeys longer than the table use its last stage."""
    return min(max(1, math.ceil(round(distance_km, 3) / STAGE_KM)), len(STAGE_FARES))


def stage_fares(distance_km: float) -> Dict[str, int]:
    adult, child, senior = STAGE_FARES[stage_for_distance(distance_km) - 1]
    return {"ADULT": adult, "CHILD": child, "SENIOR": senior}


def _haversine_km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (float(a["latitude"]), float(a["longitude"]), float(b["latitude"]), float(b["longitude"])))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def route_distance_km(stops: List[dict]) -> Optional[float]:
    """Distance travelled from the first to the last stop of `stops` (in route order), stop by stop."""
    try:
        return sum(_haversine_km(stops[i], stops[i + 1]) for i in range(len(stops) - 1))
    except (KeyError, TypeError, ValueError):
        return None


@dataclass
class FareQuote:
    route: str
    direction: int
    from_stop_id: str
    from_stop: str
    to_stop_id: str
    to_stop: str
    unit_fare: int  # adult fare
    source: str  # BMTC_STAGE_FARE_TABLE | GTFS_FARE_RULES | DEMO_FARE_ESTIMATE
    distance_km: Optional[float] = None
    stage: Optional[int] = None
    fares: Dict[str, int] = field(default_factory=dict)  # per category, when the stage table applies

    def fare_for(self, category: str) -> int:
        return self.fares.get(category, self.unit_fare)


class FareProvider(ABC):
    @abstractmethod
    async def quote(self, route: str, direction: Optional[int], from_stop_id: str, to_stop_id: str) -> FareQuote: ...


class NammaRouteFareProvider(FareProvider):
    async def _stops(self, route: str, direction: int) -> List[dict]:
        from ..services.nammaroute_client import nammaroute_client

        data = (await nammaroute_client.get(f"/routes/{route}/stops", {"direction": direction}, ttl=300)).get("data")
        return data if isinstance(data, list) else (data or {}).get("stops", [])

    async def quote(self, route: str, direction: Optional[int], from_stop_id: str, to_stop_id: str) -> FareQuote:
        from ..services.nammaroute_client import NetworkNotFound, NetworkUnavailable, nammaroute_client

        try:
            detail = (await nammaroute_client.get(f"/routes/{route}", ttl=300)).get("data") or {}
            directions = [direction] if direction in (0, 1) else [0, 1]
            chosen = None
            for d in directions:
                stops = await self._stops(route, d)
                ids = [str(s.get("id") or s.get("stopId")) for s in stops]
                if from_stop_id in ids and to_stop_id in ids and ids.index(from_stop_id) < ids.index(to_stop_id):
                    i, j = ids.index(from_stop_id), ids.index(to_stop_id)
                    chosen = (d, stops[i], stops[j], stops[i : j + 1])
                    break
        except NetworkNotFound:
            raise HTTPException(status_code=400, detail=f"Route '{route}' does not exist in the BMTC network.")
        except NetworkUnavailable:
            raise HTTPException(status_code=503, detail="BMTC route network service is unavailable; fare cannot be calculated.")
        if not chosen:
            raise HTTPException(
                status_code=400,
                detail="The selected stops are not on this route in this direction (boarding stop must come before the destination).",
            )
        d, from_stop, to_stop, segment = chosen
        common = dict(route=str(detail.get("routeNumber") or route), direction=d, from_stop_id=from_stop_id,
                      from_stop=str(from_stop.get("name") or from_stop_id), to_stop_id=to_stop_id,
                      to_stop=str(to_stop.get("name") or to_stop_id))
        service = str(detail.get("serviceType") or "ORDINARY").upper()
        distance = route_distance_km(segment)
        if service in STAGE_TABLE_SERVICES and distance is not None:
            fares = stage_fares(distance)
            return FareQuote(**common, unit_fare=fares["ADULT"], source=STAGE_FARE_SOURCE, distance_km=round(distance, 2),
                             stage=stage_for_distance(distance), fares=fares)
        unit, source = None, "DEMO_FARE_ESTIMATE"
        try:
            body = await nammaroute_client.get("/fares", {"from": from_stop_id, "to": to_stop_id, "route": route}, ttl=3600)
            amount = (body.get("data") or {}).get("fareAmount")
            if amount is not None:
                unit, source = int(round(float(amount))), "GTFS_FARE_RULES"
        except NetworkNotFound:
            pass
        except NetworkUnavailable:
            raise HTTPException(status_code=503, detail="BMTC route network service is unavailable; fare cannot be calculated.")
        if unit is None:
            unit = DEMO_FARE_BY_SERVICE_TYPE.get(service, 25)
        return FareQuote(**common, unit_fare=unit, source=source, distance_km=round(distance, 2) if distance is not None else None)


_override: Optional[FareProvider] = None


def get_fare_provider() -> FareProvider:
    return _override or NammaRouteFareProvider()


def set_fare_provider(provider: Optional[FareProvider]) -> None:
    global _override
    _override = provider
