"""
Identity verification adapters.

IdentityProvider
  ├── MockIdentityProvider       IDENTITY_PROVIDER=mock (development only; every result is labelled
  │                              "DEVELOPMENT VERIFICATION — NOT REAL IDENTITY VERIFICATION")
  ├── DigiLockerIdentityProvider IDENTITY_PROVIDER=digilocker (needs official partner credentials)
  └── UnavailableIdentityProvider IDENTITY_PROVIDER=unavailable

Rules: the app never asks for or sees DigiLocker/Aadhaar credentials, never stores an Aadhaar number or
document, and only keeps an opaque verification reference plus the minimum attributes needed
(e.g. gender) for the configured eligibility policy.
"""

import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlencode

from ..config import settings

DEV_LABEL = "DEVELOPMENT VERIFICATION — NOT REAL IDENTITY VERIFICATION"


class IdentityProviderUnavailable(Exception):
    pass


@dataclass
class IdentityResult:
    status: str  # VERIFIED | FAILED | UNAVAILABLE
    reference: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)
    detail: str = ""


class IdentityProvider(ABC):
    name: str = "BASE"
    is_development: bool = False

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def authorization_url(self, state: str, api_base: str) -> str:
        """URL the user opens (after consent) to verify with the provider."""

    @abstractmethod
    def complete(self, code: str) -> IdentityResult:
        """Exchange the provider's authorization result for a verification outcome."""


class MockIdentityProvider(IdentityProvider):
    """Development stand-in. It does not verify anything and does not imitate DigiLocker's UI."""

    name = "MOCK_DEVELOPMENT"
    is_development = True
    OUTCOMES = {"mock-verified-female": ("VERIFIED", "F"), "mock-verified-male": ("VERIFIED", "M"), "mock-failed": ("FAILED", None)}

    def available(self) -> bool:
        return True

    def authorization_url(self, state: str, api_base: str) -> str:
        return f"{api_base}/identity/mock-consent?{urlencode({'state': state})}"

    def complete(self, code: str) -> IdentityResult:
        if code not in self.OUTCOMES:
            return IdentityResult(status="FAILED", detail="Unknown development outcome")
        status, gender = self.OUTCOMES[code]
        if status != "VERIFIED":
            return IdentityResult(status="FAILED", detail=f"{DEV_LABEL}: simulated failure")
        return IdentityResult(
            status="VERIFIED",
            reference=f"MOCKDEV-{secrets.token_hex(8).upper()}",
            attributes={"gender": gender},
            detail=DEV_LABEL,
        )


class DigiLockerIdentityProvider(IdentityProvider):
    """
    Slot for the official DigiLocker partner integration (OAuth 2.0 authorization-code flow).
    Endpoints are configured from the partner onboarding documents via DIGILOCKER_AUTHORIZE_URL /
    DIGILOCKER_TOKEN_URL, not guessed here. Until the attribute retrieval agreed in the partner contract is
    implemented, `complete` reports UNAVAILABLE instead of returning a result.
    """

    name = "DIGILOCKER"
    is_development = False

    def __init__(self) -> None:
        self.authorize_url = os.getenv("DIGILOCKER_AUTHORIZE_URL", "")
        self.token_url = os.getenv("DIGILOCKER_TOKEN_URL", "")

    def available(self) -> bool:
        return bool(
            settings.digilocker_client_id
            and settings.digilocker_client_secret
            and settings.digilocker_redirect_uri
            and self.authorize_url
            and self.token_url
        )

    def authorization_url(self, state: str, api_base: str) -> str:
        if not self.available():
            raise IdentityProviderUnavailable("DigiLocker credentials are not configured")
        query = {
            "response_type": "code",
            "client_id": settings.digilocker_client_id,
            "redirect_uri": settings.digilocker_redirect_uri,
            "state": state,
        }
        return f"{self.authorize_url}?{urlencode(query)}"

    def complete(self, code: str) -> IdentityResult:
        # Token exchange + attribute retrieval must follow the partner specification; not implemented yet.
        return IdentityResult(
            status="UNAVAILABLE",
            detail="DigiLocker attribute retrieval is not implemented yet; complete it per the partner agreement.",
        )


class UnavailableIdentityProvider(IdentityProvider):
    name = "UNAVAILABLE"

    def available(self) -> bool:
        return False

    def authorization_url(self, state: str, api_base: str) -> str:
        raise IdentityProviderUnavailable("Identity verification is temporarily unavailable.")

    def complete(self, code: str) -> IdentityResult:
        return IdentityResult(status="UNAVAILABLE", detail="Identity verification is temporarily unavailable.")


_override: Optional[IdentityProvider] = None


def get_identity_provider() -> IdentityProvider:
    if _override is not None:
        return _override
    kind = settings.identity_provider
    if kind == "mock":
        return MockIdentityProvider()
    if kind in ("digilocker", "authorized"):
        return DigiLockerIdentityProvider()
    return UnavailableIdentityProvider()


def set_identity_provider(provider: Optional[IdentityProvider]) -> None:
    """Test/integration hook."""
    global _override
    _override = provider
