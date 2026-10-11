"""Security primitives: password hashing, tokens, rate limiting, encryption, TOTP, ticket signatures."""

import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Optional, Tuple

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request

from .config import settings

# ---------------------------------------------------------------------------
# Passwords (scrypt, per-password salt, constant-time comparison)
# ---------------------------------------------------------------------------
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        # Burn comparable time so unknown accounts are not distinguishable by timing
        hashlib.scrypt(b"x", salt=b"0" * 16, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
        return False
    try:
        _, n, r, p, salt_b64, digest_b64 = stored.split("$")
        digest = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except Exception:
        return False


def password_policy_error(password: str) -> Optional[str]:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password.isdigit() or password.isalpha():
        return "Password must contain both letters and numbers."
    return None


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_access_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        # The role claim is informational only; authorization always re-reads the role from the database
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "typ": "access",
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    return payload


def new_refresh_token() -> Tuple[str, str]:
    """Returns (token, sha256 hash). Only the hash is stored."""
    token = secrets.token_urlsafe(48)
    return token, sha256_hex(token)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# Rate limiting (in-process sliding window; replace with Redis when running multiple workers)
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                retry = int(window_seconds - (now - q[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Too many attempts. Please wait and try again.",
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Encryption at rest
# ---------------------------------------------------------------------------

def _fernet() -> Fernet:
    return Fernet(settings.fernet_key)


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    try:
        return _fernet().decrypt(data)
    except InvalidToken:
        raise HTTPException(status_code=500, detail="Stored document could not be decrypted.")


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


# ---------------------------------------------------------------------------
# TOTP (RFC 6238) second factor for staff accounts
# ---------------------------------------------------------------------------

def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret_b32: str, at: Optional[float] = None, step: int = 30, digits: int = 6) -> str:
    padded = secret_b32 + "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(padded)
    counter = int((at if at is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    now = time.time()
    return any(hmac.compare_digest(totp_code(secret_b32, now + i * 30), str(code).strip()) for i in range(-window, window + 1))


# ---------------------------------------------------------------------------
# Ticket QR signatures (HMAC-SHA256 over a canonical payload)
# ---------------------------------------------------------------------------
QR_FIELDS = ("tid", "ref", "rid", "ts", "exp")


# Trip and bus the ticket was issued into. Signed whenever present, so they cannot be added, removed or altered.
QR_OPTIONAL_FIELDS = ("trp", "bus")


def _canonical(payload: dict) -> bytes:
    body = {k: payload[k] for k in QR_FIELDS}
    body.update({k: payload[k] for k in QR_OPTIONAL_FIELDS if k in payload})
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode()


def sign_ticket_payload(payload: dict) -> str:
    return hmac.new(settings.ticket_signing_secret.encode(), _canonical(payload), hashlib.sha256).hexdigest()


def build_qr_payload(ticket_id: str, reference: str, route: str, created_at: datetime, expires_at: datetime,
                     trip_id: Optional[str] = None, bus_id: Optional[str] = None) -> str:
    """QR contains only ticket identifiers, route, trip/bus ids, timestamps and a signature. No identity data."""
    payload = {
        "v": 1,
        "tid": ticket_id,
        "ref": reference,
        "rid": route,
        "ts": int(created_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if trip_id:
        payload["trp"] = trip_id
    if bus_id:
        payload["bus"] = bus_id
    payload["sig"] = sign_ticket_payload(payload)
    return json.dumps(payload, separators=(",", ":"))


def parse_and_verify_qr(raw: str) -> Tuple[Optional[dict], str]:
    """Returns (payload, error). error is '' when the signature is valid."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or any(k not in payload for k in (*QR_FIELDS, "sig")):
            return None, "MALFORMED"
    except (ValueError, TypeError):
        return None, "MALFORMED"
    expected = sign_ticket_payload(payload)
    if not hmac.compare_digest(expected, str(payload.get("sig", ""))):
        return None, "BAD_SIGNATURE"
    return payload, ""


# ---------------------------------------------------------------------------
# Short-lived signed document URLs
# ---------------------------------------------------------------------------

def sign_document_token(document_id: str, viewer_id: str, ttl_seconds: int) -> str:
    exp = int(time.time()) + ttl_seconds
    body = f"{document_id}.{viewer_id}.{exp}"
    sig = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}.{sig}".encode()).decode()


def verify_document_token(token: str, document_id: str) -> Optional[str]:
    """Returns viewer_id if the token is valid for this document and not expired."""
    try:
        doc_id, viewer_id, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().split(".")
    except Exception:
        return None
    body = f"{doc_id}.{viewer_id}.{exp}"
    expected = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if doc_id != document_id or not hmac.compare_digest(expected, sig) or int(exp) < time.time():
        return None
    return viewer_id
