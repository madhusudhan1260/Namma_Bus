"""Aggregate router for the Access module. Mounted by the Namma Bus backend under /api/access."""

import os
from pathlib import Path

from fastapi import APIRouter


def load_local_env() -> None:
    """Load backend/.env.access (git-ignored) for local development without overriding real env vars."""
    path = Path(__file__).resolve().parents[2] / ".env.access"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


def build_router() -> APIRouter:
    from . import config

    # Refresh the shared settings object in place (modules hold a reference to it)
    config.settings.__dict__.update(config.AccessSettings().__dict__)
    config.settings.validate()
    from . import realtime
    from .routers import admin, auth, conductor, identity, notifications, passenger, students, support, tickets

    router = APIRouter()
    router.include_router(realtime.router)
    for module in (auth, identity, students, tickets, admin, support, passenger, conductor, notifications):
        router.include_router(module.router)

    @router.get("/health", tags=["Access: Auth"])
    def access_health():
        from sqlalchemy import text

        from .db import engine
        from .providers.biometric import get_biometric_provider
        from .providers.identity import get_identity_provider

        try:
            with engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        idp, bio = get_identity_provider(), get_biometric_provider()
        return {
            "database": "OK" if db_ok else "UNAVAILABLE",
            "identity_provider": idp.name, "identity_available": idp.available(), "identity_is_development": idp.is_development,
            "biometric_provider": bio.name, "biometric_available": bio.available(), "biometric_is_development": bio.is_development,
            "development_secrets_in_use": config.settings.using_dev_secrets,
            "environment": config.settings.env,
        }

    return router
