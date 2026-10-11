"""
Configuration for the Access module. Every secret comes from the environment; development fallbacks are
flagged by `using_dev_secrets` and refused when ACCESS_ENV=production.
"""

import base64
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


DEV_JWT_SECRET = "dev-only-access-jwt-secret-change-me"
DEV_TICKET_SECRET = "dev-only-access-ticket-signing-secret-change-me"
DEV_ENCRYPTION_SEED = "dev-only-access-encryption-seed-change-me"


@dataclass
class AccessSettings:
    env: str = field(default_factory=lambda: _env("ACCESS_ENV", "development"))
    database_url: str = field(default_factory=lambda: _env("ACCESS_DATABASE_URL"))

    jwt_secret: str = field(default_factory=lambda: _env("ACCESS_JWT_SECRET", DEV_JWT_SECRET))
    ticket_signing_secret: str = field(default_factory=lambda: _env("ACCESS_TICKET_SIGNING_SECRET", DEV_TICKET_SECRET))
    # Fernet key (urlsafe base64, 32 bytes). Used for documents at rest and TOTP secrets.
    encryption_key: str = field(default_factory=lambda: _env("ACCESS_ENCRYPTION_KEY"))

    access_token_ttl_seconds: int = field(default_factory=lambda: int(_env("ACCESS_TOKEN_TTL_SECONDS", "900")))
    refresh_token_ttl_seconds: int = field(default_factory=lambda: int(_env("ACCESS_REFRESH_TTL_SECONDS", str(14 * 86400))))
    cookie_secure: bool = field(default_factory=lambda: _env("ACCESS_COOKIE_SECURE", "false").lower() == "true")

    # Verification adapters: mock (development, clearly labelled) | digilocker / authorized | unavailable
    identity_provider: str = field(default_factory=lambda: _env("IDENTITY_PROVIDER", "mock").lower())
    biometric_provider: str = field(default_factory=lambda: _env("BIOMETRIC_PROVIDER", "mock").lower())
    otp_provider: str = field(default_factory=lambda: _env("OTP_PROVIDER", "mock").lower())

    # Official DigiLocker partner credentials (never committed). Without them the adapter is UNAVAILABLE.
    digilocker_client_id: str = field(default_factory=lambda: _env("DIGILOCKER_CLIENT_ID"))
    digilocker_client_secret: str = field(default_factory=lambda: _env("DIGILOCKER_CLIENT_SECRET"))
    digilocker_redirect_uri: str = field(default_factory=lambda: _env("DIGILOCKER_REDIRECT_URI"))

    identity_verification_valid_days: int = field(default_factory=lambda: int(_env("IDENTITY_VERIFICATION_VALID_DAYS", "365")))
    # Biometric audit rows (result only, never images) are deleted after this many days
    biometric_audit_retention_days: int = field(default_factory=lambda: int(_env("BIOMETRIC_AUDIT_RETENTION_DAYS", "30")))

    # UIDAI Aadhaar Paperless Offline e-KYC: PEM/DER public certificate published by UIDAI (used to check the
    # XML signature). Without it no e-KYC can be marked VERIFIED.
    uidai_cert_path: str = field(default_factory=lambda: _env("ACCESS_UIDAI_CERT_PATH"))
    # Root certificates trusted for UIDAI's e-Aadhaar PDF signature chain (e.g. CCA India root). Empty → PDF route off.
    trusted_ca_dir: str = field(default_factory=lambda: _env("ACCESS_TRUSTED_CA_DIR", str(Path(__file__).resolve().parents[2] / "certs" / "trusted")))
    ekyc_max_age_hours: int = field(default_factory=lambda: int(_env("ACCESS_EKYC_MAX_AGE_HOURS", "72")))
    # Local face matching (OpenCV YuNet detector + SFace recognizer ONNX models)
    face_model_dir: str = field(default_factory=lambda: _env("ACCESS_FACE_MODEL_DIR", str(Path(__file__).resolve().parents[2] / "models" / "face")))
    face_match_threshold: float = field(default_factory=lambda: float(_env("ACCESS_FACE_MATCH_THRESHOLD", "0.363")))

    # Eligibility policy (JSON file). Default: backend/app/access/eligibility_policy.json
    eligibility_policy_path: str = field(
        default_factory=lambda: _env("ELIGIBILITY_POLICY_PATH", str(Path(__file__).with_name("eligibility_policy.json")))
    )

    # Private document storage (outside any web root). Files are encrypted at rest.
    upload_dir: str = field(
        default_factory=lambda: _env("ACCESS_UPLOAD_DIR", str(Path(__file__).resolve().parents[2] / "private_uploads"))
    )
    max_upload_bytes: int = field(default_factory=lambda: int(_env("ACCESS_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))))
    document_url_ttl_seconds: int = field(default_factory=lambda: int(_env("ACCESS_DOCUMENT_URL_TTL_SECONDS", "300")))

    # Sign-in: after the password, a one-time code is emailed (skipped for accounts with TOTP two-factor)
    login_email_code: bool = field(default_factory=lambda: _env("ACCESS_LOGIN_EMAIL_CODE", "true").lower() == "true")
    email_code_ttl_minutes: int = field(default_factory=lambda: int(_env("ACCESS_EMAIL_CODE_TTL_MINUTES", "10")))

    # Outgoing email (SMTP) for sign-in codes. Used when OTP_PROVIDER=email.
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "587")))
    smtp_username: str = field(default_factory=lambda: _env("SMTP_USERNAME"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM"))
    smtp_security: str = field(default_factory=lambda: _env("SMTP_SECURITY", "starttls").lower())  # starttls | ssl | none

    ticket_validity_minutes: int = field(default_factory=lambda: int(_env("ACCESS_TICKET_VALIDITY_MINUTES", "120")))
    login_rate_limit_per_minute: int = field(default_factory=lambda: int(_env("ACCESS_LOGIN_RATE_LIMIT", "10")))

    # Ticket payments: "test" (development, no money moves, clearly labelled) | "razorpay" (needs merchant keys).
    # The key secret stays on the server; only the public key id is ever sent to the app.
    payment_provider: str = field(default_factory=lambda: _env("PAYMENT_PROVIDER", "test").lower())
    razorpay_key_id: str = field(default_factory=lambda: _env("RAZORPAY_KEY_ID"))
    razorpay_key_secret: str = field(default_factory=lambda: _env("RAZORPAY_KEY_SECRET"))
    razorpay_webhook_secret: str = field(default_factory=lambda: _env("RAZORPAY_WEBHOOK_SECRET"))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def using_dev_secrets(self) -> bool:
        return (
            self.jwt_secret == DEV_JWT_SECRET
            or self.ticket_signing_secret == DEV_TICKET_SECRET
            or not self.encryption_key
        )

    @property
    def fernet_key(self) -> bytes:
        if self.encryption_key:
            return self.encryption_key.encode()
        # Development only: deterministic key so encrypted dev uploads stay readable across restarts
        return base64.urlsafe_b64encode(hashlib.sha256(DEV_ENCRYPTION_SEED.encode()).digest())

    def validate(self) -> None:
        if self.is_production:
            if self.using_dev_secrets:
                raise RuntimeError(
                    "Access module: set ACCESS_JWT_SECRET, ACCESS_TICKET_SIGNING_SECRET and ACCESS_ENCRYPTION_KEY in production"
                )
            if self.identity_provider == "mock" or self.biometric_provider == "mock" or self.otp_provider == "mock":
                raise RuntimeError("Access module: mock verification/OTP providers are not allowed in production")
            if self.payment_provider == "test":
                raise RuntimeError("Access module: the test payment provider is not allowed in production")


settings = AccessSettings()
