"""
Backend-priced tickets (paid / eligible ₹0), payments verified on the server, signed QR.

Every ticket belongs to a running trip. A ticket is counted into the trip's passenger count exactly once, in the
same transaction that makes it ISSUED (see access/trips.py): free tickets at creation, paid tickets only after the
backend has verified the payment. Repeating a request with the same idempotency key never creates a second ticket.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..eligibility import (
    current_identity_verification,
    effective_student_status,
    evaluate,
    load_policy,
    today_ist,
)
from ..fares import get_fare_provider
from ..models import (
    Bus,
    Conductor,
    Role,
    Ticket,
    TicketStatus,
    TicketVerification,
    Trip,
    User,
)
from ..payments import TEST_PAYMENT_LABEL, TestPaymentProvider, get_payment_provider
from ..notifications import notify
from ..trips import TripError, active_trips, issue_into_trip, public_trip_view, release_from_trip, resolve_trip_for_ticket
from ..providers.identity import DEV_LABEL
from ..rbac import TRAVELLER_ROLES, conductor_record, get_current_user, require_roles
from ..security import build_qr_payload, client_ip, parse_and_verify_qr, rate_limiter

router = APIRouter(tags=["Access: Tickets & Conductor"])

DEMO_PAYMENT_LABEL = TEST_PAYMENT_LABEL
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9_\-:.]{8,64}$"


class JourneyRequest(BaseModel):
    route: str = Field(min_length=1, max_length=40)
    direction: Optional[int] = Field(default=None, ge=0, le=1)
    from_stop_id: str = Field(min_length=1, max_length=40)
    to_stop_id: str = Field(min_length=1, max_length=40)
    passenger_count: int = Field(default=1, ge=1, le=6)
    use_eligibility: bool = False
    face_verification_id: Optional[str] = Field(default=None, max_length=32)
    vehicle_number: Optional[str] = Field(default=None, max_length=20)
    # BMTC fare column. CHILD is for a child travelling on this ticket (the conductor sees the category on scan);
    # SENIOR needs the account's date of birth to show age 60 or above.
    fare_category: Literal["ADULT", "CHILD", "SENIOR"] = "ADULT"
    # The running trip (bus) to travel on. Optional when the route has exactly one running trip.
    trip_id: Optional[str] = Field(default=None, max_length=32)
    # Generated once per purchase attempt by the app; retries with the same key return the same ticket
    idempotency_key: Optional[str] = Field(default=None, pattern=IDEMPOTENCY_PATTERN)


SENIOR_MIN_AGE = 60
FARE_CATEGORY_LABEL = {"ADULT": "Adult", "CHILD": "Child", "SENIOR": "Senior Citizen"}


def _age(dob, today) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _check_category(user: User, category: str) -> None:
    if category == "SENIOR":
        if not user.date_of_birth:
            raise HTTPException(status_code=409, detail="Add your date of birth in your profile to buy a Senior Citizen ticket.")
        if _age(user.date_of_birth, today_ist()) < SENIOR_MIN_AGE:
            raise HTTPException(status_code=409, detail=f"Senior Citizen fares are for passengers aged {SENIOR_MIN_AGE} or above.")


async def _price(db: Session, user: User, req: JourneyRequest):
    _check_category(user, req.fare_category)
    fare = await get_fare_provider().quote(req.route.strip(), req.direction, req.from_stop_id, req.to_stop_id)
    decision = evaluate(db, user, passenger_count=req.passenger_count, face_verification_id=req.face_verification_id,
                        use_eligibility=req.use_eligibility)
    normal_total = fare.fare_for(req.fare_category) * req.passenger_count
    total = normal_total * decision.fare_percent // 100 if decision.eligible else normal_total
    return fare, decision, normal_total, total


def _quote_body(fare, decision, normal_total, total, req: JourneyRequest) -> dict:
    policy = load_policy()
    return {
        "route": fare.route,
        "direction": fare.direction,
        "from_stop": {"id": fare.from_stop_id, "name": fare.from_stop},
        "to_stop": {"id": fare.to_stop_id, "name": fare.to_stop},
        "passenger_count": req.passenger_count,
        "fare_category": req.fare_category,
        "fare_category_label": FARE_CATEGORY_LABEL[req.fare_category],
        "unit_fare": fare.fare_for(req.fare_category),
        "fares_by_category": fare.fares or None,
        "distance_km": fare.distance_km,
        "fare_stage": fare.stage,
        "normal_fare": normal_total,
        "fare": total,
        "currency": "INR",
        "fare_source": fare.source,
        "fare_source_note": _source_note(fare),
        "ticket_type": "ELIGIBLE_FREE" if decision.eligible and total == 0 else "PAID",
        "eligible": decision.eligible,
        "eligibility": decision.eligibility,
        "reason_code": decision.reason_code,
        "eligibility_type": decision.eligibility_type,
        "eligibility_reasons": decision.reasons,
        "needs_face_verification": decision.needs_face_verification,
        "eligibility_is_development": decision.is_development,
        "eligibility_label": DEV_LABEL if decision.is_development else None,
        "policy_disclaimer": policy.get("disclaimer"),
        "payment_label": DEMO_PAYMENT_LABEL,
    }


def trip_public(db: Session, trip_id: Optional[str]) -> Optional[dict]:
    trip = db.get(Trip, trip_id) if trip_id else None
    return public_trip_view(trip, db.get(Bus, trip.bus_id) if trip.bus_id else None) if trip else None


def _existing_by_key(db: Session, user_id: str, key: Optional[str]) -> Optional[Ticket]:
    if not key:
        return None
    return db.scalars(select(Ticket).where(Ticket.user_id == user_id, Ticket.idempotency_key == key)).first()


def insert_ticket_once(db: Session, t: Ticket) -> Optional[Ticket]:
    """Insert the ticket; when a concurrent request with the same idempotency key won the race, return that one."""
    try:
        with db.begin_nested():
            db.add(t)
            db.flush()
        return None
    except IntegrityError:
        existing = _existing_by_key(db, t.user_id, t.idempotency_key)
        if not existing:
            raise
        return existing


def notify_ticket_issued(db: Session, t: Ticket) -> None:
    notify(db, t.user_id, "TICKET_ISSUED", "Ticket issued",
           f"Your {t.route} ticket {t.reference} ({t.from_stop} → {t.to_stop}) is ready.",
           {"ticket_id": t.id, "route": t.route, "reference": t.reference, "fare": t.fare}, f"ticket-issued-{t.id}")


def _source_note(fare) -> str:
    if fare.source == "BMTC_STAGE_FARE_TABLE":
        return (f"BMTC revised stage fare · stage {fare.stage} ({fare.distance_km} km along the route, measured stop to stop)")
    if fare.source == "GTFS_FARE_RULES":
        return "BMTC GTFS fare rules"
    return "DEMO FARE ESTIMATE — not an official BMTC fare (AC services are not covered by the stage-fare table)"


def ticket_view(t: Ticket, include_qr: bool = True, trip: Optional[dict] = None) -> dict:
    issued = t.status in (TicketStatus.ISSUED, TicketStatus.USED)
    return {
        "trip_id": t.trip_id,
        "bus_id": t.bus_id,
        "trip": trip,
        "issued_at": t.issued_at.isoformat() if t.issued_at else None,
        "issued_by": "CONDUCTOR" if t.issued_by else "APP",
        "payment_provider": t.payment_provider,
        "ticket_id": t.id,
        "reference": t.reference,
        "passenger_id": t.user_id,
        "route": t.route,
        "direction": t.direction,
        "from_stop": t.from_stop,
        "to_stop": t.to_stop,
        "passenger_count": t.passenger_count,
        "fare_category": t.fare_category or "ADULT",
        "fare_category_label": FARE_CATEGORY_LABEL.get(t.fare_category or "ADULT"),
        "distance_km": t.distance_km,
        "fare_stage": t.fare_stage,
        "normal_fare": t.normal_fare,
        "fare": t.fare,
        "fare_source": t.fare_source,
        "ticket_type": t.ticket_type,
        "eligibility": t.eligibility_type or "REGULAR_PAID",
        "eligibility_type": t.eligibility_type,
        "verification_reference": t.verification_reference,
        "payment_status": t.payment_status,
        "status": t.status.value,
        "vehicle_number": t.vehicle_number,
        "created_at": t.created_at.isoformat(),
        "expires_at": t.expires_at.isoformat(),
        "used_at": t.used_at.isoformat() if t.used_at else None,
        "qr_payload": build_qr_payload(t.id, t.reference, t.route, t.created_at, t.expires_at, t.trip_id, t.bus_id)
        if include_qr and issued else None,
        "payment_label": DEMO_PAYMENT_LABEL if t.payment_status == "PAID_DEMO" else None,
    }


@router.post("/tickets/quote")
async def ticket_quote(req: JourneyRequest, user: User = Depends(require_roles(*TRAVELLER_ROLES)), db: Session = Depends(get_db, scope="function")):
    fare, decision, normal_total, total = await _price(db, user, req)
    return _quote_body(fare, decision, normal_total, total, req)


@router.post("/tickets/create", status_code=201)
async def ticket_create(req: JourneyRequest, request: Request, response: Response,
                        user: User = Depends(require_roles(*TRAVELLER_ROLES)), db: Session = Depends(get_db, scope="function")):
    rate_limiter.check(f"ticket-create:{user.id}", limit=20)
    replay = _existing_by_key(db, user.id, req.idempotency_key)
    if replay:
        response.status_code = 200
        return {**ticket_view(replay, trip=trip_public(db, replay.trip_id)), "idempotent_replay": True}
    # Recomputed from scratch; nothing from a previous quote or the client is trusted
    fare, decision, normal_total, total = await _price(db, user, req)
    if req.use_eligibility and not decision.eligible:
        audit(db, "FREE_TICKET_DENIED", user, "ticket", None, {"reason_code": decision.reason_code}, client_ip(request), result="DENIED")
        db.commit()
        raise HTTPException(status_code=409, detail={"message": "Eligibility could not be confirmed. You can buy a regular ticket instead.",
                                                     "reason_code": decision.reason_code, "reasons": decision.reasons,
                                                     "needs_face_verification": decision.needs_face_verification})
    trip = resolve_trip_for_ticket(db, fare.route, req.trip_id, req.vehicle_number)
    if trip.passenger_count + req.passenger_count > trip.max_capacity:
        # Early answer only; the authoritative check happens under the row lock when the ticket is issued
        raise TripError("BUS_FULL", "This bus is currently full.", trip_public(db, trip.id))
    now = datetime.now(timezone.utc)
    free = decision.eligible and total == 0
    bus = db.get(Bus, trip.bus_id) if trip.bus_id else None
    t = Ticket(
        reference=f"NB{secrets.token_hex(5).upper()}",
        user_id=user.id, route=fare.route, direction=fare.direction,
        from_stop_id=fare.from_stop_id, from_stop=fare.from_stop, to_stop_id=fare.to_stop_id, to_stop=fare.to_stop,
        passenger_count=req.passenger_count, normal_fare=normal_total, fare=total, fare_source=fare.source,
        ticket_type="ELIGIBLE_FREE" if free else "PAID",
        eligibility_type=decision.eligibility_type if decision.eligible else None,
        eligibility_rule_id=decision.rule_id if decision.eligible else None,
        verification_reference=decision.verification_reference if decision.eligible else None,
        payment_status="NOT_REQUIRED" if free else "PENDING",
        status=TicketStatus.PENDING_PAYMENT,  # becomes ISSUED only inside issue_into_trip
        vehicle_number=(req.vehicle_number or "").strip().upper() or (bus.registration_number if bus else None),
        fare_category=req.fare_category, distance_km=fare.distance_km, fare_stage=fare.stage,
        trip_id=trip.id, bus_id=trip.bus_id, idempotency_key=req.idempotency_key,
        created_at=now, expires_at=now + timedelta(minutes=settings.ticket_validity_minutes),
    )
    winner = insert_ticket_once(db, t)
    if winner:
        response.status_code = 200
        return {**ticket_view(winner, trip=trip_public(db, winner.trip_id)), "idempotent_replay": True}
    if decision.face_attempt is not None:
        decision.face_attempt.consumed_by_ticket_id = t.id  # single use
    audit(db, "TICKET_CREATED", user, "ticket", t.id,
          {"type": t.ticket_type, "eligibility": t.eligibility_type, "fare": t.fare, "route": t.route, "category": t.fare_category,
           "stage": t.fare_stage, "trip": trip.id, "passengers": t.passenger_count}, client_ip(request))
    if free:
        # ₹0 ticket: counted now, atomically (raises 409 BUS_FULL / TRIP_ENDED and nothing is saved)
        counted = issue_into_trip(db, t, trip.id)
        audit(db, "PASSENGER_COUNT_UPDATED", user, "trip", counted.id,
              {"delta": t.passenger_count, "passenger_count": counted.passenger_count, "ticket": t.id}, client_ip(request))
        notify_ticket_issued(db, t)
    return {**ticket_view(t, trip=trip_public(db, trip.id)), "eligibility_label": DEV_LABEL if decision.is_development else None}


# ---------------------------------------------------------------------------------------------- payments
def _own_ticket(db: Session, ticket_id: str, user: User, lock: bool = False) -> Ticket:
    q = select(Ticket).where(Ticket.id == ticket_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    t = db.scalars(q).first()
    if not t or t.user_id != user.id:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return t


@router.post("/tickets/{ticket_id}/payment/order")
def ticket_payment_order(ticket_id: str, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)),
                         db: Session = Depends(get_db, scope="function")):
    """Create (or return the existing) payment order for a pending ticket. The amount comes from the ticket."""
    t = _own_ticket(db, ticket_id, user, lock=True)
    if expire_if_stale(db, t, user, client_ip(request)):
        db.commit()
        raise HTTPException(status_code=409, detail={"code": "PAYMENT_TIMEOUT", "message": "This payment window has expired. Please book again."})
    if t.status != TicketStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=409, detail=f"Ticket is {t.status.value}.")
    trip = db.get(Trip, t.trip_id) if t.trip_id else None
    if not trip or trip.status != "ACTIVE":
        raise TripError("TRIP_ENDED", "This trip has ended. Choose another bus.")
    if trip.passenger_count + t.passenger_count > trip.max_capacity:
        raise TripError("BUS_FULL", "This bus is currently full.", trip_public(db, trip.id))
    provider = get_payment_provider()
    if not (t.payment_order_id and t.payment_provider == provider.name):
        order = provider.create_order(t.fare * 100, t.reference)
        t.payment_provider, t.payment_order_id = provider.name, order.order_id
    audit(db, "PAYMENT_ORDER_CREATED", user, "ticket", t.id, {"provider": provider.name, "amount": t.fare}, client_ip(request))
    return {"ticket_id": t.id, "order_id": t.payment_order_id, "amount_paise": t.fare * 100, "currency": "INR",
            "provider": provider.name, "key_id": settings.razorpay_key_id if provider.name == "razorpay" else None,  # public id only
            "is_test": provider.is_test, "label": TEST_PAYMENT_LABEL if provider.is_test else None}


class PaymentVerify(BaseModel):
    order_id: str = Field(min_length=6, max_length=64)
    payment_id: str = Field(min_length=6, max_length=64)
    signature: str = Field(min_length=16, max_length=128)


PAYMENT_WINDOW_MINUTES = 15


def payment_window_closed(t: Ticket) -> bool:
    created = t.created_at if t.created_at.tzinfo else t.created_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created > timedelta(minutes=PAYMENT_WINDOW_MINUTES)


def expire_if_stale(db: Session, t: Ticket, actor: Optional[User], ip: Optional[str]) -> bool:
    """A pending payment older than the payment window is closed as TIMEOUT (it was never counted)."""
    if t.status == TicketStatus.PENDING_PAYMENT and payment_window_closed(t):
        t.status, t.cancelled_at, t.payment_status = TicketStatus.CANCELLED, datetime.now(timezone.utc), "TIMEOUT"
        audit(db, "PAYMENT_FAILED", actor, "ticket", t.id, {"reason": "TIMEOUT"}, ip, result="FAILURE")
        return True
    return False


def issue_paid_ticket(db: Session, t: Ticket, actor: Optional[User], payment_id: str, ip: Optional[str]) -> dict:
    """The payment is already verified (gateway signature or signed webhook). Count it into the trip atomically,
    or refund it when the bus filled up / the trip ended / the payment window had closed."""
    provider = get_payment_provider()
    t.payment_reference = payment_id
    audit(db, "PAYMENT_VERIFIED", actor, "ticket", t.id, {"provider": provider.name, "amount": t.fare}, ip)

    def refund(reason: str) -> None:
        refund_id = provider.refund(payment_id, t.fare * 100)
        t.status, t.cancelled_at, t.payment_status = TicketStatus.CANCELLED, datetime.now(timezone.utc), "REFUNDED"
        audit(db, "PAYMENT_REFUNDED", actor, "ticket", t.id, {"reason": reason, "refund": refund_id[:40]}, ip)
        notify(db, t.user_id, "PAYMENT_REFUNDED", "Payment refunded",
               f"Your payment of ₹{t.fare} for {t.route} was refunded. No ticket was created.", {"ticket_id": t.id, "fare": t.fare},
               f"refunded-{t.id}")
        db.commit()

    if payment_window_closed(t):
        refund("TIMEOUT")
        raise HTTPException(status_code=409, detail={"code": "PAYMENT_TIMEOUT",
                                                     "message": "The payment window had closed. Your payment was refunded and no ticket was created."})
    try:
        trip = issue_into_trip(db, t, t.trip_id)
    except TripError as e:
        refund(e.code)  # paid, but the bus filled up or the trip ended meanwhile: refund, never over-fill
        raise
    t.payment_status = "PAID_DEMO" if provider.is_test else "PAID"
    t.expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.ticket_validity_minutes)
    audit(db, "PASSENGER_COUNT_UPDATED", actor, "trip", trip.id,
          {"delta": t.passenger_count, "passenger_count": trip.passenger_count, "ticket": t.id}, ip)
    notify_ticket_issued(db, t)
    return ticket_view(t, trip=public_trip_view(trip, db.get(Bus, trip.bus_id) if trip.bus_id else None))


def complete_payment(db: Session, t: Ticket, user: User, order_id: str, payment_id: str, signature: str, ip: str) -> dict:
    """Server-side payment verification (checkout signature), then the atomic issue into the trip. Safe to call twice."""
    provider = get_payment_provider()
    if t.status in (TicketStatus.ISSUED, TicketStatus.USED) and t.payment_reference == payment_id:
        return {**ticket_view(t, trip=trip_public(db, t.trip_id)), "idempotent_replay": True}
    if t.status != TicketStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=409, detail={"code": f"TICKET_{t.status.value}", "message": f"Ticket is {t.status.value.lower().replace('_', ' ')}."})
    if not t.payment_order_id or order_id != t.payment_order_id or t.payment_provider != provider.name \
            or not provider.verify(order_id, payment_id, signature):
        t.status, t.cancelled_at = TicketStatus.CANCELLED, datetime.now(timezone.utc)
        t.payment_status = "FAILED_DEMO" if provider.is_test else "FAILED"
        audit(db, "PAYMENT_FAILED", user, "ticket", t.id, {"provider": provider.name, "reason": "SIGNATURE_MISMATCH"}, ip, result="FAILURE")
        db.commit()
        raise HTTPException(status_code=402, detail={"code": "PAYMENT_NOT_VERIFIED", "message": "Payment could not be verified. No ticket was created."})
    return issue_paid_ticket(db, t, user, payment_id, ip)


@router.get("/payments/config")
def payments_config(user: User = Depends(get_current_user)):
    """What the app may show about payments. Only the public key id is ever returned, never a secret."""
    name = settings.payment_provider
    if name == "razorpay":
        configured = bool(settings.razorpay_key_id and settings.razorpay_key_secret)
        return {"provider": "razorpay", "configured": configured, "is_test": False,
                "key_id": settings.razorpay_key_id if configured else None,
                "message": None if configured else "Online payments need configuration (Razorpay merchant keys)."}
    if name == "test" and not settings.is_production:
        return {"provider": "test", "configured": True, "is_test": True, "key_id": None, "label": TEST_PAYMENT_LABEL}
    return {"provider": name, "configured": False, "is_test": False, "key_id": None, "message": "Online payments are not configured."}


@router.post("/tickets/{ticket_id}/payment/cancel")
def ticket_payment_cancel(ticket_id: str, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)),
                          db: Session = Depends(get_db, scope="function")):
    """The passenger closed the checkout. Nothing was counted; the ticket is cancelled."""
    t = _own_ticket(db, ticket_id, user, lock=True)
    if t.status != TicketStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=409, detail=f"Ticket is {t.status.value}.")
    t.status, t.cancelled_at, t.payment_status = TicketStatus.CANCELLED, datetime.now(timezone.utc), "CANCELLED"
    audit(db, "PAYMENT_FAILED", user, "ticket", t.id, {"reason": "CANCELLED_BY_PASSENGER"}, client_ip(request), result="FAILURE")
    return ticket_view(t, trip=trip_public(db, t.trip_id))


@router.post("/payments/razorpay/webhook", include_in_schema=False)
async def razorpay_webhook(request: Request, db: Session = Depends(get_db, scope="function")):
    """Razorpay → server. Authenticated by X-Razorpay-Signature = HMAC_SHA256(raw body, webhook secret).
    Handles payment.captured / order.paid (issue), payment.failed (fail) and refund.processed (revoke + release seat).
    Idempotent: Razorpay may deliver an event more than once."""
    import hashlib
    import hmac
    import json as _json

    secret = settings.razorpay_webhook_secret
    if settings.payment_provider != "razorpay" or not secret:
        raise HTTPException(status_code=404, detail="Not found.")
    raw = await request.body()
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("x-razorpay-signature", "")):
        raise HTTPException(status_code=400, detail="Invalid signature.")
    event = _json.loads(raw or b"{}")
    kind = event.get("event", "")
    payment = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
    order_id, payment_id = payment.get("order_id"), payment.get("id")
    if not order_id:
        return {"ok": True, "ignored": kind}
    t = db.scalars(select(Ticket).where(Ticket.payment_order_id == order_id).with_for_update()
                   .execution_options(populate_existing=True)).first()
    if not t:
        return {"ok": True, "ignored": "unknown order"}
    ip = client_ip(request)
    if kind in ("payment.captured", "order.paid") and payment_id:
        if t.status == TicketStatus.PENDING_PAYMENT:
            try:
                issue_paid_ticket(db, t, None, payment_id, ip)
            except HTTPException:
                pass  # refunded and recorded
    elif kind == "payment.failed" and t.status == TicketStatus.PENDING_PAYMENT:
        t.status, t.cancelled_at, t.payment_status = TicketStatus.CANCELLED, datetime.now(timezone.utc), "FAILED"
        audit(db, "PAYMENT_FAILED", None, "ticket", t.id, {"provider": "razorpay", "reason": "GATEWAY_FAILED"}, ip, result="FAILURE")
    elif kind == "refund.processed" and t.payment_status != "REFUNDED":
        if t.status in (TicketStatus.ISSUED, TicketStatus.USED):
            if t.status == TicketStatus.ISSUED:
                release_from_trip(db, t)
            t.status = TicketStatus.REVOKED
            audit(db, "TICKET_REVOKED", None, "ticket", t.id, {"reason": "REFUNDED_BY_GATEWAY"}, ip)
        t.payment_status = "REFUNDED"
    return {"ok": True}


@router.post("/tickets/{ticket_id}/payment/verify")
def ticket_payment_verify(ticket_id: str, req: PaymentVerify, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)),
                          db: Session = Depends(get_db, scope="function")):
    t = _own_ticket(db, ticket_id, user, lock=True)
    return complete_payment(db, t, user, req.order_id, req.payment_id, req.signature, client_ip(request))


class DemoPayment(BaseModel):
    outcome: Literal["SUCCESS", "FAILURE"] = "SUCCESS"


def _test_checkout(db: Session, ticket_id: str, outcome: str, user: User, ip: str) -> dict:
    provider = get_payment_provider()
    if not isinstance(provider, TestPaymentProvider) or settings.is_production:
        raise HTTPException(status_code=404, detail="Test payments are not available.")
    t = _own_ticket(db, ticket_id, user, lock=True)
    if t.status != TicketStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=409, detail=f"Ticket is {t.status.value}.")
    if not (t.payment_order_id and t.payment_provider == provider.name):
        t.payment_provider, t.payment_order_id = provider.name, provider.create_order(t.fare * 100, t.reference).order_id
    if outcome == "FAILURE":
        t.status, t.payment_status, t.cancelled_at = TicketStatus.CANCELLED, "FAILED_DEMO", datetime.now(timezone.utc)
        audit(db, "PAYMENT_FAILED", user, "ticket", t.id, {"provider": provider.name, "reason": "DECLINED_IN_TEST_CHECKOUT"}, ip, result="FAILURE")
        return ticket_view(t, trip=trip_public(db, t.trip_id))
    payment_id, signature = provider.simulate_gateway(t.payment_order_id)
    return complete_payment(db, t, user, t.payment_order_id, payment_id, signature, ip)


@router.post("/payments/test/complete")
def payments_test_complete(req: DemoPayment, ticket_id: str, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)),
                           db: Session = Depends(get_db, scope="function")):
    """DEVELOPMENT ONLY — plays the payment gateway (no money moves), then verifies like a real payment."""
    return _test_checkout(db, ticket_id, req.outcome, user, client_ip(request))


@router.post("/tickets/{ticket_id}/pay-demo")
def ticket_pay_demo(ticket_id: str, req: DemoPayment, request: Request, user: User = Depends(require_roles(*TRAVELLER_ROLES)),
                    db: Session = Depends(get_db, scope="function")):
    """Development checkout (test payment provider). Same server-side verification as a real payment."""
    return _test_checkout(db, ticket_id, req.outcome, user, client_ip(request))


# ---------------------------------------------------------------------------------------------- trips (public)
@router.get("/trips/active")
def trips_active(route: Optional[str] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    """Running trips with their live passenger counts. Counts only — no passenger details."""
    return {"trips": [public_trip_view(t, db.get(Bus, t.bus_id) if t.bus_id else None) for t in active_trips(db, route=route)]}


@router.get("/trips/{trip_id}")
def trip_detail(trip_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    view = trip_public(db, trip_id)
    if not view:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return {"trip": view}


@router.get("/tickets")
def my_tickets(user: User = Depends(require_roles(*TRAVELLER_ROLES)), db: Session = Depends(get_db, scope="function")):
    rows = db.scalars(select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.created_at.desc()).limit(100)).all()
    return {"tickets": [ticket_view(t, trip=trip_public(db, t.trip_id) if t.status in (TicketStatus.ISSUED, TicketStatus.USED) else None)
                        for t in rows]}


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db, scope="function")):
    t = db.get(Ticket, ticket_id)
    if not t or (t.user_id != user.id and user.role != Role.SUPER_ADMIN):
        raise HTTPException(status_code=404, detail="Ticket not found.")
    passenger = db.get(User, t.user_id)
    return {**ticket_view(t, trip=trip_public(db, t.trip_id)), "passenger_name": passenger.name if passenger else None}
