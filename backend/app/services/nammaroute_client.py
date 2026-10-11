"""
NammaRoute network client — the complete BMTC route network (PostgreSQL + Prisma, served by the
NammaRoute backend) exposed inside ನಮ್ಮ Bus through /api/network/*.

- NAMMAROUTE_API_URL (default http://localhost:4000/api) — never exposed to the app client.
- Short TTL cache + in-flight de-duplication: many app users share one upstream request.
- When NammaRoute is unreachable, calls raise NetworkUnavailable; nothing is substituted.
- Realtime vehicles are whatever the NammaRoute backend reports. They are never generated here.
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("nammablr.nammaroute")

NETWORK_UNAVAILABLE_MESSAGE = "BMTC route network service is unavailable right now."


class NetworkUnavailable(Exception):
    pass


class NetworkNotFound(Exception):
    pass


class NammaRouteClient:
    def __init__(self, base_url: Optional[str] = None, timeout_s: float = 20.0):
        self.base_url = (base_url or os.getenv("NAMMAROUTE_API_URL", "http://localhost:4000/api")).rstrip("/")
        self.timeout_s = timeout_s
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._inflight: Dict[str, asyncio.Future] = {}
        self.upstream_requests = 0
        self.transport: Optional[httpx.AsyncBaseTransport] = None  # tests inject a MockTransport
        self.last_error: Optional[str] = None

    def reset(self):
        self._cache.clear()
        self._inflight.clear()
        self.upstream_requests = 0
        self.last_error = None

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None, ttl: float = 30.0) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        key = path + "?" + "&".join(f"{k}={clean[k]}" for k in sorted(clean))
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            data = await self._fetch(path, clean)
            self._cache[key] = (time.time(), data)
            fut.set_result(data)
            return data
        except Exception as exc:
            fut.set_exception(exc)
            fut.exception()  # mark retrieved so concurrent waiters get it without warnings
            raise
        finally:
            self._inflight.pop(key, None)

    async def _fetch(self, path: str, params: Dict[str, Any]) -> Any:
        self.upstream_requests += 1
        kwargs: Dict[str, Any] = {"timeout": self.timeout_s}
        if self.transport is not None:
            kwargs["transport"] = self.transport
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                res = await client.get(f"{self.base_url}{path}", params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.last_error = type(exc).__name__
            logger.warning("[NETWORK] NammaRoute unreachable for %s (%s)", path, type(exc).__name__)
            raise NetworkUnavailable(NETWORK_UNAVAILABLE_MESSAGE) from exc
        if res.status_code == 404:
            raise NetworkNotFound(path)
        if res.status_code >= 400:
            self.last_error = f"HTTP_{res.status_code}"
            logger.warning("[NETWORK] NammaRoute returned HTTP %d for %s", res.status_code, path)
            raise NetworkUnavailable(NETWORK_UNAVAILABLE_MESSAGE)
        try:
            body = res.json()
        except ValueError as exc:
            self.last_error = "MALFORMED_RESPONSE"
            raise NetworkUnavailable(NETWORK_UNAVAILABLE_MESSAGE) from exc
        self.last_error = None
        return body


nammaroute_client = NammaRouteClient()
