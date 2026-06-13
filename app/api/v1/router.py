from fastapi import APIRouter
from app.api.v1.endpoints import health, research, sessions, events, claims, validation, understanding, knowledge, gap, followup, iterative_research, strategy, telemetry

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(research.router)
api_router.include_router(sessions.router)
api_router.include_router(events.router)
api_router.include_router(claims.router)
api_router.include_router(validation.router)
api_router.include_router(understanding.router)
api_router.include_router(knowledge.router)
api_router.include_router(gap.router)
api_router.include_router(followup.router)
api_router.include_router(iterative_research.router)
api_router.include_router(strategy.router)
api_router.include_router(telemetry.router)
