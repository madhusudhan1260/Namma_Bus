"""
Phase 41: Passwordless commuter authentication, identity onboarding and Shakti eligibility.

SECURITY & PRIVACY RULES:
- Passwordless. There is no password anywhere; login is an UNVERIFIED demo continuation until an
  email/OTP provider is configured, and the API says so explicitly.
- The raw mobile number is never stored: only an HMAC lookup key and a masked form ("+91 XXXXX X3210").
- Session tokens are stored as SHA-256 digests, never in plaintext.
- No Aadhaar numbers, document images, selfies, face embeddings or DigiLocker credentials are stored.
- Logs contain user IDs and outcomes only — never names, mobiles, emails or identity data.
- Account type SHAKTI_ONBOARDING records the onboarding path chosen, not gender.
"""

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from ..models.auth import (
    AuthResponse,
    DEMO_IDENTITY_LABEL,
    DIGILOCKER_EXPLANATION,
    DigiLockerStatusResponse,
    EMAIL_VERIFICATION_NOT_CONNECTED,
    IDENTITY_REQUIRED_MESSAGE,
    IDENTITY_UNAVAILABLE_MESSAGE,
    IdentityStatusDto,
    IdentityVerificationCompleteRequest,
    IdentityVerificationResult,
    IdentityVerificationStartRequest,
    IdentityVerificationStartResponse,
    LoginRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    ShaktiEligibilityResponse,
    UserSessionDto,
    mask_mobile,
)
from .identity_verification_providers import (
    DEFAULT_LIVENESS_ACTIONS,
    DemoIdentityVerificationProvider,
    IdentityVerificationProvider,
    ProviderVerificationResult,
    UnavailableIdentityVerificationProvider,
    build_identity_provider_from_env,
)
from ..core.config import settings
from .notification_service import notification_service
from .personalization_service import personalization_service

logger = logging.getLogger("nammablr.auth")

SESSION_TTL = timedelta(hours=24)
# A Shakti concession ticket requires an identity verification completed within this window.
VERIFICATION_FRESHNESS = timedelta(minutes=15)


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    """In-memory passwordless account and session store (demo scale)."""

    def __init__(self):
        secret = os.getenv("AUTH_IDENTIFIER_HASH_SECRET")
        self._identifier_key = secret.encode("utf-8") if secret else secrets.token_bytes(32)
        self._users: Dict[str, dict] = {}
        self._mobile_index: Dict[str, str] = {}
        self._sessions: Dict[str, dict] = {}

    # -- internals ---------------------------------------------------------

    def _mobile_key(self, mobile_10: str) -> str:
        return hmac.new(self._identifier_key, mobile_10.encode("utf-8"), hashlib.sha256).hexdigest()

    def _issue_session(self, user: dict) -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        self._sessions[_digest(token)] = {"user_id": user["user_id"], "created_at": now, "expires_at": now + SESSION_TTL}
        user["last_login_at"] = now
        return token

    def _auth_response(self, user: dict, token: str) -> AuthResponse:
        return AuthResponse(
            session_token=token,
            user=self.to_dto(user),
            authentication_assurance="UNVERIFIED_DEMO_CONTINUATION",
            email_verification_message=EMAIL_VERIFICATION_NOT_CONNECTED,
        )

    # -- public API --------------------------------------------------------

    def register(self, req: RegisterRequest) -> AuthResponse:
        key = self._mobile_key(req.mobile)
        if key in self._mobile_index:
            raise AuthError(409, "An account with this mobile number already exists. Please log in.")
        now = _now()
        user = {
            "user_id": f"USR-{uuid.uuid4().hex[:12].upper()}",
            "display_name": req.full_name,
            "masked_mobile": mask_mobile(req.mobile),
            "mobile_key": key,
            "email": req.email,
            "email_verification_status": "NOT_CONNECTED",
            "account_type": req.account_type,
            "identity_status": "NOT_STARTED",
            "verification_provider": "UNAVAILABLE",
            "masked_identity_suffix": None,
            "shakti_eligibility_status": "NOT_VERIFIED",
            "digilocker_status": "NOT_LINKED",
            "last_verified_at": None,
            "created_at": now,
            "last_login_at": now,
        }
        self._users[user["user_id"]] = user
        self._mobile_index[key] = user["user_id"]
        token = self._issue_session(user)
        logger.info("[AUTH] Registered account %s (type=%s)", user["user_id"], user["account_type"])
        return self._auth_response(user, token)

    def login(self, req: LoginRequest) -> AuthResponse:
        user_id = self._mobile_index.get(self._mobile_key(req.mobile))
        if not user_id:
            raise AuthError(404, "No account found for this mobile number. Please register first.")
        user = self._users[user_id]
        token = self._issue_session(user)
        logger.info("[AUTH] Login for account %s", user_id)
        return self._auth_response(user, token)

    def resolve(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        sess = self._sessions.get(_digest(token))
        if not sess:
            return None
        if _now() > sess["expires_at"]:
            self._sessions.pop(_digest(token), None)
            return None
        return self._users.get(sess["user_id"])

    def require(self, token: Optional[str]) -> dict:
        user = self.resolve(token)
        if user is None:
            raise AuthError(401, "Authentication required. Please log in again.")
        return user

    def logout(self, token: Optional[str]) -> bool:
        if not token:
            return False
        return self._sessions.pop(_digest(token), None) is not None

    def update_profile(self, user: dict, req: ProfileUpdateRequest) -> UserSessionDto:
        if req.full_name is not None:
            user["display_name"] = req.full_name
        if req.email is not None and req.email != user["email"]:
            user["email"] = req.email
            user["email_verification_status"] = "NOT_CONNECTED"
        logger.info("[AUTH] Profile updated for account %s", user["user_id"])
        return self.to_dto(user)

    def session_expiry(self, token: Optional[str]):
        sess = self._sessions.get(_digest(token)) if token else None
        return sess["expires_at"] if sess else None

    def to_dto(self, user: dict) -> UserSessionDto:
        return UserSessionDto(
            user_id=user["user_id"],
            display_name=user["display_name"],
            masked_mobile=user["masked_mobile"],
            email=user["email"],
            email_verification_status=user["email_verification_status"],
            account_type=user["account_type"],
            identity_status=user["identity_status"],
            verification_provider=user["verification_provider"],
            masked_identity_suffix=user["masked_identity_suffix"],
            shakti_eligibility_status=user["shakti_eligibility_status"],
            digilocker_status=user["digilocker_status"],
            created_at=user["created_at"],
            last_login_at=user["last_login_at"],
        )

    def stored_records(self) -> Dict[str, dict]:
        """Diagnostic/test access to raw stored records (used to prove no sensitive data is retained)."""
        return self._users

    def session_count(self) -> int:
        return len(self._sessions)

    def reset(self):
        self._users.clear()
        self._mobile_index.clear()
        self._sessions.clear()


class IdentityOnboardingService:
    """Coordinates DigiLocker, face/liveness verification and Shakti eligibility for an account."""

    def __init__(self):
        self.provider: IdentityVerificationProvider = build_identity_provider_from_env()

    # -- evaluator controls ------------------------------------------------

    def set_demo_mode(self, enabled: bool, demo_outcome: str = "MATCH") -> IdentityVerificationProvider:
        if settings.environment == "production":
            raise AuthError(403, "Demo identity verification cannot be enabled in production.")
        self.provider.face.clear_all()
        if enabled:
            self.provider = DemoIdentityVerificationProvider(demo_outcome)
        else:
            self.provider = UnavailableIdentityVerificationProvider()
        logger.info("[IDENTITY] Evaluator set provider mode to %s", self.provider.mode)
        return self.provider

    def reset(self):
        self.provider.face.clear_all()
        self.provider = build_identity_provider_from_env()

    # -- helpers -----------------------------------------------------------

    def _label(self, mode: str) -> Optional[str]:
        return DEMO_IDENTITY_LABEL if mode == "DEMO_VERIFICATION" else None

    @staticmethod
    def _notify(event_type: str, title: str, message: str, severity: str = "INFO"):
        """Emits to the operational event stream and the in-app notification center."""
        notification_service.create_event(event_type=event_type, title=title, message=message, severity=severity)
        personalization_service.add_notification("SYSTEM", title, message, severity)

    def _set_eligibility(self, user: dict, new_status: str):
        old = user["shakti_eligibility_status"]
        if old == new_status:
            return
        user["shakti_eligibility_status"] = new_status
        self._notify(
            event_type="shakti_eligibility",
            title="Shakti eligibility updated",
            message=f"Shakti eligibility changed from {old.replace('_', ' ').title()} to {new_status.replace('_', ' ').title()}."
            + (f" ({DEMO_IDENTITY_LABEL})" if new_status == "DEMO_ELIGIBLE" else ""),
            severity="INFO",
        )

    def _is_verified(self, user: dict) -> bool:
        return user["identity_status"] in ("AUTHORIZED_VERIFIED", "DEMO_VERIFIED")

    def _is_fresh(self, user: dict) -> bool:
        ts = user.get("last_verified_at")
        return bool(ts and _now() - ts <= VERIFICATION_FRESHNESS)

    # -- DigiLocker --------------------------------------------------------

    def digilocker_start(self, user: dict) -> DigiLockerStatusResponse:
        dl = self.provider.digilocker
        url = dl.start_authorization(user["user_id"]) if dl.is_configured else None
        if url:
            user["digilocker_status"] = "PENDING_AUTHORIZATION"
            return DigiLockerStatusResponse(
                status="PENDING_AUTHORIZATION",
                provider_mode="AUTHORIZED_VERIFICATION",
                configured=True,
                authorization_url=url,
                message="Continue in DigiLocker to authorize sharing. NammaBlr never sees your DigiLocker password.",
            )
        user["digilocker_status"] = "UNAVAILABLE"
        return DigiLockerStatusResponse(
            status="UNAVAILABLE",
            provider_mode="UNAVAILABLE",
            configured=False,
            message="DigiLocker verification is not connected yet.",
        )

    def digilocker_status(self, user: dict) -> DigiLockerStatusResponse:
        dl = self.provider.digilocker
        return DigiLockerStatusResponse(
            status=user["digilocker_status"],
            provider_mode="AUTHORIZED_VERIFICATION" if dl.is_configured else "UNAVAILABLE",
            configured=dl.is_configured,
            message=(
                "DigiLocker verification is not connected yet."
                if not dl.is_configured
                else "DigiLocker authorization is configured."
            ),
            explanation=DIGILOCKER_EXPLANATION,
        )

    # -- Face / liveness verification ---------------------------------------

    def start_verification(self, user: dict, req: IdentityVerificationStartRequest) -> IdentityVerificationStartResponse:
        if not req.consent_confirmed:
            raise AuthError(400, "Consent is required before starting identity verification.")
        mode = self.provider.mode
        attempt = self.provider.face.start_verification(user["user_id"])
        if attempt is None:
            if not self._is_verified(user):
                user["identity_status"] = "UNAVAILABLE"
                user["verification_provider"] = "UNAVAILABLE"
                self._set_eligibility(user, "VERIFICATION_UNAVAILABLE")
            logger.info("[IDENTITY] Verification unavailable for account %s", user["user_id"])
            return IdentityVerificationStartResponse(
                provider_mode="UNAVAILABLE",
                available=False,
                message=IDENTITY_UNAVAILABLE_MESSAGE,
            )
        if not self._is_verified(user):
            user["identity_status"] = "IN_PROGRESS"
        logger.info("[IDENTITY] Verification attempt started for account %s (mode=%s)", user["user_id"], mode)
        return IdentityVerificationStartResponse(
            attempt_id=attempt.attempt_id,
            provider_mode=mode,
            available=True,
            liveness_actions=list(DEFAULT_LIVENESS_ACTIONS),
            message="Follow the on-screen liveness instructions.",
            label=self._label(mode),
        )

    def complete_verification(self, user: dict, req: IdentityVerificationCompleteRequest) -> IdentityVerificationResult:
        face = self.provider.face
        mode = self.provider.mode
        attempt = face.get_attempt(req.attempt_id)
        if attempt is None or attempt.user_id != user["user_id"]:
            raise AuthError(404, "Verification attempt not found or expired.")

        try:
            face.capture_liveness_frame(req.attempt_id, req.liveness_action_completed)
            result = face.verify(req.attempt_id)
        except Exception:  # never let a provider fault look like success
            logger.exception("[IDENTITY] Provider error for account %s", user["user_id"])
            result = ProviderVerificationResult(outcome="VERIFICATION_ERROR", detail="Verification provider error.")
        finally:
            cleared = face.clear_temporary_capture(req.attempt_id)

        now = _now()
        verified_at = None
        message = result.detail

        if result.outcome == "MATCH":
            verified_at = now
            user["last_verified_at"] = now
            user["verification_provider"] = mode
            if mode == "AUTHORIZED_VERIFICATION":
                user["identity_status"] = "AUTHORIZED_VERIFIED"
                user["masked_identity_suffix"] = result.masked_identity_suffix
                self._set_eligibility(user, "ELIGIBLE" if result.shakti_eligible else "NOT_ELIGIBLE")
                message = "Identity verified by the authorized provider."
            else:
                user["identity_status"] = "DEMO_VERIFIED"
                user["masked_identity_suffix"] = None
                self._set_eligibility(user, "DEMO_ELIGIBLE")
                message = f"{DEMO_IDENTITY_LABEL}: not a real Aadhaar or DigiLocker verification."
            self._notify(
                event_type="identity_verification",
                title="Identity verification completed",
                message=message,
                severity="INFO",
            )
        elif result.outcome == "UNAVAILABLE":
            if not self._is_verified(user):
                user["identity_status"] = "UNAVAILABLE"
                user["verification_provider"] = "UNAVAILABLE"
                self._set_eligibility(user, "VERIFICATION_UNAVAILABLE")
            message = IDENTITY_UNAVAILABLE_MESSAGE
        else:  # NO_MATCH | VERIFICATION_ERROR
            user["identity_status"] = "FAILED"
            user["last_verified_at"] = None
            self._set_eligibility(user, "NOT_VERIFIED")
            self._notify(
                event_type="identity_verification",
                title="Identity verification failed",
                message="Identity could not be verified. The Shakti concession was not applied.",
                severity="WARNING",
            )

        logger.info("[IDENTITY] Verification outcome for account %s: %s (mode=%s)", user["user_id"], result.outcome, mode)
        return IdentityVerificationResult(
            attempt_id=req.attempt_id,
            outcome=result.outcome,
            provider_mode=mode,
            identity_status=user["identity_status"],
            shakti_eligibility_status=user["shakti_eligibility_status"],
            masked_identity_suffix=user["masked_identity_suffix"],
            temporary_capture_cleared=cleared,
            message=message,
            label=self._label(mode) if result.outcome == "MATCH" else None,
            verified_at=verified_at,
        )

    def get_status(self, user: dict) -> IdentityStatusDto:
        provider_mode = self.provider.mode
        verified_by = user["verification_provider"] if self._is_verified(user) else provider_mode
        if user["identity_status"] == "DEMO_VERIFIED":
            message = f"{DEMO_IDENTITY_LABEL}: not a real Aadhaar or DigiLocker verification."
        elif user["identity_status"] == "AUTHORIZED_VERIFIED":
            message = "Identity verified by the authorized provider."
        elif not self.provider.is_available:
            message = IDENTITY_UNAVAILABLE_MESSAGE
        else:
            message = IDENTITY_REQUIRED_MESSAGE
        return IdentityStatusDto(
            identity_status=user["identity_status"],
            verification_provider=verified_by,
            provider_available=self.provider.is_available,
            masked_identity_suffix=user["masked_identity_suffix"],
            shakti_eligibility_status=user["shakti_eligibility_status"],
            digilocker_status=user["digilocker_status"],
            last_verified_at=user["last_verified_at"],
            label=self._label(verified_by),
            message=message,
        )

    # -- Shakti ------------------------------------------------------------

    def check_shakti_eligibility(self, user: dict) -> ShaktiEligibilityResponse:
        status = user["shakti_eligibility_status"]
        eligible = status in ("ELIGIBLE", "DEMO_ELIGIBLE")
        fresh = eligible and self._is_fresh(user)
        verified_by = user["verification_provider"] if self._is_verified(user) else self.provider.mode

        if fresh:
            message = (
                f"Shakti demo concession allowed ({DEMO_IDENTITY_LABEL})."
                if status == "DEMO_ELIGIBLE"
                else "Shakti concession allowed."
            )
        elif not self.provider.is_available:
            message = IDENTITY_UNAVAILABLE_MESSAGE
        else:
            message = IDENTITY_REQUIRED_MESSAGE

        return ShaktiEligibilityResponse(
            eligibility_status=status,
            concession_allowed=fresh,
            requires_verification=not fresh,
            verification_fresh=fresh,
            provider_mode=verified_by,
            label=self._label(verified_by),
            message=message,
        )


auth_service = AuthService()
identity_onboarding_service = IdentityOnboardingService()
