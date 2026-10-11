"""
Conductor portal: ID + password/PIN login (accounts are created only by Super Admin), assigned bus and
route, live position of that bus from the BMTC feed (never invented), trips, and QR ticket validation.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..eligibility import current_identity_verification, effective_student_status, today_ist
from ..models import Bus, BusStatus, College, CollegeStatus, Conductor, PassengerProfile, Role, Ticket, TicketStatus, TicketVerification, Trip, User
from ..rbac import conductor_record, require_roles
from ..fares import get_fare_provider
from ..security import client_ip, decrypt_text, parse_and_verify_qr, rate_limiter, verify_password, verify_totp
from ..trips import issue_into_trip, new_trip_code, public_trip_view, publish_trip

router = APIRouter(tags=["Access: Conductor"])
REALTIME_UNAVAILABLE = "REALTIME DATA UNAVAILABLE"
MAX_FAILED_LOGINS = 5


def norm_route(value: Optional[str]) -> str:
    """365P, 365-P and 365 P are the same route number."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def norm_reg(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


class ConductorLogin(BaseModel):
    conductor_id: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    totp_code: Optional[str] = Field(default=None, max_length=8)


@router.post("/conductor/login")
def conductor_login(req: ConductorLogin, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    """Conductor ID + password/PIN. There is no public conductor registration."""
    from .auth import issue_session

    ip = client_ip(request)
    rate_limiter.check(f"conductor-login:{ip}", limit=settings.login_rate_limit_per_minute)
    c = db.scalars(select(Conductor).where(Conductor.employee_id == req.conductor_id.strip().upper())).first()
    user = db.get(User, c.user_id) if c else None
    now = datetime.now(timezone.utc)
    if user and user.locked_until and user.locked_until.replace(tzinfo=user.locked_until.tzinfo or timezone.utc) > now:
        raise HTTPException(status_code=423, detail="Account temporarily locked after repeated failed sign-ins. Try again later.")
    if not user or user.role != Role.CONDUCTOR or not user.is_active or not verify_password(req.password, user.password_hash):
        if user:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_logins = 0
        audit(db, "CONDUCTOR_LOGIN_FAILED", None, "conductor", req.conductor_id.strip().upper()[:32], None, ip, result="FAILURE",
              user_agent=request.headers.get("user-agent"))
        db.commit()
        raise HTTPException(status_code=401, detail="Incorrect Conductor ID or password.")
    if user.totp_secret_encrypted:
        if not req.totp_code:
            raise HTTPException(status_code=401, detail="Two-factor code required.", headers={"X-2FA-Required": "totp"})
        if not verify_totp(decrypt_text(user.totp_secret_encrypted), req.totp_code):
            audit(db, "CONDUCTOR_TOTP_FAILED", user, "conductor", c.employee_id, None, ip, result="FAILURE")
            db.commit()
            raise HTTPException(status_code=401, detail="Incorrect two-factor code.")
    user.failed_logins, user.locked_until = 0, None
    audit(db, "CONDUCTOR_LOGIN", user, "conductor", c.employee_id, None, ip, user_agent=request.headers.get("user-agent"))
    return {**issue_session(db, user, response, request), "user_id": user.id, "next_step": "CONDUCTOR_DASHBOARD"}


async def bus_realtime(bus: Optional[Bus]) -> dict:
    """Live position of this bus from the BMTC feed, matched by registration number. Never invented."""
    if not bus or not bus.registration_number:
        return {"available": False, "status": REALTIME_UNAVAILABLE, "reason": "No registration number assigned to this bus."}
    try:
        from ...api.network_routes import network_vehicles

        target = norm_reg(bus.registration_number)
        match = lambda data: next((v for v in data.vehicles if norm_reg(v.vehicle_number) == target), None)  # noqa: E731
        found = match(await network_vehicles(route=None))
        if not found and bus.route:
            found = match(await network_vehicles(route=bus.route))
        if not found:
            return {"available": False, "status": REALTIME_UNAVAILABLE, "reason": "This bus is not in the live BMTC feed right now."}
        return {
            "available": True,
            "status": found.freshness,
            "latitude": found.latitude,
            "longitude": found.longitude,
            "route": found.route_number,
            "direction": found.direction,
            "destination": found.destination,
            "current_stop": found.current_stop.stop_name if found.current_stop else None,
            "next_stop": found.next_stop.stop_name if found.next_stop else None,
            "last_update": found.timestamp,
            "age_seconds": found.freshness_seconds,
        }
    except Exception:
        return {"available": False, "status": REALTIME_UNAVAILABLE, "reason": "The BMTC network service is unavailable."}


def bus_view(bus: Optional[Bus]) -> Optional[dict]:
    if not bus:
        return None
    return {"id": bus.id, "fleet_label": bus.fleet_label, "registration_number": bus.registration_number, "route": bus.route,
            "operational_status": bus.operational_status.value, "max_capacity": bus.max_capacity}


def _active_trip(db: Session, conductor_user_id: str) -> Optional[Trip]:
    return db.scalars(select(Trip).where(Trip.conductor_id == conductor_user_id, Trip.status == "ACTIVE")
                      .order_by(Trip.started_at.desc())).first()


def _trip_view(db: Session, trip: Optional[Trip]) -> Optional[dict]:
    if not trip:
        return None
    scans = db.scalars(select(TicketVerification).where(TicketVerification.conductor_id == trip.conductor_id,
                                                        TicketVerification.created_at >= trip.started_at)).all()
    valid_ticket_ids = [s.ticket_id for s in scans if s.result == "VALID" and s.ticket_id]
    passengers = 0
    for tid in valid_ticket_ids:
        t = db.get(Ticket, tid)
        passengers += t.passenger_count if t else 0
    bus = db.get(Bus, trip.bus_id) if trip.bus_id else None
    return {**public_trip_view(trip, bus), "id": trip.id, "tickets_issued": trip.tickets_issued,
            "tickets_scanned": len(scans), "valid_tickets": len(valid_ticket_ids), "passengers_boarded": passengers,
            # kept for older app builds: the authoritative count, not the scan tally
            "passengers": trip.passenger_count}


@router.get("/conductor/me")
def conductor_me(user: User = Depends(require_roles(Role.CONDUCTOR)), db: Session = Depends(get_db, scope="function")):
    c = conductor_record(user, db)
    bus = db.get(Bus, c.bus_id) if c.bus_id else None
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    history = db.scalars(select(TicketVerification).where(TicketVerification.conductor_id == user.id, TicketVerification.created_at >= since)
                         .order_by(TicketVerification.created_at.desc()).limit(50)).all()
    passengers = 0
    for h in history:
        if h.result == "VALID" and h.ticket_id:
            t = db.get(Ticket, h.ticket_id)
            passengers += t.passenger_count if t else 0
    return {
        "name": user.name, "conductor_id": c.employee_id, "employee_id": c.employee_id,
        "assigned_bus": (bus.registration_number or bus.fleet_label) if bus else c.assigned_bus,
        "assigned_route": (bus.route if bus and bus.route else c.assigned_route),
        "bus": bus_view(bus), "current_trip": _trip_view(db, _active_trip(db, user.id)), "current_trip_id": c.current_trip_id,
        "passengers_admitted_24h": passengers,
        "history": [{"result": h.result, "detail": h.detail, "route": h.route, "at": h.created_at.isoformat()} for h in history],
    }


@router.get("/conductor/bus")
async def conductor_bus(user: User = Depends(require_roles(Role.CONDUCTOR)), db: Session = Depends(get_db, scope="function")):
    c = conductor_record(user, db)
    bus = db.get(Bus, c.bus_id) if c.bus_id else None
    return {"bus": bus_view(bus), "route": (bus.route if bus else c.assigned_route), "realtime": await bus_realtime(bus)}


@router.get("/conductor/trip")
def conductor_trip(user: User = Depends(require_roles(Role.CONDUCTOR)), db: Session = Depends(get_db, scope="function")):
    conductor_record(user, db)
    return {"trip": _trip_view(db, _active_trip(db, user.id))}


class TripStart(BaseModel):
    direction: Optional[int] = Field(default=None, ge=0, le=1)


@router.post("/conductor/trip/start")
def conductor_trip_start(req: TripStart, request: Request, user: User = Depends(require_roles(Role.CONDUCTOR)), db: Session = Depends(get_db, scope="function")):
    c = conductor_record(user, db)
    bus = db.get(Bus, c.bus_id) if c.bus_id else None
    if not bus:
        raise HTTPException(status_code=409, detail="No bus is assigned to you. Contact the Super Admin.")
    if bus.operational_status != BusStatus.IN_SERVICE:
        raise HTTPException(status_code=409, detail=f"Bus {bus.fleet_label} is {bus.operational_status.value.replace('_', ' ').lower()}.")
    other = db.scalars(select(Trip).where(Trip.bus_id == bus.id, Trip.status == "ACTIVE", Trip.conductor_id != user.id)).first()
    if other:
        raise HTTPException(status_code=409, detail=f"Bus {bus.fleet_label} already has an active trip ({other.trip_code or other.id}).")
    now = datetime.now(timezone.utc)
    for t in db.scalars(select(Trip).where(Trip.conductor_id == user.id, Trip.status == "ACTIVE")).all():
        t.status, t.ended_at, t.updated_at = "COMPLETED", now, now
        audit(db, "TRIP_ENDED", user, "trip", t.id, {"passenger_count": t.passenger_count, "reason": "NEW_TRIP_STARTED"}, client_ip(request))
        publish_trip(db, t, "TRIP_STATE")
    db.flush()  # the closed trips must be written before the one-active-trip-per-bus index sees the new one
    trip = Trip(bus_id=bus.id, conductor_id=user.id, route=bus.route, direction=req.direction, status="ACTIVE", started_at=now,
                updated_at=now, trip_code=new_trip_code(db, bus.route, now), max_capacity=bus.max_capacity or 50, passenger_count=0)
    try:
        with db.begin_nested():
            db.add(trip)
            db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"Bus {bus.fleet_label} already has an active trip.")
    c.current_trip_id = trip.id
    audit(db, "TRIP_STARTED", user, "trip", trip.id, {"bus": bus.fleet_label, "route": bus.route, "trip_code": trip.trip_code,
                                                      "max_capacity": trip.max_capacity}, client_ip(request))
    publish_trip(db, trip, "TRIP_STATE")
    return {"trip": _trip_view(db, trip)}


@router.post("/conductor/trip/end")
def conductor_trip_end(request: Request, user: User = Depends(require_roles(Role.CONDUCTOR)), db: Session = Depends(get_db, scope="function")):
    c = conductor_record(user, db)
    trip = _active_trip(db, user.id)
    if not trip:
        raise HTTPException(status_code=409, detail="No active trip.")
    from ..trips import lock_trip

    trip = lock_trip(db, trip.id)  # wait for any ticket being issued into it right now
    now = datetime.now(timezone.utc)
    trip.status, trip.ended_at, trip.updated_at = "COMPLETED", now, now
    c.current_trip_id = None
    audit(db, "TRIP_ENDED", user, "trip", trip.id, {"passenger_count": trip.passenger_count, "tickets": trip.tickets_issued},
          client_ip(request))
    publish_trip(db, trip, "TRIP_STATE")
    return {"trip": _trip_view(db, trip)}


@router.get("/conductor/trips")
def conductor_trip_history(limit: int = 20, user: User = Depends(require_roles(Role.CONDUCTOR)), db: Session = Depends(get_db, scope="function")):
    """This conductor's recent trips with their final counts (own trips only)."""
    conductor_record(user, db)
    rows = db.scalars(select(Trip).where(Trip.conductor_id == user.id).order_by(Trip.started_at.desc()).limit(max(1, min(limit, 50)))).all()
    out = []
    for t in rows:
        revenue = db.scalar(select(func.coalesce(func.sum(Ticket.fare), 0)).where(
            Ticket.trip_id == t.id, Ticket.status.in_((TicketStatus.ISSUED, TicketStatus.USED)))) or 0
        out.append({**public_trip_view(t, db.get(Bus, t.bus_id) if t.bus_id else None), "tickets_issued": t.tickets_issued,
                    "revenue": int(revenue)})
    return {"trips": out}


class CashTicket(BaseModel):
    from_stop_id: str = Field(min_length=1, max_length=40)
    to_stop_id: str = Field(min_length=1, max_length=40)
    passenger_count: int = Field(default=1, ge=1, le=6)
    fare_category: Literal["ADULT", "CHILD", "SENIOR"] = "ADULT"
    payment_mode: Literal["CASH"] = "CASH"
    # Optional: the trip the app believes it is issuing into. Must be this conductor's own running trip.
    trip_id: Optional[str] = Field(default=None, max_length=32)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_\-:.]{8,64}$")


@router.post("/conductor/tickets/issue", status_code=201)
async def conductor_issue_ticket(req: CashTicket, request: Request, response: Response,
                                 user: User = Depends(require_roles(Role.CONDUCTOR)), db: Session = Depends(get_db, scope="function")):
    """Cash ticket sold on board. Only for the conductor's own bus and running trip; the fare comes from the
    backend fare table, never from the device. Counted into the trip atomically."""
    from .tickets import FARE_CATEGORY_LABEL, insert_ticket_once, ticket_view, trip_public

    rate_limiter.check(f"conductor-issue:{user.id}", limit=60)
    c = conductor_record(user, db)
    existing = db.scalars(select(Ticket).where(Ticket.user_id == user.id, Ticket.idempotency_key == req.idempotency_key)).first()
    if existing:
        response.status_code = 200
        return {**ticket_view(existing, trip=trip_public(db, existing.trip_id)), "idempotent_replay": True}
    bus = db.get(Bus, c.bus_id) if c.bus_id else None
    if not bus:
        raise HTTPException(status_code=409, detail="No bus is assigned to you. Contact the Super Admin.")
    if bus.operational_status != BusStatus.IN_SERVICE:
        raise HTTPException(status_code=409, detail=f"Bus {bus.fleet_label} is not in service.")
    if req.trip_id:
        target = db.get(Trip, req.trip_id)
        if target and (target.conductor_id != user.id or target.bus_id != bus.id):
            audit(db, "TICKET_ISSUE_DENIED", user, "trip", target.id, {"reason": "NOT_ASSIGNED_TO_THIS_BUS"}, client_ip(request), result="DENIED")
            db.commit()
            raise HTTPException(status_code=403, detail={"code": "WRONG_CONDUCTOR", "message": "You can only issue tickets on your own bus and trip."})
    trip = _active_trip(db, user.id)
    if not trip or trip.bus_id != bus.id or (req.trip_id and trip.id != req.trip_id):
        raise HTTPException(status_code=409, detail={"code": "NO_ACTIVE_TRIP", "message": "Start a trip on your bus before issuing tickets."})
    fare = await get_fare_provider().quote(trip.route or "", trip.direction, req.from_stop_id, req.to_stop_id)
    unit = fare.fare_for(req.fare_category)
    now = datetime.now(timezone.utc)
    t = Ticket(
        reference=f"NB{secrets.token_hex(5).upper()}", user_id=user.id, issued_by=user.id,
        route=fare.route, direction=fare.direction, from_stop_id=fare.from_stop_id, from_stop=fare.from_stop,
        to_stop_id=fare.to_stop_id, to_stop=fare.to_stop, passenger_count=req.passenger_count,
        normal_fare=unit * req.passenger_count, fare=unit * req.passenger_count, fare_source=fare.source, ticket_type="PAID",
        payment_status="CASH_COLLECTED", payment_provider="CASH", status=TicketStatus.PENDING_PAYMENT,
        vehicle_number=bus.registration_number, fare_category=req.fare_category, distance_km=fare.distance_km, fare_stage=fare.stage,
        trip_id=trip.id, bus_id=bus.id, idempotency_key=req.idempotency_key,
        created_at=now, expires_at=now + timedelta(minutes=settings.ticket_validity_minutes),
    )
    winner = insert_ticket_once(db, t)
    if winner:
        response.status_code = 200
        return {**ticket_view(winner, trip=trip_public(db, winner.trip_id)), "idempotent_replay": True}
    counted = issue_into_trip(db, t, trip.id)  # 409 BUS_FULL / TRIP_ENDED → nothing saved, no cash should be taken
    audit(db, "TICKET_CREATED", user, "ticket", t.id, {"type": "PAID", "payment": "CASH", "fare": t.fare, "route": t.route,
                                                      "category": t.fare_category, "trip": trip.id, "passengers": t.passenger_count},
          client_ip(request))
    audit(db, "PASSENGER_COUNT_UPDATED", user, "trip", counted.id,
          {"delta": t.passenger_count, "passenger_count": counted.passenger_count, "ticket": t.id}, client_ip(request))
    return {**ticket_view(t, trip=trip_public(db, trip.id)), "fare_category_label": FARE_CATEGORY_LABEL[req.fare_category]}


class ConductorVerify(BaseModel):
    qr_payload: str = Field(min_length=10, max_length=2000)
    admit: bool = True  # mark as used when valid


def eligibility_still_valid(db: Session, t: Ticket) -> Optional[str]:
    """Re-check the eligibility a free ticket was issued under, at the moment of travel."""
    if t.ticket_type != "ELIGIBLE_FREE":
        return None
    profile = db.get(PassengerProfile, t.user_id)
    if profile and profile.eligibility_suspended:
        return "Free-ticket eligibility has been suspended."
    if t.eligibility_type == "STUDENT_FREE":
        status, ver, sp = effective_student_status(db, t.user_id)
        college = db.get(College, ver.college_id) if ver else None
        if status != "APPROVED" or not sp or not sp.expiry_date or sp.expiry_date < today_ist():
            return f"Student pass is no longer valid ({status})."
        if not college or college.status != CollegeStatus.APPROVED:
            return "The student's college is no longer approved."
        return None
    if t.eligibility_type == "FEMALE_IDENTITY_VERIFIED_FREE":
        iv = current_identity_verification(db, t.user_id)
        if not iv or (iv.attributes or {}).get("gender") != "F":
            return "Identity verification is no longer valid."
        return None
    return "Unknown eligibility type."


DISPLAY = {"VALID": "VALID TICKET ✓", "EXPIRED": "EXPIRED TICKET", "ALREADY_USED": "ALREADY USED", "REVOKED": "TICKET REVOKED",
           "WRONG_ROUTE": "WRONG ROUTE", "WRONG_BUS": "WRONG BUS", "WRONG_TRIP": "WRONG TRIP", "INVALID": "INVALID TICKET ✕"}


@router.post("/conductor/ticket/verify")
def conductor_verify(req: ConductorVerify, request: Request, user: User = Depends(require_roles(Role.CONDUCTOR)),
                     db: Session = Depends(get_db, scope="function")):
    """The QR is only a pointer: every field is re-checked against the server's ticket record."""
    rate_limiter.check(f"conductor-verify:{user.id}", limit=120)
    conductor: Conductor = conductor_record(user, db)
    bus = db.get(Bus, conductor.bus_id) if conductor.bus_id else None
    assigned_route = (bus.route if bus and bus.route else conductor.assigned_route)
    now = datetime.now(timezone.utc)

    def record(result: str, detail: str, ticket: Optional[Ticket] = None) -> dict:
        db.add(TicketVerification(ticket_id=ticket.id if ticket else None, conductor_id=user.id, result=result,
                                  detail=detail, route=assigned_route))
        audit(db, "QR_SCANNED", user, "ticket", ticket.id if ticket else None, {"result": result, "bus": bus.fleet_label if bus else None},
              client_ip(request), result="SUCCESS" if result == "VALID" else "DENIED")
        body = {"result": result, "display": DISPLAY.get(result, "INVALID TICKET ✕"), "detail": detail, "checked_at": now.isoformat()}
        if ticket is not None:
            passenger = db.get(User, ticket.user_id)
            body["ticket"] = {
                "reference": ticket.reference, "route": ticket.route, "from_stop": ticket.from_stop, "to_stop": ticket.to_stop,
                "passenger_count": ticket.passenger_count, "fare": ticket.fare, "ticket_type": ticket.ticket_type,
                "fare_category": ticket.fare_category or "ADULT", "fare_stage": ticket.fare_stage, "distance_km": ticket.distance_km,
                "eligibility": ticket.eligibility_type or "REGULAR_PAID", "eligibility_type": ticket.eligibility_type,
                "passenger_name": passenger.name if passenger and not ticket.issued_by else None, "vehicle_number": ticket.vehicle_number,
                "created_at": ticket.created_at.isoformat(), "expires_at": ticket.expires_at.isoformat(),
            }
        return body

    payload, error = parse_and_verify_qr(req.qr_payload)
    if error:
        return record("INVALID", "QR code is not a genuine Namma Bus ticket (signature check failed)." if error == "BAD_SIGNATURE"
                      else "QR code could not be read.")
    t = db.get(Ticket, payload["tid"])
    if not t or t.reference != payload["ref"] or t.route != payload["rid"] \
            or payload.get("trp", t.trip_id) != t.trip_id or payload.get("bus", t.bus_id) != t.bus_id:
        return record("INVALID", "Ticket not found.")
    if t.status == TicketStatus.REVOKED:
        return record("REVOKED", "This ticket has been revoked.", t)
    if t.status == TicketStatus.USED:
        return record("ALREADY_USED", f"Ticket was already used at {t.used_at.isoformat() if t.used_at else 'an earlier scan'}.", t)
    if t.status in (TicketStatus.CANCELLED, TicketStatus.PENDING_PAYMENT):
        return record("INVALID", "Ticket is not paid or was cancelled.", t)
    expires = t.expires_at if t.expires_at.tzinfo else t.expires_at.replace(tzinfo=timezone.utc)
    if expires < now:
        return record("EXPIRED", "Ticket validity period has ended.", t)
    if assigned_route and norm_route(assigned_route) != norm_route(t.route):
        return record("WRONG_ROUTE", f"Ticket is for route {t.route}; this bus is on route {assigned_route}.", t)
    if t.bus_id and bus and t.bus_id != bus.id:
        other = db.get(Bus, t.bus_id)
        return record("WRONG_BUS", f"Ticket was issued for bus {(other.registration_number or other.fleet_label) if other else 'another bus'}; "
                                   f"this is {bus.registration_number or bus.fleet_label}.", t)
    if t.vehicle_number and bus and bus.registration_number and norm_reg(t.vehicle_number) != norm_reg(bus.registration_number):
        return record("WRONG_BUS", f"Ticket was bought for bus {t.vehicle_number}; this is {bus.registration_number}.", t)
    current = _active_trip(db, user.id)
    if t.trip_id and current and t.trip_id != current.id:
        return record("WRONG_TRIP", f"Ticket belongs to trip {(db.get(Trip, t.trip_id).trip_code if db.get(Trip, t.trip_id) else t.trip_id)}, "
                                    f"not the current trip {current.trip_code or current.id}.", t)
    problem = eligibility_still_valid(db, t)
    if problem:
        return record("REVOKED", problem, t)
    if req.admit:
        t.status, t.used_at = TicketStatus.USED, now
    return record("VALID", "Ticket is valid.", t)
