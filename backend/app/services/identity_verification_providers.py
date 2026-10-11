"""
Phase 41: Government identity-verification provider abstractions.

These are INTERFACES plus safe implementations. No government integration is connected:

- UNAVAILABLE (default): every verification reports "Identity verification is currently unavailable."
- DEMO_VERIFICATION: evaluator-controlled development provider. Results are always labelled
  "DEMO IDENTITY VERIFICATION" and never presented as Aadhaar / DigiLocker verification.
- AUTHORIZED_VERIFICATION: adapter slot for a future authorized provider. It is only selected when
  credentials are configured via environment variables, and until the adapter is actually written it
  reports UNAVAILABLE rather than fabricating a result.

Note: `identity_provider.IdentityVerificationProvider` is the older Phase 22 session-based demo used by
the legacy /identity/* endpoints. It is kept unchanged; this module backs the Phase 41 account flow.

PRIVACY: providers never receive or retain images, embeddings, document numbers or XML. The
"temporary capture" tracked here is only a liveness-confirmation flag keyed by attempt ID, and it is
cleared after every verification.
"""

import logging
import os
import secrets
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlencode

logger = logging.getLogger("nammablr.identity_verification")

DEFAULT_LIVENESS_ACTIONS = ["LOOK_AT_CAMERA", "BLINK_ONCE"]


@dataclass
class FaceVerificationAttempt:
    attempt_id: str
    user_id: str
    created_at: datetime
    liveness_action_completed: bool = False


@dataclass
class ProviderVerificationResult:
    outcome: str  # MATCH | NO_MATCH | UNAVAILABLE | VERIFICATION_ERROR
    masked_identity_suffix: Optional[str] = None
    shakti_eligible: Optional[bool] = None
    detail: str = ""


# ---------------------------------------------------------------------------
# DigiLocker
# ---------------------------------------------------------------------------

class DigiLockerProvider(ABC):
    """Authorization-code flow against DigiLocker. The app never sees DigiLocker credentials."""

    mode: str = "UNAVAILABLE"

    @property
    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def start_authorization(self, user_id: str) -> Optional[str]:
        """Returns the authorization URL the commuter opens in the system browser, or None if unavailable."""


class UnconfiguredDigiLockerProvider(DigiLockerProvider):
    mode = "UNAVAILABLE"

    @property
    def is_configured(self) -> bool:
        return False

    def start_authorization(self, user_id: str) -> Optional[str]:
        return None


class AuthorizedDigiLockerProvider(DigiLockerProvider):
    """
    Builds the authorization URL from environment configuration. Token exchange / document fetch is
    intentionally not implemented until an authorized partner integration exists, so an account is
    never reported as LINKED by this code.
    """

    mode = "AUTHORIZED_VERIFICATION"

    def __init__(self, authorize_url: str, client_id: str, redirect_uri: str):
        self._authorize_url = authorize_url
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._pending_states: Dict[str, str] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self._authorize_url and self._client_id and self._redirect_uri)

    def start_authorization(self, user_id: str) -> Optional[str]:
        if not self.is_configured:
            return None
        state = secrets.token_urlsafe(16)
        self._pending_states[state] = user_id
        query = urlencode({
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "state": state,
        })
        return f"{self._authorize_url}?{query}"


# ---------------------------------------------------------------------------
# Face / liveness verification
# ---------------------------------------------------------------------------

class FaceVerificationProvider(ABC):
    """
    startVerification -> captureLivenessFrame -> verify -> clearTemporaryCapture.

    Implementations MUST NOT compute face embeddings or run home-grown face matching. Comparison
    against the authorized reference happens only inside an authorized provider.
    """

    mode: str = "UNAVAILABLE"

    def __init__(self):
        self._attempts: Dict[str, FaceVerificationAttempt] = {}

    @property
    @abstractmethod
    def is_available(self) -> bool: ...

    def start_verification(self, user_id: str) -> Optional[FaceVerificationAttempt]:
        if not self.is_available:
            return None
        attempt = FaceVerificationAttempt(
            attempt_id=f"IDV-{uuid.uuid4().hex[:12].upper()}",
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
        self._attempts[attempt.attempt_id] = attempt
        return attempt

    def get_attempt(self, attempt_id: str) -> Optional[FaceVerificationAttempt]:
        return self._attempts.get(attempt_id)

    def capture_liveness_frame(self, attempt_id: str, liveness_action_completed: bool) -> bool:
        """Records that the commuter performed the liveness action. No frame data is accepted here."""
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            return False
        attempt.liveness_action_completed = bool(liveness_action_completed)
        return True

    @abstractmethod
    def verify(self, attempt_id: str) -> ProviderVerificationResult: ...

    def clear_temporary_capture(self, attempt_id: str) -> bool:
        return self._attempts.pop(attempt_id, None) is not None

    def pending_capture_count(self) -> int:
        return len(self._attempts)

    def clear_all(self) -> None:
        self._attempts.clear()


class UnavailableFaceVerificationProvider(FaceVerificationProvider):
    mode = "UNAVAILABLE"

    @property
    def is_available(self) -> bool:
        return False

    def verify(self, attempt_id: str) -> ProviderVerificationResult:
        return ProviderVerificationResult(outcome="UNAVAILABLE", detail="No identity verification provider is configured.")


class DemoFaceVerificationProvider(FaceVerificationProvider):
    """Evaluator-controlled development provider. Performs no face comparison of any kind."""

    mode = "DEMO_VERIFICATION"

    def __init__(self, demo_outcome: str = "MATCH"):
        super().__init__()
        self.demo_outcome = demo_outcome

    @property
    def is_available(self) -> bool:
        return True

    def verify(self, attempt_id: str) -> ProviderVerificationResult:
        attempt = self._attempts.get(attempt_id)
        if attempt is None:
            return ProviderVerificationResult(outcome="VERIFICATION_ERROR", detail="Verification attempt not found or expired.")
        if not attempt.liveness_action_completed:
            return ProviderVerificationResult(outcome="VERIFICATION_ERROR", detail="Liveness action was not completed.")
        if self.demo_outcome == "NO_MATCH":
            return ProviderVerificationResult(outcome="NO_MATCH", detail="Demo evaluator outcome: no match.")
        # No real identity is involved, so no masked identifier is produced.
        return ProviderVerificationResult(outcome="MATCH", shakti_eligible=True, detail="Demo evaluator outcome: match.")


class AuthorizedFaceVerificationProvider(FaceVerificationProvider):
    """
    Slot for an authorized verification partner (e.g. a DigiLocker / UIDAI-approved face-authentication
    service). The network adapter is not implemented yet, so verify() reports UNAVAILABLE rather than
    inventing a result. When implemented, the live frame must be streamed to the provider and discarded,
    and only {outcome, masked suffix, eligibility attribute} may be returned.
    """

    mode = "AUTHORIZED_VERIFICATION"

    def __init__(self, base_url: str, api_key: str):
        super().__init__()
        self._base_url = base_url
        self._api_key = api_key

    @property
    def is_available(self) -> bool:
        return bool(self._base_url and self._api_key)

    def verify(self, attempt_id: str) -> ProviderVerificationResult:
        return ProviderVerificationResult(
            outcome="UNAVAILABLE",
            detail="Authorized identity provider adapter is not implemented in this build.",
        )


# ---------------------------------------------------------------------------
# Composite provider
# ---------------------------------------------------------------------------

class IdentityVerificationProvider(ABC):
    """Groups the DigiLocker and face-verification capabilities under a single provider mode."""

    mode: str = "UNAVAILABLE"
    digilocker: DigiLockerProvider
    face: FaceVerificationProvider

    @property
    def is_available(self) -> bool:
        return self.face.is_available


class UnavailableIdentityVerificationProvider(IdentityVerificationProvider):
    mode = "UNAVAILABLE"

    def __init__(self):
        self.digilocker = UnconfiguredDigiLockerProvider()
        self.face = UnavailableFaceVerificationProvider()


class DemoIdentityVerificationProvider(IdentityVerificationProvider):
    """Development/evaluator provider. DigiLocker stays unavailable: demo mode never fakes a DigiLocker link."""

    mode = "DEMO_VERIFICATION"

    def __init__(self, demo_outcome: str = "MATCH"):
        self.digilocker = UnconfiguredDigiLockerProvider()
        self.face = DemoFaceVerificationProvider(demo_outcome)


class AuthorizedIdentityVerificationProvider(IdentityVerificationProvider):
    mode = "AUTHORIZED_VERIFICATION"

    def __init__(self, digilocker: DigiLockerProvider, face: FaceVerificationProvider):
        self.digilocker = digilocker
        self.face = face


def build_identity_provider_from_env() -> IdentityVerificationProvider:
    """
    IDENTITY_VERIFICATION_MODE = unavailable (default) | demo | authorized

    'authorized' requires IDENTITY_PROVIDER_BASE_URL and IDENTITY_PROVIDER_API_KEY; otherwise it falls
    back to UNAVAILABLE. 'demo' is refused in production environments.
    """
    mode = os.getenv("IDENTITY_VERIFICATION_MODE", "unavailable").strip().lower()
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()

    if mode == "authorized":
        base_url = os.getenv("IDENTITY_PROVIDER_BASE_URL", "")
        api_key = os.getenv("IDENTITY_PROVIDER_API_KEY", "")
        face = AuthorizedFaceVerificationProvider(base_url, api_key)
        digilocker = AuthorizedDigiLockerProvider(
            os.getenv("DIGILOCKER_AUTHORIZE_URL", ""),
            os.getenv("DIGILOCKER_CLIENT_ID", ""),
            os.getenv("DIGILOCKER_REDIRECT_URI", ""),
        )
        if face.is_available:
            return AuthorizedIdentityVerificationProvider(digilocker, face)
        logger.warning("[IDENTITY] IDENTITY_VERIFICATION_MODE=authorized but provider credentials are missing; verification unavailable.")
        return UnavailableIdentityVerificationProvider()

    if mode == "demo":
        if environment == "production":
            logger.warning("[IDENTITY] Demo identity verification is not permitted in production; verification unavailable.")
            return UnavailableIdentityVerificationProvider()
        return DemoIdentityVerificationProvider()

    return UnavailableIdentityVerificationProvider()
