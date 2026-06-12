from contextlib import asynccontextmanager
from typing import Dict
from fastapi import FastAPI
from app.core.config import settings
from app.core.db import init_db
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown events for the FastAPI application.
    Initializes SQLModel SQLite database tables on startup.
    """
    await init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
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
