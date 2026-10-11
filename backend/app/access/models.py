"""
PostgreSQL models for the Access module.

Privacy by design:
- No Aadhaar numbers, Aadhaar documents or DigiLocker credentials are stored. Identity verification keeps
  only provider, status, an opaque provider reference and timestamps.
- No face images or biometric templates are stored. FaceVerificationAttempt keeps the result, provider
  reference and timestamps, and is purged after the configured retention period.
- Uploaded documents are encrypted files in private storage; the DB holds metadata and a storage key.
"""

import enum
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Role(str, enum.Enum):
    PASSENGER = "PASSENGER"
    STUDENT = "STUDENT"
    CONDUCTOR = "CONDUCTOR"
    COLLEGE_ADMIN = "COLLEGE_ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class Gender(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class VerificationStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    DECLINED = "DECLINED"  # user chose not to verify / has no Aadhaar
    UNAVAILABLE = "UNAVAILABLE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class StudentStatus(str, enum.Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"  # withdrawn by the college / super admin


class CollegeStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class BusStatus(str, enum.Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    MAINTENANCE = "MAINTENANCE"


class TicketStatus(str, enum.Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ISSUED = "ISSUED"
    USED = "USED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"  # withdrawn by Super Admin


class User(Base):
    __tablename__ = "access_users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[Optional[str]] = mapped_column(String(254), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(256))
    role: Mapped[Role] = mapped_column(Enum(Role, name="access_role"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Optional TOTP second factor (encrypted secret) for staff accounts
    totp_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    profile_photo_document_id: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    passenger_profile: Mapped[Optional["PassengerProfile"]] = relationship(back_populates="user", uselist=False)
    student_profile: Mapped[Optional["StudentProfile"]] = relationship(back_populates="user", uselist=False, foreign_keys="StudentProfile.user_id")


class RefreshToken(Base):
    __tablename__ = "access_refresh_tokens"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Device/session management (shown to the user; never used for authorization)
    user_agent: Mapped[Optional[str]] = mapped_column(String(200))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PasswordReset(Base):
    __tablename__ = "access_password_resets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OtpChallenge(Base):
    __tablename__ = "access_otp_challenges"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(20))  # LOGIN (passwordless) | LOGIN_EMAIL (second sign-in step)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    resend_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PassengerProfile(Base):
    __tablename__ = "access_passenger_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), primary_key=True)
    gender: Mapped[Gender] = mapped_column(Enum(Gender, name="access_gender"))
    # Cached summary; the IdentityVerification rows are the source of truth
    identity_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="access_verification_status"), default=VerificationStatus.NOT_STARTED
    )
    has_aadhaar_answer: Mapped[Optional[bool]] = mapped_column(Boolean)
    has_bus_pass_answer: Mapped[Optional[bool]] = mapped_column(Boolean)
    # Super Admin can suspend free-ticket eligibility (e.g. misuse); reason kept for the audit trail
    eligibility_suspended: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    eligibility_suspended_reason: Mapped[Optional[str]] = mapped_column(Text)
    user: Mapped[User] = relationship(back_populates="passenger_profile")


class College(Base):
    __tablename__ = "access_colleges"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # the "College ID" used to log in
    name: Mapped[str] = mapped_column(String(200))
    email_domain: Mapped[Optional[str]] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Self-registration + Super Admin review. Only APPROVED colleges are offered to students.
    status: Mapped[CollegeStatus] = mapped_column(Enum(CollegeStatus, name="access_college_status"),
                                                  default=CollegeStatus.APPROVED, server_default="APPROVED", index=True)
    affiliation: Mapped[Optional[str]] = mapped_column(String(200))
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(80))
    state: Mapped[Optional[str]] = mapped_column(String(80))
    official_email: Mapped[Optional[str]] = mapped_column(String(254))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    website: Mapped[Optional[str]] = mapped_column(String(200))
    officer_name: Mapped[Optional[str]] = mapped_column(String(120))
    officer_designation: Mapped[Optional[str]] = mapped_column(String(120))
    document_id: Mapped[Optional[str]] = mapped_column(String(32))
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(32))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[Optional[str]] = mapped_column(Text)


class CollegeAdmin(Base):
    __tablename__ = "access_college_admins"
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), primary_key=True)
    college_id: Mapped[str] = mapped_column(ForeignKey("access_colleges.id"), index=True)


class Conductor(Base):
    __tablename__ = "access_conductors"
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    assigned_bus: Mapped[Optional[str]] = mapped_column(String(20))
    assigned_route: Mapped[Optional[str]] = mapped_column(String(40))
    current_trip_id: Mapped[Optional[str]] = mapped_column(String(64))
    bus_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_buses.id"), index=True)


class Bus(Base):
    """A BMTC bus managed in ನಮ್ಮ Bus. Its live position comes only from the realtime feed (matched by
    registration number); nothing is stored or invented when the feed has no data for it."""

    __tablename__ = "access_buses"
    __table_args__ = (Index("ix_access_buses_route", "route"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    fleet_label: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. "BUS 1"
    registration_number: Mapped[Optional[str]] = mapped_column(String(20), unique=True)  # e.g. KA57F4578
    route: Mapped[Optional[str]] = mapped_column(String(40))  # GTFS route number, e.g. 365-P
    operational_status: Mapped[BusStatus] = mapped_column(Enum(BusStatus, name="access_bus_status"), default=BusStatus.IN_SERVICE)
    max_capacity: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trip(Base):
    """One run of a bus. passenger_count is the authoritative number of passengers on valid tickets issued into
    this trip; it only changes inside a transaction that locks this row (see access/trips.py)."""

    __tablename__ = "access_trips"
    __table_args__ = (
        # At most one ACTIVE trip per bus, enforced by the database itself
        Index("uq_access_trips_one_active_per_bus", "bus_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),
        Index("ix_access_trips_status", "status"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    trip_code: Mapped[Optional[str]] = mapped_column(String(40), unique=True)
    bus_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_buses.id"), index=True)
    conductor_id: Mapped[str] = mapped_column(ForeignKey("access_users.id"), index=True)
    route: Mapped[Optional[str]] = mapped_column(String(40))
    direction: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE | COMPLETED
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    passenger_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tickets_issued: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_capacity: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentProfile(Base):
    __tablename__ = "access_student_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), primary_key=True)
    college_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_colleges.id"), index=True)
    student_name: Mapped[Optional[str]] = mapped_column(String(120))
    college_email: Mapped[Optional[str]] = mapped_column(String(254))
    student_id_number: Mapped[Optional[str]] = mapped_column(String(64))
    course: Mapped[Optional[str]] = mapped_column(String(80))
    branch: Mapped[Optional[str]] = mapped_column(String(80))
    year: Mapped[Optional[int]] = mapped_column(Integer)
    semester: Mapped[Optional[int]] = mapped_column(Integer)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    user: Mapped[User] = relationship(back_populates="student_profile", foreign_keys=[user_id])


class Document(Base):
    """Private, encrypted uploaded document. Never served from a public path."""

    __tablename__ = "access_documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), index=True)
    document_type: Mapped[str] = mapped_column(String(40))  # STUDENT_BUS_PASS | COLLEGE_ID | SUPPORTING
    storage_reference: Mapped[str] = mapped_column(String(80), unique=True)
    mime_type: Mapped[str] = mapped_column(String(60))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(String(20))  # CLEAN | NOT_SCANNED | INFECTED
    verification_status: Mapped[StudentStatus] = mapped_column(
        Enum(StudentStatus, name="access_student_status"), default=StudentStatus.PENDING
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentPass(Base):
    __tablename__ = "access_student_passes"
    __table_args__ = (Index("ix_access_student_passes_status_expiry", "status", "expiry_date"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), index=True)
    pass_number: Mapped[Optional[str]] = mapped_column(String(64))
    issue_date: Mapped[Optional[date]] = mapped_column(Date)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_documents.id"))
    status: Mapped[StudentStatus] = mapped_column(Enum(StudentStatus, name="access_student_status"), default=StudentStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentVerification(Base):
    __tablename__ = "access_student_verifications"
    __table_args__ = (Index("ix_access_student_verifications_college_status", "college_id", "status"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), index=True)
    college_id: Mapped[str] = mapped_column(ForeignKey("access_colleges.id"), index=True)
    student_pass_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_student_passes.id"))
    college_id_document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_documents.id"))
    supporting_document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_documents.id"))
    status: Mapped[StudentStatus] = mapped_column(Enum(StudentStatus, name="access_student_status"), default=StudentStatus.PENDING)
    reviewed_by: Mapped[Optional[str]] = mapped_column(ForeignKey("access_users.id"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdentityVerification(Base):
    __tablename__ = "access_identity_verifications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))  # MOCK_DEVELOPMENT | DIGILOCKER
    verification_status: Mapped[VerificationStatus] = mapped_column(Enum(VerificationStatus, name="access_verification_status"))
    verification_reference: Mapped[Optional[str]] = mapped_column(String(80))
    consent_given_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # OAuth state for the authorization round trip (random, single use)
    state_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # Minimum attributes returned by the provider, e.g. {"gender": "F"}; never an Aadhaar number
    attributes: Mapped[Optional[dict]] = mapped_column(JSON)
    is_development: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # UIDAI Offline e-KYC: the UIDAI-signed photo (encrypted private document) used as the face-match reference,
    # and a keyed fingerprint that stops one Aadhaar being used on several accounts. No Aadhaar number is stored.
    reference_photo_document_id: Mapped[Optional[str]] = mapped_column(String(32))
    identity_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), index=True)


class FaceVerificationAttempt(Base):
    """Result-only audit of a face verification. No image, embedding or template is ever stored."""

    __tablename__ = "access_face_verification_attempts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"), index=True)
    identity_verification_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_identity_verifications.id"))
    provider: Mapped[str] = mapped_column(String(30))
    result: Mapped[str] = mapped_column(String(20))  # MATCH | NO_MATCH | UNAVAILABLE | ERROR
    verification_reference: Mapped[Optional[str]] = mapped_column(String(80))
    consent_given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_development: Mapped[bool] = mapped_column(Boolean, default=False)
    # Single-use: bound to at most one ticket
    consumed_by_ticket_id: Mapped[Optional[str]] = mapped_column(String(32))
    match_score: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Ticket(Base):
    __tablename__ = "access_tickets"
    __table_args__ = (
        # The same purchase attempt (idempotency key) can only ever create one ticket per user
        Index("uq_access_tickets_idempotency", "user_id", "idempotency_key", unique=True, postgresql_where=text("idempotency_key IS NOT NULL")),
        Index("ix_access_tickets_trip_status", "trip_id", "status"),  # live trip stats
        Index("ix_access_tickets_status_issued", "status", "issued_at"),  # today's passengers / revenue
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    reference: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id"), index=True)
    route: Mapped[str] = mapped_column(String(40))
    direction: Mapped[Optional[int]] = mapped_column(Integer)
    from_stop_id: Mapped[str] = mapped_column(String(40))
    from_stop: Mapped[str] = mapped_column(String(200))
    to_stop_id: Mapped[str] = mapped_column(String(40))
    to_stop: Mapped[str] = mapped_column(String(200))
    passenger_count: Mapped[int] = mapped_column(Integer, default=1)
    normal_fare: Mapped[int] = mapped_column(Integer)
    fare: Mapped[int] = mapped_column(Integer)
    fare_source: Mapped[str] = mapped_column(String(40))
    ticket_type: Mapped[str] = mapped_column(String(20))  # PAID | ELIGIBLE_FREE
    eligibility_type: Mapped[Optional[str]] = mapped_column(String(40))
    eligibility_rule_id: Mapped[Optional[str]] = mapped_column(String(60))
    verification_reference: Mapped[Optional[str]] = mapped_column(String(80))
    payment_status: Mapped[str] = mapped_column(String(20))  # NOT_REQUIRED | PENDING | PAID_DEMO
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus, name="access_ticket_status"))
    vehicle_number: Mapped[Optional[str]] = mapped_column(String(20))
    # BMTC stage fare: ADULT | CHILD | SENIOR, journey distance along the route and the chargeable stage
    fare_category: Mapped[str] = mapped_column(String(10), default="ADULT", server_default="ADULT")
    # Realtime trip ticketing: the trip/bus the ticket belongs to, who issued it (conductor for cash tickets),
    # an idempotency key so repeated taps never create a second ticket, and the payment order / reference
    trip_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_trips.id"), index=True)
    bus_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_buses.id"))
    issued_by: Mapped[Optional[str]] = mapped_column(String(32))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64))
    payment_provider: Mapped[Optional[str]] = mapped_column(String(20))
    payment_order_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(64))
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    distance_km: Mapped[Optional[float]] = mapped_column(Float)
    fare_stage: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class TicketVerification(Base):
    __tablename__ = "access_ticket_verifications"
    __table_args__ = (Index("ix_access_ticket_verifications_conductor_created", "conductor_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    ticket_id: Mapped[Optional[str]] = mapped_column(ForeignKey("access_tickets.id"), index=True)
    conductor_id: Mapped[str] = mapped_column(ForeignKey("access_users.id"), index=True)
    result: Mapped[str] = mapped_column(String(30))  # VALID | INVALID | EXPIRED | ALREADY_USED | ...
    detail: Mapped[Optional[str]] = mapped_column(Text)
    route: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "access_audit_logs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(40))
    target_id: Mapped[Optional[str]] = mapped_column(String(64))
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    result: Mapped[Optional[str]] = mapped_column(String(20))  # SUCCESS | FAILURE | DENIED
    user_agent: Mapped[Optional[str]] = mapped_column(String(200))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Feedback(Base):
    """'Report a problem' submissions. Free text only; users are told not to include personal documents."""

    __tablename__ = "access_feedback"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    screen: Mapped[Optional[str]] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


Index("ix_access_tickets_created", Ticket.created_at)


class Notification(Base):
    """In-app notification for one user. `dedupe_key` stops the same event notifying twice (e.g. one
    'pass expires in 7 days' per pass, one 'bus is full' per trip)."""

    __tablename__ = "access_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_access_notifications_dedupe"),
        Index("ix_access_notifications_user_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("access_users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # TICKET_ISSUED | PASS_APPROVED | PASS_REJECTED | PASS_EXPIRING | BUS_FULL | ...
    title: Mapped[str] = mapped_column(String(140))
    body: Mapped[str] = mapped_column(String(400))
    data: Mapped[Optional[dict]] = mapped_column(JSON)  # only ids for navigation, never personal data
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
