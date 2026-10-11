import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.core import middleware
from app.services.auth_service import auth_service, _digest


class TestPhase42AuthProfile(unittest.TestCase):
    """Master spec Phase 42: profile update, session expiry, preferences untouched by auth."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.post("/api/demo/reset")
        middleware._ip_request_timestamps.clear()
        self.token = self.client.post("/api/auth/register", json={
            "full_name": "Meena Shetty", "mobile": "9812345678", "email": "meena@gmail.com",
        }).json()["session_token"]
        self.h = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client.post("/api/demo/reset")

    def test_profile_update(self):
        res = self.client.patch("/api/auth/profile", json={"full_name": "Meena  S Shetty", "email": "Meena.S@Gmail.com"}, headers=self.h)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["display_name"], "Meena S Shetty")
        self.assertEqual(res.json()["email"], "meena.s@gmail.com")
        self.assertEqual(res.json()["email_verification_status"], "NOT_CONNECTED")
        self.assertEqual(self.client.patch("/api/auth/profile", json={"email": "bad"}, headers=self.h).status_code, 422)
        self.assertEqual(self.client.patch("/api/auth/profile", json={"password": "x"}, headers=self.h).status_code, 422)
        self.assertEqual(self.client.patch("/api/auth/profile", json={"full_name": "Anon"}).status_code, 401)

    def test_session_expiry_reported_and_enforced(self):
        me = self.client.get("/api/auth/me", headers=self.h).json()
        self.assertIsNotNone(me["session_expires_at"])
        auth_service._sessions[_digest(self.token)]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertEqual(self.client.get("/api/auth/me", headers=self.h).status_code, 401)

    def test_login_logout_keep_preferences(self):
        prefs = self.client.get("/api/preferences").json()
        self.client.post("/api/auth/logout", headers=self.h)
        self.assertEqual(self.client.get("/api/preferences").json(), prefs)
        self.assertEqual(self.client.get("/api/saved-journeys").status_code, 200)


if __name__ == "__main__":
    unittest.main()
