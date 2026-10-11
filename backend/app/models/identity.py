"""
Identity verification models for demo women's fare-concession (Shakti scheme prototype).

SAFETY & PRIVACY CONSTRAINTS:
- ZERO storage of raw Aadhaar numbers or document images.
- ZERO storage of facial biometrics, selfies, or embedding vectors.
- Strict masking (e.g. XXXX XXXX 1234) for any user presentation.
- Fully simulated identity verification provider interface.
"""

from datetime import datetime, timezone
from typing import Optional, Literal
from pydantic import BaseModel, Field


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IdentitySessionCreate(BaseModel):
    user_id: Optional[str] = "USER-COMMUTER-1"
    passenger_type: Literal["female", "male"] = "female"
    concession_type: Literal["karnataka_women_shakti", "senior_citizen", "student", "none"] = "karnataka_women_shakti"
    consent_obtained: bool = Field(..., description="User explicit consent must be granted")


class IdentitySessionResponse(BaseModel):
    session_id: str
    user_id: str
    passenger_type: str
    concession_type: str
    status: Literal["SESSION_CREATED", "DOCUMENT_PENDING", "DOCUMENT_DEMO_VERIFIED", "SELFIE_PENDING", "MATCHED", "MISMATCHED", "VERIFICATION_UNAVAILABLE"]
    disclaimer: str = "PROTOTYPE DEMO: Simulated verification only. No real UIDAI Aadhaar authentication is performed."
    created_at: datetime = Field(default_factory=_get_utc_now)


class DocumentVerifyRequest(BaseModel):
    session_id: str
    document_type: Literal["aadhaar_card", "voter_id", "ration_card"] = "aadhaar_card"
    last_four_digits: str = Field(default="1234", min_length=4, max_length=4)
    has_photo_present: bool = True
    user_consent: bool = True


class SelfieVerifyRequest(BaseModel):
    session_id: str
    client_timestamp: Optional[datetime] = None
    liveness_confirmed: bool = True


class IdentityVerifyResponse(BaseModel):
    session_id: str
    status: Literal["MATCH", "MISMATCH", "VERIFICATION_UNAVAILABLE"]
    verified: bool
    eligibility_status: Literal["ELIGIBLE", "INELIGIBLE", "RETRY_REQUIRED", "PENDING"]
    fare_discount_percentage: int = 100
    masked_id_preview: str = "XXXX XXXX 1234"
    message: str
    disclaimer: str = "DEMO SIMULATION: Identity verification simulated for hackathon evaluation."
    timestamp: datetime = Field(default_factory=_get_utc_now)


class IdentityStatusResponse(BaseModel):
    session_id: str
    user_id: str
    status: str
    is_eligible_for_concession: bool
    concession_scheme: str
    masked_id_preview: str
    disclaimer: str
    last_updated: datetime = Field(default_factory=_get_utc_now)


class DemoOverrideRequest(BaseModel):
    mode: Literal["MATCH", "MISMATCH", "VERIFICATION_UNAVAILABLE"]
