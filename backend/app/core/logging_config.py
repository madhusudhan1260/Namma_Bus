import logging
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nammablr.structured")

SENSITIVE_KEYS = {"api_key", "authorization", "token", "secret", "password", "bmtc_api_key"}


def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively redacts sensitive keys to prevent credential leaks."""
    sanitized = {}
    for k, v in data.items():
        if k.lower() in SENSITIVE_KEYS or "key" in k.lower() or "secret" in k.lower() or "token" in k.lower():
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_dict(v)
        else:
            sanitized[k] = v
    return sanitized


def log_structured_event(
    event_type: str,
    details: Dict[str, Any],
    request_id: Optional[str] = None,
    latency_ms: Optional[float] = None,
    level: int = logging.INFO,
):
    """
    Logs structured JSON operational events safely without leaking credentials.
    Includes timestamp, event_type, request_id, and latency_ms.
    """
    safe_details = sanitize_dict(details)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "request_id": request_id,
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "data": safe_details,
    }
    logger.log(level, "[STRUCTURED_EVENT] %s", json.dumps(payload))
