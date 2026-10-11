"""
Development seed data (python -m app.access.cli seed-demo).

Creates exactly three development conductors bound to three buses on real BMTC route numbers, plus demo
colleges and demo passengers. Buses get NO registration number: their live position is shown only after a
Super Admin enters the real registration of a bus that appears in the BMTC feed. No GPS is invented.
Passwords are random and written only to backend/.env.access.accounts (git-ignored); they are never printed.
"""

import secrets
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Bus,
    BusStatus,
    College,
    CollegeAdmin,
    CollegeStatus,
    Conductor,
    Gender,
    PassengerProfile,
    Role,
    TicketVerification,
    User,
    VerificationStatus,
)
from .security import hash_password

ACCOUNTS_FILE = Path(__file__).resolve().parents[2] / ".env.access.accounts"

DEV_FLEET = [  # (bus label, BMTC route number in GTFS, conductor id)
    ("BUS 1", "365-P", "CONDUCTOR-365P"),
    ("BUS 2", "356-M", "CONDUCTOR-356M"),
    ("BUS 3", "361-C", "CONDUCTOR-361C"),
]
LEGACY_DEV_CONDUCTORS = ["EMP1001"]

DEMO_PASSENGERS = [  # key, name, email, gender, role, has_bus_pass, has_aadhaar
    ("PASSENGER_MALE_REGULAR", "Demo Male Regular", "male.regular@example.com", Gender.MALE, Role.PASSENGER, False, None),
    ("PASSENGER_MALE_BUSPASS", "Demo Male Student", "male.buspass@example.com", Gender.MALE, Role.STUDENT, True, None),
    ("PASSENGER_FEMALE_NO_AADHAAR", "Demo Female No Aadhaar", "female.noaadhaar@example.com", Gender.FEMALE, Role.PASSENGER, None, False),
    ("PASSENGER_FEMALE_AADHAAR", "Demo Female Aadhaar", "female.aadhaar@example.com", Gender.FEMALE, Role.PASSENGER, None, True),
]


def _password() -> str:
    return "Nb-" + secrets.token_urlsafe(10)


def _read_accounts() -> Dict[str, str]:
    rows: Dict[str, str] = {}
    if ACCOUNTS_FILE.exists():
        for line in ACCOUNTS_FILE.read_text().splitlines():
            if line.strip() and not line.startswith("#") and " " in line:
                key, rest = line.split(" ", 1)
                rows[key] = rest.strip()
    return rows


def _write_accounts(rows: Dict[str, str]) -> None:
    header = ["# Development accounts for the Namma Bus Access module (local only; git-ignored). Never commit or share.",
              "# Format: KEY  login-details  password=...   (passwords are random; rerun seed-demo --reset-passwords to rotate)"]
    body = [f"{k} {v}" for k, v in sorted(rows.items())]
    ACCOUNTS_FILE.write_text("\n".join(header + body) + "\n")
    try:
        ACCOUNTS_FILE.chmod(0o600)
    except OSError:
        pass


def _user(db: Session, email: str) -> Optional[User]:
    return db.scalars(select(User).where(User.email == email)).first()


def seed_demo(db: Session, reset_passwords: bool = False) -> List[str]:
    log: List[str] = []
    accounts = _read_accounts()

    def set_pw(user: User, key: str, login: str) -> None:
        pw = _password()
        user.password_hash = hash_password(pw)
        accounts[key] = f"{login} password={pw}"

    # --- buses + the three dev conductors ---------------------------------------------------------
    for label, route, cid in DEV_FLEET:
        bus = db.scalars(select(Bus).where(Bus.fleet_label == label)).first()
        if not bus:
            bus = Bus(fleet_label=label, route=route, registration_number=None, operational_status=BusStatus.IN_SERVICE)
            db.add(bus)
            db.flush()
            log.append(f"Bus created: {label} on route {route} (registration not set; realtime shows UNAVAILABLE until set)")
        c = db.scalars(select(Conductor).where(Conductor.employee_id == cid)).first()
        user = db.get(User, c.user_id) if c else None
        if not user:
            user = User(name=f"Conductor {route}", email=None, role=Role.CONDUCTOR)
            db.add(user)
            db.flush()
            set_pw(user, cid, f"conductor_id={cid}")
            c = Conductor(user_id=user.id, employee_id=cid)
            db.add(c)
            log.append(f"Conductor created: {cid}")
        elif reset_passwords or cid not in accounts:
            set_pw(user, cid, f"conductor_id={cid}")
            log.append(f"Conductor password rotated: {cid}")
        user.is_active = True
        c.bus_id, c.assigned_route, c.assigned_bus = bus.id, bus.route, bus.registration_number

    # Exactly three dev conductors: retire the earlier sample conductor
    for emp in LEGACY_DEV_CONDUCTORS:
        c = db.scalars(select(Conductor).where(Conductor.employee_id == emp)).first()
        if not c:
            continue
        user = db.get(User, c.user_id)
        has_history = db.scalars(select(TicketVerification).where(TicketVerification.conductor_id == c.user_id)).first()
        if has_history:
            user.is_active = False
            log.append(f"Old dev conductor {emp} disabled (kept for its scan history)")
        else:
            db.delete(c)
            db.flush()
            if user:
                db.delete(user)
            log.append(f"Old dev conductor {emp} removed")
        accounts.pop("CONDUCTOR", None)

    # --- colleges ---------------------------------------------------------------------------------
    approved = db.scalars(select(College).where(College.code == "DEMO-COLLEGE")).first()
    if not approved:
        approved = College(code="DEMO-COLLEGE", name="Demo College of Engineering (development)", email_domain="demo-college.dev",
                           status=CollegeStatus.APPROVED, city="Bengaluru", state="Karnataka")
        db.add(approved)
        db.flush()
        log.append("Approved demo college created: DEMO-COLLEGE")
    approved.status, approved.is_active = CollegeStatus.APPROVED, True
    approved.city, approved.state = approved.city or "Bengaluru", approved.state or "Karnataka"

    pending = db.scalars(select(College).where(College.code == "DEMO-PENDING")).first()
    if not pending:
        pending = College(code="DEMO-PENDING", name="Demo Pending Institute (development)", email_domain="example.com",
                          status=CollegeStatus.PENDING, is_active=False, city="Bengaluru", state="Karnataka",
                          affiliation="Development only", officer_name="Demo Officer", officer_designation="Principal",
                          official_email="officer.pending@example.com")
        db.add(pending)
        db.flush()
        officer = _user(db, "officer.pending@example.com") or User(name="Demo Officer", email="officer.pending@example.com",
                                                                   role=Role.COLLEGE_ADMIN)
        db.add(officer)
        db.flush()
        set_pw(officer, "COLLEGE_PENDING", "portal=college email=officer.pending@example.com (status: PENDING approval)")
        db.add(CollegeAdmin(user_id=officer.id, college_id=pending.id))
        log.append("Pending demo college created: DEMO-PENDING (awaiting Super Admin approval)")

    # --- demo passengers --------------------------------------------------------------------------
    for key, name, email, gender, role, bus_pass, aadhaar in DEMO_PASSENGERS:
        user = _user(db, email)
        if not user:
            user = User(name=name, email=email, role=role)
            db.add(user)
            db.flush()
            db.add(PassengerProfile(user_id=user.id, gender=gender, has_bus_pass_answer=bus_pass, has_aadhaar_answer=aadhaar,
                                    identity_status=VerificationStatus.DECLINED if aadhaar is False else VerificationStatus.NOT_STARTED))
            set_pw(user, key, f"portal=passenger email={email}")
            log.append(f"Demo passenger created: {key}")
        elif reset_passwords or key not in accounts:
            set_pw(user, key, f"portal=passenger email={email}")
            log.append(f"Demo passenger password rotated: {key}")

    db.commit()
    _write_accounts(accounts)
    log.append(f"Credentials for new/rotated accounts are in {ACCOUNTS_FILE.name} (git-ignored). They are not shown here.")
    return log
