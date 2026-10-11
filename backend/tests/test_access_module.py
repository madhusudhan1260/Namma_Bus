"""
Access module tests (accounts, RBAC, identity/face verification, student passes, college portal,
eligibility, tickets, conductor validation, documents, admin). Runs against a real PostgreSQL test
database (ACCESS_TEST_DATABASE_URL, e.g. from backend/.env.access). Fares use a static provider so no
network access is needed.
"""

import base64
import json
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.access.api import build_router, load_local_env

load_local_env()
TEST_DB = os.getenv("ACCESS_TEST_DATABASE_URL")


def _png(extra: bytes = b"") -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64 + extra


def _pdf(extra: bytes = b"") -> bytes:
    return b"%PDF-1.4\n%test\n" + extra + b"\n%%EOF"


@unittest.skipUnless(TEST_DB, "ACCESS_TEST_DATABASE_URL not configured")
class AccessModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["ACCESS_DATABASE_URL"] = TEST_DB
        # Tests use the labelled development providers regardless of the developer's local .env.access
        os.environ["IDENTITY_PROVIDER"] = "mock"
        os.environ["BIOMETRIC_PROVIDER"] = "mock"
        cls._tmp = TemporaryDirectory()
        os.environ["ACCESS_UPLOAD_DIR"] = cls._tmp.name
        router = build_router()
        from app.access import config, db, fares, models  # noqa: F401

        cls.config, cls.db = config, db
        db.configure(TEST_DB)
        models_base = db.Base
        models_base.metadata.drop_all(db.engine())
        models_base.metadata.create_all(db.engine())

        class StaticFareProvider(fares.FareProvider):
            STOPS = {0: [("S1", "Hebbal Bridge"), ("S2", "Nagawara Junction"), ("S3", "Tin Factory")],
                     1: [("S3", "Tin Factory"), ("S2", "Nagawara Junction"), ("S1", "Hebbal Bridge")]}
            down = False

            async def quote(self, route, direction, from_stop_id, to_stop_id):
                if self.down:
                    raise HTTPException(status_code=503, detail="BMTC route network service is unavailable")
                if route != "500-D":
                    raise HTTPException(status_code=400, detail="Route does not exist")
                for d in ([direction] if direction in (0, 1) else [0, 1]):
                    ids = [s[0] for s in self.STOPS[d]]
                    if from_stop_id in ids and to_stop_id in ids and ids.index(from_stop_id) < ids.index(to_stop_id):
                        names = dict(self.STOPS[d])
                        return fares.FareQuote("500-D", d, from_stop_id, names[from_stop_id], to_stop_id, names[to_stop_id], 25, "GTFS_FARE_RULES")
                raise HTTPException(status_code=400, detail="Stops not on route")

        cls.fare_provider = StaticFareProvider()
        fares.set_fare_provider(cls.fare_provider)
        app = FastAPI()
        app.include_router(router, prefix="/api/access")
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        from app.access import fares
        from app.access.providers import biometric, identity

        fares.set_fare_provider(None)
        identity.set_identity_provider(None)
        biometric.set_biometric_provider(None)
        cls._tmp.cleanup()

    def setUp(self):
        from sqlalchemy import text

        from app.access.providers import biometric, identity
        from app.access.providers.scanner import set_scanner
        from app.access.security import rate_limiter

        rate_limiter.reset()
        identity.set_identity_provider(None)
        biometric.set_biometric_provider(None)
        set_scanner(None)
        self.fare_provider.down = False
        tables = ", ".join(t.name for t in reversed(self.db.Base.metadata.sorted_tables))
        with self.db.engine().begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} CASCADE"))
        self._n = 0
        self.trip_id = self._fixture_trip()

    def _fixture_trip(self, capacity=50):
        """Every ticket belongs to a running trip: a bus (KA57F9999) with an ACTIVE trip on route 500-D, created
        directly in the database so the existing ticket tests have a trip to buy into."""
        from datetime import datetime, timezone

        from app.access.models import Bus, Role, Trip, User

        gen = self.db.get_db()
        s = next(gen)
        crew = User(name="Fixture Crew", email=f"crew{id(self)}@bmtc.example", role=Role.CONDUCTOR)
        bus = Bus(fleet_label="FIXTURE BUS", registration_number="KA57F9999", route="500-D", max_capacity=capacity)
        s.add_all([crew, bus])
        s.flush()
        now = datetime.now(timezone.utc)
        trip = Trip(bus_id=bus.id, conductor_id=crew.id, route="500-D", direction=0, status="ACTIVE", started_at=now, updated_at=now,
                    trip_code="TRIP-FIXTURE-500D-001", max_capacity=capacity, passenger_count=0)
        s.add(trip)
        s.commit()
        trip_id = trip.id
        gen.close()
        return trip_id

    # ------------------------------------------------------------------ helpers
    def _uniq(self):
        self._n += 1
        return self._n

    def register(self, gender="MALE", is_student=False, name="Madhusudhan", **extra):
        n = self._uniq()
        body = {"name": name, "phone": f"98450{n:05d}", "email": f"user{n}@example.com", "password": "Travel2026",
                "gender": gender, "is_student": is_student, **extra}
        r = self.client.post("/api/access/auth/register", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        data = r.json()
        data["headers"] = {"Authorization": f"Bearer {data['access_token']}"}
        data["email"] = body["email"]
        return data

    def login(self, body):
        """Password step, then the emailed code (development delivery returns it), as the app does."""
        r = self.client.post("/api/access/auth/login", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["status"], "EMAIL_CODE_SENT")
        self.assertNotIn("access_token", data)  # no session before the code is verified
        r = self.client.post("/api/access/auth/login/verify", json={"challenge_id": data["challenge_id"], "code": data["development_code"]})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def make_super_admin(self):
        from app.access.models import Role, User
        from app.access.security import create_access_token, hash_password

        with self.db.engine().begin():
            pass
        gen = self.db.get_db()
        s = next(gen)
        u = User(name="Ops Admin", email=f"admin{self._uniq()}@example.org", password_hash=hash_password("Admin2026x"), role=Role.SUPER_ADMIN)
        s.add(u)
        s.commit()
        uid = u.id
        gen.close()
        return {"id": uid, "headers": {"Authorization": f"Bearer {create_access_token(uid, 'SUPER_ADMIN')}"}}

    def make_college(self, admin, code="RVCE", domain="rvce.edu.in"):
        r = self.client.post("/api/access/admin/colleges", json={"code": code, "name": f"{code} College", "email_domain": domain}, headers=admin["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        email = f"verifier{self._uniq()}@{domain}"
        r = self.client.post("/api/access/admin/college-admins", json={"name": "College Verifier", "email": email, "password": "College2026",
                                                                       "college_code": code}, headers=admin["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        s = self.login({"identifier": email, "password": "College2026", "portal": "college", "college_code": code})
        return {"code": code, "domain": domain, "headers": {"Authorization": f"Bearer {s['access_token']}"}}

    def make_conductor(self, admin, route="500-D"):
        emp = f"EMP{self._uniq():04d}"
        r = self.client.post("/api/access/admin/conductors", json={"name": "Ravi Conductor", "email": f"{emp.lower()}@bmtc.example",
                                                                   "password": "Conduct2026", "employee_id": emp, "assigned_bus": "KA57F4578",
                                                                   "assigned_route": route}, headers=admin["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        # Conductors sign in with Conductor ID + password on the conductor portal (no email code)
        r = self.client.post("/api/access/conductor/login", json={"conductor_id": emp, "password": "Conduct2026"})
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()
        return {"user_id": s["user_id"], "employee_id": emp, "headers": {"Authorization": f"Bearer {s['access_token']}"}}

    def verify_identity(self, user, outcome="mock-verified-female"):
        r = self.client.post("/api/access/identity/start", json={"consent": True}, headers=user["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        start = r.json()
        self.assertTrue(start["is_development"])
        self.assertIn("DEVELOPMENT VERIFICATION", start["label"])
        state = start["authorization_url"].split("state=")[1]
        page = self.client.get(f"/api/access/identity/mock-consent?state={state}")
        self.assertIn("DEVELOPMENT VERIFICATION — NOT REAL IDENTITY VERIFICATION", page.text)
        self.assertNotIn("password", page.text.lower().replace("never asks for any password", ""))
        r = self.client.get(f"/api/access/identity/callback?state={state}&code={outcome}", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        return self.client.get("/api/access/identity/status", headers=user["headers"]).json()

    def face(self, user, outcome="MATCH"):
        r = self.client.post("/api/access/biometric/verify", data={"consent": "true", "mock_outcome": outcome},
                             files={"image": ("face.png", _png(), "image/png")}, headers=user["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def journey(self, **kw):
        return {"route": "500-D", "direction": 0, "from_stop_id": "S1", "to_stop_id": "S3", "passenger_count": 1, **kw}

    def buy_paid(self, user):
        r = self.client.post("/api/access/tickets/create", json=self.journey(), headers=user["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        t = r.json()
        r = self.client.post(f"/api/access/tickets/{t['ticket_id']}/pay-demo", json={"outcome": "SUCCESS"}, headers=user["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def submit_student(self, student, college, expiry=None, **files):
        expiry = expiry or (date.today() + timedelta(days=180)).isoformat()
        data = {"college_code": college["code"], "student_name": "Asha Kumar", "college_email": f"asha{self._uniq()}@{college['domain']}",
                "student_id_number": "1RV22CS001", "course": "B.E.", "branch": "CSE", "year": "3", "semester": "5",
                "phone": "9845012345", "pass_number": "BMTC-STU-7788", "pass_issue_date": (date.today() - timedelta(days=30)).isoformat(),
                "pass_expiry_date": expiry}
        f = {"bus_pass": ("pass.pdf", files.get("bus_pass", _pdf()), "application/pdf"),
             "college_id_card": ("id.png", files.get("college_id_card", _png()), "image/png")}
        return self.client.post("/api/access/students/pass/upload", data=data, files=f, headers=student["headers"])

    # ------------------------------------------------------------------ 1-3 passengers
    def test_01_male_passenger_registration_and_paid_fare(self):
        u = self.register("MALE")
        self.assertEqual(u["role"], "PASSENGER")
        self.assertEqual(u["next_step"], "DASHBOARD")
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=u["headers"]).json()
        self.assertEqual((q["normal_fare"], q["fare"], q["ticket_type"], q["eligible"]), (25, 25, "PAID", False))
        self.assertEqual((q["from_stop"]["name"], q["to_stop"]["name"]), ("Hebbal Bridge", "Tin Factory"))
        r = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True), headers=u["headers"])
        self.assertEqual(r.status_code, 409)  # no free ticket for the male flow without verified eligibility

    def test_02_female_passenger_registration_asks_aadhaar(self):
        u = self.register("FEMALE", name="Lakshmi")
        self.assertEqual(u["next_step"], "AADHAAR_QUESTION")
        me = self.client.get("/api/access/me", headers=u["headers"]).json()
        self.assertEqual(me["passenger"]["identity_status"], "NOT_STARTED")
        self.assertTrue(me["passenger"]["identity_service_is_development"])

    def test_03_female_without_aadhaar_buys_regular_ticket(self):
        u = self.register("FEMALE")
        r = self.client.post("/api/access/identity/aadhaar-answer", json={"has_aadhaar": False}, headers=u["headers"]).json()
        self.assertEqual(r["identity_status"], "DECLINED")
        self.assertIn("You can still travel by purchasing a regular ticket", r["message"])
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=u["headers"]).json()
        self.assertEqual(q["fare"], 25)
        t = self.buy_paid(u)
        self.assertEqual((t["status"], t["fare"], t["payment_status"]), ("ISSUED", 25, "PAID_DEMO"))
        self.assertIsNotNone(t["qr_payload"])

    # ------------------------------------------------------------------ 4-7 identity & face
    def test_04_female_identity_verification_stores_minimum(self):
        from sqlalchemy import select

        from app.access.models import IdentityVerification

        u = self.register("FEMALE")
        st = self.verify_identity(u)
        self.assertEqual(st["identity_status"], "VERIFIED")
        self.assertTrue(st["is_development"])
        self.assertTrue(st["verification_reference"].startswith("MOCKDEV-"))
        gen = self.db.get_db()
        s = next(gen)
        iv = s.scalars(select(IdentityVerification).where(IdentityVerification.user_id == u["user_id"])).one()
        self.assertEqual(iv.attributes, {"gender": "F"})  # data minimisation: no Aadhaar number / document
        self.assertIsNone(iv.state_hash)  # single-use state consumed
        gen.close()
        # Consent is mandatory
        r = self.client.post("/api/access/identity/start", json={"consent": False}, headers=u["headers"])
        self.assertEqual(r.status_code, 400)

    def test_05_identity_verification_failure(self):
        u = self.register("FEMALE")
        st = self.verify_identity(u, outcome="mock-failed")
        self.assertEqual(st["identity_status"], "FAILED")
        r = self.client.post("/api/access/biometric/verify", data={"consent": "true", "mock_outcome": "MATCH"},
                             files={"image": ("f.png", _png(), "image/png")}, headers=u["headers"])
        self.assertEqual(r.status_code, 409)
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=u["headers"]).json()
        self.assertEqual(q["fare"], 25)

    def test_06_face_verification_success_gives_single_use_free_ticket(self):
        u = self.register("FEMALE", name="Lakshmi")
        self.verify_identity(u)
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=u["headers"]).json()
        self.assertTrue(q["needs_face_verification"])
        self.assertEqual(q["fare"], 25)
        f = self.face(u, "MATCH")
        self.assertEqual(f["result"], "MATCH")
        self.assertEqual(f["message"], "Identity verified successfully.")
        self.assertNotIn("image", json.dumps(f).lower().replace("face_verification_id", ""))
        j = self.journey(use_eligibility=True, face_verification_id=f["face_verification_id"])
        q = self.client.post("/api/access/tickets/quote", json=j, headers=u["headers"]).json()
        self.assertEqual((q["normal_fare"], q["fare"], q["ticket_type"], q["eligibility_type"]), (25, 0, "ELIGIBLE_FREE", "FEMALE_IDENTITY_VERIFIED_FREE"))
        r = self.client.post("/api/access/tickets/create", json=j, headers=u["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        t = r.json()
        self.assertEqual((t["fare"], t["status"], t["payment_status"]), (0, "ISSUED", "NOT_REQUIRED"))
        self.assertIn("MOCKDEV-", t["verification_reference"])
        # The same face verification cannot be reused for a second free ticket
        r = self.client.post("/api/access/tickets/create", json=j, headers=u["headers"])
        self.assertEqual(r.status_code, 409)

    def test_07_face_verification_failure_falls_back_to_paid(self):
        u = self.register("FEMALE")
        self.verify_identity(u)
        f = self.face(u, "NO_MATCH")
        self.assertEqual(f["result"], "NO_MATCH")
        self.assertIn("You can purchase a regular ticket instead", f["message"])
        j = self.journey(use_eligibility=True, face_verification_id=f["face_verification_id"])
        self.assertEqual(self.client.post("/api/access/tickets/create", json=j, headers=u["headers"]).status_code, 409)
        self.assertEqual(self.buy_paid(u)["fare"], 25)
        # Consent required and a real image required
        r = self.client.post("/api/access/biometric/verify", data={"consent": "false"}, files={"image": ("f.png", _png(), "image/png")}, headers=u["headers"])
        self.assertEqual(r.status_code, 400)

    def test_07b_male_identity_attestation_does_not_grant_female_benefit(self):
        u = self.register("FEMALE")  # self-declared gender alone never grants eligibility
        self.verify_identity(u, outcome="mock-verified-male")
        f = self.face(u, "MATCH")
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True, face_verification_id=f["face_verification_id"]),
                             headers=u["headers"]).json()
        self.assertEqual(q["fare"], 25)

    # ------------------------------------------------------------------ 8-13 students
    def test_08_student_registration(self):
        s = self.register("MALE", is_student=True)
        self.assertEqual((s["role"], s["next_step"]), ("STUDENT", "STUDENT_VERIFICATION"))
        st = self.client.get("/api/access/students/pass/status", headers=s["headers"]).json()
        self.assertEqual(st["status"], "NOT_SUBMITTED")

    def test_09_student_pass_upload_is_pending_and_encrypted(self):
        admin = self.make_super_admin()
        college = self.make_college(admin)
        s = self.register("MALE", is_student=True)
        original = _pdf(b"secret pass content")
        r = self.submit_student(s, college, bus_pass=original)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["status"], "PENDING")
        self.assertIn("does not by itself make you eligible", r.json()["message"])
        # Pending → normal fare
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
        self.assertEqual(q["fare"], 25)
        stored = [p.read_bytes() for p in Path(os.environ["ACCESS_UPLOAD_DIR"]).iterdir()]
        self.assertTrue(stored and all(b"secret pass content" not in b for b in stored))
        # Duplicate pending submission blocked
        self.assertEqual(self.submit_student(s, college).status_code, 409)

    def _approved_student(self, expiry=None):
        admin = self.make_super_admin()
        college = self.make_college(admin)
        s = self.register("MALE", is_student=True)
        ver = self.submit_student(s, college, expiry=expiry).json()
        r = self.client.post(f"/api/access/college/students/{ver['verification_id']}/approve", json={}, headers=college["headers"])
        return admin, college, s, ver, r

    def test_10_college_approval_enables_free_student_ticket(self):
        admin, college, s, ver, r = self._approved_student()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "APPROVED")
        st = self.client.get("/api/access/students/pass/status", headers=s["headers"]).json()
        self.assertEqual(st["status"], "APPROVED")
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
        self.assertEqual((q["fare"], q["eligibility_type"]), (0, "STUDENT_FREE"))
        logs = self.client.get("/api/access/admin/audit-logs?action=STUDENT_APPROVED", headers=admin["headers"]).json()["logs"]
        self.assertEqual(len(logs), 1)

    def test_11_college_rejection_keeps_normal_fare(self):
        admin = self.make_super_admin()
        college = self.make_college(admin)
        s = self.register("FEMALE", is_student=True)
        ver = self.submit_student(s, college).json()
        r = self.client.post(f"/api/access/college/students/{ver['verification_id']}/reject", json={"reason": "x"}, headers=college["headers"])
        self.assertEqual(r.status_code, 422)  # a reason is required
        reason = "Student pass rejected because the document could not be verified."
        r = self.client.post(f"/api/access/college/students/{ver['verification_id']}/reject", json={"reason": reason}, headers=college["headers"])
        self.assertEqual(r.json()["status"], "REJECTED")
        st = self.client.get("/api/access/students/pass/status", headers=s["headers"]).json()
        self.assertEqual((st["status"], st["rejection_reason"]), ("REJECTED", reason))
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
        self.assertEqual(q["fare"], 25)

    def test_12_expired_student_pass_pays_normal_fare(self):
        admin, college, s, ver, r = self._approved_student(expiry=(date.today() + timedelta(days=10)).isoformat())
        from sqlalchemy import update

        from app.access.models import StudentPass

        with self.db.engine().begin() as conn:
            conn.execute(update(StudentPass).values(expiry_date=date.today() - timedelta(days=2)))
        st = self.client.get("/api/access/students/pass/status", headers=s["headers"]).json()
        self.assertEqual(st["status"], "EXPIRED")
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
        self.assertEqual(q["fare"], 25)

    def test_13_valid_student_pass_quote_and_multi_passenger_limit(self):
        admin, college, s, ver, r = self._approved_student()
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
        self.assertEqual(q["fare"], 0)
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True, passenger_count=2), headers=s["headers"]).json()
        self.assertEqual(q["fare"], 50)  # eligibility covers the student only
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=False), headers=s["headers"]).json()
        self.assertEqual(q["fare"], 25)

    # ------------------------------------------------------------------ 14-18 tickets & conductor
    def test_14_free_ticket_contents_and_safe_qr(self):
        admin, college, s, ver, r = self._approved_student()
        t = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
        for k in ("ticket_id", "passenger_id", "route", "from_stop", "to_stop", "created_at", "passenger_count", "fare",
                  "eligibility_type", "verification_reference", "qr_payload"):
            self.assertIsNotNone(t[k], k)
        self.assertEqual((t["fare"], t["ticket_type"], t["eligibility_type"]), (0, "ELIGIBLE_FREE", "STUDENT_FREE"))
        qr = json.loads(t["qr_payload"])
        # identifiers, the trip and bus it was issued into, timestamps and the signature — nothing about the person
        self.assertEqual(set(qr), {"v", "tid", "ref", "rid", "ts", "exp", "trp", "bus", "sig"})
        self.assertNotIn("Madhusudhan", t["qr_payload"])

    def test_15_paid_ticket_requires_payment_before_qr(self):
        u = self.register("MALE")
        t = self.client.post("/api/access/tickets/create", json=self.journey(), headers=u["headers"]).json()
        self.assertEqual((t["status"], t["payment_status"], t["qr_payload"]), ("PENDING_PAYMENT", "PENDING", None))
        paid = self.client.post(f"/api/access/tickets/{t['ticket_id']}/pay-demo", json={"outcome": "SUCCESS"}, headers=u["headers"]).json()
        self.assertEqual((paid["status"], paid["payment_label"]), ("ISSUED", "DEMO PAYMENT — NO REAL MONEY CHARGED"))
        failed = self.client.post("/api/access/tickets/create", json=self.journey(), headers=u["headers"]).json()
        f = self.client.post(f"/api/access/tickets/{failed['ticket_id']}/pay-demo", json={"outcome": "FAILURE"}, headers=u["headers"]).json()
        self.assertEqual(f["status"], "CANCELLED")

    def test_16_18_conductor_validation_valid_invalid_used_expired(self):
        admin = self.make_super_admin()
        conductor = self.make_conductor(admin)
        u = self.register("MALE")
        t = self.buy_paid(u)
        v = lambda qr: self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": qr}, headers=conductor["headers"]).json()
        first = v(t["qr_payload"])
        self.assertEqual((first["result"], first["display"]), ("VALID", "VALID TICKET ✓"))
        self.assertEqual(first["ticket"]["route"], "500-D")
        again = v(t["qr_payload"])
        self.assertEqual((again["result"], again["display"]), ("ALREADY_USED", "ALREADY USED"))
        bogus = v('{"not":"a ticket"}')
        self.assertEqual((bogus["result"], bogus["display"]), ("INVALID", "INVALID TICKET ✕"))
        t2 = self.buy_paid(u)
        from sqlalchemy import update

        from app.access.models import Ticket
        from datetime import datetime, timezone

        with self.db.engine().begin() as conn:
            conn.execute(update(Ticket).where(Ticket.id == t2["ticket_id"]).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        self.assertEqual(v(t2["qr_payload"])["result"], "EXPIRED")
        me = self.client.get("/api/access/conductor/me", headers=conductor["headers"]).json()
        self.assertEqual((me["assigned_route"], me["passengers_admitted_24h"]), ("500-D", 1))

    def test_17_invalid_wrong_route_and_revoked_eligibility(self):
        admin, college, s, ver, r = self._approved_student()
        other_route = self.make_conductor(admin, route="335-E")
        conductor = self.make_conductor(admin)
        t = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
        wrong = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": t["qr_payload"]}, headers=other_route["headers"]).json()
        self.assertEqual(wrong["result"], "WRONG_ROUTE")  # spec result code (was the generic INVALID)
        self.assertIn("route", wrong["detail"])
        from sqlalchemy import update

        from app.access.models import StudentPass

        with self.db.engine().begin() as conn:
            conn.execute(update(StudentPass).values(expiry_date=date.today() - timedelta(days=1)))
        res = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": t["qr_payload"]}, headers=conductor["headers"]).json()
        self.assertEqual(res["result"], "REVOKED")  # eligibility withdrawn after issue (spec result code)
        self.assertIn("Student pass", res["detail"])

    # ------------------------------------------------------------------ 19-22 authorization & tampering
    def test_19_college_cannot_access_other_college_students(self):
        admin = self.make_super_admin()
        college_a = self.make_college(admin, "COLA", "cola.edu.in")
        college_b = self.make_college(admin, "COLB", "colb.edu.in")
        s = self.register("MALE", is_student=True)
        ver = self.submit_student(s, college_a).json()
        vid = ver["verification_id"]
        self.assertEqual(self.client.get(f"/api/access/college/students/{vid}", headers=college_b["headers"]).status_code, 404)
        self.assertEqual(self.client.post(f"/api/access/college/students/{vid}/approve", json={}, headers=college_b["headers"]).status_code, 404)
        self.assertEqual(self.client.get("/api/access/college/students", headers=college_b["headers"]).json()["count"], 0)
        detail = self.client.get(f"/api/access/college/students/{vid}", headers=college_a["headers"]).json()
        doc_id = detail["bus_pass_document"]["id"]
        self.assertEqual(self.client.get(f"/api/access/documents/{doc_id}/url", headers=college_b["headers"]).status_code, 404)
        ok = self.client.get(f"/api/access/{detail['bus_pass_document']['view_url']}")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.content.startswith(b"%PDF-"))
        self.assertEqual(ok.headers["cache-control"], "no-store")
        # College login requires the matching college ID
        r = self.client.post("/api/access/auth/login", json={"identifier": "nobody@colb.edu.in", "password": "x", "portal": "college", "college_code": "COLA"})
        self.assertEqual(r.status_code, 401)

    def test_20_unauthorized_admin_access(self):
        u = self.register("MALE")
        self.assertEqual(self.client.get("/api/access/admin/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/api/access/admin/dashboard", headers=u["headers"]).status_code, 403)
        self.assertEqual(self.client.get("/api/access/admin/audit-logs", headers=u["headers"]).status_code, 403)
        admin = self.make_super_admin()
        dash = self.client.get("/api/access/admin/dashboard", headers=admin["headers"]).json()
        self.assertEqual(dash["users"]["passengers"], 1)

    def test_21_role_based_authorization(self):
        from app.access.security import create_access_token

        u = self.register("MALE", role="SUPER_ADMIN")  # role in the request body is ignored
        self.assertEqual(u["role"], "PASSENGER")
        forged = {"Authorization": f"Bearer {create_access_token(u['user_id'], 'SUPER_ADMIN')}"}
        self.assertEqual(self.client.get("/api/access/admin/users", headers=forged).status_code, 403)  # DB role wins
        self.assertEqual(self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": "x" * 20}, headers=u["headers"]).status_code, 403)
        admin = self.make_super_admin()
        conductor = self.make_conductor(admin)
        self.assertEqual(self.client.post("/api/access/tickets/create", json=self.journey(), headers=conductor["headers"]).status_code, 403)
        self.assertEqual(self.client.get("/api/access/college/dashboard", headers=conductor["headers"]).status_code, 403)
        r = self.client.post("/api/access/auth/login", json={"identifier": u["email"], "password": "Travel2026", "portal": "admin"})
        self.assertEqual(r.status_code, 403)
        bad = {"Authorization": "Bearer not-a-token"}
        self.assertEqual(self.client.get("/api/access/me", headers=bad).status_code, 401)

    def test_22_qr_tampering_detected(self):
        admin = self.make_super_admin()
        conductor = self.make_conductor(admin)
        u = self.register("MALE")
        t = self.buy_paid(u)
        qr = json.loads(t["qr_payload"])
        for field, value in (("exp", qr["exp"] + 86400), ("rid", "335-E"), ("tid", "0" * 32)):
            forged = dict(qr, **{field: value})
            res = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": json.dumps(forged)}, headers=conductor["headers"]).json()
            self.assertEqual(res["result"], "INVALID", field)
            self.assertIn("signature", res["detail"])
        self.assertEqual(self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": t["qr_payload"]},
                                          headers=conductor["headers"]).json()["result"], "VALID")

    # ------------------------------------------------------------------ 23-25 documents, outages
    def test_23_document_upload_security(self):
        from app.access.providers.scanner import EICAR

        admin = self.make_super_admin()
        college = self.make_college(admin)
        s = self.register("MALE", is_student=True)
        self.assertEqual(self.submit_student(s, college, bus_pass=b"MZ\x90\x00 executable").status_code, 415)
        self.assertEqual(self.submit_student(s, college, bus_pass=b"plain text pretending").status_code, 415)
        self.assertEqual(self.submit_student(s, college, bus_pass=_pdf(EICAR)).status_code, 422)
        self.config.settings.max_upload_bytes = 1024
        try:
            self.assertEqual(self.submit_student(s, college, bus_pass=_pdf(b"x" * 5000)).status_code, 413)
        finally:
            self.config.settings.max_upload_bytes = 5 * 1024 * 1024
        ok = self.submit_student(s, college)
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["documents"][0]["scan_status"], "NOT_SCANNED")  # never claims CLEAN without a real scanner
        other = self.register("MALE")
        doc_id = ok.json()["documents"][0]["id"]
        self.assertEqual(self.client.get(f"/api/access/documents/{doc_id}/url", headers=other["headers"]).status_code, 404)
        own = self.client.get(f"/api/access/documents/{doc_id}/url", headers=s["headers"]).json()
        self.assertEqual(self.client.get(f"/api/access/{own['url']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/access/documents/{doc_id}/content?token=forged").status_code, 404)
        # Only STUDENT role may upload; wrong college email domain rejected
        self.assertEqual(self.submit_student(other, college).status_code, 403)

    def test_24_identity_provider_unavailable(self):
        from app.access.providers import biometric, identity

        identity.set_identity_provider(identity.UnavailableIdentityProvider())
        u = self.register("FEMALE")
        r = self.client.post("/api/access/identity/start", json={"consent": True}, headers=u["headers"])
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["detail"], "Identity verification is temporarily unavailable.")
        self.assertFalse(self.client.get("/api/access/me", headers=u["headers"]).json()["passenger"]["identity_service_available"])
        self.assertEqual(self.buy_paid(u)["fare"], 25)  # still able to travel
        # Face service down: never a free ticket
        identity.set_identity_provider(None)
        self.verify_identity(u)
        biometric.set_biometric_provider(biometric.UnavailableBiometricProvider())
        f = self.face(u)
        self.assertEqual(f["result"], "UNAVAILABLE")
        self.assertEqual(self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True, face_verification_id=f["face_verification_id"]),
                                          headers=u["headers"]).status_code, 409)
        # Fare network down: clean 503
        self.fare_provider.down = True
        self.assertEqual(self.client.post("/api/access/tickets/quote", json=self.journey(), headers=u["headers"]).status_code, 503)

    def test_25_database_failure_returns_503(self):
        u = self.register("MALE")
        self.db.configure("postgresql+psycopg://nobody:wrong@127.0.0.1:9/none")
        try:
            r = self.client.get("/api/access/me", headers=u["headers"])
            self.assertEqual(r.status_code, 503)
            self.assertIn("temporarily unavailable", r.json()["detail"])
        finally:
            self.db.configure(TEST_DB)
        self.assertEqual(self.client.get("/api/access/me", headers=u["headers"]).status_code, 200)

    # ------------------------------------------------------------------ extra security coverage
    def test_26_sessions_refresh_rotation_lockout_and_otp(self):
        u = self.register("MALE")
        r1 = self.client.post("/api/access/auth/refresh", json={"refresh_token": u["refresh_token"]})
        self.assertEqual(r1.status_code, 200)
        # Reusing the rotated token is rejected and revokes the new session too
        self.assertEqual(self.client.post("/api/access/auth/refresh", json={"refresh_token": u["refresh_token"]}).status_code, 401)
        self.assertEqual(self.client.post("/api/access/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code, 401)
        for _ in range(5):
            self.client.post("/api/access/auth/login", json={"identifier": u["email"], "password": "wrong-pass1"})
        r = self.client.post("/api/access/auth/login", json={"identifier": u["email"], "password": "Travel2026"})
        self.assertEqual(r.status_code, 423)
        other = self.register("FEMALE")
        otp = self.client.post("/api/access/auth/otp/request", json={"identifier": other["email"]}).json()
        self.assertEqual(otp["development_notice"], "DEVELOPMENT CODE — NOT SENT BY EMAIL")
        ok = self.client.post("/api/access/auth/otp/verify", json={"identifier": other["email"], "code": otp["development_otp"]})
        self.assertEqual(ok.status_code, 200)
        # Weak password rejected
        r = self.client.post("/api/access/auth/register", json={"name": "Test User", "phone": "9845099999", "email": "weak@example.com",
                                                                "password": "password", "gender": "MALE"})
        self.assertEqual(r.status_code, 422)

    def test_27_staff_two_factor(self):
        from app.access.security import totp_code

        admin = self.make_super_admin()
        conductor = self.make_conductor(admin)
        secret = self.client.post(f"/api/access/admin/users/{conductor['user_id']}/two-factor", headers=admin["headers"]).json()["totp_secret"]
        emp = self.client.get("/api/access/conductor/me", headers=conductor["headers"]).json()["employee_id"]
        r = self.client.post("/api/access/auth/login", json={"identifier": emp, "password": "Conduct2026", "portal": "conductor"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/access/auth/login", json={"identifier": emp, "password": "Conduct2026", "portal": "conductor", "totp_code": totp_code(secret)})
        self.assertEqual(r.status_code, 200)

    def test_28_eligibility_policy_is_configurable(self):
        import tempfile

        from app.access import eligibility

        admin, college, s, ver, r = self._approved_student()
        policy = json.loads(Path(self.config.settings.eligibility_policy_path).read_text())
        for rule in policy["rules"]:
            rule["enabled"] = rule["id"] != "student_bus_pass"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(policy, fh)
        original = self.config.settings.eligibility_policy_path
        self.config.settings.eligibility_policy_path = fh.name
        eligibility.reload_policy()
        try:
            q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
            self.assertEqual(q["fare"], 25)  # rule switched off by configuration only
        finally:
            self.config.settings.eligibility_policy_path = original
            eligibility.reload_policy()
            os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main()


class AccessSupportCases:
    """Help/feedback, CSV export and self-service account deletion (attached to AccessModuleTests below)."""

    def test_29_feedback_anonymous_and_signed_in(self):
        r = self.client.post("/api/access/feedback", json={"category": "BUS_LOCATION", "message": "Bus 500-D marker did not move", "screen": "map"})
        self.assertEqual(r.status_code, 201)
        u = self.register("MALE")
        self.assertEqual(self.client.post("/api/access/feedback", json={"category": "TICKET", "message": "QR too small"}, headers=u["headers"]).status_code, 201)
        admin = self.make_super_admin()
        rows = self.client.get("/api/access/admin/feedback", headers=admin["headers"]).json()["feedback"]
        self.assertEqual(sorted(r["signed_in"] for r in rows), [False, True])
        self.assertEqual(self.client.get("/api/access/admin/feedback", headers=u["headers"]).status_code, 403)

    def test_30_admin_csv_export_is_formula_safe(self):
        u = self.register("MALE")
        self.buy_paid(u)
        from sqlalchemy import update

        from app.access.models import Ticket

        with self.db.engine().begin() as conn:
            conn.execute(update(Ticket).values(from_stop="=HYPERLINK(\"x\")"))
        admin = self.make_super_admin()
        r = self.client.get("/api/access/admin/tickets.csv", headers=admin["headers"])
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["content-type"])
        self.assertIn("'=HYPERLINK", r.text)
        self.assertEqual(self.client.get("/api/access/admin/tickets.csv", headers=u["headers"]).status_code, 403)

    def test_31_account_deletion_removes_personal_data(self):
        admin = self.make_super_admin()
        college = self.make_college(admin)
        s = self.register("FEMALE", is_student=True)
        self.verify_identity(s)
        existing = set(Path(os.environ["ACCESS_UPLOAD_DIR"]).iterdir())
        self.assertEqual(self.submit_student(s, college).status_code, 201)
        t = self.buy_paid(s)
        files_before = [p for p in Path(os.environ["ACCESS_UPLOAD_DIR"]).iterdir() if p not in existing]  # this student's uploads
        self.assertEqual(len(files_before), 2)
        bad = self.client.post("/api/access/me/delete", json={"password": "wrong-pass1", "confirm": "DELETE"}, headers=s["headers"])
        self.assertEqual(bad.status_code, 401)
        ok = self.client.post("/api/access/me/delete", json={"password": "Travel2026", "confirm": "DELETE"}, headers=s["headers"])
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertFalse(any(p.exists() for p in files_before))  # encrypted files removed
        self.assertEqual(self.client.get("/api/access/me", headers=s["headers"]).status_code, 401)
        self.assertEqual(self.client.post("/api/access/auth/login", json={"identifier": s["email"], "password": "Travel2026"}).status_code, 401)
        self.assertEqual(self.client.post("/api/access/auth/refresh", json={"refresh_token": s["refresh_token"]}).status_code, 401)
        tickets = self.client.get("/api/access/admin/tickets", headers=admin["headers"]).json()["tickets"]
        self.assertEqual([x["reference"] for x in tickets], [t["reference"]])  # kept as anonymised record
        users = self.client.get("/api/access/admin/users?role=STUDENT", headers=admin["headers"]).json()["users"]
        self.assertEqual((users[0]["name"], users[0]["email"], users[0]["is_active"]), ("Deleted account", None, False))


class EmailLoginCodeCases:
    """Password + emailed one-time code sign-in (attached to AccessModuleTests below)."""

    def _start(self, email):
        r = self.client.post("/api/access/auth/login", json={"identifier": email, "password": "Travel2026"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_32_login_requires_emailed_code(self):
        u = self.register("MALE")
        d = self._start(u["email"])
        self.assertEqual(d["status"], "EMAIL_CODE_SENT")
        self.assertNotIn("access_token", d)
        self.assertTrue(d["email_hint"].endswith("@example.com") and "*" in d["email_hint"])
        self.assertEqual(d["development_notice"], "DEVELOPMENT CODE — NOT SENT BY EMAIL")
        wrong = str((int(d["development_code"]) + 1) % 1_000_000).zfill(6)
        r = self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": wrong})
        self.assertEqual(r.status_code, 401)
        self.assertIn("4 attempt(s) left", r.json()["detail"])
        ok = self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": d["development_code"]})
        self.assertEqual(ok.status_code, 200)
        self.assertIn("access_token", ok.json())
        again = self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": d["development_code"]})
        self.assertEqual(again.status_code, 401)  # single use
        # A code only works for its own sign-in attempt
        d1, d2 = self._start(u["email"]), self._start(u["email"])
        self.assertEqual(self.client.post("/api/access/auth/login/verify", json={"challenge_id": d2["challenge_id"], "code": d1["development_code"]}).status_code
                         if d1["development_code"] != d2["development_code"] else 401, 401)
        # Wrong password never sends a code
        bad = self.client.post("/api/access/auth/login", json={"identifier": u["email"], "password": "Wrong2026x"})
        self.assertEqual(bad.status_code, 401)

    def test_33_code_attempt_limit_and_expiry(self):
        from sqlalchemy import update

        from app.access.models import OtpChallenge

        u = self.register("FEMALE")
        d = self._start(u["email"])
        wrong = str((int(d["development_code"]) + 7) % 1_000_000).zfill(6)
        for _ in range(5):
            self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": wrong})
        r = self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": d["development_code"]})
        self.assertEqual(r.status_code, 401)  # locked after 5 wrong attempts
        d = self._start(u["email"])
        from datetime import datetime, timezone
        with self.db.engine().begin() as conn:
            conn.execute(update(OtpChallenge).where(OtpChallenge.id == d["challenge_id"]).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        r = self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": d["development_code"]})
        self.assertEqual(r.status_code, 401)
        self.assertIn("expired", r.json()["detail"])

    def test_34_resend_cooldown_and_limit(self):
        from datetime import datetime, timezone

        from sqlalchemy import update

        from app.access.models import OtpChallenge

        u = self.register("MALE")
        d = self._start(u["email"])
        self.assertEqual(self.client.post("/api/access/auth/login/resend", json={"challenge_id": d["challenge_id"]}).status_code, 429)

        def age():
            with self.db.engine().begin() as conn:
                conn.execute(update(OtpChallenge).where(OtpChallenge.id == d["challenge_id"]).values(sent_at=datetime.now(timezone.utc) - timedelta(seconds=61)))

        codes = [d["development_code"]]
        for _ in range(3):
            age()
            r = self.client.post("/api/access/auth/login/resend", json={"challenge_id": d["challenge_id"]})
            self.assertEqual(r.status_code, 200, r.text)
            codes.append(r.json()["development_code"])
        age()
        self.assertEqual(self.client.post("/api/access/auth/login/resend", json={"challenge_id": d["challenge_id"]}).status_code, 429)
        if codes[0] != codes[-1]:  # the first code no longer works after a resend
            self.assertEqual(self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": codes[0]}).status_code, 401)
        ok = self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": codes[-1]})
        self.assertEqual(ok.status_code, 200)

    def test_35_code_is_sent_by_smtp_email(self):
        import smtplib

        from app.access.providers import otp

        sent = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=None):
                self.calls = [("connect", host, port)]
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def starttls(self, context=None):
                self.calls.append(("starttls",))
            def login(self, user, pw):
                self.calls.append(("login", user))
            def send_message(self, msg):
                sent.append((msg, self.calls))

        cfg = self.config.settings
        saved = (cfg.smtp_host, cfg.smtp_from, cfg.smtp_username, cfg.smtp_password, cfg.smtp_security)
        real_smtp = smtplib.SMTP
        cfg.smtp_host, cfg.smtp_from, cfg.smtp_username, cfg.smtp_password, cfg.smtp_security = "smtp.test", "no-reply@nammabus.test", "mailer", "secret", "starttls"
        smtplib.SMTP = FakeSMTP
        otp.set_otp_delivery(otp.EmailOtpDelivery())
        try:
            u = self.register("MALE", name="Madhusudhan")
            d = self._start(u["email"])
            self.assertNotIn("development_code", d)  # real delivery: code only in the email
            self.assertEqual(len(sent), 1)
            msg, calls = sent[0]
            self.assertEqual(msg["To"], u["email"])
            code = msg["Subject"].split()[0]
            self.assertTrue(code.isdigit() and len(code) == 6)
            self.assertIn(code, msg.get_body(("plain",)).get_content())
            self.assertIn(("starttls",), calls)
            self.assertIn(("login", "mailer"), calls)
            ok = self.client.post("/api/access/auth/login/verify", json={"challenge_id": d["challenge_id"], "code": code})
            self.assertEqual(ok.status_code, 200)

            # Delivery failure: clean 503 and no session
            class BrokenSMTP(FakeSMTP):
                def send_message(self, msg):
                    raise smtplib.SMTPServerDisconnected("down")
            smtplib.SMTP = BrokenSMTP
            r = self.client.post("/api/access/auth/login", json={"identifier": u["email"], "password": "Travel2026"})
            self.assertEqual(r.status_code, 503)
            self.assertNotIn("access_token", r.text)
        finally:
            smtplib.SMTP = real_smtp
            otp.set_otp_delivery(None)
            cfg.smtp_host, cfg.smtp_from, cfg.smtp_username, cfg.smtp_password, cfg.smtp_security = saved


for _name, _fn in list(vars(EmailLoginCodeCases).items()):
    if _name.startswith("test_") or _name == "_start":
        setattr(AccessModuleTests, _name, _fn)


for _name, _fn in list(vars(AccessSupportCases).items()):
    if _name.startswith("test_"):
        setattr(AccessModuleTests, _name, _fn)


class SpecFlowCases:
    """Passenger categories, college self-registration, conductor portal, buses and admin controls (spec v2)."""

    def _register_college(self, name="Sri Demo Institute of Technology"):
        n = self._uniq()
        data = {"college_name": name, "affiliation": "VTU", "address": "12 MG Road", "city": "Bengaluru", "state": "Karnataka",
                "official_email": f"principal{n}@sdit{n}.edu.in", "phone": "08022334455", "officer_name": "Dr. Rao",
                "officer_designation": "Principal", "password": "College2026", "website": f"https://sdit{n}.edu.in"}
        r = self.client.post("/api/access/colleges/register", data=data, files={"document": ("aicte.pdf", _pdf(), "application/pdf")})
        self.assertEqual(r.status_code, 201, r.text)
        return {**r.json(), "email": data["official_email"], "domain": f"sdit{n}.edu.in"}

    def _college_row(self, admin, code):
        rows = self.client.get("/api/access/admin/colleges", headers=admin["headers"]).json()["colleges"]
        return next(c for c in rows if c["code"] == code)

    def _eligibility(self, user):
        r = self.client.get("/api/access/passenger/eligibility", headers=user["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ---------------------------------------------------------------- passenger categories
    def test_s01_male_without_bus_pass_is_regular_paid(self):
        u = self.register("MALE", has_bus_pass=False, date_of_birth="2001-04-12")
        self.assertEqual(u["next_step"], "DASHBOARD")
        e = self._eligibility(u)
        self.assertEqual((e["eligibility"], e["reason_code"], e["category"]), ("REGULAR_PAID", "NOT_ELIGIBLE", "MALE_REGULAR"))
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=u["headers"]).json()
        self.assertEqual((q["fare"], q["eligibility"]), (25, "REGULAR_PAID"))
        prof = self.client.get("/api/access/passenger/profile", headers=u["headers"]).json()
        self.assertEqual(prof["date_of_birth"], "2001-04-12")

    def test_s02_male_with_bus_pass_needs_college_verification(self):
        u = self.register("MALE", has_bus_pass=True)
        me = self.client.get("/api/access/me", headers=u["headers"]).json()
        self.assertEqual(me["role"], "STUDENT")
        e = self._eligibility(u)
        self.assertEqual(e["eligibility"], "REGULAR_PAID")
        self.assertIn(e["reason_code"], ("VERIFICATION_REQUIRED", "NOT_ELIGIBLE"))
        self.assertEqual(e["bus_pass_status"], "NOT_SUBMITTED")

    def test_s03_female_without_aadhaar_pays_regular_fare(self):
        u = self.register("FEMALE", has_aadhaar=False)
        e = self._eligibility(u)
        self.assertEqual((e["eligibility"], e["reason_code"]), ("REGULAR_PAID", "NOT_ELIGIBLE"))
        r = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True), headers=u["headers"])
        self.assertEqual((r.status_code, r.json()["detail"]["reason_code"]), (409, "NOT_ELIGIBLE"))  # never silently free
        r = self.client.post("/api/access/tickets/create", json=self.journey(), headers=u["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["fare"], r.json()["ticket_type"]), (25, "PAID"))

    def test_s04_female_with_aadhaar_requires_verification_then_free(self):
        u = self.register("FEMALE", has_aadhaar=True)
        self.assertEqual(self._eligibility(u)["reason_code"], "VERIFICATION_REQUIRED")
        self.verify_identity(u)
        self.assertEqual(self.client.post("/api/access/face/start", json={"consent": True}, headers=u["headers"]).status_code, 200)
        face = self.face(u)
        self.assertEqual(self.client.get("/api/access/face/status", headers=u["headers"]).json()["valid_now"], True)
        t = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True, face_verification_id=face["face_verification_id"]),
                             headers=u["headers"])
        self.assertEqual(t.status_code, 201, t.text)
        self.assertEqual((t.json()["fare"], t.json()["eligibility"]), (0, "FEMALE_IDENTITY_VERIFIED_FREE"))

    def test_s05_failed_face_match_is_not_free(self):
        u = self.register("FEMALE", has_aadhaar=True)
        self.verify_identity(u)
        face = self.face(u, outcome="NO_MATCH")
        r = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True, face_verification_id=face["face_verification_id"]),
                             headers=u["headers"])
        self.assertEqual(r.status_code, 409)

    def test_s06_frontend_cannot_bypass_eligibility(self):
        u = self.register("MALE", has_bus_pass=False)
        # Extra fields a tampered client might send are ignored; price and eligibility come from the server
        forged = dict(fare=0, eligibility_type="STUDENT_FREE", ticket_type="ELIGIBLE_FREE", eligible=True, payment_status="NOT_REQUIRED")
        r = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True, **forged), headers=u["headers"])
        self.assertEqual(r.status_code, 409)
        r = self.client.post("/api/access/tickets/create", json=self.journey(**forged), headers=u["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["status"], "PENDING_PAYMENT")
        self.assertEqual((r.json()["fare"], r.json()["ticket_type"]), (25, "PAID"))
        # A forged role claim in the request does not grant staff access
        self.assertEqual(self.client.get("/api/access/admin/dashboard", headers={**u["headers"], "X-Role": "SUPER_ADMIN"}).status_code, 403)
        # Registration cannot create staff roles
        n = self._uniq()
        r = self.client.post("/api/access/auth/register", json={"name": "Sneaky", "phone": f"98451{n:05d}", "email": f"s{n}@example.com",
                                                                "password": "Travel2026", "gender": "MALE", "role": "SUPER_ADMIN"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.client.get("/api/access/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()["role"], "PASSENGER")

    def test_s07_suspended_eligibility_blocks_free_ticket(self):
        admin, college, s, ver, r = self._approved_student()
        self.assertEqual(self._eligibility(s)["eligibility"], "STUDENT_FREE")
        r = self.client.post(f"/api/access/admin/students/{s['user_id']}/suspend-eligibility", json={"reason": "Pass misuse reported"},
                             headers=admin["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        e = self._eligibility(s)
        self.assertEqual((e["eligibility"], e["eligibility_suspended"]), ("REGULAR_PAID", True))
        self.client.post(f"/api/access/admin/students/{s['user_id']}/reinstate-eligibility", headers=admin["headers"])
        self.assertEqual(self._eligibility(s)["eligibility"], "STUDENT_FREE")

    def test_s08_expired_bus_pass_is_not_free(self):
        admin, college, s, ver, r = self._approved_student(expiry=(date.today() - timedelta(days=1)).isoformat())
        e = self._eligibility(s)
        self.assertEqual(e["eligibility"], "REGULAR_PAID")
        self.assertEqual(e["bus_pass_status"], "EXPIRED")

    # ---------------------------------------------------------------- colleges
    def test_s10_college_registration_pending_until_approved(self):
        reg = self._register_college()
        self.assertEqual(reg["status"], "PENDING")
        approved = [c["code"] for c in self.client.get("/api/access/colleges/approved").json()["colleges"]]
        self.assertNotIn(reg["college_id"], approved)
        r = self.client.post("/api/access/auth/login", json={"identifier": reg["email"], "password": "College2026", "portal": "college"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("pending", r.json()["detail"].lower())
        admin = self.make_super_admin()
        row = self._college_row(admin, reg["college_id"])
        detail = self.client.get(f"/api/access/admin/colleges/{row['id']}", headers=admin["headers"]).json()
        self.assertIsNotNone(detail["document"])
        r = self.client.post(f"/api/access/admin/colleges/{row['id']}/approve", json={}, headers=admin["headers"])
        self.assertEqual(r.json()["status"], "APPROVED")
        approved = [c["code"] for c in self.client.get("/api/access/colleges/approved").json()["colleges"]]
        self.assertIn(reg["college_id"], approved)
        s = self.login({"identifier": reg["email"], "password": "College2026", "portal": "college"})
        self.assertIn("access_token", s)

    def test_s11_college_rejection_needs_reason_and_blocks_login(self):
        reg = self._register_college()
        admin = self.make_super_admin()
        row = self._college_row(admin, reg["college_id"])
        self.assertEqual(self.client.post(f"/api/access/admin/colleges/{row['id']}/reject", json={}, headers=admin["headers"]).status_code, 422)
        r = self.client.post(f"/api/access/admin/colleges/{row['id']}/reject", json={"reason": "Documents unreadable"}, headers=admin["headers"])
        self.assertEqual(r.json()["status"], "REJECTED")
        r = self.client.post("/api/access/auth/login", json={"identifier": reg["email"], "password": "College2026", "portal": "college"})
        self.assertEqual(r.status_code, 403)

    def test_s12_suspended_college_loses_portal_and_student_benefit(self):
        admin, college, s, ver, r = self._approved_student()
        row = self._college_row(admin, college["code"])
        r = self.client.post(f"/api/access/admin/colleges/{row['id']}/suspend", json={"reason": "Under review by BMTC"}, headers=admin["headers"])
        self.assertEqual(r.json()["status"], "SUSPENDED")
        self.assertEqual(self.client.get("/api/access/college/requests", headers=college["headers"]).status_code, 403)
        self.assertEqual(self._eligibility(s)["eligibility"], "REGULAR_PAID")
        self.assertNotIn(college["code"], [c["code"] for c in self.client.get("/api/access/colleges/approved").json()["colleges"]])
        self.client.post(f"/api/access/admin/colleges/{row['id']}/reactivate", json={}, headers=admin["headers"])
        self.assertEqual(self._eligibility(s)["eligibility"], "STUDENT_FREE")

    def test_s13_college_can_search_and_revoke_pass(self):
        admin, college, s, ver, r = self._approved_student()
        rows = self.client.get("/api/access/college/requests?q=asha", headers=college["headers"]).json()
        self.assertEqual(rows["count"], 1)
        self.assertEqual(self.client.get("/api/access/college/requests?q=nobody", headers=college["headers"]).json()["count"], 0)
        r = self.client.post(f"/api/access/college/requests/{ver['verification_id']}/revoke", json={"reason": "Student left the college"},
                             headers=college["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._eligibility(s)["eligibility"], "REGULAR_PAID")

    def test_s14_no_public_staff_registration(self):
        paths = {getattr(r, "path", "") for r in self.client.app.routes}
        for route in self.client.app.routes:
            for sub in getattr(getattr(route, "original_router", None), "routes", []) or []:
                paths.add(getattr(sub, "path", ""))
        self.assertFalse(any("conductor/register" in p or "admin/register" in p for p in paths))
        r = self.client.post("/api/access/admin/conductors", json={"name": "X", "password": "Conduct2026", "employee_id": "CONDUCTOR-X"})
        self.assertEqual(r.status_code, 401)

    # ---------------------------------------------------------------- conductors & buses
    def _bus(self, admin, label, route="500-D", reg=None):
        r = self.client.post("/api/access/admin/buses", json={"fleet_label": label, "route": route, "registration_number": reg},
                             headers=admin["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def test_s20_conductor_login_and_wrong_password(self):
        admin = self.make_super_admin()
        c = self.make_conductor(admin)
        r = self.client.post("/api/access/conductor/login", json={"conductor_id": c["employee_id"], "password": "wrong-pass"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/access/conductor/login", json={"conductor_id": "CONDUCTOR-NOPE", "password": "Conduct2026"})
        self.assertEqual(r.status_code, 401)
        logs = self.client.get("/api/access/admin/audit-logs?action=CONDUCTOR_LOGIN_FAILED", headers=admin["headers"]).json()["logs"]
        self.assertGreaterEqual(len(logs), 2)
        # a passenger token cannot use conductor endpoints
        p = self.register("MALE")
        self.assertEqual(self.client.get("/api/access/conductor/me", headers=p["headers"]).status_code, 403)

    def test_s21_bus_assignment_and_unavailable_realtime(self):
        admin = self.make_super_admin()
        bus = self._bus(admin, "BUS 9", route="500-D")
        c = self.make_conductor(admin)
        r = self.client.patch(f"/api/access/admin/conductors/{c['user_id']}", json={"bus_id": bus["id"]}, headers=admin["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        b = self.client.get("/api/access/conductor/bus", headers=c["headers"]).json()
        self.assertEqual(b["bus"]["fleet_label"], "BUS 9")
        # no registration → never a made-up position
        self.assertFalse(b["realtime"]["available"])
        self.assertEqual(b["realtime"]["status"], "REALTIME DATA UNAVAILABLE")
        self.assertNotIn("latitude", b["realtime"])

    def test_s22_trip_start_and_end(self):
        admin = self.make_super_admin()
        bus = self._bus(admin, "BUS 8")
        c = self.make_conductor(admin)
        self.client.patch(f"/api/access/admin/conductors/{c['user_id']}", json={"bus_id": bus["id"]}, headers=admin["headers"])
        first = self.client.post("/api/access/conductor/trip/start", json={"direction": 0}, headers=c["headers"])
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post("/api/access/conductor/trip/start", json={"direction": 1}, headers=c["headers"]).json()["trip"]
        self.assertNotEqual(second["id"], first.json()["trip"]["id"])  # starting a new trip closes the previous one
        self.assertEqual(self.client.get("/api/access/conductor/trip", headers=c["headers"]).json()["trip"]["id"], second["id"])
        r = self.client.post("/api/access/conductor/trip/end", headers=c["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        self.client.patch(f"/api/access/admin/buses/{bus['id']}", json={"operational_status": "MAINTENANCE"}, headers=admin["headers"])
        self.assertEqual(self.client.post("/api/access/conductor/trip/start", json={"direction": 0}, headers=c["headers"]).status_code, 409)

    def test_s23_wrong_route_and_wrong_bus(self):
        admin = self.make_super_admin()
        bus_a = self._bus(admin, "BUS A", route="500-D", reg="KA57F1111")
        bus_b = self._bus(admin, "BUS B", route="335-E", reg="KA57F2222")
        on_route = self.make_conductor(admin)
        other = self.make_conductor(admin)
        self.client.patch(f"/api/access/admin/conductors/{on_route['user_id']}", json={"bus_id": bus_a["id"]}, headers=admin["headers"])
        self.client.patch(f"/api/access/admin/conductors/{other['user_id']}", json={"bus_id": bus_b["id"]}, headers=admin["headers"])
        u = self.register("MALE")
        r = self.client.post("/api/access/tickets/create", json=self.journey(vehicle_number="KA57F9999"), headers=u["headers"])
        t = self.client.post(f"/api/access/tickets/{r.json()['ticket_id']}/pay-demo", json={"outcome": "SUCCESS"}, headers=u["headers"]).json()
        res = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": t["qr_payload"]}, headers=other["headers"]).json()
        self.assertEqual(res["result"], "WRONG_ROUTE")
        res = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": t["qr_payload"]}, headers=on_route["headers"]).json()
        self.assertEqual(res["result"], "WRONG_BUS")

    def test_s24_admin_revokes_ticket(self):
        admin = self.make_super_admin()
        c = self.make_conductor(admin)
        u = self.register("MALE")
        t = self.buy_paid(u)
        r = self.client.post(f"/api/access/admin/tickets/{t['ticket_id']}/revoke", json={"reason": "Refund issued"}, headers=admin["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        res = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": t["qr_payload"]}, headers=c["headers"]).json()
        self.assertEqual(res["result"], "REVOKED")

    def test_s25_admin_only_endpoints_and_dashboard(self):
        admin = self.make_super_admin()
        stats = self.client.get("/api/access/admin/dashboard", headers=admin["headers"]).json()["stats"]
        for key in ("male_passengers", "female_passengers", "pending_colleges", "active_conductors", "active_buses",
                    "tickets_free", "tickets_paid", "failed_verification_attempts", "system_health"):
            self.assertIn(key, stats)
        admin_c, college, s, ver, r = self._approved_student()
        for path in ("/api/access/admin/dashboard", "/api/access/admin/colleges", "/api/access/admin/students",
                     "/api/access/admin/conductors", "/api/access/admin/buses"):
            self.assertEqual(self.client.get(path, headers=college["headers"]).status_code, 403, path)
            self.assertEqual(self.client.get(path, headers=s["headers"]).status_code, 403, path)

    def test_s26_conductor_credential_reset_revokes_old_password(self):
        admin = self.make_super_admin()
        c = self.make_conductor(admin)
        r = self.client.post(f"/api/access/admin/conductors/{c['user_id']}/reset-credentials", headers=admin["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.post("/api/access/conductor/login", json={"conductor_id": c["employee_id"], "password": "Conduct2026"}).status_code, 401)
        new = r.json()["temporary_password"]
        self.assertEqual(self.client.post("/api/access/conductor/login", json={"conductor_id": c["employee_id"], "password": new}).status_code, 200)
        self.client.post(f"/api/access/admin/users/{c['user_id']}/deactivate", headers=admin["headers"])
        self.assertEqual(self.client.post("/api/access/conductor/login", json={"conductor_id": c["employee_id"], "password": new}).status_code, 401)

    # ---------------------------------------------------------------- account recovery & sessions
    def test_s30_forgot_and_reset_password(self):
        u = self.register("MALE")
        r = self.client.post("/api/access/auth/password/forgot", json={"identifier": u["email"]}).json()
        code = r["development_code"]
        bad = self.client.post("/api/access/auth/password/reset", json={"identifier": u["email"], "code": "000000" if code != "000000" else "111111",
                                                                       "new_password": "Newpass2026"})
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/api/access/auth/password/reset", json={"identifier": u["email"], "code": code, "new_password": "Newpass2026"})
        self.assertEqual(ok.status_code, 200, ok.text)
        again = self.client.post("/api/access/auth/password/reset", json={"identifier": u["email"], "code": code, "new_password": "Other2026x"})
        self.assertEqual(again.status_code, 400)  # single use
        self.login({"identifier": u["email"], "password": "Newpass2026"})
        unknown = self.client.post("/api/access/auth/password/forgot", json={"identifier": "nobody@example.com"}).json()
        self.assertNotIn("development_code", unknown)  # same answer, no account enumeration

    def test_s31_sessions_list_and_revoke(self):
        u = self.register("MALE")
        self.login({"identifier": u["email"], "password": "Travel2026"})
        rows = self.client.get("/api/access/auth/sessions", headers=u["headers"]).json()["sessions"]
        self.assertGreaterEqual(len(rows), 2)
        r = self.client.delete(f"/api/access/auth/sessions/{rows[-1]['id']}", headers=u["headers"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.client.get("/api/access/auth/sessions", headers=u["headers"]).json()["sessions"]), len(rows) - 1)
        other = self.register("MALE")
        self.assertEqual(self.client.delete(f"/api/access/auth/sessions/{rows[0]['id']}", headers=other["headers"]).status_code, 404)


class StageFareCases:
    """BMTC revised stage-fare table: Adult / Child / Senior Citizen by distance."""

    def _stage_provider(self, km):
        from app.access import fares

        test = self

        class StageProvider(fares.FareProvider):
            async def quote(self, route, direction, from_stop_id, to_stop_id):
                f = fares.stage_fares(km)
                return fares.FareQuote("500-D", 0, "S1", "Hebbal Bridge", "S3", "Tin Factory", f["ADULT"], fares.STAGE_FARE_SOURCE,
                                       distance_km=km, stage=fares.stage_for_distance(km), fares=f)

        fares.set_fare_provider(StageProvider())
        self.addCleanup(fares.set_fare_provider, test.fare_provider)

    def test_f01_stage_table_matches_bmtc_chart(self):
        from app.access.fares import STAGE_FARES, stage_fares, stage_for_distance

        self.assertEqual(len(STAGE_FARES), 25)
        chart = {2.0: (6, 3, 5), 4.0: (12, 6, 9), 6.0: (18, 9, 14), 8.0: (23, 12, 18), 10.0: (23, 12, 18), 12.0: (24, 12, 18),
                 16.0: (28, 14, 21), 20.0: (28, 14, 21), 22.0: (30, 15, 23), 40.0: (30, 15, 23), 42.0: (32, 16, 24), 50.0: (32, 16, 24)}
        for km, (adult, child, senior) in chart.items():
            self.assertEqual(stage_fares(km), {"ADULT": adult, "CHILD": child, "SENIOR": senior}, km)
        self.assertEqual((stage_for_distance(0.3), stage_for_distance(2.0), stage_for_distance(2.01), stage_for_distance(10.0)), (1, 1, 2, 5))
        self.assertEqual(stage_for_distance(75), 25)  # beyond the chart → last stage

    def test_f02_ticket_uses_category_fare(self):
        self._stage_provider(9.4)  # stage 5
        u = self.register("MALE")
        q = self.client.post("/api/access/tickets/quote", json=self.journey(), headers=u["headers"]).json()
        self.assertEqual((q["fare"], q["fare_stage"], q["fare_category"], q["fare_source"]), (23, 5, "ADULT", "BMTC_STAGE_FARE_TABLE"))
        self.assertEqual(q["fares_by_category"], {"ADULT": 23, "CHILD": 12, "SENIOR": 18})
        q = self.client.post("/api/access/tickets/quote", json=self.journey(fare_category="CHILD", passenger_count=2), headers=u["headers"]).json()
        self.assertEqual(q["fare"], 24)
        t = self.client.post("/api/access/tickets/create", json=self.journey(fare_category="CHILD"), headers=u["headers"]).json()
        self.assertEqual((t["fare"], t["fare_category"], t["fare_stage"]), (12, "CHILD", 5))
        # a client-sent price is ignored
        q = self.client.post("/api/access/tickets/quote", json=self.journey(fare=1, unit_fare=1), headers=u["headers"]).json()
        self.assertEqual(q["fare"], 23)

    def test_f03_senior_fare_needs_age_60_from_dob(self):
        self._stage_provider(16)  # stage 8: 28 / 14 / 21
        no_dob = self.register("MALE")
        r = self.client.post("/api/access/tickets/quote", json=self.journey(fare_category="SENIOR"), headers=no_dob["headers"])
        self.assertEqual(r.status_code, 409)
        young = self.register("MALE", date_of_birth="1990-01-01")
        self.assertEqual(self.client.post("/api/access/tickets/quote", json=self.journey(fare_category="SENIOR"), headers=young["headers"]).status_code, 409)
        senior = self.register("FEMALE", has_aadhaar=False, date_of_birth="1955-06-15")
        q = self.client.post("/api/access/tickets/quote", json=self.journey(fare_category="SENIOR"), headers=senior["headers"]).json()
        self.assertEqual(q["fare"], 21)
        self.assertEqual(self.client.post("/api/access/tickets/quote", json=self.journey(fare_category="VIP"), headers=senior["headers"]).status_code, 422)

    def test_f04_free_eligibility_still_zero_with_stage_fare(self):
        self._stage_provider(30)
        admin, college, s, ver, r = self._approved_student()
        q = self.client.post("/api/access/tickets/quote", json=self.journey(use_eligibility=True), headers=s["headers"]).json()
        self.assertEqual((q["normal_fare"], q["fare"], q["eligibility"]), (30, 0, "STUDENT_FREE"))


for _name, _fn in list(vars(StageFareCases).items()):
    if _name.startswith(("test_", "_")) and not _name.startswith("__"):
        setattr(AccessModuleTests, _name, _fn)


def _ekyc_tools_available():
    import shutil

    return all(shutil.which(t) for t in ("openssl", "xmllint", "bsdtar"))


def build_signed_ekyc(tmp, gender="F", name="Asha Kumari", hours_ago=0, photo=None, share_code="4321", last4="1234"):
    """A UIDAI-format Offline e-KYC ZIP signed with a throwaway test key (xmllint C14N + openssl RSA-SHA256,
    AES-256 ZIP by bsdtar) — produced by tools independent of the code under test."""
    import base64 as b64
    import hashlib
    import subprocess
    from datetime import datetime as dt, timedelta as td, timezone as tz

    run = lambda *a, **k: subprocess.run(list(a), check=True, capture_output=True, **k).stdout  # noqa: E731
    key, cert = f"{tmp}/k.pem", f"{tmp}/c.pem"
    if not os.path.exists(cert):
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "2", "-subj", "/CN=Test UIDAI")
    ref = last4 + (dt.now(tz(td(hours=5, minutes=30))) - td(hours=hours_ago)).strftime("%Y%m%d%H%M%S") + "123"
    pht = b64.b64encode(photo or (b"\xff\xd8\xff\xe0" + b"\x00" * 60)).decode()
    body = (f'<?xml version="1.0" encoding="UTF-8"?>\n<OfflinePaperlessKyc referenceId="{ref}">\n <UidData>\n'
            f'  <Poi dob="15-06-1995" e="" gender="{gender}" m="" name="{name}"/>\n  <Pht>{pht}</Pht>\n </UidData>\n')
    with open(f"{tmp}/doc.xml", "w") as fh:
        fh.write(body + "</OfflinePaperlessKyc>")
    digest = b64.b64encode(hashlib.sha256(run("xmllint", "--c14n", f"{tmp}/doc.xml")).digest()).decode()
    si = ('<SignedInfo xmlns="http://www.w3.org/2000/09/xmldsig#"><CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315">'
          '</CanonicalizationMethod><SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"></SignatureMethod>'
          '<Reference URI=""><Transforms><Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"></Transform></Transforms>'
          f'<DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></DigestMethod><DigestValue>{digest}</DigestValue></Reference></SignedInfo>')
    with open(f"{tmp}/si.xml", "w") as fh:
        fh.write(si)
    sig = b64.b64encode(run("openssl", "dgst", "-sha256", "-sign", key, input=run("xmllint", "--c14n", f"{tmp}/si.xml"))).decode()
    xml = (body + '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">' + si.replace(' xmlns="http://www.w3.org/2000/09/xmldsig#"', "", 1)
           + f"<SignatureValue>{sig}</SignatureValue></Signature></OfflinePaperlessKyc>")
    with open(f"{tmp}/offlineaadhaar.xml", "w") as fh:
        fh.write(xml)
    out = f"{tmp}/ekyc.zip"
    if os.path.exists(out):
        os.remove(out)
    run("bsdtar", "-a", "-cf", out, "--options", "zip:encryption=aes256", "--passphrase", share_code, "-C", tmp, "offlineaadhaar.xml")
    with open(out, "rb") as fh:
        return fh.read(), cert, xml


class EkycCases:
    """UIDAI Offline e-KYC upload, duplicate protection, and face matching against the UIDAI-signed photo."""

    def _ekyc_setup(self):
        if not _ekyc_tools_available():
            self.skipTest("openssl / xmllint / bsdtar not available")
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = self.config.settings.uidai_cert_path
        self.addCleanup(setattr, self.config.settings, "uidai_cert_path", original)
        return tmp.name

    def _upload(self, user, zip_bytes, share_code="4321", consent="true"):
        return self.client.post("/api/access/identity/aadhaar-ekyc", data={"consent": consent, "share_code": share_code},
                                files={"ekyc_file": ("offlineaadhaar.zip", zip_bytes, "application/zip")}, headers=user["headers"])

    def test_k01_ekyc_verifies_and_stores_no_aadhaar_number(self):
        tmp = self._ekyc_setup()
        zip_bytes, cert, xml = build_signed_ekyc(tmp)
        u = self.register("FEMALE", has_aadhaar=True, name="Asha Kumari")
        # not configured → never verified
        self.config.settings.uidai_cert_path = ""
        self.assertEqual(self._upload(u, zip_bytes).status_code, 503)
        self.assertFalse(self.client.get("/api/access/identity/aadhaar-ekyc/info").json()["available"])
        self.config.settings.uidai_cert_path = cert
        self.assertEqual(self._upload(u, zip_bytes, consent="false").status_code, 400)
        self.assertEqual(self._upload(u, zip_bytes, share_code="1111").json()["detail"]["code"], "BAD_SHARE_CODE")
        r = self._upload(u, zip_bytes)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["identity_status"], body["gender_attested"], body["name_matches_account"], body["date_of_birth"]),
                         ("VERIFIED", "F", True, "1995-06-15"))
        st = self.client.get("/api/access/identity/status", headers=u["headers"]).json()
        self.assertEqual((st["identity_status"], st["provider"], st["is_development"]), ("VERIFIED", "UIDAI_OFFLINE_EKYC", False))
        # Nothing stored anywhere contains the Aadhaar reference / last 4 digits or the share code
        from sqlalchemy import text

        with self.db.engine().connect() as conn:
            rows = conn.execute(text("SELECT attributes::text, verification_reference, identity_fingerprint FROM access_identity_verifications")).all()
            logs = conn.execute(text("SELECT coalesce(details::text,'') FROM access_audit_logs")).all()
        dump = " ".join(str(v) for row in rows + logs for v in row)
        self.assertNotIn("1234" + "2026", dump)
        self.assertNotIn("4321", dump)

    def test_k02_ekyc_rejects_tampered_old_and_duplicate(self):
        tmp = self._ekyc_setup()
        zip_bytes, cert, xml = build_signed_ekyc(tmp)
        self.config.settings.uidai_cert_path = cert
        u = self.register("FEMALE", has_aadhaar=True)
        import subprocess

        with open(f"{tmp}/offlineaadhaar.xml", "w") as fh:
            fh.write(xml.replace('gender="F"', 'gender="M"'))
        os.remove(f"{tmp}/ekyc.zip")
        subprocess.run(["bsdtar", "-a", "-cf", f"{tmp}/ekyc.zip", "--options", "zip:encryption=aes256", "--passphrase", "4321", "-C", tmp,
                        "offlineaadhaar.xml"], check=True)
        r = self._upload(u, open(f"{tmp}/ekyc.zip", "rb").read())
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (422, "BAD_SIGNATURE"))
        old, _, _ = build_signed_ekyc(tmp, hours_ago=100)
        self.assertEqual(self._upload(u, old).json()["detail"]["code"], "TOO_OLD")
        self.assertEqual(self._upload(u, zip_bytes).status_code, 200)
        other = self.register("FEMALE", has_aadhaar=True)
        r = self._upload(other, zip_bytes)
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (409, "ALREADY_USED"))

    def test_k03_male_ekyc_gives_no_female_benefit(self):
        tmp = self._ekyc_setup()
        zip_bytes, cert, _ = build_signed_ekyc(tmp, gender="M", name="Ravi Kumar", last4="5678")
        self.config.settings.uidai_cert_path = cert
        u = self.register("FEMALE", has_aadhaar=True)
        self.assertEqual(self._upload(u, zip_bytes).json()["gender_attested"], "M")
        self.assertEqual(self._eligibility(u)["eligibility"], "REGULAR_PAID")

    def test_k04_face_match_uses_uidai_photo_then_free_ticket(self):
        from app.access.providers import biometric

        tmp = self._ekyc_setup()
        photo = b"\xff\xd8\xff\xe0" + b"REFERENCE-PHOTO" * 4
        zip_bytes, cert, _ = build_signed_ekyc(tmp, photo=photo)
        self.config.settings.uidai_cert_path = cert
        seen = {}

        class RecordingMatcher(biometric.BiometricProvider):
            name = "TEST_MATCHER"
            needs_reference_image = True

            def available(self):
                return True

            def verify(self, capture, identity_reference, mock_outcome=None, reference_image=None):
                seen["reference"] = reference_image
                return biometric.BiometricResult(result="MATCH" if reference_image == photo else "NO_MATCH", reference="FACE-T", score=0.71)

        biometric.set_biometric_provider(RecordingMatcher())
        u = self.register("FEMALE", has_aadhaar=True)
        self.assertEqual(self._upload(u, zip_bytes).status_code, 200)
        r = self.client.post("/api/access/face/verify", data={"consent": "true"}, files={"image": ("face.png", _png(), "image/png")},
                             headers=u["headers"])
        self.assertEqual(r.json()["result"], "MATCH", r.text)
        self.assertEqual(seen["reference"], photo)  # compared with the UIDAI-signed photo, decrypted only in memory
        t = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True, face_verification_id=r.json()["face_verification_id"]),
                             headers=u["headers"]).json()
        self.assertEqual((t["fare"], t["eligibility"]), (0, "FEMALE_IDENTITY_VERIFIED_FREE"))

    def test_k05_opencv_matcher_unavailable_without_models(self):
        from app.access.providers.biometric import OpenCVFaceProvider

        with TemporaryDirectory() as empty:
            p = OpenCVFaceProvider(model_dir=empty)
            self.assertFalse(p.available())
            self.assertEqual(p.verify(_png(), "x", reference_image=None).result, "ERROR")


class EAadhaarPdfCases:
    """UIDAI e-Aadhaar PDF: password, CMS signature over the whole file, chain to a trusted root, UIDAI signer."""

    def _pdf_setup(self):
        import importlib.util
        import shutil

        from app.access.providers.biometric import OpenCVFaceProvider

        sp = Path(importlib.util.find_spec("skimage").origin).parent if importlib.util.find_spec("skimage") else None
        photo = sp / "data" / "astronaut.png" if sp else None
        if not (shutil.which("openssl") and importlib.util.find_spec("matplotlib") and photo and photo.exists() and OpenCVFaceProvider().available()):
            self.skipTest("openssl / matplotlib / sample photo / face models not available")
        import sys

        sys.path.insert(0, str(Path(__file__).parent))
        import eaadhaar_fixture as fx

        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fx.make_chain(tmp.name)
        original = self.config.settings.trusted_ca_dir
        self.addCleanup(setattr, self.config.settings, "trusted_ca_dir", original)
        self.config.settings.trusted_ca_dir = f"{tmp.name}/trusted"
        return fx, tmp.name, str(photo)

    def test_p01_eaadhaar_pdf_verifies_then_face_match_free_ticket(self):
        from app.access.providers import biometric

        fx, tmp, photo = self._pdf_setup()
        pdf = fx.sign(fx.encrypt(fx.make_pdf(photo), "ASHA1995"), tmp)
        u = self.register("FEMALE", has_aadhaar=True, name="Asha Kumari")
        upload = lambda pw: self.client.post("/api/access/identity/aadhaar", data={"consent": "true", "pdf_password": pw},  # noqa: E731
                                             files={"ekyc_file": ("EAadhaar.pdf", pdf, "application/pdf")}, headers=u["headers"])
        self.assertEqual(upload("ASHA1996").json()["detail"]["code"], "BAD_PASSWORD")
        r = upload("asha1995")
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()
        self.assertEqual((b["provider"], b["gender_attested"], b["date_of_birth"], b["name_matches_account"]),
                         ("UIDAI_EAADHAAR_PDF", "F", "1995-06-15", True))
        self.assertTrue(self.client.get("/api/access/identity/aadhaar-ekyc/info").json()["pdf_available"])
        # Real face matching against the photo taken from the signed PDF
        biometric.set_biometric_provider(biometric.OpenCVFaceProvider())
        import cv2

        live = cv2.imencode(".jpg", cv2.convertScaleAbs(cv2.imread(photo), alpha=0.85, beta=-10))[1].tobytes()
        f = self.client.post("/api/access/face/verify", data={"consent": "true"}, files={"image": ("live.jpg", live, "image/jpeg")},
                             headers=u["headers"]).json()
        self.assertEqual(f["result"], "MATCH", f)
        t = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True, face_verification_id=f["face_verification_id"]),
                             headers=u["headers"]).json()
        self.assertEqual((t["fare"], t["eligibility"]), (0, "FEMALE_IDENTITY_VERIFIED_FREE"))
        # Someone else's face does not match
        other = cv2.imencode(".jpg", cv2.imread(str(Path(photo).parents[2] / "matplotlib" / "mpl-data" / "sample_data" / "grace_hopper.jpg")))[1].tobytes()
        f2 = self.client.post("/api/access/face/verify", data={"consent": "true"}, files={"image": ("x.jpg", other, "image/jpeg")},
                              headers=u["headers"]).json()
        self.assertEqual(f2["result"], "NO_MATCH")

    def test_p02_eaadhaar_pdf_rejections(self):
        from app.access.providers.aadhaar_ekyc import EkycError
        from app.access.providers.eaadhaar_pdf import verify_eaadhaar_pdf

        fx, tmp, photo = self._pdf_setup()
        trusted = f"{tmp}/trusted"
        signed = fx.sign(fx.encrypt(fx.make_pdf(photo), "ASHA1995"), tmp)
        self.assertEqual(verify_eaadhaar_pdf(signed, "ASHA1995", trusted).last4, "1234")  # not the VID digits
        cases = [
            (signed + b"\n% appended\n", "ASHA1995", trusted, "BAD_SIGNATURE"),
            (signed[:300] + bytes([signed[300] ^ 1]) + signed[301:], "ASHA1995", trusted, "BAD_SIGNATURE"),
            (fx.encrypt(fx.make_pdf(photo), "ASHA1995"), "ASHA1995", trusted, "NOT_SIGNED"),
            (signed, "ASHA1995", "", "UNAVAILABLE"),
            (signed, "1995ASHA", trusted, "BAD_PASSWORD"),
        ]
        other, fake = TemporaryDirectory(), TemporaryDirectory()
        self.addCleanup(other.cleanup)
        self.addCleanup(fake.cleanup)
        fx.make_chain(other.name)  # a different, untrusted root
        cases.append((signed, "ASHA1995", f"{other.name}/trusted", "BAD_SIGNATURE"))
        fx.make_chain(fake.name, signer_org="Not UIDAI Pvt Ltd")  # trusted chain, but the signer is not UIDAI
        cases.append((fx.sign(fx.encrypt(fx.make_pdf(photo), "ASHA1995"), fake.name), "ASHA1995", f"{fake.name}/trusted", "BAD_SIGNATURE"))
        for pdf, pw, anchors, code in cases:
            with self.assertRaises(EkycError) as ctx:
                verify_eaadhaar_pdf(pdf, pw, anchors)
            self.assertEqual(ctx.exception.code, code)


for _name, _fn in list(vars(EAadhaarPdfCases).items()):
    if _name.startswith(("test_", "_")) and not _name.startswith("__"):
        setattr(AccessModuleTests, _name, _fn)


for _name, _fn in list(vars(EkycCases).items()):
    if _name.startswith(("test_", "_")) and not _name.startswith("__"):
        setattr(AccessModuleTests, _name, _fn)


for _name, _fn in list(vars(SpecFlowCases).items()):
    if _name.startswith(("test_", "_")) and not _name.startswith("__"):
        setattr(AccessModuleTests, _name, _fn)


class RealtimeTripCases:
    """Real-time ticketing & capacity: the trip row in PostgreSQL is the only passenger count."""

    # ------------------------------------------------------------ helpers
    def _trip(self, trip_id=None):
        from app.access.models import Trip

        gen = self.db.get_db()
        s = next(gen)
        t = s.get(Trip, trip_id or self.trip_id)
        out = (t.passenger_count, t.tickets_issued, t.max_capacity, t.status)
        gen.close()
        return out

    def _set_capacity(self, cap, trip_id=None):
        from sqlalchemy import text

        with self.db.engine().begin() as conn:
            conn.execute(text("UPDATE access_trips SET max_capacity = :c WHERE id = :i"), {"c": cap, "i": trip_id or self.trip_id})

    def _pending(self, user, **kw):
        r = self.client.post("/api/access/tickets/create", json=self.journey(**kw), headers=user["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def _pay(self, user, ticket, outcome="SUCCESS"):
        return self.client.post(f"/api/access/tickets/{ticket['ticket_id']}/pay-demo", json={"outcome": outcome}, headers=user["headers"])

    def _crew(self, label="BUS 365", reg="KA57F4578", start=True, capacity=None):
        admin = self.make_super_admin()
        body = {"fleet_label": label, "route": "500-D", "registration_number": reg}
        if capacity:
            body["max_capacity"] = capacity
        bus = self.client.post("/api/access/admin/buses", json=body, headers=admin["headers"]).json()
        c = self.make_conductor(admin)
        self.client.patch(f"/api/access/admin/conductors/{c['user_id']}", json={"bus_id": bus["id"]}, headers=admin["headers"])
        trip = None
        if start:
            r = self.client.post("/api/access/conductor/trip/start", json={"direction": 0}, headers=c["headers"])
            self.assertEqual(r.status_code, 200, r.text)
            trip = r.json()["trip"]
        return admin, bus, c, trip

    def _cash(self, c, key, n=1):
        return self.client.post("/api/access/conductor/tickets/issue", json={"from_stop_id": "S1", "to_stop_id": "S3", "passenger_count": n,
                                                                              "idempotency_key": key}, headers=c["headers"])

    @staticmethod
    def _token(user):
        return user["headers"]["Authorization"].split(" ", 1)[1]

    class _AuthedWs:
        """websocket_connect + the first-message auth handshake (the token is never put in the URL)."""

        def __init__(self, tc, user):
            self.cm = tc.client.websocket_connect("/api/access/ws")
            self.token = tc._token(user)

        def __enter__(self):
            ws = self.cm.__enter__()
            ws.send_json({"action": "auth", "token": self.token})
            assert ws.receive_json()["type"] == "AUTH_OK"
            return ws

        def __exit__(self, *exc):
            return self.cm.__exit__(*exc)

    def _ws(self, user):
        return RealtimeTripCases._AuthedWs(self, user)

    def _ws_until(self, ws, predicate, limit=10):
        for _ in range(limit):
            msg = ws.receive_json()
            if predicate(msg):
                return msg
        self.fail("expected realtime message not received")

    # ------------------------------------------------------------ 1. counting rules
    def test_rt01_paid_ticket_counts_only_after_verified_payment(self):
        u = self.register("MALE")
        t = self._pending(u)
        self.assertEqual(t["trip_id"], self.trip_id)
        self.assertEqual(self._trip()[0], 0)  # pending payment is not a passenger
        paid = self._pay(u, t).json()
        self.assertEqual((paid["status"], paid["trip"]["passenger_count"]), ("ISSUED", 1))
        self.assertEqual(self._trip()[:2], (1, 1))

    def test_rt02_failed_payment_never_counts(self):
        u = self.register("MALE")
        t = self._pending(u)
        self.assertEqual(self._pay(u, t, "FAILURE").json()["status"], "CANCELLED")
        self.assertEqual(self._trip()[0], 0)
        self.assertEqual(self._pay(u, t).status_code, 409)  # a cancelled ticket can't be paid afterwards
        self.assertEqual(self._trip()[0], 0)

    def test_rt03_free_ticket_counts_immediately(self):
        _, _, s, _, _ = self._approved_student()
        r = self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True, passenger_count=1), headers=s["headers"])
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["fare"], r.json()["status"], r.json()["trip"]["passenger_count"]), (0, "ISSUED", 1))
        self.assertEqual(self._trip()[0], 1)

    def test_rt04_frontend_cannot_claim_payment_success(self):
        u = self.register("MALE")
        t = self._pending(u)
        order = self.client.post(f"/api/access/tickets/{t['ticket_id']}/payment/order", headers=u["headers"]).json()
        self.assertEqual((order["amount_paise"], order["is_test"]), (2500, True))
        self.assertNotIn("secret", json.dumps(order).lower())
        forged = self.client.post(f"/api/access/tickets/{t['ticket_id']}/payment/verify", headers=u["headers"],
                                  json={"order_id": order["order_id"], "payment_id": "pay_forged123", "signature": "0" * 64,
                                        "payment_success": True})
        self.assertEqual(forged.status_code, 402)
        self.assertEqual(self._trip()[0], 0)
        self.assertEqual(self.client.get(f"/api/access/tickets/{t['ticket_id']}", headers=u["headers"]).json()["status"], "CANCELLED")

    def test_rt05_idempotency_key_never_creates_a_second_ticket(self):
        _, _, s, _, _ = self._approved_student()
        body = self.journey(use_eligibility=True, idempotency_key="tap-0001-abcdef")
        first = self.client.post("/api/access/tickets/create", json=body, headers=s["headers"])
        again = self.client.post("/api/access/tickets/create", json=body, headers=s["headers"])
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()["ticket_id"], again.json()["ticket_id"])
        self.assertTrue(again.json()["idempotent_replay"])
        self.assertEqual(self._trip()[:2], (1, 1))
        # paying the same ticket twice is also counted once
        u = self.register("MALE")
        t = self._pending(u)
        self._pay(u, t)
        self.assertEqual(self._pay(u, t).status_code, 409)
        self.assertEqual(self._trip()[:2], (2, 2))

    # ------------------------------------------------------------ 2. capacity
    def test_rt06_bus_full_is_enforced_by_backend(self):
        self._set_capacity(2)
        u = self.register("MALE")
        self._pay(u, self._pending(u, passenger_count=2))
        self.assertEqual(self._trip()[0], 2)
        r = self.client.post("/api/access/tickets/create", json=self.journey(), headers=u["headers"])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["code"], "BUS_FULL")
        self.assertEqual(r.json()["detail"]["trip"]["occupancy"], "FULL")

    def test_rt07_concurrent_payments_never_overfill(self):
        from concurrent.futures import ThreadPoolExecutor

        self._set_capacity(5)
        users = [self.register("MALE") for _ in range(4)]
        pending = [(u, self._pending(u)) for u in users for _ in range(3)]  # 12 pending tickets for 5 seats
        with ThreadPoolExecutor(max_workers=12) as pool:
            codes = list(pool.map(lambda ut: self._pay(*ut).status_code, pending))
        self.assertEqual(codes.count(200), 5, codes)
        self.assertEqual(codes.count(409), 7, codes)  # paid but full → refunded, not issued
        self.assertEqual(self._trip()[:2], (5, 5))
        admin = self.make_super_admin()
        refunds = self.client.get("/api/access/admin/audit-logs?action=PAYMENT_REFUNDED", headers=admin["headers"]).json()["logs"]
        self.assertEqual(len(refunds), 7)

    def test_rt08_concurrent_cash_tickets_count_exactly(self):
        from concurrent.futures import ThreadPoolExecutor

        _, _, c, trip = self._crew(capacity=10)
        with ThreadPoolExecutor(max_workers=10) as pool:
            res = list(pool.map(lambda i: self._cash(c, f"cash-{i:04d}-key"), range(14)))
        codes = [r.status_code for r in res]
        self.assertEqual((codes.count(201), codes.count(409)), (10, 4), codes)
        self.assertEqual(self._trip(trip["trip_id"])[:2], (10, 10))

    # ------------------------------------------------------------ 3. trips, revocation, conductor rules
    def test_rt09_revoked_ticket_releases_seat_once(self):
        admin = self.make_super_admin()
        u = self.register("MALE")
        t = self._pay(u, self._pending(u, passenger_count=2)).json()
        self.assertEqual(self._trip()[0], 2)
        self.assertEqual(self.client.post(f"/api/access/admin/tickets/{t['ticket_id']}/revoke", json={}, headers=admin["headers"]).status_code, 200)
        self.assertEqual(self._trip()[0], 0)
        self.assertEqual(self.client.post(f"/api/access/admin/tickets/{t['ticket_id']}/revoke", json={}, headers=admin["headers"]).status_code, 409)
        self.assertEqual(self._trip()[0], 0)

    def test_rt10_no_active_trip_and_ended_trip(self):
        from sqlalchemy import text

        u = self.register("MALE")
        t = self._pending(u)
        with self.db.engine().begin() as conn:
            conn.execute(text("UPDATE access_trips SET status = 'COMPLETED' WHERE id = :i"), {"i": self.trip_id})
        r = self._pay(u, t)  # trip ended between booking and payment → refunded, not counted
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (409, "TRIP_ENDED"))
        self.assertEqual(self.client.get(f"/api/access/tickets/{t['ticket_id']}", headers=u["headers"]).json()["payment_status"], "REFUNDED")
        r = self.client.post("/api/access/tickets/create", json=self.journey(), headers=u["headers"])
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (409, "NO_ACTIVE_TRIP"))
        self.assertEqual(self._trip()[0], 0)

    def test_rt11_conductor_issues_only_on_own_running_trip(self):
        admin, bus, c, _ = self._crew(start=False)
        self.assertEqual(self._cash(c, "cash-before-trip").status_code, 409)  # no trip yet
        trip = self.client.post("/api/access/conductor/trip/start", json={"direction": 0}, headers=c["headers"]).json()["trip"]
        self.assertRegex(trip["trip_code"], r"^TRIP-\d{8}-500D-\d{3}$")
        r = self._cash(c, "cash-0001-abcdef", n=2)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["fare"], r.json()["trip"]["passenger_count"]), (50, 2))  # fare from the backend fare table
        self.assertEqual(self._cash(c, "cash-0001-abcdef", n=2).status_code, 200)  # same tap again → same ticket
        self.assertEqual(self._trip(trip["trip_id"])[0], 2)
        live = self.client.get("/api/access/conductor/trip", headers=c["headers"]).json()["trip"]
        self.assertEqual((live["passenger_count"], live["max_capacity"], live["occupancy"]), (2, 50, "AVAILABLE"))
        self.client.patch(f"/api/access/admin/buses/{bus['id']}", json={"operational_status": "MAINTENANCE"}, headers=admin["headers"])
        self.assertEqual(self._cash(c, "cash-0002-abcdef").status_code, 409)  # bus not in service
        # a passenger can't use the conductor endpoint
        self.assertEqual(self._cash(self.register("MALE"), "cash-0003-abcdef").status_code, 403)

    def test_rt12_one_active_trip_per_bus(self):
        admin, bus, c, trip = self._crew()
        other = self.make_conductor(admin)
        self.client.patch(f"/api/access/admin/conductors/{other['user_id']}", json={"bus_id": bus["id"]}, headers=admin["headers"])
        r = self.client.post("/api/access/conductor/trip/start", json={"direction": 0}, headers=other["headers"])
        self.assertEqual(r.status_code, 409, r.text)
        # and the database itself refuses a second ACTIVE trip for the bus
        from datetime import datetime, timezone

        from sqlalchemy.exc import IntegrityError

        from app.access.models import Trip
        gen = self.db.get_db()
        s = next(gen)
        s.add(Trip(bus_id=bus["id"], conductor_id=other["user_id"], route="500-D", status="ACTIVE", started_at=datetime.now(timezone.utc)))
        with self.assertRaises(IntegrityError):
            s.flush()
        s.rollback()
        gen.close()

    def test_rt13_qr_is_bound_to_trip_and_bus(self):
        admin, bus, c, trip = self._crew()
        u = self.register("MALE")
        # two trips on the route now → the passenger must choose; picks the conductor's bus
        r = self.client.post("/api/access/tickets/create", json=self.journey(), headers=u["headers"])
        self.assertEqual(r.json()["detail"]["code"], "CHOOSE_TRIP")
        t = self._pay(u, self._pending(u, trip_id=trip["trip_id"])).json()
        qr = json.loads(t["qr_payload"])
        self.assertEqual((qr["trp"], qr["bus"]), (trip["trip_id"], bus["id"]))
        forged = dict(qr, trp=self.trip_id)  # moving the ticket to another trip breaks the signature
        res = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": json.dumps(forged), "admit": False},
                               headers=c["headers"]).json()
        self.assertEqual(res["result"], "INVALID")
        other_trip_ticket = self._pay(u, self._pending(u, trip_id=self.trip_id)).json()
        res = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": other_trip_ticket["qr_payload"]}, headers=c["headers"]).json()
        self.assertEqual(res["result"], "WRONG_BUS")
        res = self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": t["qr_payload"]}, headers=c["headers"]).json()
        self.assertEqual(res["result"], "VALID")
        self.assertEqual(self._trip(trip["trip_id"])[0], 1)  # scanning admits; it does not count twice

    # ------------------------------------------------------------ 4. realtime
    def test_rt14_websocket_two_clients_see_0_1_2_3(self):
        u = self.register("MALE")
        watcher = self.register("FEMALE", name="Other Rider")
        with self._ws(u) as a, \
                self._ws(watcher) as b:
            for ws, topic in ((a, f"trip:{self.trip_id}"), (b, "route:500D")):
                ws.send_json({"action": "subscribe", "topics": [topic]})
                snap = self._ws_until(ws, lambda m: m["type"] == "SNAPSHOT")
                self.assertEqual(snap["trips"][0]["passenger_count"], 0)
            for expected in (1, 2, 3):
                self._pay(u, self._pending(u))
                for ws in (a, b):
                    msg = self._ws_until(ws, lambda m: m["type"] == "PASSENGER_COUNT_UPDATED")
                    self.assertEqual(msg["trip"]["passenger_count"], expected)
                    blob = json.dumps(msg)
                    for pii in ("Madhusudhan", u["email"], "user_id", "phone", "aadhaar"):
                        self.assertNotIn(pii, blob)
        self.assertEqual(self._trip()[0], 3)

    def test_rt15_reconnect_gets_authoritative_snapshot_and_topics_are_guarded(self):
        u = self.register("MALE")
        with self._ws(u) as ws:
            ws.send_json({"action": "subscribe", "topics": [f"trip:{self.trip_id}", "admin"]})
            denied = self._ws_until(ws, lambda m: m["type"] == "ERROR")
            self.assertEqual((denied["topic"], denied["code"]), ("admin", "FORBIDDEN"))
        # while "disconnected", two tickets are sold
        self._pay(u, self._pending(u))
        self._pay(u, self._pending(u))
        with self._ws(u) as ws:
            ws.send_json({"action": "subscribe", "topics": [f"trip:{self.trip_id}"]})
            snap = self._ws_until(ws, lambda m: m["type"] == "SNAPSHOT")
            self.assertEqual(snap["trips"][0]["passenger_count"], 2)
        with self.client.websocket_connect("/api/access/ws") as ws:
            ws.send_json({"action": "auth", "token": "not-a-token"})
            self.assertEqual(ws.receive_json()["code"], "UNAUTHORIZED")
        # REST fallback returns the same authoritative value
        r = self.client.get(f"/api/access/trips/{self.trip_id}", headers=u["headers"]).json()["trip"]
        self.assertEqual((r["passenger_count"], r["seats_left"]), (2, 48))

    def test_rt16_trip_end_is_broadcast_and_admin_live_view(self):
        admin, bus, c, trip = self._crew()
        _, _, s, _, _ = self._approved_student()
        self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True, trip_id=trip["trip_id"]), headers=s["headers"])
        self._cash(c, "cash-live-0001", n=3)
        live = self.client.get("/api/access/admin/trips/live", headers=admin["headers"]).json()
        row = next(t for t in live["trips"] if t["trip_id"] == trip["trip_id"])
        self.assertEqual((row["passenger_count"], row["free_passengers"], row["paid_passengers"], row["revenue"]), (4, 1, 3, 75))
        self.assertEqual(self.client.get("/api/access/admin/trips/live", headers=s["headers"]).status_code, 403)
        with self._ws(admin) as ws:
            ws.send_json({"action": "subscribe", "topics": ["admin"]})
            self._ws_until(ws, lambda m: m["type"] == "SNAPSHOT")
            self.client.post("/api/access/conductor/trip/end", headers=c["headers"])
            msg = self._ws_until(ws, lambda m: m["type"] == "TRIP_STATE")
            self.assertEqual((msg["trip"]["trip_id"], msg["trip"]["status"], msg["trip"]["passenger_count"]), (trip["trip_id"], "COMPLETED", 4))
        self.assertEqual(self._cash(c, "cash-live-0002").status_code, 409)  # ended trip takes no more tickets

    def test_rt17_audit_trail(self):
        admin, bus, c, trip = self._crew()
        u = self.register("MALE")
        t = self._pay(u, self._pending(u, trip_id=trip["trip_id"])).json()
        self._pay(u, self._pending(u, trip_id=trip["trip_id"]), "FAILURE")
        self.client.post("/api/access/conductor/ticket/verify", json={"qr_payload": t["qr_payload"], "admit": False}, headers=c["headers"])
        self.client.post(f"/api/access/admin/tickets/{t['ticket_id']}/revoke", json={}, headers=admin["headers"])
        self.client.post("/api/access/conductor/trip/end", headers=c["headers"])
        for action in ("TICKET_CREATED", "PAYMENT_VERIFIED", "PAYMENT_FAILED", "TICKET_REVOKED", "PASSENGER_COUNT_UPDATED",
                       "TRIP_STARTED", "TRIP_ENDED", "QR_SCANNED"):
            logs = self.client.get(f"/api/access/admin/audit-logs?action={action}", headers=admin["headers"]).json()["logs"]
            self.assertTrue(logs, action)


    def test_rt18_trip_starts_at_zero_and_ten_tickets_make_ten(self):
        admin, bus, c, trip = self._crew()
        self.assertEqual((trip["passenger_count"], trip["max_capacity"], trip["seats_left"]), (0, 50, 50))
        for i in range(10):
            self.assertEqual(self._cash(c, f"ten-{i:04d}-abcdef").status_code, 201)
        self.assertEqual(self._trip(trip["trip_id"])[:2], (10, 10))
        live = self.client.get(f"/api/access/trips/{trip['trip_id']}", headers=c["headers"]).json()["trip"]
        self.assertEqual((live["passenger_count"], live["seats_left"]), (10, 40))

    def test_rt19_conductor_cannot_issue_on_another_bus(self):
        admin, bus_a, c365, trip_a = self._crew("BUS 365", "KA57F1365")
        bus_b = self.client.post("/api/access/admin/buses", json={"fleet_label": "BUS 356", "route": "500-D", "registration_number": "KA57F1356"},
                                 headers=admin["headers"]).json()
        c356 = self.make_conductor(admin)
        self.client.patch(f"/api/access/admin/conductors/{c356['user_id']}", json={"bus_id": bus_b["id"]}, headers=admin["headers"])
        trip_b = self.client.post("/api/access/conductor/trip/start", json={"direction": 0}, headers=c356["headers"]).json()["trip"]
        r = self.client.post("/api/access/conductor/tickets/issue", headers=c365["headers"],
                             json={"from_stop_id": "S1", "to_stop_id": "S3", "trip_id": trip_b["trip_id"], "idempotency_key": "wrong-bus-0001"})
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (403, "WRONG_CONDUCTOR"))
        self.assertEqual(self._trip(trip_b["trip_id"])[0], 0)  # the other bus's count is untouched
        self.assertEqual(self._trip(trip_a["trip_id"])[0], 0)
        # nor can a conductor end or watch another bus's trip
        with self._ws(c365) as ws:
            ws.send_json({"action": "subscribe", "topics": [f"bus:{bus_b['id']}"]})
            self.assertEqual(self._ws_until(ws, lambda m: m["type"] == "ERROR")["code"], "FORBIDDEN")
        self.client.post("/api/access/conductor/trip/end", headers=c365["headers"])
        self.assertEqual(self._trip(trip_b["trip_id"])[3], "ACTIVE")
        # the realtime message carries the flat fields too
        u = self.register("MALE")
        with self._ws(u) as ws:
            ws.send_json({"action": "subscribe", "topics": [f"trip:{trip_b['trip_id']}"]})
            self._ws_until(ws, lambda m: m["type"] == "SNAPSHOT")
            self._cash(c356, "flat-fields-0001")
            m = self._ws_until(ws, lambda m: m["type"] == "PASSENGER_COUNT_UPDATED")
            self.assertEqual((m["event"], m["trip_id"], m["route"], m["passenger_count"]), ("PASSENGER_COUNT_UPDATED", trip_b["trip_id"], "500-D", 1))
            self.assertIn("timestamp", m)

    # ------------------------------------------------------------ 5. notifications, payments, history, dashboards
    def test_rt20_notifications_ticket_pass_and_bus_full(self):
        _, college, s, ver, r = self._approved_student()
        n = self.client.get("/api/access/notifications", headers=s["headers"]).json()
        self.assertIn("PASS_APPROVED", [x["kind"] for x in n["notifications"]])
        self.client.post("/api/access/tickets/create", json=self.journey(use_eligibility=True), headers=s["headers"])
        n = self.client.get("/api/access/notifications", headers=s["headers"]).json()
        kinds = [x["kind"] for x in n["notifications"]]
        self.assertEqual(kinds.count("TICKET_ISSUED"), 1)
        self.assertGreaterEqual(n["unread"], 2)
        self.assertEqual(self.client.post("/api/access/notifications/read", json={"all": True}, headers=s["headers"]).json()["marked"], n["unread"])
        self.assertEqual(self.client.get("/api/access/notifications", headers=s["headers"]).json()["unread"], 0)
        # conductor: told once when nearly full and once when full
        _, _, c, trip = self._crew(capacity=10)
        for i in range(10):
            self._cash(c, f"fill-{i:04d}-abcdef")
        kinds = [x["kind"] for x in self.client.get("/api/access/notifications", headers=c["headers"]).json()["notifications"]]
        self.assertEqual((kinds.count("BUS_NEARLY_FULL"), kinds.count("BUS_FULL")), (1, 1))

    def test_rt21_notification_is_pushed_only_to_its_owner(self):
        u = self.register("MALE")
        other = self.register("MALE")
        with self._ws(u) as ws:
            ws.send_json({"action": "subscribe", "topics": [f"user:{other['user_id']}", f"user:{u['user_id']}"]})
            self.assertEqual(self._ws_until(ws, lambda m: m["type"] == "ERROR")["code"], "FORBIDDEN")
            self._pay(u, self._pending(u))
            m = self._ws_until(ws, lambda m: m["type"] == "NOTIFICATION")
            self.assertEqual(m["notification"]["kind"], "TICKET_ISSUED")
        # the token is never accepted in the URL (it would end up in access logs)
        with self.client.websocket_connect(f"/api/access/ws?token={self._token(u)}") as ws:
            ws.send_json({"action": "subscribe", "topics": [f"trip:{self.trip_id}"]})
            self.assertEqual(ws.receive_json()["code"], "UNAUTHORIZED")

    def test_rt22_payment_config_cancel_and_timeout(self):
        from sqlalchemy import text

        u = self.register("MALE")
        cfg = self.client.get("/api/access/payments/config", headers=u["headers"]).json()
        self.assertEqual((cfg["provider"], cfg["configured"], cfg["is_test"]), ("test", True, True))
        self.assertNotIn("secret", json.dumps(cfg).lower())
        t = self._pending(u)
        r = self.client.post(f"/api/access/tickets/{t['ticket_id']}/payment/cancel", headers=u["headers"]).json()
        self.assertEqual((r["status"], r["payment_status"]), ("CANCELLED", "CANCELLED"))
        late = self._pending(u)
        with self.db.engine().begin() as conn:
            conn.execute(text("UPDATE access_tickets SET created_at = now() - interval '20 minutes' WHERE id = :i"), {"i": late["ticket_id"]})
        r = self.client.post(f"/api/access/tickets/{late['ticket_id']}/payment/order", headers=u["headers"])
        self.assertEqual((r.status_code, r.json()["detail"]["code"]), (409, "PAYMENT_TIMEOUT"))
        self.assertEqual(self.client.get(f"/api/access/tickets/{late['ticket_id']}", headers=u["headers"]).json()["payment_status"], "TIMEOUT")
        self.assertEqual(self._trip()[0], 0)

    def test_rt23_razorpay_webhook_is_signature_checked_and_idempotent(self):
        import hashlib
        import hmac as _hmac

        from app.access import payments

        class FakeRazorpay(payments.TestPaymentProvider):
            name = "razorpay"
            is_test = False

        cfg = self.config.settings
        old = (cfg.payment_provider, cfg.razorpay_webhook_secret)
        cfg.payment_provider, cfg.razorpay_webhook_secret = "razorpay", "whsec-test-only"
        payments.set_payment_provider(FakeRazorpay())
        try:
            u = self.register("MALE")
            t = self._pending(u)
            order = self.client.post(f"/api/access/tickets/{t['ticket_id']}/payment/order", headers=u["headers"]).json()
            body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_webhook_001", "order_id": order["order_id"]}}}}).encode()
            bad = self.client.post("/api/access/payments/razorpay/webhook", content=body, headers={"X-Razorpay-Signature": "0" * 64})
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(self._trip()[0], 0)
            sig = _hmac.new(b"whsec-test-only", body, hashlib.sha256).hexdigest()
            for _ in range(2):  # delivered twice → counted once
                self.assertEqual(self.client.post("/api/access/payments/razorpay/webhook", content=body,
                                                  headers={"X-Razorpay-Signature": sig}).status_code, 200)
            got = self.client.get(f"/api/access/tickets/{t['ticket_id']}", headers=u["headers"]).json()
            self.assertEqual((got["status"], got["payment_status"]), ("ISSUED", "PAID"))
            self.assertEqual(self._trip()[:2], (1, 1))
            refund = json.dumps({"event": "refund.processed", "payload": {"payment": {"entity": {"id": "pay_webhook_001", "order_id": order["order_id"]}}}}).encode()
            self.client.post("/api/access/payments/razorpay/webhook", content=refund,
                             headers={"X-Razorpay-Signature": _hmac.new(b"whsec-test-only", refund, hashlib.sha256).hexdigest()})
            got = self.client.get(f"/api/access/tickets/{t['ticket_id']}", headers=u["headers"]).json()
            self.assertEqual((got["status"], got["payment_status"]), ("REVOKED", "REFUNDED"))
            self.assertEqual(self._trip()[0], 0)  # seat returned
        finally:
            cfg.payment_provider, cfg.razorpay_webhook_secret = old
            payments.set_payment_provider(None)

    def test_rt24_conductor_trip_history_and_admin_today(self):
        admin, bus, c, trip = self._crew()
        self._cash(c, "hist-0001-abcdef", n=2)
        self.client.post("/api/access/conductor/trip/end", headers=c["headers"])
        hist = self.client.get("/api/access/conductor/trips", headers=c["headers"]).json()["trips"]
        self.assertEqual((hist[0]["trip_id"], hist[0]["passenger_count"], hist[0]["revenue"], hist[0]["status"]), (trip["trip_id"], 2, 50, "COMPLETED"))
        self.assertEqual(self.client.get("/api/access/conductor/trips", headers=self.register("MALE")["headers"]).status_code, 403)
        stats = self.client.get("/api/access/admin/dashboard", headers=admin["headers"]).json()["stats"]
        self.assertEqual((stats["passengers_today"], stats["paid_tickets_today"], stats["revenue_today"]), (2, 1, 50))
        self.assertEqual(stats["active_trips"], 1)  # the fixture trip is still running
        pay = self.client.get("/api/access/admin/payments", headers=admin["headers"]).json()
        self.assertEqual((pay["provider"], pay["recent"][0]["payment_status"]), ("test", "CASH_COLLECTED"))
        self.assertNotIn("passenger_name", json.dumps(pay))
        live = self.client.get("/api/access/admin/trips/live", headers=admin["headers"]).json()["trips"]
        self.assertEqual(live[0]["realtime_status"], "REALTIME DATA UNAVAILABLE")  # no fake stops

    def test_rt25_every_endpoint_commits_before_responding(self):
        """With the default "request" scope FastAPI commits AFTER sending the response, so a client acting at once
        (sign in → verify code, create ticket → pay) could miss the row. Every access endpoint must use scope="function"."""
        import re as _re

        root = Path(__file__).resolve().parents[1] / "app" / "access"
        offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                     if _re.search(r"Depends\(get_db\)", p.read_text())]
        self.assertEqual(offenders, [])

for _name, _fn in list(vars(RealtimeTripCases).items()):
    if _name.startswith(("test_", "_")) and callable(_fn) and not _name.startswith("__"):
        setattr(AccessModuleTests, _name, _fn)


class NammaRouteFareProviderTests(unittest.TestCase):
    """The real fare provider against a mocked NammaRoute API (no network)."""

    def setUp(self):
        import httpx

        from app.services.nammaroute_client import nammaroute_client

        stops = {"0": [{"id": "S1", "name": "Hebbal Bridge"}, {"id": "S2", "name": "Nagawara"}, {"id": "S3", "name": "Tin Factory"}],
                 "1": [{"id": "S3", "name": "Tin Factory"}, {"id": "S2", "name": "Nagawara"}, {"id": "S1", "name": "Hebbal Bridge"}]}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/routes/500-D"):
                return httpx.Response(200, json={"data": {"routeNumber": "500-D", "serviceType": "ORDINARY"}})
            if path.endswith("/routes/500-D/stops"):
                return httpx.Response(200, json={"data": stops[request.url.params.get("direction", "0")]})
            if path.endswith("/fares"):
                if request.url.params.get("from") == "S1":
                    return httpx.Response(200, json={"data": {"fareAmount": 30}})
                return httpx.Response(404, json={"status": "ERROR"})
            return httpx.Response(404, json={"status": "ERROR"})

        self.client = nammaroute_client
        self.client.reset()
        self.client.transport = httpx.MockTransport(handler)

    def tearDown(self):
        self.client.transport = None
        self.client.reset()

    def test_stage_fare_from_stop_coordinates(self):
        import asyncio

        import httpx

        from app.access.fares import NammaRouteFareProvider

        # three stops ~3.34 km apart along a meridian (0.03° latitude each) → 6.67 km → stage 4
        stops = [{"id": f"P{i}", "name": f"Stop {i}", "latitude": 12.90 + 0.03 * i, "longitude": 77.60} for i in range(3)]

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/routes/365-P"):
                return httpx.Response(200, json={"data": {"routeNumber": "365-P", "serviceType": "ORDINARY"}})
            if path.endswith("/routes/V-500D"):
                return httpx.Response(200, json={"data": {"routeNumber": "V-500D", "serviceType": "VAJRA"}})
            if path.endswith("/stops"):
                return httpx.Response(200, json={"data": stops})
            return httpx.Response(404, json={"status": "ERROR"})

        self.client.reset()
        self.client.transport = httpx.MockTransport(handler)
        q = asyncio.run(NammaRouteFareProvider().quote("365-P", 0, "P0", "P2"))
        self.assertEqual((q.source, q.stage, q.fares), ("BMTC_STAGE_FARE_TABLE", 4, {"ADULT": 23, "CHILD": 12, "SENIOR": 18}))
        self.assertAlmostEqual(q.distance_km, 6.67, delta=0.05)
        q = asyncio.run(NammaRouteFareProvider().quote("365-P", 0, "P0", "P1"))
        self.assertEqual((q.stage, q.unit_fare), (2, 12))
        q = asyncio.run(NammaRouteFareProvider().quote("V-500D", 0, "P0", "P2"))  # AC: not in the ordinary chart
        self.assertEqual(q.source, "DEMO_FARE_ESTIMATE")

    def test_gtfs_fare_direction_and_order(self):
        import asyncio

        from app.access.fares import NammaRouteFareProvider

        p = NammaRouteFareProvider()
        q = asyncio.run(p.quote("500-D", None, "S1", "S3"))
        self.assertEqual((q.direction, q.unit_fare, q.source, q.from_stop, q.to_stop), (0, 30, "GTFS_FARE_RULES", "Hebbal Bridge", "Tin Factory"))
        q = asyncio.run(p.quote("500-D", None, "S3", "S2"))  # reverse direction, no GTFS rule → labelled estimate
        self.assertEqual((q.direction, q.unit_fare, q.source), (1, 25, "DEMO_FARE_ESTIMATE"))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(p.quote("500-D", 0, "S3", "S1"))  # destination before boarding in that direction
        self.assertEqual(ctx.exception.status_code, 400)
