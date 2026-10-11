"""
Identity verification provider interface and demo implementation for women's fare concession.

SAFETY & PRIVACY CONSTRAINTS:
- Abstract protocol / base class for seamless swapping with an authorized UIDAI or Digilocker SDK.
- Demo provider supports simulated states: MATCH, MISMATCH, VERIFICATION_UNAVAILABLE.
- Strictly NO raw PII, Aadhaar numbers, biometric vectors, or face images stored.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Optional, Literal

from ..models.identity import (
    IdentitySessionCreate,
    IdentitySessionResponse,
    DocumentVerifyRequest,
    SelfieVerifyRequest,
    IdentityVerifyResponse,
    IdentityStatusResponse,
)

logger = logging.getLogger("nammamove.identity_provider")


class IdentityVerificationProvider(ABC):
    """Abstract provider for identity & concession verification."""

    @abstractmethod
    def create_session(self, req: IdentitySessionCreate) -> IdentitySessionResponse:
        pass

    @abstractmethod
    def verify_document(self, req: DocumentVerifyRequest) -> IdentityStatusResponse:
        pass

    @abstractmethod
    def register_selfie_liveness(self, req: SelfieVerifyRequest) -> IdentityStatusResponse:
        pass

    @abstractmethod
    def execute_verification(self, session_id: str) -> IdentityVerifyResponse:
        pass

    @abstractmethod
    def get_status(self, session_id: str) -> Optional[IdentityStatusResponse]:
        pass

    @abstractmethod
    def set_demo_override(self, mode: Literal["MATCH", "MISMATCH", "VERIFICATION_UNAVAILABLE"]) -> str:
        pass


class DemoIdentityVerificationProvider(IdentityVerificationProvider):
    """
    Simulated implementation for hackathon demonstration.
    Features:
    - Zero raw biometric / document storage.
    - Controllable outcome for judge evaluation (MATCH, MISMATCH, UNAVAILABLE).
    - Clear disclaimers and masking.
    """

    def __init__(self):
        self._sessions: Dict[str, Dict] = {}
        self._demo_override_mode: Literal["MATCH", "MISMATCH", "VERIFICATION_UNAVAILABLE"] = "MATCH"
        self._seed_demo_session()

    def _seed_demo_session(self):
        """Pre-seed verified session for instant commuter demo."""
        demo_session_id = "DEMO-SHAKTI-SESSION-001"
        self._sessions[demo_session_id] = {
            "session_id": demo_session_id,
            "user_id": "USER-DEMO-FEMALE-01",
            "passenger_type": "female",
            "concession_type": "karnataka_women_shakti",
            "status": "MATCHED",
            "document_verified": True,
            "selfie_verified": True,
            "is_eligible": True,
            "masked_id": "XXXX XXXX 4821",
            "last_updated": datetime.now(timezone.utc),
        }

    def create_session(self, req: IdentitySessionCreate) -> IdentitySessionResponse:
        if not req.consent_obtained:
            raise ValueError("Commuter consent is mandatory for simulated identity verification.")

        session_id = f"ID-SESS-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)

        self._sessions[session_id] = {
            "session_id": session_id,
            "user_id": req.user_id or "USER-COMMUTER-1",
            "passenger_type": req.passenger_type,
            "concession_type": req.concession_type,
            "status": "DOCUMENT_PENDING",
            "document_verified": False,
            "selfie_verified": False,
            "is_eligible": False,
            "masked_id": "XXXX XXXX 1234",
            "last_updated": now,
        }

        logger.info("Created simulated identity session: %s", session_id)
        return IdentitySessionResponse(
            session_id=session_id,
            user_id=req.user_id or "USER-COMMUTER-1",
            passenger_type=req.passenger_type,
            concession_type=req.concession_type,
            status="DOCUMENT_PENDING",
            created_at=now,
        )

    def verify_document(self, req: DocumentVerifyRequest) -> IdentityStatusResponse:
        sess = self._sessions.get(req.session_id)
        if not sess:
            raise KeyError(f"Identity session {req.session_id} not found.")

        if not req.user_consent:
            raise ValueError("Commuter consent must be confirmed.")

        # Sanitized last 4 digits only
        clean_last4 = req.last_four_digits.strip()[-4:]
        sess["masked_id"] = f"XXXX XXXX {clean_last4}"
        sess["document_verified"] = True
        sess["status"] = "DOCUMENT_DEMO_VERIFIED"
        sess["last_updated"] = datetime.now(timezone.utc)

        logger.info("Simulated document validated for session: %s (Masked: %s)", req.session_id, sess["masked_id"])
        return self._build_status_response(sess)

    def register_selfie_liveness(self, req: SelfieVerifyRequest) -> IdentityStatusResponse:
        sess = self._sessions.get(req.session_id)
        if not sess:
            raise KeyError(f"Identity session {req.session_id} not found.")

        sess["selfie_verified"] = req.liveness_confirmed
        sess["status"] = "SELFIE_PENDING"
        sess["last_updated"] = datetime.now(timezone.utc)

        logger.info("Selfie liveness check registered for session: %s", req.session_id)
        return self._build_status_response(sess)

    def execute_verification(self, session_id: str) -> IdentityVerifyResponse:
        sess = self._sessions.get(session_id)
        if not sess:
            raise KeyError(f"Identity session {session_id} not found.")

        now = datetime.now(timezone.utc)

        # Check demo override mode
        if self._demo_override_mode == "VERIFICATION_UNAVAILABLE":
            sess["status"] = "VERIFICATION_UNAVAILABLE"
            sess["is_eligible"] = False
            sess["last_updated"] = now
            return IdentityVerifyResponse(
                session_id=session_id,
                status="VERIFICATION_UNAVAILABLE",
                verified=False,
                eligibility_status="RETRY_REQUIRED",
                masked_id_preview=sess.get("masked_id", "XXXX XXXX 1234"),
                message="Identity verification service temporarily unavailable. Please retry or continue at standard fare.",
                timestamp=now,
            )

        if self._demo_override_mode == "MISMATCH":
            sess["status"] = "MISMATCHED"
            sess["is_eligible"] = False
            sess["last_updated"] = now
            return IdentityVerifyResponse(
                session_id=session_id,
                status="MISMATCH",
                verified=False,
                eligibility_status="INELIGIBLE",
                masked_id_preview=sess.get("masked_id", "XXXX XXXX 1234"),
                message="Photo mismatch detected against Aadhaar profile. Verification failed.",
                timestamp=now,
            )

        # Successful MATCH case
        # Check if female passenger applying for Karnataka Shakti Scheme
        is_female = sess.get("passenger_type") == "female"
        is_shakti = sess.get("concession_type") == "karnataka_women_shakti"

        if is_female and is_shakti:
            sess["status"] = "MATCHED"
            sess["is_eligible"] = True
            sess["last_updated"] = now
            return IdentityVerifyResponse(
                session_id=session_id,
                status="MATCH",
                verified=True,
                eligibility_status="ELIGIBLE",
                fare_discount_percentage=100,
                masked_id_preview=sess.get("masked_id", "XXXX XXXX 1234"),
                message="Identity verified. Karnataka Women's Concession (Shakti Scheme) applied: 100% Demo Fare Waiver.",
                timestamp=now,
            )
        else:
            sess["status"] = "MATCHED"
            sess["is_eligible"] = False
            sess["last_updated"] = now
            return IdentityVerifyResponse(
                session_id=session_id,
                status="MATCH",
                verified=True,
                eligibility_status="INELIGIBLE",
                fare_discount_percentage=0,
                masked_id_preview=sess.get("masked_id", "XXXX XXXX 1234"),
                message="Identity verified. Concession criteria not applicable for this passenger category.",
                timestamp=now,
            )

    def get_status(self, session_id: str) -> Optional[IdentityStatusResponse]:
        sess = self._sessions.get(session_id)
        if not sess:
            return None
        return self._build_status_response(sess)

    def set_demo_override(self, mode: Literal["MATCH", "MISMATCH", "VERIFICATION_UNAVAILABLE"]) -> str:
        self._demo_override_mode = mode
        logger.info("Identity provider demo override set to: %s", mode)
        return f"Identity verification provider simulation override set to: {mode}"

    def get_session(self, session_id: str) -> Optional[Dict]:
        return self._sessions.get(session_id)

    def reset_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def reset_all_sessions(self):
        """Reset all sessions back to pre-seeded demo state."""
        self._sessions.clear()
        self._demo_override_mode = "MATCH"
        self._seed_demo_session()
        logger.info("Reset all identity sessions to pre-seeded state.")

    def _build_status_response(self, sess: Dict) -> IdentityStatusResponse:
        return IdentityStatusResponse(
            session_id=sess["session_id"],
            user_id=sess["user_id"],
            status=sess["status"],
            is_eligible_for_concession=sess.get("is_eligible", False),
            concession_scheme=sess.get("concession_type", "karnataka_women_shakti"),
            masked_id_preview=sess.get("masked_id", "XXXX XXXX 1234"),
            disclaimer="PROTOTYPE DEMO: Simulated identity verification only.",
            last_updated=sess.get("last_updated", datetime.now(timezone.utc)),
        )


# Global singleton instance
identity_service = DemoIdentityVerificationProvider()
