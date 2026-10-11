import json
import logging
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import OPERATIONAL_STATEMENT_NOT_CONNECTED, settings
from app.core import middleware
from app.services.auth_service import auth_service, identity_onboarding_service
from app.services.ticket_service import ticket_service, verify_ticket_signature
from app.services.active_journey_service import active_journey_service
from app.services.notification_service import notification_service

DEMO_PASS_DISCLAIMER = "DEMO PASS — NOT VALID FOR REAL BMTC TRAVEL"
SENSITIVE_KEYS = ("aadhaar", "selfie", "image", "photo", "embedding", "biometric", "template", "password", "xml", "face")


class TestPhase41AuthIdentity(unittest.TestCase):
    """
    Phase 41: Commuter authentication, identity onboarding and Shakti access.
    Verifies passwordless registration/login, honest UNAVAILABLE / DEMO verification states,
    privacy (no raw Aadhaar, biometrics or selfies), Shakti ticket gating on the existing HMAC
    ticketing system, and demo reset.
    """

    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    def tearDown(self):
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()

    # -- helpers -----------------------------------------------------------

    def _register(self, mobile="9876543210", account_type="GENERAL", name="Asha Kumari", email="asha.k@gmail.com"):
        return self.client.post("/api/auth/register", json={
            "full_name": name, "mobile": mobile, "email": email, "account_type": account_type,
        })

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _shakti_user(self):
        res = self._register(account_type="SHAKTI_ONBOARDING")
        self.assertEqual(res.status_code, 200)
        return res.json()["session_token"]

    def _demo_verify(self, token, liveness=True):
        start = self.client.post("/api/identity/verification/start", json={"consent_confirmed": True}, headers=self._auth(token))
        self.assertEqual(start.status_code, 200)
        attempt_id = start.json()["attempt_id"]
        return self.client.post(
            "/api/identity/verification/complete",
            json={"attempt_id": attempt_id, "liveness_action_completed": liveness},
            headers=self._auth(token),
        )

    def _concession_ticket(self, token=None):
        headers = self._auth(token) if token else {}
        return self.client.post("/api/tickets", json={
            "route_number": "500D", "source": "Central Silk Board", "destination": "Hebbal",
            "fare_rupees": 0, "fare_type": "women_demo_concession",
        }, headers=headers)

    # -- 1-6: auth ---------------------------------------------------------

    def test_01_general_registration(self):
        res = self._register(mobile="+91 98765 43210")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["session_token"])
        user = data["user"]
        self.assertEqual(user["account_type"], "GENERAL")
        self.assertEqual(user["masked_mobile"], "+91 XXXXX X3210")
        self.assertEqual(user["email_verification_status"], "NOT_CONNECTED")
        self.assertEqual(data["authentication_assurance"], "UNVERIFIED_DEMO_CONTINUATION")
        self.assertEqual(data["email_verification_message"], "Email verification is not connected yet.")
        self.assertNotIn("otp", json.dumps(data).lower())
        # Duplicate mobile is rejected
        self.assertEqual(self._register(mobile="9876543210").status_code, 409)

    def test_02_general_login(self):
        self._register()
        res = self.client.post("/api/auth/login", json={"mobile": "09876543210"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["display_name"], "Asha Kumari")
        self.assertEqual(self.client.post("/api/auth/login", json={"mobile": "9123456780"}).status_code, 404)

    def test_03_invalid_mobile(self):
        for bad in ["12345", "5876543210", "98765432101", "abcdefghij"]:
            self.assertEqual(self._register(mobile=bad).status_code, 422, bad)

    def test_04_invalid_email(self):
        for bad in ["asha", "asha@", "asha@gmail", "@gmail.com", "a b@gmail.com"]:
            self.assertEqual(self._register(email=bad).status_code, 422, bad)
        self.assertEqual(self._register(name="12345").status_code, 422)

    def test_05_session_retrieval(self):
        token = self._register().json()["session_token"]
        me = self.client.get("/api/auth/me", headers=self._auth(token))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "asha.k@gmail.com")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me", headers=self._auth("forged")).status_code, 401)

    def test_06_logout(self):
        token = self._register().json()["session_token"]
        res = self.client.post("/api/auth/logout", headers=self._auth(token))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["session_ended"])
        self.assertEqual(self.client.get("/api/auth/me", headers=self._auth(token)).status_code, 401)

    # -- 7-9: providers ----------------------------------------------------

    def test_07_digilocker_unavailable(self):
        token = self._shakti_user()
        res = self.client.post("/api/identity/digilocker/start", headers=self._auth(token))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "UNAVAILABLE")
        self.assertFalse(data["configured"])
        self.assertIsNone(data["authorization_url"])
        self.assertIn("authorized government identity-verification flow", data["explanation"])
        status = self.client.get("/api/identity/digilocker/status", headers=self._auth(token)).json()
        self.assertNotEqual(status["status"], "LINKED")
        # Demo mode never fakes a DigiLocker link either
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        self.assertEqual(self.client.post("/api/identity/digilocker/start", headers=self._auth(token)).json()["status"], "UNAVAILABLE")

    def test_08_identity_verification_unavailable_by_default(self):
        token = self._shakti_user()
        start = self.client.post("/api/identity/verification/start", json={"consent_confirmed": True}, headers=self._auth(token))
        self.assertEqual(start.status_code, 200)
        data = start.json()
        self.assertFalse(data["available"])
        self.assertEqual(data["provider_mode"], "UNAVAILABLE")
        self.assertEqual(data["message"], "Identity verification is currently unavailable.")
        self.assertIsNone(data["attempt_id"])
        status = self.client.get("/api/identity/status", headers=self._auth(token)).json()
        self.assertEqual(status["identity_status"], "UNAVAILABLE")
        self.assertEqual(status["shakti_eligibility_status"], "VERIFICATION_UNAVAILABLE")
        # Consent is mandatory
        self.assertEqual(
            self.client.post("/api/identity/verification/start", json={"consent_confirmed": False}, headers=self._auth(token)).status_code,
            400,
        )

    def test_09_demo_verification_clearly_marked(self):
        token = self._shakti_user()
        mode = self.client.post("/api/identity/verification/demo-mode", json={"enabled": True}).json()
        self.assertEqual(mode["provider_mode"], "DEMO_VERIFICATION")
        self.assertEqual(mode["label"], "DEMO IDENTITY VERIFICATION")
        res = self._demo_verify(token)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["outcome"], "MATCH")
        self.assertEqual(data["provider_mode"], "DEMO_VERIFICATION")
        self.assertEqual(data["identity_status"], "DEMO_VERIFIED")
        self.assertEqual(data["shakti_eligibility_status"], "DEMO_ELIGIBLE")
        self.assertEqual(data["label"], "DEMO IDENTITY VERIFICATION")
        self.assertIn("not a real Aadhaar or DigiLocker verification", data["message"])
        self.assertNotEqual(data["identity_status"], "AUTHORIZED_VERIFIED")
        self.assertIsNone(data["masked_identity_suffix"])
        self.assertTrue(data["temporary_capture_cleared"])
        self.assertEqual(identity_onboarding_service.provider.face.pending_capture_count(), 0)

    def test_09b_demo_no_match_and_missing_liveness(self):
        token = self._shakti_user()
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        self.assertEqual(self._demo_verify(token, liveness=False).json()["outcome"], "VERIFICATION_ERROR")
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True, "demo_outcome": "NO_MATCH"})
        data = self._demo_verify(token).json()
        self.assertEqual(data["outcome"], "NO_MATCH")
        self.assertEqual(data["identity_status"], "FAILED")
        self.assertEqual(data["shakti_eligibility_status"], "NOT_VERIFIED")
        titles = [e.title for e in notification_service.get_events()]
        self.assertIn("Identity verification failed", titles)

    # -- 10-12: privacy ----------------------------------------------------

    def test_10_no_raw_aadhaar_accepted_or_stored(self):
        token = self._shakti_user()
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        start = self.client.post("/api/identity/verification/start", json={"consent_confirmed": True}, headers=self._auth(token)).json()
        res = self.client.post("/api/identity/verification/complete", json={
            "attempt_id": start["attempt_id"], "liveness_action_completed": True, "aadhaar_number": "234567894821",
        }, headers=self._auth(token))
        self.assertEqual(res.status_code, 422)
        reg = self.client.post("/api/auth/register", json={
            "full_name": "Test User", "mobile": "9000000001", "email": "t@gmail.com", "aadhaar_number": "234567894821",
        })
        self.assertEqual(reg.status_code, 422)
        dump = json.dumps(auth_service.stored_records(), default=str)
        self.assertNotIn("234567894821", dump)

    def test_11_no_biometric_or_selfie_storage(self):
        token = self._shakti_user()
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        start = self.client.post("/api/identity/verification/start", json={"consent_confirmed": True}, headers=self._auth(token)).json()
        for field in ("selfie_image", "face_embedding", "frame_base64"):
            res = self.client.post("/api/identity/verification/complete", json={
                "attempt_id": start["attempt_id"], "liveness_action_completed": True, field: "AAAA",
            }, headers=self._auth(token))
            self.assertEqual(res.status_code, 422, field)
        self._demo_verify(token)
        for record in auth_service.stored_records().values():
            for key in record:
                self.assertFalse(any(s in key.lower() for s in SENSITIVE_KEYS), key)
            # Raw mobile never stored
            self.assertNotIn("9876543210", json.dumps(record, default=str))

    def test_12_masked_identity_only(self):
        token = self._register().json()["session_token"]
        me = self.client.get("/api/auth/me", headers=self._auth(token)).json()
        self.assertTrue(me["masked_mobile"].startswith("+91 XXXXX"))
        self.assertNotIn("9876543210", json.dumps(me))
        self.assertIsNone(me["masked_identity_suffix"])
        # Sessions are stored hashed, never as plaintext tokens
        self.assertNotIn(token, json.dumps(auth_service._sessions, default=str))

    def test_12b_no_sensitive_values_in_logs(self):
        with self.assertLogs(level=logging.INFO) as captured:
            token = self._register(mobile="9876501234", email="secret.person@gmail.com", name="Secret Person").json()["session_token"]
            self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
            self._demo_verify(token)
            logging.getLogger("nammablr.test").info("marker")
        joined = "\n".join(captured.output)
        for value in ("9876501234", "secret.person@gmail.com", "Secret Person", token):
            self.assertNotIn(value, joined)

    # -- 13-15: Shakti ------------------------------------------------------

    def test_13_shakti_eligibility_flow(self):
        token = self._shakti_user()
        me = self.client.get("/api/auth/me", headers=self._auth(token)).json()
        self.assertEqual(me["account_type"], "SHAKTI_ONBOARDING")
        self.assertNotIn("gender", json.dumps(me).lower())
        check = self.client.post("/api/shakti/eligibility/check", headers=self._auth(token)).json()
        self.assertFalse(check["concession_allowed"])
        self.assertEqual(check["eligibility_status"], "NOT_VERIFIED")
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        self._demo_verify(token)
        check = self.client.post("/api/shakti/eligibility/check", headers=self._auth(token)).json()
        self.assertTrue(check["concession_allowed"])
        self.assertEqual(check["eligibility_status"], "DEMO_ELIGIBLE")
        self.assertEqual(check["label"], "DEMO IDENTITY VERIFICATION")
        titles = [e.title for e in notification_service.get_events()]
        self.assertIn("Identity verification completed", titles)
        self.assertIn("Shakti eligibility updated", titles)
        self.assertFalse(any("otp" in t.lower() for t in titles))

    def test_14_ticket_blocked_when_verification_unavailable(self):
        token = self._shakti_user()
        self.client.post("/api/identity/verification/start", json={"consent_confirmed": True}, headers=self._auth(token))
        res = self._concession_ticket(token)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "Identity verification is currently unavailable.")
        # Not verified (provider available but no verification yet) is also blocked
        general = self._register(mobile="9123456789").json()["session_token"]
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        res = self._concession_ticket(general)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "Identity verification required")

    def test_15_demo_shakti_ticket_keeps_disclaimer(self):
        token = self._shakti_user()
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        self._demo_verify(token)
        res = self._concession_ticket(token)
        self.assertEqual(res.status_code, 200)
        ticket = res.json()
        self.assertEqual(ticket["disclaimer"], DEMO_PASS_DISCLAIMER)
        self.assertEqual(ticket["fare_rupees"], 0)
        self.assertEqual(ticket["fare_type"], "women_demo_concession")
        self.assertEqual(ticket["identity_status"], "demo_identity_verification")
        self.assertIsNone(ticket["passenger_gender"])

    # -- 16-20: regression ---------------------------------------------------

    def test_16_hmac_ticket_validation_still_works(self):
        token = self._shakti_user()
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        self._demo_verify(token)
        ticket = self._concession_ticket(token).json()
        payload = json.loads(ticket["qr_payload"])
        self.assertTrue(verify_ticket_signature(payload["ticketId"], payload["route"], payload["fare"], payload["expiresAt"], payload["signature"]))
        # Legacy anonymous standard ticket unchanged
        std = self.client.post("/api/tickets", json={"route_number": "500D", "source": "A", "destination": "B"})
        self.assertEqual(std.status_code, 200)
        self.assertEqual(std.json()["disclaimer"], DEMO_PASS_DISCLAIMER)

    def test_17_conductor_validation_still_works(self):
        token = self._shakti_user()
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        self._demo_verify(token)
        ticket = self._concession_ticket(token).json()
        first = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": ticket["qr_payload"], "conductor_route_number": "500D"})
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["valid"])
        used = self.client.post(f"/api/tickets/{ticket['ticket_id']}/use")
        self.assertEqual(used.status_code, 200)
        again = self.client.post("/api/tickets/verify", json={"qr_payload_or_code": ticket["qr_payload"], "conductor_route_number": "500D"})
        self.assertFalse(again.json()["valid"])

    def test_18_active_journey_still_works(self):
        self._register()
        res = self.client.post("/api/journey/active", json={
            "route_number": "500D", "bus_id": "bus-500d-1",
            "origin": "Central Silk Board Junction", "destination": "Hebbal",
        })
        self.assertIn(res.status_code, (200, 201))
        self.assertEqual(self.client.get("/api/journey/active").status_code, 200)

    def test_19_demo_reset_clears_auth_state(self):
        token = self._shakti_user()
        self.client.post("/api/identity/verification/demo-mode", json={"enabled": True})
        self.client.post("/api/identity/verification/start", json={"consent_confirmed": True}, headers=self._auth(token))
        self.assertEqual(self.client.post("/api/demo/reset").status_code, 200)
        self.assertEqual(auth_service.stored_records(), {})
        self.assertEqual(auth_service.session_count(), 0)
        self.assertEqual(identity_onboarding_service.provider.mode, "UNAVAILABLE")
        self.assertEqual(self.client.get("/api/auth/me", headers=self._auth(token)).status_code, 401)

    def test_20_canonical_operational_statement_unchanged(self):
        self.assertEqual(
            OPERATIONAL_STATEMENT_NOT_CONNECTED,
            "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED",
        )
        res = self.client.get("/api/realtime/test")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.json().get("message"),
            "REALTIME BMTC FEED: READY FOR AUTHORIZED CONFIGURATION — NOT CURRENTLY CONNECTED",
        )

    def test_21_demo_mode_refused_in_production(self):
        original = settings.environment
        settings.environment = "production"
        try:
            self.assertEqual(self.client.post("/api/identity/verification/demo-mode", json={"enabled": True}).status_code, 403)
        finally:
            settings.environment = original


if __name__ == "__main__":
    unittest.main()
