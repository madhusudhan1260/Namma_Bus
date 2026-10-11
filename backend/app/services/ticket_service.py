import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .provider_factory import get_transit_provider
from ..models.transit import (
    Ticket,
    TicketCreateRequest,
    TicketVerificationRequest,
    TicketVerificationResponse,
)

logger = logging.getLogger("nammamove.ticket_service")

# Phase 48: the signing secret comes from TICKET_HMAC_SECRET. The fallback is a development-only value;
# config validation warns when it is used in production.
DEV_TICKET_HMAC_SECRET = "nammablr_ticket_tamper_signature_key_2026"
HMAC_SECRET = os.getenv("TICKET_HMAC_SECRET", DEV_TICKET_HMAC_SECRET).encode("utf-8")


def compute_ticket_signature(ticket_id: str, route_number: str, fare_rupees: int, expires_at: str, payment_id: Optional[str] = None) -> str:
    """
    Compute HMAC-SHA256 tamper-evident digital signature for demo transit QR payloads.
    Paid tickets (Phase 43) also sign the payment reference; unpaid tickets keep the original payload.
    """
    payload = f"{ticket_id}:{route_number}:{fare_rupees}:{expires_at}"
    if payment_id:
        payload += f":{payment_id}"
    return hmac.new(HMAC_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def verify_ticket_signature(ticket_id: str, route_number: str, fare_rupees: int, expires_at: str, signature: str, payment_id: Optional[str] = None) -> bool:
    """Verify HMAC-SHA256 tamper-evident digital signature."""
    expected = compute_ticket_signature(ticket_id, route_number, fare_rupees, expires_at, payment_id)
    return hmac.compare_digest(expected, str(signature))


class TicketService:
    """
    In-memory demo digital ticketing service.
    
    SAFETY & INTEGRITY RULES:
    - Zero real money transactions or banking connections.
    - Explicitly labeled as prototype demo tickets.
    - Verifies route validity against active transit corridors.
    - Records validation events for conductor tally and future crowd prediction.
    """

    def __init__(self):
        self._tickets: Dict[str, Ticket] = {}
        self._validation_events: List[Dict] = []
        self._validations_by_route: Dict[str, int] = {}
        self._seed_initial_tickets()

    def _seed_initial_tickets(self):
        """Seed pre-configured tickets for instant demonstration."""
        now = datetime.utcnow()

        # 1. Active demo ticket
        active_id = "NMA-500D-8F42A1"
        active_exp = now + timedelta(hours=1, minutes=45)
        active_sig = compute_ticket_signature(active_id, "500D", 25, active_exp.isoformat())
        active_qr = json.dumps({
            "ticketId": active_id,
            "route": "500D",
            "from": "Central Silk Board Junction",
            "to": "Majestic (Kempegowda Bus Station)",
            "fare": 25,
            "issuedAt": (now - timedelta(minutes=15)).isoformat(),
            "expiresAt": active_exp.isoformat(),
            "signature": active_sig,
            "demo": True,
        })
        self._tickets[active_id] = Ticket(
            ticket_id=active_id,
            route_number="500D",
            source="Central Silk Board Junction",
            destination="Majestic (Kempegowda Bus Station)",
            fare_rupees=25,
            bus_type="Vajra AC Electric",
            issued_at=now - timedelta(minutes=15),
            expires_at=active_exp,
            passenger_id="PASS-84920",
            qr_payload=active_qr,
            status="active",
        )

        # 2. Used demo ticket
        used_id = "NMA-356-C19A02"
        used_exp = now - timedelta(hours=1)
        used_sig = compute_ticket_signature(used_id, "356", 20, used_exp.isoformat())
        used_qr = json.dumps({
            "ticketId": used_id,
            "route": "356",
            "from": "Electronic City Phase 1",
            "to": "Shivajinagar Bus Station",
            "fare": 20,
            "issuedAt": (now - timedelta(hours=3)).isoformat(),
            "expiresAt": used_exp.isoformat(),
            "signature": used_sig,
            "demo": True,
        })
        self._tickets[used_id] = Ticket(
            ticket_id=used_id,
            route_number="356",
            source="Electronic City Phase 1",
            destination="Shivajinagar Bus Station",
            fare_rupees=20,
            bus_type="BMTC Ordinary",
            issued_at=now - timedelta(hours=3),
            expires_at=used_exp,
            passenger_id="PASS-84920",
            qr_payload=used_qr,
            status="used",
            used_at=now - timedelta(hours=2, minutes=30),
        )

        # 3. Expired demo ticket
        expired_id = "NMA-201R-B51203"
        expired_exp = now - timedelta(hours=3)
        expired_sig = compute_ticket_signature(expired_id, "201R", 20, expired_exp.isoformat())
        expired_qr = json.dumps({
            "ticketId": expired_id,
            "route": "201R",
            "from": "BTM Layout Water Tank",
            "to": "Majestic (Kempegowda Bus Station)",
            "fare": 20,
            "issuedAt": (now - timedelta(hours=5)).isoformat(),
            "expiresAt": expired_exp.isoformat(),
            "signature": expired_sig,
            "demo": True,
        })
        self._tickets[expired_id] = Ticket(
            ticket_id=expired_id,
            route_number="201R",
            source="BTM Layout Water Tank",
            destination="Majestic (Kempegowda Bus Station)",
            fare_rupees=20,
            bus_type="BMTC Ordinary",
            issued_at=now - timedelta(hours=5),
            expires_at=expired_exp,
            passenger_id="PASS-84920",
            qr_payload=expired_qr,
            status="expired",
        )

    async def create_ticket(
        self,
        req: TicketCreateRequest,
        payment_id: Optional[str] = None,
        payment_status: Optional[str] = None,
        passenger_count: int = 1,
        ticket_type: Optional[str] = None,
        route_validated: bool = False,
        vehicle_number: Optional[str] = None,
    ) -> Ticket:
        """
        Creates a verified demo digital ticket connected to active transit routes.
        Rejects arbitrary non-existent bus routes.
        """
        provider = get_transit_provider()
        buses = await provider.get_buses()
        valid_routes = {b.route_number.upper() for b in buses}

        clean_route = req.route_number.strip().upper()
        # Network routes are validated against the BMTC network by the caller (route_validated=True)
        if not route_validated and clean_route not in valid_routes:
            raise ValueError(
                f"Route '{req.route_number}' does not exist on active transit corridors. "
                f"Valid routes: {', '.join(sorted(valid_routes))}"
            )

        now = datetime.utcnow()
        expires = now + timedelta(hours=2)
        unique_suffix = uuid.uuid4().hex[:6].upper()
        ticket_id = f"NMA-{clean_route.replace(' ', '')}-{unique_suffix}"

        # Fare concession calculation
        is_concession = req.fare_type == "women_demo_concession"
        fare_amount = 0 if is_concession else (req.fare_rupees if req.fare_rupees is not None else 25)

        sig = compute_ticket_signature(ticket_id, clean_route, fare_amount, expires.isoformat(), payment_id)
        qr_data = {
            "ticketId": ticket_id,
            "route": clean_route,
            "from": req.source.strip(),
            "to": req.destination.strip(),
            "fare": fare_amount,
            "fareType": req.fare_type or "standard_demo_fare",
            "issuedAt": now.isoformat(),
            "expiresAt": expires.isoformat(),
            "signature": sig,
            "demo": True,
        }
        if payment_id:
            qr_data["paymentId"] = payment_id
            qr_data["passengers"] = passenger_count
        if vehicle_number:
            qr_data["bus"] = vehicle_number
        if is_concession:
            qr_data["concession"] = "WOMEN COMMUTER CONCESSION — BMTC SHAKTI SCHEME (DEMO)"
            qr_data["scheme"] = "GOVERNMENT OF KARNATAKA CONCESSION"
        qr_payload = json.dumps(qr_data)

        ticket = Ticket(
            ticket_id=ticket_id,
            route_number=clean_route,
            source=req.source.strip(),
            destination=req.destination.strip(),
            fare_rupees=fare_amount,
            bus_type=req.bus_type or "BMTC Ordinary",
            issued_at=now,
            expires_at=expires,
            passenger_id="PASS-84920",
            qr_payload=qr_payload,
            status="active",
            fare_type=req.fare_type or "standard_demo_fare",
            passenger_gender=req.passenger_gender,
            identity_status=req.identity_status,
            payment_id=payment_id,
            payment_status=payment_status,
            passenger_count=passenger_count,
            ticket_type=ticket_type,
            vehicle_number=vehicle_number,
        )

        self._tickets[ticket_id] = ticket
        logger.info("Demo ticket created: %s (%s, fare=%d, type=%s)", ticket_id, clean_route, fare_amount, ticket.fare_type)
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """Retrieves a ticket by ID and checks for automatic expiration."""
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            return None

        self._expire_if_due(ticket)
        return ticket

    def _expire_if_due(self, ticket: Ticket) -> None:
        """Marks an active ticket expired once past expiry and emits a single TICKET_EXPIRED notification."""
        if ticket.status == "active" and datetime.utcnow() > ticket.expires_at:
            ticket.status = "expired"
            from .notification_center_service import notification_center_service
            notification_center_service.publish(
                "TICKET_EXPIRED",
                "Ticket expired",
                f"Demo ticket {ticket.ticket_id} for route {ticket.route_number} has expired.",
                route_number=ticket.route_number,
                source="SYSTEM",
                dedup_key=f"ticket-expired:{ticket.ticket_id}",
            )

    def verify_ticket(self, payload_or_code: str, conductor_route_number: Optional[str] = None) -> TicketVerificationResponse:
        """
        Verifies a ticket presented to conductor via QR payload or direct ticket ID code.
        Distinguishes active, already-used, expired, invalid, and route mismatch tickets.
        """
        clean_input = payload_or_code.strip()
        ticket_id = clean_input

        # Check if input is a JSON QR payload
        if clean_input.startswith("{") and clean_input.endswith("}"):
            try:
                parsed = json.loads(clean_input)
                ticket_id = parsed.get("ticketId", clean_input)
                # Tamper-evident digital signature verification
                if "signature" in parsed:
                    sig = parsed.get("signature", "")
                    p_route = parsed.get("route", "")
                    p_fare = parsed.get("fare", 0)
                    p_exp = parsed.get("expiresAt", "")
                    p_payment = parsed.get("paymentId")
                    if not verify_ticket_signature(ticket_id, p_route, p_fare, p_exp, sig, p_payment):
                        return TicketVerificationResponse(
                            valid=False,
                            status="invalid",
                            message="Ticket validation failed: Tamper-evident digital signature is invalid or modified.",
                        )
            except Exception:
                return TicketVerificationResponse(
                    valid=False,
                    status="invalid",
                    message="Ticket information could not be verified. Invalid QR structure.",
                )

        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return TicketVerificationResponse(
                valid=False,
                status="invalid",
                message="Ticket information could not be verified. Unknown ticket ID.",
            )

        # Route mismatch detection
        if conductor_route_number and ticket.route_number:
            c_route = conductor_route_number.strip().upper().replace("-", "").replace(" ", "")
            t_route = ticket.route_number.strip().upper().replace("-", "").replace(" ", "")
            if c_route != t_route:
                return TicketVerificationResponse(
                    valid=False,
                    status="mismatch",
                    message=f"Route Mismatch: Ticket is issued for Route {ticket.route_number}, but conductor is verifying on Route {conductor_route_number}.",
                    ticket=ticket,
                )

        if ticket.status == "active":
            return TicketVerificationResponse(
                valid=True,
                status="active",
                message="Valid demo ticket.",
                ticket=ticket,
            )
        elif ticket.status == "used":
            used_str = f" at {ticket.used_at.strftime('%H:%M:%S')}" if ticket.used_at else ""
            return TicketVerificationResponse(
                valid=False,
                status="used",
                message=f"This ticket has already been validated{used_str}.",
                ticket=ticket,
            )
        elif ticket.status == "expired":
            return TicketVerificationResponse(
                valid=False,
                status="expired",
                message="This ticket is no longer valid.",
                ticket=ticket,
            )
        else:
            return TicketVerificationResponse(
                valid=False,
                status="invalid",
                message="Ticket information could not be verified.",
                ticket=ticket,
            )

    def use_ticket(self, ticket_id: str) -> TicketVerificationResponse:
        """
        Conductor action to validate and mark a ticket as used.
        Records validation event for crowd prediction counting.
        """
        verification = self.verify_ticket(ticket_id)
        if not verification.valid or not verification.ticket:
            return verification

        ticket = verification.ticket
        ticket.status = "used"
        ticket.used_at = datetime.utcnow()

        # Record validation event for passenger counting analytics
        event = {
            "ticket_id": ticket.ticket_id,
            "route_number": ticket.route_number,
            "timestamp": ticket.used_at,
            "stop": ticket.source,
        }
        self._validation_events.append(event)
        self._validations_by_route[ticket.route_number] = (
            self._validations_by_route.get(ticket.route_number, 0) + 1
        )

        logger.info("Ticket marked as USED by conductor: %s (Route %s)", ticket.ticket_id, ticket.route_number)

        return TicketVerificationResponse(
            valid=True,
            status="used",
            message="Ticket successfully validated and marked as used.",
            ticket=ticket,
        )

    def get_history(self) -> List[Ticket]:
        """Returns all tickets sorted by issued timestamp descending."""
        for t in self._tickets.values():
            self._expire_if_due(t)

        return sorted(self._tickets.values(), key=lambda t: t.issued_at, reverse=True)

    def get_stats(self) -> Dict:
        """Returns validation statistics for conductor reporting."""
        return {
            "total_tickets_generated": len(self._tickets),
            "total_validations": len(self._validation_events),
            "validations_by_route": self._validations_by_route,
        }

    def reset(self):
        """Reset ticket store and verification statistics back to initial seeded demo state."""
        self._tickets.clear()
        self._validation_events.clear()
        self._validations_by_route.clear()
        self._seed_initial_tickets()
        logger.info("TicketService state reset to initial demo seeds.")


# Global singleton instance
ticket_service = TicketService()
