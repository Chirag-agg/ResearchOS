from contextlib import asynccontextmanager
from typing import Dict
import sys
import asyncio

if sys.platform == "win32":
    # Explicitly configure Windows Proactor event loop to support subprocesses (required by Playwright)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from app.core.config import settings
from app.core.db import init_db, async_session_maker
from app.api.v1.router import api_router
from app.events.bus import EventBus
from app.events.logger import EventLogger
from app.services.telemetry import TelemetryService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown events for the FastAPI application.
    Initializes database tables, creates the EventBus singleton, and
    registers the EventLogger subscriber for automatic event persistence.
    """
    # Initialize database
    await init_db()

    # Initialize event infrastructure
    event_bus = EventBus()
    event_logger = EventLogger(session_maker=async_session_maker)
    event_bus.subscribe_all(event_logger.handle_event)

    # Store EventBus in app state for dependency injection
    app.state.event_bus = event_bus

    # Initialize telemetry service
    app.state.telemetry_service = TelemetryService(session_maker=async_session_maker)

    yield


from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
)

# Add CORS Middleware to allow requests from frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> Dict[str, str]:
    """
    Root endpoint offering basic API information and documentation link.
    """
    return {
        "project": settings.PROJECT_NAME,
        "status": "active",
        "docs_url": "/docs",
    }


@app.get("/health")
async def root_health_check() -> Dict[str, str]:
    """
    Root-level health check endpoint for proxy and load-balancer heartbeat checks.
    """
    return {"status": "healthy"}


# Versioned API routes
app.include_router(api_router, prefix=settings.API_V1_STR)

# Expose research routes directly at the root level to support POST /research
from app.api.v1.endpoints import research
app.include_router(research.router)

