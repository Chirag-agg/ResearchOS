from fastapi import APIRouter, Depends, status
from app.services.llm import LLMService
from app.api.deps import get_llm_service

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """
    Heartbeat health check endpoint to verify that the service is running.
    """
    return {"status": "healthy"}


@router.get("/health/llm")
async def llm_health_check(
    llm_service: LLMService = Depends(get_llm_service)
) -> dict[str, str]:
    """
    Checks the connectivity status of the local Ollama instance.
    """
    is_healthy = await llm_service.check_health()
    if is_healthy:
        return {"status": "healthy", "ollama": "online"}
    return {"status": "unhealthy", "ollama": "offline"}
