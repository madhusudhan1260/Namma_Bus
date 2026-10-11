import asyncio
import json
import unittest
from datetime import datetime, timedelta

from app.models.transit import TicketCreateRequest, TicketVerificationRequest
from app.services.ticket_service import TicketService


class TestTicketService(unittest.TestCase):
    """
    Test suite for Digital Tickets & Conductor Verification Prototype.
    Validates ticket issuance, route verification, QR payload integrity,
    status transitions, conductor validation, and expiry handling.
    """

    def setUp(self):
        # Create a fresh isolated ticket service for test repeatability
        self.service = TicketService()

    def test_1_create_ticket_valid_route(self):
        """Valid route on active corridor must generate an active ticket."""
        req = TicketCreateRequest(
            route_number="500D",
            source="Central Silk Board Junction",
            destination="Majestic (Kempegowda Bus Station)",
            bus_type="Vajra AC Electric",
            fare_rupees=25,
        )
        ticket = asyncio.run(self.service.create_ticket(req))
        self.assertIsNotNone(ticket)
        self.assertTrue(ticket.ticket_id.startswith("NMA-500D-"))
        self.assertEqual(ticket.route_number, "500D")
        self.assertEqual(ticket.status, "active")
        self.assertEqual(ticket.fare_rupees, 25)
        self.assertIsNone(ticket.used_at)

        # Verify QR payload is valid JSON and contains safe demo fields
        qr = json.loads(ticket.qr_payload)
        self.assertEqual(qr["ticketId"], ticket.ticket_id)
        self.assertEqual(qr["route"], "500D")
        self.assertEqual(qr["fare"], 25)
        self.assertTrue(qr["demo"])

    def test_2_create_ticket_invalid_route_rejected(self):
        """Arbitrary non-existent routes must be rejected."""
        req = TicketCreateRequest(
            route_number="999XYZ",
            source="Nowhere",
            destination="Anywhere",
            fare_rupees=50,
        )
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(self.service.create_ticket(req))
        self.assertIn("does not exist", str(ctx.exception))

    def test_3_verify_valid_ticket(self):
        """Verifying an active ticket by code or QR payload must return valid=True."""
        req = TicketCreateRequest(
            route_number="356",
            source="Electronic City",
            destination="Shivajinagar",
            fare_rupees=20,
        )
        ticket = asyncio.run(self.service.create_ticket(req))

        # Verify by code
        res1 = self.service.verify_ticket(ticket.ticket_id)
        self.assertTrue(res1.valid)
        self.assertEqual(res1.status, "active")
        self.assertIn("Valid demo ticket", res1.message)

        # Verify by full QR payload
        res2 = self.service.verify_ticket(ticket.qr_payload)
        self.assertTrue(res2.valid)
        self.assertEqual(res2.status, "active")

    def test_4_verify_invalid_ticket(self):
        """Non-existent ticket must report invalid status."""
        res = self.service.verify_ticket("NMA-FAKE-000000")
        self.assertFalse(res.valid)
        self.assertEqual(res.status, "invalid")
        self.assertIn("could not be verified", res.message)

    def test_5_verify_already_used_ticket(self):
        """A used ticket must report already validated."""
        # Use pre-seeded used ticket
        res = self.service.verify_ticket("NMA-356-C19A02")
        self.assertFalse(res.valid)
        self.assertEqual(res.status, "used")
        self.assertIn("already been validated", res.message)

    def test_6_verify_expired_ticket(self):
        """An expired ticket must report no longer valid."""
        # Use pre-seeded expired ticket
        res = self.service.verify_ticket("NMA-201R-B51203")
        self.assertFalse(res.valid)
        self.assertEqual(res.status, "expired")
        self.assertIn("no longer valid", res.message)

    def test_7_use_ticket_conductor_action(self):
        """Conductor action transitions active ticket to used and records validation event."""
        req = TicketCreateRequest(
            route_number="500D",
            source="Silk Board",
            destination="Majestic",
            fare_rupees=25,
        )
        ticket = asyncio.run(self.service.create_ticket(req))
        self.assertEqual(ticket.status, "active")

        # Conductor marks ticket as used
        use_res = self.service.use_ticket(ticket.ticket_id)
        self.assertTrue(use_res.valid)
        self.assertEqual(use_res.status, "used")
        self.assertIsNotNone(use_res.ticket.used_at)

        # Re-verifying must now report already used
        verify_again = self.service.verify_ticket(ticket.ticket_id)
        self.assertFalse(verify_again.valid)
        self.assertEqual(verify_again.status, "used")

    def test_8_ticket_history_and_stats(self):
        """History returns tickets and stats tracks validation counts."""
        history = self.service.get_history()
        self.assertGreaterEqual(len(history), 3)

        stats = self.service.get_stats()
        self.assertIn("total_tickets_generated", stats)
        self.assertIn("total_validations", stats)
        self.assertIn("validations_by_route", stats)


if __name__ == "__main__":
    unittest.main()
