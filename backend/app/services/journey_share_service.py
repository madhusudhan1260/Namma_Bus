import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from ..models.safety import (
    JourneyShareResponse,
    JourneyShareStartRequest,
    JourneyShareStatusResponse,
    JourneyShareStopRequest,
    ShareState,
)
from .active_journey_service import active_journey_service
from .metrics_service import metrics_service

logger = logging.getLogger("nammablr.journey_share_service")

# Secret key for signing share tokens (default fallback for local/dev)
SECRET_KEY = os.environ.get("JOURNEY_SHARE_SECRET_KEY", "nammablr-secure-share-key-v41-prod-grade")


class JourneyShareService:
    """
    Journey Share Service for Phase 41 Smart Commuter Safety.
    Generates time-bounded HMAC-signed sharing tokens that convey ONLY verified
    public route, stop, and journey identifiers. Strictly never includes passenger PII,
    biometrics, passwords, or personal credentials.
    """

    DEFAULT_DISCLOSURE = "Your journey location is not shared automatically."
    CONFIRMATION_TEXT = "Journey sharing is active only after explicit user confirmation."

    def __init__(self):
        # journey_id -> dict with keys: share_token, state, duration_minutes, expires_at, created_at
        self._shares: Dict[str, dict] = {}

    def _sign_payload(self, payload_bytes: bytes) -> str:
        sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")

    def generate_token(self, journey_id: str, route_number: Optional[str], destination: Optional[str], expires_at: datetime) -> str:
        payload = {
            "jid": journey_id,
            "rt": route_number or "",
            "dst": destination or "",
            "exp": int(expires_at.timestamp()),
        }
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
        signature = self._sign_payload(payload_bytes)
        return f"{payload_b64}.{signature}"

    def verify_token(self, token: str) -> Tuple[bool, Optional[dict], str]:
        """
        Verifies HMAC signature and expiration of a journey share token.
        Returns (is_valid, payload_dict_or_none, reason_string).
        """
        try:
            parts = token.split(".")
            if len(parts) != 2:
                return False, None, "Invalid token format"

            payload_b64, signature = parts[0], parts[1]
            # Pad base64 if needed
            pad_len = 4 - (len(payload_b64) % 4)
            if pad_len != 4:
                payload_b64 += "=" * pad_len

            payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
            expected_sig = self._sign_payload(payload_bytes)

            if not hmac.compare_digest(signature, expected_sig):
                return False, None, "Signature mismatch"

            data = json.loads(payload_bytes.decode("utf-8"))
            now_ts = int(time.time())
            if data.get("exp", 0) < now_ts:
                return False, data, "Token expired"

            return True, data, "Valid"
        except Exception as e:
            logger.warning(f"Error verifying token: {e}")
            return False, None, f"Malformed token: {str(e)}"

    async def start_share(self, req: JourneyShareStartRequest) -> JourneyShareResponse:
        """
        Starts explicit journey sharing with time-bound duration (15, 30, or 60 min).
        Requires explicit user action (never automatic).
        """
        active = await active_journey_service.get_active_journey()
        if not active:
            active = active_journey_service._active_journey

        now = datetime.now(timezone.utc)
        duration = req.duration_minutes if req.duration_minutes in [15, 30, 60] else 30
        expires_at = now + timedelta(minutes=duration)

        route_num = active.route_number if active else None
        dest = active.destination if active else None

        token = self.generate_token(req.journey_id, route_num, dest, expires_at)

        self._shares[req.journey_id] = {
            "token": token,
            "state": ShareState.ACTIVE.value,
            "duration_minutes": duration,
            "expires_at": expires_at,
            "created_at": now,
        }

        metrics_service.journey_shares_started += 1

        return JourneyShareResponse(
            journey_id=req.journey_id,
            share_token=token,
            share_state=ShareState.ACTIVE.value,
            duration_minutes=duration,
            expires_at=expires_at,
            route_number=route_num,
            destination=dest,
            data_source="simulated" if not (active and active.telemetry_reliable) else "realtime",
            disclosure=self.DEFAULT_DISCLOSURE,
            confirmation_text=self.CONFIRMATION_TEXT,
        )

    async def stop_share(self, req: JourneyShareStopRequest) -> JourneyShareResponse:
        """
        Immediately halts active journey sharing upon commuter request.
        """
        share = self._shares.get(req.journey_id)
        active = await active_journey_service.get_active_journey()
        if not active:
            active = active_journey_service._active_journey

        now = datetime.now(timezone.utc)

        if share:
            share["state"] = ShareState.CANCELLED.value
            token = share["token"]
            expires_at = share["expires_at"]
            duration = share.get("duration_minutes", 30)
        else:
            token = ""
            expires_at = now
            duration = 0

        metrics_service.journey_shares_stopped += 1

        return JourneyShareResponse(
            journey_id=req.journey_id,
            share_token=token,
            share_state=ShareState.CANCELLED.value,
            duration_minutes=duration,
            expires_at=expires_at,
            route_number=active.route_number if active else None,
            destination=active.destination if active else None,
            data_source="simulated" if not (active and active.telemetry_reliable) else "realtime",
            disclosure=self.DEFAULT_DISCLOSURE,
            confirmation_text=self.CONFIRMATION_TEXT,
        )

    async def get_share_status(self, journey_id: str) -> JourneyShareStatusResponse:
        """
        Retrieves the current sharing status for a given journey.
        Handles automated expiration if time threshold is crossed.
        """
        share = self._shares.get(journey_id)
        active = await active_journey_service.get_active_journey()
        if not active:
            active = active_journey_service._active_journey

        now = datetime.now(timezone.utc)

        if not share:
            return JourneyShareStatusResponse(
                journey_id=journey_id,
                share_state=ShareState.INACTIVE.value,
                share_token=None,
                expires_at=None,
                remaining_minutes=0,
                route_number=active.route_number if active else None,
                current_stop=active.current_stop if active else None,
                destination=active.destination if active else None,
                last_updated=now,
                data_source="simulated" if not (active and active.telemetry_reliable) else "realtime",
                disclosure=self.DEFAULT_DISCLOSURE,
            )

        # Check for expiration
        state = share["state"]
        expires_at = share["expires_at"]
        rem_seconds = (expires_at - now).total_seconds()
        remaining_minutes = max(0, int(rem_seconds // 60))

        if state == ShareState.ACTIVE.value and rem_seconds <= 0:
            state = ShareState.EXPIRED.value
            share["state"] = ShareState.EXPIRED.value
            metrics_service.journey_shares_expired += 1

        return JourneyShareStatusResponse(
            journey_id=journey_id,
            share_state=state,
            share_token=share["token"] if state == ShareState.ACTIVE.value else None,
            expires_at=expires_at,
            remaining_minutes=remaining_minutes if state == ShareState.ACTIVE.value else 0,
            route_number=active.route_number if active else None,
            current_stop=active.current_stop if active else None,
            destination=active.destination if active else None,
            last_updated=now,
            data_source="simulated" if not (active and active.telemetry_reliable) else "realtime",
            disclosure=self.DEFAULT_DISCLOSURE,
        )

    def is_share_active(self, journey_id: str) -> bool:
        share = self._shares.get(journey_id)
        if not share or share["state"] != ShareState.ACTIVE.value:
            return False
        now = datetime.now(timezone.utc)
        if (share["expires_at"] - now).total_seconds() <= 0:
            share["state"] = ShareState.EXPIRED.value
            metrics_service.journey_shares_expired += 1
            return False
        return True

    def reset(self):
        self._shares.clear()


journey_share_service = JourneyShareService()
