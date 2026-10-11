import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .api.routes import router as api_router
from .api.network_routes import router as network_router
from .services.provider_factory import is_simulation_active
from .services.mock_provider import mock_provider
from .services.bmtc_provider import bmtc_provider


async def run_simulation_loop():
    """Background simulator worker updating bus positions periodically when simulated data is active."""
    try:
        while True:
            if is_simulation_active():
                mock_provider.tick_simulation()
            await asyncio.sleep(settings.simulation_tick_seconds)
    except asyncio.CancelledError:
        pass


OPENAPI_TAGS = [
    {"name": "System", "description": "Liveness probes, readiness probes, diagnostics, and system health status."},
    {"name": "Buses", "description": "Active fleet telemetry, real-time coordinates, routes, stops, dynamic ETAs, and passenger crowd predictions."},
    {"name": "Alerts", "description": "Municipal service alerts, corridor disruption notices, and maintenance bulletins."},
    {"name": "Journey", "description": "Inter-stop and corridor journey planning across Bengaluru."},
    {"name": "AI Assistant", "description": "Telemetry-grounded transit assistant providing natural-language assistance without hallucinations."},
    {"name": "Tickets", "description": "Digital transit ticketing, booking history, and fare calculation."},
    {"name": "Conductor", "description": "Conductor validation portal for digital ticket verification and passenger admittance."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup validation
    validation = settings.validate_production_config()
    logger = logging.getLogger("nammablr.startup")
    logger.info(
        "[STARTUP] NammaBlr Backend starting in '%s' environment (provider=%s, active_mode=%s)",
        validation["environment"],
        validation["transit_provider_configured"],
        validation["active_mode"],
    )
    for w in validation.get("warnings", []):
        logger.warning("[CONFIG_WARNING] %s", w)

    # Auto-import static GTFS if configured
    if settings.gtfs_static_dir:
        from .services.gtfs.import_static import GTFSStaticImporter
        GTFSStaticImporter.startup_import()

    # Startup background workers. The legacy corridor simulator can be switched off entirely
    # (SIMULATION_ENABLED=false) when the app runs on real BMTC data only.
    simulation_enabled = os.getenv("SIMULATION_ENABLED", "true").lower() != "false"
    sim_task = asyncio.create_task(run_simulation_loop()) if simulation_enabled else None
    if not simulation_enabled:
        logger.info("Legacy corridor simulator disabled (SIMULATION_ENABLED=false)")
    if bmtc_provider.is_configured:
        bmtc_provider.start_polling()
    # Pre-load OpenStreetMap facilities around major bus stations (slow free servers) and refresh daily,
    # so the Facilities screen answers instantly from cache.
    async def _warm_facilities():
        from .api.network_routes import network_facilities

        while True:
            try:
                await network_facilities()
            except Exception as exc:  # never let a busy OSM server affect the API
                logger.warning("[FACILITIES] warm-up failed: %s", exc)
            await asyncio.sleep(6 * 3600)

    facilities_task = asyncio.create_task(_warm_facilities())
    yield
    facilities_task.cancel()
    # Shutdown: stop bmtc poller and cancel simulation background worker
    bmtc_provider.stop_polling()
    if sim_task:
        sim_task.cancel()
        try:
            await sim_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="NammaBlr — Bengaluru Transit Intelligence API",
    description=(
        "Production-ready backend REST service powering the NammaBlr transit ecosystem. "
        "Provides authorized BMTC GTFS / GTFS-RT feed ingestion with automatic corridor simulator fallback, "
        "telemetry-grounded AI journey assistance, bayesian crowd prediction, and offline-resilient digital ticketing."
    ),
    version=settings.version,
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for Mobile & Web clients (using environment-configured explicit origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.effective_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Attach Security and Observability Middleware
from .core.middleware import SecurityAndObservabilityMiddleware
app.add_middleware(SecurityAndObservabilityMiddleware)

# Register API routes
app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(network_router, prefix=settings.api_prefix)

# Access module (accounts, RBAC, eligibility, student passes, college/conductor/admin portals).
# Mounted only when its PostgreSQL database is configured, so existing features are unaffected otherwise.
from .access.api import build_router as _build_access_router, load_local_env as _load_access_env  # noqa: E402

_load_access_env()
if os.getenv("ACCESS_DATABASE_URL"):
    app.include_router(_build_access_router(), prefix=f"{settings.api_prefix}/access")
    logging.getLogger("nammablr").info("Access module mounted at %s/access", settings.api_prefix)


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Welcome to NammaBlr Transit Backend",
        "docs_url": "/docs",
        "health_url": "/api/health",
        "buses_url": "/api/buses",
    }
