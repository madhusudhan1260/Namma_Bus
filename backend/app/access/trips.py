"""
Trips and the authoritative passenger counter.

`access_trips.passenger_count` is the only passenger count in the system. It changes only inside
`issue_into_trip` / `release_from_trip`, which lock the trip row (SELECT … FOR UPDATE) for the rest of the
transaction, so two tickets issued at the same moment are counted one after the other and the capacity check
always sees the latest committed value. A ticket is counted exactly once: when it becomes ISSUED (free ticket,
verified payment, or conductor cash ticket). Pending or failed payments are never counted. A revoked ticket
gives its seats back once.
"""

import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Bus, Ticket, TicketStatus, Trip
from .realtime import publish_after_commit

ORANGE_FROM = 0.70  # 70 % full → orange


class TripError(HTTPException):
    """409 with a machine-readable code: NO_ACTIVE_TRIP | TRIP_ENDED | BUS_FULL | CHOOSE_TRIP."""

    def __init__(self, code: str, message: str, trip: Optional[dict] = None) -> None:
        super().__init__(status_code=409, detail={"code": code, "message": message, "trip": trip})
        self.code = code


def norm_route(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def occupancy_state(count: int, capacity: int) -> str:
    if capacity <= 0 or count >= capacity:
        return "FULL"
    return "FILLING" if count >= capacity * ORANGE_FROM else "AVAILABLE"


def seq_of(trip: Trip) -> int:
    ts = _utc(trip.updated_at) or _utc(trip.started_at)
    return int(ts.timestamp() * 1_000_000) if ts else 0


def public_trip_view(trip: Trip, bus: Optional[Bus]) -> dict:
    """What any signed-in user may see about a trip. Counts only — never who the passengers are."""
    count, cap = int(trip.passenger_count or 0), int(trip.max_capacity or 0)
    return {
        "trip_id": trip.id,
        "trip_code": trip.trip_code,
        "route": trip.route,
        "direction": trip.direction,
        "bus_id": trip.bus_id,
        "bus_label": bus.fleet_label if bus else None,
        "vehicle_number": bus.registration_number if bus else None,
        "status": trip.status,
        "passenger_count": count,
        "max_capacity": cap,
        "seats_left": max(cap - count, 0),
        "occupancy": occupancy_state(count, cap),
        "started_at": _utc(trip.started_at).isoformat() if trip.started_at else None,
        "ended_at": _utc(trip.ended_at).isoformat() if trip.ended_at else None,
        "updated_at": (_utc(trip.updated_at) or _utc(trip.started_at)).isoformat(),
        "seq": seq_of(trip),
    }


def trip_topics(trip: Trip) -> List[str]:
    topics = [f"trip:{trip.id}", "admin"]
    if trip.route:
        topics.append(f"route:{norm_route(trip.route)}")
    if trip.bus_id:
        topics.append(f"bus:{trip.bus_id}")
    return topics


def publish_trip(db: Session, trip: Trip, event_type: str = "PASSENGER_COUNT_UPDATED") -> None:
    """Broadcast this trip's committed state once the current transaction commits."""
    bus = db.get(Bus, trip.bus_id) if trip.bus_id else None
    bus_info = Bus(id=bus.id, fleet_label=bus.fleet_label, registration_number=bus.registration_number) if bus else None

    def build():
        view = public_trip_view(trip, bus_info)
        # flat fields for simple clients + the full public view; never anything about individual passengers
        return trip_topics(trip), {"type": event_type, "event": event_type, "trip_id": trip.id, "route": trip.route,
                                   "passenger_count": view["passenger_count"], "max_capacity": view["max_capacity"],
                                   "timestamp": view["updated_at"], "trip": view}

    publish_after_commit(db, f"trip:{trip.id}", build)


def lock_trip(db: Session, trip_id: str) -> Optional[Trip]:
    """SELECT … FOR NO KEY UPDATE: serialises every change to this trip's counter, but does not conflict with the
    KEY SHARE lock PostgreSQL takes when a ticket row referencing the trip is inserted (plain FOR UPDATE would
    deadlock two transactions that each inserted a ticket and then wait for the trip lock).
    populate_existing overwrites any stale copy in this session with the locked, current row."""
    return db.scalars(select(Trip).where(Trip.id == trip_id).with_for_update(key_share=True)
                      .execution_options(populate_existing=True)).first()


def issue_into_trip(db: Session, ticket: Ticket, trip_id: Optional[str]) -> Trip:
    """Atomically count `ticket` into the trip and mark it ISSUED. Raises TripError (and changes nothing) when the
    trip is missing, has ended or has no room. The caller's transaction commit makes both changes visible together."""
    if not trip_id:
        raise TripError("NO_ACTIVE_TRIP", "This bus has no active trip. Tickets can be issued only while a trip is running.")
    trip = lock_trip(db, trip_id)
    if not trip:
        raise TripError("NO_ACTIVE_TRIP", "Trip not found.")
    if trip.status != "ACTIVE":
        raise TripError("TRIP_ENDED", "This trip has ended.", public_trip_view(trip, db.get(Bus, trip.bus_id) if trip.bus_id else None))
    seats = int(ticket.passenger_count or 1)
    if trip.passenger_count + seats > trip.max_capacity:
        view = public_trip_view(trip, db.get(Bus, trip.bus_id) if trip.bus_id else None)
        left = max(trip.max_capacity - trip.passenger_count, 0)
        raise TripError("BUS_FULL", "This bus is currently full." if left == 0 else f"Only {left} seat(s) left on this bus.", view)
    now = datetime.now(timezone.utc)
    trip.passenger_count += seats
    trip.tickets_issued += 1
    trip.updated_at = max(now, (_utc(trip.updated_at) or now))
    ticket.trip_id, ticket.bus_id = trip.id, trip.bus_id
    ticket.status, ticket.issued_at = TicketStatus.ISSUED, now
    db.flush()
    publish_trip(db, trip)
    _capacity_alerts(db, trip)
    return trip


NEARLY_FULL_FROM = 0.90


def _capacity_alerts(db: Session, trip: Trip) -> None:
    """Tell the conductor once per trip when the bus is nearly full and when it is full."""
    from .notifications import notify

    code = trip.trip_code or trip.id
    data = {"trip_id": trip.id, "route": trip.route, "passenger_count": trip.passenger_count, "max_capacity": trip.max_capacity}
    if trip.passenger_count >= trip.max_capacity:
        notify(db, trip.conductor_id, "BUS_FULL", f"Bus {trip.route} is full",
               f"{trip.passenger_count}/{trip.max_capacity} on trip {code}. No more tickets can be issued.", data, f"bus-full-{trip.id}")
    elif trip.passenger_count >= trip.max_capacity * NEARLY_FULL_FROM:
        notify(db, trip.conductor_id, "BUS_NEARLY_FULL", f"Bus {trip.route} is nearly full",
               f"{trip.passenger_count}/{trip.max_capacity} on trip {code}.", data, f"bus-nearly-full-{trip.id}")


def release_from_trip(db: Session, ticket: Ticket) -> Optional[Trip]:
    """Give back the seats of a counted ticket (revoked / refunded). Never goes below zero."""
    if not ticket.trip_id or ticket.issued_at is None:
        return None
    trip = lock_trip(db, ticket.trip_id)
    if not trip:
        return None
    now = datetime.now(timezone.utc)
    trip.passenger_count = max(int(trip.passenger_count) - int(ticket.passenger_count or 1), 0)
    trip.updated_at = max(now, (_utc(trip.updated_at) or now))
    db.flush()
    publish_trip(db, trip)
    return trip


def active_trips(db: Session, route: Optional[str] = None, bus_id: Optional[str] = None) -> List[Trip]:
    q = select(Trip).where(Trip.status == "ACTIVE")
    if bus_id:
        q = q.where(Trip.bus_id == bus_id)
    rows = db.scalars(q.order_by(Trip.started_at.desc())).all()
    if route:
        rows = [t for t in rows if norm_route(t.route) == norm_route(route)]
    return list(rows)


def resolve_trip_for_ticket(db: Session, route: str, trip_id: Optional[str], vehicle_number: Optional[str]) -> Trip:
    """Which running trip a passenger's ticket goes into: the one they chose, or the bus they named, or the only
    active trip on the route. Never a guess between several buses."""
    if trip_id:
        trip = db.get(Trip, trip_id)
        if not trip or trip.status != "ACTIVE":
            raise TripError("TRIP_ENDED" if trip else "NO_ACTIVE_TRIP", "That trip is not running any more. Choose another bus.")
        if norm_route(trip.route) != norm_route(route):
            raise HTTPException(status_code=409, detail={"code": "WRONG_ROUTE", "message": f"That trip runs route {trip.route}."})
        return trip
    if vehicle_number:
        reg = norm_route(vehicle_number)
        bus = db.scalars(select(Bus).where(func.upper(Bus.registration_number) == reg)).first()
        trips = active_trips(db, route=route, bus_id=bus.id) if bus else []
        if not trips:
            raise TripError("NO_ACTIVE_TRIP", f"Bus {vehicle_number} has no active trip on route {route} right now.")
        return trips[0]
    trips = active_trips(db, route=route)
    if not trips:
        raise TripError("NO_ACTIVE_TRIP", f"No bus on route {route} has an active trip right now. Try again when the bus starts its trip.")
    if len(trips) > 1:
        raise HTTPException(status_code=409, detail={
            "code": "CHOOSE_TRIP", "message": "Several buses are running this route. Choose your bus.",
            "trips": [public_trip_view(t, db.get(Bus, t.bus_id) if t.bus_id else None) for t in trips]})
    return trips[0]


def new_trip_code(db: Session, route: Optional[str], now: datetime) -> str:
    """TRIP-YYYYMMDD-<ROUTE>-NNN, numbered per route per day."""
    day = now.strftime("%Y%m%d")
    prefix = f"TRIP-{day}-{norm_route(route) or 'NA'}-"
    taken = db.scalars(select(Trip.trip_code).where(Trip.trip_code.like(f"{prefix}%"))).all()
    nums = [int(c.rsplit("-", 1)[1]) for c in taken if c and c.rsplit("-", 1)[1].isdigit()]
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


def snapshot_for_topic(db: Session, topic: str) -> dict:
    """Current committed state for a topic, sent to a client when it (re)subscribes."""
    kind, _, value = topic.partition(":")
    if kind == "trip":
        trip = db.get(Trip, value)
        trips = [trip] if trip else []
    elif kind == "route":
        trips = active_trips(db, route=value)
    elif kind == "bus":
        trips = active_trips(db, bus_id=value)
    else:  # admin
        trips = active_trips(db)
    views = [public_trip_view(t, db.get(Bus, t.bus_id) if t.bus_id else None) for t in trips]
    return {"type": "SNAPSHOT", "topic": topic, "trips": views, "at": datetime.now(timezone.utc).isoformat()}
