import json
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.core import middleware
from app.services.ticket_service import verify_ticket_signature
from app.services.payment_service import payment_service

DISCLOSURE = "DEMO PAYMENT — NO REAL MONEY CHARGED"


class TestPhase43PaymentTicketing(unittest.TestCase):
    """Master spec Phase 43: sandbox payment → verification → EXISTING TicketService → conductor."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def tearDown(self):
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def _create(self, route="500D", ticket_type="ADULT", quantity=1, headers=None):
        return self.client.post("/api/payment/create", json={
            "route_number": route, "source": "Central Silk Board", "destination": "Majestic",
            "ticket_type": ticket_type, "quantity": quantity,
        }, headers=headers or {})

    def _verify(self, pid, outcome="PAYMENT_SUCCESS"):
        return self.client.post("/api/payment/verify", json={"payment_id": pid, "sandbox_outcome": outcome})

    def _paid_ticket(self, **kw):
        pid = self._create(**kw).json()["payment_id"]
        self._verify(pid)
        return pid, self.client.post("/api/tickets/purchase", json={"payment_id": pid})

    def test_create_computes_fare_on_server(self):
        rec = self._create(quantity=2).json()
        self.assertEqual(rec["status"], "PAYMENT_PENDING")
        self.assertEqual(rec["provider"], "MOCK_SANDBOX")
        self.assertEqual(rec["amount"], 50)
        self.assertEqual(rec["disclosure"], DISCLOSURE)
        student = self._create(ticket_type="STUDENT").json()
        self.assertEqual(student["unit_fare"], 15)
        # client cannot inject an amount
        self.assertEqual(self.client.post("/api/payment/create", json={"route_number": "500D", "source": "a", "destination": "b", "amount": 1}).json()["amount"], 25)
        self.assertEqual(self._create(route="999X").status_code, 400)
        self.assertEqual(self._create(quantity=7).status_code, 422)
        self.assertEqual(self._create(ticket_type="VIP").status_code, 400)

    def test_quote_matches_payment_amount(self):
        q = self.client.get("/api/payment/quote?route_number=KIA-8&ticket_type=STUDENT&quantity=3").json()
        rec = self._create(route="KIA-8", ticket_type="STUDENT", quantity=3).json()
        self.assertEqual(q["total"], rec["amount"])
        self.assertEqual(q["fare_source"], "DEMO_FARE_TABLE")
        self.assertEqual(self.client.get("/api/payment/quote?route_number=ZZZ").status_code, 400)

    def test_pending_failed_cancelled_do_not_issue(self):
        pid = self._create().json()["payment_id"]
        self.assertEqual(self.client.post("/api/tickets/purchase", json={"payment_id": pid}).status_code, 409)
        for outcome in ("PAYMENT_FAILED", "PAYMENT_CANCELLED"):
            pid = self._create().json()["payment_id"]
            self.assertEqual(self._verify(pid, outcome).json()["status"], outcome)
            res = self.client.post("/api/tickets/purchase", json={"payment_id": pid})
            self.assertEqual(res.status_code, 409)
            self.assertIn("No ticket has been issued", res.json()["detail"])

    def test_invalid_outcome_and_idempotent_final_state(self):
        pid = self._create().json()["payment_id"]
        self.assertEqual(self._verify(pid, "PAYMENT_PENDING").status_code, 400)
        self._verify(pid, "PAYMENT_FAILED")
        # final state cannot be flipped to success afterwards
        self.assertEqual(self._verify(pid, "PAYMENT_SUCCESS").json()["status"], "PAYMENT_FAILED")

    def test_success_issues_ticket_via_existing_service_with_signed_payment(self):
        pid, res = self._paid_ticket(quantity=2)
        self.assertEqual(res.status_code, 200)
        t = res.json()
        self.assertTrue(t["ticket_id"].startswith("NMA-500D-"))
        self.assertEqual(t["disclaimer"], "DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL")
        self.assertEqual(t["payment_id"], pid)
        self.assertEqual(t["payment_status"], "PAYMENT_SUCCESS")
        self.assertEqual(t["fare_rupees"], 50)
        self.assertEqual(t["passenger_count"], 2)
        qr = json.loads(t["qr_payload"])
        self.assertEqual(qr["paymentId"], pid)
        self.assertTrue(verify_ticket_signature(qr["ticketId"], qr["route"], qr["fare"], qr["expiresAt"], qr["signature"], pid))
        # stripping the payment reference breaks the signature
        self.assertFalse(verify_ticket_signature(qr["ticketId"], qr["route"], qr["fare"], qr["expiresAt"], qr["signature"]))
        history_ids = [x["ticket_id"] for x in self.client.get("/api/tickets/history").json()]
        self.assertIn(t["ticket_id"], history_ids)

    def test_payment_replay_blocked(self):
        pid, first = self._paid_ticket()
        self.assertEqual(first.status_code, 200)
        again = self.client.post("/api/tickets/purchase", json={"payment_id": pid})
        self.assertEqual(again.status_code, 409)

    def test_tampered_qr_rejected_and_conductor_flow(self):
        _, res = self._paid_ticket()
        t = res.json()
        tampered = json.loads(t["qr_payload"])
        tampered["paymentId"] = "PAY-FORGED"
        bad = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": json.dumps(tampered), "conductor_route_number": "500D"}).json()
        self.assertFalse(bad["valid"])
        self.assertEqual(bad["status"], "invalid")
        ok = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": t["qr_payload"], "conductor_route_number": "500D"}).json()
        self.assertTrue(ok["valid"])
        mismatch = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": t["qr_payload"], "conductor_route_number": "356"}).json()
        self.assertEqual(mismatch["status"], "mismatch")
        self.assertTrue(self.client.post(f"/api/tickets/{t['ticket_id']}/use").json()["valid"])
        used = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": t["qr_payload"]}).json()
        self.assertEqual(used["status"], "used")

    def test_receipt_and_history_contain_no_sensitive_fields(self):
        pid, res = self._paid_ticket()
        receipt = self.client.get(f"/api/payment/{pid}/receipt").json()
        self.assertEqual(receipt["ticket_id"], res.json()["ticket_id"])
        self.assertEqual(receipt["disclosure"], DISCLOSURE)
        self.assertTrue(receipt["transaction_reference"].startswith("MOCK-TXN-"))
        blob = json.dumps(receipt).lower() + json.dumps(self.client.get("/api/payment/history").json()).lower()
        for word in ("card", "cvv", "upi_pin", "pin\"", "password"):
            self.assertNotIn(word, blob)
        self.assertEqual(self.client.get("/api/payment/PAY-NOPE").status_code, 404)

    def test_history_is_scoped_per_user(self):
        token = self.client.post("/api/auth/register", json={
            "full_name": "Ravi Kumar", "mobile": "9876500000", "email": "ravi@gmail.com",
        }).json()["session_token"]
        self._create(headers={"Authorization": f"Bearer {token}"})
        self._create()
        mine = self.client.get("/api/payment/history", headers={"Authorization": f"Bearer {token}"}).json()
        guest = self.client.get("/api/payment/history").json()
        self.assertEqual(len(mine), 1)
        self.assertEqual(len(guest), 1)
        self.assertNotEqual(mine[0]["payment_id"], guest[0]["payment_id"])

    def test_notifications_for_payment_and_ticket(self):
        self._paid_ticket()
        events = [n.get("event_type") for n in self.client.get("/api/notifications").json()]
        self.assertIn("PAYMENT_STATUS", events)
        self.assertIn("TICKET_PURCHASED", events)

    def test_demo_reset_clears_payments(self):
        self._paid_ticket()
        self.client.post("/api/demo/reset")
        self.assertEqual(payment_service.stats()["total"], 0)

    def test_legacy_ticket_creation_unchanged(self):
        res = self.client.post("/api/tickets", json={"route_number": "500D", "source": "A", "destination": "B"})
        self.assertEqual(res.status_code, 200)
        qr = json.loads(res.json()["qr_payload"])
        self.assertNotIn("paymentId", qr)
        self.assertTrue(verify_ticket_signature(qr["ticketId"], qr["route"], qr["fare"], qr["expiresAt"], qr["signature"]))


if __name__ == "__main__":
    unittest.main()
