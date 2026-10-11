"""
Phase 43 (master spec): Digital ticket payment, integrated with the EXISTING TicketService.

Ported from the standalone "NammaBlr Digital Ticket Payment" module (MockPaymentProvider,
PaymentStatus lifecycle, "ticket only after verified payment", amount matching) and adapted:

- The fare is computed on the server from the demo fare table; the client never sets the amount.
- The payment session binds route / origin / destination / ticket type / quantity at creation,
  so the purchase cannot be changed after payment.
- A payment can be consumed by exactly one ticket (replay protection).
- Status always comes from the provider record on the server, never from the client.
- Only a sandbox provider exists. It never touches real money or payment credentials, and every
  response carries "DEMO PAYMENT — NO REAL MONEY CHARGED". A real gateway must be added as another
  PaymentProvider and enabled explicitly via configuration.

Never stored: card numbers, CVV, UPI PIN, banking passwords or any payment credential.
"""

import logging
import os
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("nammablr.payments")

DEMO_PAYMENT_DISCLOSURE = "DEMO PAYMENT — NO REAL MONEY CHARGED"

# Demo fare table (₹) for the simulated corridors. Source: DEMO_FARE_TABLE — not official BMTC fares.
DEMO_ROUTE_FARES: Dict[str, int] = {"500D": 25, "356": 20, "KIA-8": 240, "201R": 15, "G-2": 30}
TICKET_TYPE_MULTIPLIER: Dict[str, float] = {"ADULT": 1.0, "STUDENT": 0.6}
MAX_QUANTITY = 6


class PaymentStatus(str, Enum):
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_PROCESSING = "PAYMENT_PROCESSING"
    PAYMENT_SUCCESS = "PAYMENT_SUCCESS"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_CANCELLED = "PAYMENT_CANCELLED"


FINAL_STATUSES = {PaymentStatus.PAYMENT_SUCCESS, PaymentStatus.PAYMENT_FAILED, PaymentStatus.PAYMENT_CANCELLED}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaymentRecord(BaseModel):
    payment_id: str
    amount: int
    currency: str = "INR"
    provider: str
    status: PaymentStatus
    created_at: str
    completed_at: Optional[str] = None
    transaction_reference: Optional[str] = None
    # Purchase bound at creation
    route_number: str
    bus_id: Optional[str] = None
    bus_type: Optional[str] = None
    source: str
    destination: str
    ticket_type: str
    quantity: int
    unit_fare: int
    fare_source: str = "DEMO_FARE_TABLE"  # DEMO_FARE_TABLE | GTFS_FARE_RULES | DEMO_FARE_ESTIMATE (network, no feed fare)
    from_stop_id: Optional[str] = None
    to_stop_id: Optional[str] = None
    vehicle_number: Optional[str] = None
    user_id: Optional[str] = None
    ticket_id: Optional[str] = None
    is_sandbox: bool = True
    disclosure: str = DEMO_PAYMENT_DISCLOSURE


class PaymentReceipt(BaseModel):
    """Customer receipt. Contains no card, UPI or credential data."""
    receipt_number: str
    payment_id: str
    transaction_reference: Optional[str]
    status: PaymentStatus
    amount: int
    currency: str
    provider: str
    route_number: str
    source: str
    destination: str
    ticket_type: str
    quantity: int
    unit_fare: int
    ticket_id: Optional[str]
    paid_at: Optional[str]
    disclosure: str = DEMO_PAYMENT_DISCLOSURE


class PaymentCreateRequest(BaseModel):
    route_number: str = Field(..., min_length=1, max_length=16)
    source: str = Field(..., min_length=1, max_length=120)
    destination: str = Field(..., min_length=1, max_length=120)
    ticket_type: str = "ADULT"
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)
    bus_id: Optional[str] = None
    bus_type: Optional[str] = None
    # Network (NammaRoute) routes: stop ids select the GTFS zone fare; vehicle_number is the bus boarded
    from_stop_id: Optional[str] = Field(default=None, max_length=40)
    to_stop_id: Optional[str] = Field(default=None, max_length=40)
    vehicle_number: Optional[str] = Field(default=None, max_length=40)


class PaymentVerifyRequest(BaseModel):
    payment_id: str
    # Sandbox only: simulates the outcome the sandbox provider reports. Ignored/refused for real providers.
    sandbox_outcome: Optional[PaymentStatus] = None


class TicketPurchaseRequest(BaseModel):
    payment_id: str


class PaymentError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class PaymentProvider(ABC):
    name: str = "UNAVAILABLE"
    is_sandbox: bool = True

    @abstractmethod
    def create_order(self, payment_id: str, amount: int, currency: str) -> None: ...

    @abstractmethod
    def fetch_status(self, payment_id: str) -> PaymentStatus:
        """Authoritative status as reported by the provider."""


class SandboxPaymentProvider(PaymentProvider):
    """Development-only provider (from the payment module's MockPaymentProvider). No real money."""

    name = "MOCK_SANDBOX"
    is_sandbox = True

    def __init__(self):
        self._orders: Dict[str, PaymentStatus] = {}

    def create_order(self, payment_id: str, amount: int, currency: str) -> None:
        self._orders[payment_id] = PaymentStatus.PAYMENT_PENDING

    def simulate(self, payment_id: str, outcome: PaymentStatus) -> None:
        if payment_id not in self._orders:
            raise KeyError(payment_id)
        self._orders[payment_id] = outcome

    def fetch_status(self, payment_id: str) -> PaymentStatus:
        return self._orders.get(payment_id, PaymentStatus.PAYMENT_FAILED)


def build_payment_provider() -> PaymentProvider:
    mode = os.getenv("PAYMENT_PROVIDER", "sandbox").strip().lower()
    if mode != "sandbox":
        logger.warning("[PAYMENTS] PAYMENT_PROVIDER=%s is not implemented; using sandbox (no real money).", mode)
    return SandboxPaymentProvider()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def quote_fare(route_number: str, ticket_type: str, quantity: int) -> tuple[int, int]:
    route = route_number.strip().upper()
    if route not in DEMO_ROUTE_FARES:
        raise PaymentError(400, f"No demo fare is defined for route '{route_number}'.")
    ttype = ticket_type.strip().upper()
    if ttype not in TICKET_TYPE_MULTIPLIER:
        raise PaymentError(400, f"Unsupported ticket type '{ticket_type}'. Use ADULT or STUDENT.")
    unit = max(1, round(DEMO_ROUTE_FARES[route] * TICKET_TYPE_MULTIPLIER[ttype]))
    return unit, unit * quantity


class PaymentService:
    def __init__(self):
        self._lock = threading.RLock()
        self.reset()

    def reset(self):
        with self._lock:
            self.provider = build_payment_provider()
            self._records: Dict[str, PaymentRecord] = {}

    def create(self, req: PaymentCreateRequest, user_id: Optional[str] = None, network_unit_fare: Optional[int] = None,
               network_fare_source: Optional[str] = None) -> PaymentRecord:
        """network_unit_fare: fare for a network route (GTFS_FARE_RULES or a labelled DEMO_FARE_ESTIMATE; adult only)."""
        if network_unit_fare is not None:
            if req.ticket_type.strip().upper() != "ADULT":
                raise PaymentError(400, "Only adult fares are available for network routes.")
            unit, total, fare_source = network_unit_fare, network_unit_fare * req.quantity, network_fare_source or "GTFS_FARE_RULES"
        else:
            unit, total = quote_fare(req.route_number, req.ticket_type, req.quantity)
            fare_source = "DEMO_FARE_TABLE"
        payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
        record = PaymentRecord(
            payment_id=payment_id,
            amount=total,
            provider=self.provider.name,
            status=PaymentStatus.PAYMENT_PENDING,
            created_at=_now(),
            route_number=req.route_number.strip().upper(),
            bus_id=req.bus_id,
            bus_type=req.bus_type,
            source=req.source.strip(),
            destination=req.destination.strip(),
            ticket_type=req.ticket_type.strip().upper(),
            quantity=req.quantity,
            unit_fare=unit,
            fare_source=fare_source,
            from_stop_id=req.from_stop_id,
            to_stop_id=req.to_stop_id,
            vehicle_number=req.vehicle_number or req.bus_id,
            user_id=user_id,
            is_sandbox=self.provider.is_sandbox,
        )
        with self._lock:
            self.provider.create_order(payment_id, total, record.currency)
            self._records[payment_id] = record
        logger.info("[PAYMENTS] Created %s (%s ₹%d, provider=%s)", payment_id, record.route_number, total, record.provider)
        return record

    def get(self, payment_id: str) -> PaymentRecord:
        rec = self._records.get(payment_id)
        if rec is None:
            raise PaymentError(404, "Payment not found")
        return rec

    def verify(self, req: PaymentVerifyRequest) -> PaymentRecord:
        with self._lock:
            rec = self.get(req.payment_id)
            if rec.status in FINAL_STATUSES:
                return rec  # idempotent
            if req.sandbox_outcome is not None:
                if not isinstance(self.provider, SandboxPaymentProvider):
                    raise PaymentError(403, "Outcome simulation is only available with the sandbox provider.")
                if req.sandbox_outcome not in FINAL_STATUSES:
                    raise PaymentError(400, "Invalid final payment outcome")
                rec.status = PaymentStatus.PAYMENT_PROCESSING
                self.provider.simulate(rec.payment_id, req.sandbox_outcome)
            # Authoritative status comes from the provider, not from the request.
            status = self.provider.fetch_status(rec.payment_id)
            rec.status = status
            if status in FINAL_STATUSES:
                rec.completed_at = _now()
            if status == PaymentStatus.PAYMENT_SUCCESS and not rec.transaction_reference:
                rec.transaction_reference = f"MOCK-TXN-{uuid.uuid4().hex[:10].upper()}"
        logger.info("[PAYMENTS] Verified %s -> %s", rec.payment_id, rec.status.value)
        return rec

    def reserve_for_ticket(self, payment_id: str) -> PaymentRecord:
        """Atomically claims a verified payment for one ticket. Raises 409 when it cannot be used."""
        with self._lock:
            rec = self.get(payment_id)
            if rec.status != PaymentStatus.PAYMENT_SUCCESS or self.provider.fetch_status(payment_id) != PaymentStatus.PAYMENT_SUCCESS:
                raise PaymentError(409, "Payment is not successfully verified. No ticket has been issued.")
            if rec.ticket_id:
                raise PaymentError(409, "This payment has already been used for a ticket.")
            rec.ticket_id = "RESERVED"
            return rec

    def release(self, payment_id: str) -> None:
        with self._lock:
            rec = self._records.get(payment_id)
            if rec and rec.ticket_id == "RESERVED":
                rec.ticket_id = None

    def attach_ticket(self, payment_id: str, ticket_id: str) -> None:
        with self._lock:
            self.get(payment_id).ticket_id = ticket_id

    def history(self, user_id: Optional[str] = None) -> List[PaymentRecord]:
        # Guests only see payments made without an account; signed-in users only see their own.
        items = [r for r in self._records.values() if r.user_id == user_id]
        return sorted(items, key=lambda r: r.created_at, reverse=True)

    def receipt(self, payment_id: str) -> PaymentReceipt:
        rec = self.get(payment_id)
        return PaymentReceipt(
            receipt_number=f"RCPT-{rec.payment_id[4:]}",
            payment_id=rec.payment_id,
            transaction_reference=rec.transaction_reference,
            status=rec.status,
            amount=rec.amount,
            currency=rec.currency,
            provider=rec.provider,
            route_number=rec.route_number,
            source=rec.source,
            destination=rec.destination,
            ticket_type=rec.ticket_type,
            quantity=rec.quantity,
            unit_fare=rec.unit_fare,
            ticket_id=rec.ticket_id,
            paid_at=rec.completed_at if rec.status == PaymentStatus.PAYMENT_SUCCESS else None,
        )

    def stats(self) -> Dict[str, int]:
        out = {s.value: 0 for s in PaymentStatus}
        for r in self._records.values():
            out[r.status.value] += 1
        return {**out, "total": len(self._records)}


payment_service = PaymentService()
