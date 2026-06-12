from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """
    Heartbeat health check endpoint to verify that the service is running.
    """
    return {"status": "healthy"}
