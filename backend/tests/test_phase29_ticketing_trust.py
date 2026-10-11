import json
import unittest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.services.ticket_service import ticket_service, compute_ticket_signature, verify_ticket_signature


class TestPhase29TicketingTrust(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        ticket_service.reset()

    def tearDown(self):
        ticket_service.reset()

    def test_complete_ticket_lifecycle(self):
        """Test ticket states: ACTIVE -> USED -> EXPIRED -> INVALID -> MISMATCH."""
        # 1. Create active ticket
        create_res = self.client.post(
            "/api/tickets",
            json={
                "route_number": "500D",
                "source": "Central Silk Board Junction",
                "destination": "Majestic (Kempegowda Bus Station)",
                "bus_type": "Vajra AC Electric",
                "fare_rupees": 25,
            },
        )
        self.assertEqual(create_res.status_code, 200)
        ticket_data = create_res.json()
        ticket_id = ticket_data["ticket_id"]
        self.assertEqual(ticket_data["status"], "active")
        self.assertEqual(ticket_data["disclaimer"], "DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL")

        # 2. Verify active ticket by conductor on matching route
        v_res = self.client.post(
            "/api/tickets/verify",
            json={"qr_payload_or_code": ticket_id, "conductor_route_number": "500D"},
        )
        self.assertEqual(v_res.status_code, 200)
        self.assertTrue(v_res.json()["valid"])
        self.assertEqual(v_res.json()["status"], "active")

        # 3. Mark ticket as USED
        use_res = self.client.post(f"/api/tickets/{ticket_id}/use")
        self.assertEqual(use_res.status_code, 200)
        self.assertEqual(use_res.json()["status"], "used")

        # 4. Duplicate scan prevention: second verification must return used
        dup_res = self.client.post(
            "/api/tickets/verify",
            json={"qr_payload_or_code": ticket_id, "conductor_route_number": "500D"},
        )
        self.assertEqual(dup_res.status_code, 200)
        self.assertFalse(dup_res.json()["valid"])
        self.assertEqual(dup_res.json()["status"], "used")
        self.assertIn("already been validated", dup_res.json()["message"])

    def test_route_mismatch_detection(self):
        """Ticket issued for Route 500D scanned on Route 356 must be rejected with mismatch status."""
        create_res = self.client.post(
            "/api/tickets",
            json={
                "route_number": "500D",
                "source": "Central Silk Board Junction",
                "destination": "Majestic (Kempegowda Bus Station)",
            },
        )
        ticket_id = create_res.json()["ticket_id"]

        # Conductor on Route 356 scans Route 500D ticket
        v_res = self.client.post(
            "/api/tickets/verify",
            json={"qr_payload_or_code": ticket_id, "conductor_route_number": "356"},
        )
        self.assertEqual(v_res.status_code, 200)
        data = v_res.json()
        self.assertFalse(data["valid"])
        self.assertEqual(data["status"], "mismatch")
        self.assertIn("Route Mismatch", data["message"])
        self.assertIn("500D", data["message"])
        self.assertIn("356", data["message"])

    def test_hmac_sha256_qr_signature_and_tampering(self):
        """Verify HMAC-SHA256 signature validates genuine payloads and detects tampering."""
        create_res = self.client.post(
            "/api/tickets",
            json={
                "route_number": "500D",
                "source": "Central Silk Board Junction",
                "destination": "Majestic (Kempegowda Bus Station)",
                "fare_rupees": 25,
            },
        )
        ticket_data = create_res.json()
        qr_payload_str = ticket_data["qr_payload"]
        qr_dict = json.loads(qr_payload_str)

        # Signature must be present
        self.assertIn("signature", qr_dict)
        self.assertTrue(len(qr_dict["signature"]) >= 16)

        # Valid payload passes verification
        v_res = self.client.post(
            "/api/tickets/verify",
            json={"qr_payload_or_code": qr_payload_str, "conductor_route_number": "500D"},
        )
        self.assertTrue(v_res.json()["valid"])
        self.assertEqual(v_res.json()["status"], "active")

        # Tampered payload: attacker alters fare or route in QR payload
        tampered_qr = dict(qr_dict)
        tampered_qr["fare"] = 0  # Tampering with fare
        tampered_res = self.client.post(
            "/api/tickets/verify",
            json={"qr_payload_or_code": json.dumps(tampered_qr), "conductor_route_number": "500D"},
        )
        self.assertFalse(tampered_res.json()["valid"])
        self.assertEqual(tampered_res.json()["status"], "invalid")
        self.assertIn("Tamper-evident", tampered_res.json()["message"])

    def test_women_concession_shakti_scheme_labeling(self):
        """Verify Shakti Scheme concession tickets are free, clearly labeled DEMO, and tamper-signed."""
        create_res = self.client.post(
            "/api/tickets",
            json={
                "route_number": "500D",
                "source": "Central Silk Board Junction",
                "destination": "Majestic (Kempegowda Bus Station)",
                "fare_type": "women_demo_concession",
                "passenger_gender": "female",
                "identity_status": "demo_verified",
            },
        )
        self.assertEqual(create_res.status_code, 200)
        ticket_data = create_res.json()
        self.assertEqual(ticket_data["fare_rupees"], 0)
        self.assertEqual(ticket_data["disclaimer"], "DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL")
        self.assertEqual(ticket_data["fare_type"], "women_demo_concession")

        # Check QR payload contains explicit Shakti scheme and Government of Karnataka metadata
        qr_dict = json.loads(ticket_data["qr_payload"])
        self.assertIn("SHAKTI SCHEME (DEMO)", qr_dict.get("concession", ""))
        self.assertIn("GOVERNMENT OF KARNATAKA CONCESSION", qr_dict.get("scheme", ""))

    def test_conductor_data_minimization(self):
        """Verify conductor response exposes zero raw identity, selfie, or biometric data."""
        create_res = self.client.post(
            "/api/tickets",
            json={
                "route_number": "500D",
                "source": "Central Silk Board Junction",
                "destination": "Majestic (Kempegowda Bus Station)",
                "fare_type": "women_demo_concession",
                "passenger_gender": "female",
                "identity_status": "demo_verified",
            },
        )
        ticket_id = create_res.json()["ticket_id"]

        v_res = self.client.post(
            "/api/tickets/verify",
            json={"qr_payload_or_code": ticket_id, "conductor_route_number": "500D"},
        )
        conductor_data = v_res.json()
        ticket_obj = conductor_data["ticket"]

        # Ensure conductor receives only operational transit fields
        forbidden_keys = [
            "aadhaar",
            "aadhaar_number",
            "raw_aadhaar",
            "biometric",
            "biometric_template",
            "selfie",
            "face_embedding",
            "phone_number",
            "otp",
        ]
        for key in forbidden_keys:
            self.assertNotIn(key, ticket_obj)
            self.assertNotIn(key, conductor_data)


if __name__ == "__main__":
    unittest.main()
