import unittest
from fastapi.testclient import TestClient

from app.main import app
from app.services.identity_provider import identity_service
from app.services.ticket_service import ticket_service

client = TestClient(app)


class TestIdentityVerification(unittest.TestCase):
    def setUp(self):
        # Reset override mode to MATCH
        identity_service.set_demo_override("MATCH")

    def test_01_create_session_requires_consent(self):
        res = client.post("/api/identity/session", json={
            "user_id": "USER-1",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": False
        })
        self.assertEqual(res.status_code, 400)

    def test_02_create_session_success(self):
        res = client.post("/api/identity/session", json={
            "user_id": "USER-TEST-1",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("session_id", data)
        self.assertEqual(data["passenger_type"], "female")
        self.assertEqual(data["status"], "DOCUMENT_PENDING")
        self.assertIn("Simulated verification only", data["disclaimer"])

    def test_03_verify_document_masked_only(self):
        # Create session
        s_res = client.post("/api/identity/session", json={
            "user_id": "USER-TEST-2",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        session_id = s_res.json()["session_id"]

        # Submit masked document
        d_res = client.post("/api/identity/document", json={
            "session_id": session_id,
            "document_type": "aadhaar_card",
            "last_four_digits": "9876",
            "has_photo_present": True,
            "user_consent": True
        })
        self.assertEqual(d_res.status_code, 200)
        data = d_res.json()
        self.assertEqual(data["masked_id_preview"], "XXXX XXXX 9876")
        self.assertEqual(data["status"], "DOCUMENT_DEMO_VERIFIED")

    def test_04_register_selfie_liveness(self):
        s_res = client.post("/api/identity/session", json={
            "user_id": "USER-TEST-3",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        session_id = s_res.json()["session_id"]

        selfie_res = client.post("/api/identity/selfie", json={
            "session_id": session_id,
            "liveness_confirmed": True
        })
        self.assertEqual(selfie_res.status_code, 200)
        self.assertEqual(selfie_res.json()["status"], "SELFIE_PENDING")

    def test_05_execute_verification_match_female_concession(self):
        s_res = client.post("/api/identity/session", json={
            "user_id": "USER-TEST-4",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        session_id = s_res.json()["session_id"]

        # Verify document
        client.post("/api/identity/document", json={
            "session_id": session_id,
            "last_four_digits": "4321",
            "user_consent": True
        })

        # Execute verification
        v_res = client.post(f"/api/identity/verify?session_id={session_id}")
        self.assertEqual(v_res.status_code, 200)
        data = v_res.json()
        self.assertEqual(data["status"], "MATCH")
        self.assertTrue(data["verified"])
        self.assertEqual(data["eligibility_status"], "ELIGIBLE")
        self.assertEqual(data["fare_discount_percentage"], 100)
        self.assertEqual(data["masked_id_preview"], "XXXX XXXX 4321")

    def test_06_execute_verification_male_ineligible_for_women_scheme(self):
        s_res = client.post("/api/identity/session", json={
            "user_id": "USER-TEST-MALE",
            "passenger_type": "male",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        session_id = s_res.json()["session_id"]

        client.post("/api/identity/document", json={
            "session_id": session_id,
            "last_four_digits": "1111",
            "user_consent": True
        })

        v_res = client.post(f"/api/identity/verify?session_id={session_id}")
        self.assertEqual(v_res.status_code, 200)
        data = v_res.json()
        self.assertEqual(data["status"], "MATCH")
        self.assertEqual(data["eligibility_status"], "INELIGIBLE")
        self.assertEqual(data["fare_discount_percentage"], 0)

    def test_07_demo_override_mismatch(self):
        identity_service.set_demo_override("MISMATCH")

        s_res = client.post("/api/identity/session", json={
            "user_id": "USER-TEST-MISMATCH",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        session_id = s_res.json()["session_id"]

        v_res = client.post(f"/api/identity/verify?session_id={session_id}")
        self.assertEqual(v_res.status_code, 200)
        data = v_res.json()
        self.assertEqual(data["status"], "MISMATCH")
        self.assertFalse(data["verified"])
        self.assertEqual(data["eligibility_status"], "INELIGIBLE")

    def test_08_demo_override_unavailable(self):
        identity_service.set_demo_override("VERIFICATION_UNAVAILABLE")

        s_res = client.post("/api/identity/session", json={
            "user_id": "USER-TEST-UNAVAIL",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        session_id = s_res.json()["session_id"]

        v_res = client.post(f"/api/identity/verify?session_id={session_id}")
        self.assertEqual(v_res.status_code, 200)
        data = v_res.json()
        self.assertEqual(data["status"], "VERIFICATION_UNAVAILABLE")
        self.assertFalse(data["verified"])
        self.assertEqual(data["eligibility_status"], "RETRY_REQUIRED")

    def test_09_demo_override_api_endpoint(self):
        res = client.post("/api/identity/demo-override", json={"mode": "MISMATCH"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["mode"], "MISMATCH")

    def test_10_get_identity_status(self):
        # Using pre-seeded session
        res = client.get("/api/identity/status/DEMO-SHAKTI-SESSION-001")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["session_id"], "DEMO-SHAKTI-SESSION-001")
        self.assertTrue(data["is_eligible_for_concession"])
        self.assertEqual(data["masked_id_preview"], "XXXX XXXX 4821")

    def test_11_concession_ticket_creation_zero_fare(self):
        res = client.post("/api/tickets", json={
            "route_number": "500D",
            "source": "Central Silk Board",
            "destination": "Majestic",
            "bus_type": "BMTC Ordinary",
            "fare_rupees": 25,
            "fare_type": "women_demo_concession",
            "passenger_gender": "female",
            "identity_status": "demo_verified"
        })
        self.assertEqual(res.status_code, 200)
        ticket = res.json()
        self.assertEqual(ticket["fare_rupees"], 0)
        self.assertEqual(ticket["fare_type"], "women_demo_concession")
        self.assertEqual(ticket["passenger_gender"], "female")
        self.assertEqual(ticket["identity_status"], "demo_verified")
        self.assertIn("concession", ticket["qr_payload"])

    def test_12_standard_ticket_creation_preserves_fare(self):
        res = client.post("/api/tickets", json={
            "route_number": "500D",
            "source": "Central Silk Board",
            "destination": "Majestic",
            "bus_type": "BMTC Ordinary",
            "fare_rupees": 25,
            "fare_type": "standard_demo_fare"
        })
        self.assertEqual(res.status_code, 200)
        ticket = res.json()
        self.assertEqual(ticket["fare_rupees"], 25)
        self.assertEqual(ticket["fare_type"], "standard_demo_fare")

    def test_13_conductor_verify_concession_ticket(self):
        # Create a concession ticket
        c_res = client.post("/api/tickets", json={
            "route_number": "500D",
            "source": "Central Silk Board",
            "destination": "Majestic",
            "bus_type": "BMTC Ordinary",
            "fare_rupees": 25,
            "fare_type": "women_demo_concession",
            "passenger_gender": "female",
            "identity_status": "demo_verified"
        })
        ticket = c_res.json()
        ticket_id = ticket["ticket_id"]

        # Conductor verifies ticket
        v_res = client.post("/api/tickets/verify", json={
            "qr_payload_or_code": ticket_id,
            "conductor_route_number": "500D"
        })
        self.assertEqual(v_res.status_code, 200)
        v_data = v_res.json()
        self.assertTrue(v_data["valid"])
        self.assertEqual(v_data["status"], "active")
        self.assertEqual(v_data["ticket"]["fare_rupees"], 0)
        self.assertEqual(v_data["ticket"]["fare_type"], "women_demo_concession")
        # Ensure zero sensitive biometric data in ticket response
        self.assertNotIn("aadhaar", str(v_data).lower())
        self.assertNotIn("selfie", str(v_data).lower())

    def test_14_demo_reset_restores_identity_sessions(self):
        # Create a transient session
        s_res = client.post("/api/identity/session", json={
            "user_id": "USER-TEMP-SESSION",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        self.assertEqual(s_res.status_code, 200)
        temp_session_id = s_res.json()["session_id"]

        # Reset demo state via endpoint
        reset_res = client.post("/api/demo/reset")
        self.assertEqual(reset_res.status_code, 200)
        self.assertEqual(reset_res.json()["status"], "success")

        # Verify default seeded session is restored
        seeded_res = client.get("/api/identity/status/DEMO-SHAKTI-SESSION-001")
        self.assertEqual(seeded_res.status_code, 200)
        seeded_data = seeded_res.json()
        self.assertEqual(seeded_data["session_id"], "DEMO-SHAKTI-SESSION-001")
        self.assertTrue(seeded_data["is_eligible_for_concession"])
        self.assertEqual(seeded_data["masked_id_preview"], "XXXX XXXX 4821")

    def test_15_conductor_route_mismatch_verification(self):
        # Create a ticket for Route 500D
        ticket_res = client.post("/api/tickets", json={
            "route_number": "500D",
            "source": "Central Silk Board",
            "destination": "Hebbal",
            "bus_type": "BMTC Ordinary",
            "fare_rupees": 25,
            "fare_type": "women_demo_concession",
            "passenger_gender": "female",
            "identity_status": "demo_verified"
        })
        self.assertEqual(ticket_res.status_code, 200)
        ticket_id = ticket_res.json()["ticket_id"]

        # Conductor verifies ticket on a mismatched route (335E)
        verify_res = client.post("/api/tickets/verify", json={
            "qr_payload_or_code": ticket_id,
            "conductor_route_number": "335E"
        })
        self.assertEqual(verify_res.status_code, 200)
        v_data = verify_res.json()
        self.assertFalse(v_data["valid"])
        self.assertEqual(v_data["status"], "mismatch")
        self.assertIn("Route Mismatch", v_data["message"])

    def test_16_strict_zero_storage_privacy_compliance(self):
        # Verify creating and running an entire verification session never retains raw Aadhaar or biometrics
        s_res = client.post("/api/identity/session", json={
            "user_id": "USER-PRIVACY-AUDIT",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "consent_obtained": True
        })
        session_id = s_res.json()["session_id"]

        # Document submission with 4-digit last suffix
        d_res = client.post("/api/identity/document", json={
            "session_id": session_id,
            "document_type": "aadhaar_card",
            "last_four_digits": "7712",
            "has_photo_present": True,
            "user_consent": True
        })
        self.assertEqual(d_res.status_code, 200)

        # Liveness registration
        selfie_res = client.post("/api/identity/selfie", json={
            "session_id": session_id,
            "liveness_confirmed": True
        })
        self.assertEqual(selfie_res.status_code, 200)

        # Verify session
        v_res = client.post(f"/api/identity/verify?session_id={session_id}")
        self.assertEqual(v_res.status_code, 200)
        v_json = v_res.json()

        # Audit session dictionary
        session = identity_service.get_session(session_id)
        self.assertIsNotNone(session)
        # Check no raw 12-digit Aadhaar exists anywhere
        self.assertNotIn("raw_aadhaar", session)
        self.assertNotIn("selfie_base64", session)
        self.assertNotIn("biometrics", session)
        self.assertEqual(session.get("masked_id"), "XXXX XXXX 7712")


if __name__ == "__main__":
    unittest.main()
