"""
Phase 41: Commuter authentication, identity onboarding and Shakti eligibility models.

PRIVACY CONSTRAINTS (enforced by schema):
- Passwordless: no password fields exist anywhere in these models.
- No raw Aadhaar numbers, document images, QR images or XML.
- No face images, embeddings or biometric templates.
- Request models forbid unknown fields, so image/biometric payloads are rejected (422)
  instead of being silently accepted.
- The selected onboarding path (GENERAL / SHAKTI) is NOT a gender attribute and is never
  interpreted as one.
"""

import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Enumerations (string literals keep JSON contracts simple for the mobile client)
# ---------------------------------------------------------------------------

AccountType = Literal["GENERAL", "SHAKTI_ONBOARDING"]

# Which kind of provider produced (or would produce) an identity result.
VerificationProviderMode = Literal["AUTHORIZED_VERIFICATION", "DEMO_VERIFICATION", "UNAVAILABLE"]

# Account-level identity status.
IdentityStatus = Literal[
    "NOT_STARTED",
    "IN_PROGRESS",
    "AUTHORIZED_VERIFIED",
    "DEMO_VERIFIED",
    "FAILED",
    "UNAVAILABLE",
]

# Outcome of a single face / liveness verification attempt.
FaceVerificationOutcome = Literal["MATCH", "NO_MATCH", "UNAVAILABLE", "VERIFICATION_ERROR"]

ShaktiEligibilityStatus = Literal[
    "ELIGIBLE",                   # authorized provider confirmed eligibility
    "DEMO_ELIGIBLE",              # evaluator demo verification only — never real
    "NOT_VERIFIED",
    "VERIFICATION_UNAVAILABLE",
    "NOT_ELIGIBLE",
]

DigiLockerStatus = Literal["NOT_LINKED", "PENDING_AUTHORIZATION", "LINKED", "UNAVAILABLE"]

EmailVerificationStatus = Literal["NOT_CONNECTED", "PENDING", "VERIFIED"]

EMAIL_VERIFICATION_NOT_CONNECTED = "Email verification is not connected yet."
DEMO_IDENTITY_LABEL = "DEMO IDENTITY VERIFICATION"
IDENTITY_UNAVAILABLE_MESSAGE = "Identity verification is currently unavailable."
IDENTITY_REQUIRED_MESSAGE = "Identity verification required"
DIGILOCKER_EXPLANATION = (
    "DigiLocker verification will use an authorized government identity-verification flow when configured."
)

_INDIAN_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_NAME_RE = re.compile(r"^[^\d<>{}\[\]@#$%^*=_|\\/~`]+$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_indian_mobile(raw: str) -> str:
    """Normalizes '+91 98765 43210', '098765-43210' etc. to a bare 10-digit number or raises ValueError."""
    digits = re.sub(r"[\s\-()]", "", raw or "")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if not _INDIAN_MOBILE_RE.match(digits):
        raise ValueError("Enter a valid 10-digit Indian mobile number starting with 6, 7, 8 or 9.")
    return digits


def normalize_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    return email


def mask_mobile(mobile_10: str) -> str:
    return f"+91 XXXXX X{mobile_10[-4:]}"


# ---------------------------------------------------------------------------
# Auth requests / responses
# ---------------------------------------------------------------------------

class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(_StrictRequest):
    full_name: str = Field(..., min_length=2, max_length=80)
    mobile: str
    email: str
    account_type: AccountType = "GENERAL"

    @field_validator("full_name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        name = " ".join(v.split())
        if len(name) < 2 or not _NAME_RE.match(name):
            raise ValueError("Enter your full name using letters only.")
        return name

    @field_validator("mobile")
    @classmethod
    def _validate_mobile(cls, v: str) -> str:
        return normalize_indian_mobile(v)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        return normalize_email(v)


class LoginRequest(_StrictRequest):
    mobile: str

    @field_validator("mobile")
    @classmethod
    def _validate_mobile(cls, v: str) -> str:
        return normalize_indian_mobile(v)


class ProfileUpdateRequest(_StrictRequest):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    email: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def _validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        name = " ".join(v.split())
        if len(name) < 2 or not _NAME_RE.match(name):
            raise ValueError("Enter your full name using letters only.")
        return name

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else normalize_email(v)


class UserSessionDto(BaseModel):
    """Safe account view. Contains no raw mobile, no Aadhaar, no biometric data."""
    user_id: str
    display_name: str
    masked_mobile: str
    email: str
    email_verification_status: EmailVerificationStatus = "NOT_CONNECTED"
    account_type: AccountType
    identity_status: IdentityStatus = "NOT_STARTED"
    verification_provider: VerificationProviderMode = "UNAVAILABLE"
    masked_identity_suffix: Optional[str] = None
    shakti_eligibility_status: ShaktiEligibilityStatus = "NOT_VERIFIED"
    digilocker_status: DigiLockerStatus = "NOT_LINKED"
    created_at: datetime
    last_login_at: datetime
    session_expires_at: Optional[datetime] = None


class AuthResponse(BaseModel):
    session_token: str
    user: UserSessionDto
    authentication_assurance: Literal["UNVERIFIED_DEMO_CONTINUATION", "EMAIL_VERIFIED"] = "UNVERIFIED_DEMO_CONTINUATION"
    email_verification_message: str = EMAIL_VERIFICATION_NOT_CONNECTED


# ---------------------------------------------------------------------------
# DigiLocker
# ---------------------------------------------------------------------------

class DigiLockerStatusResponse(BaseModel):
    status: DigiLockerStatus
    provider_mode: VerificationProviderMode
    configured: bool
    authorization_url: Optional[str] = None
    message: str
    explanation: str = DIGILOCKER_EXPLANATION


# ---------------------------------------------------------------------------
# Identity / face verification
# ---------------------------------------------------------------------------

class IdentityVerificationStartRequest(_StrictRequest):
    purpose: Literal["SHAKTI_ONBOARDING", "SHAKTI_TICKET"] = "SHAKTI_ONBOARDING"
    consent_confirmed: bool = Field(..., description="Explicit commuter consent for temporary verification")


class IdentityVerificationStartResponse(BaseModel):
    attempt_id: Optional[str] = None
    provider_mode: VerificationProviderMode
    available: bool
    liveness_actions: list[str] = Field(default_factory=list)
    message: str
    label: Optional[str] = None


class IdentityVerificationCompleteRequest(_StrictRequest):
    """
    Carries only the liveness confirmation. There is deliberately NO field for image data,
    embeddings or document numbers; any such field is rejected by extra='forbid'.
    """
    attempt_id: str
    liveness_action_completed: bool = False


class IdentityVerificationResult(BaseModel):
    attempt_id: Optional[str] = None
    outcome: FaceVerificationOutcome
    provider_mode: VerificationProviderMode
    identity_status: IdentityStatus
    shakti_eligibility_status: ShaktiEligibilityStatus
    masked_identity_suffix: Optional[str] = None
    temporary_capture_cleared: bool = True
    message: str
    label: Optional[str] = None
    verified_at: Optional[datetime] = None


class IdentityStatusDto(BaseModel):
    identity_status: IdentityStatus
    verification_provider: VerificationProviderMode
    provider_available: bool
    masked_identity_suffix: Optional[str] = None
    shakti_eligibility_status: ShaktiEligibilityStatus
    digilocker_status: DigiLockerStatus
    last_verified_at: Optional[datetime] = None
    label: Optional[str] = None
    message: str


class IdentityDemoModeRequest(_StrictRequest):
    """Evaluator control: switch the development provider between UNAVAILABLE and DEMO_VERIFICATION."""
    enabled: bool
    demo_outcome: Literal["MATCH", "NO_MATCH"] = "MATCH"


# ---------------------------------------------------------------------------
# Shakti eligibility
# ---------------------------------------------------------------------------

class ShaktiEligibilityResponse(BaseModel):
    eligibility_status: ShaktiEligibilityStatus
    concession_allowed: bool
    requires_verification: bool
    verification_fresh: bool
    provider_mode: VerificationProviderMode
    label: Optional[str] = None
    message: str
    checked_at: datetime = Field(default_factory=_utc_now)
