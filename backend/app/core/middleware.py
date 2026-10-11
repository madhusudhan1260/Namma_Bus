import time
import uuid
import logging
from collections import defaultdict
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings
from ..services.metrics_service import metrics_service

logger = logging.getLogger("nammablr.access")

# Simple in-memory rate-limiter: client_ip -> [timestamps]
_ip_request_timestamps = defaultdict(list)


class SecurityAndObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Production-safe middleware that handles:
    1. Request correlation ID (X-Request-ID)
    2. Response timing header (X-Response-Time-Ms)
    3. Metrics recording for observability
    4. Safe rate limiting protection on POST endpoints
    5. Request size limitation
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start_time = time.time()

        # 1. Check Request Size
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.max_request_body_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": "Payload Too Large: Request entity exceeds permitted maximum."},
                headers={"X-Request-ID": request_id},
            )

        # 2. Rate Limiting for mutating/expensive endpoints
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - 60.0

        # Phase 41: auth/identity endpoints use a separate bucket so login attempts cannot exhaust
        # (or be masked by) the ticketing/AI allowance.
        is_auth_path = any(
            path in request.url.path
            for path in ["/api/auth/register", "/api/auth/login", "/api/identity/verification"]
        )
        if request.method == "POST" and (is_auth_path or any(
            path in request.url.path
            for path in ["/api/ai/chat", "/api/journey/search", "/api/tickets", "/api/payment"]
        )):
            bucket = f"{client_ip}:auth" if is_auth_path else client_ip
            timestamps = [ts for ts in _ip_request_timestamps[bucket] if ts > window_start]
            _ip_request_timestamps[bucket] = timestamps

            if len(timestamps) >= settings.rate_limit_per_minute:
                logger.warning(
                    "[SECURITY] Rate limit exceeded for IP %s on %s",
                    client_ip,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests: Rate limit exceeded. Please try again shortly."},
                    headers={"X-Request-ID": request_id, "Retry-After": "60"},
                )
            _ip_request_timestamps[bucket].append(now)

        # 3. Process Request
        try:
            response: Response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            metrics_service.record_request(request.url.path, duration_ms)
            logger.error(
                "[HTTP] %s %s ERROR after %.1fms (req_id=%s): %s",
                request.method,
                request.url.path,
                duration_ms,
                request_id,
                exc,
            )
            raise exc

        duration_ms = round((time.time() - start_time) * 1000, 2)
        metrics_service.record_request(request.url.path, duration_ms)

        # 4. Attach Security & Tracing Headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

        from .logging_config import log_structured_event
        log_structured_event(
            event_type="http_request",
            details={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "client_ip": client_ip,
            },
            request_id=request_id,
            latency_ms=duration_ms,
        )

        return response
